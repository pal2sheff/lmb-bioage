"""Синтетические пациенты для тестов. Реальных данных нет."""
import datetime as dt

from lmb_engine.core import Encounter, Measurement, Sex

ENC_DATE = dt.date(2026, 10, 10)

UNITS = {
    "height_cm": "cm", "weight_kg": "kg", "waist_cm": "cm",
    "glucose_fasting": "mmol/L", "insulin_fasting": "uU/mL", "tg": "mmol/L", "tc": "mmol/L",
    "hdl": "mmol/L", "creatinine_serum": "umol/L", "u_albumin": "mg/L", "u_creatinine": "mmol/L",
    "ast": "U/L", "alt": "U/L", "platelets": "10^9/L", "neutrophils_abs": "10^9/L",
    "lymphocytes_abs": "10^9/L", "visbody_asm": "kg", "sbp_mmhg": "mmHg",
}

CLEAN_FLAGS = {"fasting_status": "yes", "insulin_therapy": "no", "diabetes": "no",
               "acute_kidney_change": "no", "creatinine_idms": "yes", "acute_liver_condition": "no",
               "acute_infection": "no"}


def birth_for_age(age: int) -> dt.date:
    return dt.date(ENC_DATE.year - age, 1, 1)


def enc(age=50, sex=Sex.FEMALE, flags=None, units=None, **values) -> Encounter:
    units = {**UNITS, **(units or {})}
    ms = {}
    for k, v in values.items():
        ms[k] = v if isinstance(v, Measurement) else Measurement(v, units[k])
    return Encounter(
        birth_date=birth_for_age(age) if age is not None else None,
        encounter_date=ENC_DATE, sex=sex, measurements=ms,
        flags={**CLEAN_FLAGS, **(flags or {})},
    )
