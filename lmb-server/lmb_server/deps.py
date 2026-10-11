"""Текущий пользователь, проверка CSRF, второй фактор и роли."""
from __future__ import annotations

import datetime as dt
import hmac
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, User, UserRole
from .security import token_hash
from .settings import get_settings

COOKIE = "lmb_session"
STAFF = {"doctor", "clinic_admin", "researcher"}
SAFE = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: User
    session: AuthSession
    roles: set

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def clinic_id(self) -> uuid.UUID:
        return self.user.clinic_id

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & STAFF) or self.user.is_model_owner


def bind_clinic(db: Session, clinic_id: Optional[uuid.UUID]) -> None:
    """Привязать транзакцию к клинике: политики RLS пропустят только её строки."""
    db.info["clinic_id"] = clinic_id
    db.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(clinic_id) if clinic_id else ""})


def _principal(request: Request, db: Session, allow_without_totp: bool) -> Principal:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Требуется вход")
    now = dt.datetime.now(dt.timezone.utc)
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if s is None or s.revoked_at is not None or s.expires_at <= now:
        raise HTTPException(401, "Сеанс недействителен")
    user = db.get(User, s.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Учётная запись отключена")
    if request.method not in SAFE:
        sent = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, s.csrf_token):
            raise HTTPException(403, "Неверный CSRF-токен")
    roles = set(db.scalars(select(UserRole.role).where(UserRole.user_id == user.id)))
    p = Principal(user, s, roles)
    if (not allow_without_totp and p.is_staff and get_settings().require_staff_totp and not user.totp_enabled):
        raise HTTPException(403, "Для доступа нужен второй фактор: подключите TOTP")
    bind_clinic(db, user.clinic_id)
    return p


def current(request: Request, db: Session = Depends(get_db)) -> Principal:
    return _principal(request, db, allow_without_totp=False)


def current_allow_no_totp(request: Request, db: Session = Depends(get_db)) -> Principal:
    return _principal(request, db, allow_without_totp=True)


def require(*roles: str, model_owner: bool = False) -> Callable:
    def dep(p: Principal = Depends(current)) -> Principal:
        if model_owner and p.user.is_model_owner:
            return p
        if not (p.roles & set(roles)):
            raise HTTPException(403, "Недостаточно прав")
        return p
    return dep
