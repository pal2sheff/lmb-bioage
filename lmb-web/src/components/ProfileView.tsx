import type { ReactNode } from "react";
import { fmt } from "../api";
import type { CardioAnchor, Catalog, DomainRes, IndexRes, Run, ZRes } from "../types";
import { unitRu } from "../units";
import { AgeGraphs, BranchContributions, DeviationChart, IndicatorDrivers, signed } from "./Charts";
import { ResearchToggle, useCardioCheck, useResearchMode } from "./TestMode";
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
  phenoage: 1,
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
  asmi: "ASMI = масса мышц конечностей / рост²",
  phenoage: "Levine 2018 (поправка PLoS Med 2019): альбумин, креатинин, глюкоза, вч-СРБ, лимфоциты %, MCV, RDW, ЩФ, лейкоциты, возраст",
};
const Z_LABEL: Record<string, string> = {
  score2: "SCORE2", egfr: "eGFR", acr: "ACR", fib4: "FIB-4", homa_ir: "HOMA-IR", tyg: "TyG", aip: "AIP",
  whtr: "WHtR", nlr: "NLR", sii: "SII", caide: "CAIDE", frax_major: "FRAX осн.",
};
const DOMAIN_INPUTS: Record<string, string[]> = {
  cardio: ["score2"], metabolic: ["homa_ir", "tyg", "aip", "whtr"], renal: ["egfr", "acr"], hepatic: ["fib4"],
  inflammation: ["nlr", "sii"], brain: ["caide"], bone: ["frax_major"],
};
/** Модули оборудования без подключённого ввода — показываются свёрнутыми. */
const EXTRA_BRANCHES = ["muscle", "adaptive"];

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

/** Результаты: возрастные показатели → клинические индексы → ограничения и пропуски → доп. разделы → исследовательский раздел. */
export function ProfileView({ result, catalog, meta, goTo }: { result: EngineResult; catalog: Catalog; meta?: ReactNode; goTo?: GoTo }) {
  const idx = new Map(result.indices.map((i) => [i.code, i]));
  const doms = new Map(result.domains.map((d) => [d.domain, d]));
  const [research, setResearch] = useResearchMode();
  const names = fieldNames(catalog);
  const bio = research && result.research?.status === "calculated" ? result.research : null;
  const main = catalog.branches.filter((b) => !EXTRA_BRANCHES.includes(b.code));
  const extra = catalog.branches.filter((b) => EXTRA_BRANCHES.includes(b.code));
  return (
    <>
      <h2 className="section-title">Возрастные показатели</h2>
      <div className="age-grid">
        <PhenoAgeCard res={idx.get("phenoage")} names={names} goTo={goTo} />
        <LmbCard result={result} catalog={catalog} research={research} setResearch={setResearch} />
      </div>

      <h2 className="section-title">Клинические индексы</h2>
      <div className="branch-grid">
        {main.map((b) => (
          <SystemCard key={b.code} code={b.code} name={b.name} indices={b.indices} idx={idx} domain={doms.get(b.code)}
            zs={result.zscores ?? {}} catalog={catalog} research={research} names={names} goTo={goTo} />
        ))}
      </div>

      <GapsCard result={result} catalog={catalog} names={names} goTo={goTo} />

      <details className="more details-card extra-branches">
        <summary>Дополнительные разделы: мышечный и адаптационный профили (оборудование не подключено)</summary>
        <div className="branch-grid">
          {extra.map((b) => (
            <SystemCard key={b.code} code={b.code} name={b.name} indices={b.indices} idx={idx} domain={doms.get(b.code)}
              zs={result.zscores ?? {}} catalog={catalog} research={false} names={names} goTo={goTo} />
          ))}
        </div>
      </details>

      {research && (
        <details className="research-section" open>
          <summary>Исследовательский раздел LMB BioAge</summary>
          <p className="limits" role="note">
            Исследовательская модель, клиническая валидация не проведена. Вклады, отклонения и графики описывают
            авторскую модель, а не клинические нормы.
          </p>
          <div className="dv-stack">
            <BranchContributions domains={result.domains} catalog={catalog} intercept={result.intercept} total={bio !== null} />
            <IndicatorDrivers domains={result.domains} catalog={catalog} />
          </div>
          {result.trajectories && <DeviationChart data={result.trajectories} />}
          {result.trajectories && <AgeGraphs data={result.trajectories} />}
          {result.research?.cardio_anchor_experiment && <CardioCheck x={result.research.cardio_anchor_experiment} result={result} />}
        </details>
      )}

      <CalcDetails result={result} extra={meta} />
    </>
  );
}

/** PhenoAge — самостоятельный показатель: свой статус, не зависит от LMB и исследовательского режима. */
export function PhenoAgeCard({ res, names, goTo }: { res?: IndexRes; names: Record<string, string>; goTo?: GoTo }) {
  if (!res) return null;
  const ok = res.status === "calculated" && res.value !== null;
  return (
    <section className="age-card" aria-labelledby="pheno-title">
      <header className="age-card-head">
        <h3 id="pheno-title">PhenoAge</h3>
        {!ok && <StatusBadge status={res.status} />}
      </header>
      <p className="age-card-sub">Фенотипический возраст (Levine 2018) по биохимии и общему анализу крови</p>
      {ok ? (
        <p className="age-card-value">
          <span className="figure-value num">{fmt(res.value, 1)}</span> <span className="figure-unit">лет</span>
        </p>
      ) : (
        <p className="age-card-value"><span className="figure-value empty">не рассчитан</span></p>
      )}
      <IndexNotes res={res} names={names} goTo={goTo} />
    </section>
  );
}

/** LMB BioAge: клинический статус и (в исследовательском режиме) исследовательская оценка. */
function LmbCard({ result, catalog, research, setResearch }: {
  result: EngineResult; catalog: Catalog; research: boolean; setResearch: (v: boolean) => void;
}) {
  const r = result.research;
  const age = result.age_years ?? null;
  const ok = !!r && r.status === "calculated" && r.bioage_years !== null && r.delta_years !== null;
  const d = r?.delta_years ?? 0;
  const why = reasonsRu(result.blocking_reasons, catalog);
  return (
    <section className={research ? "age-card research-card" : "age-card"} aria-labelledby="research-title">
      <header className="age-card-head">
        <h3 id="research-title">LMB BioAge</h3>
        <span className="research-chip">
          <span aria-hidden="true">◆</span> Исследовательский статус · не валидирован
        </span>
      </header>
      <p className="age-card-sub">
        Клинический итог не рассчитан{why.length ? `: ${why.join("; ")}` : ""}.
      </p>
      {r && <ResearchToggle on={research} onChange={setResearch} />}
      {research && r ? (
        <>
          <div className="figures">
            <div className="figure">
              <span className="eyebrow">Календарный возраст</span>
              <span className="figure-value secondary">{age ?? "—"}</span>
              <span className="figure-note">лет на дату обследования</span>
            </div>
            <div className="figure">
              <span className="eyebrow">Расчётная оценка</span>
              {ok ? <span className="figure-value bio-value">{fmt(r.bioage_years, 1)}</span> : <span className="figure-value empty">не рассчитана</span>}
              <span className="figure-note">лет, исследовательская модель</span>
            </div>
            <div className="figure">
              <span className="eyebrow">Разница</span>
              {ok ? (
                <>
                  <span className="figure-value secondary">{signed(d, 1)}</span>
                  <span className={`delta ${d > 0 ? "up" : d < 0 ? "down" : ""}`}>
                    {d > 0 ? "выше календарного" : d < 0 ? "ниже календарного" : "равна календарному"}
                  </span>
                </>
              ) : (
                <span className="figure-value empty">—</span>
              )}
            </div>
          </div>
          {!ok && r.reasons.length > 0 && (
            <div className="why-block">
              <p className="strong" style={{ margin: "16px 0 0" }}>Почему не рассчитана:</p>
              <ul className="reason-list">
                {reasonsRu(r.reasons, catalog).map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              <p className="muted small">Какие данные нужны — в разделе «Ограничения и недостающие данные».</p>
            </div>
          )}
          <p className="limits" role="note">
            {r.limitations.length > 0 ? r.limitations.join(" ") : "Исследовательская модель. Клиническая валидация не проведена."}{" "}
            Изменение оценки не означает доказанного лечебного эффекта.
          </p>
        </>
      ) : (
        <p className="muted small">Исследовательский режим выключен: оценка модели и исследовательский раздел скрыты.</p>
      )}
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
  code: string; name: string; indices: string[]; idx: Map<string, IndexRes>; domain?: DomainRes;
  zs: Record<string, ZRes>; catalog: Catalog; research: boolean; names: Record<string, string>; goTo?: GoTo;
}) {
  const { code, name, indices, idx, domain: d, zs, catalog, research, names, goTo } = props;
  return (
    <article className="branch" aria-label={name}>
      <header>
        <h3>{name}</h3>
      </header>
      {indices.length === 0 && <p className="index-expl">Ввод показателей LQ One — следующая очередь (сопоставление полей готово).</p>}
      {indices.map((c) => (
        <IndexBlock key={c} code={c} res={idx.get(c)} catalog={catalog} names={names} goTo={goTo} />
      ))}
      {research && d && d.status !== "not_included" && (
        <footer className="domain-line">
          <span title="Оценка системы в модели LMB — безразмерная, не годы">Оценка системы (модель LMB)</span>
          <span className={d.status === "calculated" ? "num strong" : "muted"}>
            {d.status === "calculated" ? fmt(d.score, 2) : DOMAIN_LABEL[d.status] ?? d.status}
          </span>
        </footer>
      )}
      {research && d && (DOMAIN_INPUTS[code] ?? []).some((c) => c in zs) && (
        <details className="more">
          <summary>Подробнее об оценке</summary>
          <div className="more-body">
            <ZLine domain={d} zs={zs} />
            {d.coefficient !== null && (
              <span>
                коэффициент модели {fmt(d.coefficient, 1)}
                {d.contribution !== null && <> · вклад {signed(d.contribution, 2)}</>}
              </span>
            )}
          </div>
        </details>
      )}
    </article>
  );
}

/** Причины, предупреждения и недостающие поля индекса — только фактические, с переходом к полю. */
function IndexNotes({ res, names, goTo }: { res: IndexRes; names: Record<string, string>; goTo?: GoTo }) {
  const bad = (res.invalid_fields ?? []).filter((f) => !res.missing_fields.includes(f));
  if (res.reasons.length === 0 && res.warnings.length === 0 && res.missing_fields.length === 0) return null;
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

function IndexBlock({ code, res, catalog, names, goTo }: {
  code: string; res: IndexRes | undefined; catalog: Catalog; names: Record<string, string>; goTo?: GoTo;
}) {
  const label = catalog.index_labels[code];
  if (!res) return null;
  const unit = unitRu(res.unit);
  const show = res.value !== null && res.status === "calculated";
  const e = res.extra as Record<string, unknown>;
  const extra = details(code, res);
  return (
    <div className="index-line">
      <div className="index-name">
        <strong>{label?.short ?? code}</strong>
        {res.status !== "calculated" && <StatusBadge status={res.status} />}
      </div>
      {code === "frax_kz" && show ? (
        <div className="frax-pair">
          <span className="index-val num">
            {fmt(res.value, 1)}<span className="unit">%</span>
          </span>
          <span className="index-expl">основные остеопоротические переломы, 10 лет</span>
          <span className="index-val num">
            {fmt(e.hip_10y_pct as number, 1)}<span className="unit">%</span>
          </span>
          <span className="index-expl">перелом бедра, 10 лет</span>
          <span className="index-expl strong-note">
            Перенесено из официального калькулятора FRAX (модель Казахстана, {e.with_bmd ? "с МПК" : "без МПК"})
          </span>
        </div>
      ) : (
        <>
          <span className={show ? "index-val num" : "index-val empty"}>
            {show ? fmt(res.value, DIGITS[code] ?? 2) : "—"}
            {show && unit && <span className="unit">{unit}</span>}
          </span>
          <span className="index-expl">{label?.name}</span>
        </>
      )}
      {code === "acr" && <AcrSource res={res} />}
      <IndexNotes res={res} names={names} goTo={goTo} />
      {(FORMULA[code] || extra.length > 0) && (
        <details className="more">
          <summary>Подробнее</summary>
          <div className="more-body">
            {FORMULA[code] && <span className="formula">{FORMULA[code]}</span>}
            {extra.map((x) => (
              <span key={x}>{x}</span>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

const ACR_SOURCE_RU: Record<string, string> = { lab: "готовый ACR лаборатории", calculated: "расчёт по альбумину и креатинину мочи" };

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
  const skip = new Set(["asmi"]);   // модуль оборудования не подключён — в доп. разделах
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
    if (i.status === "not_applicable") i.reasons.forEach((r) => limits.push(`${label(i.code)}: ${r}`));
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
          <ul className="gap-list">
            {[...missing.entries()].map(([f, by]) => (
              <li key={f}>
                <FieldLinks codes={[f]} names={names} goTo={goTo} />
                <span className="muted small"> — нужно для: {[...new Set(by)].join(", ")}</span>
              </li>
            ))}
          </ul>
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

function ZLine({ domain, zs }: { domain: DomainRes; zs: Record<string, ZRes> }) {
  const codes = (DOMAIN_INPUTS[domain.domain] ?? []).filter((c) => c in zs);
  return (
    <span className="z-line">
      {codes.map((c, i) => {
        const z = zs[c];
        return (
          <span key={c}>
            {i > 0 && " · "}
            Z {Z_LABEL[c] ?? c}
            {c === "score2" ? " (от авторского ожидания)" : ""}{" "}
            {z.z_raw === null ? (
              <span className="muted">—</span>
            ) : (
              <span className="num">
                {fmt(z.z_raw, 2)}
                {z.z_clipped !== z.z_raw && <span className="muted"> → {fmt(z.z_clipped, 0)}</span>}
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}

/** Технические метаданные расчёта — раскрываются по запросу. */
export function CalcDetails({ result, extra, open }: { result: EngineResult; extra?: ReactNode; open?: boolean }) {
  const r = result.research;
  return (
    <details className="more details-card" open={open}>
      <summary>Подробности расчёта</summary>
      <dl className="meta-list">
        <dt>Модель</dt>
        <dd>
          {result.model_version ?? "—"} · конфигурация {(result.model_config_sha256 ?? "").slice(0, 12) || "—"}
        </dd>
        <dt>Расчётный модуль</dt>
        <dd>{result.engine_version ?? "—"}</dd>
        <dt>Снимок входов</dt>
        <dd className="num">{result.input_version}</dd>
        {r && (
          <>
            <dt>Исследовательский режим</dt>
            <dd>
              {r.mode ?? "—"} · научный статус: {r.scientific_status === "not_validated" ? "не валидирована" : r.scientific_status}
              {r.research_population ? ` · техническая область ${r.research_population.age_min}–${r.research_population.age_max} лет` : ""}
            </dd>
          </>
        )}
        <dt>Постоянная модели</dt>
        <dd className="num">{signed(result.intercept, 2)}</dd>
      </dl>
      {extra}
    </details>
  );
}
