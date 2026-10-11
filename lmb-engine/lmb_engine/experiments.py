"""Проверочные режимы поверх неизменённой v0.3 (не заменяют основную конфигурацию).

cardio_anchor_experiment_v1 (задание владельца 11.10.2026): в Z Cardio вместо ожидания v0.3
по возрасту и полу используется SCORE2 High условного контрольного профиля того же пола и того
же точного возраста, рассчитанный той же функцией SCORE2:

    Z = (ln(1 + SCORE2_пациента_%) − ln(1 + SCORE2_контроль_%)) / 0.365158,  ограничение ±3,
    вклад = 0.7 × Z;  остальные вклады, свободный член и веса — как в v0.3.

Это проверка влияния замены ожидания, а не популяционная норма и не перевод риска в годы.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Optional

from . import cardio
from .core import Encounter, Sex, Status, age_exact_years

EXP_DIR = Path(__file__).resolve().parent.parent / "config" / "experiments"


def load_experiment(name: str = "cardio_anchor_experiment_v1") -> dict:
    raw = (EXP_DIR / f"{name}.json").read_bytes()
    p = json.loads(raw.decode("utf-8"))
    p["_sha256"] = hashlib.sha256(raw).hexdigest()
    if p["transform"] != "log1p" or not p["residual_sd"] > 0 or p["z_clip"] <= 0:
        raise ValueError(f"{name}: недопустимые параметры")
    return p


def control_score2_pct(sex: Sex, age_exact: float, profile: Mapping, params: Optional[dict] = None) -> float:
    """SCORE2 High контрольного профиля той же функцией, что и у пациента (в процентах)."""
    p = params or cardio.load_params("score2")
    return cardio.compute(p, age_exact, sex, bool(profile["smoker"]), float(profile["sbp_mmhg"]),
                          float(profile["tc_mmol_l"]), float(profile["hdl_mmol_l"]))["risk"] * 100


def anchor_z(patient_pct: float, control_pct: float, residual_sd: float, clip: float) -> tuple:
    """Риски подаются в процентах (3.223, а не 0.03223)."""
    z = (math.log1p(patient_pct) - math.log1p(control_pct)) / residual_sd
    return z, max(-clip, min(clip, z))


def cardio_anchor(enc: Encounter, indices: Mapping, research: Mapping, weights: Mapping,
                  exp: Optional[dict] = None) -> dict:
    exp = exp or load_experiment()
    out = {"id": exp["id"], "status": "blocked", "config_sha256": exp["_sha256"], "base_model": exp["base_model"],
           "label": exp["label_ru"], "disclaimer": exp["disclaimer_ru"], "control_profile": exp["control_profile"],
           "residual_sd": exp["residual_sd"], "residual_sd_note": exp["residual_sd_note"], "weight": exp["weight"],
           "age_exact_years": None, "score2_pct": None, "control_score2_pct": None, "z_raw": None, "z_clipped": None,
           "contribution": None, "contribution_v03": None, "delta_years": None, "bioage_years": None,
           "change_years": None, "reasons": []}
    if weights.get("cardio") != exp["weight"]:
        out["reasons"].append("Вес Cardio в конфигурации отличается от веса проверочного режима")
        return out
    s2 = indices.get(exp["applies_to_index"])
    if s2 is None or s2.status != Status.CALCULATED or s2.value is None:
        out["status"] = s2.status.value if s2 else "missing_data"
        out["reasons"].append("SCORE2 не рассчитан: " + "; ".join((s2.reasons if s2 else []) or [out["status"]]))
        return out
    age = age_exact_years(enc.birth_date, enc.encounter_date)
    ctrl = control_score2_pct(enc.sex, age, exp["control_profile"])
    z_raw, z = anchor_z(s2.value, ctrl, exp["residual_sd"], exp["z_clip"])
    contrib = exp["weight"] * z
    out.update(age_exact_years=age, score2_pct=s2.value, control_score2_pct=ctrl, z_raw=z_raw, z_clipped=z,
               contribution=contrib)
    if research.get("status") != "calculated":
        out["status"] = research.get("status", "blocked")
        out["reasons"] += list(research.get("reasons") or [])
        return out
    c = research["contributions"]
    others = [v for d, v in c.items() if d != "cardio"]
    delta = math.fsum([research["intercept"], contrib, *others])
    out.update(status="calculated", contribution_v03=c["cardio"], delta_years=delta,
               bioage_years=research["bioage_years"] - research["delta_years"] + delta,
               change_years=delta - research["delta_years"])
    return out
