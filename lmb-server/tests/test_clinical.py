"""Карточка, визит, наблюдения с редакциями, анкета, расчёт и воспроизводимость."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import PATIENT

LAB = [("glucose_fasting", 5.0, "mmol/L"), ("insulin_fasting", 9.0, "uU/mL"), ("tg", 1.5, "mmol/L"),
       ("hdl", 1.5, "mmol/L"), ("creatinine_serum", 53.04, "umol/L"), ("height_cm", 170, "cm"),
       ("waist_cm", 85, "cm"), ("weight_kg", 70, "kg")]
CLEAN = {"fasting_status": "yes", "insulin_therapy": "no", "diabetes": "no", "creatinine_idms": "yes",
         "acute_kidney_change": "no"}


def add(d, eid, code, value, unit, **kw):
    return d.post(f"/encounters/{eid}/observations", json={"code": code, "value": value, "unit": unit, **kw})


# ---- карточка
def test_iin_encrypted_and_searchable(world, patient_flow, admin_engine):
    d, iin = patient_flow["doctor"], patient_flow["iin"]
    p = d.get(f"/patients/{patient_flow['patient']['id']}").json()
    assert p["iin_masked"].endswith(iin[-4:]) and iin not in p["iin_masked"]
    with admin_engine.begin() as c:
        row = c.execute(text("select iin_enc, phone_enc from patient where id = :i"),
                        {"i": patient_flow["patient"]["id"]}).one()
    assert iin not in row.iin_enc and "701" not in row.phone_enc
    found = d.get(f"/patients?iin={iin}").json()
    assert [x["id"] for x in found] == [patient_flow["patient"]["id"]]
    assert d.post("/patients", json={**PATIENT, "iin": iin}).status_code == 409


def test_patient_idempotency(world):
    d = world["doctor_a"]
    k = {"Idempotency-Key": uuid.uuid4().hex}
    a = d.post("/patients", json=PATIENT, headers=k).json()
    b = d.post("/patients", json=PATIENT, headers=k).json()
    assert a["id"] == b["id"]


def test_patient_update_optimistic_lock(world, patient_flow):
    d, pid = patient_flow["doctor"], patient_flow["patient"]["id"]
    body = {"phone": "+7 702 111 11 11", "change_reason": "Новый номер"}
    assert d.patch(f"/patients/{pid}", json=body, headers={"If-Match": "99"}).status_code == 412
    r = d.patch(f"/patients/{pid}", json=body, headers={"If-Match": "1"})
    assert r.status_code == 200 and r.json()["version"] == 2


def test_invalid_iin_rejected(world):
    assert world["doctor_a"].post("/patients", json={**PATIENT, "iin": "123"}).status_code == 422


# ---- наблюдения
def test_observation_rules(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    r = add(d, eid, "tg", 1.5, "mmol/L")
    assert r.status_code == 201 and r.json()["review_status"] == "confirmed" and r.json()["revision"] == 1
    assert add(d, eid, "tg", 1.6, "mmol/L").status_code == 409            # второй раз — только редакцией
    assert add(d, eid, "tg", 1.6, "furlong").status_code == 422           # единица вне справочника
    assert add(d, eid, "unknown_code", 1, "x").status_code == 422
    assert add(d, eid, "insulin_fasting", 62, "pmol/L").status_code == 201  # сохраняется, движок отклонит
    r = add(d, eid, "u_albumin", None, None)
    assert r.status_code == 201 and r.json()["value"] is None             # отсутствие числа — null


def test_observation_revision_keeps_history(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    chain = add(d, eid, "tg", 1.5, "mmol/L").json()["chain_id"]
    upd = {"value": 1.7, "unit": "mmol/L", "change_reason": "Опечатка при вводе"}
    assert d.patch(f"/observations/{chain}", json=upd).status_code == 422          # нет If-Match
    assert d.patch(f"/observations/{chain}", json=upd, headers={"If-Match": "5"}).status_code == 412
    assert d.patch(f"/observations/{chain}", json={"value": 1.7, "unit": "mmol/L"},
                   headers={"If-Match": "1"}).status_code == 422                    # нет причины
    r = d.patch(f"/observations/{chain}", json=upd, headers={"If-Match": "1"})
    assert r.status_code == 200 and r.json()["revision"] == 2
    hist = d.get(f"/encounters/{eid}/observations?history=true").json()
    tg = [o for o in hist if o["code"] == "tg"]
    assert [o["value"] for o in tg] == [1.5, 1.7] and [o["is_current"] for o in tg] == [False, True]
    assert len([o for o in d.get(f"/encounters/{eid}/observations").json() if o["code"] == "tg"]) == 1


def test_db_requires_reason_for_revision(world, admin_engine):
    with pytest.raises(Exception, match="ck_observation_reason"):
        with admin_engine.begin() as c:
            c.execute(text("insert into observation (id, clinic_id, encounter_id, definition_code, chain_id, "
                           "revision, is_current, qualifier, source, review_status, created_by) "
                           "select gen_random_uuid(), clinic_id, id, 'tg', gen_random_uuid(), 2, true, 'eq', "
                           "'manual', 'confirmed', doctor_id from encounter limit 1"))


def test_import_needs_review(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    o = add(d, eid, "weight_kg", 80, "kg", source="import").json()
    assert o["review_status"] == "pending"
    r = d.post(f"/observations/{o['chain_id']}/review", json={"decision": "confirm"}, headers={"If-Match": "1"})
    assert r.json()["review_status"] == "confirmed"
    assert d.post(f"/observations/{o['chain_id']}/review", json={"decision": "confirm"},
                  headers={"If-Match": "1"}).status_code == 409


# ---- анкета
def test_questionnaire_unknown_by_default_and_versioned(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    q = d.get(f"/encounters/{eid}/questionnaire").json()
    assert q["smoking_current"]["answer"] == "unknown" and q["smoking_current"]["answered"] is False
    assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"smoking_current": "maybe"}}).status_code == 422
    assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"bogus": "yes"}}).status_code == 422
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"smoking_current": "no"}})
    q = d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"smoking_current": "yes"}}).json()
    assert q["smoking_current"]["answer"] == "yes"


# ---- расчёт
def _fill(d, eid):
    for code, v, u in LAB:
        assert add(d, eid, code, v, u).status_code == 201
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": CLEAN})


def test_calculation_end_to_end(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    _fill(d, eid)
    r = d.post(f"/encounters/{eid}/calculations", json={"model_version": "v0.3"})
    assert r.status_code == 201
    run = r.json()
    idx = {i["code"]: i for i in run["result"]["indices"]}
    assert idx["homa_ir"]["value"] == pytest.approx(2.0) and idx["homa_ir"]["status"] == "calculated"
    assert idx["whtr"]["value"] == pytest.approx(0.5)
    assert idx["aip"]["value"] == pytest.approx(0.0)
    assert idx["egfr_ckdepi_cr_2021"]["value"] == pytest.approx(109.283 * 0.9938 ** 2, abs=1e-3)  # ж, 52 года
    assert run["status"] == "blocked" and run["bioage_years"] is None
    assert run["engine_version"] and run["model_config_sha256"]


def test_calc_uses_age_on_encounter_date(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    add(d, eid, "creatinine_serum", 88.4, "umol/L")
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": CLEAN})
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    egfr = next(i for i in run["result"]["indices"] if i["code"] == "egfr_ckdepi_cr_2021")
    # рождение 15.03.1974, визит 10.10.2026 → 52 полных года; женщина, креатинин 1,0 мг/дл
    from lmb_engine.indices import egfr_ckdepi_cr_2021
    import datetime as dt
    from lmb_engine.core import Encounter, Measurement, Sex
    ref = egfr_ckdepi_cr_2021(Encounter(dt.date(1974, 3, 15), dt.date(2026, 10, 10), Sex.FEMALE,
                                        {"creatinine_serum": Measurement(88.4, "umol/L")},
                                        {"creatinine_idms": "yes", "acute_kidney_change": "no"}))
    assert egfr["value"] == pytest.approx(ref.value, abs=1e-12)


def test_pending_import_gives_awaiting_review(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    add(d, eid, "height_cm", 170, "cm")
    add(d, eid, "weight_kg", 80, "kg", source="import")
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    bmi = next(i for i in run["result"]["indices"] if i["code"] == "bmi")
    assert bmi["status"] == "awaiting_review"


def test_revision_creates_new_snapshot_and_old_run_reproducible(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    _fill(d, eid)
    run1 = d.post(f"/encounters/{eid}/calculations", json={}).json()
    run1b = d.post(f"/encounters/{eid}/calculations", json={}).json()
    assert run1["snapshot_id"] == run1b["snapshot_id"]        # те же входы — тот же снимок
    chain = next(o for o in d.get(f"/encounters/{eid}/observations").json() if o["code"] == "tg")["chain_id"]
    d.patch(f"/observations/{chain}", json={"value": 2.0, "unit": "mmol/L", "change_reason": "Пересдача"},
            headers={"If-Match": "1"})
    run2 = d.post(f"/encounters/{eid}/calculations", json={}).json()
    assert run2["snapshot_id"] != run1["snapshot_id"]
    aip1 = next(i for i in run1["result"]["indices"] if i["code"] == "aip")["value"]
    aip2 = next(i for i in run2["result"]["indices"] if i["code"] == "aip")["value"]
    assert aip1 == pytest.approx(0.0) and aip2 > 0
    rep = d.post(f"/calculations/{run1['calculation_id']}/reproduce").json()
    assert rep == {"identical": True, "same_engine_version": True, "same_model_config": True}
    assert d.get(f"/calculations/{run1['calculation_id']}").json()["result"] == run1["result"]
    assert len(d.get(f"/encounters/{eid}/calculations").json()) == 3


def test_calculation_idempotency(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    k = {"Idempotency-Key": uuid.uuid4().hex}
    a = d.post(f"/encounters/{eid}/calculations", json={}, headers=k).json()
    b = d.post(f"/encounters/{eid}/calculations", json={}, headers=k).json()
    assert a["calculation_id"] == b["calculation_id"]


def test_unknown_model_version(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    assert d.post(f"/encounters/{eid}/calculations", json={"model_version": "v9"}).status_code == 404


def test_audit_has_no_medical_values(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    add(d, eid, "glucose_fasting", 7.77, "mmol/L")
    events = world["admin_a"].get("/audit-events").json()
    assert any(e["action"] == "observation_added" for e in events)
    assert "7.77" not in str(events) and patient_flow["iin"] not in str(events)


def test_openapi_published(world):
    spec = world["doctor_a"].get("/openapi.json").json()
    assert "/api/v1/encounters/{encounter_id}/calculations" in spec["paths"]


def test_migrations_match_models(pg):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=f"{root}:{root.parent / 'lmb-engine'}")
    r = subprocess.run(["alembic", "check"], cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_encounter_rules(world, patient_flow):
    d, pid = patient_flow["doctor"], patient_flow["patient"]["id"]
    assert d.post(f"/patients/{pid}/encounters", json={"encounter_date": "1960-01-01"}).status_code == 422
    k = {"Idempotency-Key": uuid.uuid4().hex}
    a = d.post(f"/patients/{pid}/encounters", json={"encounter_date": "2026-10-09"}, headers=k).json()
    b = d.post(f"/patients/{pid}/encounters", json={"encounter_date": "2026-10-09"}, headers=k).json()
    assert a["id"] == b["id"]
    dates = [e["encounter_date"] for e in d.get(f"/patients/{pid}/encounters").json()]
    assert dates == sorted(dates, reverse=True) and len(dates) == 2


def test_observation_idempotency_and_reject(world, patient_flow):
    d, eid = patient_flow["doctor"], patient_flow["encounter"]["id"]
    k = {"Idempotency-Key": uuid.uuid4().hex}
    a = d.post(f"/encounters/{eid}/observations", json={"code": "height_cm", "value": 170, "unit": "cm"}, headers=k)
    b = d.post(f"/encounters/{eid}/observations", json={"code": "height_cm", "value": 170, "unit": "cm"}, headers=k)
    assert a.json()["chain_id"] == b.json()["chain_id"]
    w = add(d, eid, "weight_kg", 800, "kg", source="import").json()
    r = d.post(f"/observations/{w['chain_id']}/review", json={"decision": "reject"}, headers={"If-Match": "1"})
    assert r.json()["review_status"] == "rejected"
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    bmi = next(i for i in run["result"]["indices"] if i["code"] == "bmi")
    assert bmi["status"] == "missing_data" and "weight_kg" in bmi["missing_fields"]
    assert add(d, eid, "weight_kg", 80, "kg").status_code == 201   # после отклонения можно внести заново


def test_bootstrap_cli(pg):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=f"{root}:{root.parent / 'lmb-engine'}",
               LMB_BOOTSTRAP_PASSWORD="bootstrap-password-1")
    r = subprocess.run(["python3", "-m", "lmb_server.bootstrap", "--clinic", "Love my body",
                        "--email", f"root.{uuid.uuid4().hex[:6]}@test.kz", "--name", "Администратор"],
                       cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_catalog(world):
    c = world["doctor_a"].get("/catalog").json()
    assert [b["code"] for b in c["branches"]] == ["cardio", "metabolic", "renal", "hepatic", "inflammation",
                                                   "brain", "bone", "muscle", "adaptive"]
    codes = [i["code"] for g in c["observation_groups"] for i in g["items"]]
    assert "fn_tscore" in codes and not any(x.startswith("frax_") for x in codes)
    assert world["admin_a"].get("/catalog").status_code == 403
