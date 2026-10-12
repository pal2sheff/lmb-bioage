"""Мост браузерного калькулятора: JSON случая → lmb_engine.pipeline.run → JSON результата.

Выполняется в Pyodide. Формулы и правила не дублируются: вызывается тот же модуль,
что и на сервере, с той же конфигурацией модели v0.3.
"""
import base64
import datetime as dt
import json

from lmb_engine import __version__ as ENGINE_VERSION
from lmb_engine import labimport
from lmb_engine.core import Encounter, Measurement, Qualifier, Sex
from lmb_engine.model import config_path, load_config
from lmb_engine.pipeline import run

CONFIG = load_config(config_path("model_v0.3.json"))


def calculate(case_json: str) -> str:
    c = json.loads(case_json)
    ms = {}
    for code, m in (c.get("measurements") or {}).items():
        if m.get("value") is not None:
            # «<x» и «>x» передаются как есть: модуль не превращает их в точное число
            ms[code] = Measurement(value=float(m["value"]), unit=m["unit"],
                                   qualifier=Qualifier(m.get("qualifier") or "eq"))
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


def lab_import(payload_json: str) -> str:
    """Импорт анализов: CSV/XLSX (байты в base64) или строки текстового слоя PDF → предложение переноса."""
    p = json.loads(payload_json)
    enc = dt.date.fromisoformat(p["encounter_date"]) if p.get("encounter_date") else None
    try:
        if p.get("lines") is not None:
            out = labimport.candidates(labimport.rows_from_lines(p["lines"]), enc)
        else:
            out = labimport.import_file(p["name"], base64.b64decode(p["b64"]), enc)
    except (ValueError, KeyError) as e:
        out = {"error": str(e)}
    return json.dumps(out, ensure_ascii=False, default=str)
