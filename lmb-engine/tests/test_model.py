"""Механизм модели v0.3 (Z-17…Z-20, B-12…B-15).

Тесты на заранее заданных доменных оценках проверяют арифметику выражения и не
заменяют отсутствующие нормативы. Синтетическая конфигурация помечена synthetic.
"""
import copy

import pytest

from lmb_engine.core import Sex, Status
from lmb_engine.model import (DOMAINS_V03, V03_INTERCEPT, V03_WEIGHTS, DomainResult, check_config,
                              combine, default_v03_config, domain_score, integral, load_config, zscore)
from lmb_engine.pipeline import run
from tests.helpers import enc


def delta(scores):
    return combine(scores, V03_WEIGHTS, V03_INTERCEPT)[1]


# Z-17…Z-19 — эталоны владельца
def test_z17_all_zero():
    assert delta({d: 0.0 for d in DOMAINS_V03}) == pytest.approx(0.08, abs=1e-12)


def test_z18_only_cardio():
    s = {d: 0.0 for d in DOMAINS_V03}
    s["cardio"] = 1.0
    assert delta(s) == pytest.approx(0.78, abs=1e-12)


def test_z19_all_one():
    assert delta({d: 1.0 for d in DOMAINS_V03}) == pytest.approx(8.08, abs=1e-12)


def test_z20_mixed_and_contributions_sum():
    s = dict(cardio=0.5, metabolic=-0.4, renal=0.2, hepatic=-1.0, inflammation=0.3, brain=0.0, bone=-0.6)
    contrib, d = combine(s, V03_WEIGHTS, V03_INTERCEPT)
    assert d == pytest.approx(-1.03, abs=1e-12)
    assert V03_INTERCEPT + sum(contrib.values()) == pytest.approx(d, abs=1e-12)


# текущая конфигурация v0.3
def test_shipped_config_matches_owner_and_is_incomplete():
    """Веса и постоянная — как в v0.3; нормализация и правила — из LMB_Claude_Data_1 (11.10.2026).
    Единственный пробел — целевая популяция."""
    cfg = load_config("config/model_v0.3.json")
    base = default_v03_config()
    assert cfg["integral"] == base["integral"] and cfg["sex_coding"] == base["sex_coding"]
    c = check_config(cfg)
    assert c.valid and c.gaps == ["target_population"]
    assert cfg["synthetic_parameters"] is False and cfg["scientific_status"] == "not_validated"


def test_weights_cannot_be_changed():
    cfg = default_v03_config()
    cfg["integral"]["weights"]["metabolic"] = 1.6
    assert not check_config(cfg).valid


def test_muscle_adaptive_must_stay_null():
    cfg = default_v03_config()
    cfg["integral"]["weights"]["muscle"] = 0.5
    assert not check_config(cfg).valid


def test_current_run_blocks_bioage():
    e = enc(age=52, sex=Sex.MALE, glucose_fasting=5, insulin_fasting=9, creatinine_serum=80)
    out = run(e, default_v03_config())
    assert out["status"] == "blocked"
    assert out["bioage_years"] is None and out["delta_years"] is None and out["contributions"] is None
    assert "model_config_incomplete" in out["warnings"]
    doms = {d["domain"]: d for d in out["domains"]}
    assert doms["muscle"]["status"] == "not_included" and doms["muscle"]["contribution"] is None
    assert doms["renal"]["status"] == "model_not_configured"
    idx = {i["code"]: i for i in out["indices"]}
    assert idx["homa_ir"]["status"] == "calculated"  # индексы доступны без итога


# B-12
def test_residual_sd_must_be_positive():
    cfg = synthetic_config()
    cfg["normalization"]["bmi"]["residual_sd"] = 0
    assert not check_config(cfg).valid
    z = zscore("bmi", 25, 50, Sex.MALE, cfg["normalization"]["bmi"])
    assert z.status == Status.MODEL_NOT_CONFIGURED


# B-13
def test_z_clip_keeps_raw():
    p = dict(transform="identity", intercept=0, age_coef=0, sex_coef=0, age_sex_coef=0, sign=1, residual_sd=1)
    z = zscore("x", 4.2, 50, Sex.FEMALE, p)
    assert z.z_raw == pytest.approx(4.2) and z.z_clipped == 3.0 and z.warnings


def test_lmb_sex_coding_and_age_sex_term():
    p = dict(transform="identity", intercept=1, age_coef=0.1, sex_coef=2, age_sex_coef=0.01,
             sign=-1, residual_sd=2)
    zf = zscore("x", 10, 50, Sex.FEMALE, p)   # female = 0
    zm = zscore("x", 10, 50, Sex.MALE, p)     # male = 1
    assert zf.expected == pytest.approx(6.0) and zf.z_raw == pytest.approx(-2.0)
    assert zm.expected == pytest.approx(8.5) and zm.z_raw == pytest.approx(-0.75)


def test_transform_domain_checked():
    p = dict(transform="ln", intercept=0, age_coef=0, sex_coef=0, age_sex_coef=0, sign=1, residual_sd=1)
    assert zscore("x", 0, 50, Sex.MALE, p).status == Status.INVALID_INPUT


def test_unknown_transform_rejected():
    cfg = synthetic_config()
    cfg["normalization"]["bmi"]["transform"] = "sqrt"
    assert not check_config(cfg).valid


# B-14
def test_missing_domain_blocks_without_reweighting():
    doms = {d: DomainResult(d, Status.CALCULATED, score=0.1) for d in DOMAINS_V03}
    doms["brain"] = DomainResult("brain", Status.MODEL_NOT_CONFIGURED)
    r = integral(doms, synthetic_config(), 50)
    assert r.status == "blocked" and r.bioage_years is None
    assert any("brain" in x for x in r.blocking_reasons)


def test_domain_requires_all_inputs():
    from lmb_engine.model import ZScore
    zs = {"a": ZScore("a", Status.CALCULATED, z_clipped=1.0), "b": ZScore("b", Status.NOT_APPLICABLE)}
    r = domain_score("metabolic", {"rule": "max", "inputs": ["a", "b"]}, zs)
    assert r.status == Status.NOT_APPLICABLE and r.score is None


# сквозной путь на синтетической конфигурации (не клинический результат)
def synthetic_config():
    cfg = default_v03_config()
    cfg["synthetic_parameters"] = True
    cfg["target_population"] = {"description": "SYNTHETIC — только для тестов"}
    # для каждого домена — один индикатор BMI с разными синтетическими параметрами,
    # подобранными так, что Z = заранее известное число
    targets = dict(cardio=0.5, metabolic=-0.4, renal=0.2, hepatic=-1.0, inflammation=0.3, brain=0.0, bone=-0.6)
    for d, z in targets.items():
        code = f"syn_{d}"
        cfg["normalization"][code] = dict(input={"index": code, "unit": "syn"}, transform="identity",
                                          intercept=25.0 - z, age_coef=0.0,
                                          sex_coef=0.0, age_sex_coef=0.0, sign=1, residual_sd=1.0)
        cfg["domains"][d] = {"rule": "single", "inputs": [code], "weights": None,
                             "missing_policy": "all_required"}
    cfg["normalization"]["bmi"] = dict(input={"index": "bmi", "unit": "kg/m2"}, transform="identity",
                                       intercept=0, age_coef=0, sex_coef=0,
                                       age_sex_coef=0, sign=1, residual_sd=1)
    return cfg


def test_synthetic_end_to_end():
    cfg = synthetic_config()
    assert check_config(cfg).complete
    external = {f"syn_{d}": 25.0 for d in DOMAINS_V03}
    out = run(enc(age=52), cfg, external)
    assert out["status"] == "calculated"
    assert out["delta_years"] == pytest.approx(-1.03, abs=1e-12)
    assert out["bioage_years"] == pytest.approx(50.97, abs=1e-12)
    assert "synthetic_parameters" in out["warnings"]


# B-15
def test_lqone_value_does_not_change_integral():
    cfg = synthetic_config()
    base = {f"syn_{d}": 25.0 for d in DOMAINS_V03}
    a = run(enc(age=52), cfg, base)
    b = run(enc(age=52), cfg, {**base, "lqone_summary": 61.0})
    assert a["delta_years"] == b["delta_years"]
    assert a["input_version"] != b["input_version"]  # снимок входов отличается


def test_snapshot_hash_stable():
    cfg = copy.deepcopy(default_v03_config())
    e = enc(age=52, glucose_fasting=5, insulin_fasting=9)
    assert run(e, cfg)["input_version"] == run(e, cfg)["input_version"]
