"""Связь сервера с расчётным модулем: снимок входов → lmb_engine → результат.

Снимок — неизменяемый JSON со ссылками на редакции наблюдений. Повторный расчёт
по сохранённому снимку и сохранённой конфигурации модели воспроизводит результат.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from lmb_engine import __version__ as ENGINE_VERSION
from lmb_engine.core import Encounter as EngineEncounter
from lmb_engine.core import Measurement, Qualifier, Review, Sex
from lmb_engine.pipeline import run

from .models import Encounter, Observation, Patient, QuestionnaireAnswer


def build_payload(db: Session, enc: Encounter, patient: Patient) -> dict:
    obs = db.scalars(select(Observation).where(Observation.encounter_id == enc.id,
                                               Observation.is_current.is_(True))).all()
    answers = db.scalars(select(QuestionnaireAnswer).where(QuestionnaireAnswer.encounter_id == enc.id,
                                                           QuestionnaireAnswer.is_current.is_(True))).all()
    return {
        "encounter_id": str(enc.id),
        "encounter_date": enc.encounter_date.isoformat(),
        "birth_date": patient.birth_date.isoformat(),
        "sex": patient.sex_at_birth,
        "measurements": {
            o.definition_code: {
                "observation_id": str(o.id), "revision": o.revision, "value": o.value_num,
                "unit": o.unit_original, "qualifier": o.qualifier,
                "sample_date": o.sample_date.isoformat() if o.sample_date else None,
                "sample_id": o.sample_id, "review": o.review_status,
            } for o in sorted(obs, key=lambda x: x.definition_code)
        },
        "flags": {a.item_code: a.answer for a in sorted(answers, key=lambda x: x.item_code)},
    }


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def to_engine(payload: dict) -> EngineEncounter:
    ms = {}
    for code, m in payload["measurements"].items():
        ms[code] = Measurement(
            value=m["value"], unit=m["unit"] or "", qualifier=Qualifier(m["qualifier"]),
            sample_date=dt.date.fromisoformat(m["sample_date"]) if m["sample_date"] else None,
            sample_id=m["sample_id"], review=Review(m["review"]))
    return EngineEncounter(
        birth_date=dt.date.fromisoformat(payload["birth_date"]),
        encounter_date=dt.date.fromisoformat(payload["encounter_date"]),
        sex=Sex(payload["sex"]), measurements=ms, flags=dict(payload["flags"]))


def calculate(payload: dict, config: dict) -> dict:
    return run(to_engine(payload), config)


__all__ = ["build_payload", "payload_sha256", "to_engine", "calculate", "ENGINE_VERSION"]
