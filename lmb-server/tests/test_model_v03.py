"""Конфигурация v0.3 с нормализацией (редакция 2), CAIDE через анкету, неизменность редакций."""
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


def test_calculation_uses_revision_2_and_blocks_integral(world):
    d = world["doctor_a"]
    eid = visit(d)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": ANSWERS})
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    assert run["model_version"] == "v0.3" and run["model_revision"] == 2
    res = run["result"]
    caide = next(i for i in res["indices"] if i["code"] == "caide")
    assert caide["status"] == "calculated" and caide["value"] == 4.0          # 55 лет → 4, остальное 0
    dom = {x["domain"]: x for x in res["domains"]}
    for name in ("metabolic", "renal", "hepatic", "inflammation", "brain"):
        assert dom[name]["status"] == "calculated", (name, dom[name])
    assert dom["cardio"]["status"] == "model_not_configured"                 # SCORE2 не сверен полностью
    assert dom["bone"]["status"] != "calculated"                             # нет FRAX
    assert run["status"] == "blocked" and run["bioage_years"] is None
    assert any("target_population" in r for r in res["blocking_reasons"])
    assert res["zscores"]["acr"]["input"] == "acr" and res["zscores"]["egfr"]["z_raw"] is not None


def test_model_versions_immutable_revisions(world, admin_engine):
    rows = world["owner_a"].get("/model-versions").json()
    v03 = [r for r in rows if r["label"] == "v0.3"]
    assert [(r["revision"], r["state"]) for r in v03] == [(1, "archived"), (2, "draft")]
    assert v03[1]["config_gaps"] == ["target_population"] and v03[1]["usage_permission"] == "none"
    assert v03[1]["validation_status"] == "not_validated" and "11.10.2026" in v03[1]["source_note"]
    with admin_engine.connect() as c:
        n = c.execute(text("select count(*) from model_version where label = 'v0.3'")).scalar()
    assert n == 2


def test_old_run_reproducible_after_new_revision(world):
    """Расчёт хранит ссылку на свою редакцию: повтор даёт тот же результат."""
    d = world["doctor_a"]
    eid = visit(d)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": ANSWERS})
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    rep = d.post(f"/calculations/{run['calculation_id']}/reproduce").json()
    assert rep == {"identical": True, "same_engine_version": True, "same_model_config": True}
