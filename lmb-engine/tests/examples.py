"""Синтетические примеры калькулятора (lmb-web/src/calc/example.ts) для проверок движка."""
import datetime as dt

from lmb_engine.core import Encounter, Measurement, Sex

FLAGS = dict(fasting_status="yes", creatinine_idms="yes", acute_infection="no", acute_kidney_change="no",
             acute_liver_condition="no", diabetes="no", insulin_therapy="no", ascvd="no", ckd_known="no", fh="no",
             very_high_single_risk_factor="no", smoking_current="no", alcohol_3plus="no",
             physical_activity_caide="active", education_years="14", frax_source="manual", frax_with_bmd=False)

EXAMPLE_1 = dict(
    birth=dt.date(1971, 3, 1), sex=Sex.FEMALE, frax=(6.5, 1.0), flags={},
    values=dict(height_cm=(165, "cm"), weight_kg=(68, "kg"), waist_cm=(82, "cm"), sbp_mmhg=(128, "mmHg"),
                glucose_fasting=(5.2, "mmol/L"), insulin_fasting=(8, "uU/mL"), tg=(1.3, "mmol/L"), tc=(5.4, "mmol/L"),
                hdl=(1.5, "mmol/L"), creatinine_serum=(70, "umol/L"), u_albumin=(20, "mg/L"), u_creatinine=(10, "mmol/L"),
                ast=(22, "U/L"), alt=(20, "U/L"), platelets=(240, "10^9/L"), neutrophils_abs=(3.5, "10^9/L"),
                lymphocytes_abs=(2.0, "10^9/L"), wbc=(6.3, "10^9/L"), mcv=(91, "fL"), rdw=(13.4, "%"),
                albumin_serum=(44, "g/L"), crp=(1.8, "mg/L"), alp=(78, "U/L")))

EXAMPLE_2 = dict(
    birth=dt.date(1976, 5, 14), sex=Sex.MALE, frax=(3.1, 0.3), flags={"education_years": "16"},
    values=dict(height_cm=(178, "cm"), weight_kg=(72, "kg"), waist_cm=(80, "cm"), sbp_mmhg=(114, "mmHg"),
                glucose_fasting=(4.7, "mmol/L"), insulin_fasting=(4.5, "uU/mL"), tg=(0.8, "mmol/L"), tc=(4.6, "mmol/L"),
                hdl=(1.6, "mmol/L"), creatinine_serum=(78, "umol/L"), u_albumin=(5, "mg/L"), u_creatinine=(12, "mmol/L"),
                ast=(19, "U/L"), alt=(17, "U/L"), platelets=(260, "10^9/L"), neutrophils_abs=(2.6, "10^9/L"),
                lymphocytes_abs=(2.3, "10^9/L"), wbc=(5.6, "10^9/L"), mcv=(89, "fL"), rdw=(12.6, "%"),
                albumin_serum=(46, "g/L"), crp=(0.6, "mg/L"), alp=(58, "U/L")))

ENC_DATE = dt.date(2026, 10, 10)


def encounter(ex: dict, birth=None, sex=None, **override) -> Encounter:
    vals = {**ex["values"], **{k: (v, ex["values"][k][1]) for k, v in override.items()}}
    ms = {k: Measurement(v, u) for k, (v, u) in vals.items()}
    ms["frax_major_10y_pct"] = Measurement(ex["frax"][0], "%")
    ms["frax_hip_10y_pct"] = Measurement(ex["frax"][1], "%")
    return Encounter(birth_date=birth or ex["birth"], encounter_date=ENC_DATE, sex=sex or ex["sex"],
                     measurements=ms, flags={**FLAGS, **ex["flags"]})
