import { type ReactNode, useEffect, useState } from "react";
import { fmt } from "../api";
import type { CardioAnchor, Catalog, IndexRes, MuscleMeasurements, Run } from "../types";
import { unitRu } from "../units";
import { BranchContributions, DeviationChart, signed } from "./Charts";
import { MuscleTestToggle, ResearchToggle, useCardioCheck, useMuscleTest, useResearchMode } from "./TestMode";
import { StatusBadge } from "./ui";

/** Результат расчётного модуля (pipeline.run) — одинаковый у сервера и браузерного калькулятора. */
export type EngineResult = Run["result"] & {
  status: "calculated" | "blocked";
  bioage_years: number | null;
  delta_years: number | null;
};

/** Переход от сообщения к полю ввода (в калькуляторе); в кабинете не передаётся. */
export type GoTo = (code: string) => void;

export const DIGITS: Record<string, number> = {
  caide: 0, egfr_ckdepi_cr_2021: 0, bmi: 1, score2: 1, score2_op: 1, frax_kz: 1, sii: 0, whtr: 3, aip: 3, tyg: 2,
  phenoage: 1, muscle_age: 1, lqone_bioage: 2,
};
export const DOMAIN_LABEL: Record<string, string> = {
  calculated: "рассчитана",
  model_not_configured: "входной индекс не активирован",
  not_included: "не входит в модель",
  missing_data: "не хватает данных",
  not_applicable: "данные вне области применения",
  invalid_input: "ошибка во входных данных",
  awaiting_review: "требует решения врача",
};
const FORMULA: Record<string, string> = {
  score2: "SCORE2 (ESC 2021), регион высокого риска; непрерывный возраст на дату обследования",
  score2_op: "SCORE2-OP (ESC 2021), регион высокого риска, 70–89 лет",
  non_hdl: "Non-HDL = общий холестерин − ЛПВП",
  homa_ir: "HOMA-IR = глюкоза (ммоль/л) × инсулин (мкЕд/мл) / 22,5",
  tyg: "TyG = ln(ТГ мг/дл × глюкоза мг/дл / 2)",
  aip: "AIP = log10(ТГ / ЛПВП), ммоль/л",
  whtr: "WHtR = талия / рост",
  bmi: "ИМТ = масса / рост², кг/м²",
  egfr_ckdepi_cr_2021: "CKD-EPI 2021 (креатинин), без расового коэффициента",
  acr: "ACR = альбумин мочи / креатинин мочи; мг/г = мг/ммоль × 8,84",
  fib4: "FIB-4 = возраст × АСТ / (тромбоциты × √АЛТ)",
  nlr: "NLR = нейтрофилы / лимфоциты (абсолютные)",
  sii: "SII = тромбоциты × нейтрофилы / лимфоциты",
  caide: "CAIDE, модель 1 без APOE (Kivipelto 2006), 39–64 года",
  frax_kz: "Результат официального калькулятора FRAX, модель Казахстана; приложение FRAX не рассчитывает",
  asmi: "ASMI = ASM / рост², кг/м²; ASM = левая рука + правая рука + левая нога + правая нога (сегменты Visbody, туловище не входит); источник «Visbody, расчёт по четырём сегментам»",
  phenoage: "Levine 2018 (поправка PLoS Med 2019): альбумин, креатинин, глюкоза, вч-СРБ, лимфоциты %, MCV, RDW, ЩФ, лейкоциты, возраст",
  lqone_bioage: "Значение из отчёта LQ One, годы, внесённое врачом, без пересчёта; алгоритм аппарата не воспроизводится. В LMB BioAge не входит",
  muscle_age: "Мышечный возраст = A + P − P_ref(A); P = 67,0445 − 0,6524·G + 23,8986·ln(T) − 4,7645·ASMI (G — максимум хвата, кг; T — пять вставаний, с; ASMI — ASM/рост², ASM — сумма 4 сегментов Visbody). Тестовая модель 0.1-synthetic: коэффициенты и ориентиры владельца без описания происхождения; мужчины 20–89 лет; не подтверждена; в LMB BioAge не входит",
};
/** SCORE2 и SCORE2-OP взаимоисключающие по возрасту: неприменимость второго при рассчитанном первом — не ограничение. */
const PARTNER: Record<string, string> = { score2: "score2_op", score2_op: "score2" };
function isComplement(res: IndexRes, all: { code: string; status: string }[]): boolean {
  const p = PARTNER[res.code];
  return !!p && res.status === "not_applicable" && all.some((i) => i.code === p && i.status === "calculated");
}

/** Русские названия полей для сообщений (без внутренних кодов). */
export function fieldNames(catalog: Catalog): Record<string, string> {
  const names: Record<string, string> = {
    birth_date: "дата рождения", sex_at_birth: "пол", frax_result: "результат FRAX",
    frax_major_10y_pct: "FRAX: риск основных переломов", frax_hip_10y_pct: "FRAX: риск перелома бедра",
  };
  catalog.observation_groups.forEach((g) => g.items.forEach((d) => (names[d.code] = d.name_ru)));
  catalog.questionnaire_groups.forEach((g) => g.items.forEach((q) => (names[q.code] = q.name)));
  return names;
}

export function reasonsRu(reasons: string[], catalog: Catalog): string[] {
  const title = Object.fromEntries(catalog.branches.map((b) => [b.code, b.name]));
  return reasons.map((x) => {
    const m = /^Домен (\w+): (\w+)$/.exec(x);
    if (m) return `${title[m[1]] ?? m[1]}: ${DOMAIN_LABEL[m[2]] ?? m[2]}`;
    if (x.startsWith("Конфигурация модели неполная: target_population")) return "целевая популяция модели не утверждена";
    return x;
  });
}

/** Ссылки «к полю» для перечня полей. */
export function FieldLinks({ codes, names, goTo }: { codes: string[]; names: Record<string, string>; goTo?: GoTo }) {
  return (
    <>
      {codes.map((c, i) => (
        <span key={c}>
          {i > 0 && ", "}
          {goTo ? (
            <button type="button" className="link-btn" onClick={() => goTo(c)}>
              {names[c] ?? c}
            </button>
          ) : (
            names[c] ?? c
          )}
        </span>
      ))}
    </>
  );
}

/**
 * Результаты (уточнение владельца 11.10.2026, 21:24): возраст и PhenoAge → инфографика (видна сразу) →
 * показатели по системам → недостающие данные → «О методике» (статус, область, настройки, техданные).
 */
export function ProfileView({ result, catalog, meta, goTo }: { result: EngineResult; catalog: Catalog; meta?: ReactNode; goTo?: GoTo }) {
  const idx = new Map(result.indices.map((i) => [i.code, i]));
  const [research, setResearch] = useResearchMode();
  const [muscleTest, setMuscleTest] = useMuscleTest();
  const [method, setMethod] = useState(false);
  useEffect(() => {
    const open = () => setMethod(true);
    window.addEventListener(METHOD_EVENT, open);
    return () => window.removeEventListener(METHOD_EVENT, open);
  }, []);
  const names = fieldNames(catalog);
  const r = research ? result.research ?? null : null;
  const delta = r?.status === "calculated" ? r.delta_years : null;
  // мышечный возраст и возраст LQ1 — рядом с PhenoAge, когда для них что-то внесено
  const side = AGE_CARDS.filter((c) => {
    const x = idx.get(c);
    if (!x) return false;
    if (c === "muscle_age" && !muscleTest) return false;    // модель 0.1-synthetic — только в режиме тестирования
    if (x.status !== "missing_data") return true;
    const inputs = AGE_INPUTS[c];
    return x.missing_fields.length < inputs.length && inputs.some((f) => !x.missing_fields.includes(f));
  });
  return (
    <>
      <div className={`summary-grid side-${side.length}`}>
        <AgeSummary result={result} catalog={catalog} research={research} />
        <PhenoAgeCard res={idx.get("phenoage")} names={names} goTo={goTo} />
        {side.map((c) => (
          <DeviceAgeCard key={c} code={c} res={idx.get(c)!} names={names} goTo={goTo} />
        ))}
      </div>

      {r ? (
        <div className="charts-grid">
          <BranchContributions domains={result.domains} intercept={result.intercept} delta={delta} />
          {result.trajectories && <DeviationChart data={result.trajectories} />}
        </div>
      ) : (
        <p className="muted small charts-off">
          Расчётная оценка LMB и инфографика выключены —{" "}
          <button type="button" className="link-btn" onClick={openMethod}>включить в разделе «О методике»</button>
        </p>
      )}

      <h2 className="section-title results-title">Показатели по системам</h2>
      <div className="branch-grid">
        {catalog.branches.map((b) => (
          <SystemCard key={b.code} name={b.name} indices={b.indices.filter((c) => c !== "muscle_age" || muscleTest)} idx={idx}
            catalog={catalog} names={names} goTo={goTo}
            extra={b.code === "muscle" ? <MuscleRaw m={result.muscle_measurements} /> : undefined} />
        ))}
        {(catalog.future_branches ?? []).map((b) => (
          <article key={b.code} className="branch future" aria-label={b.name}>
            <h3>
              {b.name} <span className="badge-dev">В работе</span>
            </h3>
            <p className="index-expl">{b.note}</p>
          </article>
        ))}
      </div>

      <GapsCard result={result} catalog={catalog} names={names} goTo={goTo} />

      {method && (
        <MethodDrawer onClose={() => setMethod(false)}>
          <Methodology result={result} catalog={catalog} extra={meta}
            settings={
              <>
                {result.research && <ResearchToggle on={research} onChange={setResearch} />}
                <MuscleTestToggle on={muscleTest} onChange={setMuscleTest} />
                {research && result.research?.cardio_anchor_experiment && (
                  <CardioCheck x={result.research.cardio_anchor_experiment} result={result} />
                )}
              </>
            } />
        </MethodDrawer>
      )}
    </>
  );
}

const METHOD_EVENT = "lmb:open-method";
/** Открыть панель «О методике» (поверх экрана: карточки и диаграммы не сдвигаются). */
export function openMethod() {
  window.dispatchEvent(new Event(METHOD_EVENT));
}

/** Всплывающая панель справа; закрывается кнопкой, Esc или щелчком по затемнению. */
function MethodDrawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="drawer-backdrop no-print" onClick={onClose}>
      <aside className="method-drawer" role="dialog" aria-modal="true" aria-labelledby="method-title" id="method"
        onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <h2 id="method-title">О методике</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} autoFocus>Закрыть</button>
        </header>
        {children}
      </aside>
    </div>
  );
}

/** Исходные данные мышечной ветки — показываются всегда (мышечный возраст — только в режиме тестирования). */
function MuscleRaw({ m }: { m?: MuscleMeasurements }) {
  if (!m) return null;
  const has = m.grip_used_kg != null || m.chair_stand_5x_s != null || m.chair_stand_unable || m.asm_kg != null;
  if (!has) return null;
  const parts = [
    m.grip_used_kg != null ? `хват ${fmt(m.grip_used_kg, 1)} кг (правая ${fmt(m.grip_right_kg, 1)}, левая ${fmt(m.grip_left_kg, 1)})` : null,
    m.chair_stand_unable ? "5 вставаний: не удалось выполнить" : m.chair_stand_5x_s != null ? `5 вставаний ${fmt(m.chair_stand_5x_s, 1)} с` : null,
    m.asm_kg != null ? `ASM ${fmt(m.asm_kg, 2)} кг (4 сегмента Visbody)` : null,
  ].filter(Boolean);
  return <p className="index-expl muscle-raw">{parts.join(" · ")}</p>;
}
function toGaps() {
  document.getElementById("gaps-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** Компактный блок: календарный возраст, LMB BioAge (расчётная оценка тестового режима), разница. */
function AgeSummary({ result, catalog, research }: { result: EngineResult; catalog: Catalog; research: boolean }) {
  const r = result.research;
  const age = result.age_years ?? null;
  const ok = research && !!r && r.status === "calculated" && r.bioage_years !== null && r.delta_years !== null;
  const d = ok ? r!.delta_years! : 0;
  const why = r && !ok && research ? reasonsRu(r.reasons, catalog) : [];
  return (
    <section className="age-summary" aria-label="Возраст">
      <div className="figure">
        <span className="eyebrow">Календарный возраст</span>
        <span className="figure-value secondary num">
          {age ?? "—"} <span className="figure-unit">лет</span>
        </span>
      </div>
      <div className="figure">
        <span className="eyebrow">
          LMB BioAge
          <button type="button" className="info-btn" aria-label="О методике LMB BioAge" onClick={openMethod}>i</button>
        </span>
        {ok ? (
          <span className="figure-value bio-value num">
            {fmt(r!.bioage_years, 1)} <span className="figure-unit">лет</span>
          </span>
        ) : (
          <>
            <span className="figure-value empty">{research ? "не рассчитан" : "выключен"}</span>
            {why.length > 0 && (
              <span className="figure-note why">
                {why.slice(0, 2).join("; ")}{" "}
                <button type="button" className="link-btn" onClick={toGaps}>что нужно</button>
              </span>
            )}
          </>
        )}
      </div>
      <div className="figure">
        <span className="eyebrow">Разница</span>
        {ok ? (
          <>
            <span className="figure-value secondary num">
              {signed(d, 1)} <span className="figure-unit">лет</span>
            </span>
            <span className={`delta ${d > 0 ? "up" : d < 0 ? "down" : ""}`}>
              {d > 0 ? "старше календарного" : d < 0 ? "моложе календарного" : "равен календарному"}
            </span>
          </>
        ) : (
          <span className="figure-value empty">—</span>
        )}
      </div>
    </section>
  );
}

const AGE_CARDS = ["muscle_age", "lqone_bioage"];
const AGE_TITLE: Record<string, string> = { muscle_age: "Мышечный возраст", lqone_bioage: "Возраст по LQ1" };
/** Входы, по которым видно, что исследование вносили (карточка появляется, даже если чего-то не хватает). */
const AGE_INPUTS: Record<string, string[]> = {
  muscle_age: ["grip_right_kg", "grip_left_kg", "chair_stand_5x_s", "visbody_seg_arm_left_kg", "visbody_seg_arm_right_kg",
    "visbody_seg_leg_left_kg", "visbody_seg_leg_right_kg"],
  lqone_bioage: ["lqone_bioage_years"],
};

/** Мышечный возраст (режим тестирования; с разницей с календарным) и возраст по LQ1 (только значение). */
function DeviceAgeCard({ code, res, names, goTo }: { code: string; res: IndexRes; names: Record<string, string>; goTo?: GoTo }) {
  const ok = res.status === "calculated" && res.value !== null;
  const d = (res.extra as { delta_years?: number | null }).delta_years;
  return (
    <section className="pheno-card age-side" aria-label={AGE_TITLE[code]}>
      <span className="eyebrow">
          <span>{AGE_TITLE[code]}</span>
        {code === "muscle_age" && <span className="badge-dev">тест</span>}
        <Info label={AGE_TITLE[code]}>
          <span>{FORMULA[code]}</span>
        </Info>
      </span>
      {ok ? (
        <span className="figure-value num">
          {code === "muscle_age" ? fixed1(res.value!) : fmt(res.value, 2)} <span className="figure-unit">лет</span>
        </span>
      ) : (
        <span className="figure-value empty">не рассчитан</span>
      )}
      {ok && d != null && code === "muscle_age" && (
        <span className={`delta ${d > 0 ? "up" : d < 0 ? "down" : ""}`}>{signed(d, 1)} к календарному</span>
      )}
      {!ok && <ShortNotes res={res} names={names} goTo={goTo} />}
    </section>
  );
}

/** Один десятичный знак всегда (33,7; 35,0). */
const fixed1 = (v: number) => v.toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Кнопка информации: формулы, источники и пояснения — по нажатию. */
export function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="info" onToggle={(e) => {
      const d = e.currentTarget;
      if (!d.open) return;
      const close = (ev: MouseEvent) => {
        if (!d.contains(ev.target as Node)) {
          d.open = false;
          document.removeEventListener("click", close);
        }
      };
      setTimeout(() => document.addEventListener("click", close), 0);
    }}>
      <summary aria-label={`Подробнее: ${label}`} title="Подробнее">i</summary>
      <div className="info-body">{children}</div>
    </details>
  );
}

/** PhenoAge — самостоятельный показатель: свой статус, не зависит от LMB и режима расчёта. */
export function PhenoAgeCard({ res, names, goTo }: { res?: IndexRes; names: Record<string, string>; goTo?: GoTo }) {
  if (!res) return null;
  const ok = res.status === "calculated" && res.value !== null;
  // методические оговорки (сверка с внешним калькулятором) — в справке, а не на основном экране
  return (
    <section className="pheno-card" aria-labelledby="pheno-title">
      <span className="eyebrow">
        <span id="pheno-title">PhenoAge</span>
        <Info label="PhenoAge">
          <span>{FORMULA.phenoage}</span>
          <span>Самостоятельный показатель: в LMB BioAge не входит.</span>
          {res.warnings.map((w) => (
            <span key={w}>{w}</span>
          ))}
        </Info>
      </span>
      {ok ? (
        <span className="figure-value num">
          {fmt(res.value, 1)} <span className="figure-unit">лет</span>
        </span>
      ) : (
        <span className="figure-value empty">не рассчитан</span>
      )}
      {!ok && <ShortNotes res={res} names={names} goTo={goTo} />}
    </section>
  );
}

/** Проверочный расчёт Cardio рядом с исходным (задание владельца 11.10.2026). В отчёт не входит. */
function CardioCheck({ x, result }: { x: CardioAnchor; result: EngineResult }) {
  const [on, setOn] = useCardioCheck();
  const r = result.research!;
  const z = result.zscores?.score2;
  const expected = z?.expected != null ? Math.expm1(z.expected) : null;
  const ok = x.status === "calculated" && r.status === "calculated";
  const row = (label: string, a: ReactNode, b: ReactNode) => (
    <tr>
      <th scope="row">{label}</th>
      <td className="num">{a}</td>
      <td className="num">{b}</td>
    </tr>
  );
  // фиксированное число знаков, чтобы колонки сравнивались по разрядам
  const fx = (v: number, d: number) => v.toFixed(d).replace(".", ",").replace("-", "−");
  const sg = (v: number, d: number) => (v > 0 ? "+" : "") + fx(v, d);
  const pct = (v: number | null | undefined, d = 3) => (v == null ? "—" : `${fx(v, d)} %`);
  const num = (v: number | null | undefined, d = 3) => (v == null ? "—" : sg(v, d));
  return (
    <div className="card cardio-check no-print">
      <label className="research-toggle small-toggle">
        <span className="switch">
          <input type="checkbox" role="switch" checked={on} onChange={(e) => setOn(e.target.checked)}
            aria-label="Проверочный расчёт Cardio" />
          <span />
        </span>
        Проверочный расчёт Cardio (условный контрольный профиль SCORE2)
      </label>
      {on && (
        <div className="check-body" aria-label={x.label}>
          <h3>{x.label}</h3>
          <p className="limits check-note" role="note">
            {x.disclaimer}. Ожидание Cardio заменено SCORE2 High условного профиля того же пола и возраста (САД{" "}
            {x.control_profile.sbp_mmhg}, общий холестерин {fmt(x.control_profile.tc_mmol_l, 1)}, ЛПВП{" "}
            {fmt(x.control_profile.hdl_mmol_l, 1)} ммоль/л, без курения); делитель {fmt(x.residual_sd, 6)} — из
            исходной модели, новой выборкой не подтверждён.
          </p>
          <table className="check-table">
            <thead>
              <tr>
                <th />
                <th scope="col">Исходная модель</th>
                <th scope="col">Проверочный расчёт</th>
              </tr>
            </thead>
            <tbody>
              {row("SCORE2 пациента", pct(x.score2_pct), pct(x.score2_pct))}
              {row("Ожидание / риск условного профиля", pct(expected), pct(x.control_score2_pct))}
              {row("Нормированная оценка Cardio", num(z?.z_clipped ?? null), num(x.z_clipped))}
              {row("Вклад Cardio, лет", num(r.contributions?.cardio ?? null), num(x.contribution))}
              {row("LMB BioAge, лет", r.bioage_years == null ? "—" : fx(r.bioage_years, 2), x.bioage_years == null ? "—" : fx(x.bioage_years, 2))}
            </tbody>
          </table>
          {ok ? (
            <p className="check-change">
              Изменение общего результата: <b className="num">{sg(x.change_years!, 2)} лет</b>
            </p>
          ) : (
            <p className="muted">Проверочный итог не рассчитан: {x.reasons[0] ?? x.status}</p>
          )}
        </div>
      )}
    </div>
  );
}

function SystemCard(props: {
  name: string; indices: string[]; idx: Map<string, IndexRes>; catalog: Catalog; names: Record<string, string>; goTo?: GoTo;
  extra?: ReactNode;
}) {
  const { name, indices, idx, catalog, names, goTo, extra } = props;
  return (
    <article className="branch" aria-label={name}>
      <h3>{name}</h3>
      {indices.length === 0 && <p className="index-expl">Данные LQ One пока не подключены</p>}
      {indices.map((c) => (
        <IndexBlock key={c} code={c} res={idx.get(c)} idx={idx} catalog={catalog} names={names} goTo={goTo} />
      ))}
      {extra}
    </article>
  );
}

/** Причины, предупреждения и недостающие поля индекса — только фактические, с переходом к полю. */
function IndexNotes({ res, names, goTo }: { res: IndexRes; names: Record<string, string>; goTo?: GoTo }) {
  const bad = (res.invalid_fields ?? []).filter((f) => !res.missing_fields.includes(f));
  if (res.reasons.length + res.warnings.length + res.missing_fields.length + bad.length === 0) return null;
  return (
    <ul className="notes">
      {res.reasons.map((r) => (
        <li key={r}>{r}</li>
      ))}
      {bad.length > 0 && (
        <li>
          исправьте: <FieldLinks codes={bad} names={names} goTo={goTo} />
        </li>
      )}
      {res.missing_fields.length > 0 && (
        <li>
          не хватает: <FieldLinks codes={res.missing_fields} names={names} goTo={goTo} />
        </li>
      )}
      {res.warnings.map((r) => (
        <li key={r} className="warn">
          {r}
        </li>
      ))}
    </ul>
  );
}

function IndexBlock({ code, res, idx, catalog, names, goTo }: {
  code: string; res: IndexRes | undefined; idx: Map<string, IndexRes>; catalog: Catalog; names: Record<string, string>; goTo?: GoTo;
}) {
  const label = catalog.index_labels[code];
  if (!res) return null;
  const unit = unitRu(res.unit);
  const show = res.value !== null && res.status === "calculated";
  const e = res.extra as Record<string, unknown>;
  // при рассчитанном SCORE2 неприменимость SCORE2-OP (и наоборот) — справка, а не предупреждение
  const quiet = isComplement(res, [...idx.values()]);
  const shown = quiet ? { ...res, reasons: [] } : res;
  const info = (
    <Info label={label?.short ?? code}>
      {label?.name && <strong>{label.name}</strong>}
      {FORMULA[code] && <span className="formula">{FORMULA[code]}</span>}
      {quiet && res.reasons.map((x) => <span key={x}>{x}</span>)}
      {details(code, res).map((x) => (
        <span key={x}>{x}</span>
      ))}
    </Info>
  );
  const status = res.status !== "calculated" && <StatusBadge status={res.status} />;
  if (code === "frax_kz" && show)
    return (
      <div className="index-line">
        <div className="index-row">
          <span className="index-name"><strong>FRAX</strong> <span className="muted">основные</span>{info}</span>
          <span className="index-val num">{fmt(res.value, 1)}<span className="unit">%</span></span>
        </div>
        <div className="index-row">
          <span className="index-name"><strong>FRAX</strong> <span className="muted">бедро</span></span>
          <span className="index-val num">{fmt(e.hip_10y_pct as number, 1)}<span className="unit">%</span></span>
        </div>
        <span className="index-expl">из официального калькулятора FRAX · модель Казахстана · {e.with_bmd ? "с МПК" : "без МПК"}</span>
        <IndexNotes res={res} names={names} goTo={goTo} />
      </div>
    );
  return (
    <div className="index-line">
      <div className="index-row">
        <span className="index-name"><strong>{label?.short ?? code}</strong>{info}</span>
        {show ? (
          <span className="index-val num">
            {code === "muscle_age" ? fixed1(res.value!) : fmt(res.value, DIGITS[code] ?? 2)}
            {unit && <span className="unit">{unit}</span>}
          </span>
        ) : (
          status
        )}
      </div>
      {code === "acr" && <AcrSource res={res} />}
      {code === "muscle_age" && <MuscleMeta res={res} />}
      <IndexNotes res={shown} names={names} goTo={goTo} />
    </div>
  );
}

/** Мышечный возраст (режим тестирования): разница с календарным и отметка модели. */
function MuscleMeta({ res }: { res: IndexRes }) {
  const d = (res.extra as { delta_years?: number | null }).delta_years;
  return (
    <span className="index-expl">
      {d != null ? `${signed(d, 1)} к календарному · ` : ""}тестовая модель 0.1-synthetic, не подтверждена
    </span>
  );
}

const ACR_SOURCE_RU: Record<string, string> = { lab: "готовый ACR лаборатории", calculated: "расчёт по альбумину и креатинину мочи" };

/**
 * Короткая причина в карточке возрастного показателя: ошибка в данных («Проверьте альбумин сыворотки» —
 * переход к полю, подробное сообщение — у поля), недостающие данные, неприменимость. Различаются по виду.
 */
function ShortNotes({ res, names, goTo }: { res: IndexRes; names: Record<string, string>; goTo?: GoTo }) {
  const bad = (res.invalid_fields ?? []).filter((f) => !res.missing_fields.includes(f));
  const low = (c: string) => {
    const n = names[c] ?? c;
    return /^[А-ЯЁ][а-яё]/.test(n) ? n[0].toLowerCase() + n.slice(1) : n;
  };
  return (
    <ul className="short-notes">
      {res.status === "invalid_input" &&
        (bad.length > 0 ? (
          bad.map((f) => (
            <li key={f} className="sn-error">
              {goTo ? (
                <button type="button" className="link-btn" onClick={() => goTo(f)}>Проверьте {low(f)}</button>
              ) : (
                <>Проверьте {low(f)}</>
              )}
            </li>
          ))
        ) : (
          res.reasons.slice(0, 1).map((r) => <li key={r} className="sn-error">{r}</li>)
        ))}
      {res.missing_fields.length > 0 && (
        <li className="sn-missing">
          не хватает: <Collapsible codes={res.missing_fields} names={names} goTo={goTo} />
        </li>
      )}
      {(res.status === "not_applicable" || res.status === "awaiting_review") &&
        res.reasons.map((r) => <li key={r} className="sn-na">{r}</li>)}
    </ul>
  );
}

/** Длинный перечень полей сворачивается: первые три видны, остальные — по нажатию. */
function Collapsible({ codes, names, goTo, limit = 3 }: { codes: string[]; names: Record<string, string>; goTo?: GoTo; limit?: number }) {
  const [all, setAll] = useState(false);
  if (codes.length <= limit + 1 || all) return <FieldLinks codes={codes} names={names} goTo={goTo} />;
  return (
    <>
      <FieldLinks codes={codes.slice(0, limit)} names={names} goTo={goTo} />{" "}
      <button type="button" className="more-btn" onClick={() => setAll(true)}>ещё {codes.length - limit}</button>
    </>
  );
}

/** Источник ACR и оба значения, если их два. */
export function AcrSource({ res }: { res: IndexRes }) {
  const e = res.extra as { source?: string | null; acr_lab_mg_mmol?: number; acr_calculated_mg_mmol?: number };
  const both = e.acr_lab_mg_mmol !== undefined && e.acr_calculated_mg_mmol !== undefined;
  if (!e.source && !both) return null;
  return (
    <span className="index-expl acr-source">
      {e.source && <>источник: {ACR_SOURCE_RU[e.source] ?? e.source}</>}
      {both && (
        <>
          {e.source ? " · " : ""}лаборатория {fmt(e.acr_lab_mg_mmol, 2)} мг/ммоль, расчёт {fmt(e.acr_calculated_mg_mmol, 2)} мг/ммоль
        </>
      )}
    </span>
  );
}

function details(code: string, res: IndexRes): string[] {
  const out: string[] = [];
  if (res.status !== "calculated") return out;
  const e = res.extra as Record<string, unknown>;
  if (code === "acr" && e.acr_mg_g !== undefined) out.push(`${fmt(e.acr_mg_g as number, 1)} мг/г`);
  if (code === "caide" && e.age_band) {
    const b = e.age_band as { label: string; points: number };
    out.push(`возрастная категория: ${b.label} (${b.points} балла). Балл возраста меняется ступенчато в 47 и 54 года — при сравнении визитов через эти границы оценка меняется без изменения здоровья.`);
  }
  if (code === "score2" || code === "score2_op")
    out.push("Категорию сердечно-сосудистого риска определяет сам SCORE2.");
  return out;
}

/** Ограничения и недостающие данные: по полям, с переходом к полю; без повторов. */
function GapsCard({ result, catalog, names, goTo }: { result: EngineResult; catalog: Catalog; names: Record<string, string>; goTo?: GoTo }) {
  const label = (c: string) => catalog.index_labels[c]?.short ?? c;
  const skip = new Set(["asmi", "lqone_bioage", "muscle_age"]);   // показатели аппаратов необязательны — не «недостающие данные»
  const missing = new Map<string, string[]>();
  const invalid: { msg: string; fields: string[] }[] = [];
  const review: string[] = [];
  const limits: string[] = [];
  const seen = new Set<string>();
  for (const i of result.indices) {
    if (skip.has(i.code)) continue;
    for (const f of i.missing_fields) missing.set(f, [...(missing.get(f) ?? []), label(i.code)]);
    if (i.status === "invalid_input")
      for (const r of i.reasons) {
        if (seen.has(r)) continue;
        seen.add(r);
        invalid.push({ msg: r, fields: i.invalid_fields ?? [] });
      }
    if (i.status === "awaiting_review") i.reasons.forEach((r) => !review.includes(r) && review.push(r));
    if (i.status === "not_applicable" && !isComplement(i, result.indices)) i.reasons.forEach((r) => limits.push(`${label(i.code)}: ${r}`));
  }
  if (missing.size + invalid.length + review.length + limits.length === 0) return null;
  return (
    <section className="card gaps-card" aria-labelledby="gaps-title">
      <h2 id="gaps-title" className="section-title">Ограничения и недостающие данные</h2>
      {invalid.length > 0 && (
        <>
          <h3>Исправьте</h3>
          <ul className="gap-list">
            {invalid.map((x) => (
              <li key={x.msg}>
                {x.msg}
                {x.fields.length > 0 && (
                  <>
                    {" "}— <FieldLinks codes={x.fields} names={names} goTo={goTo} />
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {review.length > 0 && (
        <>
          <h3>Требует решения врача</h3>
          <ul className="gap-list">
            {review.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}
      {missing.size > 0 && (
        <>
          <h3>Не хватает данных</h3>
          <MissingList entries={[...missing.entries()]} names={names} goTo={goTo} />
        </>
      )}
      {limits.length > 0 && (
        <>
          <h3>Ограничения применимости</h3>
          <ul className="gap-list">
            {limits.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/** О методике: статус, область, правила расчёта, настройки режима (на экране) и технические данные — одним блоком. */
export function Methodology({ result, catalog, extra, settings }: {
  result: EngineResult; catalog: Catalog; extra?: ReactNode; settings?: ReactNode;
}) {
  const r = result.research;
  const why = reasonsRu(result.blocking_reasons, catalog);
  const pop = r?.research_population;
  return (
    <div className="method-body">
      {settings && <div className="method-settings no-print">{settings}</div>}
      <ul className="method-list">
        <li>
          {r && r.limitations.length > 0 ? r.limitations.join(" ") : "Исследовательская модель. Клиническая валидация не проведена."}
        </li>
        <li>
          Значение LMB BioAge — расчётная оценка локального тестового режима
          {pop ? ` (синтетические профили ${pop.age_min}–${pop.age_max} лет, не референтная выборка)` : ""}.
          {why.length > 0 && <> Клинический итог не рассчитан: {why.join("; ")}.</>}
        </li>
        <li>
          Разница с календарным возрастом = постоянная {signed(result.intercept, 2)} + сумма вкладов семи систем;
          вклад = коэффициент модели × оценка системы. Оценка системы объединяет Z показателей: Z = (значение −
          ожидаемое для возраста и пола) / разброс, в модель входит Z в пределах ±3. Ожидаемые значения — авторская
          нормализация, не клинические нормы. Мышечный и адаптационный профили в модель не входят.
        </li>
        <li>
          Нормализация Cardio проверена 12.10.2026: ожидание SCORE2 в модели ниже риска SCORE2 даже при оптимальных
          факторах, поэтому вклад Cardio завышен и растёт с возрастом. Замена — после данных целевой популяции.
        </li>
        <li>
          Мышечная ветка: сила хвата (максимум двух рук), пять вставаний и ASMI = ASM / рост², где ASM — сумма
          четырёх сегментов конечностей Visbody (туловище не входит). Мышечный возраст — тестовая модель
          0.1-synthetic: коэффициенты и возрастные ориентиры переданы владельцем без описания происхождения и
          выборки, клиническая проверка не проведена; только мужчины 20–89 лет; показывается только в режиме
          тестирования. «Возраст по LQ1» — значение из отчёта LQ One, внесённое врачом, без пересчёта. Ни мышечный
          возраст, ни возраст по LQ1 в LMB BioAge не входят: веса не утверждены. Респираторный профиль — в работе.
        </li>
        <li>Изменение оценки между визитами не означает доказанного лечебного эффекта.</li>
        <li>PhenoAge — самостоятельный показатель (Levine 2018, поправка 2019), в LMB BioAge не входит.</li>
        <li>
          FRAX — результат официального калькулятора, модель Казахстана; приложение FRAX не рассчитывает. FRAX не
          предназначен для оценки эффективности лечения.
        </li>
      </ul>
      <dl className="meta-list">
        <dt>Модель</dt>
        <dd>
          {result.model_version ?? "—"} · конфигурация {(result.model_config_sha256 ?? "").slice(0, 12) || "—"}
          {r ? ` · научный статус: ${r.scientific_status === "not_validated" ? "не валидирована" : r.scientific_status}` : ""}
        </dd>
        <dt>Расчётный модуль</dt>
        <dd>{result.engine_version ?? "—"}</dd>
        <dt>Снимок входов</dt>
        <dd className="num">{result.input_version}</dd>
      </dl>
      {extra}
    </div>
  );
}

/** Недостающие данные: первые пять видны, остальные свёрнуты. */
function MissingList({ entries, names, goTo }: { entries: [string, string[]][]; names: Record<string, string>; goTo?: GoTo }) {
  const [all, setAll] = useState(false);
  const LIMIT = 5;
  const shown = all || entries.length <= LIMIT + 1 ? entries : entries.slice(0, LIMIT);
  return (
    <>
      <ul className="gap-list">
        {shown.map(([f, by]) => (
          <li key={f}>
            <FieldLinks codes={[f]} names={names} goTo={goTo} />
            <span className="muted small"> — нужно для: {[...new Set(by)].join(", ")}</span>
          </li>
        ))}
      </ul>
      {shown.length < entries.length && (
        <button type="button" className="more-btn" onClick={() => setAll(true)}>
          Показать ещё {entries.length - shown.length}
        </button>
      )}
    </>
  );
}
