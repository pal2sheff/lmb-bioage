export type Status =
  | "calculated"
  | "missing_data"
  | "invalid_input"
  | "not_applicable"
  | "model_not_configured"
  | "integration_not_configured"
  | "external_error"
  | "awaiting_review"
  | "not_included";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  is_model_owner: boolean;
  totp_enabled: boolean;
  csrf_token: string;
}

export interface Patient {
  id: string;
  last_name: string;
  first_name: string;
  middle_name: string | null;
  birth_date: string;
  sex_at_birth: "female" | "male";
  pseudonym_code: string;
  version: number;
  iin_masked?: string | null;
  phone?: string | null;
  email?: string | null;
}

export interface EncounterT {
  id: string;
  patient_id: string;
  encounter_date: string;
  status: string;
}

export interface Definition {
  code: string;
  name_ru: string;
  unit_canonical: string | null;
  allowed_units: string[];
  plausible_min: number | null;
  plausible_max: number | null;
}

export interface QItem {
  code: string;
  name: string;
  kind: "choice" | "text" | "frax_list" | "integer";
  options: string[] | null;
  range?: [number, number] | null;
  doctor_only: boolean;
}

export interface Catalog {
  observation_groups: { title: string; items: Definition[] }[];
  questionnaire_groups: { title: string; items: QItem[] }[];
  frax_risk_factors: string[];
  index_labels: Record<string, { short: string; name: string }>;
  branches: { code: string; title: string; name: string; indices: string[] }[];
}

export interface Obs {
  chain_id: string;
  id: string;
  code: string;
  revision: number;
  value: number | null;
  unit: string | null;
  qualifier: "eq" | "lt" | "gt";
  sample_date: string | null;
  sample_id: string | null;
  source: string;
  review_status: "pending" | "confirmed" | "rejected";
  is_current: boolean;
  change_reason: string | null;
  created_at: string | null;
}

export interface IndexRes {
  code: string;
  version: number;
  status: Status;
  value: number | null;
  unit: string | null;
  extra: Record<string, unknown>;
  warnings: string[];
  missing_fields: string[];
  reasons: string[];
}

export interface ZRes {
  status: Status;
  input: string | null;
  t: number | null;
  expected: number | null;
  z_raw: number | null;
  z_clipped: number | null;
  reasons: string[];
}

/** Ожидаемое значение показателя по нормализации v0.3 в зависимости от возраста (±1 SD) и точка пациента. */
export interface Trajectory {
  label: string;
  unit: string | null;
  sign: 1 | -1;
  age: number;
  value: number;
  z_raw: number;
  z_clipped: number;
  curve: { age: number; expected: number; lo: number; hi: number }[];
}

/** Исследовательский расчёт неизменённой v0.3 (режим local_synthetic); не клинический итог. */
export interface ResearchRes {
  status: "calculated" | "blocked" | "not_applicable" | "model_not_configured";
  mode: string | null;
  model_version: string;
  model_config_sha256: string;
  scientific_status: string;
  research_population: { description: string; age_min: number; age_max: number } | null;
  intercept: number;
  contributions: Record<string, number> | null;
  domain_scores: Record<string, number> | null;
  delta_years: number | null;
  bioage_years: number | null;
  limitations: string[];
  reasons: string[];
}

export interface DomainRes {
  domain: string;
  score: number | null;
  inputs?: Record<string, number>;
  /** разложение вклада ветки по показателям (коэффициент ветки × доля Z по правилу объединения) */
  input_contributions?: Record<string, number>;
  coefficient: number | null;
  contribution: number | null;
  status: Status;
  reasons: string[];
}

export interface Run {
  calculation_id: string;
  snapshot_id: string;
  model_version: string;
  model_revision?: number;
  model_config_sha256: string;
  engine_version: string;
  status: "calculated" | "blocked";
  bioage_years: number | null;
  delta_years: number | null;
  created_at: string;
  result: {
    indices: IndexRes[];
    domains: DomainRes[];
    zscores?: Record<string, ZRes>;
    trajectories?: Record<string, Trajectory>;
    research?: ResearchRes;
    age_years?: number | null;
    contributions: Record<string, number> | null;
    intercept: number;
    warnings: string[];
    blocking_reasons: string[];
    input_version: string;
  };
}

export interface FraxJob {
  id: string;
  provider: string;
  status: string;
  frax_major_10y_pct: number | null;
  frax_hip_10y_pct: number | null;
  with_bmd: boolean | null;
  source: "manual" | "automatic";
  error_code: string | null;
  error_detail: string | null;
  attempts: number;
  is_active_choice: boolean;
  conflict_note: string | null;
  inputs_current: boolean | null;
  manual_calculated_on: string | null;
  manual_source_note: string | null;
  inputs_bound: boolean;
  attachment_id: string | null;
  created_at: string | null;
  quota_warning?: string | null;
}

export interface Attachment {
  id: string;
  encounter_id: string;
  kind: "frax_result" | "lab" | "visbody" | "lqone" | "other";
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string | null;
}

export interface FraxInputs {
  status: string;
  problems: string[];
  request: Record<string, unknown> | null;
  input_hash: string | null;
  provider: string;
}
