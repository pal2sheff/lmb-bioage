"""FRAX через API: задачи, очередь, ручной режим, поздний ответ, выбор результата, расчёт."""
import datetime as dt
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from lmb_server.frax import service
from lmb_server.frax.providers import FRAXResult
from lmb_server.frax.request import RISK_FACTORS
from tests.conftest import PATIENT


class FakeProvider:
    """Тестовый провайдер: помечен fake_test, в рабочую базу не допускается."""
    name = "fake_test"

    def __init__(self, major=11.0, hip=2.5, fail=False):
        self.major, self.hip, self.fail, self.calls = major, hip, fail, 0

    def calculate(self, req):
        self.calls += 1
        if self.fail:
            return FRAXResult("external_error", self.name, error_code="provider_unavailable", attempts=3)
        return FRAXResult("calculated", self.name, self.major, self.hip, req.fn_bmd is not None, "Kazakhstan",
                          "test", attempts=1)


@pytest.fixture
def fake(monkeypatch):
    p = FakeProvider()
    monkeypatch.setattr(service, "provider_factory", lambda: p)
    return p


@pytest.fixture
def ready(world):
    d = world["doctor_a"]
    pt = d.post("/patients", json={**PATIENT, "birth_date": "1960-01-01"}).json()
    e = d.post(f"/patients/{pt['id']}/encounters", json={"encounter_date": "2026-10-10"}).json()
    eid = e["id"]
    for code, v, u in (("height_cm", 160, "cm"), ("weight_kg", 60, "kg")):
        d.post(f"/encounters/{eid}/observations", json={"code": code, "value": v, "unit": u})
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": {f: "no" for f in RISK_FACTORS}})
    return d, eid


def work(admin_engine, provider):
    return service.process_pending(lambda: Session(admin_engine), provider)


def frax_index(d, eid):
    run = d.post(f"/encounters/{eid}/calculations", json={}).json()
    return next(i for i in run["result"]["indices"] if i["code"] == "frax_kz")


def test_inputs_endpoint(ready):
    d, eid = ready
    r = d.get(f"/encounters/{eid}/frax/inputs").json()
    assert r["status"] == "ready" and r["request"]["age_years"] == 66 and r["provider"] == "not_configured"
    assert "birth_date" not in r["request"] and PATIENT["last_name"] not in str(r)


def test_missing_factor_blocks_request(world):
    d = world["doctor_a"]
    pt = d.post("/patients", json={**PATIENT, "birth_date": "1960-01-01"}).json()
    eid = d.post(f"/patients/{pt['id']}/encounters", json={"encounter_date": "2026-10-10"}).json()["id"]
    r = d.post(f"/encounters/{eid}/frax-jobs")
    assert r.status_code == 422 and "parent_hip_fracture" in str(r.json())


def test_not_configured_status_reaches_profile(ready):
    d, eid = ready
    r = d.post(f"/encounters/{eid}/frax-jobs")
    assert r.status_code == 202 and r.json()["status"] == "integration_not_configured"
    assert frax_index(d, eid)["status"] == "integration_not_configured"


def test_auto_flow_and_no_double_spend(ready, fake, admin_engine):
    d, eid = ready
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    assert j["status"] == "queued" and j["created"] is True
    again = d.post(f"/encounters/{eid}/frax-jobs").json()
    assert again["id"] == j["id"] and again["created"] is False
    assert work(admin_engine, fake) == 1 and fake.calls == 1
    done = d.get(f"/frax-jobs/{j['id']}").json()
    assert done["status"] == "calculated" and done["is_active_choice"] and done["inputs_current"]
    third = d.post(f"/encounters/{eid}/frax-jobs").json()
    assert third["id"] == j["id"] and third["created"] is False      # лимит повторно не расходуется
    idx = frax_index(d, eid)
    assert idx["status"] == "calculated" and idx["value"] == 11.0 and idx["extra"]["hip_10y_pct"] == 2.5
    assert idx["extra"]["source"] == "automatic"


def test_b18_late_answer_not_applied_to_changed_inputs(ready, fake, admin_engine):
    d, eid = ready
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    chain = next(o for o in d.get(f"/encounters/{eid}/observations").json() if o["code"] == "weight_kg")["chain_id"]
    d.patch(f"/observations/{chain}", json={"value": 64, "unit": "kg", "change_reason": "Перевзвешивание"},
            headers={"If-Match": "1"})
    work(admin_engine, fake)
    done = d.get(f"/frax-jobs/{j['id']}").json()
    assert done["status"] == "calculated" and done["inputs_current"] is False
    idx = frax_index(d, eid)
    assert idx["status"] != "calculated" and idx["value"] is None


def test_manual_entry_rules(ready):
    d, eid = ready
    base = {"frax_major_10y_pct": 9.1, "frax_hip_10y_pct": 1.8, "with_bmd": False,
            "calculated_on": "2026-10-10", "national_model": "Kazakhstan", "source_note": "Официальный калькулятор"}
    assert d.post(f"/encounters/{eid}/frax-manual", json={**base, "frax_hip_10y_pct": 140}).status_code == 422
    assert d.post(f"/encounters/{eid}/frax-manual", json={**base, "with_bmd": True}).status_code == 422
    assert d.post(f"/encounters/{eid}/frax-manual", json={**base, "national_model": "UK"}).status_code == 422
    future = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    assert d.post(f"/encounters/{eid}/frax-manual", json={**base, "calculated_on": future}).status_code == 422
    r = d.post(f"/encounters/{eid}/frax-manual", json=base)
    assert r.status_code == 201 and r.json()["is_active_choice"] and r.json()["source"] == "manual"
    idx = frax_index(d, eid)
    assert idx["status"] == "calculated" and idx["value"] == 9.1 and idx["extra"]["source"] == "manual"


def test_auto_does_not_silently_replace_manual(ready, fake, admin_engine):
    d, eid = ready
    m = d.post(f"/encounters/{eid}/frax-manual", json={
        "frax_major_10y_pct": 9.1, "frax_hip_10y_pct": 1.8, "with_bmd": False, "calculated_on": "2026-10-10",
        "national_model": "Kazakhstan", "source_note": "Официальный калькулятор"}).json()
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    work(admin_engine, fake)
    auto = d.get(f"/frax-jobs/{j['id']}").json()
    assert auto["is_active_choice"] is False and auto["conflict_note"]
    assert frax_index(d, eid)["value"] == 9.1                      # действует ручной результат
    assert d.post(f"/frax-jobs/{auto['id']}/activate").status_code == 200
    assert frax_index(d, eid)["value"] == 11.0
    jobs = {x["id"]: x for x in d.get(f"/encounters/{eid}/frax-jobs").json()}
    assert jobs[m["id"]]["is_active_choice"] is False               # история сохранена


def test_error_and_retry(ready, monkeypatch, admin_engine):
    d, eid = ready
    failing = FakeProvider(fail=True)
    monkeypatch.setattr(service, "provider_factory", lambda: failing)
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    work(admin_engine, failing)
    err = d.get(f"/frax-jobs/{j['id']}").json()
    assert err["status"] == "external_error" and err["error_code"] == "provider_unavailable"
    assert frax_index(d, eid)["status"] == "external_error"
    assert d.post(f"/frax-jobs/{j['id']}/activate").status_code == 409
    r = d.post(f"/frax-jobs/{j['id']}/retry")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    ok = FakeProvider()
    work(admin_engine, ok)
    assert frax_index(d, eid)["status"] == "calculated"


def test_other_clinic_cannot_see_job(ready, world, fake):
    d, eid = ready
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    assert world["doctor_b"].get(f"/frax-jobs/{j['id']}").status_code == 404
    assert world["doctor_b"].post(f"/encounters/{eid}/frax-jobs").status_code == 404


def test_test_flag_enforced_in_db(admin_engine, ready):
    _, eid = ready
    with pytest.raises(Exception, match="ck_ext_test_flag"):
        with admin_engine.begin() as c:
            c.execute(text("insert into external_request (id, clinic_id, encounter_id, kind, provider, "
                           "frax_input_hash, request_payload, status, attempts, is_active_choice, is_test, created_by) "
                           "select gen_random_uuid(), clinic_id, id, 'frax', 'fake_test', 'h', '{}'::jsonb, 'queued', "
                           "0, false, false, doctor_id from encounter where id = :e"), {"e": eid})


def test_fake_provider_forbidden_outside_test_env(ready, fake, monkeypatch):
    d, eid = ready
    from lmb_server import settings
    st = settings.get_settings()
    monkeypatch.setattr(settings, "get_settings", lambda: type(st)(**{**st.__dict__, "environment": "production"}))
    monkeypatch.setattr(service, "get_settings", settings.get_settings)
    with pytest.raises(RuntimeError):
        d.post(f"/encounters/{eid}/frax-jobs")


def test_default_provider_selection(monkeypatch):
    from lmb_server import settings
    from lmb_server.frax.providers import FraxPlusHttpProvider, NotConfiguredProvider
    st = settings.get_settings()
    assert isinstance(service.default_provider(), NotConfiguredProvider)
    cfg = type(st)(**{**st.__dict__, "frax_provider": "fraxplus_local", "frax_base_url": "http://frax:8085",
                      "frax_api_key": "k"})
    monkeypatch.setattr(service, "get_settings", lambda: cfg)
    p = service.default_provider()
    assert isinstance(p, FraxPlusHttpProvider) and p.mapping.verified is False
    assert p.calculate(None).status == "integration_not_configured"


def test_new_inputs_replace_old_active(ready, fake, admin_engine):
    d, eid = ready
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    work(admin_engine, fake)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"smoking_current": "yes"}})
    k = {"Idempotency-Key": uuid.uuid4().hex}
    body = {"frax_major_10y_pct": 14.0, "frax_hip_10y_pct": 3.0, "with_bmd": False, "calculated_on": "2026-10-10",
            "national_model": "Kazakhstan", "source_note": "Официальный калькулятор"}
    m = d.post(f"/encounters/{eid}/frax-manual", json=body, headers=k).json()
    assert d.post(f"/encounters/{eid}/frax-manual", json=body, headers=k).json()["id"] == m["id"]
    assert m["is_active_choice"] is True
    old = d.get(f"/frax-jobs/{j['id']}").json()
    assert old["is_active_choice"] is False and old["inputs_current"] is False
    assert frax_index(d, eid)["value"] == 14.0


def test_retry_guards(ready, fake, admin_engine):
    d, eid = ready
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    work(admin_engine, fake)
    assert d.post(f"/frax-jobs/{j['id']}/retry").status_code == 409          # уже получен


def test_retry_after_input_change(ready, monkeypatch, admin_engine):
    d, eid = ready
    failing = FakeProvider(fail=True)
    monkeypatch.setattr(service, "provider_factory", lambda: failing)
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    work(admin_engine, failing)
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"alcohol_3plus": "yes"}})
    assert d.post(f"/frax-jobs/{j['id']}/retry").status_code == 409


def test_quota_warning(ready, fake, monkeypatch):
    d, eid = ready
    monkeypatch.setattr(service, "usage_this_year", lambda db: 4600)
    assert "4600" in d.post(f"/encounters/{eid}/frax-jobs").json()["quota_warning"]


def test_frax_questionnaire_items(ready):
    d, eid = ready
    assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"frax_assumed_no": "bogus"}}).status_code == 422
    assert d.put(f"/encounters/{eid}/questionnaire", json={"answers": {"fn_bmd_device_make": ""}}).status_code == 422
    q = d.put(f"/encounters/{eid}/questionnaire",
              json={"answers": {"frax_assumed_no": "parent_hip_fracture", "fn_bmd_device_make": "Hologic"}}).json()
    assert q["fn_bmd_device_make"]["answer"] == "Hologic" and q["frax_assumed_no"]["doctor_only"]


def test_worker_cli(pg):
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=f"{root}:{root.parent / 'lmb-engine'}")
    r = subprocess.run(["python3", "-m", "lmb_server.frax.worker", "--once"], cwd=root, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "Обработано" in r.stdout, r.stderr
