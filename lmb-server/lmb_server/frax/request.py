"""FRAXRequest: проверенный набор расчётных признаков из снимка визита (ТЗ 10.1.3–10.1.4).

Во внешний сервис уходят только эти признаки: без ФИО, ИИН, контактов, идентификаторов
пациента и визита, без даты рождения. Набор признаков о здоровье без ФИО не считается
автоматически анонимным: основание передачи определяет правовая проверка.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from lmb_engine.core import age_full_years

FRAX_AGE = (40, 90)
FRAX_BMI = (5.0, 125.0)  # документация CSV FRAXplus: вне диапазона строка отклоняется
RISK_FACTORS = ("prior_fragility_fracture", "parent_hip_fracture", "smoking_current", "glucocorticoids",
                "rheumatoid_arthritis", "secondary_osteoporosis", "alcohol_3plus")


@dataclass(frozen=True)
class FemoralNeckBMD:
    kind: str                      # "t_score" | "g_cm2"
    value: float
    device_make: Optional[str] = None
    site: str = "femoral_neck"
    method: str = "DXA"


@dataclass(frozen=True)
class FRAXRequest:
    age_years: int
    sex: str                       # "female" | "male" (внутреннее кодирование, не кодирование API)
    bmi_kg_m2: float
    risk_factors: dict             # код -> "yes" | "no"
    assumed_no_fields: tuple = field(default_factory=tuple)
    fn_bmd: Optional[FemoralNeckBMD] = None
    model_country: str = "Kazakhstan"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["assumed_no_fields"] = list(self.assumed_no_fields)
        return d

    def input_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class BuildResult:
    request: Optional[FRAXRequest]
    status: str                    # ready | missing_data | not_applicable | invalid_input | awaiting_review
    problems: list


def build_request(payload: dict, allow_assumed_no: bool = False) -> BuildResult:
    """Собрать запрос из снимка визита. Ничего не подставляет вместо отсутствующих данных."""
    missing, invalid, review, na = [], [], [], []
    ms, flags = payload["measurements"], payload["flags"]

    age = age_full_years(dt.date.fromisoformat(payload["birth_date"]), dt.date.fromisoformat(payload["encounter_date"]))
    if not FRAX_AGE[0] <= age <= FRAX_AGE[1]:
        na.append(f"Возраст {age} вне диапазона FRAX {FRAX_AGE[0]}–{FRAX_AGE[1]}; граница не подставляется")

    def num(code, unit):
        m = ms.get(code)
        if m is None or m["value"] is None or m["review"] == "rejected":
            missing.append(code)
            return None
        if m["qualifier"] != "eq":
            invalid.append(f"{code}: цензурированное значение")
            return None
        if m["review"] == "pending":
            review.append(f"{code}: не подтверждено врачом")
        if m["unit"] != unit:
            invalid.append(f"{code}: нужна единица {unit}")
            return None
        return float(m["value"])

    h, w = num("height_cm", "cm"), num("weight_kg", "kg")
    bmi = None
    if h and w:
        bmi = w / (h / 100) ** 2
        if not FRAX_BMI[0] <= bmi <= FRAX_BMI[1]:
            invalid.append(f"ИМТ {bmi:.1f} вне диапазона FRAX {FRAX_BMI[0]}–{FRAX_BMI[1]}")

    raw = flags.get("frax_assumed_no") or []
    assumed = set(raw.split(",") if isinstance(raw, str) else raw) - {""}
    if assumed and not allow_assumed_no:
        invalid.append("Ответ «нет — сведений нет, по правилу FRAX» не разрешён настройками")
    factors = {}
    for f in RISK_FACTORS:
        v = flags.get(f, "unknown")
        if v == "unknown":
            if f in assumed and allow_assumed_no:
                factors[f] = "no"
            else:
                missing.append(f)    # «неизвестно» не равно «нет»
        else:
            factors[f] = v

    bmd = None
    has_t = "fn_tscore" in ms and ms["fn_tscore"]["value"] is not None
    has_g = "fn_bmd" in ms and ms["fn_bmd"]["value"] is not None
    if has_t and has_g:
        review.append("Указаны и T-показатель, и МПК в г/см²: выберите один источник")
    elif has_t:
        v = num("fn_tscore", "SD")
        if v is not None:
            bmd = FemoralNeckBMD("t_score", v)
    elif has_g:
        v = num("fn_bmd", "g/cm2")
        dev = flags.get("fn_bmd_device_make")
        if v is not None:
            if not dev:
                missing.append("fn_bmd_device_make")
            bmd = FemoralNeckBMD("g_cm2", v, dev)

    if invalid:
        return BuildResult(None, "invalid_input", invalid + missing + review + na)
    if na:
        return BuildResult(None, "not_applicable", na)
    if missing:
        return BuildResult(None, "missing_data", missing)
    if review:
        return BuildResult(None, "awaiting_review", review)
    sex = payload["sex"]
    return BuildResult(FRAXRequest(age, sex, bmi, factors, tuple(sorted(assumed & set(RISK_FACTORS))), bmd),
                       "ready", [])
