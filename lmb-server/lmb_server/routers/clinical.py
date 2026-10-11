"""Визиты, наблюдения с редакциями, анкета, расчёт через lmb_engine."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lmb_engine.units import INPUTS

from .. import __version__ as APP_VERSION
from .. import audit
from ..catalog import DOCTOR_ONLY_ITEMS, QUESTIONNAIRE_ITEMS, validate_answer
from ..db import get_db
from ..deps import Principal, require
from ..engine_bridge import ENGINE_VERSION, build_payload, calculate, payload_sha256
from ..models import (CalculationRun, Encounter, InputSnapshot, ModelVersion, Observation,
                      ObservationDefinition, QuestionnaireAnswer)
from .patients import get_patient

router = APIRouter(tags=["clinical"])
DOCTOR = require("doctor")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def get_encounter(db: Session, p: Principal, encounter_id: uuid.UUID) -> Encounter:
    e = db.get(Encounter, encounter_id)
    if e is None or e.clinic_id != p.clinic_id:
        raise HTTPException(404, "Визит не найден")
    return e


def enc_out(e: Encounter) -> dict:
    return {"id": str(e.id), "patient_id": str(e.patient_id), "encounter_date": e.encounter_date.isoformat(),
            "status": e.status, "doctor_id": str(e.doctor_id)}


# ---------------------------------------------------------------- визиты
class EncounterIn(BaseModel):
    encounter_date: dt.date


@router.post("/patients/{patient_id}/encounters", status_code=201)
def create_encounter(patient_id: uuid.UUID, body: EncounterIn, request: Request, p: Principal = Depends(DOCTOR),
                     db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(default=None)):
    pt = get_patient(db, p, patient_id)
    if body.encounter_date < pt.birth_date or body.encounter_date > dt.date.today() + dt.timedelta(days=1):
        raise HTTPException(422, "Недопустимая дата обследования")
    if idempotency_key:
        prev = db.scalar(select(Encounter).where(Encounter.clinic_id == p.clinic_id,
                                                 Encounter.idempotency_key == idempotency_key))
        if prev:
            return enc_out(prev)
    e = Encounter(clinic_id=p.clinic_id, patient_id=pt.id, encounter_date=body.encounter_date, doctor_id=p.id,
                  idempotency_key=idempotency_key)
    db.add(e)
    db.flush()
    audit.log(db, request, p.id, p.clinic_id, "encounter_created", "encounter", e.id, pt.id)
    db.commit()
    return enc_out(e)


@router.get("/patients/{patient_id}/encounters")
def list_encounters(patient_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    pt = get_patient(db, p, patient_id)
    rows = db.scalars(select(Encounter).where(Encounter.patient_id == pt.id)
                      .order_by(Encounter.encounter_date.desc())).all()
    return [enc_out(e) for e in rows]


@router.get("/encounters/{encounter_id}")
def read_encounter(encounter_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    return enc_out(get_encounter(db, p, encounter_id))


# ---------------------------------------------------------------- наблюдения
class ObservationIn(BaseModel):
    code: str
    value: Optional[float] = None
    unit: Optional[str] = None
    qualifier: Literal["eq", "lt", "gt"] = "eq"
    sample_date: Optional[dt.date] = None
    sample_id: Optional[str] = Field(default=None, max_length=64)
    source: Literal["manual", "import", "device"] = "manual"
    method: Optional[str] = Field(default=None, max_length=200)


class ObservationRevisionIn(BaseModel):
    value: Optional[float] = None
    unit: Optional[str] = None
    qualifier: Literal["eq", "lt", "gt"] = "eq"
    sample_date: Optional[dt.date] = None
    sample_id: Optional[str] = Field(default=None, max_length=64)
    change_reason: str = Field(min_length=3, max_length=500)


def obs_out(o: Observation) -> dict:
    return {"chain_id": str(o.chain_id), "id": str(o.id), "code": o.definition_code, "revision": o.revision,
            "value": o.value_num, "unit": o.unit_original, "qualifier": o.qualifier,
            "sample_date": o.sample_date.isoformat() if o.sample_date else None, "sample_id": o.sample_id,
            "source": o.source, "review_status": o.review_status, "is_current": o.is_current,
            "change_reason": o.change_reason, "created_at": o.created_at.isoformat() if o.created_at else None}


def _check_unit(code: str, unit: Optional[str], value: Optional[float]) -> None:
    d = INPUTS.get(code)
    allowed = set(d.conversions) | set(d.rejected_units) if d else {"mg/mmol", "mg/g"}
    if value is not None and unit not in allowed:
        raise HTTPException(422, f"Единица «{unit}» не предусмотрена для {code}: {sorted(allowed)}")


@router.post("/encounters/{encounter_id}/observations", status_code=201)
def add_observation(encounter_id: uuid.UUID, body: ObservationIn, request: Request, p: Principal = Depends(DOCTOR),
                    db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(default=None)):
    e = get_encounter(db, p, encounter_id)
    if db.get(ObservationDefinition, body.code) is None:
        raise HTTPException(422, f"Неизвестный показатель {body.code}")
    _check_unit(body.code, body.unit, body.value)
    if idempotency_key:
        prev = db.scalar(select(Observation).where(Observation.clinic_id == p.clinic_id,
                                                   Observation.idempotency_key == idempotency_key))
        if prev:
            return obs_out(prev)
    exists = db.scalar(select(Observation).where(Observation.encounter_id == e.id,
                                                 Observation.definition_code == body.code,
                                                 Observation.is_current.is_(True),
                                                 Observation.review_status != "rejected"))
    if exists:
        raise HTTPException(409, "Показатель уже внесён в этот визит; исправление — новой редакцией (PATCH)")
    manual = body.source == "manual"
    o = Observation(clinic_id=p.clinic_id, encounter_id=e.id, definition_code=body.code, chain_id=uuid.uuid4(),
                    revision=1, value_num=body.value, qualifier=body.qualifier, unit_original=body.unit,
                    sample_date=body.sample_date, sample_id=body.sample_id, source=body.source, method=body.method,
                    review_status="confirmed" if manual else "pending",
                    confirmed_by=p.id if manual else None, confirmed_at=_now() if manual else None,
                    idempotency_key=idempotency_key, created_by=p.id)
    db.add(o)
    db.flush()
    audit.log(db, request, p.id, p.clinic_id, "observation_added", "observation", o.id, e.patient_id,
              details={"code": body.code, "source": body.source})
    db.commit()
    return obs_out(o)


@router.get("/encounters/{encounter_id}/observations")
def list_observations(encounter_id: uuid.UUID, history: bool = False, p: Principal = Depends(DOCTOR),
                      db: Session = Depends(get_db)):
    e = get_encounter(db, p, encounter_id)
    q = select(Observation).where(Observation.encounter_id == e.id)
    if not history:
        q = q.where(Observation.is_current.is_(True))
    return [obs_out(o) for o in db.scalars(q.order_by(Observation.definition_code, Observation.revision))]


def _current(db: Session, p: Principal, chain_id: uuid.UUID) -> Observation:
    o = db.scalar(select(Observation).where(Observation.chain_id == chain_id, Observation.is_current.is_(True))
                  .with_for_update())
    if o is None or o.clinic_id != p.clinic_id:
        raise HTTPException(404, "Наблюдение не найдено")
    return o


@router.patch("/observations/{chain_id}")
def revise_observation(chain_id: uuid.UUID, body: ObservationRevisionIn, request: Request,
                       if_match: str = Header(), p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    """Исправление создаёт новую редакцию; прежняя сохраняется и остаётся в снимках расчётов."""
    old = _current(db, p, chain_id)
    if if_match.strip('"') != str(old.revision):
        raise HTTPException(412, f"Текущая редакция — {old.revision}; обновите данные")
    _check_unit(old.definition_code, body.unit, body.value)
    old.is_current = False
    db.flush()
    new = Observation(clinic_id=old.clinic_id, encounter_id=old.encounter_id, definition_code=old.definition_code,
                      chain_id=old.chain_id, revision=old.revision + 1, supersedes_id=old.id,
                      value_num=body.value, qualifier=body.qualifier, unit_original=body.unit,
                      sample_date=body.sample_date, sample_id=body.sample_id, source="manual",
                      method=old.method, review_status="confirmed", confirmed_by=p.id, confirmed_at=_now(),
                      change_reason=body.change_reason, created_by=p.id)
    db.add(new)
    db.flush()
    e = db.get(Encounter, old.encounter_id)
    audit.log(db, request, p.id, p.clinic_id, "observation_revised", "observation", new.id, e.patient_id,
              details={"code": old.definition_code, "revision": new.revision})
    db.commit()
    return obs_out(new)


class ReviewIn(BaseModel):
    decision: Literal["confirm", "reject"]


@router.post("/observations/{chain_id}/review")
def review_observation(chain_id: uuid.UUID, body: ReviewIn, request: Request, if_match: str = Header(),
                       p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    o = _current(db, p, chain_id)
    if if_match.strip('"') != str(o.revision):
        raise HTTPException(412, f"Текущая редакция — {o.revision}")
    if o.review_status != "pending":
        raise HTTPException(409, "Наблюдение уже проверено")
    o.review_status = "confirmed" if body.decision == "confirm" else "rejected"
    o.confirmed_by, o.confirmed_at = p.id, _now()
    e = db.get(Encounter, o.encounter_id)
    audit.log(db, request, p.id, p.clinic_id, f"observation_{o.review_status}", "observation", o.id, e.patient_id)
    db.commit()
    return obs_out(o)


# ---------------------------------------------------------------- анкета
class QuestionnaireIn(BaseModel):
    answers: dict[str, str]


@router.put("/encounters/{encounter_id}/questionnaire")
def put_questionnaire(encounter_id: uuid.UUID, body: QuestionnaireIn, request: Request,
                      p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    e = get_encounter(db, p, encounter_id)
    for code, val in body.answers.items():
        if code not in QUESTIONNAIRE_ITEMS:
            raise HTTPException(422, f"Неизвестный пункт анкеты {code}")
        err = validate_answer(code, val)
        if err:
            raise HTTPException(422, err)
    changed = []
    for code, val in sorted(body.answers.items()):
        cur = db.scalar(select(QuestionnaireAnswer).where(QuestionnaireAnswer.encounter_id == e.id,
                                                          QuestionnaireAnswer.item_code == code,
                                                          QuestionnaireAnswer.is_current.is_(True)))
        if cur is not None and cur.answer == val:
            continue
        rev = 1
        if cur is not None:
            cur.is_current = False
            rev = cur.revision + 1
            db.flush()
        db.add(QuestionnaireAnswer(clinic_id=p.clinic_id, encounter_id=e.id, item_code=code, answer=val,
                                   revision=rev, answered_by_role="doctor", created_by=p.id))
        changed.append(code)
    audit.log(db, request, p.id, p.clinic_id, "questionnaire_updated", "encounter", e.id, e.patient_id,
              details={"items": changed})
    db.commit()
    return get_questionnaire(encounter_id, p, db)


@router.get("/encounters/{encounter_id}/questionnaire")
def get_questionnaire(encounter_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    e = get_encounter(db, p, encounter_id)
    cur = {a.item_code: a for a in db.scalars(select(QuestionnaireAnswer).where(
        QuestionnaireAnswer.encounter_id == e.id, QuestionnaireAnswer.is_current.is_(True)))}
    # отсутствующий ответ показывается как «неизвестно», а не «нет»
    return {code: {"name": name,
                   "answer": cur[code].answer if code in cur else ("unknown" if allowed not in (None, "frax_list") else None),
                   "answered": code in cur, "doctor_only": code in DOCTOR_ONLY_ITEMS}
            for code, (name, allowed) in QUESTIONNAIRE_ITEMS.items()}


# ---------------------------------------------------------------- расчёт
class CalcIn(BaseModel):
    model_version: str = "v0.3"


def current_model_version(db: Session, label: str) -> Optional[ModelVersion]:
    """Последняя неархивная редакция версии модели."""
    return db.scalar(select(ModelVersion).where(ModelVersion.label == label, ModelVersion.state != "archived")
                     .order_by(ModelVersion.revision.desc()).limit(1))


def run_out(r: CalculationRun, mv: ModelVersion) -> dict:
    return {"calculation_id": str(r.id), "encounter_id": str(r.encounter_id), "snapshot_id": str(r.snapshot_id),
            "model_version": mv.label, "model_revision": mv.revision, "model_config_sha256": r.model_config_sha256,
            "engine_version": r.engine_version, "app_version": r.app_version, "status": r.status,
            "bioage_years": r.bioage_years, "delta_years": r.delta_years, "result": r.result,
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.post("/encounters/{encounter_id}/calculations", status_code=201)
def start_calculation(encounter_id: uuid.UUID, body: CalcIn, request: Request, p: Principal = Depends(DOCTOR),
                      db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(default=None)):
    e = get_encounter(db, p, encounter_id)
    mv = current_model_version(db, body.model_version)
    if mv is None:
        raise HTTPException(404, "Версия модели не найдена")
    if idempotency_key:
        prev = db.scalar(select(CalculationRun).where(CalculationRun.clinic_id == p.clinic_id,
                                                      CalculationRun.idempotency_key == idempotency_key))
        if prev:
            return run_out(prev, db.get(ModelVersion, prev.model_version_id))
    pt = get_patient(db, p, e.patient_id)
    from ..frax.service import augment_payload
    payload = augment_payload(db, e, build_payload(db, e, pt))
    sha = payload_sha256(payload)
    snap = db.scalar(select(InputSnapshot).where(InputSnapshot.encounter_id == e.id, InputSnapshot.sha256 == sha))
    if snap is None:
        snap = InputSnapshot(clinic_id=p.clinic_id, encounter_id=e.id, payload=payload, sha256=sha)
        db.add(snap)
        db.flush()
    result = calculate(payload, mv.config)
    r = CalculationRun(clinic_id=p.clinic_id, encounter_id=e.id, snapshot_id=snap.id, model_version_id=mv.id,
                       model_config_sha256=mv.config_sha256, engine_version=ENGINE_VERSION,
                       app_version=APP_VERSION, status=result["status"], result=result,
                       bioage_years=result["bioage_years"], delta_years=result["delta_years"],
                       idempotency_key=idempotency_key, started_by=p.id)
    db.add(r)
    db.flush()
    audit.log(db, request, p.id, p.clinic_id, "calculation_run", "calculation", r.id, e.patient_id,
              details={"model_version": mv.label, "model_revision": mv.revision, "status": r.status})
    db.commit()
    return run_out(r, mv)


def _get_run(db: Session, p: Principal, run_id: uuid.UUID) -> CalculationRun:
    r = db.get(CalculationRun, run_id)
    if r is None or r.clinic_id != p.clinic_id:
        raise HTTPException(404, "Расчёт не найден")
    return r


@router.get("/calculations/{run_id}")
def read_calculation(run_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    r = _get_run(db, p, run_id)
    return run_out(r, db.get(ModelVersion, r.model_version_id))


@router.get("/encounters/{encounter_id}/calculations")
def list_calculations(encounter_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    e = get_encounter(db, p, encounter_id)
    rows = db.scalars(select(CalculationRun).where(CalculationRun.encounter_id == e.id)
                      .order_by(CalculationRun.created_at)).all()
    return [{"calculation_id": str(r.id), "status": r.status, "created_at": r.created_at.isoformat(),
             "engine_version": r.engine_version} for r in rows]


@router.post("/calculations/{run_id}/reproduce")
def reproduce(run_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    """Пересчитать по сохранённому снимку и сохранённой конфигурации и сравнить с исходным результатом."""
    r = _get_run(db, p, run_id)
    snap = db.get(InputSnapshot, r.snapshot_id)
    mv = db.get(ModelVersion, r.model_version_id)
    again = calculate(snap.payload, mv.config)
    return {"identical": again == r.result, "same_engine_version": r.engine_version == ENGINE_VERSION,
            "same_model_config": mv.config_sha256 == r.model_config_sha256}
