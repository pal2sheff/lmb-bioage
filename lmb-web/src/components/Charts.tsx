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

/** Вклад систем: коэффициент модели × доменная оценка, в годах модели. */
export function BranchContributions({ domains, catalog, intercept, total }: {
  domains: DomainRes[];
  catalog: Catalog;
  intercept: number;
  total: boolean;
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
        Вклад = коэффициент модели × доменная оценка, в годах модели. Постоянная модели {signed(intercept)}.{" "}
        {total
          ? "Сумма вкладов и постоянной равна разнице биологического и паспортного возраста."
          : "Пока рассчитаны не все семь систем, вклады не складываются в биологический возраст."}{" "}
        {extra.length > 0 && <>{extra.join(" и ")} показываются в своих единицах и в модель не входят.</>}
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

const SYSTEM_OF: Record<string, string> = {
  score2: "cardio", homa_ir: "metabolic", tyg: "metabolic", aip: "metabolic", whtr: "metabolic", egfr: "renal",
  acr: "renal", fib4: "hepatic", nlr: "inflammation", sii: "inflammation", caide: "brain", frax_major: "bone",
};
const SYSTEM_RU: Record<string, string> = {
  cardio: "Cardio", metabolic: "Metabolic", renal: "Renal", hepatic: "Hepatic", inflammation: "Inflammation",
  brain: "Brain", bone: "Bone",
};
const digitsFor = (v: number) => (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);

/**
 * Одна диаграмма для всех показателей: общая безразмерная ось Z (отклонение от ожидаемого для возраста
 * и пола) и в каждой строке — траектория ожидаемого значения по возрасту в исходных единицах показателя.
 * Значения разных единиц на одну числовую ось не кладутся; общая ось — только Z.
 */
export function DeviationChart({ data }: { data: Record<string, Trajectory> }) {
  const codes = Object.keys(SYSTEM_OF).filter((c) => c in data);
  if (codes.length === 0) return null;
  const ZMAX = 3;
  const pos = (z: number) => ((Math.max(-ZMAX, Math.min(ZMAX, z)) + ZMAX) / (2 * ZMAX)) * 100;
  return (
    <section className="dv-card traj-section" aria-labelledby="dv-traj">
      <header className="dv-head">
        <h3 id="dv-traj">Показатели на траектории возраста</h3>
        <p className="dv-legend">
          <span className="dv-key line" /> ожидаемое для возраста и пола <span className="dv-key band" /> ±1 стандартное
          отклонение <span className="dv-key up" /> неблагоприятнее <span className="dv-key down" /> благоприятнее
        </p>
      </header>
      <div className="dev-grid" role="table" aria-label="Отклонение показателей от ожидаемого">
        <div className="dev-row dev-head" role="row">
          <span role="columnheader">Показатель</span>
          <span role="columnheader">Траектория с возрастом</span>
          <span role="columnheader" className="dev-axis-head">
            <span style={{ left: "0%" }}>−3</span>
            <span style={{ left: "33.333%" }}>−1</span>
            <span style={{ left: "50%" }}>0</span>
            <span style={{ left: "66.667%" }}>+1</span>
            <span style={{ left: "100%" }}>+3</span>
          </span>
          <span role="columnheader" className="dev-num">Пациент / ожидаемое</span>
        </div>
        {codes.map((c, i) => {
          const t = data[c];
          const at = t.curve.find((p) => p.age === t.age);
          const tone = Math.abs(t.z_raw) < 0.05 ? "mid" : t.z_raw > 0 ? "up" : "down";
          const d = digitsFor(t.value);
          const unit = unitRu(t.unit);
          const newGroup = i === 0 || SYSTEM_OF[codes[i - 1]] !== SYSTEM_OF[c];
          return (
            <div key={c} className={`dev-row${newGroup ? " group-start" : ""}`} role="row"
              title={`${INDEX_LABEL[c]}: пациент ${fmt(t.value, d)}${unit ? " " + unit : ""}, ожидаемое ${at ? fmt(at.expected, d) : "—"}, Z ${signed(t.z_raw, 2)}`}>
              <span className="dev-label" role="cell">
                <strong>{INDEX_LABEL[c] ?? c}</strong>
                <span className="muted small">{SYSTEM_RU[SYSTEM_OF[c]]}{c === "score2" ? " · от авторского ожидания" : ""}</span>
              </span>
              <span role="cell"><Spark t={t} tone={tone} /></span>
              <span className="dev-strip" role="cell" aria-label={`Z ${signed(t.z_raw, 2)}`}>
                <span className="dev-band" />
                <span className="dev-zero" />
                <span className={`dev-stem ${tone}`} style={t.z_raw >= 0
                  ? { left: "50%", width: `${pos(t.z_raw) - 50}%` } : { left: `${pos(t.z_raw)}%`, width: `${50 - pos(t.z_raw)}%` }} />
                <span className={`dev-dot ${tone}`} style={{ left: `${pos(t.z_raw)}%` }} />
                {Math.abs(t.z_raw) > ZMAX && <span className={`dev-clip ${t.z_raw > 0 ? "right" : "left"}`}>{signed(t.z_raw, 1)}</span>}
              </span>
              <span className="dev-num num" role="cell">
                {fmt(t.value, d)} <span className="muted">/ {at ? fmt(at.expected, d) : "—"}</span>
                {unit && <span className="muted small"> {unit}</span>}
              </span>
            </div>
          );
        })}
      </div>
      <p className="dv-note small muted">
        Ожидаемое значение — нормализация модели LMB (авторская конфигурация, не клинические нормы). Z — отклонение от
        ожидаемого в стандартных отклонениях: вправо — неблагоприятнее, влево — благоприятнее; в модель входит Z,
        ограниченное ±3.
      </p>
    </section>
  );
}

/** Мини-траектория: ожидаемое по возрасту (±1 SD) в единицах показателя и точка пациента. */
function Spark({ t, tone }: { t: Trajectory; tone: string }) {
  const W = 160, H = 40, P = 4;
  const xs = t.curve.map((p) => p.age);
  const ys = t.curve.flatMap((p) => [p.lo, p.hi]).concat(t.value);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (a: number) => P + ((a - x0) / (x1 - x0 || 1)) * (W - 2 * P);
  const Y = (v: number) => P + (1 - (v - y0) / (y1 - y0 || 1)) * (H - 2 * P);
  const band = t.curve.map((p, i) => `${i ? "L" : "M"}${X(p.age).toFixed(1)},${Y(p.hi).toFixed(1)}`).join("") +
    t.curve.slice().reverse().map((p) => `L${X(p.age).toFixed(1)},${Y(p.lo).toFixed(1)}`).join("") + "Z";
  const line = t.curve.map((p, i) => `${i ? "L" : "M"}${X(p.age).toFixed(1)},${Y(p.expected).toFixed(1)}`).join("");
  const at = t.curve.find((p) => p.age === t.age);
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} aria-hidden="true" preserveAspectRatio="none">
      <path className="traj-band" d={band} />
      <path className="traj-line" d={line} vectorEffect="non-scaling-stroke" />
      {at && <line className="traj-gap" x1={X(t.age)} x2={X(t.age)} y1={Y(at.expected)} y2={Y(t.value)} vectorEffect="non-scaling-stroke" />}
      <circle className={`traj-dot ${tone}`} cx={X(t.age)} cy={Y(t.value)} r={3.6} />
    </svg>
  );
}
