// Синтетический пациент для знакомства с калькулятором. Данные выдуманы.
import type { FormState } from "./CalcApp";

const v = (text: string, unit: string) => ({ text, unit });

export const EXAMPLE: FormState = {
  birth_date: "1971-03-01",
  encounter_date: "2026-10-10",
  sex: "female",
  values: {
    height_cm: v("165", "cm"),
    weight_kg: v("68", "kg"),
    waist_cm: v("82", "cm"),
    sbp_mmhg: v("128", "mmHg"),
    glucose_fasting: v("5,2", "mmol/L"),
    insulin_fasting: v("8", "uU/mL"),
    tg: v("1,3", "mmol/L"),
    tc: v("5,4", "mmol/L"),
    hdl: v("1,5", "mmol/L"),
    creatinine_serum: v("70", "umol/L"),
    u_albumin: v("20", "mg/L"),
    u_creatinine: v("10", "mmol/L"),
    ast: v("22", "U/L"),
    alt: v("20", "U/L"),
    platelets: v("240", "10^9/L"),
    neutrophils_abs: v("3,5", "10^9/L"),
    lymphocytes_abs: v("2,0", "10^9/L"),
  },
  flags: {
    fasting_status: "yes", creatinine_idms: "yes", acute_infection: "no", acute_kidney_change: "no",
    acute_liver_condition: "no", diabetes: "no", insulin_therapy: "no", ascvd: "no", ckd_known: "no", fh: "no",
    very_high_single_risk_factor: "no", smoking_current: "no", alcohol_3plus: "no", physical_activity_caide: "active",
    education_years: "14", prior_fragility_fracture: "no", parent_hip_fracture: "no", glucocorticoids: "no",
    rheumatoid_arthritis: "no", secondary_osteoporosis: "no",
  },
  frax: { major: "6,5", hip: "1,0", with_bmd: "no" },
};
