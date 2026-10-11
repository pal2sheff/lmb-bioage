"""Проверки согласованности входов между полями (аудит владельца 11.10.2026).

Противоречивые данные не исправляются и не обходятся: зависимые индексы получают
invalid_input, а значит, и домен, и итог LMB не считаются до исправления.
Каждая проверка возвращает список проблем {fields, message} — интерфейс показывает
сообщение рядом с перечисленными полями.
"""
from __future__ import annotations

from typing import Optional

from .core import Encounter, Qualifier
from .units import INPUTS

# Допуск на округление при сложении показателей ОАК: каждое значение обычно выдаётся с шагом 0,1 × 10⁹/л,
# поэтому ошибка округления каждого слагаемого и лейкоцитов — не более 0,05.
CBC_ROUNDING = 0.05
CBC_PARTS = ("neutrophils_abs", "lymphocytes_abs")
ACR_MGG_PER_MGMMOL = 8.84


def _ru(x: float) -> str:
    """Число для сообщения врачу: десятичная запятая, без лишних знаков."""
    return f"{round(x, 3):g}".replace(".", ",")


def _num(enc: Encounter, code: str) -> Optional[float]:
    """Значение в канонической единице, если оно точное и пересчитывается; иначе None."""
    m = enc.measurements.get(code)
    if m is None or m.value is None or m.qualifier != Qualifier.EQ:
        return None
    conv = INPUTS[code].conversions.get(m.unit) if code in INPUTS else None
    return conv(float(m.value)) if conv else None


def cbc_issue(enc: Encounter) -> Optional[dict]:
    """Сумма абсолютных нейтрофилов и лимфоцитов не может превышать лейкоциты (с учётом округления)."""
    wbc = _num(enc, "wbc")
    if wbc is None:
        return None
    parts = {c: _num(enc, c) for c in CBC_PARTS}
    parts = {c: v for c, v in parts.items() if v is not None}
    if not parts:
        return None
    total = sum(parts.values())
    tol = CBC_ROUNDING * (len(parts) + 1)
    if total <= wbc + tol:
        return None
    names = " + ".join(INPUTS[c].name_ru.lower() for c in parts)
    return {"code": "cbc_sum", "fields": [*parts, "wbc"],
            "message": (f"Общий анализ крови противоречив: {names} ({_ru(total)} × 10⁹/л) больше лейкоцитов "
                        f"({_ru(wbc)} × 10⁹/л). Проверьте значения и единицы.")}


def frax_issue(enc: Encounter) -> Optional[dict]:
    """Риск перелома бедра не может превышать риск основных остеопоротических переломов."""
    major, hip = _num(enc, "frax_major_10y_pct"), _num(enc, "frax_hip_10y_pct")
    if major is None or hip is None:
        return None
    if hip > major:
        return {"code": "frax_hip_gt_major", "fields": ["frax_major_10y_pct", "frax_hip_10y_pct"],
                "message": (f"FRAX: риск перелома бедра ({_ru(hip)} %) больше риска основных остеопоротических "
                            f"переломов ({_ru(major)} %). Проверьте перенос из официального калькулятора.")}
    return None


def acr_lab_mg_mmol(enc: Encounter) -> tuple:
    """(значение мг/ммоль | None, проблема | None) для готового ACR лаборатории."""
    m = enc.measurements.get("acr_lab")
    if m is None or m.value is None:
        return None, None
    if m.qualifier != Qualifier.EQ:
        return None, "ACR лаборатории указан со знаком «<» или «>» — правило для таких значений не утверждено"
    factor = {"mg/mmol": 1.0, "mg/g": 1 / ACR_MGG_PER_MGMMOL}.get(m.unit)
    if factor is None:
        return None, "ACR лаборатории: укажите единицу мг/ммоль или мг/г"
    v = float(m.value) * factor
    if not 0 <= v <= 5000:
        return None, "ACR лаборатории вне технического диапазона"
    return v, None


def all_issues(enc: Encounter) -> list:
    return [x for x in (cbc_issue(enc), frax_issue(enc)) if x]
