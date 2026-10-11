"""Cardio: SCORE2 (40–69 лет) и SCORE2-OP (70–89 лет), регион риска high.

Параметры читаются из config/algorithms/*.json вместе с SHA-256 файла.
Пока в файле verification.heartscore_verified = false, индекс не активирован:
статус model_not_configured, значение не выдаётся (ТЗ, раздел 6.6). Для сверки
с HeartScore используется функция compute(), которая не участвует в профиле.
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

from .core import Encounter, IndexResult, Sex, Status, Tri, age_exact_years
from .gate import Gate

ALG_DIR = Path(__file__).resolve().parent.parent / "config" / "algorithms"
FILES = {"score2": "score2_2021.json", "score2_op": "score2op_2021.json"}
TERMS = ("cage", "smoking", "csbp", "ctchol", "chdl", "smoking_cage", "csbp_cage", "ctchol_cage", "chdl_cage")


@lru_cache(maxsize=None)
def load_params(code: str) -> dict:
    raw = (ALG_DIR / FILES[code]).read_bytes()
    p = json.loads(raw.decode("utf-8"))
    p["_sha256"] = hashlib.sha256(raw).hexdigest()
    _validate(p)
    return p


def _validate(p: Mapping) -> None:
    for sex in ("male", "female"):
        c = p["coefficients"][sex]
        missing = [t for t in TERMS if t not in c]
        if missing:
            raise ValueError(f"{p['code']}: нет коэффициентов {missing} для {sex}")
        if not 0 < p["baseline_survival"][sex] < 1:
            raise ValueError(f"{p['code']}: базовая выживаемость вне (0, 1)")
        if p["region"] not in p["calibration"][sex]:
            raise ValueError(f"{p['code']}: нет калибровки региона {p['region']}")


def compute(params: Mapping, age: float, sex: Sex, smoker: bool, sbp: float, tc: float, hdl: float,
            region: Optional[str] = None) -> dict:
    """Чистая формула. Возвращает линейный предиктор, некалиброванный и калиброванный риск (доли)."""
    s = sex.value
    cen = params["centering"]
    cage = (age - cen["age"][0]) / cen["age"][1]
    csbp = (sbp - cen["sbp"][0]) / cen["sbp"][1]
    ctc = (tc - cen["tc"][0]) / cen["tc"][1]
    chdl = (hdl - cen["hdl"][0]) / cen["hdl"][1]
    sm = 1.0 if smoker else 0.0
    b = params["coefficients"][s]
    lp = math.fsum([
        b["cage"] * cage, b["smoking"] * sm, b["csbp"] * csbp, b["ctchol"] * ctc, b["chdl"] * chdl,
        b["smoking_cage"] * sm * cage, b["csbp_cage"] * csbp * cage,
        b["ctchol_cage"] * ctc * cage, b["chdl_cage"] * chdl * cage,
    ])
    shift = params.get("mean_linear_predictor", {}).get(s, 0.0)
    uncal = 1 - params["baseline_survival"][s] ** math.exp(lp - shift)
    s1, s2 = params["calibration"][s][region or params["region"]]
    risk = 1 - math.exp(-math.exp(s1 + s2 * math.log(-math.log(1 - uncal))))
    return {"linear_predictor": lp, "uncalibrated": uncal, "risk": risk}


def model_for_age(age: Optional[int]) -> Optional[str]:
    """SCORE2 для 40–69 лет, SCORE2-OP для 70–89 лет; вне диапазона — неприменимо."""
    if age is None:
        return None
    for code in ("score2", "score2_op"):
        lo, hi = load_params(code)["age_range"]
        if lo <= age <= hi:
            return code
    return None


EXCLUSIONS = (
    ("ascvd", "Установленное атеросклеротическое ССЗ"),
    ("ckd_known", "Хроническая болезнь почек"),
    ("fh", "Семейная гиперхолестеринемия"),
    ("very_high_single_risk_factor", "Очень высокий отдельный фактор риска по оценке врача"),
)


def _index(code: str, enc: Encounter, params: Optional[Mapping] = None) -> IndexResult:
    p = params or load_params(code)
    g = Gate(enc, code, p["version"])
    age = g.age()
    sex = g.sex()
    sbp = g.value("sbp_mmhg")
    tc = g.value("tc")
    hdl = g.value("hdl")
    g.same_sample("tc", "hdl", label="общий холестерин и ЛПВП")
    smoking = enc.flag("smoking_current")
    if smoking == Tri.UNKNOWN:
        g.missing.append("smoking_current")
    if age is not None:
        lo, hi = p["age_range"]
        if not lo <= age <= hi:
            title = {"score2": "SCORE2", "score2_op": "SCORE2-OP"}.get(code, code)
            g.not_applicable.append(f"Возраст {age} вне диапазона {title} ({lo}–{hi} лет)")
    diabetes = enc.flags.get("diabetes")
    if diabetes in (None, "unknown"):
        g.review.append("Наличие сахарного диабета: неизвестно")
    elif diabetes != "no":
        g.not_applicable.append("Сахарный диабет: SCORE2/SCORE2-OP не применяются")
    for flag, text in EXCLUSIONS:
        g.exclude_if_yes(flag, text)
    # Вне области применения формула не вычисляется: диабетический член и возраст
    # вне диапазона дали бы вводящее в заблуждение число.
    if g.blocked() or g.not_applicable or g.review:
        return g.result()
    if not p["verification"]["heartscore_verified"]:
        r = IndexResult(code=code, version=p["version"], status=Status.MODEL_NOT_CONFIGURED,
                        reasons=["Алгоритм не активирован: ожидает сверки с HeartScore (регион high)"],
                        warnings=list(g.warnings))
        r.extra = {"params_sha256": p["_sha256"]}
        return r
    # Возраст в формуле — непрерывный, как в публикации и в HeartScore; границы применимости —
    # по полным годам. Сверка HS04 (10.10.2026) совпадает только с непрерывным возрастом.
    age_exact = age_exact_years(enc.birth_date, enc.encounter_date)
    out = compute(p, age_exact, sex, smoking == Tri.YES, sbp, tc, hdl)
    return g.result(out["risk"] * 100, "%", {"region": p["region"], "params_sha256": p["_sha256"],
                                             "age_exact_years": age_exact,
                                             "linear_predictor": out["linear_predictor"],
                                             "uncalibrated_pct": out["uncalibrated"] * 100})


def score2(enc: Encounter, params: Optional[Mapping] = None) -> IndexResult:
    return _index("score2", enc, params)


def score2_op(enc: Encounter, params: Optional[Mapping] = None) -> IndexResult:
    return _index("score2_op", enc, params)
