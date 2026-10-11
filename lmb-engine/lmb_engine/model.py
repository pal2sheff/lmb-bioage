"""Авторская модель LMB BioAge: нормализация, доменные оценки, интеграл v0.3.

Коэффициенты v0.3 заданы владельцем и не корректируются (ТЗ, раздел 8).
Отсутствующие параметры не придумываются: итог блокируется с перечнем причин.
Конфигурация — только данные; произвольный код и выражения не выполняются.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .core import IndexResult, Sex, Status, is_finite_number

DOMAINS_V03 = ("cardio", "metabolic", "renal", "hepatic", "inflammation", "brain", "bone")
NOT_INCLUDED_V03 = ("muscle", "adaptive")
ALL_DOMAINS = DOMAINS_V03 + NOT_INCLUDED_V03

# Зафиксированное выражение v0.3 (контекст проекта, раздел 3; промт, раздел 7)
V03_INTERCEPT = 0.08
V03_WEIGHTS = {"cardio": 0.7, "metabolic": 1.5, "renal": 1.3, "hepatic": 1.0,
               "inflammation": 1.4, "brain": 1.2, "bone": 0.9}

# raw и log1p — обозначения из пакета владельца (LMB_Claude_Data_1): raw ≡ identity, log1p ≡ ln1p
TRANSFORMS = ("identity", "raw", "ln", "ln1p", "log1p", "log10")
RULES = ("single", "mean", "weighted_sum", "max", "min")
# Разрешённые пересчёты единиц входа нормализации: только утверждённые в ТЗ коэффициенты
UNIT_CONVERSIONS = {("mg/mmol", "mg/g"): 8.84}
NORM_KEYS = ("transform", "intercept", "age_coef", "sex_coef", "age_sex_coef", "sign", "residual_sd")
LMB_SEX_CODE = {Sex.FEMALE: 0, Sex.MALE: 1}   # только для LMB-нормализации


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------- проверка конфигурации
@dataclass
class ConfigCheck:
    errors: list = field(default_factory=list)     # делают версию недопустимой
    gaps: list = field(default_factory=list)       # отсутствующие параметры -> incomplete

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def complete(self) -> bool:
        return self.valid and not self.gaps


def config_sha256(config: Mapping) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def check_config(config: Mapping) -> ConfigCheck:
    c = ConfigCheck()
    integ = config.get("integral", {})
    if config.get("version", "").startswith("v0.3"):
        if integ.get("intercept") != V03_INTERCEPT:
            c.errors.append("integral.intercept отличается от утверждённого 0.08")
        w = integ.get("weights", {})
        for d, v in V03_WEIGHTS.items():
            if w.get(d) != v:
                c.errors.append(f"integral.weights.{d} отличается от утверждённого {v}")
        for d in NOT_INCLUDED_V03:
            if w.get(d) is not None:
                c.errors.append(f"integral.weights.{d} должен быть null в v0.3")
        if tuple(integ.get("required_domains", ())) != DOMAINS_V03:
            c.errors.append("integral.required_domains должен содержать семь доменов v0.3")
    if integ.get("z_clip") != 3.0:
        c.errors.append("integral.z_clip должен быть 3.0")

    if config.get("target_population") in (None, {}):
        c.gaps.append("target_population")

    norm = config.get("normalization", {}) or {}
    for code, p in norm.items():
        for k in NORM_KEYS:
            if p.get(k) is None:
                c.gaps.append(f"normalization.{code}.{k}")
        t = p.get("transform")
        if t is not None and t not in TRANSFORMS:
            c.errors.append(f"normalization.{code}.transform «{t}» не из перечня {TRANSFORMS}")
        inp = p.get("input") or {}
        if not inp.get("index") or not inp.get("unit"):
            c.gaps.append(f"normalization.{code}.input")
        s = p.get("sign")
        if s is not None and s not in (1, -1):
            c.errors.append(f"normalization.{code}.sign должен быть +1 или −1")
        sd = p.get("residual_sd")
        if sd is not None and not (is_finite_number(sd) and sd > 0):
            c.errors.append(f"normalization.{code}.residual_sd должен быть > 0")
        for k in ("intercept", "age_coef", "sex_coef", "age_sex_coef"):
            v = p.get(k)
            if v is not None and not is_finite_number(v):
                c.errors.append(f"normalization.{code}.{k} не число")

    domains = config.get("domains", {}) or {}
    for d in integ.get("required_domains", DOMAINS_V03):
        spec = domains.get(d)
        if not spec or spec.get("rule") is None:
            c.gaps.append(f"domains.{d}.rule")
            continue
        rule = spec["rule"]
        if rule not in RULES:
            c.errors.append(f"domains.{d}.rule «{rule}» не из перечня {RULES}")
            continue
        inputs = spec.get("inputs") or []
        if not inputs:
            c.gaps.append(f"domains.{d}.inputs")
        if rule == "mean" and len(inputs) < 2:
            c.errors.append(f"domains.{d}: правило mean требует не менее двух входов")
        if rule == "single" and len(inputs) != 1:
            c.errors.append(f"domains.{d}: правило single требует ровно один вход")
        if rule == "weighted_sum":
            ws = spec.get("weights")
            if ws is None:
                c.gaps.append(f"domains.{d}.weights")
            elif set(ws) != set(inputs) or not all(is_finite_number(x) for x in ws.values()):
                c.errors.append(f"domains.{d}.weights не совпадают с inputs или не числа")
        for i in inputs:
            if i not in norm:
                c.gaps.append(f"normalization.{i}")
    return c


def config_path(name: str = "model_v0.3.json") -> str:
    import os
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", name)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- нормализация
@dataclass
class ZScore:
    code: str
    status: Status
    t: Optional[float] = None
    expected: Optional[float] = None
    z_raw: Optional[float] = None
    z_clipped: Optional[float] = None
    warnings: list = field(default_factory=list)
    reasons: list = field(default_factory=list)


def _transform(kind: str, x: float) -> float:
    if kind in ("identity", "raw"):
        return x
    if kind == "ln":
        if x <= 0:
            raise ValueError("ln: аргумент ≤ 0")
        return math.log(x)
    if kind in ("ln1p", "log1p"):
        if x <= -1:
            raise ValueError("ln(1+x): аргумент ≤ −1")
        return math.log1p(x)
    if kind == "log10":
        if x <= 0:
            raise ValueError("log10: аргумент ≤ 0")
        return math.log10(x)
    raise ValueError(f"неизвестное преобразование {kind}")


def zscore(code: str, value: float, age: float, sex: Sex, params: Mapping, clip: float = 3.0) -> ZScore:
    """Z_raw = Sign·(T − Expected)/ResidualSD; Z_clipped = min(clip, max(−clip, Z_raw))."""
    missing = [k for k in NORM_KEYS if params.get(k) is None]
    if missing:
        return ZScore(code, Status.MODEL_NOT_CONFIGURED, reasons=[f"нет параметров: {', '.join(missing)}"])
    if not params["residual_sd"] > 0:
        return ZScore(code, Status.MODEL_NOT_CONFIGURED, reasons=["ResidualSD ≤ 0"])
    app = params.get("applicability") or {}
    if app.get("age_min") is not None and age < app["age_min"] or \
       app.get("age_max") is not None and age > app["age_max"]:
        return ZScore(code, Status.NOT_APPLICABLE, reasons=["возраст вне области нормативов"])
    if app.get("sex") and sex.value not in app["sex"]:
        return ZScore(code, Status.NOT_APPLICABLE, reasons=["пол вне области нормативов"])
    try:
        t = _transform(params["transform"], value)
    except ValueError as e:
        return ZScore(code, Status.INVALID_INPUT, reasons=[str(e)])
    s = LMB_SEX_CODE[sex]
    expected = (params["intercept"] + params["age_coef"] * age + params["sex_coef"] * s
                + params["age_sex_coef"] * age * s)
    z_raw = params["sign"] * (t - expected) / params["residual_sd"]
    z_clipped = min(clip, max(-clip, z_raw))
    warns = [f"Z_raw = {z_raw:.3f} вне ±{clip:g}; во вклад идёт {z_clipped:g}"] if z_raw != z_clipped else []
    return ZScore(code, Status.CALCULATED, t, expected, z_raw, z_clipped, warns)


# ---------------------------------------------------------------- домены
@dataclass
class DomainResult:
    domain: str
    status: Status
    score: Optional[float] = None
    coefficient: Optional[float] = None
    contribution: Optional[float] = None
    inputs: dict = field(default_factory=dict)
    input_contributions: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)


def domain_score(domain: str, spec: Optional[Mapping], zs: Mapping[str, ZScore]) -> DomainResult:
    if domain in NOT_INCLUDED_V03:
        return DomainResult(domain, Status.NOT_INCLUDED, reasons=["Не включено в эту версию модели"])
    if not spec or spec.get("rule") is None:
        return DomainResult(domain, Status.MODEL_NOT_CONFIGURED, reasons=[f"Нет правила объединения для {domain}"])
    inputs = spec.get("inputs") or []
    vals, reasons = {}, []
    worst = None
    for i in inputs:
        z = zs.get(i)
        if z is None:
            reasons.append(f"{i}: нет Z-оценки")
            worst = worst or Status.MISSING_DATA
            continue
        if z.status != Status.CALCULATED:
            reasons.append(f"{i}: {'; '.join(z.reasons) if z.reasons else z.status.value}")
            worst = worst or z.status
            continue
        vals[i] = z.z_clipped
    # политика по умолчанию: требуются все входы (ТЗ 8.1)
    if len(vals) != len(inputs):
        return DomainResult(domain, worst or Status.MISSING_DATA, inputs=vals, reasons=reasons)
    rule = spec["rule"]
    if rule == "single":
        score = vals[inputs[0]]
    elif rule == "mean":
        # фиксированный знаменатель = число обязательных входов; пропуски сюда не доходят
        score = math.fsum(vals[i] for i in inputs) / len(inputs)
    elif rule == "weighted_sum":
        score = math.fsum(spec["weights"][i] * vals[i] for i in inputs)
    elif rule == "max":
        score = max(vals.values())
    elif rule == "min":
        score = min(vals.values())
    else:
        return DomainResult(domain, Status.MODEL_NOT_CONFIGURED, reasons=[f"Неизвестное правило {rule}"])
    return DomainResult(domain, Status.CALCULATED, score=score, inputs=vals)


def attribute(domain: DomainResult, spec: Mapping, coefficient: float) -> None:
    """Вклад ветки (коэффициент × доменная оценка) и его точное разложение по показателям.

    Сумма вкладов показателей равна вкладу ветки: для mean — коэффициент × Z / n, для single —
    коэффициент × Z, для weighted_sum — коэффициент × вес × Z, для max/min — выбранный показатель.
    Это арифметика утверждённых правил; итог LMB BioAge отсюда не складывается.
    """
    if domain.status != Status.CALCULATED or domain.score is None:
        return
    vals = domain.inputs
    rule = spec["rule"]
    if rule == "mean":
        parts = {i: coefficient * z / len(vals) for i, z in vals.items()}
    elif rule == "weighted_sum":
        parts = {i: coefficient * spec["weights"][i] * z for i, z in vals.items()}
    elif rule in ("max", "min"):
        pick = (max if rule == "max" else min)(vals, key=vals.get)
        parts = {pick: coefficient * vals[pick]}
    else:  # single
        parts = {i: coefficient * z for i, z in vals.items()}
    domain.coefficient = coefficient
    domain.contribution = coefficient * domain.score
    domain.input_contributions = parts


def _inverse(kind: str, t: float) -> float:
    if kind in ("identity", "raw"):
        return t
    if kind in ("ln1p", "log1p"):
        return math.expm1(t)
    if kind == "ln":
        return math.exp(t)
    if kind == "log10":
        return 10 ** t
    raise ValueError(kind)


def trajectory(params: Mapping, sex: Sex, ages) -> list:
    """Ожидаемое значение показателя по нормализации для заданного пола на каждом возрасте
    и полоса ±1 ResidualSD — в исходных единицах показателя. Обратного пересчёта значения
    в «возраст» нет (возрастные эквиваленты не утверждены)."""
    s = LMB_SEX_CODE[sex]
    out = []
    for a in ages:
        e = params["intercept"] + params["age_coef"] * a + params["sex_coef"] * s + params["age_sex_coef"] * a * s
        sd = params["residual_sd"]
        lo, hi = sorted((_inverse(params["transform"], e - sd), _inverse(params["transform"], e + sd)))
        out.append({"age": a, "expected": _inverse(params["transform"], e), "lo": lo, "hi": hi})
    return out


# ---------------------------------------------------------------- интеграл
@dataclass
class IntegralResult:
    status: str                         # calculated | blocked
    intercept: float
    contributions: Optional[dict]
    delta_years: Optional[float]
    bioage_years: Optional[float]
    blocking_reasons: list = field(default_factory=list)


def combine(domain_scores: Mapping[str, float], weights: Mapping[str, float], intercept: float) -> tuple:
    """Чистая арифметика: вклады и DeltaBioAge по заданным доменным оценкам."""
    contributions = {d: weights[d] * domain_scores[d] for d in weights}
    delta = math.fsum([intercept, *contributions.values()])
    return contributions, delta


def integral(domains: Mapping[str, DomainResult], config: Mapping, calendar_age: Optional[float],
             check: Optional[ConfigCheck] = None) -> IntegralResult:
    integ = config["integral"]
    intercept = integ["intercept"]
    reasons = []
    check = check or check_config(config)
    if not check.valid:
        reasons += [f"Конфигурация недопустима: {e}" for e in check.errors]
    if check.gaps:
        reasons.append("Конфигурация модели неполная: " + ", ".join(check.gaps))
    if calendar_age is None:
        reasons.append("Нет календарного возраста")
    for d in integ["required_domains"]:
        r = domains.get(d)
        if r is None or r.status != Status.CALCULATED or r.score is None:
            reasons.append(f"Домен {d}: {r.status.value if r else 'нет результата'}")
    if reasons:
        # без перераспределения весов, без нулей и средних вместо пропусков
        return IntegralResult("blocked", intercept, None, None, None, reasons)
    weights = {d: integ["weights"][d] for d in integ["required_domains"]}
    contributions, delta = combine({d: domains[d].score for d in weights}, weights, intercept)
    for d, c in contributions.items():
        domains[d].coefficient = weights[d]
        domains[d].contribution = c
    return IntegralResult("calculated", intercept, contributions, delta, calendar_age + delta)


def default_v03_config() -> dict:
    """Конфигурация v0.3 в текущем виде: веса заданы, параметры нормализации отсутствуют."""
    return copy.deepcopy({
        "model": "LMB BioAge", "version": "v0.3", "synthetic_parameters": False,
        "integral": {"intercept": V03_INTERCEPT,
                     "weights": {**V03_WEIGHTS, "muscle": None, "adaptive": None},
                     "required_domains": list(DOMAINS_V03), "z_clip": 3.0},
        "target_population": None,
        "sex_coding": {"female": 0, "male": 1},
        "normalization": {},
        "domains": {d: {"rule": None, "inputs": [], "weights": None, "missing_policy": "all_required"}
                    for d in DOMAINS_V03},
        "interpretation_templates": {},
    })
