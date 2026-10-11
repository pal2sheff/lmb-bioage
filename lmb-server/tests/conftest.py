"""Тесты на настоящем PostgreSQL 16: временный кластер, миграции, две клиники."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pyotp
import pytest

os.environ["LMB_ARGON2_PROFILE"] = "test"  # облегчённый Argon2 только в тестах
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "lmb-engine"))

from tests.pgcluster import PgCluster  # noqa: E402

PASSWORD = "correct-horse-battery-1"


@pytest.fixture(scope="session")
def pg():
    c = PgCluster().start()
    os.environ.update({
        "LMB_DATABASE_URL": c.url("lmb_app", driver="postgresql+psycopg"),
        "LMB_ADMIN_DATABASE_URL": c.url("lmb_admin", driver="postgresql+psycopg"),
        "LMB_FIELD_KEY": Fernet.generate_key().decode(),
        "LMB_INDEX_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "LMB_COOKIE_SECURE": "false",
        "LMB_REQUIRE_STAFF_TOTP": "true",
        "LMB_ENVIRONMENT": "test",
        "LMB_FILES_DIR": os.path.join(c.dir, "files"),
        "LMB_FILES_KEY": Fernet.generate_key().decode(),
        "LMB_MAX_UPLOAD_MB": "1",
    })
    env = dict(os.environ, PYTHONPATH=f"{ROOT}:{ROOT.parent / 'lmb-engine'}")
    r = subprocess.run(["alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    yield c
    from lmb_server.db import reset_engine
    reset_engine()
    c.stop()


@pytest.fixture(scope="session")
def app(pg):
    from lmb_server.main import create_app
    return create_app()


@pytest.fixture(scope="session")
def admin_engine(pg):
    from sqlalchemy import create_engine
    e = create_engine(os.environ["LMB_ADMIN_DATABASE_URL"])
    yield e
    e.dispose()


class Api:
    """Клиент от имени пользователя: cookie сеанса и заголовок CSRF."""

    def __init__(self, app, email, totp_secret=None):
        from fastapi.testclient import TestClient
        self.c = TestClient(app)
        self.email = email
        self.totp_secret = totp_secret
        self.csrf = None

    def login(self, password=PASSWORD, totp=True):
        body = {"email": self.email, "password": password}
        if totp and self.totp_secret:
            body["totp"] = pyotp.TOTP(self.totp_secret).now()
        r = self.c.post("/api/v1/auth/login", json=body)
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r

    def _h(self, headers):
        h = {"X-CSRF-Token": self.csrf or ""}
        h.update(headers or {})
        return h

    def get(self, path, **kw):
        return self.c.get("/api/v1" + path, **kw)

    def post(self, path, json=None, headers=None):
        return self.c.post("/api/v1" + path, json=json, headers=self._h(headers))

    def upload(self, path, data: bytes, filename="file.pdf", kind="frax_result", headers=None):
        return self.c.post("/api/v1" + path, data={"kind": kind}, files={"file": (filename, data)},
                           headers=self._h(headers))

    def put(self, path, json=None, headers=None):
        return self.c.put("/api/v1" + path, json=json, headers=self._h(headers))

    def patch(self, path, json=None, headers=None):
        return self.c.patch("/api/v1" + path, json=json, headers=self._h(headers))


@pytest.fixture
def world(app, admin_engine):
    """Две клиники с пользователями всех ролей. У персонала включён TOTP."""
    from sqlalchemy.orm import Session

    from lmb_server.bootstrap import create_clinic, create_user
    from lmb_server.security import encrypt

    tag = uuid.uuid4().hex[:8]
    users = {}
    with Session(admin_engine) as s, s.begin():
        for clinic in ("A", "B"):
            c = create_clinic(s, f"Clinic {clinic} {tag}")
            spec = [("doctor", ["doctor"], False), ("admin", ["clinic_admin"], False),
                    ("researcher", ["researcher"], False), ("patient", ["patient"], False),
                    ("owner", ["doctor"], True)]
            for key, roles, owner in spec:
                email = f"{key}.{clinic.lower()}.{tag}@test.kz"
                u = create_user(s, c.id, email, f"{key} {clinic}", PASSWORD, roles, model_owner=owner)
                secret = None
                if key != "patient":
                    secret = pyotp.random_base32()
                    u.totp_secret_enc = encrypt(secret)
                    u.totp_enabled = True
                users[f"{key}_{clinic.lower()}"] = (email, secret, c.id, u.id)
    out = {}
    for k, (email, secret, cid, uid) in users.items():
        api = Api(app, email, secret)
        assert api.login().status_code == 200
        api.clinic_id, api.user_id = cid, uid
        out[k] = api
    out["tag"] = tag
    return out


PATIENT = {"last_name": "Тестова", "first_name": "Анна", "birth_date": "1974-03-15", "sex_at_birth": "female"}


@pytest.fixture
def patient_flow(world):
    """Пациент клиники A с визитом."""
    d = world["doctor_a"]
    iin = str(uuid.uuid4().int)[:12]
    p = d.post("/patients", json={**PATIENT, "iin": iin, "phone": "+7 701 000 00 00"}).json()
    e = d.post(f"/patients/{p['id']}/encounters", json={"encounter_date": "2026-10-10"}).json()
    return {"patient": p, "encounter": e, "iin": iin, "doctor": d}
