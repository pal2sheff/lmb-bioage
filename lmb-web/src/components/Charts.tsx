// Инфографика профиля: вклад систем в LMB BioAge и профиль отклонений показателей (Z).
// Все числа приходят из расчётного модуля (lmb_engine); здесь только отображение.
import { useState } from "react";
import { fmt } from "../api";
import type { DomainRes, Status, Trajectory } from "../types";
import { unitRu } from "../units";

const V03 = ["cardio", "metabolic", "renal", "hepatic", "inflammation", "brain", "bone"];
/** Короткие названия систем на графиках — те же слова, что в названиях веток. */
export const SYSTEM_SHORT: Record<string, string> = {
  cardio: "Сердечно-сосудистый", metabolic: "Метаболический", renal: "Почечный", hepatic: "Печёночный",
  inflammation: "Воспалительный", brain: "Когнитивно-сосудистый", bone: "Риск переломов",
};
const INDEX_LABEL: Record<string, string> = {
  score2: "SCORE2", egfr: "eGFR", acr: "ACR", fib4: "FIB-4", homa_ir: "HOMA-IR", tyg: "TyG", aip: "AIP",
  whtr: "WHtR", nlr: "NLR", sii: "SII", caide: "CAIDE", frax_major: "FRAX",
};
const SYSTEM_OF: Record<string, string> = {
  score2: "cardio", homa_ir: "metabolic", tyg: "metabolic", aip: "metabolic", whtr: "metabolic", egfr: "renal",
  acr: "renal", fib4: "hepatic", nlr: "inflammation", sii: "inflammation", caide: "brain", frax_major: "bone",
};
const MISSING: Partial<Record<Status, string>> = {
  model_not_configured: "не активирован",
  missing_data: "нет данных",
  not_applicable: "вне области",
  invalid_input: "ошибка ввода",
  awaiting_review: "ждёт решения",
};
// знак ставится только если число не округляется до нуля (иначе «−0»); число знаков фиксировано,
// чтобы значения в столбце сравнивались по разрядам
export const signed = (v: number, d = 2) => {
  if (Math.abs(v) < 0.5 * 10 ** -d) return "0";
  return (v > 0 ? "+" : "−") + Math.abs(v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
};

export function Bar({ value, max }: { value: number; max: number }) {
  const w = max > 0 ? (Math.min(Math.abs(value), max) / max) * 50 : 0;
  return (
    <span className="dv-track" aria-hidden="true">
      <span className="dv-axis" />
      <span className={value >= 0 ? "dv-bar up" : "dv-bar down"} style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
    </span>
  );
}

/**
 * Вклад систем: коэффициент модели × оценка системы, в годах модели. По нажатию на систему —
 * разложение её вклада по показателям (правило объединения домена).
 */
export function BranchContributions({ domains, intercept, delta, interactive = true }: {
  domains: DomainRes[]; intercept: number; delta: number | null; interactive?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const dom = new Map(domains.map((d) => [d.domain, d]));
  const rows = V03.map((c) => dom.get(c)).filter((d): d is DomainRes => !!d);
  const done = rows.filter((d) => d.contribution !== null).sort((a, b) => b.contribution! - a.contribution!);
  const miss = rows.filter((d) => d.contribution === null);
  const max = Math.max(0.5, ...done.map((d) => Math.abs(d.contribution!)));
  return (
    <section className="dv-card" aria-labelledby="dv-branches">
      <header className="dv-head">
        <h3 id="dv-branches">Вклад систем в LMB BioAge, лет</h3>
        <p className="dv-legend">
          <span><span className="dv-key up" />повышает</span>
          <span><span className="dv-key down" />снижает</span>
        </p>
      </header>
      <ul className="dv-rows">
        {done.map((d) => {
          const parts = Object.entries(d.input_contributions ?? {}).sort((a, b) => b[1] - a[1]);
          const isOpen = open === d.domain;
          return (
            <li key={d.domain} className={isOpen ? "dv-item open" : "dv-item"}>
              {interactive ? (
                <button type="button" className="dv-row" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : d.domain)}
                  title={`${SYSTEM_SHORT[d.domain]}: ${signed(d.contribution!)} лет — показать показатели`}>
                  <span className="dv-label">{SYSTEM_SHORT[d.domain]}</span>
                  <Bar value={d.contribution!} max={max} />
                  <span className="dv-val num">{signed(d.contribution!)}</span>
                </button>
              ) : (
                <div className="dv-row">
                  <span className="dv-label">{SYSTEM_SHORT[d.domain]}</span>
                  <Bar value={d.contribution!} max={max} />
                  <span className="dv-val num">{signed(d.contribution!)}</span>
                </div>
              )}
              {isOpen && (
                <div className="dv-parts">
                  {parts.map(([code, v]) => (
                    <div key={code} className="dv-part">
                      <span className="dv-label">{INDEX_LABEL[code] ?? code}</span>
                      <Bar value={v} max={max} />
                      <span className="dv-val num">{signed(v)}</span>
                    </div>
                  ))}
                  <p className="dv-part-note num">
                    оценка системы {signed(d.score!, 2)} × коэффициент {fmt(d.coefficient, 1)}
                  </p>
                </div>
              )}
            </li>
          );
        })}
        {miss.map((d) => (
          <li key={d.domain} className="dv-item">
            <div className="dv-row is-missing">
              <span className="dv-label">{SYSTEM_SHORT[d.domain]}</span>
              <span className="dv-track dv-empty" aria-hidden="true" />
              <span className="dv-val">{MISSING[d.status] ?? d.status}</span>
            </div>
          </li>
        ))}
      </ul>
      <p className="dv-foot num">
        постоянная {signed(intercept)} ·{" "}
        {delta !== null ? (
          <>
            итого <b>{signed(delta)}</b> лет
          </>
        ) : (
          "итог не рассчитан"
        )}
      </p>
    </section>
  );
}

const ZMAX = 3;
const toneOf = (z: number) => (Math.abs(z) < 0.05 ? "mid" : z > 0 ? "up" : "down");
const digitsFor = (v: number) => (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);
const dirText = (z: number) => (Math.abs(z) < 0.05 ? "на уровне ожидаемого" : z > 0 ? "неблагоприятнее" : "благоприятнее");

/**
 * Профиль отклонений: все показатели на общей безразмерной оси Z (отклонение от ожидаемого для возраста
 * и пола). Значения разных единиц на одну ось не кладутся. По нажатию — значение, ожидаемое и возрастной график.
 */
export function DeviationChart({ data }: { data: Record<string, Trajectory> }) {
  const [open, setOpen] = useState<string | null>(null);
  const codes = Object.keys(SYSTEM_OF).filter((c) => c in data);
  if (codes.length === 0) return null;
  const pos = (z: number) => ((Math.max(-ZMAX, Math.min(ZMAX, z)) + ZMAX) / (2 * ZMAX)) * 100;
  return (
    <section className="dv-card dev-card" aria-labelledby="dv-dev">
      <header className="dv-head">
        <h3 id="dv-dev">Профиль отклонений, Z</h3>
        <p className="dv-legend">
          <span><span className="dv-key band" />±1</span>
          <span><span className="dv-key up" />неблагоприятнее</span>
          <span><span className="dv-key down" />благоприятнее</span>
        </p>
      </header>
      <div className="dev-row dev-axis" aria-hidden="true">
        <span className="dev-sys" />
        <span />
        <span className="dev-axis-head">
          <span style={{ left: "0%" }}>−3</span>
          <span style={{ left: "33.333%" }}>−1</span>
          <span style={{ left: "50%" }}>0</span>
          <span style={{ left: "66.667%" }}>+1</span>
          <span style={{ left: "100%" }}>+3</span>
        </span>
        <span />
      </div>
      <ul className="dev-grid">
        {codes.map((c, i) => {
          const t = data[c];
          const tone = toneOf(t.z_raw);
          const p = pos(t.z_raw);
          const newGroup = i === 0 || SYSTEM_OF[codes[i - 1]] !== SYSTEM_OF[c];
          const isOpen = open === c;
          return (
            <li key={c} className={`dev-item${newGroup ? " group-start" : ""}${isOpen ? " open" : ""}`}>
              <button type="button" className="dev-row" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : c)}
                aria-label={`${INDEX_LABEL[c]}: Z ${signed(t.z_raw, 1)}, ${dirText(t.z_raw)}`}>
                <span className="dev-sys">{newGroup ? SYSTEM_SHORT[SYSTEM_OF[c]] : ""}</span>
                <span className="dev-label">{INDEX_LABEL[c] ?? c}</span>
                <span className="dev-strip">
                  <span className="dev-band" />
                  <span className="dev-zero" />
                  <span className={`dev-stem ${tone}`} style={t.z_raw >= 0 ? { left: "50%", width: `${p - 50}%` } : { left: `${p}%`, width: `${50 - p}%` }} />
                  <span className={`dev-dot ${tone}`} style={{ left: `${p}%` }} />
                </span>
                <span className="dev-z num">{signed(t.z_raw, 1)}</span>
              </button>
              {isOpen && <DeviationDetail code={c} t={t} />}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function DeviationDetail({ code, t }: { code: string; t: Trajectory }) {
  const at = t.curve.find((p) => p.age === t.age);
  const d = digitsFor(t.value);
  const unit = unitRu(t.unit);
  return (
    <div className="dev-detail">
      <p className="num">
        пациент <b>{fmt(t.value, d)}</b> · ожидаемое {at ? fmt(at.expected, d) : "—"}
        {unit && <> {unit}</>} · Z {signed(t.z_raw, 2)}
        {Math.abs(t.z_raw) > ZMAX && <> (в модель входит {signed(Math.sign(t.z_raw) * ZMAX, 0)})</>}
        {code === "score2" && <> · отклонение от авторского ожидания, не категория риска</>}
      </p>
      <TrajectoryChart code={code} t={t} />
    </div>
  );
}

/** Проценты риска (SCORE2, SCORE2-OP, FRAX): шкала отображения ограничена 0–100 %; расчёт не меняется. */
const PERCENT_RISK = new Set(["score2", "score2_op", "frax_major"]);

/** Ожидаемое значение по возрасту (±1 SD) и точка пациента — в собственных единицах показателя. */
function TrajectoryChart({ code, t }: { code: string; t: Trajectory }) {
  const W = 420, H = 140, L = 46, R = 10, T = 10, B = 22;
  const risk = PERCENT_RISK.has(code);
  const lim = (v: number) => (risk ? Math.min(100, Math.max(0, v)) : v);
  const xs = t.curve.map((p) => p.age);
  const ys = t.curve.flatMap((p) => [p.lo, p.hi]).concat(t.value).map(lim);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo) * 0.08 || 1;
  const y0 = risk ? Math.max(0, lo - pad) : lo - pad;
  const y1 = risk ? Math.min(100, hi + pad) : hi + pad;
  const X = (a: number) => L + ((a - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (v: number) => T + (1 - (lim(v) - y0) / (y1 - y0)) * (H - T - B);
  const band = t.curve.map((p, i) => `${i ? "L" : "M"}${X(p.age).toFixed(1)},${Y(p.hi).toFixed(1)}`).join("") +
    t.curve.slice().reverse().map((p) => `L${X(p.age).toFixed(1)},${Y(p.lo).toFixed(1)}`).join("") + "Z";
  const line = t.curve.map((p, i) => `${i ? "L" : "M"}${X(p.age).toFixed(1)},${Y(p.expected).toFixed(1)}`).join("");
  const tone = toneOf(t.z_raw);
  const unit = unitRu(t.unit);
  const d = digitsFor(t.value);
  const at = t.curve.find((p) => p.age === t.age);
  return (
    <figure className="traj">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`${INDEX_LABEL[code]} по возрасту: линия — ожидаемое, полоса — ±1 стандартное отклонение, точка — пациент`}>
        <path className="traj-band" d={band} />
        <path className="traj-line" d={line} />
        {at && <line className="traj-gap" x1={X(t.age)} x2={X(t.age)} y1={Y(at.expected)} y2={Y(t.value)} />}
        <circle className={`traj-dot ${tone}`} cx={X(t.age)} cy={Y(t.value)} r={5.5} />
        <text className="traj-tick" x={L - 6} y={Y(hi) + 4} textAnchor="end">{fmt(hi, d)}</text>
        <text className="traj-tick" x={L - 6} y={Y(lo) + 4} textAnchor="end">{fmt(lo, d)}</text>
        <text className="traj-tick" x={X(x0)} y={H - 4} textAnchor="start">{x0}</text>
        <text className="traj-tick" x={X(x1)} y={H - 4} textAnchor="end">{x1} лет</text>
        <text className="traj-tick strong" x={X(t.age)} y={H - 4} textAnchor="middle">{t.age}</text>
      </svg>
      <figcaption className="muted small">
        линия — ожидаемое для возраста и пола, полоса — ±1 SD, точка — пациент{unit ? `; ${unit}` : ""}
      </figcaption>
    </figure>
  );
}
