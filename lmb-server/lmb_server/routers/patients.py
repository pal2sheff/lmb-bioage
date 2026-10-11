"""Карточки пациентов. ИИН и контакты шифруются; ИИН ищется по слепому индексу."""
from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import Principal, require
from ..models import Patient
from ..security import blind_index, decrypt, encrypt, name_index, normalize_name

router = APIRouter(tags=["patients"])
CLINICAL_ID = ("doctor", "clinic_admin")


class PatientIn(BaseModel):
    last_name: str = Field(min_length=1, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: Optional[str] = Field(default=None, max_length=100)
    iin: Optional[str] = None
    birth_date: dt.date
    sex_at_birth: Literal["female", "male"]
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)

    @field_validator("iin")
    @classmethod
    def _iin(cls, v):
        if v is not None and (len(v) != 12 or not v.isdigit()):
            raise ValueError("ИИН — 12 цифр")
        return v

    @field_validator("birth_date")
    @classmethod
    def _bd(cls, v):
        if v > dt.date.today() or v.year < 1900:
            raise ValueError("Недопустимая дата рождения")
        return v


class PatientPatch(BaseModel):
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    middle_name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)
    change_reason: str = Field(min_length=3)


def out(pt: Patient, full: bool = True) -> dict:
    d = {"id": str(pt.id), "last_name": decrypt(pt.last_name_enc), "first_name": decrypt(pt.first_name_enc),
         "middle_name": decrypt(pt.middle_name_enc), "birth_date": pt.birth_date.isoformat(),
         "sex_at_birth": pt.sex_at_birth, "pseudonym_code": pt.pseudonym_code, "version": pt.version}
    if full:
        iin = decrypt(pt.iin_enc)
        d.update(iin_masked=("********" + iin[-4:]) if iin else None, phone=decrypt(pt.phone_enc),
                 email=decrypt(pt.email_enc))
    return d


def get_patient(db: Session, p: Principal, patient_id: uuid.UUID) -> Patient:
    pt = db.get(Patient, patient_id)
    if pt is None or pt.clinic_id != p.clinic_id or pt.deleted_at is not None:
        raise HTTPException(404, "Пациент не найден")
    return pt


@router.post("/patients", status_code=201)
def create_patient(body: PatientIn, request: Request, p: Principal = Depends(require(*CLINICAL_ID)),
                   db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(default=None)):
    if idempotency_key:
        prev = db.scalar(select(Patient).where(Patient.clinic_id == p.clinic_id,
                                               Patient.idempotency_key == idempotency_key))
        if prev:
            return out(prev)
    middle = body.middle_name.strip() if body.middle_name and body.middle_name.strip() else None
    pt = Patient(clinic_id=p.clinic_id, last_name_enc=encrypt(body.last_name.strip()),
                 first_name_enc=encrypt(body.first_name.strip()), middle_name_enc=encrypt(middle),
                 last_name_index=name_index(body.last_name),
                 iin_enc=encrypt(body.iin), iin_index=blind_index(body.iin),
                 birth_date=body.birth_date, sex_at_birth=body.sex_at_birth, phone_enc=encrypt(body.phone),
                 email_enc=encrypt(body.email), pseudonym_code="P-" + secrets.token_hex(5).upper(),
                 idempotency_key=idempotency_key, created_by=p.id)
    db.add(pt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Пациент с таким ИИН уже есть в клинике")
    audit.log(db, request, p.id, p.clinic_id, "patient_created", "patient", pt.id, pt.id)
    db.commit()
    return out(pt)


@router.get("/patients")
def search_patients(request: Request, query: str = "", iin: Optional[str] = None,
                    p: Principal = Depends(require(*CLINICAL_ID)), db: Session = Depends(get_db)):
    q = select(Patient).where(Patient.clinic_id == p.clinic_id, Patient.deleted_at.is_(None))
    """Поиск по ИИН или по полной фамилии (точное совпадение без учёта регистра и ё/е).

    ФИО зашифровано, поэтому поиск по началу фамилии невозможен. Без запроса возвращаются
    50 последних карточек; сортировка по алфавиту выполняется после расшифровки.
    """
    if iin:
        q = q.where(Patient.iin_index == blind_index(iin))
    elif query.strip():
        q = q.where(Patient.last_name_index == name_index(query))
    rows = db.scalars(q.order_by(Patient.created_at.desc()).limit(50)).all()
    result = sorted((out(r, full=False) for r in rows),
                    key=lambda d: (normalize_name(d["last_name"]), normalize_name(d["first_name"])))
    audit.log(db, request, p.id, p.clinic_id, "patient_search", details={"results": len(rows)})
    db.commit()
    return result


@router.get("/patients/{patient_id}")
def read_patient(patient_id: uuid.UUID, request: Request, p: Principal = Depends(require(*CLINICAL_ID)),
                 db: Session = Depends(get_db)):
    pt = get_patient(db, p, patient_id)
    audit.log(db, request, p.id, p.clinic_id, "patient_viewed", "patient", pt.id, pt.id)
    db.commit()
    return out(pt)


@router.patch("/patients/{patient_id}")
def update_patient(patient_id: uuid.UUID, body: PatientPatch, request: Request,
                   if_match: str = Header(), p: Principal = Depends(require(*CLINICAL_ID)),
                   db: Session = Depends(get_db)):
    pt = get_patient(db, p, patient_id)
    if if_match.strip('"') != str(pt.version):
        raise HTTPException(412, "Карточка изменена другим пользователем; обновите данные")
    changed = []
    for f in ("last_name", "first_name", "middle_name"):
        v = getattr(body, f)
        if v is not None:
            setattr(pt, f + "_enc", encrypt(v.strip() or None))
            if f == "last_name":
                pt.last_name_index = name_index(v)
            changed.append(f)
    for f in ("phone", "email"):
        v = getattr(body, f)
        if v is not None:
            setattr(pt, f + "_enc", encrypt(v))
            changed.append(f)
    pt.version += 1
    audit.log(db, request, p.id, p.clinic_id, "patient_updated", "patient", pt.id, pt.id,
              details={"fields": changed, "reason": body.change_reason})
    db.commit()
    return out(pt)
