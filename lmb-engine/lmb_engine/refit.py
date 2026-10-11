"""Пересчёт нормализации по реальной референтной выборке (подготовка к v0.4).

Без заполненной записи выборки (config/reference/*.json) пересчёт не выполняется:
статус reference_sample_missing, коэффициенты не создаются.

Модель ожидания та же, что в v0.3: T = b0 + b1·возраст + b2·пол + b3·возраст·пол
(пол: женщина 0, мужчина 1), T = преобразованное значение (например, ln(1+SCORE2 %)).
Разброс — стандартное отклонение остатков (n − 4 степеней свободы). Проверка — на участниках,
не использованных для подбора (разделение по участникам, а не по визитам).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable, Mapping, Optional, Sequence

SAMPLE_FIELDS = ("source", "description", "n_participants", "age_min", "age_max", "sexes", "region",
                 "inclusion_criteria", "exclusion_criteria", "score2_applicability_rules", "expectation_method",
                 "dispersion_method", "holdout_method", "date", "version")
TRANSFORMS = {"raw": lambda x: x, "log1p": math.log1p}


def load_record(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def record_status(record: Optional[Mapping]) -> tuple:
    """(статус, недостающие поля): reference_sample_missing | reference_sample_incomplete | ready."""
    if not record or not record.get("sample"):
        return "reference_sample_missing", list(SAMPLE_FIELDS)
    missing = [k for k in SAMPLE_FIELDS if record["sample"].get(k) in (None, "", [])]
    if len(missing) == len(SAMPLE_FIELDS):
        return "reference_sample_missing", missing
    return ("reference_sample_incomplete", missing) if missing else ("ready", [])


def _solve(a: list, b: list) -> list:
    """Гаусс с выбором главного элемента для малой системы (4×4)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("Вырожденная система: выборка не позволяет оценить возраст, пол и их взаимодействие")
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def _design(age: float, sex: int) -> list:
    return [1.0, age, float(sex), age * sex]


def fit_expectation(rows: Sequence[Mapping], transform: str = "log1p") -> dict:
    """rows: {participant_id, age, sex (0/1), value}. Возвращает коэффициенты и ResidualSD."""
    if transform not in TRANSFORMS:
        raise ValueError(f"преобразование «{transform}» не поддерживается")
    t = TRANSFORMS[transform]
    xs = [_design(r["age"], r["sex"]) for r in rows]
    ys = [t(r["value"]) for r in rows]
    n = len(ys)
    if n <= 4:
        raise ValueError("Слишком мало наблюдений для четырёх коэффициентов")
    xtx = [[math.fsum(x[i] * x[j] for x in xs) for j in range(4)] for i in range(4)]
    xty = [math.fsum(x[i] * y for x, y in zip(xs, ys)) for i in range(4)]
    b = _solve(xtx, xty)
    res = [y - sum(bi * xi for bi, xi in zip(b, x)) for x, y in zip(xs, ys)]
    sd = math.sqrt(math.fsum(e * e for e in res) / (n - 4))
    return {"transform": transform, "intercept": b[0], "age_coef": b[1], "sex_coef": b[2], "age_sex_coef": b[3],
            "residual_sd": sd, "n": n, "n_participants": len({r["participant_id"] for r in rows})}


def split_by_participant(rows: Iterable[Mapping], holdout_fraction: float = 0.3, salt: str = "lmb") -> tuple:
    """Детерминированное разделение по участникам: все визиты одного человека — в одной части."""
    train, hold = [], []
    for r in rows:
        h = int(hashlib.sha256(f"{salt}:{r['participant_id']}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        (hold if h < holdout_fraction else train).append(r)
    return train, hold


def validate(params: Mapping, rows: Sequence[Mapping]) -> dict:
    """Средняя Z и SD Z на проверочной части; при корректной нормализации ≈ 0 и ≈ 1."""
    t = TRANSFORMS[params["transform"]]
    zs = []
    for r in rows:
        x = _design(r["age"], r["sex"])
        e = params["intercept"] * x[0] + params["age_coef"] * x[1] + params["sex_coef"] * x[2] + params["age_sex_coef"] * x[3]
        zs.append((t(r["value"]) - e) / params["residual_sd"])
    n = len(zs)
    mean = math.fsum(zs) / n
    sd = math.sqrt(math.fsum((z - mean) ** 2 for z in zs) / (n - 1)) if n > 1 else float("nan")
    return {"n": n, "mean_z": mean, "sd_z": sd}


def refit(record: Optional[Mapping], rows: Optional[Sequence[Mapping]], transform: str = "log1p") -> dict:
    """Полный цикл: проверка записи выборки → подбор на обучающей части → проверка на отложенной."""
    status, missing = record_status(record)
    if status != "ready" or not rows:
        return {"status": status if status != "ready" else "reference_sample_missing", "missing_fields": missing,
                "fit": None, "validation": None}
    train, hold = split_by_participant(rows)
    fit = fit_expectation(train, transform)
    return {"status": "fitted_not_approved", "missing_fields": [], "fit": fit, "validation": validate(fit, hold),
            "note": "Новые коэффициенты требуют утверждения владельцем и новой версии модели; v0.3 не меняется."}
