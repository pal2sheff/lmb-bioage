"""Базовые типы расчётного модуля LMB BioAge.

Модуль не зависит от веба и базы данных. Все значения передаются явно.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class Status(str, Enum):
    CALCULATED = "calculated"
    MISSING_DATA = "missing_data"
    INVALID_INPUT = "invalid_input"
    NOT_APPLICABLE = "not_applicable"
    MODEL_NOT_CONFIGURED = "model_not_configured"
    INTEGRATION_NOT_CONFIGURED = "integration_not_configured"
    EXTERNAL_ERROR = "external_error"
    AWAITING_REVIEW = "awaiting_review"
    NOT_INCLUDED = "not_included"


class Tri(str, Enum):
    """Логическое поле с тремя состояниями. unknown не равно no."""
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class Sex(str, Enum):
    FEMALE = "female"
    MALE = "male"


class Qualifier(str, Enum):
    EQ = "eq"
    LT = "lt"   # «<x»
    GT = "gt"   # «>x»


class Review(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Measurement:
    """Одно наблюдение в исходной единице. value=None означает отсутствие числа."""
    value: Optional[float]
    unit: str
    qualifier: Qualifier = Qualifier.EQ
    sample_date: Optional[dt.date] = None
    sample_id: Optional[str] = None
    review: Review = Review.CONFIRMED


@dataclass
class Encounter:
    """Снимок входных данных одного визита для расчёта индексов."""
    birth_date: Optional[dt.date]
    encounter_date: dt.date
    sex: Optional[Sex]
    measurements: Mapping[str, Measurement] = field(default_factory=dict)
    flags: Mapping[str, Any] = field(default_factory=dict)

    def flag(self, code: str) -> Tri:
        v = self.flags.get(code)
        if v is None:
            return Tri.UNKNOWN
        return Tri(v) if not isinstance(v, Tri) else v


@dataclass
class IndexResult:
    code: str
    version: int
    status: Status
    value: Optional[float] = None
    unit: Optional[str] = None
    extra: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    missing_fields: list = field(default_factory=list)
    reasons: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.code}@{self.version}"

    def to_dict(self) -> dict:
        return {
            "code": self.code, "version": self.version, "status": self.status.value,
            "value": self.value, "unit": self.unit, "extra": self.extra,
            "warnings": self.warnings, "missing_fields": self.missing_fields,
            "reasons": self.reasons,
        }


def age_full_years(birth: dt.date, on: dt.date) -> int:
    """Число полных лет на дату обследования."""
    years = on.year - birth.year
    if (on.month, on.day) < (birth.month, birth.day):
        years -= 1
    return years


def age_exact_years(birth: dt.date, on: dt.date) -> float:
    """Точный возраст в годах: полные годы + доля прожитого года с последнего дня рождения.

    Используется только там, где модель принимает непрерывный возраст (SCORE2/SCORE2-OP,
    как в официальном калькуляторе HeartScore). Для рождённых 29 февраля в невисокосный
    год днём рождения считается 28 февраля.
    """
    full = age_full_years(birth, on)

    def anniversary(year: int) -> dt.date:
        try:
            return birth.replace(year=year)
        except ValueError:          # 29 февраля в невисокосный год
            return dt.date(year, 2, 28)

    last = anniversary(birth.year + full)
    nxt = anniversary(birth.year + full + 1)
    return full + (on - last).days / (nxt - last).days


def is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
