"""SCORE2 и SCORE2-OP: сверка формулы с независимой реализацией, применимость, блокировка.

Сверка с официальным HeartScore — tests/test_heartscore.py."""
import copy
import csv
from pathlib import Path

import pytest

from lmb_engine import cardio
from lmb_engine.core import Sex, Status, age_exact_years
from tests.helpers import enc

CASES = list(csv.DictReader(open(Path(__file__).parent / "fixtures" / "score2_crosscheck.csv", encoding="utf-8")))


def _compute(row, region=None):
    p = cardio.load_params(row["model"])
    return cardio.compute(p, int(row["age"]), Sex(row["sex"]), row["smoker"] == "1",
                          float(row["sbp_mmhg"]), float(row["tc_mmol_l"]), float(row["hdl_mmol_l"]), region)


@pytest.mark.parametrize("row", CASES, ids=[r["case"] for r in CASES])
def test_matches_independent_implementation(row):
    """Совпадение с cvd-risk 0.1.48 (независимая открытая реализация), регион high."""
    assert _compute(row)["risk"] * 100 == pytest.approx(float(row["cvd_risk_0_1_48_pct"]), abs=1e-6)


def test_score2op_metricgate_example():
    """MetricGate: 75 лет, мужчина, САД 150, ОХС 5,5, ЛПВП 1,3, не курит, регион moderate → 18,8 %."""
    r = cardio.compute(cardio.load_params("score2_op"), 75, Sex.MALE, False, 150, 5.5, 1.3, "moderate")
    assert round(r["risk"] * 100, 1) == 18.8


def test_reference_point_score2():
    """В точке центрирования (60 лет, САД 120, ОХС 6, ЛПВП 1,3, не курит) линейный предиктор = 0."""
    r = cardio.compute(cardio.load_params("score2"), 60, Sex.MALE, False, 120, 6, 1.3)
    assert r["linear_predictor"] == 0
    assert r["uncalibrated"] == pytest.approx(1 - 0.9605)


def test_risk_increases_with_smoking_and_sbp():
    p = cardio.load_params("score2")
    base = cardio.compute(p, 55, Sex.FEMALE, False, 130, 5.5, 1.4)["risk"]
    assert cardio.compute(p, 55, Sex.FEMALE, True, 130, 5.5, 1.4)["risk"] > base
    assert cardio.compute(p, 55, Sex.FEMALE, False, 160, 5.5, 1.4)["risk"] > base


def test_params_hash_and_region():
    p = cardio.load_params("score2")
    assert len(p["_sha256"]) == 64 and p["region"] == "high"


def test_params_validation():
    p = copy.deepcopy(cardio.load_params("score2"))
    del p["coefficients"]["male"]["chdl"]
    with pytest.raises(ValueError):
        cardio._validate(p)
    p = copy.deepcopy(cardio.load_params("score2"))
    p["baseline_survival"]["female"] = 1.2
    with pytest.raises(ValueError):
        cardio._validate(p)
    p = copy.deepcopy(cardio.load_params("score2"))
    p["region"] = "kz"
    with pytest.raises(ValueError):
        cardio._validate(p)


# ---- индекс в профиле
GOOD = dict(sbp_mmhg=140, tc=5.8, hdl=1.2)
FLAGS = {"smoking_current": "yes", "diabetes": "no", "ascvd": "no", "ckd_known": "no", "fh": "no",
         "very_high_single_risk_factor": "no"}


def verified(code):
    p = copy.deepcopy(cardio.load_params(code))
    p["verification"]["heartscore_verified"] = True
    return p


def test_not_activated_until_heartscore():
    """Без отметки сверки индекс не считается (правило активации)."""
    p = copy.deepcopy(cardio.load_params("score2"))
    p["verification"]["heartscore_verified"] = False
    r = cardio.score2(enc(age=55, sex=Sex.MALE, flags=FLAGS, **GOOD), p)
    assert r.status == Status.MODEL_NOT_CONFIGURED and r.value is None
    assert "HeartScore" in r.reasons[0]


def test_shipped_params_activated_after_heartscore():
    """11.10.2026: сверены 20 случаев SCORE2 и 10 SCORE2-OP — оба алгоритма активированы."""
    for code in ("score2", "score2_op"):
        assert cardio.load_params(code)["verification"]["heartscore_verified"] is True
    r = cardio.score2(enc(age=55, sex=Sex.MALE, flags=FLAGS, **GOOD))
    assert r.status == Status.CALCULATED and r.unit == "%"


def test_calculated_when_verified():
    e = enc(age=55, sex=Sex.MALE, flags=FLAGS, **GOOD)
    r = cardio.score2(e, verified("score2"))
    age = age_exact_years(e.birth_date, e.encounter_date)          # 55,77: в формуле непрерывный возраст
    exp = cardio.compute(cardio.load_params("score2"), age, Sex.MALE, True, 140, 5.8, 1.2)["risk"] * 100
    assert r.status == Status.CALCULATED and r.value == pytest.approx(exp) and r.unit == "%"
    assert r.extra["age_exact_years"] == pytest.approx(55 + 282 / 365)


def test_op_calculated_when_verified():
    r = cardio.score2_op(enc(age=75, sex=Sex.FEMALE, flags=FLAGS, **GOOD), verified("score2_op"))
    assert r.status == Status.CALCULATED


@pytest.mark.parametrize("flags,status", [
    ({"diabetes": "type2"}, Status.NOT_APPLICABLE),
    ({"diabetes": "unknown"}, Status.AWAITING_REVIEW),
    ({"ascvd": "yes"}, Status.NOT_APPLICABLE),
    ({"ckd_known": "yes"}, Status.NOT_APPLICABLE),
    ({"fh": "unknown"}, Status.AWAITING_REVIEW),
    ({"smoking_current": "unknown"}, Status.MISSING_DATA),
])
def test_applicability(flags, status):
    r = cardio.score2(enc(age=55, sex=Sex.MALE, flags={**FLAGS, **flags}, **GOOD), verified("score2"))
    assert r.status == status and r.value is None


def test_age_switch_between_models():
    e70 = enc(age=70, sex=Sex.MALE, flags=FLAGS, **GOOD)
    assert cardio.score2(e70, verified("score2")).status == Status.NOT_APPLICABLE
    assert cardio.score2_op(e70, verified("score2_op")).status == Status.CALCULATED
    e39 = enc(age=39, sex=Sex.MALE, flags=FLAGS, **GOOD)
    assert cardio.score2(e39, verified("score2")).status == Status.NOT_APPLICABLE


def test_missing_sbp():
    r = cardio.score2(enc(age=55, sex=Sex.MALE, flags=FLAGS, tc=5.8, hdl=1.2), verified("score2"))
    assert r.status == Status.MISSING_DATA and "sbp_mmhg" in r.missing_fields
