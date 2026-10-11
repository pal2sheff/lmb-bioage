"""Конвейер расчёта визита (ТЗ, раздел 3.3).

снимок → проверка → индексы → внешние результаты → Z-оценки → домены → интеграл.
Каждый шаг пишет статус; ошибка одной ветки не останавливает остальные.
"""
from __future__ import annotations

import hashlib
import json
from typing import Mapping, Optional

from . import __version__
from .cardio import model_for_age
from .core import Encounter, Status, age_full_years, is_finite_number
from .experiments import cardio_anchor
from .indices import run_all
from .model import (ALL_DOMAINS, UNIT_CONVERSIONS, IntegralResult, ZScore, _inverse, attribute, check_config,
                    config_sha256, domain_score, integral, research_integral, trajectory, zscore)


cardio_model_for_age = model_for_age  # совместимость с версией 0.1.0


def snapshot_hash(enc: Encounter, external: Mapping) -> str:
    payload = {
        "birth_date": enc.birth_date.isoformat() if enc.birth_date else None,
        "encounter_date": enc.encounter_date.isoformat(),
        "sex": enc.sex.value if enc.sex else None,
        "measurements": {k: [m.value, m.unit, m.qualifier.value,
                             m.sample_date.isoformat() if m.sample_date else None,
                             m.sample_id, m.review.value]
                         for k, m in sorted(enc.measurements.items())},
        "flags": {k: (v.value if hasattr(v, "value") else v) for k, v in sorted(enc.flags.items())},
        "external": dict(sorted(external.items())),
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _zscore_for(code: str, params: Mapping, indices: Mapping, external: Mapping, age, sex, clip: float) -> ZScore:
    """Z-оценка одного входа: статус исходного индекса передаётся без изменений.

    Единица результата индекса должна совпадать с единицей нормализации или иметь
    утверждённый пересчёт; иначе — invalid_input (ограничение Z ошибку не исправляет).
    """
    inp = params.get("input") or {}
    src, unit = inp.get("index"), inp.get("unit")
    if not src or not unit:
        return ZScore(code, Status.MODEL_NOT_CONFIGURED, reasons=["не задан входной индекс или единица"])
    if src in external:
        value, have_unit = external[src], unit
    else:
        r = indices.get(src)
        if r is None:
            return ZScore(code, Status.MISSING_DATA, reasons=[f"{src}: индекс не рассчитывался"])
        if r.status != Status.CALCULATED or r.value is None:
            return ZScore(code, r.status, reasons=[f"{src}: {x}" for x in (r.reasons or [r.status.value])])
        value, have_unit = r.value, r.unit
    if have_unit != unit:
        factor = UNIT_CONVERSIONS.get((have_unit, unit))
        if factor is None:
            return ZScore(code, Status.INVALID_INPUT, reasons=[f"{src}: единица {have_unit} ≠ {unit}"])
        value = value * factor
    if not is_finite_number(value):
        return ZScore(code, Status.INVALID_INPUT, reasons=[f"{src}: значение не является конечным числом"])
    if sex is None or age is None:
        return ZScore(code, Status.MISSING_DATA, reasons=["нет пола или возраста для нормализации"])
    return zscore(code, value, age, sex, params, clip)


def run(enc: Encounter, config: Mapping, external: Optional[Mapping[str, float]] = None) -> dict:
    """external — подтверждённые внешние результаты (например, FRAX) по кодам показателей."""
    external = dict(external or {})
    check = check_config(config)
    indices = run_all(enc)
    age = age_full_years(enc.birth_date, enc.encounter_date) if enc.birth_date else None

    clip = config["integral"].get("z_clip", 3.0)
    zs = {}
    for code, params in (config.get("normalization") or {}).items():
        zs[code] = _zscore_for(code, params, indices, external, age, enc.sex, clip)

    domains = {d: domain_score(d, (config.get("domains") or {}).get(d), zs) for d in ALL_DOMAINS}
    if check.valid:
        weights = config["integral"]["weights"]
        for d in config["integral"]["required_domains"]:
            attribute(domains[d], config["domains"][d], weights[d])
    integ: IntegralResult = integral(domains, config, age, check)
    research = research_integral(domains, config, age, check)   # отдельный блок, не клинический итог
    # проверочный режим Cardio (не меняет v0.3; показывается врачу по переключателю)
    research["cardio_anchor_experiment"] = (
        cardio_anchor(enc, indices, research, config["integral"]["weights"])
        if enc.birth_date is not None and enc.sex is not None else None)

    # траектории: ожидаемое значение по нормализации от возраста (±1 SD) и точка пациента
    trajectories = {}
    if age is not None and enc.sex is not None:
        ages = list(range(max(18, age - 15), min(95, age + 15) + 1))
        for code, z in zs.items():
            p = config["normalization"][code]
            if z.status != Status.CALCULATED:
                continue
            trajectories[code] = {
                "label": p.get("label", code), "unit": (p.get("input") or {}).get("unit"),
                "sign": p["sign"], "age": age, "value": _inverse(p["transform"], z.t),
                "z_raw": z.z_raw, "z_clipped": z.z_clipped, "curve": trajectory(p, enc.sex, ages),
            }

    warnings = []
    if not check.complete:
        warnings.append("model_config_incomplete")
    if config.get("synthetic_parameters"):
        warnings.append("synthetic_parameters")
    for z in zs.values():
        warnings += z.warnings

    return {
        "input_version": snapshot_hash(enc, external),
        "model_version": config.get("version"),
        "model_config_sha256": config_sha256(config),
        "engine_version": __version__,
        "status": integ.status,
        "age_years": age,                      # паспортный возраст на дату обследования, полных лет
        "indices": [r.to_dict() for r in indices.values()],
        "zscores": {c: {"status": z.status.value, "input": (config["normalization"][c].get("input") or {}).get("index"),
                        "t": z.t, "expected": z.expected,
                        "z_raw": z.z_raw, "z_clipped": z.z_clipped, "reasons": z.reasons}
                    for c, z in zs.items()},
        "trajectories": trajectories,
        "domains": [{"domain": d.domain, "score": d.score, "inputs": d.inputs,
                     "input_contributions": d.input_contributions, "coefficient": d.coefficient,
                     "contribution": d.contribution, "status": d.status.value, "reasons": d.reasons}
                    for d in domains.values()],
        "contributions": integ.contributions,
        "intercept": integ.intercept,
        "delta_years": integ.delta_years,
        "bioage_years": integ.bioage_years,
        "warnings": warnings,
        "missing_fields": sorted({f for r in indices.values() for f in r.missing_fields} | set(check.gaps)),
        "blocking_reasons": integ.blocking_reasons,
        "research": research,
    }
