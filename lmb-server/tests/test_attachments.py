"""Вложения на локальном диске и независимый ручной ввод FRAX. Все данные синтетические."""
import os
import stat
from pathlib import Path

import pytest
from sqlalchemy import text

from lmb_server.frax import service
from lmb_server.frax.request import RISK_FACTORS
from tests.conftest import PATIENT
from tests.test_frax_api import FakeProvider, frax_index, work

PDF = b"%PDF-1.4\n% synthetic test document LMB-SYNTHETIC-MARKER\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MANUAL = {"frax_major_10y_pct": 12.5, "frax_hip_10y_pct": 3.1, "with_bmd": False, "calculated_on": "2026-10-10",
          "national_model": "Kazakhstan", "source_note": "Официальный калькулятор FRAX, модель Казахстана"}


def _visit(d, birth="1960-01-01", measurements=True, questionnaire=False):
    pt = d.post("/patients", json={**PATIENT, "birth_date": birth}).json()
    eid = d.post(f"/patients/{pt['id']}/encounters", json={"encounter_date": "2026-10-10"}).json()["id"]
    if measurements:
        for code, v, u in (("height_cm", 160, "cm"), ("weight_kg", 60, "kg")):
            d.post(f"/encounters/{eid}/observations", json={"code": code, "value": v, "unit": u})
    if questionnaire:
        d.put(f"/encounters/{eid}/questionnaire", json={"answers": {f: "no" for f in RISK_FACTORS}})
    return eid


def _files_root() -> Path:
    return Path(os.environ["LMB_FILES_DIR"])


# ---------- хранилище файлов ----------

def test_upload_download_roundtrip_encrypted_on_disk(world, admin_engine):
    d = world["doctor_a"]
    eid = _visit(d)
    r = d.upload(f"/encounters/{eid}/attachments", PDF, filename="FRAX Синтетическая.pdf")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["mime_type"] == "application/pdf" and a["size_bytes"] == len(PDF)
    assert a["filename"] == "FRAX Синтетическая.pdf"

    with admin_engine.connect() as c:
        row = c.execute(text("select storage_key, filename_enc from attachment where id = :i"),
                        {"i": a["id"]}).one()
    assert "Синтетическая" not in row.filename_enc                 # имя файла в базе зашифровано
    path = _files_root() / row.storage_key
    raw = path.read_bytes()
    assert b"LMB-SYNTHETIC-MARKER" not in raw and not raw.startswith(b"%PDF")   # на диске шифротекст
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    dl = d.get(f"/attachments/{a['id']}")
    assert dl.status_code == 200 and dl.content == PDF
    assert dl.headers["cache-control"] == "no-store"
    assert dl.headers["content-disposition"].startswith("attachment;")
    assert [x["id"] for x in d.get(f"/encounters/{eid}/attachments").json()] == [a["id"]]

    with admin_engine.connect() as c:
        acts = c.execute(text("select action, details::text from audit_event where entity_id = :i"),
                         {"i": a["id"]}).all()
    assert {x.action for x in acts} == {"attachment_uploaded", "attachment_downloaded"}
    assert all("Синтетическая" not in (x.details or "") for x in acts)   # в журнале нет имени и содержимого


def test_upload_rejects_wrong_type_size_and_role(world):
    d = world["doctor_a"]
    eid = _visit(d)
    assert d.upload(f"/encounters/{eid}/attachments", b"plain text", filename="x.pdf").status_code == 422
    assert d.upload(f"/encounters/{eid}/attachments", b"MZ\x90\x00", filename="x.exe").status_code == 422
    assert d.upload(f"/encounters/{eid}/attachments", b"", filename="x.pdf").status_code == 422
    big = b"%PDF-" + b"0" * (1024 * 1024 + 10)                       # лимит в тестах 1 МБ
    assert d.upload(f"/encounters/{eid}/attachments", big).status_code == 422
    assert d.upload(f"/encounters/{eid}/attachments", PDF, kind="unknown").status_code == 422
    assert d.upload(f"/encounters/{eid}/attachments", PNG, filename="scan.png").json()["mime_type"] == "image/png"
    assert world["researcher_a"].upload(f"/encounters/{eid}/attachments", PDF).status_code == 403
    assert world["admin_a"].upload(f"/encounters/{eid}/attachments", PDF).status_code == 403
    # без заголовка CSRF загрузка отклоняется
    r = d.c.post(f"/api/v1/encounters/{eid}/attachments", data={"kind": "lab"}, files={"file": ("a.pdf", PDF)})
    assert r.status_code == 403


def test_attachment_isolated_between_clinics(world, admin_engine):
    d = world["doctor_a"]
    eid = _visit(d)
    aid = d.upload(f"/encounters/{eid}/attachments", PDF).json()["id"]
    other = world["doctor_b"]
    assert other.get(f"/attachments/{aid}").status_code == 404
    assert other.get(f"/encounters/{eid}/attachments").status_code == 404
    assert other.upload(f"/encounters/{eid}/attachments", PDF).status_code == 404
    # RLS: роль приложения в контексте клиники B не видит строку клиники A
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["LMB_DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(other.clinic_id)})
        assert c.execute(text("select count(*) from attachment where id = :i"), {"i": aid}).scalar() == 0
    eng.dispose()


def test_app_role_cannot_modify_or_delete_attachment(world):
    d = world["doctor_a"]
    eid = _visit(d)
    aid = d.upload(f"/encounters/{eid}/attachments", PDF).json()["id"]
    from sqlalchemy import create_engine
    from sqlalchemy.exc import ProgrammingError
    eng = create_engine(os.environ["LMB_DATABASE_URL"])
    for sql in ("update attachment set kind = 'other' where id = :i", "delete from attachment where id = :i"):
        with pytest.raises(ProgrammingError):
            with eng.begin() as c:
                c.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(d.clinic_id)})
                c.execute(text(sql), {"i": aid})
    eng.dispose()


def test_tampered_file_detected(world, admin_engine):
    d = world["doctor_a"]
    eid = _visit(d)
    aid = d.upload(f"/encounters/{eid}/attachments", PDF).json()["id"]
    with admin_engine.connect() as c:
        key = c.execute(text("select storage_key from attachment where id = :i"), {"i": aid}).scalar()
    p = _files_root() / key
    data = bytearray(p.read_bytes())
    data[-5] ^= 1
    p.write_bytes(bytes(data))
    assert d.get(f"/attachments/{aid}").status_code == 500


def test_storage_path_traversal_blocked():
    from cryptography.fernet import Fernet

    from lmb_server.storage import LocalEncryptedStorage, StorageError
    s = LocalEncryptedStorage(str(_files_root()), Fernet.generate_key(), 1024)
    with pytest.raises(StorageError):
        s.get("../../etc/passwd", "0" * 64)


# ---------- независимый ручной FRAX ----------

def test_manual_frax_without_questionnaire(world):
    d = world["doctor_a"]
    eid = _visit(d, questionnaire=False)
    assert d.get(f"/encounters/{eid}/frax/inputs").json()["status"] != "ready"
    assert d.post(f"/encounters/{eid}/frax-jobs").status_code == 422   # автоматический запрос заблокирован
    r = d.post(f"/encounters/{eid}/frax-manual", json=MANUAL)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["inputs_bound"] is False and j["is_active_choice"] and j["inputs_current"] is True
    assert j["manual_source_note"] == MANUAL["source_note"]
    idx = frax_index(d, eid)
    assert idx["status"] == "calculated" and idx["value"] == 12.5
    assert idx["extra"]["hip_10y_pct"] == 3.1 and idx["extra"]["source"] == "manual"
    assert any("без полного набора" in w for w in idx["warnings"])


def test_manual_frax_without_any_measurements(world):
    d = world["doctor_a"]
    eid = _visit(d, measurements=False)
    r = d.post(f"/encounters/{eid}/frax-manual", json={**MANUAL, "with_bmd": True})
    assert r.status_code == 201 and r.json()["with_bmd"] is True
    assert frax_index(d, eid)["extra"]["with_bmd"] is True


def test_manual_frax_age_outside_model(world):
    d = world["doctor_a"]
    for birth in ("1990-01-01", "1930-01-01"):                      # 36 и 96 лет
        eid = _visit(d, birth=birth)
        r = d.post(f"/encounters/{eid}/frax-manual", json=MANUAL)
        assert r.status_code == 422 and "40–90" in r.text


def test_manual_frax_with_attachment(world):
    d = world["doctor_a"]
    eid = _visit(d)
    aid = d.upload(f"/encounters/{eid}/attachments", PDF).json()["id"]
    j = d.post(f"/encounters/{eid}/frax-manual", json={**MANUAL, "attachment_id": aid}).json()
    assert j["attachment_id"] == aid
    listed = d.get(f"/encounters/{eid}/frax-jobs").json()
    assert listed[0]["attachment_id"] == aid
    # файл другого визита или другой клиники привязать нельзя
    eid2 = _visit(d)
    assert d.post(f"/encounters/{eid2}/frax-manual", json={**MANUAL, "attachment_id": aid}).status_code == 422
    other = world["doctor_b"]
    eid_b = _visit(other)
    assert other.post(f"/encounters/{eid_b}/frax-manual", json={**MANUAL, "attachment_id": aid}).status_code == 404


def test_manual_unbound_then_questionnaire_completed(world, monkeypatch, admin_engine):
    """Ручной результат без анкеты продолжает действовать после её заполнения;
    автоматический ответ его не заменяет без решения врача."""
    d = world["doctor_a"]
    eid = _visit(d)
    m = d.post(f"/encounters/{eid}/frax-manual", json=MANUAL).json()
    d.put(f"/encounters/{eid}/questionnaire", json={"answers": {f: "no" for f in RISK_FACTORS}})
    assert frax_index(d, eid)["value"] == 12.5
    fake = FakeProvider(major=7.0)
    monkeypatch.setattr(service, "provider_factory", lambda: fake)
    j = d.post(f"/encounters/{eid}/frax-jobs").json()
    work(admin_engine, fake)
    auto = d.get(f"/frax-jobs/{j['id']}").json()
    assert auto["is_active_choice"] is False and auto["conflict_note"]
    assert frax_index(d, eid)["value"] == 12.5
    d.post(f"/frax-jobs/{auto['id']}/activate")
    assert frax_index(d, eid)["value"] == 7.0
    jobs = {x["id"]: x for x in d.get(f"/encounters/{eid}/frax-jobs").json()}
    assert jobs[m["id"]]["is_active_choice"] is False


def test_second_manual_replaces_first_and_is_idempotent(world):
    d = world["doctor_a"]
    eid = _visit(d)
    first = d.post(f"/encounters/{eid}/frax-manual", json=MANUAL).json()
    h = {"Idempotency-Key": "manual-2"}
    second = d.post(f"/encounters/{eid}/frax-manual", json={**MANUAL, "frax_major_10y_pct": 13.0}, headers=h).json()
    again = d.post(f"/encounters/{eid}/frax-manual", json={**MANUAL, "frax_major_10y_pct": 13.0}, headers=h).json()
    assert again["id"] == second["id"]
    jobs = {x["id"]: x for x in d.get(f"/encounters/{eid}/frax-jobs").json()}
    assert len(jobs) == 2 and jobs[second["id"]]["is_active_choice"] and not jobs[first["id"]]["is_active_choice"]
    assert frax_index(d, eid)["value"] == 13.0


def test_bound_manual_with_bmd_mismatch_still_rejected(world):
    d = world["doctor_a"]
    eid = _visit(d, questionnaire=True)
    assert d.post(f"/encounters/{eid}/frax-manual", json={**MANUAL, "with_bmd": True}).status_code == 422
    r = d.post(f"/encounters/{eid}/frax-manual", json=MANUAL)
    assert r.status_code == 201 and r.json()["inputs_bound"] is True
