"""Проверочный режим cardio_anchor_experiment_v1 и контрольная арифметика примера 1
(задание владельца 11.10.2026). Допуск для округлённых чисел владельца — 0,0001."""
import datetime as dt
import math

import pytest

from lmb_engine.core import Sex
from lmb_engine.experiments import control_score2_pct, load_experiment
from lmb_engine.model import load_config
from lmb_engine.pipeline import run
from tests.examples import EXAMPLE_1, EXAMPLE_2, ENC_DATE, encounter

CFG = load_config("config/model_v0.3.json")
TOL = 1e-4


def by_code(out):
    return {i["code"]: i for i in out["indices"]}


@pytest.fixture(scope="module")
def ex1():
    return run(encounter(EXAMPLE_1), CFG)


def test_example1_v03_control_arithmetic(ex1):
    idx, r = by_code(ex1), ex1["research"]
    assert ex1["age_years"] == 55
    assert idx["score2"]["extra"]["age_exact_years"] == pytest.approx(55.610959, abs=1e-6)
    assert idx["score2"]["value"] == pytest.approx(3.22300, abs=TOL)
    assert math.expm1(ex1["zscores"]["score2"]["expected"]) == pytest.approx(0.70842, abs=TOL)
    assert r["bioage_years"] == pytest.approx(58.60469, abs=TOL)
    assert idx["phenoage"]["value"] == pytest.approx(50.10730, abs=TOL)        # самостоятельный показатель
    assert r["contributions"]["cardio"] == pytest.approx(1.73483, abs=TOL)
    assert r["contributions"]["renal"] == pytest.approx(1.89879, abs=TOL)
    assert r["bioage_years"] - r["contributions"]["cardio"] == pytest.approx(56.86986, abs=TOL)


def test_cardio_contribution_ceiling():
    """Максимальный вклад Cardio — 0,7 × 3 = 2,1 года. (Сравнение LMB с PhenoAge не ведётся — решение 11.10.2026.)"""
    assert CFG["integral"]["weights"]["cardio"] * CFG["integral"]["z_clip"] == pytest.approx(2.1)


def test_seven_contributions_sum(ex1):
    r = ex1["research"]
    assert set(r["contributions"]) == {"cardio", "metabolic", "renal", "hepatic", "inflammation", "brain", "bone"}
    assert math.fsum([r["intercept"], *r["contributions"].values()]) == pytest.approx(r["delta_years"], abs=1e-12)


def test_example1_experiment_control_arithmetic(ex1):
    x = ex1["research"]["cardio_anchor_experiment"]
    assert x["status"] == "calculated" and x["id"] == "cardio_anchor_experiment_v1"
    assert x["control_score2_pct"] == pytest.approx(2.57530, abs=TOL)
    assert x["z_clipped"] == pytest.approx(0.45596, abs=TOL)
    assert x["contribution"] == pytest.approx(0.31917, abs=TOL)
    assert x["bioage_years"] == pytest.approx(57.18903, abs=TOL)
    assert x["contribution_v03"] == pytest.approx(1.73483, abs=TOL)
    assert x["change_years"] == pytest.approx(x["contribution"] - x["contribution_v03"], abs=1e-12)
    assert x["label"] == "Проверочный расчёт с условным контрольным профилем"
    assert x["disclaimer"] == "Популяционная нормализация и перевод в годы не подтверждены"


def test_v03_unchanged_by_experiment(ex1):
    """Основной расчёт v0.3 не меняется: свободный член, веса и остальные вклады те же."""
    assert CFG["normalization"]["score2"]["residual_sd"] == 0.365158
    assert ex1["research"]["contributions"]["cardio"] == pytest.approx(1.73483, abs=TOL)
    exp = load_experiment()
    assert exp["residual_sd"] == CFG["normalization"]["score2"]["residual_sd"] and exp["weight"] == 0.7


@pytest.mark.parametrize("sex", [Sex.FEMALE, Sex.MALE])
@pytest.mark.parametrize("age", range(40, 65))
def test_control_profile_gives_zero(sex, age):
    """У контрольного профиля экспериментальный вклад Cardio равен нулю; возраст SCORE2 совпадает."""
    birth = dt.date(ENC_DATE.year - age - 1, 12, 31)
    out = run(encounter(EXAMPLE_1, birth=birth, sex=sex, sbp_mmhg=120, tc=4.5, hdl=1.5), CFG)
    x = out["research"]["cardio_anchor_experiment"]
    s2 = by_code(out)["score2"]
    assert x["age_exact_years"] == s2["extra"]["age_exact_years"]
    assert x["control_score2_pct"] == pytest.approx(s2["value"], abs=1e-12)
    assert x["z_raw"] == pytest.approx(0, abs=1e-12) and x["contribution"] == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("sex", [Sex.FEMALE, Sex.MALE])
def test_monotonic_in_score2(sex):
    contribs, risks = [], []
    for sbp in (100, 120, 140, 160, 180, 200, 220, 240):
        x = run(encounter(EXAMPLE_1, sex=sex, sbp_mmhg=sbp), CFG)["research"]["cardio_anchor_experiment"]
        risks.append(x["score2_pct"])
        contribs.append(x["contribution"])
    assert risks == sorted(risks)
    for a, b in zip(contribs, contribs[1:]):
        assert b >= a - 1e-12
    assert max(contribs) <= 0.7 * 3 + 1e-12


def test_not_transferred_to_score2_op():
    out = run(encounter(EXAMPLE_1, birth=dt.date(1953, 1, 1)), CFG)      # 73 года
    assert by_code(out)["score2_op"]["status"] == "calculated"
    x = out["research"]["cardio_anchor_experiment"]
    assert x["status"] != "calculated" and x["contribution"] is None and x["bioage_years"] is None


def test_incomplete_domain_blocks_experiment_total():
    out = run(encounter(EXAMPLE_1, insulin_fasting=None), CFG)
    x = out["research"]["cardio_anchor_experiment"]
    assert out["research"]["status"] == "blocked"
    assert x["status"] == "blocked" and x["bioage_years"] is None and x["contribution"] is not None


def test_example2_both_modes():
    out = run(encounter(EXAMPLE_2), CFG)
    r, x = out["research"], out["research"]["cardio_anchor_experiment"]
    assert r["bioage_years"] == pytest.approx(46.88, abs=0.01)
    assert x["status"] == "calculated" and x["bioage_years"] < r["bioage_years"]


def test_control_function_uses_score2_formula():
    from lmb_engine import cardio
    p = cardio.load_params("score2")
    assert control_score2_pct(Sex.FEMALE, 55.610959, load_experiment()["control_profile"]) == pytest.approx(
        cardio.compute(p, 55.610959, Sex.FEMALE, False, 120, 4.5, 1.5)["risk"] * 100)
