"""ФИО пациента хранится зашифрованным; поиск по точной фамилии через слепой индекс."""
import os
import subprocess
import uuid
from pathlib import Path

import psycopg
from sqlalchemy import text

from tests.conftest import PATIENT


def test_names_not_stored_in_plaintext(world, admin_engine):
    d = world["doctor_a"]
    surname = f"Синтетическая-{uuid.uuid4().hex[:6]}"
    pid = d.post("/patients", json={**PATIENT, "last_name": surname, "first_name": "Айгерим",
                                     "middle_name": "Тестовна"}).json()["id"]
    with admin_engine.connect() as c:
        row = c.execute(text("select * from patient where id = :i"), {"i": pid}).mappings().one()
    blob = " ".join(str(v) for v in row.values())
    for plain in (surname, "Айгерим", "Тестовна"):
        assert plain not in blob                                       # ни в одном столбце нет открытого ФИО
    assert {"last_name", "first_name", "middle_name"}.isdisjoint(row.keys())
    card = d.get(f"/patients/{pid}").json()
    assert (card["last_name"], card["first_name"], card["middle_name"]) == (surname, "Айгерим", "Тестовна")


def test_search_exact_surname_case_and_yo(world):
    d = world["doctor_a"]
    tag = uuid.uuid4().hex[:6]
    pid = d.post("/patients", json={**PATIENT, "last_name": f"Семёнова{tag}", "first_name": "Ирина"}).json()["id"]
    for q in (f"Семёнова{tag}", f"семенова{tag}", f"  СЕМЁНОВА{tag} "):
        assert [p["id"] for p in d.get("/patients", params={"query": q}).json()] == [pid], q
    assert d.get("/patients", params={"query": "Семён"}).json() == []      # начало фамилии не ищется
    assert world["doctor_b"].get("/patients", params={"query": f"Семёнова{tag}"}).json() == []


def test_list_sorted_alphabetically_after_decrypt(world):
    d = world["doctor_b"]
    for name in ("Яковлева", "Абенова", "Мусина"):
        d.post("/patients", json={**PATIENT, "last_name": name})
    names = [p["last_name"] for p in d.get("/patients").json()]
    assert names == sorted(names, key=str.casefold)


def test_rename_updates_index_and_audit_has_no_names(world, admin_engine):
    d = world["doctor_a"]
    p = d.post("/patients", json={**PATIENT, "last_name": "Старая"}).json()
    new = f"Новая{uuid.uuid4().hex[:6]}"
    r = d.patch(f"/patients/{p['id']}", json={"last_name": new, "change_reason": "Смена фамилии"},
                headers={"If-Match": str(p["version"])})
    assert r.status_code == 200 and r.json()["last_name"] == new
    assert [x["id"] for x in d.get("/patients", params={"query": new}).json()] == [p["id"]]
    assert p["id"] not in [x["id"] for x in d.get("/patients", params={"query": "Старая"}).json()]
    with admin_engine.connect() as c:
        details = c.execute(text("select coalesce(string_agg(details::text, ' '), '') from audit_event "
                                 "where patient_id = :i"), {"i": p["id"]}).scalar()
    assert new not in details and "Старая" not in details


def test_migration_encrypts_existing_names(pg):
    """Существующие карточки шифруются миграцией 0006 и восстанавливаются при откате."""
    root = Path(__file__).resolve().parents[1]
    db = "lmb_mig_" + uuid.uuid4().hex[:6]
    with psycopg.connect(pg.url("postgres", "postgres"), autocommit=True) as c:
        c.execute(f"CREATE DATABASE {db} OWNER lmb_admin")
    url = pg.url("lmb_admin", db=db, driver="postgresql+psycopg")
    env = dict(os.environ, LMB_ADMIN_DATABASE_URL=url, PYTHONPATH=f"{root}:{root.parent / 'lmb-engine'}")

    def alembic(*args):
        r = subprocess.run(["alembic", *args], cwd=root, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]

    alembic("upgrade", "0005")
    with psycopg.connect(pg.url("lmb_admin", db=db)) as c:
        cid, uid, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        c.execute("insert into clinic (id, name, timezone) values (%s, 'М', 'Asia/Almaty')", (cid,))
        c.execute("insert into app_user (id, clinic_id, email, full_name, password_hash, totp_enabled, is_active, "
                  "is_model_owner) "
                  "values (%s, %s, 'm@test.kz', 'М', 'x', false, true, false)", (uid, cid))
        c.execute("insert into patient (id, clinic_id, last_name, first_name, middle_name, birth_date, sex_at_birth, "
                  "pseudonym_code, version, created_by) values (%s, %s, 'Ёлкина', 'Анна', null, '1970-01-01', 'female', "
                  "'P-MIG', 1, %s)", (pid, cid, uid))
    alembic("upgrade", "head")
    from lmb_server.security import decrypt, name_index
    with psycopg.connect(pg.url("lmb_admin", db=db)) as c:
        row = c.execute("select last_name_enc, first_name_enc, middle_name_enc, last_name_index from patient "
                        "where id = %s", (pid,)).fetchone()
    assert decrypt(row[0]) == "Ёлкина" and decrypt(row[1]) == "Анна" and row[2] is None
    assert row[3] == name_index("елкина")
    alembic("downgrade", "0005")
    with psycopg.connect(pg.url("lmb_admin", db=db)) as c:
        assert c.execute("select last_name, first_name from patient where id = %s", (pid,)).fetchone() == \
            ("Ёлкина", "Анна")
