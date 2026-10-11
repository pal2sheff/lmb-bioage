"""Проверки входов по аудиту владельца 11.10.2026: согласованность ОАК, FRAX, источник ACR,
независимость PhenoAge от LMB."""
import pytest

from lmb_engine.model import load_config
from lmb_engine.pipeline import run
from tests.examples import EXAMPLE_1, EXAMPLE_2, encounter

CFG = load_config("config/model_v0.3.json")


def idx(out):
    return {i["code"]: i for i in out["indices"]}


def test_examples_keep_phenoage():
    assert idx(run(encounter(EXAMPLE_1), CFG))["phenoage"]["value"] == pytest.approx(50.1073, abs=1e-4)
    assert idx(run(encounter(EXAMPLE_2), CFG))["phenoage"]["value"] == pytest.approx(38.0830, abs=1e-4)


def test_inconsistent_cbc_blocks_dependents_and_lmb():
    """Лимфоциты 8 при лейкоцитах 6,3: блокируются NLR, SII, PhenoAge и итог LMB (раньше LMB менялся до 54,6)."""
    out = run(encounter(EXAMPLE_1, lymphocytes_abs=8), CFG)
    i = idx(out)
    for code in ("nlr", "sii", "phenoage"):
        assert i[code]["status"] == "invalid_input" and i[code]["value"] is None, code
        assert {"lymphocytes_abs", "wbc"} <= set(i[code]["invalid_fields"])
        assert "противоречив" in i[code]["reasons"][0]
    assert out["research"]["status"] == "blocked" and out["research"]["bioage_years"] is None
    assert out["input_checks"][0]["code"] == "cbc_sum"
    assert i["fib4"]["status"] == "calculated"                 # независимые индексы считаются


def test_cbc_rounding_tolerance():
    """Сумма 3,5 + 2,85 = 6,35 при лейкоцитах 6,3 — в пределах округления (0,05 × 3)."""
    out = run(encounter(EXAMPLE_1, lymphocytes_abs=2.85), CFG)
    assert idx(out)["nlr"]["status"] == "calculated" and out["input_checks"] == []
    out = run(encounter(EXAMPLE_1, lymphocytes_abs=3.0), CFG)       # 6,5 > 6,45
    assert idx(out)["nlr"]["status"] == "invalid_input"


def test_frax_hip_above_major_is_error():
    ex = {**EXAMPLE_1, "frax": (6.5, 10.0)}
    out = run(encounter(ex), CFG)
    f = idx(out)["frax_kz"]
    assert f["status"] == "invalid_input" and "перелома бедра" in f["reasons"][0]
    assert out["research"]["status"] == "blocked"
    ok = idx(run(encounter(EXAMPLE_1), CFG))["frax_kz"]
    assert ok["value"] == 6.5 and ok["extra"]["hip_10y_pct"] == 1.0 and ok["extra"]["major_10y_pct"] == 6.5
    assert ok["extra"]["transferred_from_official_frax"] is True


def test_messages_use_russian_names():
    out = run(encounter(EXAMPLE_1, lymphocytes_abs=500), CFG)
    msg = " ".join(idx(out)["nlr"]["reasons"])
    assert "Лимфоциты" in msg and "lymphocytes_abs" not in msg


def test_phenoage_independent_of_lmb_block():
    """PhenoAge считается, даже если LMB не рассчитан (например, вне 40–64 лет или без FRAX)."""
    e = encounter(EXAMPLE_1)
    e.measurements.pop("frax_major_10y_pct")
    e.measurements.pop("frax_hip_10y_pct")
    out = run(e, CFG)
    assert out["research"]["status"] == "blocked"
    assert idx(out)["phenoage"]["status"] == "calculated"
