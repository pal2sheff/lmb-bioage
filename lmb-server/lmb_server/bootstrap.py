"""Начальная настройка: клиника и первый администратор (роль lmb_admin).

Пример:
  LMB_BOOTSTRAP_PASSWORD='…' python3 -m lmb_server.bootstrap --clinic "Love my body" \
      --email admin@clinic.kz --name "Администратор"
"""
from __future__ import annotations

import argparse
import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .models import Clinic, User, UserRole
from .security import hash_password
from .settings import get_settings


def create_clinic(session: Session, name: str, timezone: str = "Asia/Almaty") -> Clinic:
    c = Clinic(name=name, timezone=timezone)
    session.add(c)
    session.flush()
    return c


def create_user(session: Session, clinic_id: uuid.UUID, email: str, name: str, password: str, roles: list[str],
                model_owner: bool = False) -> User:
    u = User(clinic_id=clinic_id, email=email, full_name=name, password_hash=hash_password(password),
             is_model_owner=model_owner)
    session.add(u)
    session.flush()
    for r in roles:
        session.add(UserRole(user_id=u.id, role=r))
    session.flush()
    return u


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clinic", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--model-owner", action="store_true", help="выдать полномочие ответственного за модель")
    a = ap.parse_args()
    pw = os.environ.get("LMB_BOOTSTRAP_PASSWORD")
    if not pw:
        raise SystemExit("Задайте пароль в LMB_BOOTSTRAP_PASSWORD")
    eng = create_engine(get_settings().admin_database_url)
    with Session(eng) as s, s.begin():
        c = create_clinic(s, a.clinic)
        create_user(s, c.id, a.email, a.name, pw, ["clinic_admin"], model_owner=a.model_owner)
    print("Клиника и администратор созданы")


if __name__ == "__main__":
    main()
