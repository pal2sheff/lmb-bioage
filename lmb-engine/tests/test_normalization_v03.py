"""Нормализация и правила доменов v0.3 по пакету владельца LMB_Claude_Data_1 (11.10.2026).

Числа таблицы ниже — дословная копия раздела 3 документа; тест сверяет с ней конфигурацию.
Сквозной численный пример использует синтетического пациента и две тестовые подстановки
(целевая популяция и отметка сверки SCORE2); сверка SCORE2 с 11.10.2026 есть и в рабочих параметрах.
"""
import copy
import math
from decimal import Decimal

import pytest

from lmb_engine import cardio
from lmb_engine.core import Measurement, Sex, Status
from lmb_engine.model import V03_INTERCEPT, V03_WEIGHTS, check_config, load_config
from lmb_engine.pipeline import run
from tests.helpers import enc

OWNER_TABLE = """
score2      log1p -0.899658  0.026095 -0.297043  0.007705 0.365158 +1
egfr        raw   138.448114 -0.694552 1.562779 -0.040677 8.889928 -1
acr         log1p 0.946022   0.017104  0.230741 -0.003230 0.672528 +1
fib4        log1p 0.236480   0.007291  0.054408 -0.001255 0.206494 +1
homa_ir     log1p 0.682206   0.003799  0.183697 -0.003366 0.336773 +1
tyg         raw   7.963346   0.006609  0.174804 -0.003627 0.325012 +1
aip         raw   -0.117737  0.001019  0.115893 -0.002406 0.268843 +1
whtr        raw   0.387310   0.001841  0.030852 -0.000563 0.049167 +1
nlr         log1p 0.952203   0.000337  0.049062 -0.000447 0.240447 +1
sii         log1p 6.081920  -0.000449  0.048600  0.000039 0.441133 +1
caide       raw   -0.580342  0.106991  0.516611 -0.003742 1.193644 +1
frax_major  log1p -0.600379  0.047611  0.048514 -0.002754 0.481152 +1
"""
CFG = load_config("config/model_v0.3.json")


def owner_rows():
    for line in OWNER_TABLE.strip().splitlines():
        code, t, *nums = line.split()
        yield code, t, [Decimal(x) for x in nums]


def test_table_transferred_exactly():
    norm = CFG["normalization"]
    assert set(norm) == {r[0] for r in owner_rows()} and len(norm) == 12
    for code, t, (a, b, c, d, sd, sign) in owner_rows():
        p = norm[code]
        assert p["transform"] == t
        got = [Decimal(repr(p[k])) for k in ("intercept", "age_coef", "sex_coef", "age_sex_coef", "residual_sd")]
        assert got == [a, b, c, d, sd], code
        assert Decimal(p["sign"]) == sign


def test_units_and_inputs():
    u = {c: (p["input"]["index"], p["input"]["unit"]) for c, p in CFG["normalization"].items()}
    assert u["score2"] == ("score2", "%") and u["frax_major"] == ("frax_kz", "%")
    assert u["acr"] == ("acr", "mg/g") and u["egfr"] == ("egfr_ckdepi_cr_2021", "mL/min/1.73m2")
    assert u["caide"] == ("caide", "points") and u["sii"] == ("sii", "10^9/L")
    assert "score2_op" not in CFG["normalization"]          # перенос на SCORE2-OP не подтверждён


def test_domain_rules():
    d = CFG["domains"]
    assert d["cardio"] == {"rule": "single", "inputs": ["score2"], "weights": None, "missing_policy": "all_required"}
    assert d["metabolic"]["rule"] == "mean" and d["metabolic"]["inputs"] == ["homa_ir", "tyg", "aip", "whtr"]
    assert d["renal"]["inputs"] == ["egfr", "acr"] and d["inflammation"]["inputs"] == ["nlr", "sii"]
    assert d["hepatic"]["inputs"] == ["fib4"] and d["brain"]["inputs"] == ["caide"]
    assert d["bone"]["inputs"] == ["frax_major"]


def test_config_status():
    c = check_config(CFG)
    assert c.valid and c.gaps == ["target_population"]
    # решение владельца 11.10.2026: клиническая популяция и референтная выборка не заданы,
    # техническая область тестирования хранится отдельно
    assert CFG["target_population"] is None and CFG["reference_sample"] is None
    assert CFG["research_mode"] == "local_synthetic"
    rp = CFG["research_population"]
    assert (rp["age_min"], rp["age_max"], rp["score2_region"]) == (40, 64, "high")
    assert any("Клиническая валидация не проведена" in x for x in CFG["research_limitations"])
    assert CFG["scientific_status"] == "not_validated" and CFG["synthetic_parameters"] is False
    assert "24.09.2026" in CFG["parameters_source"]["origin"]


# ------------------------------------------------------------------ синтетический пациент
FLAGS = {"smoking_current": "no", "ascvd": "no", "ckd_known": "no", "fh": "no",
         "very_high_single_risk_factor": "no", "education_years": "14", "physical_activity_caide": "active",
         "frax_source": "manual", "frax_with_bmd": False}
VALUES = dict(height_cm=165, weight_kg=68, waist_cm=82, sbp_mmhg=128, glucose_fasting=5.2, insulin_fasting=8,
              tg=1.3, tc=5.4, hdl=1.5, creatinine_serum=70, u_albumin=20, u_creatinine=10, ast=22, alt=20,
              platelets=240, neutrophils_abs=3.5, lymphocytes_abs=2.0,
              frax_major_10y_pct=Measurement(6.5, "%"), frax_hip_10y_pct=Measurement(1.0, "%"))


def patient(age=55, sex=Sex.FEMALE, **over):
    return enc(age=age, sex=sex, flags=FLAGS, **{**VALUES, **over})


@pytest.fixture
def verified_score2(monkeypatch):
    """Тестовая подстановка: SCORE2 считается сверенным. В рабочей конфигурации — нет."""
    real = cardio.load_params

    def fake(code):
        p = copy.deepcopy(real(code))
        p["verification"]["heartscore_verified"] = True
        return p
    monkeypatch.setattr(cardio, "load_params", fake)


def manual_z(code, x, age, sex_code):
    p = CFG["normalization"][code]
    t = math.log1p(x) if p["transform"] == "log1p" else x
    exp_ = p["intercept"] + p["age_coef"] * age + p["sex_coef"] * sex_code + p["age_sex_coef"] * age * sex_code
    z = p["sign"] * (t - exp_) / p["residual_sd"]
    return z, max(-3, min(3, z))


def by(out, key):
    return {d["domain"]: d for d in out[key]} if key == "domains" else {i["code"]: i for i in out[key]}


def test_acr_converted_to_mg_per_g():
    out = run(patient(), CFG)
    acr = by(out, "indices")["acr"]
    assert acr["value"] == pytest.approx(2.0) and acr["unit"] == "mg/mmol"
    assert out["zscores"]["acr"]["t"] == pytest.approx(math.log1p(17.68))


def test_egfr_sign_negative():
    """Более низкая eGFR даёт более положительное (неблагоприятное) Z."""
    low = run(patient(creatinine_serum=110), CFG)["zscores"]["egfr"]["z_raw"]
    high = run(patient(creatinine_serum=60), CFG)["zscores"]["egfr"]["z_raw"]
    assert low > high


def test_zscores_match_manual_formula():
    out = run(patient(), CFG)
    idx = by(out, "indices")
    for code, src in [("egfr", "egfr_ckdepi_cr_2021"), ("fib4", "fib4"), ("homa_ir", "homa_ir"), ("tyg", "tyg"),
                      ("aip", "aip"), ("whtr", "whtr"), ("nlr", "nlr"), ("sii", "sii"), ("caide", "caide"),
                      ("frax_major", "frax_kz")]:
        z_raw, z = manual_z(code, idx[src]["value"], 55, 0)
        assert out["zscores"][code]["z_raw"] == pytest.approx(z_raw, abs=1e-12), code
        assert out["zscores"][code]["z_clipped"] == pytest.approx(z, abs=1e-12), code


def test_metabolic_mean_fixed_denominator_and_block():
    out = run(patient(), CFG)
    zs = out["zscores"]
    m = by(out, "domains")["metabolic"]
    assert m["status"] == "calculated"
    assert m["score"] == pytest.approx(sum(zs[c]["z_clipped"] for c in ("homa_ir", "tyg", "aip", "whtr")) / 4)
    out2 = run(patient(insulin_fasting=None), CFG)
    m2 = by(out2, "domains")["metabolic"]
    assert m2["status"] == "missing_data" and m2["score"] is None      # не среднее трёх оставшихся


def test_clip_keeps_raw():
    out = run(patient(ast=300, alt=20, platelets=60), CFG)
    z = out["zscores"]["fib4"]
    assert z["z_raw"] > 3 and z["z_clipped"] == 3


def test_bone_uses_major_only():
    a = run(patient(), CFG)["zscores"]["frax_major"]["z_raw"]
    b = run(patient(frax_hip_10y_pct=Measurement(9.0, "%")), CFG)["zscores"]["frax_major"]["z_raw"]
    assert a == b


def test_score2op_not_normalized(verified_score2):
    out = run(patient(age=75), CFG)
    cardio_dom = by(out, "domains")["cardio"]
    assert cardio_dom["status"] != "calculated" and cardio_dom["score"] is None


def test_shipped_config_blocks_integral():
    """Клинический итог по-прежнему заблокирован: нет целевой популяции."""
    out = run(patient(), CFG)
    assert out["status"] == "blocked" and out["bioage_years"] is None and out["delta_years"] is None
    assert out["blocking_reasons"] == ["Конфигурация модели неполная: target_population"]
    assert all(d["status"] == "calculated" for d in out["domains"] if d["domain"] in V03_WEIGHTS)


# ------------------------------------------------------------------ исследовательский расчёт
def test_research_calculated_without_target_population():
    out = run(patient(), CFG)
    r = out["research"]
    assert r["status"] == "calculated" and r["mode"] == "local_synthetic" and r["reasons"] == []
    assert r["target_population"] is None and r["reference_sample"] is None
    assert r["scientific_status"] == "not_validated" and r["model_config_sha256"] == out["model_config_sha256"]
    doms = by(out, "domains")
    contrib = {d: V03_WEIGHTS[d] * doms[d]["score"] for d in V03_WEIGHTS}
    assert r["contributions"] == pytest.approx(contrib, abs=1e-12)
    assert r["intercept"] == 0.08
    assert r["delta_years"] == pytest.approx(math.fsum([0.08, *contrib.values()]), abs=1e-12)
    assert r["bioage_years"] == pytest.approx(55 + r["delta_years"], abs=1e-12)
    assert set(r["contributions"]) == set(V03_WEIGHTS)             # Muscle и Adaptive не входят
    # клинический итог при этом не появляется
    assert out["bioage_years"] is None and out["contributions"] is None


def test_research_keeps_all_other_checks():
    """Переключатель режима не снимает проверок: пропуск домена или неприменимость блокируют расчёт."""
    no_insulin = run(patient(insulin_fasting=None), CFG)["research"]
    assert no_insulin["status"] == "blocked" and no_insulin["bioage_years"] is None
    assert any(x.startswith("Домен metabolic") for x in no_insulin["reasons"])
    diab = run(enc(age=55, sex=Sex.FEMALE, flags={**FLAGS, "diabetes": "yes"}, **VALUES), CFG)["research"]
    assert diab["status"] == "blocked" and any(x.startswith("Домен cardio") for x in diab["reasons"])
    bad = copy.deepcopy(CFG)
    bad["integral"]["weights"]["renal"] = 1.0
    assert any("недопустима" in x for x in run(patient(), bad)["research"]["reasons"])
    gap = copy.deepcopy(CFG)
    gap["normalization"]["fib4"]["residual_sd"] = None
    assert "normalization.fib4.residual_sd" in " ".join(run(patient(), gap)["research"]["reasons"])


@pytest.mark.parametrize("age,status", [(39, "not_applicable"), (40, "calculated"), (64, "calculated"),
                                        (65, "not_applicable")])
def test_research_population_age_bounds(age, status):
    r = run(patient(age=age), CFG)["research"]
    assert r["status"] == status, r["reasons"]
    if status == "not_applicable":
        assert r["bioage_years"] is None and any("вне технической области" in x for x in r["reasons"])


def test_research_without_mode_not_configured():
    cfg = copy.deepcopy(CFG)
    cfg.pop("research_mode")
    assert run(patient(), cfg)["research"]["status"] == "model_not_configured"


def test_score2_normalization_not_transferred_to_op():
    """70+ лет: SCORE2-OP считается как клинический индекс, но Z Cardio по нормализации SCORE2 нет."""
    out = run(enc(age=72, sex=Sex.MALE, flags=FLAGS, **VALUES), CFG)
    idx = by(out, "indices")
    assert idx["score2_op"]["status"] == "calculated" and idx["score2"]["status"] == "not_applicable"
    assert out["zscores"]["score2"]["status"] == "not_applicable"
    assert by(out, "domains")["cardio"]["status"] != "calculated"


def test_cardio_z_matches_owner_check_hs11_hs12():
    """Решение 11.10.2026, раздел 3: 55 лет, САД 120, ОХС 4,5, ЛПВП 1,5, без курения —
    ожидание v0.3 0,708 % (ж) и 0,939 % (м); при HeartScore 2,6 % и 3,5 % Z ≈ +2,04 и +2,31."""
    for sex, code, hs, z_exp in [(Sex.FEMALE, 0, 2.6, 2.04), (Sex.MALE, 1, 3.5, 2.31)]:
        p = CFG["normalization"]["score2"]
        e = p["intercept"] + p["age_coef"] * 55 + p["sex_coef"] * code + p["age_sex_coef"] * 55 * code
        assert round(math.expm1(e), 3) == {0: 0.708, 1: 0.939}[code]   # SCORE2 подаётся в %
        assert manual_z("score2", hs, 55, code)[0] == pytest.approx(z_exp, abs=0.005)


# ------------------------------------------------------------------ ступени CAIDE
@pytest.mark.parametrize("sex", [Sex.FEMALE, Sex.MALE])
@pytest.mark.parametrize("a,b,expected", [(46, 47, 2.91), (53, 54, 0.90)])
def test_caide_step_brain_contribution(sex, a, b, expected):
    """Переход через границу шкалы при прочих равных: балл возраста растёт на 3 (46→47) и на 1 (53→54);
    вклад Brain (вес 1,2) растёт примерно на 2,91 и 0,90 — это свойство шкалы, а не изменение здоровья."""
    # 7 лет обучения (2 балла) и низкая активность (1 балл): Z не упирается в ±3 по обе стороны границы
    fl = {**FLAGS, "education_years": "8", "physical_activity_caide": "inactive"}
    ra, rb = (run(enc(age=x, sex=sex, flags=fl, **VALUES), CFG) for x in (a, b))
    ia, ib = by(ra, "indices")["caide"], by(rb, "indices")["caide"]
    assert ib["value"] - ia["value"] == (3 if a == 46 else 1)
    assert ia["extra"]["age_band"]["band"] != ib["extra"]["age_band"]["band"]
    za, zb = ra["zscores"]["caide"], rb["zscores"]["caide"]
    assert abs(za["z_raw"]) < 3 and abs(zb["z_raw"]) < 3              # без ограничения ±3
    da, db = by(ra, "domains")["brain"], by(rb, "domains")["brain"]
    step = db["contribution"] - da["contribution"]
    assert step > 0 and step == pytest.approx(expected, abs=0.01)


def test_caide_step_crossings():
    from lmb_engine.indices import caide_age_band, caide_step_crossings
    assert caide_step_crossings(46, 47) == [47] and caide_step_crossings(53, 54) == [54]
    assert caide_step_crossings(60, 45) == [47, 54] and caide_step_crossings(48, 53) == []
    assert [caide_age_band(a)["points"] for a in (46, 47, 53, 54)] == [0, 3, 3, 4]


def test_end_to_end_numeric_with_test_substitutions(verified_score2):
    """Сквозной численный пример (локальный расчёт, не клинический эталон)."""
    cfg = copy.deepcopy(CFG)
    cfg["target_population"] = {"description": "ТЕСТОВАЯ ПОДСТАНОВКА"}
    out = run(patient(), cfg)
    assert out["status"] == "calculated", out["blocking_reasons"]
    doms = by(out, "domains")
    contrib = {d: V03_WEIGHTS[d] * doms[d]["score"] for d in V03_WEIGHTS}
    assert out["contributions"] == pytest.approx(contrib, abs=1e-12)
    assert out["delta_years"] == pytest.approx(V03_INTERCEPT + sum(contrib.values()), abs=1e-12)
    assert out["bioage_years"] == pytest.approx(55 + out["delta_years"], abs=1e-12)
    assert doms["muscle"]["status"] == "not_included" and doms["adaptive"]["contribution"] is None


# ------------------------------------------------------------------ вклады и траектории
def test_domain_contributions_without_total():
    """Вклад ветки = коэффициент × доменная оценка; без полной конфигурации итог не складывается."""
    out = run(patient(), CFG)
    assert out["status"] == "blocked" and out["contributions"] is None and out["delta_years"] is None
    doms = by(out, "domains")
    for d, w in V03_WEIGHTS.items():
        dom = doms[d]
        if dom["status"] == "calculated":
            assert dom["coefficient"] == w
            assert dom["contribution"] == pytest.approx(w * dom["score"], abs=1e-12)
            assert sum(dom["input_contributions"].values()) == pytest.approx(dom["contribution"], abs=1e-12)
        else:
            assert dom["contribution"] is None and dom["input_contributions"] == {}
    m = doms["metabolic"]["input_contributions"]
    assert set(m) == {"homa_ir", "tyg", "aip", "whtr"}
    assert m["tyg"] == pytest.approx(1.5 * out["zscores"]["tyg"]["z_clipped"] / 4)
    assert doms["muscle"]["contribution"] is None and doms["adaptive"]["contribution"] is None


def test_contributions_match_integral(verified_score2):
    cfg = copy.deepcopy(CFG)
    cfg["target_population"] = {"description": "ТЕСТОВАЯ ПОДСТАНОВКА"}
    out = run(patient(), cfg)
    doms = by(out, "domains")
    assert out["contributions"] == pytest.approx({d: doms[d]["contribution"] for d in V03_WEIGHTS}, abs=1e-12)


def test_trajectory_curve_matches_zscore():
    out = run(patient(age=55), CFG)
    tr = out["trajectories"]
    assert "egfr" in tr and "score2" in tr                # SCORE2 сверен с HeartScore 11.10.2026
    for code, t in tr.items():
        z = out["zscores"][code]
        at = next(p for p in t["curve"] if p["age"] == 55)
        p = CFG["normalization"][code]
        exp_t = math.log1p(at["expected"]) if p["transform"] == "log1p" else at["expected"]
        assert exp_t == pytest.approx(z["expected"], abs=1e-9), code
        assert at["lo"] <= at["expected"] <= at["hi"]
        assert t["curve"][0]["age"] == 40 and t["curve"][-1]["age"] == 70
    egfr = tr["egfr"]
    assert egfr["sign"] == -1 and egfr["curve"][0]["expected"] > egfr["curve"][-1]["expected"]   # с возрастом ниже
    assert tr["acr"]["unit"] == "mg/g" and tr["acr"]["value"] == pytest.approx(17.68)
