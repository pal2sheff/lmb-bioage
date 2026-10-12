"""Проверка входов перед расчётом индекса.

Gate собирает причины по категориям и определяет итоговый статус по приоритету:
invalid_input > missing_data > awaiting_review > not_applicable > calculated.
Статус not_applicable не мешает вычислить значение, если математика допустима
(ТЗ, раздел 6): такой результат показывается врачу, но в домен не входит.
"""
from __future__ import annotations

from typing import Optional

from .core import Encounter, IndexResult, Qualifier, Review, Sex, Status, Tri, age_full_years
from .units import INPUTS


class Gate:
    def __init__(self, enc: Encounter, code: str, version: int):
        self.enc = enc
        self.code = code
        self.version = version
        self.missing: list = []
        self.invalid: list = []
        self.review: list = []
        self.not_applicable: list = []
        self.warnings: list = []
        self.invalid_fields: list = []

    # --- входные значения
    def value(self, key: str) -> Optional[float]:
        """Значение в канонической единице или None (причина записана)."""
        m = self.enc.measurements.get(key)
        d = INPUTS[key]
        if m is None or m.value is None:
            self.missing.append(key)
            return None
        if m.review == Review.REJECTED:
            self.missing.append(key)
            return None
        if m.qualifier != Qualifier.EQ:
            sign = "<" if m.qualifier == Qualifier.LT else ">"
            self.invalid_fields.append(key)
            self.invalid.append(f"{d.name_ru}: значение «{sign}{m.value}» — правило для значений ниже/выше предела "
                                f"определения не утверждено")
            return None
        if m.unit in d.rejected_units:
            self.invalid_fields.append(key)
            self.invalid.append(f"{d.name_ru}: {d.rejected_units[m.unit]}")
            return None
        conv = d.conversions.get(m.unit)
        if conv is None:
            self.invalid_fields.append(key)
            self.invalid.append(f"{d.name_ru}: единица «{m.unit}» не поддерживается")
            return None
        v = conv(float(m.value))
        if d.plausible is not None:
            lo, hi = d.plausible
            if not (lo <= v <= hi):
                self.invalid_fields.append(key)
                ru = lambda x: f"{round(x, 3):g}".replace(".", ",")  # noqa: E731
                self.invalid.append(f"{d.name_ru}: {ru(v)} вне допустимого диапазона {ru(lo)}–{ru(hi)} — проверьте "
                                    f"значение и единицу")
                return None
        if m.review == Review.PENDING:
            self.review.append(f"{d.name_ru}: значение не подтверждено врачом")
        return v

    def optional(self, key: str) -> Optional[float]:
        """Необязательный вход: отсутствие не делает индекс неполным, ошибочное значение — делает."""
        m = self.enc.measurements.get(key)
        if m is None or m.value is None:
            return None
        return self.value(key)

    def age(self) -> Optional[int]:
        if self.enc.birth_date is None:
            self.missing.append("birth_date")
            return None
        a = age_full_years(self.enc.birth_date, self.enc.encounter_date)
        if a < 0:
            self.invalid.append("Дата рождения позже даты обследования")
            return None
        return a

    def sex(self) -> Optional[Sex]:
        if self.enc.sex is None:
            self.missing.append("sex_at_birth")
        return self.enc.sex

    def consistent(self, issue: Optional[dict]) -> None:
        """Межполевая проверка (consistency.py): противоречие делает индекс invalid_input."""
        if issue:
            self.invalid.append(issue["message"])
            self.invalid_fields.extend(issue["fields"])

    def same_sample(self, *keys: str, label: str = "") -> None:
        """Показатели должны быть из одного образца/даты; иначе — проверка врачом."""
        ms = [self.enc.measurements.get(k) for k in keys]
        ms = [m for m in ms if m is not None and m.value is not None]
        ids = {m.sample_id for m in ms if m.sample_id is not None}
        dates = {m.sample_date for m in ms if m.sample_date is not None}
        if len(ids) > 1 or len(dates) > 1:
            self.review.append(f"{label or ', '.join(keys)}: показатели из разных образцов или дат")

    def require_flag_yes(self, flag: str, text: str) -> None:
        """Условие должно быть подтверждено (например, натощак)."""
        v = self.enc.flag(flag)
        if v == Tri.NO:
            self.not_applicable.append(f"{text}: нет")
        elif v == Tri.UNKNOWN:
            self.review.append(f"{text}: неизвестно")

    def exclude_if_yes(self, flag: str, text: str, unknown_to_review: bool = True,
                       unknown_warning: bool = False) -> None:
        v = self.enc.flag(flag)
        if v == Tri.YES:
            self.not_applicable.append(text)
        elif v == Tri.UNKNOWN:
            if unknown_to_review:
                self.review.append(f"{text}: неизвестно")
            elif unknown_warning:
                self.warnings.append(f"{text}: сведения отсутствуют")

    # --- результат
    def blocked(self) -> bool:
        return bool(self.missing or self.invalid)

    def result(self, value: Optional[float] = None, unit: Optional[str] = None,
               extra: Optional[dict] = None) -> IndexResult:
        if self.invalid:
            status = Status.INVALID_INPUT
        elif self.missing:
            status = Status.MISSING_DATA
        elif self.review:
            status = Status.AWAITING_REVIEW
        elif self.not_applicable:
            status = Status.NOT_APPLICABLE
        else:
            status = Status.CALCULATED
        if status in (Status.INVALID_INPUT, Status.MISSING_DATA):
            value = None
            extra = {}
        return IndexResult(
            code=self.code, version=self.version, status=status, value=value, unit=unit,
            extra=extra or {}, warnings=list(self.warnings), missing_fields=list(self.missing),
            invalid_fields=list(dict.fromkeys(self.invalid_fields)),
            reasons=self.invalid + self.review + self.not_applicable,
        )
