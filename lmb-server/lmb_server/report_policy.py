"""Что из результата расчёта может попасть в пациентский отчёт.

Решение владельца 11.10.2026: исследовательский расчёт LMB v0.3 показывается только врачу
(по переключателю режима тестирования) и по умолчанию не включается в пациентский отчёт.
Модуль — точка, через которую будущий пациентский PDF получает данные.
"""
from __future__ import annotations

import copy
from typing import Mapping

RESEARCH_KEYS = ("research",)


def patient_result(result: Mapping, *, include_research: bool = False) -> dict:
    """Копия результата для пациентского отчёта; исследовательский блок исключён по умолчанию.

    include_research=True допустим только при отдельном разрешении версии модели
    (usage_permission = patient_report_allowed) — проверяет вызывающий код.
    """
    out = copy.deepcopy(dict(result))
    if not include_research:
        for k in RESEARCH_KEYS:
            out.pop(k, None)
    return out
