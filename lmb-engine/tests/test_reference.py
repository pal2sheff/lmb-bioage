"""Эталоны приложения З ТЗ (Z-01…Z-16).

Происхождение: «владелец» — эталоны промта; «формула» — рассчитано по опубликованной
формуле; при приёмке Z-11…Z-15 сверяются с калькулятором NKF.
"""
import math

import pytest

from lmb_engine import indices as ix
from lmb_engine.core import Sex, Status
from tests.helpers import enc


def ok(r, expected, tol):
    assert r.status == Status.CALCULATED, (r.status, r.reasons, r.missing_fields)
    assert r.value == pytest.approx(expected, abs=tol)


# --- эталоны владельца
def test_z01_homa_ir():
    ok(ix.homa_ir(enc(glucose_fasting=5, insulin_fasting=9)), 2.0, 1e-9)


def test_z02_whtr():
    ok(ix.whtr(enc(waist_cm=85, height_cm=170)), 0.5, 1e-9)


def test_z03_aip_zero():
    ok(ix.aip(enc(tg=1.5, hdl=1.5)), 0.0, 1e-9)


def test_z04_acr():
    r = ix.acr(enc(u_albumin=20, u_creatinine=10))
    ok(r, 2.0, 1e-9)
    assert r.extra["acr_mg_g"] == pytest.approx(17.68, abs=1e-9)


def test_z05_fib4():
    ok(ix.fib4(enc(age=50, ast=20, alt=25, platelets=200)), 1.0, 1e-9)


def test_z06_nlr_sii():
    e = enc(neutrophils_abs=4, lymphocytes_abs=2, platelets=250)
    ok(ix.nlr(e), 2.0, 1e-9)
    ok(ix.sii(e), 500.0, 1e-9)


# --- производные эталоны
def test_z07_aip_negative_allowed():
    ok(ix.aip(enc(tg=0.8, hdl=1.6)), -0.30103, 1e-5)


def test_z08_tyg():
    ok(ix.tyg(enc(tg=1.5, glucose_fasting=5.0)), 8.6969, 1e-4)


def test_z09_tyg_divisor_inside_log():
    """Ловушка: неверная запись ln(ТГ·глюкоза)/2 даёт ≈ 4,695."""
    r = ix.tyg(enc(tg=1.5, glucose_fasting=5.0))
    wrong = math.log(1.5 * 88.57 * 5.0 * 18.0182) / 2
    assert abs(r.value - wrong) > 3


def test_z10_fib4():
    ok(ix.fib4(enc(age=62, ast=35, alt=30, platelets=180)), 2.2010, 1e-4)


@pytest.mark.parametrize("case,age,sex,scr,expected", [
    ("Z-11 ж, Scr/k<1", 50, Sex.FEMALE, 53.04, 109.283),
    ("Z-12 ж, Scr/k>1", 60, Sex.FEMALE, 88.4, 64.495),
    ("Z-13 м, Scr/k=1", 50, Sex.MALE, 79.56, 104.049),
    ("Z-14 м, Scr/k<1", 45, Sex.MALE, 70, 111.566),
    ("Z-15 м, Scr/k>1", 62, Sex.MALE, 110, 65.462),
])
def test_egfr(case, age, sex, scr, expected):
    ok(ix.egfr_ckdepi_cr_2021(enc(age=age, sex=sex, creatinine_serum=scr)), expected, 1e-3)


def test_z16_bmi():
    ok(ix.bmi(enc(weight_kg=80, height_cm=175)), 26.1224, 1e-4)


def test_egfr_mg_dl_input_equivalent():
    a = ix.egfr_ckdepi_cr_2021(enc(creatinine_serum=88.4))
    b = ix.egfr_ckdepi_cr_2021(enc(creatinine_serum=1.0, units={"creatinine_serum": "mg/dL"}))
    assert a.value == pytest.approx(b.value, abs=1e-9)


def test_glucose_tg_mg_dl_conversion():
    a = ix.tyg(enc(tg=1.5, glucose_fasting=5.0))
    b = ix.tyg(enc(tg=1.5 * 88.57, glucose_fasting=5.0 * 18.0182,
                   units={"tg": "mg/dL", "glucose_fasting": "mg/dL"}))
    assert a.value == pytest.approx(b.value, abs=1e-12)


def test_full_precision_kept():
    """Округление — только при отображении."""
    r = ix.fib4(enc(age=62, ast=35, alt=30, platelets=180))
    assert r.value == 62 * 35 / (180 * math.sqrt(30))
