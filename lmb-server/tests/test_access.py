"""Матрица доступа (ТЗ 2.2) и изоляция клиник на уровне API и базы (RLS)."""
import os

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import PATIENT


@pytest.mark.parametrize("who,status", [("doctor_a", 201), ("admin_a", 201), ("researcher_a", 403),
                                        ("patient_a", 403)])
def test_create_patient_by_role(world, who, status):
    assert world[who].post("/patients", json=PATIENT).status_code == status


def test_admin_cannot_enter_clinical_data(world, patient_flow):
    a = world["admin_a"]
    eid = patient_flow["encounter"]["id"]
    assert a.post(f"/encounters/{eid}/observations", json={"code": "tg", "value": 1, "unit": "mmol/L"}).status_code == 403
    assert a.post(f"/encounters/{eid}/calculations", json={}).status_code == 403
    assert a.post(f"/patients/{patient_flow['patient']['id']}/encounters",
                  json={"encounter_date": "2026-10-10"}).status_code == 403


def test_researcher_and_patient_no_identities(world, patient_flow):
    pid = patient_flow["patient"]["id"]
    for who in ("researcher_a", "patient_a"):
        assert world[who].get(f"/patients/{pid}").status_code == 403
        assert world[who].get("/patients").status_code == 403


def test_model_versions_access(world):
    assert world["doctor_a"].get("/model-versions").status_code == 200
    assert world["admin_a"].get("/model-versions").status_code == 403
    mv = world["owner_a"].get("/model-versions").json()
    v03 = next(m for m in mv if m["label"] == "v0.3")
    assert v03["completeness"] == "incomplete" and v03["usage_permission"] == "none"


def test_other_clinic_gets_404(world, patient_flow):
    b = world["doctor_b"]
    pid, eid = patient_flow["patient"]["id"], patient_flow["encounter"]["id"]
    assert b.get(f"/patients/{pid}").status_code == 404
    assert b.get(f"/encounters/{eid}").status_code == 404
    assert b.post(f"/encounters/{eid}/observations", json={"code": "tg", "value": 1, "unit": "mmol/L"}).status_code == 404
    assert b.get(f"/patients?query={PATIENT['last_name']}").json() == [] or \
        all(p["id"] != pid for p in b.get(f"/patients?query={PATIENT['last_name']}").json())


def test_rls_blocks_raw_queries(world, patient_flow):
    """Даже без фильтра в коде роль приложения видит только строки своей клиники."""
    eng = create_engine(os.environ["LMB_DATABASE_URL"])
    pid = patient_flow["patient"]["id"]
    with eng.begin() as c:
        assert c.execute(text("select count(*) from patient where id = :p"), {"p": pid}).scalar() == 0
        c.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(world["doctor_b"].clinic_id)})
        assert c.execute(text("select count(*) from patient where id = :p"), {"p": pid}).scalar() == 0
    with eng.begin() as c:
        c.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(world["doctor_a"].clinic_id)})
        assert c.execute(text("select count(*) from patient where id = :p"), {"p": pid}).scalar() == 1
    # запись в чужую клинику отклоняется политикой WITH CHECK
    with pytest.raises(Exception, match="row-level security"):
        with eng.begin() as c:
            c.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(world["doctor_b"].clinic_id)})
            c.execute(text("insert into encounter (id, clinic_id, patient_id, encounter_date, doctor_id, status) "
                           "values (gen_random_uuid(), :ca, :p, '2026-10-10', :d, 'open')"),
                      {"ca": str(world["doctor_a"].clinic_id), "p": pid, "d": str(world["doctor_b"].user_id)})
    eng.dispose()


def test_app_role_cannot_delete_medical_data(world, patient_flow):
    eng = create_engine(os.environ["LMB_DATABASE_URL"])
    with pytest.raises(Exception, match="permission denied"):
        with eng.begin() as c:
            c.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(world["doctor_a"].clinic_id)})
            c.execute(text("delete from observation"))
    eng.dispose()
