"""Справочники: показатели (из lmb_engine.units) и пункты анкеты.

Справочник входов модели и состав чекапа клиники — разные признаки
(in_model_inputs, in_checkup); здесь заполняются входы модели.
"""
from __future__ import annotations

from lmb_engine.units import INPUTS

# Пункты анкеты и клинические отметки, которые использует расчётный модуль.
# tri — «да / нет / неизвестно»; значения списков — допустимые категории.
TRI = ("yes", "no", "unknown")
QUESTIONNAIRE_ITEMS = {
    "smoking_current": ("Текущее курение", TRI),
    "fasting_status": ("Анализ сдан натощак", TRI),
    "insulin_therapy": ("Инсулинотерапия", TRI),
    "diabetes": ("Сахарный диабет", ("no", "type1", "type2", "other", "unknown")),
    "ascvd": ("Установленное атеросклеротическое ССЗ", TRI),
    "ckd_known": ("Известная хроническая болезнь почек", TRI),
    "fh": ("Семейная гиперхолестеринемия", TRI),
    "very_high_single_risk_factor": ("Очень высокий отдельный фактор риска (оценка врача)", TRI),
    "acute_kidney_change": ("Острое изменение функции почек", TRI),
    "creatinine_idms": ("Креатинин стандартизован по IDMS", TRI),
    "acute_liver_condition": ("Острое поражение печени или мышц, иная причина тромбоцитопении", TRI),
    "acute_infection": ("Острая инфекция или значимое воспаление", TRI),
    # FRAX: формулировки по определениям FRAX; «неизвестно» не превращается в «нет»
    "prior_fragility_fracture": ("Предшествующий низкоэнергетический перелом во взрослом возрасте", TRI),
    "parent_hip_fracture": ("Перелом бедра у матери или отца", TRI),
    # формулировку сверить с текстом инструмента FRAX перед рабочим запуском
    "glucocorticoids": ("Пероральные глюкокортикоиды сейчас или ранее более 3 месяцев в дозе ≥ 5 мг преднизолона "
                        "в сутки (или эквивалент)", TRI),
    "rheumatoid_arthritis": ("Подтверждённый ревматоидный артрит", TRI),
    "secondary_osteoporosis": ("Заболевание, тесно связанное с остеопорозом (вторичный остеопороз)", TRI),
    "alcohol_3plus": ("Алкоголь ≥ 3 стандартных доз в сутки", TRI),
    # CAIDE (модель 1): определения по Kivipelto 2006; «неизвестно» не равно «неактивен»
    "physical_activity_caide": ("Физическая активность не менее 2 раз в неделю по 20–30 минут и дольше, "
                                "с потоотделением и учащением дыхания", ("active", "inactive", "unknown")),
    "education_years": ("Полные годы обучения (школа, колледж, вуз)", "integer"),
    "fn_bmd_device_make": ("Производитель денситометра (для МПК в г/см²)", None),
    # источник ACR при наличии готового и расчётного значения (аудит 11.10.2026): выбирает врач
    "acr_source": ("Источник ACR для расчёта", ("lab", "calculated", "unknown")),
    "frax_assumed_no": ("Факторы FRAX, отмеченные врачом «нет — сведений нет»", "frax_list"),
    # LQ One: сведения об исследовании для итогового показателя заключения (аудит 12.10.2026)
    "lqone_device_model": ("Модель аппарата LQ One", None),
    "lqone_software_version": ("Версия программы LQ One", None),
    "lqone_measured_on": ("Дата измерения LQ One", "date"),
    "lqone_age_name": ("Название показателя возраста в отчёте LQ1", None),
    # мышечная ветка (задание владельца 12.10.2026): невозможность теста — отдельный ответ, время не подставляется
    "chair_stand_result": ("Пять вставаний со стула без помощи рук", ("completed", "unable", "unknown")),
}

# Пункты, которые подтверждает только врач (пациент может ответить «не знаю»)
DOCTOR_ONLY_ITEMS = {"acr_source", "lqone_age_name", "chair_stand_result", "lqone_device_model", "lqone_software_version", "lqone_measured_on", "ascvd", "ckd_known", "fh", "very_high_single_risk_factor", "acute_kidney_change",
                     "creatinine_idms", "acute_liver_condition", "acute_infection", "frax_assumed_no",
                     "secondary_osteoporosis", "rheumatoid_arthritis"}
FRAX_RISK_FACTORS = ("prior_fragility_fracture", "parent_hip_fracture", "smoking_current", "glucocorticoids",
                     "rheumatoid_arthritis", "secondary_osteoporosis", "alcohol_3plus")


INTEGER_RANGES = {"education_years": (0, 30)}


def validate_answer(code: str, value: str) -> str | None:
    """Вернуть текст ошибки или None."""
    allowed = QUESTIONNAIRE_ITEMS[code][1]
    if allowed == "integer":
        lo, hi = INTEGER_RANGES[code]
        if value == "unknown":
            return None
        if not value.isdigit() or not lo <= int(value) <= hi or str(int(value)) != value:
            return f"{code}: целое число {lo}–{hi} или «unknown»"
        return None
    if allowed is None:
        return None if 0 < len(value) <= 50 else f"{code}: текст 1–50 символов"
    if allowed == "date":
        import datetime as _dt
        try:
            _dt.date.fromisoformat(value)
        except ValueError:
            return f"{code}: дата в формате ГГГГ-ММ-ДД"
        return None
    if allowed == "frax_list":
        items = [x for x in value.split(",") if x]
        bad = set(items) - set(FRAX_RISK_FACTORS)
        return f"{code}: недопустимые пункты {sorted(bad)}" if bad else None
    return None if value in allowed else f"{code}: допустимо {allowed}"


# входы только PhenoAge (самостоятельный показатель): хранятся, но в LMB v0.3 не входят
CONTROL_ONLY_INPUTS = ("wbc", "mcv", "rdw", "albumin_serum", "crp", "alp")
# показатели аппаратов, которые только отображаются (в LMB v0.3 не входят)
DEVICE_DISPLAY_INPUTS = ("lqone_bioage_years", "lqone_reliability_pct", "visbody_seg_arm_left_kg",
                         "visbody_seg_arm_right_kg", "visbody_seg_leg_left_kg", "visbody_seg_leg_right_kg",
                         "grip_right_kg", "grip_left_kg", "chair_stand_5x_s")


def observation_definitions() -> list[dict]:
    out = []
    for code, d in INPUTS.items():
        if code.startswith("frax_"):
            continue   # результаты FRAX вносятся только через запрос к сервису или ручной режим
        lo, hi = d.plausible if d.plausible else (None, None)
        out.append(dict(code=code, name_ru=d.name_ru, value_type="number", unit_canonical=d.canonical_unit,
                        allowed_units=sorted(d.conversions), plausible_min=lo, plausible_max=hi,
                        in_model_inputs=code not in CONTROL_ONLY_INPUTS + DEVICE_DISPLAY_INPUTS, in_checkup=True))
    out.append(dict(code="acr_lab", name_ru="ACR лаборатории", value_type="number", unit_canonical=None,
                    allowed_units=["mg/mmol", "mg/g"], plausible_min=0, plausible_max=5000,
                    in_model_inputs=True, in_checkup=True))
    return out


# ---------------------------------------------------------------- для интерфейса
OBSERVATION_GROUPS = [
    ("Антропометрия и давление", ["height_cm", "weight_kg", "waist_cm", "sbp_mmhg"]),
    ("Углеводный и липидный обмен", ["glucose_fasting", "insulin_fasting", "tg", "tc", "hdl"]),
    ("Почки", ["creatinine_serum", "u_albumin", "u_creatinine", "acr_lab"]),
    ("Печень", ["ast", "alt"]),
    ("Общий анализ крови", ["platelets", "neutrophils_abs", "lymphocytes_abs", "wbc", "mcv", "rdw"]),
    ("Дополнительные показатели для PhenoAge", ["albumin_serum", "crp", "alp"]),
    ("Минеральная плотность шейки бедра", ["fn_tscore", "fn_bmd"]),
    ("Мышцы и функция", ["grip_right_kg", "grip_left_kg", "chair_stand_5x_s"]),
    ("Visbody — мышцы конечностей", ["visbody_seg_arm_left_kg", "visbody_seg_arm_right_kg",
                                     "visbody_seg_leg_left_kg", "visbody_seg_leg_right_kg"]),
    ("LQ One — отчёт аппарата", ["lqone_bioage_years", "lqone_reliability_pct"]),
]

QUESTIONNAIRE_GROUPS = [
    ("Условия обследования", ["fasting_status", "creatinine_idms", "acute_infection", "acute_kidney_change",
                              "acute_liver_condition", "acr_source"]),
    ("Анамнез", ["diabetes", "insulin_therapy", "ascvd", "ckd_known", "fh", "very_high_single_risk_factor"]),
    ("Образ жизни и образование", ["smoking_current", "alcohol_3plus", "physical_activity_caide", "education_years"]),
    ("Факторы FRAX", ["prior_fragility_fracture", "parent_hip_fracture", "glucocorticoids", "rheumatoid_arthritis",
                      "secondary_osteoporosis", "fn_bmd_device_make", "frax_assumed_no"]),
    ("Мышцы и функция", ["chair_stand_result"]),
    ("LQ One", ["lqone_age_name", "lqone_device_model", "lqone_software_version", "lqone_measured_on"]),
]

INDEX_LABELS = {
    "score2": ("SCORE2", "10-летний риск сердечно-сосудистых событий"),
    "score2_op": ("SCORE2-OP", "10-летний риск сердечно-сосудистых событий, 70–89 лет"),
    "non_hdl": ("Non-HDL", "Холестерин не-ЛПВП"),
    "homa_ir": ("HOMA-IR", "Индекс инсулинорезистентности"),
    "tyg": ("TyG", "Триглицерид-глюкозный индекс"),
    "aip": ("AIP", "Атерогенный индекс плазмы"),
    "whtr": ("WHtR", "Отношение талии к росту"),
    "bmi": ("ИМТ", "Индекс массы тела"),
    "egfr_ckdepi_cr_2021": ("eGFR", "CKD-EPI 2021, креатинин"),
    "acr": ("ACR", "Альбумин/креатинин мочи"),
    "fib4": ("FIB-4", "Риск выраженного фиброза печени"),
    "nlr": ("NLR", "Нейтрофилы/лимфоциты"),
    "sii": ("SII", "Индекс системного иммунного воспаления"),
    "caide": ("CAIDE", "20-летний риск деменции, баллы"),
    "frax_kz": ("FRAX", "10-летний риск переломов, модель Казахстана"),
    "asmi": ("ASMI", "Индекс мышц конечностей: ASM (4 сегмента Visbody) / рост²"),
    "muscle_age": ("Мышечный возраст", "Модель 0.1-synthetic: сила хвата, пять вставаний, ASMI"),
    "phenoage": ("PhenoAge", "Фенотипический возраст (Levine 2018)"),
    "lqone_bioage": ("Возраст по LQ1", "Готовое значение возраста из отчёта LQ One"),
}

BRANCHES = [
    ("cardio", "Cardio", "Сердечно-сосудистый профиль", ["score2", "score2_op", "non_hdl"]),
    ("metabolic", "Metabolic", "Метаболический профиль", ["homa_ir", "tyg", "aip", "whtr", "bmi"]),
    ("renal", "Renal", "Почечный профиль", ["egfr_ckdepi_cr_2021", "acr"]),
    ("hepatic", "Hepatic", "Печёночный профиль", ["fib4"]),
    ("inflammation", "Inflammation", "Воспалительный профиль", ["nlr", "sii"]),
    ("brain", "Brain", "Когнитивно-сосудистый профиль", ["caide"]),
    ("bone", "Bone", "Профиль риска переломов", ["frax_kz"]),
    ("muscle", "Muscle / Functional", "Мышечный и функциональный профиль", ["muscle_age", "asmi"]),
    ("adaptive", "Adaptive / Autonomic", "Адаптационный и вегетативный профиль", ["lqone_bioage"]),
]

# Ветки в разработке (решение владельца 12.10.2026: показать респираторный профиль «в работе»).
# Не входят в девять текущих веток и в LMB; методика и ввод не подключены.
FUTURE_BRANCHES = [
    ("respiratory", "Respiratory", "Респираторный профиль",
     "Спирометрия (FEV1, FVC, FEV1/FVC) с уравнениями GLI — методика и ввод готовятся; в расчёт не входит."),
]


def unit_factors(code: str) -> dict:
    """Множители перевода единицы в каноническую (все конверсии справочника линейны) — для явного
    пересчёта введённого значения в интерфейсе при смене единицы. Источник — справочник движка."""
    if code == "acr_lab":
        return {"mg/mmol": 1.0, "mg/g": 1 / 8.84}
    d = INPUTS.get(code)
    if d is None:
        return {}
    out = {}
    for u, f in d.conversions.items():
        if abs(f(0.0)) < 1e-12:
            out[u] = f(1.0)
    return out


def ui_catalog(definitions: list) -> dict:
    defs = {d["code"]: {**d, "unit_factors": unit_factors(d["code"])} for d in definitions}
    return {
        "observation_groups": [{"title": t, "items": [defs[c] for c in codes if c in defs]}
                               for t, codes in OBSERVATION_GROUPS],
        "questionnaire_groups": [{"title": t, "items": [
            {"code": c, "name": QUESTIONNAIRE_ITEMS[c][0],
             "kind": "text" if QUESTIONNAIRE_ITEMS[c][1] is None else
                     "date" if QUESTIONNAIRE_ITEMS[c][1] == "date" else
                     "frax_list" if QUESTIONNAIRE_ITEMS[c][1] == "frax_list" else
                     "integer" if QUESTIONNAIRE_ITEMS[c][1] == "integer" else "choice",
             "range": list(INTEGER_RANGES[c]) if c in INTEGER_RANGES else None,
             "options": list(QUESTIONNAIRE_ITEMS[c][1]) if isinstance(QUESTIONNAIRE_ITEMS[c][1], tuple) else None,
             "doctor_only": c in DOCTOR_ONLY_ITEMS} for c in codes]} for t, codes in QUESTIONNAIRE_GROUPS],
        "frax_risk_factors": list(FRAX_RISK_FACTORS),
        "index_labels": {k: {"short": v[0], "name": v[1]} for k, v in INDEX_LABELS.items()},
        "branches": [{"code": c, "title": t, "name": n, "indices": ix} for c, t, n, ix in BRANCHES],
        "future_branches": [{"code": c, "title": t, "name": n, "note": note} for c, t, n, note in FUTURE_BRANCHES],
    }
