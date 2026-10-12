"""LQ One: ручной ввод итогового показателя заключения — только отображение, в LMB v0.3 не входит."""
from lmb_engine.core import Measurement, Status
from lmb_engine.indices import asmi, lqone_bioage
from lmb_engine.model import config_path, load_config
from lmb_engine.pipeline import run

from .examples import EXAMPLE_1, encounter


def enc_with(**ms):
    e = encounter(EXAMPLE_1)
    e.measurements = {**e.measurements, **{k: Measurement(v, u) for k, (v, u) in ms.items()}}
    return e


def test_missing_and_display():
    assert lqone_bioage(encounter(EXAMPLE_1)).status == Status.MISSING_DATA
    e = enc_with(lqone_bioage_years=(52, "years"), lqone_reliability_pct=(87, "%"))
    e.flags = {**e.flags, "lqone_device_model": "LQ One", "lqone_software_version": "1.0",
               "lqone_measured_on": "2026-10-10"}
    r = lqone_bioage(e)
    assert r.status == Status.CALCULATED and r.value == 52 and r.unit == "years"
    assert r.extra["reliability_pct"] == 87 and r.extra["in_model"] is False and not r.warnings


def test_warnings_and_invalid_reliability():
    r = lqone_bioage(enc_with(lqone_bioage_years=(52, "years")))
    assert r.status == Status.CALCULATED
    assert any("модель" in w for w in r.warnings) and any("достоверность" in w for w in r.warnings)
    bad = lqone_bioage(enc_with(lqone_bioage_years=(52, "years"), lqone_reliability_pct=(140, "%")))
    assert bad.status == Status.INVALID_INPUT and bad.invalid_fields == ["lqone_reliability_pct"]


def test_not_in_lmb():
    cfg = load_config(config_path("model_v0.3.json"))
    base = run(encounter(EXAMPLE_1), cfg)
    withlq = run(enc_with(lqone_bioage_years=(30, "years")), cfg)
    assert base["research"]["bioage_years"] == withlq["research"]["bioage_years"]
    adaptive = next(d for d in withlq["domains"] if d["domain"] == "adaptive")
    assert adaptive["status"] == "not_included" and adaptive["contribution"] is None


def test_asmi_source_warning():
    r = asmi(enc_with(visbody_asm=(18, "kg")))
    assert r.status == Status.CALCULATED and r.extra["asm_source"] == "manual"
    assert any("спецификацией аппарата не подтверждено" in w for w in r.warnings)
