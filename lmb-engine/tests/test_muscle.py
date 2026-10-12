"""Мышечный возраст (модель владельца 0.1-synthetic, задание 12.10.2026) и ASM по четырём сегментам Visbody."""
import math

import pytest

from lmb_engine.core import Sex, Status
from lmb_engine.model import config_path, load_config
from lmb_engine.muscle import load_muscle_params, muscle_age, muscle_age_from, references
from lmb_engine.pipeline import run
from tests.examples import EXAMPLE_2, encounter
from tests.helpers import enc

CONTROL = dict(height_cm=170, grip_right_kg=50, grip_left_kg=48, chair_stand_5x_s=6,
               visbody_seg_arm_left_kg=3.43, visbody_seg_arm_right_kg=3.52,
               visbody_seg_leg_left_kg=9.38, visbody_seg_leg_right_kg=9.42)


def test_owner_control_case_exact():
    r = muscle_age(enc(age=42, sex=Sex.MALE, **CONTROL))
    assert r.status == Status.CALCULATED and r.unit == "years"
    e = r.extra
    assert e["asm_kg"] == pytest.approx(25.75, abs=1e-12)
    assert e["asmi"] == pytest.approx(8.910034602076125, abs=1e-12)
    assert e["p"] == pytest.approx(34.793525920355904, abs=1e-9)
    assert e["p_ref"] == pytest.approx(43.10228656143997, abs=1e-9)
    assert r.value == pytest.approx(33.69123935891594, abs=1e-9)
    assert e["grip_used_kg"] == 50                     # максимальный результат двух рук
    assert round(r.value, 1) == 33.7 and round(e["delta_years"], 1) == -8.3
    assert e["asm_source"] == "Visbody, расчёт по четырём сегментам" and e["in_model"] is False


def test_control_values_in_config_match():
    p = load_muscle_params()
    c = p["control_case"]
    asmi = sum(c["segments_kg"].values()) / c["height_m"] ** 2
    out = muscle_age_from(p, c["age"], max(c["grip_right_kg"], c["grip_left_kg"]), c["chair_stand_s"], asmi)
    assert out["muscle_age"] == pytest.approx(c["expected"]["muscle_age"], abs=1e-9)


@pytest.mark.parametrize("age", [20, 22, 30, 42, 44.2, 55, 63.8, 70, 87, 89])
def test_reference_inputs_give_calendar_age(age):
    p = load_muscle_params()
    ref = references(p, age)
    out = muscle_age_from(p, age, ref["grip_kg"], ref["chair_stand_s"], ref["asmi_kg_m2"])
    assert out["muscle_age"] == pytest.approx(age, abs=1e-9)


def test_interpolation_and_clamp():
    p = load_muscle_params()
    assert references(p, 44.5)["grip_kg"] == pytest.approx(41 + (36 - 41) * 2.5 / 5)
    assert references(p, 20)["grip_kg"] == 40 and references(p, 89)["chair_stand_s"] == 12.4   # крайние значения
    assert references(p, 89)["asmi_kg_m2"] == 7.3
    # время интерполируется в секундах, логарифм — после
    t = references(p, 44.5)["chair_stand_s"]
    assert t == pytest.approx(6.5 + (7.5 - 6.5) * 0.5)


def test_directions():
    base = muscle_age(enc(age=42, sex=Sex.MALE, **CONTROL)).value
    weaker = muscle_age(enc(age=42, sex=Sex.MALE, **{**CONTROL, "grip_right_kg": 40})).value
    slower = muscle_age(enc(age=42, sex=Sex.MALE, **{**CONTROL, "chair_stand_5x_s": 9})).value
    thinner = muscle_age(enc(age=42, sex=Sex.MALE, **{**CONTROL, "visbody_seg_leg_left_kg": 7})).value
    assert weaker > base and slower > base and thinner > base


def test_female_and_age_not_applied_measurements_kept():
    f = muscle_age(enc(age=42, sex=Sex.FEMALE, **CONTROL))
    assert f.status == Status.NOT_APPLICABLE and f.value is None and f.extra["asmi"] == pytest.approx(8.910034602076125)
    old = muscle_age(enc(age=90, sex=Sex.MALE, **CONTROL))
    assert old.status == Status.NOT_APPLICABLE and old.value is None
    young = muscle_age(enc(age=19, sex=Sex.MALE, **CONTROL))
    assert young.status == Status.NOT_APPLICABLE


def test_chair_stand_unable_separate_status():
    vals = {k: v for k, v in CONTROL.items() if k != "chair_stand_5x_s"}
    r = muscle_age(enc(age=42, sex=Sex.MALE, flags={"chair_stand_result": "unable"}, **vals))
    assert r.status == Status.NOT_APPLICABLE and r.value is None and r.extra["chair_stand_unable"] is True
    assert "условное время не подставляется" in r.reasons[0] and not r.missing_fields
    both = muscle_age(enc(age=42, sex=Sex.MALE, flags={"chair_stand_result": "unable"}, **CONTROL))
    assert both.status == Status.INVALID_INPUT and both.invalid_fields == ["chair_stand_5x_s"]


def test_missing_and_invalid():
    vals = {k: v for k, v in CONTROL.items() if not k.startswith("grip")}
    r = muscle_age(enc(age=42, sex=Sex.MALE, **vals))
    assert r.status == Status.MISSING_DATA and set(r.missing_fields) == {"grip_right_kg", "grip_left_kg"}
    one = muscle_age(enc(age=42, sex=Sex.MALE, **{**vals, "grip_left_kg": 48}))
    assert one.status == Status.CALCULATED and one.extra["grip_used_kg"] == 48 and one.warnings
    bad = muscle_age(enc(age=42, sex=Sex.MALE, **{**CONTROL, "grip_right_kg": 500}))
    assert bad.status == Status.INVALID_INPUT and bad.invalid_fields == ["grip_right_kg"]
    no_seg = muscle_age(enc(age=42, sex=Sex.MALE, **{k: v for k, v in CONTROL.items() if k != "visbody_seg_leg_right_kg"}))
    assert no_seg.status == Status.MISSING_DATA and no_seg.missing_fields == ["visbody_seg_leg_right_kg"]


def test_not_in_lmb_and_no_double_counting():
    """Мышечный возраст и возраст LQ1 не меняют LMB v0.3 (ветки not_included, веса не утверждены)."""
    cfg = load_config(config_path("model_v0.3.json"))
    base = run(encounter(EXAMPLE_2), cfg)
    e = encounter(EXAMPLE_2)
    from lmb_engine.core import Measurement
    e.measurements = {**e.measurements, **{k: Measurement(v, "kg" if k != "chair_stand_5x_s" else "s")
                                            for k, v in CONTROL.items() if k != "height_cm"},
                      "lqone_bioage_years": Measurement(45, "years")}
    out = run(e, cfg)
    assert out["research"]["bioage_years"] == base["research"]["bioage_years"]
    ma = next(i for i in out["indices"] if i["code"] == "muscle_age")
    lq = next(i for i in out["indices"] if i["code"] == "lqone_bioage")
    assert ma["status"] == "calculated" and lq["value"] == 45      # передан без изменений
    for d in ("muscle", "adaptive"):
        dom = next(x for x in out["domains"] if x["domain"] == d)
        assert dom["status"] == "not_included" and dom["contribution"] is None
    assert math.isclose(sum(out["research"]["contributions"].values()) + out["research"]["intercept"],
                        out["research"]["delta_years"])


def test_raw_measurements_summary_independent_of_status():
    """Исходные данные для экрана и отчёта есть и у женщин, и при невыполненных вставаниях."""
    from lmb_engine.muscle import raw_measurements
    r = raw_measurements(enc(age=42, sex=Sex.FEMALE, **CONTROL))
    assert r["grip_used_kg"] == 50 and r["asm_kg"] == pytest.approx(25.75) and r["height_m"] == pytest.approx(1.7)
    assert r["asmi_kg_m2"] == pytest.approx(8.910034602076125) and r["chair_stand_5x_s"] == 6
    u = raw_measurements(enc(age=42, sex=Sex.MALE, flags={"chair_stand_result": "unable"}, height_cm=170))
    assert u["chair_stand_unable"] is True and u["asm_kg"] is None and u["chair_stand_5x_s"] is None


def test_same_measurements_at_42_and_50():
    """Одинаковые измерения: 33,69 в 42 года и 32,74 в 50 лет — P не меняется, а P_ref растёт быстрее возраста
    (docs/muscle_age_review.md)."""
    a42 = muscle_age(enc(age=42, sex=Sex.MALE, **CONTROL))
    a50 = muscle_age(enc(age=50, sex=Sex.MALE, **CONTROL))
    assert a42.extra["p"] == pytest.approx(a50.extra["p"])
    assert a50.value == pytest.approx(32.73776710858231, abs=1e-9)
    assert a50.extra["p_ref"] - a42.extra["p_ref"] > 8                      # +8,95 при +8 годах
