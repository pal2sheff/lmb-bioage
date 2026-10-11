"""PhenoAge (Levine 2018; поправка PLoS Med 2019) — контрольный ориентир, в LMB v0.3 не входит.

Константы ниже переписаны из публикаций независимо от файла параметров: тест ловит ошибку переноса.
Эталонов официального калькулятора нет — reference_cases_verified = false.
"""
import math

import pytest

from lmb_engine.core import Measurement, Qualifier, Sex, Status
from lmb_engine.indices import load_phenoage_params, phenoage
from tests.helpers import enc

LAB = dict(albumin_serum=45, creatinine_serum=70, glucose_fasting=5.0, crp=1.0, lymphocytes_abs=2.0, wbc=6.0,
           mcv=90, rdw=13, alp=70)


def published(alb, cr, glu, crp_mgl, lym_pct, mcv, rdw, alp, wbc, age):
    xb = (-19.907 - 0.0336 * alb + 0.0095 * cr + 0.1953 * glu + 0.0954 * math.log(crp_mgl / 10)
          - 0.0120 * lym_pct + 0.0268 * mcv + 0.3306 * rdw + 0.00188 * alp + 0.0554 * wbc + 0.0804 * age)
    m = 1 - math.exp(-1.51714 * math.exp(xb) / 0.0076927)
    return 141.50 + math.log(-0.00553 * math.log(1 - m)) / 0.09165


def test_params_match_publication():
    p = load_phenoage_params()
    assert p["xb"]["intercept"] == -19.907 and p["xb"]["alp"] == 0.00188 and p["xb"]["age"] == 0.0804
    assert p["conversion"] == {"intercept": 141.50, "ln_scale": -0.00553, "divisor": 0.09165}
    assert math.expm1(120 * 0.0076927) == pytest.approx(1.51714, abs=1e-5)
    assert p["applicability"] == {"age_min": 20, "age_max": 84, "fasting_required": True}
    assert p["verification"]["reference_cases_verified"] is False


def test_value_matches_published_formula():
    r = phenoage(enc(age=55, **LAB))
    assert r.status == Status.CALCULATED and r.unit == "years"
    exp = published(45, 70, 5.0, 1.0, 2.0 / 6.0 * 100, 90, 13, 70, 6.0, 55)
    assert r.value == pytest.approx(exp, abs=1e-9)
    assert r.extra["lymphocyte_percent"] == pytest.approx(100 / 3)
    assert r.extra["role"] == "control_reference"
    assert any("не сверены" in w for w in r.warnings)


def test_units_crp_and_albumin_conversions():
    a = phenoage(enc(age=55, **LAB)).value
    b = phenoage(enc(age=55, units={"crp": "mg/dL", "albumin_serum": "g/dL"},
                     **{**LAB, "crp": 0.1, "albumin_serum": 4.5})).value
    assert a == pytest.approx(b, abs=1e-9)


def test_worse_markers_raise_phenoage():
    base = phenoage(enc(age=55, **LAB)).value
    worse = phenoage(enc(age=55, **{**LAB, "crp": 8.0, "rdw": 15.5, "albumin_serum": 38})).value
    assert worse > base


@pytest.mark.parametrize("age,ok", [(19, False), (20, True), (84, True), (85, False)])
def test_age_range(age, ok):
    r = phenoage(enc(age=age, **LAB))
    assert (r.status == Status.CALCULATED) is ok
    if not ok:
        assert r.status == Status.NOT_APPLICABLE and r.value is None


def test_blocking_rules():
    assert phenoage(enc(age=55, **{k: v for k, v in LAB.items() if k != "crp"})).status == Status.MISSING_DATA
    below = phenoage(enc(age=55, **{**LAB, "crp": Measurement(0.2, "mg/L", Qualifier.LT)}))
    assert below.status == Status.INVALID_INPUT and below.value is None       # предел определения не подставляется
    assert phenoage(enc(age=55, **{**LAB, "lymphocytes_abs": 7.0})).status == Status.INVALID_INPUT
    assert phenoage(enc(age=55, flags={"fasting_status": "no"}, **LAB)).status == Status.NOT_APPLICABLE
    assert phenoage(enc(age=55, units={"rdw": "fL"}, **LAB)).status == Status.INVALID_INPUT  # RDW-SD не подставляется
    assert phenoage(enc(age=55, flags={"acute_infection": "yes"}, **LAB)).status == Status.NOT_APPLICABLE


def test_not_in_lmb_formula():
    from lmb_engine.model import load_config
    from lmb_engine.pipeline import run
    cfg = load_config("config/model_v0.3.json")
    assert all(p["input"]["index"] != "phenoage" for p in cfg["normalization"].values())
    out = run(enc(age=55, sex=Sex.MALE, **LAB), cfg)
    idx = {i["code"]: i for i in out["indices"]}
    assert idx["phenoage"]["status"] == "calculated"
