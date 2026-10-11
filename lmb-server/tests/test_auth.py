"""Вход, второй фактор, CSRF, сеансы, журнал аудита."""
import datetime as dt

import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from lmb_server.bootstrap import create_user
from tests.conftest import PASSWORD, Api


def test_wrong_password(world, app):
    api = Api(app, world["doctor_a"].email, world["doctor_a"].totp_secret)
    assert api.login(password="wrong-password-123").status_code == 401


def test_unknown_email_same_answer(app, world):
    r = Api(app, "nobody@test.kz").login()
    assert r.status_code == 401 and r.json()["detail"] == "Неверный адрес или пароль"


def test_totp_required_at_login(world, app):
    api = Api(app, world["doctor_a"].email, world["doctor_a"].totp_secret)
    assert api.login(totp=False).status_code == 401
    assert api.login().status_code == 200


def test_staff_without_totp_blocked_until_enrolled(world, app, admin_engine):
    email = f"newdoc.{world['tag']}@test.kz"
    with Session(admin_engine) as s, s.begin():
        create_user(s, world["doctor_a"].clinic_id, email, "Новый врач", PASSWORD, ["doctor"])
    api = Api(app, email)
    assert api.login().status_code == 200
    assert api.get("/patients").status_code == 403          # второй фактор не подключён
    assert api.get("/auth/me").status_code == 200
    secret = api.post("/auth/totp/enroll").json()["secret"]
    assert api.post("/auth/totp/confirm", json={"code": "000000"}).status_code in (422,)
    assert api.post("/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    assert api.get("/patients").status_code == 200
    assert api.post("/auth/totp/enroll").status_code == 409


def test_csrf_required_for_mutations(world):
    d = world["doctor_a"]
    r = d.c.post("/api/v1/patients", json={"last_name": "X", "first_name": "Y", "birth_date": "1970-01-01",
                                           "sex_at_birth": "male"})
    assert r.status_code == 403
    assert d.get("/patients").status_code == 200  # чтение без CSRF


def test_logout_revokes_session(world, app):
    api = Api(app, world["doctor_a"].email, world["doctor_a"].totp_secret)
    api.login()
    assert api.post("/auth/logout").status_code == 200
    api.c.cookies.clear()
    assert api.get("/auth/me").status_code == 401


def test_expired_session(world, admin_engine):
    d = world["doctor_a"]
    with admin_engine.begin() as c:
        c.execute(text("update auth_session set expires_at = now() - interval '1 minute' "
                       "where user_id = :u"), {"u": d.user_id})
    assert d.get("/auth/me").status_code == 401


def test_cookie_flags(world, app):
    api = Api(app, world["doctor_a"].email, world["doctor_a"].totp_secret)
    r = api.login()
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc


def test_admin_creates_user_without_model_owner(world):
    a = world["admin_a"]
    r = a.post("/users", json={"email": f"nurse.{world['tag']}@test.kz", "full_name": "Врач 2",
                               "password": "short", "roles": ["doctor"]})
    assert r.status_code == 422  # пароль короче 12 символов
    r = a.post("/users", json={"email": f"doc2.{world['tag']}@test.kz", "full_name": "Врач 2",
                               "password": PASSWORD, "roles": ["doctor"], "is_model_owner": True})
    assert r.status_code == 201
    users = {u["email"]: u for u in a.get("/users").json()}
    assert f"doc2.{world['tag']}@test.kz" in users
    assert world["doctor_a"].post("/users", json={}).status_code in (403, 422)


def test_audit_logged_and_append_only(world, pg):
    a = world["admin_a"]
    events = a.get("/audit-events").json()
    assert any(e["action"] == "login" for e in events)
    assert all(e["details"] is None or "password" not in str(e["details"]) for e in events)
    # роль приложения не может менять или удалять записи журнала
    from sqlalchemy import create_engine
    import os
    app_eng = create_engine(os.environ["LMB_DATABASE_URL"])
    for sql in ("update audit_event set action = 'x'", "delete from audit_event"):
        with pytest.raises(Exception, match="permission denied"):
            with app_eng.begin() as c:
                c.execute(text(sql))
    app_eng.dispose()


def test_security_headers(world):
    r = world["doctor_a"].get("/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
