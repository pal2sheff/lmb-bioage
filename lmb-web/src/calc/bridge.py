"""Мост браузерного калькулятора: JSON случая → lmb_engine.pipeline.run → JSON результата.

Выполняется в Pyodide. Формулы и правила не дублируются: вызывается тот же модуль,
что и на сервере, с той же конфигурацией модели v0.3.
"""
import datetime as dt
import json

from lmb_engine import __version__ as ENGINE_VERSION
from lmb_engine.core import Encounter, Measurement, Sex
from lmb_engine.model import config_path, load_config
from lmb_engine.pipeline import run

CONFIG = load_config(config_path("model_v0.3.json"))


def calculate(case_json: str) -> str:
    c = json.loads(case_json)
    ms = {}
    for code, m in (c.get("measurements") or {}).items():
        if m.get("value") is not None:
            ms[code] = Measurement(value=float(m["value"]), unit=m["unit"])
    flags = {k: v for k, v in (c.get("flags") or {}).items() if v not in (None, "")}
    frax = c.get("frax") or {}
    if frax.get("major") is not None and frax.get("hip") is not None:
        # ручной ввод официального результата FRAX (модель Казахстана)
        ms["frax_major_10y_pct"] = Measurement(float(frax["major"]), "%")
        ms["frax_hip_10y_pct"] = Measurement(float(frax["hip"]), "%")
        flags.update(frax_source="manual", frax_with_bmd=bool(frax.get("with_bmd")),
                     frax_inputs_bound=bool(frax.get("inputs_bound")))
    enc = Encounter(
        birth_date=dt.date.fromisoformat(c["birth_date"]) if c.get("birth_date") else None,
        encounter_date=dt.date.fromisoformat(c["encounter_date"]),
        sex=Sex(c["sex"]) if c.get("sex") else None,
        measurements=ms, flags=flags)
    out = run(enc, CONFIG)
    out["engine_version"] = ENGINE_VERSION
    return json.dumps(out, ensure_ascii=False, default=str)
