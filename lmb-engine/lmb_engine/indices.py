"""Опубликованные клинические индексы (ТЗ, раздел 6; реестр — приложение В).

Каждая функция получает снимок визита и возвращает IndexResult. Значение
считается с полной точностью двойной точности; округление — только при показе.
Интерпретационные категории здесь не выдаются: они включаются утверждёнными
шаблонами (ТЗ, раздел 12).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .core import Encounter, IndexResult, Sex, Status, Tri
from .cardio import score2, score2_op
from .consistency import acr_lab_mg_mmol, cbc_issue, frax_issue
from .gate import Gate
from .units import ACR_MGMMOL_TO_MGG, CREATININE_UMOL_PER_MGDL, GLUCOSE_MMOL_TO_MGDL, TG_MMOL_TO_MGDL

ADULT_AGE = 18


# ---------------------------------------------------------------- антропометрия
def bmi(enc: Encounter) -> IndexResult:
    g = Gate(enc, "bmi", 1)
    h = g.value("height_cm")
    w = g.value("weight_kg")
    g.same_sample("height_cm", "weight_kg", label="рост и масса")
    if g.blocked():
        return g.result()
    return g.result(w / (h / 100) ** 2, "kg/m2")


def whtr(enc: Encounter) -> IndexResult:
    g = Gate(enc, "whtr", 1)
    waist = g.value("waist_cm")
    h = g.value("height_cm")
    g.same_sample("waist_cm", "height_cm", label="талия и рост")
    if g.blocked():
        return g.result()
    return g.result(waist / h, "ratio")


def asmi(enc: Encounter) -> IndexResult:
    """ASMI только из массы мышц конечностей отчёта аппарата; SMM не используется."""
    g = Gate(enc, "asmi", 1)
    asm = g.value("visbody_asm")
    h = g.value("height_cm")
    if g.blocked():
        return g.result()
    return g.result(asm / (h / 100) ** 2, "kg/m2")


# ---------------------------------------------------------------- Metabolic
def _fasting_rules(g: Gate) -> None:
    g.require_flag_yes("fasting_status", "Образец сдан натощак")


def homa_ir(enc: Encounter) -> IndexResult:
    g = Gate(enc, "homa_ir", 1)
    glu = g.value("glucose_fasting")
    ins = g.value("insulin_fasting")
    g.same_sample("glucose_fasting", "insulin_fasting", label="глюкоза и инсулин")
    _fasting_rules(g)
    g.exclude_if_yes("insulin_therapy", "Инсулинотерапия")
    if enc.flags.get("diabetes") == "type1":
        g.not_applicable.append("Сахарный диабет 1 типа")
    elif enc.flags.get("diabetes") in (None, "unknown"):
        g.warnings.append("Сведения о сахарном диабете отсутствуют")
    if g.blocked():
        return g.result()
    return g.result(glu * ins / 22.5, "ratio")


def tyg(enc: Encounter) -> IndexResult:
    """TyG = ln(ТГ_мг/дл × глюкоза_мг/дл / 2); деление на 2 — внутри логарифма."""
    g = Gate(enc, "tyg", 1)
    tg = g.value("tg")
    glu = g.value("glucose_fasting")
    g.same_sample("tg", "glucose_fasting", label="триглицериды и глюкоза")
    _fasting_rules(g)
    if g.blocked():
        return g.result()
    arg = (tg * TG_MMOL_TO_MGDL) * (glu * GLUCOSE_MMOL_TO_MGDL) / 2
    if arg <= 0:
        g.invalid.append("Аргумент логарифма TyG ≤ 0")
        return g.result()
    return g.result(math.log(arg), "ratio")


def aip(enc: Encounter) -> IndexResult:
    """AIP = log10(ТГ/ЛПВП) по молярным концентрациям; отрицательные значения допустимы."""
    g = Gate(enc, "aip", 1)
    tg = g.value("tg")
    hdl = g.value("hdl")
    g.same_sample("tg", "hdl", label="триглицериды и ЛПВП")
    _fasting_rules(g)
    if g.blocked():
        return g.result()
    if tg <= 0 or hdl <= 0:
        g.invalid.append("ТГ и ЛПВП должны быть > 0")
        return g.result()
    return g.result(math.log10(tg / hdl), "ratio")


def non_hdl(enc: Encounter) -> IndexResult:
    g = Gate(enc, "non_hdl", 1)
    tc = g.value("tc")
    hdl = g.value("hdl")
    g.same_sample("tc", "hdl", label="общий холестерин и ЛПВП")
    if g.blocked():
        return g.result()
    v = tc - hdl
    if v < 0:
        g.invalid.append("ЛПВП больше общего холестерина")
        return g.result()
    return g.result(v, "mmol/L")


# ---------------------------------------------------------------- Renal
def egfr_ckdepi_cr_2021(enc: Encounter) -> IndexResult:
    """CKD-EPI 2021, креатинин, без расового коэффициента (NKF; Inker 2021)."""
    g = Gate(enc, "egfr_ckdepi_cr_2021", 1)
    scr_umol = g.value("creatinine_serum")
    age = g.age()
    sex = g.sex()
    if age is not None and age < ADULT_AGE:
        g.not_applicable.append(f"Возраст {age} < {ADULT_AGE}: формула для взрослых")
    g.exclude_if_yes("acute_kidney_change", "Острое изменение функции почек",
                     unknown_to_review=False, unknown_warning=True)
    if enc.flag("creatinine_idms") == Tri.NO:
        g.not_applicable.append("Креатинин не стандартизован по IDMS")
    elif enc.flag("creatinine_idms") == Tri.UNKNOWN:
        g.warnings.append("Стандартизация креатинина по IDMS не указана")
    if g.blocked():
        return g.result()
    scr = scr_umol / CREATININE_UMOL_PER_MGDL
    if sex == Sex.FEMALE:
        k, alpha, f = 0.7, -0.241, 1.012
    else:
        k, alpha, f = 0.9, -0.302, 1.0
    v = 142 * min(scr / k, 1) ** alpha * max(scr / k, 1) ** -1.200 * 0.9938 ** age * f
    return g.result(v, "mL/min/1.73m2", {"scr_mg_dl": scr})


ACR_SOURCES = ("lab", "calculated")


def acr(enc: Encounter) -> IndexResult:
    """ACR, мг/ммоль. Источник выбирается явно (аудит 11.10.2026):

    - готовый ACR лаборатории (acr_lab, мг/ммоль или мг/г);
    - расчёт по альбумину и креатинину одной порции мочи.
    Если есть оба значения, источник указывает врач (флаг acr_source = lab | calculated); без выбора
    результат ждёт решения и в домен не входит. Если значение одно — используется оно; источник
    записывается в результат.
    """
    g = Gate(enc, "acr", 1)
    present = lambda k: enc.measurements.get(k) is not None and enc.measurements[k].value is not None  # noqa: E731
    have_lab = present("acr_lab")
    have_urine = present("u_albumin") or present("u_creatinine")
    choice = enc.flags.get("acr_source") if enc.flags.get("acr_source") in ACR_SOURCES else None
    extra: dict = {}

    lab = None
    if have_lab:
        m = enc.measurements["acr_lab"]
        extra["acr_lab"] = {"value": m.value, "unit": m.unit}
        lab, problem = acr_lab_mg_mmol(enc)
        if problem:
            g.invalid.append(problem)
            g.invalid_fields.append("acr_lab")
        else:
            extra["acr_lab_mg_mmol"] = lab

    calc = None
    if choice != "lab" and (have_urine or not have_lab or choice == "calculated"):
        alb = g.value("u_albumin")
        cr = g.value("u_creatinine")
        g.same_sample("u_albumin", "u_creatinine", label="альбумин и креатинин мочи")
        if alb is not None and cr is not None:
            calc = alb / cr
            extra["acr_calculated_mg_mmol"] = calc
    if choice == "lab" and not have_lab:
        g.missing.append("acr_lab")

    if lab is not None and calc is not None and choice is None:
        g.review.append(f"Есть два значения ACR: лаборатории {lab:.2f} мг/ммоль и расчётное {calc:.2f} мг/ммоль — "
                        f"выберите источник")
        extra["source"] = None
        return g.result(None, "mg/mmol", extra)
    if choice == "lab" or (choice is None and lab is not None and calc is None and not have_urine):
        value, source = lab, "lab"
    else:
        value, source = calc, "calculated"
    if g.blocked() or value is None:
        return g.result()
    extra["source"] = source
    extra["acr_mg_g"] = value * ACR_MGMMOL_TO_MGG
    return g.result(value, "mg/mmol", extra)


# ---------------------------------------------------------------- Hepatic
def fib4(enc: Encounter) -> IndexResult:
    """FIB-4 = возраст × АСТ / (тромбоциты × √АЛТ); тромбоциты — число в ×10⁹/л."""
    g = Gate(enc, "fib4", 1)
    age = g.age()
    ast = g.value("ast")
    alt = g.value("alt")
    plt = g.value("platelets")
    g.same_sample("ast", "alt", label="АСТ и АЛТ")
    if age is not None:
        if age < ADULT_AGE:
            g.not_applicable.append(f"Возраст {age} < {ADULT_AGE}")
        elif age < 35:
            g.warnings.append("FIB-4 ненадёжен у лиц моложе 35 лет")
    g.exclude_if_yes("acute_liver_condition", "Острое поражение печени или мышц, иная причина тромбоцитопении",
                     unknown_to_review=False)
    if g.blocked():
        return g.result()
    return g.result(age * ast / (plt * math.sqrt(alt)), "ratio")


# ---------------------------------------------------------------- Inflammation
def _cbc_rules(g: Gate, keys) -> None:
    g.same_sample(*keys, label="показатели общего анализа крови")
    g.consistent(cbc_issue(g.enc))
    g.exclude_if_yes("acute_infection", "Острая инфекция или значимое воспаление", unknown_to_review=False,
                     unknown_warning=True)


def nlr(enc: Encounter) -> IndexResult:
    g = Gate(enc, "nlr", 1)
    n = g.value("neutrophils_abs")
    lym = g.value("lymphocytes_abs")
    _cbc_rules(g, ("neutrophils_abs", "lymphocytes_abs"))
    if g.blocked():
        return g.result()
    return g.result(n / lym, "ratio")


def sii(enc: Encounter) -> IndexResult:
    g = Gate(enc, "sii", 1)
    plt = g.value("platelets")
    n = g.value("neutrophils_abs")
    lym = g.value("lymphocytes_abs")
    _cbc_rules(g, ("platelets", "neutrophils_abs", "lymphocytes_abs"))
    if g.blocked():
        return g.result()
    return g.result(plt * n / lym, "10^9/L")


# ---------------------------------------------------------------- не активированные алгоритмы
def _pending(code: str, status: Status, reason: str):
    def fn(enc: Encounter) -> IndexResult:
        return IndexResult(code=code, version=1, status=status, reasons=[reason])
    fn.__name__ = code
    return fn


# ---------------------------------------------------------------- Brain: CAIDE
CAIDE_AGE = (39, 64)   # исходная когорта среднего возраста; вне диапазона не рассчитывается
CAIDE_SOURCE = "Kivipelto M et al. Lancet Neurol 2006;5(9):735–741, табл. 2, модель 1 без APOE"
CAIDE_ACTIVITY = ("active", "inactive")


# Ступени возрастного балла CAIDE: <47 → 0, 47–53 → 3, >53 → 4 (оригинальная шкала, без сглаживания).
CAIDE_AGE_STEPS = (47, 54)


def caide_age_band(age: int) -> dict:
    """Возрастная категория CAIDE для показа врачу."""
    if age < 47:
        return {"band": "<47", "label": "младше 47 лет", "points": 0}
    if age <= 53:
        return {"band": "47-53", "label": "47–53 года", "points": 3}
    return {"band": ">53", "label": "старше 53 лет", "points": 4}


def caide_step_crossings(age_a: int, age_b: int) -> list:
    """Границы ступеней CAIDE (47, 54), пересечённые между двумя обследованиями.

    Для сравнения визитов: изменение Brain при таком переходе отражает шкалу, а не здоровье.
    """
    lo, hi = sorted((age_a, age_b))
    return [b for b in CAIDE_AGE_STEPS if lo < b <= hi]


def caide_points(age: int, education_years: int, male: bool, sbp: float, bmi_value: float, tc: float,
                 active: bool) -> dict:
    """Баллы модели 1 по таблице владельца (LMB_Claude_Data_1, раздел 6). Сумма 0–15."""
    return {
        "age": 0 if age < 47 else (3 if age <= 53 else 4),
        "education": 0 if education_years >= 10 else (2 if education_years >= 7 else 3),
        "sex": 1 if male else 0,
        "sbp": 2 if sbp > 140 else 0,
        "bmi": 2 if bmi_value > 30 else 0,
        "tc": 2 if tc > 6.5 else 0,
        "activity": 0 if active else 1,
    }


def caide(enc: Encounter) -> IndexResult:
    """CAIDE, модель 1 без APOE: баллы 0–15, отдалённый (≈20 лет) риск деменции.

    Не является оценкой текущих когнитивных функций или «возрастом мозга».
    Неизвестная активность не приравнивается к неактивности.
    """
    g = Gate(enc, "caide", 1)
    age = g.age()
    sex = g.sex()
    sbp = g.value("sbp_mmhg")
    tc = g.value("tc")
    h = g.value("height_cm")
    w = g.value("weight_kg")
    g.same_sample("height_cm", "weight_kg", label="рост и масса")
    edu = None
    raw = enc.flags.get("education_years")
    if raw in (None, "", "unknown"):
        g.missing.append("education_years")
    else:
        try:
            edu = int(str(raw).strip())
            if str(edu) != str(raw).strip() or not 0 <= edu <= 30:
                raise ValueError
        except ValueError:
            g.invalid.append(f"education_years: «{raw}» — нужно целое число полных лет обучения 0–30")
            edu = None
    act = enc.flags.get("physical_activity_caide")
    if act in (None, "", "unknown"):
        g.missing.append("physical_activity_caide")
    elif act not in CAIDE_ACTIVITY:
        g.invalid.append(f"physical_activity_caide: недопустимое значение «{act}»")
    if age is not None and not CAIDE_AGE[0] <= age <= CAIDE_AGE[1]:
        g.not_applicable.append(f"Возраст {age} вне области модели CAIDE ({CAIDE_AGE[0]}–{CAIDE_AGE[1]} лет)")
    if g.blocked() or g.not_applicable:
        return g.result()
    bmi_value = w / (h / 100) ** 2
    pts = caide_points(age, edu, sex == Sex.MALE, sbp, bmi_value, tc, act == "active")
    return g.result(float(sum(pts.values())), "points",
                    {"points": pts, "bmi": bmi_value, "age_band": caide_age_band(age),
                     "model": "CAIDE model 1 (без APOE)", "source": CAIDE_SOURCE})
FRAX_AGE = (40, 90)
FRAX_STATUS_FLAG = "frax_status"   # состояние получения результата, которое передаёт сервер


def frax_kz(enc: Encounter) -> IndexResult:
    """FRAX Kazakhstan: результат только от официального сервиса или подтверждённый ручной ввод.

    Модуль не воспроизводит формулу FRAX. Он проверяет применимость (40–90 лет без подмены
    возраста) и принимает два 10-летних риска. value — риск основных остеопоротических
    переломов, extra.hip_10y_pct — риск перелома бедра.
    """
    g = Gate(enc, "frax_kz", 1)
    age = g.age()
    if age is not None and not FRAX_AGE[0] <= age <= FRAX_AGE[1]:
        g.not_applicable.append(f"Возраст {age} вне диапазона FRAX {FRAX_AGE[0]}–{FRAX_AGE[1]}")
    have = [k for k in ("frax_major_10y_pct", "frax_hip_10y_pct")
            if enc.measurements.get(k) is not None and enc.measurements[k].value is not None]
    if not have:
        st = enc.flags.get(FRAX_STATUS_FLAG)
        reason = {"integration_not_configured": "Доступ к FRAX API не настроен; доступен ручной ввод",
                  "external_error": "Ошибка внешнего сервиса FRAX",
                  "awaiting_review": "Результат FRAX ожидает подтверждения врача"}.get(st)
        if g.not_applicable or g.missing:
            return g.result()
        if reason:
            return IndexResult("frax_kz", 1, Status(st), reasons=[reason])
        g.missing.append("frax_result")
        return g.result()
    major = g.value("frax_major_10y_pct")
    hip = g.value("frax_hip_10y_pct")
    g.consistent(frax_issue(enc))
    if g.blocked():
        return g.result()
    if g.not_applicable:
        return g.result()   # результат вне области применения не принимается
    with_bmd = enc.flags.get("frax_with_bmd")
    source = enc.flags.get("frax_source")
    extra = {"hip_10y_pct": hip, "major_10y_pct": major, "with_bmd": with_bmd, "source": source,
             "national_model": "Kazakhstan", "transferred_from_official_frax": source == "manual",
             "inputs_bound": enc.flags.get("frax_inputs_bound", True)}
    if extra["inputs_bound"] is False:
        g.warnings.append("Ручной результат FRAX внесён без полного набора факторов риска в системе")
    return g.result(major, "%", extra)


# ---------------------------------------------------------------- PhenoAge (самостоятельный показатель)
PHENOAGE_FILE = Path(__file__).resolve().parents[1] / "config" / "algorithms" / "phenoage_2018.json"
PHENOAGE_INPUTS = ("albumin_serum", "creatinine_serum", "glucose_fasting", "crp", "lymphocytes_abs", "wbc",
                   "mcv", "rdw", "alp")


def load_phenoage_params() -> dict:
    raw = PHENOAGE_FILE.read_bytes()
    p = json.loads(raw.decode("utf-8"))
    p["_sha256"] = hashlib.sha256(raw).hexdigest()
    m = p["mortality"]
    if abs(math.expm1(m["months"] * m["gamma"]) - m["factor"]) > 1e-5:
        raise ValueError("phenoage: factor ≠ exp(months·gamma) − 1")
    return p


def phenoage_from(p: dict, albumin_gl: float, creatinine_umol: float, glucose_mmol: float, crp_mgl: float,
                  lymph_pct: float, mcv: float, rdw: float, alp: float, wbc: float, age: float) -> dict:
    """Формула Левин 2018 в редакции поправки PLoS Med 2019. CRP подаётся в мг/л и переводится в мг/дл."""
    c = p["xb"]
    xb = (c["intercept"] + c["albumin"] * albumin_gl + c["creatinine"] * creatinine_umol
          + c["glucose"] * glucose_mmol + c["ln_crp"] * math.log(crp_mgl / 10) + c["lymphocyte_percent"] * lymph_pct
          + c["mcv"] * mcv + c["rdw"] * rdw + c["alp"] * alp + c["wbc"] * wbc + c["age"] * age)
    m = p["mortality"]
    mort = 1 - math.exp(-m["factor"] * math.exp(xb) / m["gamma"])
    k = p["conversion"]
    age_out = k["intercept"] + math.log(k["ln_scale"] * math.log(1 - mort)) / k["divisor"]
    return {"xb": xb, "mortality_10y": mort, "phenoage": age_out}


def phenoage(enc: Encounter, params: dict = None) -> IndexResult:
    """PhenoAge (фенотипический возраст), годы — самостоятельный показатель; с LMB не сравнивается
    и в LMB не входит (решение владельца 11.10.2026).

    Лимфоциты, % = лимфоциты абс. / лейкоциты × 100 (один общий анализ крови).
    """
    p = params or load_phenoage_params()
    g = Gate(enc, "phenoage", 1)
    age = g.age()
    v = {k: g.value(k) for k in PHENOAGE_INPUTS}
    g.same_sample("lymphocytes_abs", "wbc", "mcv", "rdw", label="показатели общего анализа крови")
    g.consistent(cbc_issue(enc))
    _fasting_rules(g)
    ap = p["applicability"]
    if age is not None and not ap["age_min"] <= age <= ap["age_max"]:
        g.not_applicable.append(f"Возраст {age} вне выборки разработки PhenoAge ({ap['age_min']}–{ap['age_max']} лет)")
        return g.result()          # вне выборки разработки число не выдаётся (как CAIDE)
    g.exclude_if_yes("acute_infection", "Острая инфекция или значимое воспаление", unknown_to_review=False,
                     unknown_warning=True)
    if g.blocked():
        return g.result()
    lymph_pct = v["lymphocytes_abs"] / v["wbc"] * 100
    out = phenoage_from(p, v["albumin_serum"], v["creatinine_serum"], v["glucose_fasting"], v["crp"], lymph_pct,
                        v["mcv"], v["rdw"], v["alp"], v["wbc"], age)
    if not p["verification"]["reference_cases_verified"]:
        g.warnings.append("Расчёт PhenoAge ещё не сверен с внешним калькулятором на эталонных наборах входов")
    return g.result(out["phenoage"], "years", {
        "role": "independent_age_indicator", "lymphocyte_percent": lymph_pct, "xb": out["xb"],
        "mortality_10y": out["mortality_10y"], "params_version": p["version"], "params_sha256": p["_sha256"]})


REGISTRY = {
    "bmi": bmi, "whtr": whtr, "asmi": asmi,
    "homa_ir": homa_ir, "tyg": tyg, "aip": aip, "non_hdl": non_hdl,
    "egfr_ckdepi_cr_2021": egfr_ckdepi_cr_2021, "acr": acr,
    "fib4": fib4, "nlr": nlr, "sii": sii,
    "score2": score2, "score2_op": score2_op, "caide": caide, "frax_kz": frax_kz,
    "phenoage": phenoage,
}


def run_all(enc: Encounter) -> dict:
    """Все индексы независимо: исключение одного не останавливает остальные."""
    out = {}
    for code, fn in REGISTRY.items():
        try:
            out[code] = fn(enc)
        except Exception as exc:  # защита конвейера; причина сохраняется
            out[code] = IndexResult(code=code, version=0, status=Status.INVALID_INPUT,
                                    reasons=[f"Внутренняя ошибка расчёта: {type(exc).__name__}"])
    return out
