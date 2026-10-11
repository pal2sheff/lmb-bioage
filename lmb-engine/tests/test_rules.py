"""Ветвления правил: проверка конфигурации, преобразования, правила доменов, редкие входы."""
import datetime as dt
import math

import pytest

from lmb_engine import indices as ix
from lmb_engine.core import Encounter, Measurement, Sex, Status, Tri
from lmb_engine.model import (DOMAINS_V03, DomainResult, ZScore, check_config, default_v03_config,
                              domain_score, integral, zscore)
from lmb_engine.pipeline import run
from tests.helpers import ENC_DATE, enc
from tests.test_model import synthetic_config

P = dict(transform="identity", intercept=0, age_coef=0, sex_coef=0, age_sex_coef=0, sign=1, residual_sd=1)


# ---- проверка конфигурации
@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["integral"].__setitem__("intercept", 0.1), "intercept"),
    (lambda c: c["integral"].__setitem__("required_domains", ["cardio"]), "required_domains"),
    (lambda c: c["integral"].__setitem__("z_clip", 4.0), "z_clip"),
    (lambda c: c["normalization"]["syn_cardio"].__setitem__("sign", 2), "sign"),
    (lambda c: c["normalization"]["syn_cardio"].__setitem__("age_coef", "0.1"), "age_coef"),
    (lambda c: c["domains"]["cardio"].__setitem__("rule", "median"), "rule"),
    (lambda c: c["domains"]["cardio"].__setitem__("rule", "mean"), "mean"),
    (lambda c: c["domains"]["cardio"].__setitem__("inputs", ["syn_cardio", "syn_bone"]), "single"),
    (lambda c: c["domains"]["cardio"].update(rule="weighted_sum", weights={"x": 1}), "weights"),
])
def test_config_errors(mutate, needle):
    cfg = synthetic_config()
    mutate(cfg)
    chk = check_config(cfg)
    assert not chk.valid and any(needle in e for e in chk.errors)


@pytest.mark.parametrize("mutate,gap", [
    (lambda c: c["domains"]["cardio"].update(rule="weighted_sum", weights=None), "domains.cardio.weights"),
    (lambda c: c["domains"]["renal"].update(rule="max", inputs=[]), "domains.renal.inputs"),
    (lambda c: c["domains"]["renal"].update(inputs=["unknown_code"]), "normalization.unknown_code"),
    (lambda c: c["normalization"]["syn_renal"].__setitem__("residual_sd", None), "normalization.syn_renal.residual_sd"),
])
def test_config_gaps(mutate, gap):
    cfg = synthetic_config()
    mutate(cfg)
    chk = check_config(cfg)
    assert gap in chk.gaps and not chk.complete


def test_invalid_config_blocks_integral():
    cfg = synthetic_config()
    cfg["integral"]["intercept"] = 0.5
    doms = {d: DomainResult(d, Status.CALCULATED, score=0.0) for d in DOMAINS_V03}
    r = integral(doms, cfg, 50)
    assert r.status == "blocked" and any("недопустима" in x for x in r.blocking_reasons)


def test_integral_needs_age():
    doms = {d: DomainResult(d, Status.CALCULATED, score=0.0) for d in DOMAINS_V03}
    assert integral(doms, synthetic_config(), None).status == "blocked"


def test_contributions_written_to_domains():
    doms = {d: DomainResult(d, Status.CALCULATED, score=1.0) for d in DOMAINS_V03}
    r = integral(doms, synthetic_config(), 40)
    assert doms["metabolic"].contribution == 1.5 and doms["metabolic"].coefficient == 1.5
    assert r.bioage_years == pytest.approx(48.08)


# ---- преобразования и Z-оценки
@pytest.mark.parametrize("kind,x,t", [("ln", math.e, 1.0), ("ln1p", 0.0, 0.0), ("log10", 100, 2.0)])
def test_transforms(kind, x, t):
    assert zscore("x", x, 50, Sex.MALE, {**P, "transform": kind}).t == pytest.approx(t)


@pytest.mark.parametrize("kind,x", [("ln1p", -1), ("log10", 0), ("cube", 1)])
def test_transform_errors(kind, x):
    assert zscore("x", x, 50, Sex.MALE, {**P, "transform": kind}).status == Status.INVALID_INPUT


def test_zscore_missing_params():
    z = zscore("x", 1, 50, Sex.MALE, {**P, "sign": None})
    assert z.status == Status.MODEL_NOT_CONFIGURED and "sign" in z.reasons[0]


def test_zscore_applicability():
    p = {**P, "applicability": {"age_min": 40, "age_max": 64, "sex": ["female"]}}
    assert zscore("x", 1, 39, Sex.FEMALE, p).status == Status.NOT_APPLICABLE
    assert zscore("x", 1, 65, Sex.FEMALE, p).status == Status.NOT_APPLICABLE
    assert zscore("x", 1, 50, Sex.MALE, p).status == Status.NOT_APPLICABLE
    assert zscore("x", 1, 50, Sex.FEMALE, p).status == Status.CALCULATED


# ---- правила доменов
def _zs(**vals):
    return {k: ZScore(k, Status.CALCULATED, z_clipped=v) for k, v in vals.items()}


def test_domain_rules():
    zs = _zs(a=1.0, b=-2.0)
    assert domain_score("m", {"rule": "max", "inputs": ["a", "b"]}, zs).score == 1.0
    assert domain_score("m", {"rule": "min", "inputs": ["a", "b"]}, zs).score == -2.0
    r = domain_score("m", {"rule": "weighted_sum", "inputs": ["a", "b"], "weights": {"a": 0.5, "b": 0.25}}, zs)
    assert r.score == pytest.approx(0.0)
    assert domain_score("m", {"rule": "median", "inputs": ["a"]}, zs).status == Status.MODEL_NOT_CONFIGURED
    assert domain_score("m", None, zs).status == Status.MODEL_NOT_CONFIGURED
    assert domain_score("m", {"rule": "single", "inputs": ["zzz"]}, zs).status == Status.MISSING_DATA


def test_no_arithmetic_mean_default():
    """Правило «среднее» отсутствует в перечне: среднее не применяется автоматически."""
    cfg = synthetic_config()
    cfg["domains"]["metabolic"]["rule"] = "mean"
    assert not check_config(cfg).valid


# ---- редкие входы индексов
def test_unsupported_unit():
    assert ix.bmi(enc(weight_kg=180, height_cm=70, units={"height_cm": "inch"})).status == Status.INVALID_INPUT


def test_height_in_metres():
    assert ix.bmi(enc(weight_kg=80, height_cm=1.75, units={"height_cm": "m"})).value == pytest.approx(26.1224, abs=1e-4)


def test_birth_after_encounter():
    e = Encounter(birth_date=dt.date(2030, 1, 1), encounter_date=ENC_DATE, sex=Sex.MALE,
                  measurements={"creatinine_serum": Measurement(80, "umol/L")})
    assert ix.egfr_ckdepi_cr_2021(e).status == Status.INVALID_INPUT


def test_flag_accepts_enum():
    e = enc(flags={"fasting_status": Tri.YES})
    assert e.flag("fasting_status") == Tri.YES


def test_non_hdl():
    assert ix.non_hdl(enc(tc=5.0, hdl=1.2)).value == pytest.approx(3.8)
    assert ix.non_hdl(enc(tc=1.2, hdl=1.5)).status == Status.INVALID_INPUT


def test_egfr_idms():
    assert ix.egfr_ckdepi_cr_2021(enc(creatinine_serum=80, flags={"creatinine_idms": "no"})).status == Status.NOT_APPLICABLE
    r = ix.egfr_ckdepi_cr_2021(enc(creatinine_serum=80, flags={"creatinine_idms": "unknown"}))
    assert r.status == Status.CALCULATED and r.warnings


def test_acr_lab_bad_unit_is_invalid():
    r = ix.acr(enc(acr_lab=Measurement(2.0, "mg/L")))
    assert r.status == Status.INVALID_INPUT and r.invalid_fields == ["acr_lab"]


def test_fib4_minor():
    assert ix.fib4(enc(age=16, ast=20, alt=25, platelets=200)).status == Status.NOT_APPLICABLE


def test_pipeline_without_sex_skips_zscores():
    cfg = synthetic_config()
    out = run(enc(age=52, sex=None), cfg, {f"syn_{d}": 25.0 for d in DOMAINS_V03})
    assert out["status"] == "blocked"
    assert all(z["status"] != "calculated" and z["z_raw"] is None for z in out["zscores"].values())
