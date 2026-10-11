"""Справочник входов: канонические единицы, утверждённые конверсии, технические диапазоны.

Конверсии — только утверждённые владельцем (ТЗ, раздел 5). Единицы, для которых
коэффициент не утверждён, отклоняются с понятной причиной, а не пересчитываются.
Диапазоны технические — для отсева ошибок ввода, а не клинические нормы.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# Утверждённые коэффициенты (ТЗ, раздел 5)
GLUCOSE_MMOL_TO_MGDL = 18.0182
TG_MMOL_TO_MGDL = 88.57
CREATININE_UMOL_PER_MGDL = 88.4
ACR_MGMMOL_TO_MGG = 8.84


def _identity(x: float) -> float:
    return x


@dataclass(frozen=True)
class InputDef:
    code: str
    name_ru: str
    canonical_unit: str
    conversions: dict            # единица -> функция перевода в каноническую
    plausible: Optional[tuple]   # (min, max) в канонической единице
    rejected_units: dict         # единица -> причина отказа


CELL = {"10^9/L": _identity, "x10^9/L": _identity, "×10⁹/л": _identity,
        "10^3/uL": _identity, "10^3/µL": _identity}
CELL_REJECT = {"%": "Нужны абсолютные значения ×10⁹/л; проценты не принимаются"}

INPUTS = {d.code: d for d in [
    InputDef("height_cm", "Рост", "cm", {"cm": _identity, "m": lambda x: x * 100}, (100, 230), {}),
    InputDef("weight_kg", "Масса тела", "kg", {"kg": _identity}, (25, 300), {}),
    InputDef("waist_cm", "Окружность талии", "cm", {"cm": _identity}, (40, 200), {}),
    InputDef("sbp_mmhg", "Систолическое АД", "mmHg", {"mmHg": _identity}, (70, 260), {}),
    InputDef("glucose_fasting", "Глюкоза натощак", "mmol/L",
             {"mmol/L": _identity, "mg/dL": lambda x: x / GLUCOSE_MMOL_TO_MGDL}, (1, 40), {}),
    # мЕд/л и мкЕд/мл численно равны (одна и та же единица), это не конверсия.
    InputDef("insulin_fasting", "Инсулин натощак", "uU/mL",
             {"uU/mL": _identity, "µU/mL": _identity, "uIU/mL": _identity, "µIU/mL": _identity,
              "mU/L": _identity, "mIU/L": _identity}, (0.5, 300),
             {"pmol/L": "Перевод инсулина из пмоль/л не выполняется: нет утверждённой конверсии для метода лаборатории"}),
    InputDef("tg", "Триглицериды", "mmol/L",
             {"mmol/L": _identity, "mg/dL": lambda x: x / TG_MMOL_TO_MGDL}, (0.1, 50), {}),
    InputDef("tc", "Общий холестерин", "mmol/L", {"mmol/L": _identity}, (1, 20),
             {"mg/dL": "Коэффициент перевода холестерина из мг/дл не утверждён"}),
    InputDef("hdl", "ЛПВП", "mmol/L", {"mmol/L": _identity}, (0.1, 5),
             {"mg/dL": "Коэффициент перевода ЛПВП из мг/дл не утверждён"}),
    InputDef("creatinine_serum", "Креатинин сыворотки", "umol/L",
             {"umol/L": _identity, "µmol/L": _identity,
              "mg/dL": lambda x: x * CREATININE_UMOL_PER_MGDL}, (10, 2000), {}),
    InputDef("u_albumin", "Альбумин мочи", "mg/L", {"mg/L": _identity}, (0, 5000), {}),
    InputDef("u_creatinine", "Креатинин мочи", "mmol/L", {"mmol/L": _identity}, (0.5, 40), {}),
    InputDef("ast", "АСТ", "U/L", {"U/L": _identity, "IU/L": _identity}, (1, 5000), {}),
    InputDef("alt", "АЛТ", "U/L", {"U/L": _identity, "IU/L": _identity}, (1, 5000), {}),
    InputDef("platelets", "Тромбоциты", "10^9/L", CELL, (5, 1500), CELL_REJECT),
    InputDef("neutrophils_abs", "Нейтрофилы абс.", "10^9/L", CELL, (0.1, 100), CELL_REJECT),
    InputDef("lymphocytes_abs", "Лимфоциты абс.", "10^9/L", CELL, (0.1, 100), CELL_REJECT),
    # Контрольный показатель PhenoAge (не входит в LMB v0.3). Перевод г/дл → г/л и мг/дл → мг/л — смена
    # десятичного множителя внутри одной единицы массы, а не лабораторный коэффициент.
    InputDef("wbc", "Лейкоциты", "10^9/L", CELL, (0.5, 200), CELL_REJECT),
    InputDef("mcv", "Средний объём эритроцита (MCV)", "fL", {"fL": _identity}, (40, 160), {}),
    InputDef("rdw", "Ширина распределения эритроцитов (RDW-CV)", "%", {"%": _identity}, (5, 40),
             {"fL": "Нужен RDW-CV в %; RDW-SD (фл) не подставляется"}),
    InputDef("albumin_serum", "Альбумин сыворотки", "g/L", {"g/L": _identity, "g/dL": lambda x: x * 10}, (10, 70), {}),
    InputDef("crp", "С-реактивный белок (высокочувствительный)", "mg/L",
             {"mg/L": _identity, "mg/dL": lambda x: x * 10}, (0.01, 500), {}),
    InputDef("alp", "Щелочная фосфатаза", "U/L", {"U/L": _identity, "IU/L": _identity}, (5, 3000), {}),
    InputDef("visbody_asm", "Масса мышц конечностей", "kg", {"kg": _identity}, (5, 60), {}),
    # МПК только шейки бедра (позвоночник и общий проксимальный отдел не подставляются)
    InputDef("fn_tscore", "T-показатель шейки бедра (референс NHANES III)", "SD", {"SD": _identity}, (-6, 6), {}),
    InputDef("fn_bmd", "МПК шейки бедра", "g/cm2", {"g/cm2": _identity}, (0.2, 2.0), {}),
    # Результаты официального сервиса FRAX (или подтверждённый ручной ввод врача)
    InputDef("frax_major_10y_pct", "FRAX: 10-летний риск основных остеопоротических переломов", "%",
             {"%": _identity}, (0, 100), {}),
    InputDef("frax_hip_10y_pct", "FRAX: 10-летний риск перелома бедра", "%", {"%": _identity}, (0, 100), {}),
]}
