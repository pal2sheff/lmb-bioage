"""API FRAX: проверка входов, задача автоматического запроса, ручной ввод, выбор результата."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import Principal, require
from ..frax import service
from ..models import Encounter, ExternalRequest
from ..settings import get_settings
from lmb_engine.core import age_full_years

from ..frax.request import FRAX_AGE
from .attachments import get_attachment
from .clinical import get_encounter
from .patients import get_patient

router = APIRouter(tags=["frax"])
DOCTOR = require("doctor")


def job_out(j: ExternalRequest, current_hash: Optional[str] = None) -> dict:
    return {"id": str(j.id), "encounter_id": str(j.encounter_id), "provider": j.provider, "status": j.status,
            "frax_major_10y_pct": j.major_10y_pct, "frax_hip_10y_pct": j.hip_10y_pct, "with_bmd": j.with_bmd,
            "national_model": j.national_model, "provider_version": j.provider_version,
            "source": "manual" if j.provider == "manual" else "automatic",
            "error_code": j.error_code, "error_detail": j.error_detail, "attempts": j.attempts,
            "is_active_choice": j.is_active_choice, "conflict_note": j.conflict_note,
            "inputs_current": (True if (j.provider == "manual" and not j.inputs_bound)
                               else (j.frax_input_hash == current_hash) if current_hash else None),
            "manual_calculated_on": j.manual_calculated_on.isoformat() if j.manual_calculated_on else None,
            "manual_source_note": j.manual_source_note, "inputs_bound": j.inputs_bound,
            "attachment_id": str(j.attachment_id) if j.attachment_id else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "responded_at": j.responded_at.isoformat() if j.responded_at else None}


def _inputs(db: Session, p: Principal, encounter_id: uuid.UUID):
    e = get_encounter(db, p, encounter_id)
    pt = get_patient(db, p, e.patient_id)
    return e, service.current_inputs(db, e, pt)


@router.get("/encounters/{encounter_id}/frax/inputs")
def frax_inputs(encounter_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    """Что уйдёт во внешний сервис и чего не хватает. Идентификаторы пациента не входят."""
    _, built = _inputs(db, p, encounter_id)
    return {"status": built.status, "problems": built.problems,
            "request": built.request.to_dict() if built.request else None,
            "input_hash": built.request.input_hash() if built.request else None,
            "provider": service.provider_factory().name}


@router.post("/encounters/{encounter_id}/frax-jobs", status_code=202)
def start_frax(encounter_id: uuid.UUID, request: Request, p: Principal = Depends(DOCTOR),
               db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(default=None)):
    e, built = _inputs(db, p, encounter_id)
    if built.request is None:
        raise HTTPException(422, {"status": built.status, "problems": built.problems})
    job, created = service.create_job(db, p.clinic_id, p.id, e, built.request, idempotency_key)
    warn = None
    used, limit = service.usage_this_year(db), get_settings().frax_annual_limit
    if used >= 0.9 * limit:
        warn = f"Использовано {used} из {limit} API-расчётов FRAX в этом году"
    if created:
        audit.log(db, request, p.id, p.clinic_id, "frax_requested", "external_request", job.id, e.patient_id,
                  details={"provider": job.provider})
    db.commit()
    return {**job_out(job, built.request.input_hash()), "created": created, "quota_warning": warn}


def _get_job(db: Session, p: Principal, job_id: uuid.UUID) -> ExternalRequest:
    j = db.get(ExternalRequest, job_id)
    if j is None or j.clinic_id != p.clinic_id:
        raise HTTPException(404, "Запрос FRAX не найден")
    return j


@router.get("/frax-jobs/{job_id}")
def read_frax(job_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    j = _get_job(db, p, job_id)
    e = db.get(Encounter, j.encounter_id)
    built = service.current_inputs(db, e, get_patient(db, p, e.patient_id))
    return job_out(j, built.request.input_hash() if built.request else None)


@router.get("/encounters/{encounter_id}/frax-jobs")
def list_frax(encounter_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    e, built = _inputs(db, p, encounter_id)
    h = built.request.input_hash() if built.request else None
    rows = db.scalars(select(ExternalRequest).where(ExternalRequest.encounter_id == e.id)
                      .order_by(ExternalRequest.created_at)).all()
    return [job_out(j, h) for j in rows]


@router.post("/frax-jobs/{job_id}/retry", status_code=202)
def retry_frax(job_id: uuid.UUID, request: Request, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    j = _get_job(db, p, job_id)
    if j.status not in ("external_error", "integration_not_configured") or j.provider == "manual":
        raise HTTPException(409, "Повтор возможен только после ошибки автоматического запроса")
    e, built = _inputs(db, p, j.encounter_id)
    if built.request is None or built.request.input_hash() != j.frax_input_hash:
        raise HTTPException(409, "Данные визита изменились: создайте новый запрос")
    prov = service.provider_factory()
    if prov.name == "not_configured":
        raise HTTPException(409, "Доступ к FRAX API не настроен")
    new = ExternalRequest(clinic_id=p.clinic_id, encounter_id=j.encounter_id, provider=prov.name,
                          frax_input_hash=j.frax_input_hash, request_payload=j.request_payload, status="queued",
                          is_test=prov.name == "fake_test", created_by=p.id)
    db.add(new)
    db.flush()
    audit.log(db, request, p.id, p.clinic_id, "frax_retry", "external_request", new.id, e.patient_id)
    db.commit()
    return job_out(new, j.frax_input_hash)


class ManualIn(BaseModel):
    frax_major_10y_pct: float = Field(ge=0, le=100)
    frax_hip_10y_pct: float = Field(ge=0, le=100)
    with_bmd: bool
    calculated_on: dt.date
    national_model: str = Field(pattern="^Kazakhstan$")
    source_note: str = Field(min_length=3, max_length=300)
    attachment_id: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def _hip_not_above_major(self):
        # риск перелома бедра не может превышать риск основных остеопоротических переломов (аудит 11.10.2026)
        if self.frax_hip_10y_pct > self.frax_major_10y_pct:
            raise ValueError("Риск перелома бедра больше риска основных остеопоротических переломов — проверьте перенос")
        return self


@router.post("/encounters/{encounter_id}/frax-manual", status_code=201)
def manual_frax(encounter_id: uuid.UUID, body: ManualIn, request: Request, p: Principal = Depends(DOCTOR),
                db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(default=None)):
    """Ручной ввод официального результата FRAX (модель Казахстана).

    Работает независимо от анкеты в системе: если факторы риска внесены полностью, результат
    привязывается к ним и устаревает при их изменении; если нет — он действует для визита
    с пометкой «входы в системе неполные». Проверки применимости те же: возраст 40–90 лет.
    """
    e = get_encounter(db, p, encounter_id)
    pt = get_patient(db, p, e.patient_id)
    age = age_full_years(pt.birth_date, e.encounter_date)
    if not FRAX_AGE[0] <= age <= FRAX_AGE[1]:
        raise HTTPException(422, f"FRAX неприменим: возраст {age} вне диапазона {FRAX_AGE[0]}–{FRAX_AGE[1]} лет")
    if body.calculated_on > dt.date.today():
        raise HTTPException(422, "Дата расчёта в будущем")
    if body.attachment_id is not None:
        a = get_attachment(db, p, body.attachment_id)
        if a.encounter_id != e.id:
            raise HTTPException(422, "Файл относится к другому визиту")
    built = service.current_inputs(db, e, pt)
    if built.request is not None:
        if body.with_bmd != (built.request.fn_bmd is not None):
            raise HTTPException(422, "Признак «с МПК» не совпадает с данными визита")
        payload, h, bound = built.request.to_dict(), built.request.input_hash(), True
    else:
        payload, h, bound = {"inputs_incomplete": built.problems}, f"unbound:{uuid.uuid4().hex}", False
    j = service.add_manual(db, p.clinic_id, p.id, e, payload, h, bound, body.frax_major_10y_pct,
                           body.frax_hip_10y_pct, body.with_bmd, body.calculated_on, body.source_note,
                           body.attachment_id, idempotency_key)
    audit.log(db, request, p.id, p.clinic_id, "frax_manual_entered", "external_request", j.id, e.patient_id,
              details={"inputs_bound": bound, "with_attachment": body.attachment_id is not None})
    db.commit()
    return job_out(j, built.request.input_hash() if built.request else None)


@router.post("/frax-jobs/{job_id}/activate")
def activate_frax(job_id: uuid.UUID, request: Request, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    j = _get_job(db, p, job_id)
    if j.status != "calculated":
        raise HTTPException(409, "Действующим может быть только полученный результат")
    service.activate(db, j)
    e = db.get(Encounter, j.encounter_id)
    audit.log(db, request, p.id, p.clinic_id, "frax_activated", "external_request", j.id, e.patient_id,
              details={"provider": j.provider})
    db.commit()
    return job_out(j)
