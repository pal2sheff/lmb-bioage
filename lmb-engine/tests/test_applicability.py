"""Применимость, пропуски и ошибки ввода (приложение З, ситуации B-xx)."""
import datetime as dt

import pytest

from lmb_engine import indices as ix
from lmb_engine.core import Encounter, Measurement, Qualifier, Review, Sex, Status
from lmb_engine.pipeline import cardio_model_for_age
from tests.helpers import ENC_DATE, enc


# B-04
def test_homa_not_applicable_on_insulin_therapy():
    r = ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=9, flags={"insulin_therapy": "yes"}))
    assert r.status == Status.NOT_APPLICABLE
    assert r.value == 2.0  # вычислено и показано врачу, но в домен не идёт


def test_homa_type1_diabetes_not_applicable():
    r = ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=9, flags={"diabetes": "type1"}))
    assert r.status == Status.NOT_APPLICABLE


def test_homa_unknown_fasting_needs_review():
    r = ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=9, flags={"fasting_status": "unknown"}))
    assert r.status == Status.AWAITING_REVIEW


def test_homa_not_fasting_not_applicable():
    r = ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=9, flags={"fasting_status": "no"}))
    assert r.status == Status.NOT_APPLICABLE


def test_unknown_is_not_no():
    """Отсутствующий флаг = unknown, а не no."""
    e = Encounter(birth_date=dt.date(1976, 1, 1), encounter_date=ENC_DATE, sex=Sex.FEMALE,
                  measurements={"glucose_fasting": Measurement(5, "mmol/L"),
                                "insulin_fasting": Measurement(9, "uU/mL")},
                  flags={"fasting_status": "yes"})
    r = ix.homa_ir(e)
    assert r.status == Status.AWAITING_REVIEW  # инсулинотерапия неизвестна


def test_insulin_pmol_rejected():
    r = ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=62, units={"insulin_fasting": "pmol/L"}))
    assert r.status == Status.INVALID_INPUT and r.value is None


def test_cholesterol_mg_dl_rejected():
    r = ix.non_hdl(enc(tc=200, hdl=50, units={"tc": "mg/dL", "hdl": "mg/dL"}))
    assert r.status == Status.INVALID_INPUT


# B-05
def test_percent_cells_rejected():
    r = ix.nlr(enc(neutrophils_abs=60, lymphocytes_abs=30,
                   units={"neutrophils_abs": "%", "lymphocytes_abs": "%"}))
    assert r.status == Status.INVALID_INPUT


# B-06, B-07
def test_zero_values_invalid():
    assert ix.aip(enc(tg=0, hdl=1.5)).status == Status.INVALID_INPUT
    assert ix.nlr(enc(neutrophils_abs=4, lymphocytes_abs=0)).status == Status.INVALID_INPUT


# B-08
def test_egfr_missing_sex_or_age():
    r = ix.egfr_ckdepi_cr_2021(enc(sex=None, creatinine_serum=80))
    assert r.status == Status.MISSING_DATA and "sex_at_birth" in r.missing_fields
    r = ix.egfr_ckdepi_cr_2021(enc(age=None, creatinine_serum=80))
    assert r.status == Status.MISSING_DATA and "birth_date" in r.missing_fields


def test_missing_value_is_missing_not_zero():
    r = ix.homa_ir(enc(glucose_fasting=5))
    assert r.status == Status.MISSING_DATA and r.value is None
    assert "insulin_fasting" in r.missing_fields


def test_egfr_under_18_not_applicable():
    assert ix.egfr_ckdepi_cr_2021(enc(age=17, creatinine_serum=60)).status == Status.NOT_APPLICABLE


def test_egfr_acute_kidney_change():
    r = ix.egfr_ckdepi_cr_2021(enc(creatinine_serum=80, flags={"acute_kidney_change": "yes"}))
    assert r.status == Status.NOT_APPLICABLE


def test_fib4_under_35_warning():
    r = ix.fib4(enc(age=30, ast=20, alt=25, platelets=200))
    assert r.status == Status.CALCULATED and any("35" in w for w in r.warnings)


def test_acute_infection_excludes_inflammation():
    r = ix.nlr(enc(neutrophils_abs=4, lymphocytes_abs=2, flags={"acute_infection": "yes"}))
    assert r.status == Status.NOT_APPLICABLE and r.value == 2.0


# B-09 — CAIDE вне 39–64 лет не рассчитывается (см. также tests/test_caide.py)
def test_caide_outside_age():
    r = ix.caide(enc(age=66, sbp_mmhg=130, tc=5, height_cm=170, weight_kg=70,
                     flags={"education_years": "12", "physical_activity_caide": "active"}))
    assert r.status == Status.NOT_APPLICABLE and r.value is None


def test_frax_without_access():
    assert ix.frax_kz(enc(flags={"frax_status": "integration_not_configured"})).status == \
        Status.INTEGRATION_NOT_CONFIGURED
    assert ix.frax_kz(enc()).status == Status.MISSING_DATA


def test_frax_accepts_two_risks():
    r = ix.frax_kz(enc(age=65, frax_major_10y_pct=Measurement(12.5, "%"), frax_hip_10y_pct=Measurement(3.1, "%"),
                       flags={"frax_with_bmd": True, "frax_source": "manual"}))
    assert r.status == Status.CALCULATED and r.value == 12.5 and r.extra["hip_10y_pct"] == 3.1
    assert r.extra["source"] == "manual" and r.extra["national_model"] == "Kazakhstan"


def test_frax_age_not_substituted():
    """B-01: возраст 35 или 91 — неприменимо, граница не подставляется."""
    for age in (35, 91):
        r = ix.frax_kz(enc(age=age, frax_major_10y_pct=Measurement(5, "%"), frax_hip_10y_pct=Measurement(1, "%")))
        assert r.status == Status.NOT_APPLICABLE and r.value is None
    assert ix.frax_kz(enc(age=39)).status == Status.NOT_APPLICABLE


def test_frax_range_and_pair():
    r = ix.frax_kz(enc(age=60, frax_major_10y_pct=Measurement(140, "%"), frax_hip_10y_pct=Measurement(1, "%")))
    assert r.status == Status.INVALID_INPUT
    r = ix.frax_kz(enc(age=60, frax_major_10y_pct=Measurement(10, "%")))
    assert r.status == Status.MISSING_DATA and "frax_hip_10y_pct" in r.missing_fields


# B-10
def test_cardio_model_switch_by_age():
    assert cardio_model_for_age(None) is None
    assert cardio_model_for_age(39) is None
    assert cardio_model_for_age(40) == "score2"
    assert cardio_model_for_age(69) == "score2"
    assert cardio_model_for_age(70) == "score2_op"
    assert cardio_model_for_age(89) == "score2_op"
    assert cardio_model_for_age(90) is None


def test_age_counted_on_encounter_date():
    e = Encounter(birth_date=dt.date(1956, 10, 11), encounter_date=dt.date(2026, 10, 10), sex=Sex.MALE)
    from lmb_engine.core import age_full_years
    assert age_full_years(e.birth_date, e.encounter_date) == 69  # день рождения завтра


# B-16
def test_different_sample_dates_need_review():
    r = ix.homa_ir(enc(
        glucose_fasting=Measurement(5, "mmol/L", sample_date=dt.date(2026, 10, 1)),
        insulin_fasting=Measurement(9, "uU/mL", sample_date=dt.date(2026, 10, 8))))
    assert r.status == Status.AWAITING_REVIEW


def test_cbc_from_different_samples():
    r = ix.sii(enc(platelets=Measurement(250, "10^9/L", sample_id="A"),
                   neutrophils_abs=Measurement(4, "10^9/L", sample_id="A"),
                   lymphocytes_abs=Measurement(2, "10^9/L", sample_id="B")))
    assert r.status == Status.AWAITING_REVIEW


# B-17
def test_unconfirmed_recognition_not_final():
    r = ix.bmi(enc(weight_kg=Measurement(80, "kg", review=Review.PENDING), height_cm=175))
    assert r.status == Status.AWAITING_REVIEW


def test_rejected_value_treated_as_missing():
    r = ix.bmi(enc(weight_kg=Measurement(80, "kg", review=Review.REJECTED), height_cm=175))
    assert r.status == Status.MISSING_DATA


# B-23
def test_censored_value_not_substituted():
    r = ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=Measurement(0.5, "uU/mL", qualifier=Qualifier.LT)))
    assert r.status == Status.INVALID_INPUT and r.value is None


def test_out_of_technical_range():
    assert ix.bmi(enc(weight_kg=80, height_cm=17.5)).status == Status.INVALID_INPUT


def test_acr_two_sources_require_choice():
    """Оба значения ACR: без выбора источника результат ждёт решения врача (аудит 11.10.2026)."""
    r = ix.acr(enc(u_albumin=20, u_creatinine=10, acr_lab=Measurement(25, "mg/g")))
    assert r.status == Status.AWAITING_REVIEW and r.value is None
    assert "выберите источник" in r.reasons[0]
    assert r.extra["acr_lab"] == {"value": 25, "unit": "mg/g"} and r.extra["acr_calculated_mg_mmol"] == 2.0
    lab = ix.acr(enc(u_albumin=20, u_creatinine=10, acr_lab=Measurement(25, "mg/g"), flags={"acr_source": "lab"}))
    assert lab.status == Status.CALCULATED and lab.value == pytest.approx(25 / 8.84) and lab.extra["source"] == "lab"
    calc = ix.acr(enc(u_albumin=20, u_creatinine=10, acr_lab=Measurement(25, "mg/g"),
                      flags={"acr_source": "calculated"}))
    assert calc.value == 2.0 and calc.extra["source"] == "calculated"


def test_acr_single_source_used_and_named():
    only_lab = ix.acr(enc(acr_lab=Measurement(3.0, "mg/mmol")))
    assert only_lab.status == Status.CALCULATED and only_lab.value == 3.0 and only_lab.extra["source"] == "lab"
    only_urine = ix.acr(enc(u_albumin=20, u_creatinine=10))
    assert only_urine.value == 2.0 and only_urine.extra["source"] == "calculated"
    missing = ix.acr(enc(flags={"acr_source": "lab"}))
    assert missing.status == Status.MISSING_DATA and missing.missing_fields == ["acr_lab"]


def test_asmi_needs_four_limb_segments_not_smm():
    """ASM — сумма четырёх сегментов конечностей Visbody (решение владельца 12.10.2026); прежнее поле ASM не используется."""
    assert ix.asmi(enc(height_cm=175)).status == Status.MISSING_DATA
    assert ix.asmi(enc(height_cm=175, visbody_asm=22)).status == Status.MISSING_DATA
    r = ix.asmi(enc(height_cm=175, visbody_seg_arm_left_kg=3, visbody_seg_arm_right_kg=3, visbody_seg_leg_left_kg=8,
                    visbody_seg_leg_right_kg=8))
    assert r.value == 22 / 1.75 ** 2 and r.extra["asm_source"] == "Visbody, расчёт по четырём сегментам"


def test_run_all_isolated(monkeypatch):
    """Ошибка одного алгоритма не останавливает остальные."""
    def boom(e):
        raise ZeroDivisionError
    monkeypatch.setitem(ix.REGISTRY, "nlr", boom)
    out = ix.run_all(enc(weight_kg=80, height_cm=175))
    assert out["nlr"].status == Status.INVALID_INPUT
    assert out["bmi"].status == Status.CALCULATED
