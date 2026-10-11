// Визуализация профиля: вклад веток, вклад показателей и траектории показателей с возрастом.
// Все числа приходят из расчётного модуля (lmb_engine); здесь только отображение.
import { fmt } from "../api";
import type { Catalog, DomainRes, Status, Trajectory } from "../types";
import { unitRu } from "../units";

const V03 = ["cardio", "metabolic", "renal", "hepatic", "inflammation", "brain", "bone"];
const INDEX_LABEL: Record<string, string> = {
  score2: "SCORE2", egfr: "eGFR", acr: "ACR", fib4: "FIB-4", homa_ir: "HOMA-IR", tyg: "TyG", aip: "AIP",
  whtr: "WHtR", nlr: "NLR", sii: "SII", caide: "CAIDE", frax_major: "FRAX, основные переломы",
};
const MISSING: Partial<Record<Status, string>> = {
  model_not_configured: "индекс не активирован",
  missing_data: "не хватает данных",
  not_applicable: "неприменимо",
  invalid_input: "ошибка ввода",
  awaiting_review: "ждёт подтверждения",
};
// знак ставится только если число не округляется до нуля (иначе «−0»)
export const signed = (v: number, d = 2) => {
  if (Math.abs(v) < 0.5 * 10 ** -d) return "0";
  return (v > 0 ? "+" : "−") + fmt(Math.abs(v), d);
};
const effect = (v: number) => (v > 0 ? "повышает" : v < 0 ? "снижает" : "не меняет");

export function Bar({ value, max }: { value: number; max: number }) {
  const w = max > 0 ? (Math.abs(value) / max) * 50 : 0;
  return (
    <span className="dv-track" aria-hidden="true">
      <span className="dv-axis" />
      <span className={value >= 0 ? "dv-bar up" : "dv-bar down"} style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
    </span>
  );
}

/** Вклад веток модели v0.3: коэффициент × доменная оценка, в условных годах модели. */
export function BranchContributions({ domains, catalog, intercept, total, research = false }: {
  domains: DomainRes[];
  catalog: Catalog;
  intercept: number;
  total: boolean;
  research?: boolean;
}) {
  const title = Object.fromEntries(catalog.branches.map((b) => [b.code, b]));
  const dom = new Map(domains.map((d) => [d.domain, d]));
  const done = V03.map((c) => dom.get(c)!).filter((d) => d && d.contribution !== null);
  const miss = V03.map((c) => dom.get(c)!).filter((d) => d && d.contribution === null);
  done.sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0));
  const max = Math.max(0.5, ...done.map((d) => Math.abs(d.contribution ?? 0)));
  const extra = catalog.branches.filter((b) => !V03.includes(b.code)).map((b) => b.title);
  return (
    <section className="dv-card" aria-labelledby="dv-branches">
      <header className="dv-head">
        <h3 id="dv-branches">Вклад систем организма</h3>
        <p className="dv-legend">
          <span className="dv-key up" /> повышает расчётную оценку <span className="dv-key down" /> снижает
        </p>
      </header>
      <div className="dv-rows" role="table" aria-label="Вклад веток в расчётную оценку">
        {done.map((d) => (
          <div key={d.domain} className="dv-row" role="row" title={`${title[d.domain]?.title}: доменная оценка ${fmt(d.score, 2)} × коэффициент ${fmt(d.coefficient, 1)} = ${signed(d.contribution!)}`}>
            <span className="dv-label" role="cell">
              <strong>{title[d.domain]?.title}</strong>
              <span className="muted small">{title[d.domain]?.name}</span>
            </span>
            <Bar value={d.contribution!} max={max} />
            <span className="dv-val num" role="cell">
              {signed(d.contribution!)}
              <span className="muted small"> {effect(d.contribution!)}</span>
            </span>
          </div>
        ))}
        {miss.map((d) => (
          <div key={d.domain} className="dv-row is-missing" role="row">
            <span className="dv-label" role="cell">
              <strong>{title[d.domain]?.title}</strong>
              <span className="muted small">{title[d.domain]?.name}</span>
            </span>
            <span className="dv-track dv-empty" aria-hidden="true">
              <span className="dv-axis" />
            </span>
            <span className="dv-val muted small" role="cell">
              нет вклада: {MISSING[d.status] ?? d.status}
            </span>
          </div>
        ))}
      </div>
      <p className="dv-note small muted">
        Вклад = коэффициент модели v0.3 × доменная оценка, в условных годах модели. Постоянная модели {signed(intercept)}.{" "}
        {total
          ? "Сумма вкладов и постоянной равна разнице между расчётным и календарным возрастом."
          : research
            ? "Клинический итог не утверждён; сумма вкладов и постоянной равна отклонению исследовательского расчёта выше."
            : "Клинический итог не рассчитан, вклады не суммируются."}{" "}
        {extra.length > 0 && <>{extra.join(" и ")} показываются в своих единицах и в модель v0.3 не входят.</>}
      </p>
    </section>
  );
}

/** Показатели, за счёт которых расчётная оценка растёт или снижается (разложение вкладов веток). */
export function IndicatorDrivers({ domains, catalog }: { domains: DomainRes[]; catalog: Catalog }) {
  const title = Object.fromEntries(catalog.branches.map((b) => [b.code, b.title]));
  const items = domains.flatMap((d) =>
    Object.entries(d.input_contributions ?? {}).map(([code, v]) => ({ code, v, branch: d.domain })),
  );
  if (items.length === 0) return null;
  items.sort((a, b) => b.v - a.v);
  const max = Math.max(0.25, ...items.map((i) => Math.abs(i.v)));
  return (
    <section className="dv-card" aria-labelledby="dv-drivers">
      <header className="dv-head">
        <h3 id="dv-drivers">Какие показатели определяют оценку</h3>
        <p className="dv-legend">
          <span className="dv-key up" /> повышает <span className="dv-key down" /> снижает
        </p>
      </header>
      <div className="dv-rows compact" role="table" aria-label="Вклад показателей">
        {items.map((i) => (
          <div key={i.code} className="dv-row" role="row" title={`${INDEX_LABEL[i.code] ?? i.code} (${title[i.branch]}): ${signed(i.v)} усл. лет`}>
            <span className="dv-label" role="cell">
              <strong>{INDEX_LABEL[i.code] ?? i.code}</strong>
              <span className="muted small">{title[i.branch]}</span>
            </span>
            <Bar value={i.v} max={max} />
            <span className="dv-val num" role="cell">{signed(i.v)}</span>
          </div>
        ))}
      </div>
      <p className="dv-note small muted">
        Вклад ветки разложен по её показателям в соответствии с правилом объединения: при среднем — каждый показатель даёт
        свою долю (Z / число показателей × коэффициент ветки).
      </p>
    </section>
  );
}

/** Траектории: ожидаемое значение показателя с возрастом для пола пациента (±1 SD) и точка пациента. */
export function Trajectories({ data }: { data: Record<string, Trajectory> }) {
  const codes = Object.keys(INDEX_LABEL).filter((c) => c in data);
  if (codes.length === 0) return null;
  return (
    <section className="dv-card traj-section" aria-labelledby="dv-traj">
      <header className="dv-head">
        <h3 id="dv-traj">Показатели на траектории возраста</h3>
        <p className="dv-legend">
          <span className="dv-key line" /> ожидаемое для возраста и пола <span className="dv-key band" /> ±1 стандартное
          отклонение <span className="dv-key dot" /> пациент
        </p>
      </header>
      <div className="traj-grid">
        {codes.map((c) => (
          <TrajectoryChart key={c} code={c} t={data[c]} />
        ))}
      </div>
      <p className="dv-note small muted">
        Ожидаемые значения — нормализация модели LMB v0.3 (авторская конфигурация, не клинические нормы). Точка выше или
        ниже линии показывает отклонение от ожидаемого для своего возраста; Z — это отклонение в стандартных отклонениях.
      </p>
    </section>
  );
}

function TrajectoryChart({ code, t }: { code: string; t: Trajectory }) {
  const W = 300, H = 150, L = 44, R = 10, T = 12, B = 24;
  const xs = t.curve.map((p) => p.age);
  const ys = t.curve.flatMap((p) => [p.lo, p.hi]).concat(t.value);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.08 || 1;
  y0 -= pad;
  y1 += pad;
  const X = (a: number) => L + ((a - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const band =
    t.curve.map((p, i) => `${i ? "L" : "M"}${X(p.age).toFixed(1)},${Y(p.hi).toFixed(1)}`).join("") +
    t.curve.slice().reverse().map((p) => `L${X(p.age).toFixed(1)},${Y(p.lo).toFixed(1)}`).join("") + "Z";
  const line = t.curve.map((p, i) => `${i ? "L" : "M"}${X(p.age).toFixed(1)},${Y(p.expected).toFixed(1)}`).join("");
  const worse = t.z_raw > 0;
  const near = Math.abs(t.z_raw) < 0.05;
  const tone = near ? "mid" : worse ? "up" : "down";
  const unit = unitRu(t.unit);
  const digits = Math.abs(t.value) >= 100 ? 0 : Math.abs(t.value) >= 10 ? 1 : 2;
  const at = t.curve.find((p) => p.age === t.age);
  return (
    <figure className="traj">
      <figcaption>
        <strong>{INDEX_LABEL[code] ?? code}</strong>
        {unit && <span className="muted small"> {unit}</span>}
        {code === "score2" && <span className="traj-note">отклонение от авторского ожидания v0.3, не категория риска</span>}
        <span className={`traj-z ${tone}`}>
          Z {signed(t.z_raw, 1)} · {near ? "на уровне" : worse ? "неблагоприятнее" : "благоприятнее"} ожидаемого
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${INDEX_LABEL[code]}: пациент ${fmt(t.value, digits)}${unit ? " " + unit : ""}, ожидаемое ${at ? fmt(at.expected, digits) : "—"}, Z ${signed(t.z_raw, 1)}`}>
        <line className="traj-gridline" x1={L} x2={W - R} y1={Y(y0 + pad)} y2={Y(y0 + pad)} />
        <path className="traj-band" d={band} />
        <path className="traj-line" d={line} />
        {at && <line className="traj-gap" x1={X(t.age)} x2={X(t.age)} y1={Y(at.expected)} y2={Y(t.value)} />}
        <circle className={`traj-dot ${tone}`} cx={X(t.age)} cy={Y(t.value)} r={5.5}>
          <title>{`Пациент, ${t.age} лет: ${fmt(t.value, digits)}${unit ? " " + unit : ""}; ожидаемое ${at ? fmt(at.expected, digits) : "—"}`}</title>
        </circle>
        <text className="traj-tick" x={L - 6} y={Y(y1 - pad) + 4} textAnchor="end">{fmt(y1 - pad, digits)}</text>
        <text className="traj-tick" x={L - 6} y={Y(y0 + pad) + 4} textAnchor="end">{fmt(y0 + pad, digits)}</text>
        <text className="traj-tick" x={X(x0)} y={H - 6} textAnchor="start">{x0}</text>
        <text className="traj-tick" x={X(x1)} y={H - 6} textAnchor="end">{x1} лет</text>
        <text className="traj-tick strong" x={X(t.age)} y={H - 6} textAnchor="middle">{t.age}</text>
      </svg>
    </figure>
  );
}
