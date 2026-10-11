"""Конфигурация v0.3 (редакция 3 — исследовательский режим), CAIDE через анкету, неизменность редакций."""
from sqlalchemy import text

from tests.conftest import PATIENT

OBS = [("height_cm", 165, "cm"), ("weight_kg", 68, "kg"), ("waist_cm", 82, "cm"), ("sbp_mmhg", 128, "mmHg"),
       ("glucose_fasting", 5.2, "mmol/L"), ("insulin_fasting", 8, "uU/mL"), ("tg", 1.3, "mmol/L"),
       ("tc", 5.4, "mmol/L"), ("hdl", 1.5, "mmol/L"), ("creatinine_serum", 70, "umol/L"),
       ("u_albumin", 20, "mg/L"), ("u_creatinine", 10, "mmol/L"), ("ast", 22, "U/L"), ("alt", 20, "U/L"),
       ("platelets", 240, "10^9/L"), ("neutrophils_abs", 3.5, "10^9/L"), ("lymphocytes_abs", 2.0, "10^9/L")]
ANSWERS = {"fasting_status": "yes", "insulin_therapy": "no", "diabetes": "no", "creatinine_idms": "yes",
           "acute_kidney_change": "no", "acute_liver_condition": "no", "acute_infection": "no",
           "smoking_current": "no", "ascvd": "no", "ckd_known": "no", "fh": "no",
           "very_high_single_risk_factor": "no", "education_years": "14", "physical_activity_caide": "active"}


def visit(d, birth="1971-03-01"):
    pt = d.post("/patients", json={**PATIENT, "birth_date": birth}).json()
    eid = d.post(f"/patients/{pt['id']}/encounters", json={"encounter_date": "2026-10-10"}).json()["id"]
    for code, v, u in OBS:
        assert d.post(f"/encounters/{eid}/observations", json={"code": code, "value": v, "unit": u}).status_code == 201
    return eid


def test_education_and_activity_validation(world):
    d = world["doctor_a"]
    eid = visit(d)
    for bad in ("9.5", "-1", "31", "abc", "07"):
        assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"education_years": bad}}).status_code == 422
    assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"physical_activity_caide": "sometimes"}}).status_code == 422
    assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"education_years": "unknown"}}).status_code == 200
    q = d.get(f"/encounters/{eid}/questionnaire").json()
    assert q["physical_activity_caide"]["answer"] == "unknown"     # без ответа — «неизвестно», не «неактивен»


def test_catalog_has_integer_item(world):
    cat = world["doctor_a"].get("/catalog").json()
    items = {i["code"]: i for g in cat["questionnaire_groups"] for i in g["items"]}
    assert items["education_years"]["kind"] == "integer" and items["education_years"]["range"] == [0, 30]
    assert items["physical_activity_caide"]["options"] == ["active", "inactive", "unknown"]


def test_calculation_uses_revision_3_and_blocks_integral(world):
    d = world["doctor_a"]
    eid = visit(d)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": ANSWERS})
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    assert run["model_version"] == "v0.3" and run["model_revision"] == 3
    res = run["result"]
    caide = next(i for i in res["indices"] if i["code"] == "caide")
    assert caide["status"] == "calculated" and caide["value"] == 4.0          # 55 лет → 4, остальное 0
    dom = {x["domain"]: x for x in res["domains"]}
    for name in ("metabolic", "renal", "hepatic", "inflammation", "brain"):
        assert dom[name]["status"] == "calculated", (name, dom[name])
    assert dom["cardio"]["status"] == "calculated"                           # SCORE2 сверен 30/30 (11.10.2026)
    assert dom["bone"]["status"] != "calculated"                             # нет FRAX
    assert run["status"] == "blocked" and run["bioage_years"] is None
    assert any("target_population" in r for r in res["blocking_reasons"])
    assert res["zscores"]["acr"]["input"] == "acr" and res["zscores"]["egfr"]["z_raw"] is not None
    # исследовательский расчёт хранится в результате, но без Bone не выполняется (пропуск не заменяется)
    assert res["research"]["status"] == "blocked" and res["research"]["bioage_years"] is None
    assert any(r.startswith("Домен bone") for r in res["research"]["reasons"])


def test_model_versions_immutable_revisions(world, admin_engine):
    rows = world["owner_a"].get("/model-versions").json()
    v03 = [r for r in rows if r["label"] == "v0.3"]
    assert [(r["revision"], r["state"]) for r in v03] == [(1, "archived"), (2, "archived"), (3, "draft")]
    assert v03[1]["config_sha256"].startswith("eb079142")                  # редакция 2 заморожена снимком
    assert v03[2]["config_gaps"] == ["target_population"] and v03[2]["usage_permission"] == "research_only"
    assert v03[2]["validation_status"] == "not_validated" and "LMB_Claude_Decisions" in v03[2]["source_note"]
    with admin_engine.connect() as c:
        n = c.execute(text("select count(*) from model_version where label = 'v0.3'")).scalar()
    assert n == 3


def test_active_revision_matches_engine_config():
    """Изменение файла конфигурации движка требует новой редакции (миграции со снимком)."""
    from pathlib import Path
    from lmb_engine.model import config_path, config_sha256, load_config
    snap = Path(__file__).resolve().parents[1] / "migrations" / "snapshots" / "model_v0.3_rev3.json"
    assert config_sha256(load_config(str(snap))) == config_sha256(load_config(config_path("model_v0.3.json")))


def test_research_with_manual_frax_and_patient_policy(world):
    """С ручным FRAX все семь доменов есть: исследовательский итог считается, клинический — нет;
    пациентская выдача по умолчанию исследовательского блока не содержит."""
    from lmb_server.report_policy import patient_result
    d = world["doctor_a"]
    eid = visit(d)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": ANSWERS})
    r = d.post(f"/encounters/{eid}/frax-manual", json={
        "frax_major_10y_pct": 6.5, "frax_hip_10y_pct": 1.0, "with_bmd": False, "calculated_on": "2026-10-10",
        "national_model": "Kazakhstan", "source_note": "Синтетический тест: ручной ввод"})
    assert r.status_code == 201, r.text
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    res = run["result"]
    assert run["status"] == "blocked" and run["bioage_years"] is None
    rs = res["research"]
    assert rs["status"] == "calculated", rs["reasons"]
    assert rs["mode"] == "local_synthetic" and rs["model_config_sha256"] == run["model_config_sha256"]
    assert abs(rs["bioage_years"] - (rs["delta_years"] + 55)) < 1e-9          # 1971-03-01 → 55 полных лет
    assert "research" not in patient_result(res) and "research" in patient_result(res, include_research=True)
    assert "research" in res                                               # исходный результат не изменён


def test_old_run_reproducible_after_new_revision(world):
    """Расчёт хранит ссылку на свою редакцию: повтор даёт тот же результат."""
    d = world["doctor_a"]
    eid = visit(d)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": ANSWERS})
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    rep = d.post(f"/calculations/{run['calculation_id']}/reproduce").json()
    assert rep == {"identical": True, "same_engine_version": True, "same_model_config": True}


def test_phenoage_control_via_server(world):
    """Показатели PhenoAge принимаются сервером (миграция 0008) и дают контрольный индекс, не входящий в модель."""
    d = world["doctor_a"]
    eid = visit(d)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": ANSWERS})
    for code, v, u in [("wbc", 6.0, "10^9/L"), ("mcv", 90, "fL"), ("rdw", 13, "%"), ("albumin_serum", 4.5, "g/dL"),
                       ("crp", 1.0, "mg/L"), ("alp", 70, "U/L")]:
        r = d.post(f"/encounters/{eid}/observations", json={"code": code, "value": v, "unit": u})
        assert r.status_code == 201, r.text
    res = d.post(f"/encounters/{eid}/calculations", json={}).json()["result"]
    ph = next(i for i in res["indices"] if i["code"] == "phenoage")
    assert ph["status"] == "calculated" and ph["unit"] == "years" and 20 < ph["value"] < 90
    assert ph["extra"]["role"] == "control_reference"
    from lmb_server.catalog import observation_definitions
    defs = {o["code"]: o for o in observation_definitions()}
    assert defs["crp"]["in_model_inputs"] is False and defs["glucose_fasting"]["in_model_inputs"] is True
