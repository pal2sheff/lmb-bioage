"""Механизм пересчёта нормализации (v0.4). Данные ниже синтетические и служат только проверкой
арифметики подбора; они не являются референтной выборкой."""
import math
import random

import pytest

from lmb_engine.refit import (fit_expectation, load_record, record_status, refit, split_by_participant,
                              validate)

RECORD = "config/reference/v0.4_cardio_reference.json"


def test_shipped_record_is_missing():
    rec = load_record(RECORD)
    assert rec["status"] == "reference_sample_missing" and rec["fit"] is None
    assert record_status(rec)[0] == "reference_sample_missing"
    assert refit(rec, None)["status"] == "reference_sample_missing"
    assert refit(None, [{"participant_id": 1, "age": 50, "sex": 0, "value": 3}])["fit"] is None


def synthetic(n=600, seed=7, b=(-0.9, 0.026, -0.3, 0.0077), sd=0.36):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        age, sex = rnd.uniform(40, 63), rnd.randint(0, 1)
        for visit in range(2):                       # два визита одного человека
            a = age + visit
            t = b[0] + b[1] * a + b[2] * sex + b[3] * a * sex + rnd.gauss(0, sd)
            rows.append({"participant_id": f"S{i}", "age": a, "sex": sex, "value": math.expm1(t)})
    return rows


def test_fit_recovers_synthetic_expectation():
    """Подобранное ожидание совпадает с заданным в синтетике в пределах шума (коэффициенты по отдельности
    коррелированы, поэтому сравниваются ожидания по возрасту и полу)."""
    b = (-0.9, 0.026, -0.3, 0.0077)
    fit = fit_expectation(synthetic(n=4000, b=b))
    for age in (42, 50, 58, 63):
        for sex in (0, 1):
            got = fit["intercept"] + fit["age_coef"] * age + fit["sex_coef"] * sex + fit["age_sex_coef"] * age * sex
            assert got == pytest.approx(b[0] + b[1] * age + b[2] * sex + b[3] * age * sex, abs=0.03)
    assert fit["residual_sd"] == pytest.approx(0.36, abs=0.015) and fit["n_participants"] == 4000


def test_split_keeps_participant_together():
    train, hold = split_by_participant(synthetic())
    assert {r["participant_id"] for r in train}.isdisjoint({r["participant_id"] for r in hold})
    assert 0.2 < len(hold) / (len(train) + len(hold)) < 0.4


def test_holdout_validation_and_full_cycle():
    rec = {"sample": {k: "x" for k in ("source", "description", "n_participants", "age_min", "age_max", "sexes",
                                       "region", "inclusion_criteria", "exclusion_criteria",
                                       "score2_applicability_rules", "expectation_method", "dispersion_method",
                                       "holdout_method", "date", "version")}}
    out = refit(rec, synthetic())
    assert out["status"] == "fitted_not_approved"
    v = out["validation"]
    assert abs(v["mean_z"]) < 0.15 and v["sd_z"] == pytest.approx(1.0, abs=0.12)
    part = {"sample": {**rec["sample"], "region": None}}
    assert record_status(part) == ("reference_sample_incomplete", ["region"])
    assert refit(part, synthetic())["fit"] is None


def test_too_few_rows():
    with pytest.raises(ValueError):
        fit_expectation(synthetic(n=2)[:4])
