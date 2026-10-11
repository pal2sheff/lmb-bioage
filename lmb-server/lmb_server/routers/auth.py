"""Вход, выход, второй фактор (TOTP), управление пользователями клиники."""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import COOKIE, Principal, current_allow_no_totp, require
from ..models import ROLES, AuthSession, User, UserRole
from ..security import (DUMMY_HASH, decrypt, encrypt, hash_password, new_token, new_totp_secret,
                        session_expiry, token_hash, verify_password, verify_totp)
from ..settings import get_settings

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str
    totp: Optional[str] = None


def me_out(p: Principal) -> dict:
    u = p.user
    return {"id": str(u.id), "email": u.email, "full_name": u.full_name, "clinic_id": str(u.clinic_id),
            "roles": sorted(p.roles), "is_model_owner": u.is_model_owner, "totp_enabled": u.totp_enabled,
            # токен CSRF читается только JS того же источника (CORS не включён); нужен после перезагрузки страницы
            "csrf_token": p.session.csrf_token}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not user or not ok or not user.is_active:
        audit.log(db, request, user.id if user else None, user.clinic_id if user else None, "login_failed")
        db.commit()
        raise HTTPException(401, "Неверный адрес или пароль")
    if user.totp_enabled:
        if not body.totp or not verify_totp(decrypt(user.totp_secret_enc), body.totp):
            audit.log(db, request, user.id, user.clinic_id, "login_failed", details={"reason": "totp"})
            db.commit()
            raise HTTPException(401, "Неверный код второго фактора")
    token, csrf = new_token(), new_token()
    s = AuthSession(user_id=user.id, token_hash=token_hash(token), csrf_token=csrf, expires_at=session_expiry())
    db.add(s)
    audit.log(db, request, user.id, user.clinic_id, "login")
    st = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, secure=st.cookie_secure, samesite="strict",
                        max_age=st.session_hours * 3600, path="/")
    roles = sorted(db.scalars(select(UserRole.role).where(UserRole.user_id == user.id)))
    db.commit()
    return {"csrf_token": csrf, "roles": roles, "totp_enabled": user.totp_enabled}


@router.post("/auth/logout")
def logout(request: Request, response: Response, p: Principal = Depends(current_allow_no_totp),
           db: Session = Depends(get_db)):
    p.session.revoked_at = dt.datetime.now(dt.timezone.utc)
    audit.log(db, request, p.id, p.clinic_id, "logout")
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(p: Principal = Depends(current_allow_no_totp)):
    return me_out(p)


@router.post("/auth/totp/enroll")
def totp_enroll(request: Request, p: Principal = Depends(current_allow_no_totp), db: Session = Depends(get_db)):
    if p.user.totp_enabled:
        raise HTTPException(409, "Второй фактор уже подключён")
    secret = new_totp_secret()
    p.user.totp_secret_enc = encrypt(secret)
    audit.log(db, request, p.id, p.clinic_id, "totp_enroll_started")
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=p.user.email, issuer_name="LMB BioAge")
    return {"otpauth_uri": uri, "secret": secret}


class TotpConfirm(BaseModel):
    code: str


@router.post("/auth/totp/confirm")
def totp_confirm(body: TotpConfirm, request: Request, p: Principal = Depends(current_allow_no_totp),
                 db: Session = Depends(get_db)):
    if p.user.totp_enabled:
        raise HTTPException(409, "Второй фактор уже подключён")
    if not p.user.totp_secret_enc or not verify_totp(decrypt(p.user.totp_secret_enc), body.code):
        raise HTTPException(422, "Неверный код")
    p.user.totp_enabled = True
    audit.log(db, request, p.id, p.clinic_id, "totp_enabled")
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- пользователи клиники
class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(min_length=1)
    password: str
    roles: list[str]
    patient_id: Optional[str] = None


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, p: Principal = Depends(require("clinic_admin")),
                db: Session = Depends(get_db)):
    bad = set(body.roles) - set(ROLES)
    if bad or not body.roles:
        raise HTTPException(422, f"Недопустимые роли: {sorted(bad) or 'пусто'}")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "Пользователь с таким адресом уже есть")
    try:
        pw = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    # Полномочие ответственного за модель администратор не выдаёт (ТЗ, раздел 2)
    u = User(clinic_id=p.clinic_id, email=body.email, full_name=body.full_name, password_hash=pw,
             patient_id=body.patient_id)
    db.add(u)
    db.flush()
    for r in body.roles:
        db.add(UserRole(user_id=u.id, role=r, granted_by=p.id))
    audit.log(db, request, p.id, p.clinic_id, "user_created", "user", u.id, details={"roles": sorted(body.roles)})
    db.commit()
    return {"id": str(u.id)}


@router.get("/users")
def list_users(p: Principal = Depends(require("clinic_admin")), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.clinic_id == p.clinic_id).order_by(User.full_name)).all()
    roles = {}
    for r in db.scalars(select(UserRole).where(UserRole.user_id.in_([u.id for u in users]))):
        roles.setdefault(r.user_id, []).append(r.role)
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "roles": sorted(roles.get(u.id, [])),
             "is_active": u.is_active, "totp_enabled": u.totp_enabled} for u in users]
