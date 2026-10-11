"""Демонстрация: синтетический пациент, текущая конфигурация v0.3.

Запуск из корня проекта: python3 examples/demo.py
Пациент выдуман. Итог LMB BioAge заблокирован: нет целевой популяции, SCORE2 не сверен полностью, в демо нет анкеты и FRAX.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lmb_engine.core import Encounter, Measurement, Sex          # noqa: E402
from lmb_engine.model import load_config                          # noqa: E402
from lmb_engine.pipeline import run                               # noqa: E402

m = Measurement
patient = Encounter(
    birth_date=dt.date(1974, 3, 15), encounter_date=dt.date(2026, 10, 10), sex=Sex.MALE,
    measurements={
        "height_cm": m(178, "cm"), "weight_kg": m(84, "kg"), "waist_cm": m(94, "cm"),
        "glucose_fasting": m(5.6, "mmol/L", sample_id="L1"), "insulin_fasting": m(11.2, "uU/mL", sample_id="L1"),
        "tg": m(1.8, "mmol/L", sample_id="L1"), "tc": m(5.9, "mmol/L", sample_id="L1"),
        "hdl": m(1.1, "mmol/L", sample_id="L1"), "creatinine_serum": m(92, "umol/L", sample_id="L1"),
        "ast": m(28, "U/L", sample_id="L1"), "alt": m(35, "U/L", sample_id="L1"),
        "u_albumin": m(12, "mg/L", sample_id="U1"), "u_creatinine": m(9.5, "mmol/L", sample_id="U1"),
        "platelets": m(230, "10^9/L", sample_id="C1"), "neutrophils_abs": m(3.8, "10^9/L", sample_id="C1"),
        "lymphocytes_abs": m(2.1, "10^9/L", sample_id="C1"),
    },
    flags={"fasting_status": "yes", "insulin_therapy": "no", "diabetes": "no", "creatinine_idms": "yes",
           "acute_kidney_change": "no", "acute_liver_condition": "no", "acute_infection": "no"},
)

out = run(patient, load_config(str(Path(__file__).resolve().parents[1] / "config" / "model_v0.3.json")))
print(f"Статус итога: {out['status']}; LMB BioAge: {out['bioage_years']}")
print("Индексы:")
for i in out["indices"]:
    v = "—" if i["value"] is None else f"{i['value']:.3f}"
    print(f"  {i['code']:<22} {v:>10}  {i['unit'] or '':<15} {i['status']}")
print("Причины блокировки итога:")
for r in out["blocking_reasons"]:
    print("  -", r[:150])
Path("demo_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
