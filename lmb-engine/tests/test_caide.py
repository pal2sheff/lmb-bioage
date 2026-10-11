"""CAIDE, модель 1 без APOE — таблица владельца (LMB_Claude_Data_1, раздел 6; Kivipelto 2006, табл. 2)."""
import pytest

from lmb_engine import indices as ix
from lmb_engine.core import Sex, Status
from tests.helpers import enc

BASE = dict(sbp_mmhg=130, tc=5.0, height_cm=170, weight_kg=70)          # ИМТ 24,2
ACTIVE = {"education_years": "12", "physical_activity_caide": "active"}


def caide(age=50, sex=Sex.FEMALE, flags=None, **values):
    return ix.caide(enc(age=age, sex=sex, flags={**ACTIVE, **(flags or {})}, **{**BASE, **values}))


@pytest.mark.parametrize("age,pts", [(39, 0), (46, 0), (47, 3), (53, 3), (54, 4), (64, 4)])
def test_age_boundaries(age, pts):
    r = caide(age=age)
    assert r.status == Status.CALCULATED and r.extra["points"]["age"] == pts


@pytest.mark.parametrize("years,pts", [("0", 3), ("6", 3), ("7", 2), ("9", 2), ("10", 0), ("20", 0)])
def test_education(years, pts):
    assert caide(flags={"education_years": years}).extra["points"]["education"] == pts


@pytest.mark.parametrize("field,value,key,pts", [
    ("sbp_mmhg", 140, "sbp", 0), ("sbp_mmhg", 141, "sbp", 2),
    ("tc", 6.5, "tc", 0), ("tc", 6.6, "tc", 2),
])
def test_thresholds_strict(field, value, key, pts):
    assert caide(**{field: value}).extra["points"][key] == pts


def test_bmi_threshold_strict():
    # 170 см: 86,6 кг → ИМТ 29,97; 86,8 кг → 30,03; 200 см и 120 кг → ровно 30,0
    assert caide(weight_kg=86.6).extra["points"]["bmi"] == 0
    assert caide(weight_kg=86.8).extra["points"]["bmi"] == 2
    assert caide(height_cm=200, weight_kg=120).extra["points"]["bmi"] == 0     # ровно 30,0


def test_sex_and_activity():
    assert caide(sex=Sex.MALE).extra["points"]["sex"] == 1
    assert caide(flags={"physical_activity_caide": "inactive"}).extra["points"]["activity"] == 1


def test_max_score_15():
    r = caide(age=60, sex=Sex.MALE, sbp_mmhg=160, tc=7.0, weight_kg=95,
              flags={"education_years": "5", "physical_activity_caide": "inactive"})
    assert r.value == 15 and r.unit == "points"


def test_min_score_0():
    assert caide(age=45).value == 0


def test_unknown_activity_is_not_inactive():
    r = caide(flags={"physical_activity_caide": "unknown"})
    assert r.status == Status.MISSING_DATA and r.value is None and "physical_activity_caide" in r.missing_fields
    assert caide(flags={"physical_activity_caide": None}).status == Status.MISSING_DATA


@pytest.mark.parametrize("bad", ["9.5", "abc", "-1", "31"])
def test_education_invalid(bad):
    assert caide(flags={"education_years": bad}).status == Status.INVALID_INPUT


def test_education_missing():
    assert caide(flags={"education_years": None}).status == Status.MISSING_DATA


@pytest.mark.parametrize("age", [38, 65, 75])
def test_outside_model_age(age):
    r = caide(age=age)
    assert r.status == Status.NOT_APPLICABLE and r.value is None


def test_source_recorded():
    r = caide()
    assert "Kivipelto" in r.extra["source"] and "без APOE" in r.extra["model"]
