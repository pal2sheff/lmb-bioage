"""«Возраст по LQ1»: одно поле, значение передаётся без пересчёта; в LMB v0.3 не входит (решение 12.10.2026, 22:05)."""
from lmb_engine.core import Measurement, Status
from lmb_engine.indices import lqone_bioage
from lmb_engine.model import config_path, load_config
from lmb_engine.pipeline import run

from .examples import EXAMPLE_1, encounter


def enc_with(**ms):
    e = encounter(EXAMPLE_1)
    e.measurements = {**e.measurements, **{k: Measurement(v, u) for k, (v, u) in ms.items()}}
    return e


def test_value_passed_unchanged_without_extra_requirements():
    assert lqone_bioage(encounter(EXAMPLE_1)).status == Status.MISSING_DATA
    r = lqone_bioage(enc_with(lqone_bioage_years=(52.4, "years")))
    assert r.status == Status.CALCULATED and r.value == 52.4 and r.unit == "years"
    assert not r.warnings and "delta_years" not in r.extra and r.extra["in_model"] is False
    bad = lqone_bioage(enc_with(lqone_bioage_years=(500, "years")))
    assert bad.status == Status.INVALID_INPUT and bad.invalid_fields == ["lqone_bioage_years"]


def test_not_in_lmb():
    cfg = load_config(config_path("model_v0.3.json"))
    base = run(encounter(EXAMPLE_1), cfg)
    withlq = run(enc_with(lqone_bioage_years=(30, "years")), cfg)
    assert base["research"]["bioage_years"] == withlq["research"]["bioage_years"]
    adaptive = next(d for d in withlq["domains"] if d["domain"] == "adaptive")
    assert adaptive["status"] == "not_included" and adaptive["contribution"] is None
