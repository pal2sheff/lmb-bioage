"""Мышечная ветка: ASM по четырём сегментам Visbody, ASMI и мышечный возраст (модель владельца 0.1-synthetic).

Задание владельца 12.10.2026:
- ASM = левая рука + правая рука + левая нога + правая нога (туловище не входит; SMM не подставляется);
  источник — «Visbody, расчёт по четырём сегментам»;
- ASMI = ASM / рост², кг/м²;
- P = β0 + βG·G + βT·ln(T) + βM·M; P_ref(A) — то же для возрастных ориентиров;
  мышечный возраст = A + P − P_ref(A). Коэффициенты и ориентиры — config/algorithms/muscle_age_0.1_synthetic.json.

Мышечный возраст в LMB v0.3 не входит (ветка Muscle — not_included): веса не утверждены.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from pathlib import Path
from typing import Optional

from .core import Encounter, IndexResult, Sex
from .gate import Gate

MUSCLE_FILE = Path(__file__).resolve().parents[1] / "config" / "algorithms" / "muscle_age_0.1_synthetic.json"
SEGMENTS = ("visbody_seg_arm_left_kg", "visbody_seg_arm_right_kg", "visbody_seg_leg_left_kg", "visbody_seg_leg_right_kg")
ASM_SOURCE = "Visbody, расчёт по четырём сегментам"


def load_muscle_params() -> dict:
    raw = MUSCLE_FILE.read_bytes()
    p = json.loads(raw.decode("utf-8"))
    p["_sha256"] = hashlib.sha256(raw).hexdigest()
    r = p["references"]
    if not (len(r["grip_and_chair_ages"]) == len(r["grip_kg"]) == len(r["chair_stand_s"])
            and len(r["asmi_ages"]) == len(r["asmi_kg_m2"])):
        raise ValueError("muscle_age: длины таблиц ориентиров не совпадают")
    return p


def interp(xs: list, ys: list, x: float) -> float:
    """Линейная интерполяция; за крайними узлами — крайнее значение."""
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    i = bisect.bisect_right(xs, x) - 1
    return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])


def references(p: dict, age: float) -> dict:
    r = p["references"]
    return {"grip_kg": interp(r["grip_and_chair_ages"], r["grip_kg"], age),
            "chair_stand_s": interp(r["grip_and_chair_ages"], r["chair_stand_s"], age),
            "asmi_kg_m2": interp(r["asmi_ages"], r["asmi_kg_m2"], age)}


def score(p: dict, grip: float, chair_s: float, asmi_v: float) -> float:
    c = p["coefficients"]
    return c["intercept"] + c["grip_kg"] * grip + c["ln_chair_stand_s"] * math.log(chair_s) + c["asmi_kg_m2"] * asmi_v


def muscle_age_from(p: dict, age: float, grip: float, chair_s: float, asmi_v: float) -> dict:
    ref = references(p, age)
    pp = score(p, grip, chair_s, asmi_v)
    pr = score(p, ref["grip_kg"], ref["chair_stand_s"], ref["asmi_kg_m2"])
    return {"p": pp, "p_ref": pr, "muscle_age": age + pp - pr, "delta_years": pp - pr, "ref": ref}


def _asm(g: Gate) -> Optional[float]:
    vals = [g.value(k) for k in SEGMENTS]
    if any(v is None for v in vals):
        return None
    return math.fsum(vals)


def asmi(enc: Encounter) -> IndexResult:
    """ASMI = ASM / рост²; ASM — сумма четырёх сегментов конечностей Visbody (туловище не входит, SMM не используется)."""
    g = Gate(enc, "asmi", 2)
    asm = _asm(g)
    h = g.value("height_cm")
    if g.blocked():
        return g.result()
    return g.result(asm / (h / 100) ** 2, "kg/m2", {"asm_kg": asm, "asm_source": ASM_SOURCE, "height_m": h / 100})


def muscle_age(enc: Encounter, params: Optional[dict] = None) -> IndexResult:
    p = params or load_muscle_params()
    g = Gate(enc, "muscle_age", 1)
    age = g.age()
    sex = g.sex()
    grips = {k: g.optional(k) for k in ("grip_right_kg", "grip_left_kg")}
    if all(v is None for v in grips.values()) and not g.invalid:
        g.missing.extend(grips)
    unable = (enc.flags.get("chair_stand_result") or "") == "unable"
    chair = None
    if unable:
        m = enc.measurements.get("chair_stand_5x_s")
        if m is not None and m.value is not None:
            g.invalid.append("Отмечено, что пять вставаний выполнить не удалось, но время указано — уточните")
            g.invalid_fields.append("chair_stand_5x_s")
        else:
            g.not_applicable.append("Пять вставаний без помощи рук выполнить не удалось — мышечный возраст не "
                                    "рассчитывается, условное время не подставляется")
    else:
        chair = g.value("chair_stand_5x_s")
    asm = _asm(g)
    h = g.value("height_cm")
    ap = p["applicability"]
    if sex is not None and sex.value not in ap["sex"]:
        g.not_applicable.append("Коэффициенты мышечного возраста 0.1-synthetic получены для мужчин — для женщин не "
                                "применяются; измерения сохранены")
    if age is not None and not ap["age_min"] <= age < ap["age_max_exclusive"]:
        g.not_applicable.append(f"Возраст {age} вне области модели мышечного возраста "
                                f"({ap['age_min']}–{ap['age_max_exclusive'] - 1} лет)")
    known = [v for v in grips.values() if v is not None]
    measured = {"grip_right_kg": grips["grip_right_kg"], "grip_left_kg": grips["grip_left_kg"],
                "grip_used_kg": max(known) if known else None, "chair_stand_s": chair,
                "chair_stand_unable": unable, "asm_kg": asm, "asm_source": ASM_SOURCE,
                "asmi": asm / (h / 100) ** 2 if asm is not None and h else None,
                "model_version": p["version"], "scientific_status": p["scientific_status"], "in_model": False,
                "params_sha256": p["_sha256"]}
    if g.blocked() or g.not_applicable:
        return g.result(None, "years", measured)
    if len(known) == 1:
        g.warnings.append("Сила хвата измерена только одной рукой")
    out = muscle_age_from(p, age, measured["grip_used_kg"], chair, measured["asmi"])
    return g.result(out["muscle_age"], "years", {**measured, "p": out["p"], "p_ref": out["p_ref"],
                                                  "delta_years": out["delta_years"], "reference": out["ref"],
                                                  "age_basis": p["age_basis"]})


def raw_measurements(enc: Encounter) -> dict:
    """Исходные данные мышечной ветки для экрана и отчёта (независимо от статуса мышечного возраста).

    Значения — в канонических единицах; ошибочные (вне технического диапазона) не показываются как данные.
    """
    g = Gate(enc, "muscle_raw", 1)

    def val(k):
        try:
            return g.optional(k)
        except Exception:      # noqa: BLE001 — сводка не должна ломать расчёт
            return None
    out = {k: val(k) for k in ("grip_right_kg", "grip_left_kg", "chair_stand_5x_s", "height_cm", *SEGMENTS)}
    grips = [v for v in (out["grip_right_kg"], out["grip_left_kg"]) if v is not None]
    out["grip_used_kg"] = max(grips) if grips else None
    out["chair_stand_unable"] = (enc.flags.get("chair_stand_result") or "") == "unable"
    seg = [out[k] for k in SEGMENTS]
    out["asm_kg"] = math.fsum(seg) if all(v is not None for v in seg) else None
    out["height_m"] = out["height_cm"] / 100 if out["height_cm"] is not None else None
    out["asmi_kg_m2"] = out["asm_kg"] / out["height_m"] ** 2 if out["asm_kg"] is not None and out["height_m"] else None
    out["asm_source"] = ASM_SOURCE
    return out
