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

export const DIGITS: Record<string, number> = {
  caide: 0, egfr_ckdepi_cr_2021: 0, bmi: 1, score2: 1, score2_op: 1, frax_kz: 1, sii: 0, whtr: 3, aip: 3, tyg: 2,
  phenoage: 1,
};
export const DOMAIN_LABEL: Record<string, string> = {
  calculated: "рассчитана",
  model_not_configured: "входной индекс не активирован",
  not_included: "не входит в модель",
  missing_data: "не хватает входов",
  not_applicable: "входы неприменимы",
  invalid_input: "ошибка входных данных",
  awaiting_review: "ожидает подтверждения врача",
};
// Формулы и источники — только для раскрываемого блока «Подробнее»; расчёт — в расчётном модуле.
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
  frax_kz: "Официальный результат FRAX, модель Казахстана; локально не воспроизводится",
  asmi: "ASMI = масса мышц конечностей / рост²",
};
const Z_LABEL: Record<string, string> = {
  score2: "SCORE2", egfr: "eGFR", acr: "ACR", fib4: "FIB-4", homa_ir: "HOMA-IR", tyg: "TyG", aip: "AIP",
  whtr: "WHtR", nlr: "NLR", sii: "SII", caide: "CAIDE", frax_major: "FRAX осн.",
};
const DOMAIN_INPUTS: Record<string, string[]> = {
  cardio: ["score2"], metabolic: ["homa_ir", "tyg", "aip", "whtr"], renal: ["egfr", "acr"], hepatic: ["fib4"],
  inflammation: ["nlr", "sii"], brain: ["caide"], bone: ["frax_major"],
};

export function reasonsRu(reasons: string[], catalog: Catalog): string[] {
  const title = Object.fromEntries(catalog.branches.map((b) => [b.code, b.name]));
  return reasons.map((x) => {
    const m = /^Домен (\w+): (\w+)$/.exec(x);
    if (m) return `${title[m[1]] ?? m[1]}: ${DOMAIN_LABEL[m[2]] ?? m[2]}`;
    if (x.startsWith("Конфигурация модели неполная: target_population")) return "целевая популяция модели не утверждена";
    return x;
  });
}

/** Профиль систем: клинический статус, исследовательская карточка, графики, карточки девяти систем. */
export function ProfileView({ result, catalog, meta }: { result: EngineResult; catalog: Catalog; meta?: ReactNode }) {
  const idx = new Map(result.indices.map((i) => [i.code, i]));
  const doms = new Map(result.domains.map((d) => [d.domain, d]));
  const [research, setResearch] = useResearchMode();
  const bio = research && result.research?.status === "calculated" ? result.research : null;
  return (
    <>
      <ClinicalStatusLine result={result} catalog={catalog} />
      {result.research && <ResearchToggle on={research} onChange={setResearch} />}
      {research && result.research && <ResearchCard result={result} catalog={catalog} pheno={idx.get("phenoage")} withCheck />}

      <div className="dv-stack">
        <BranchContributions domains={result.domains} catalog={catalog} intercept={result.intercept} total={bio !== null} />
        <IndicatorDrivers domains={result.domains} catalog={catalog} />
      </div>
      {result.trajectories && <DeviationChart data={result.trajectories} />}
      {result.trajectories && <AgeGraphs data={result.trajectories} />}

      <h2 className="section-title">Системы организма</h2>
      <div className="branch-grid">
        {catalog.branches.map((b) => (
          <SystemCard key={b.code} code={b.code} name={b.name} title={b.title} indices={b.indices} idx={idx}
            domain={doms.get(b.code)} zs={result.zscores ?? {}} catalog={catalog} />
        ))}
      </div>

      <CalcDetails result={result} extra={meta} />
    </>
  );
}

/** Клинический итог — компактной строкой; число не выводится, пока модель клинически не утверждена. */
export function ClinicalStatusLine({ result, catalog }: { result: EngineResult; catalog: Catalog }) {
  const ok = result.status === "calculated" && result.bioage_years !== null;
  const why = reasonsRu(result.blocking_reasons, catalog);
  return (
    <div className="status-line" role="status">
      <span className="label">Клинический итог LMB BioAge:</span>
      {ok ? (
        <span className="num strong">{fmt(result.bioage_years, 1)}</span>
      ) : (
        <>
          <span className="badge tone-na">
            <span aria-hidden="true">⊘</span> не рассчитан
          </span>
          {why.length > 0 && <span className="why">{why.join("; ")}</span>}
        </>
      )}
    </div>
  );
}

/** Исследовательский результат: календарный возраст, расчётная оценка, разница, ограничения, контроль PhenoAge. */
export function ResearchCard({ result, catalog, pheno, withCheck = false }: {
  result: EngineResult;
  catalog: Catalog;
  pheno?: IndexRes;
  withCheck?: boolean;
}) {
  const r = result.research!;
  const age = result.age_years ?? null;
  const ok = r.status === "calculated" && r.bioage_years !== null && r.delta_years !== null;
  const reasons = reasonsRu(r.reasons, catalog);
  const phenoOk = pheno && pheno.status === "calculated" && pheno.value !== null;
  const d = r.delta_years ?? 0;
  return (
    <section className="research-card" aria-labelledby="research-title">
      <header className="research-head">
        <h2 id="research-title">Исследовательский расчёт LMB BioAge</h2>
        <span className="research-chip">
          <span aria-hidden="true">◆</span> Исследовательский статус · не валидирован
        </span>
      </header>
      <div className="figures">
        <div className="figure">
          <span className="eyebrow">Календарный возраст</span>
          <span className="figure-value secondary">{age ?? "—"}</span>
          <span className="figure-note">лет на дату обследования</span>
        </div>
        <div className="figure">
          <span className="eyebrow">Расчётная оценка</span>
          {ok ? <span className="figure-value bio-value">{fmt(r.bioage_years, 1)}</span> : <span className="figure-value empty">не рассчитана</span>}
          <span className="figure-note">лет, модель LMB BioAge</span>
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
      {!ok && reasons.length > 0 && (
        <div className="why-block">
          <p className="strong" style={{ margin: "20px 0 0" }}>Почему не рассчитана:</p>
          <ul className="reason-list">
            {reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="limits" role="note">
        {r.limitations.length > 0
          ? r.limitations.join(" ")
          : "Исследовательская модель. Клиническая валидация не проведена."}{" "}
        Изменение оценки не означает доказанного лечебного эффекта.
      </p>
      {pheno && (
        <div className="control-row pheno">
          <span className="eyebrow">Контроль · PhenoAge (Levine 2018)</span>
          {phenoOk ? (
            <>
              <span className="control-value num">{fmt(pheno.value, 1)} лет</span>
              {ok && <span className="muted">LMB − PhenoAge: <b className="num">{signed(r.bioage_years! - pheno.value!, 1)}</b></span>}
            </>
          ) : (
            <span className="muted">
              не рассчитан
              {pheno.missing_fields.length > 0
                ? " — нужны альбумин, вч-СРБ, лейкоциты, MCV, RDW и щелочная фосфатаза"
                : pheno.reasons[0]
                  ? ` — ${pheno.reasons[0]}`
                  : ""}
            </span>
          )}
        </div>
      )}
      {withCheck && r.cardio_anchor_experiment && (
        <CardioCheck x={r.cardio_anchor_experiment} result={result} pheno={phenoOk ? pheno!.value! : null} />
      )}
    </section>
  );
}

/** Проверочный расчёт Cardio рядом с исходным (задание владельца 11.10.2026). В отчёт не входит. */
function CardioCheck({ x, result, pheno }: { x: CardioAnchor; result: EngineResult; pheno: number | null }) {
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
    <div className="cardio-check no-print">
      <label className="research-toggle small-toggle">
        <span className="switch">
          <input type="checkbox" role="switch" checked={on} onChange={(e) => setOn(e.target.checked)}
            aria-label="Проверочный расчёт Cardio" />
          <span />
        </span>
        Проверочный расчёт Cardio (условный контрольный профиль)
      </label>
      {on && (
        <div className="check-body" aria-label={x.label}>
          <h3>{x.label}</h3>
          <p className="limits check-note" role="note">
            {x.disclaimer}. Ожидание Cardio заменено SCORE2 High контрольного профиля того же пола и возраста
            (САД {x.control_profile.sbp_mmhg}, общий холестерин {fmt(x.control_profile.tc_mmol_l, 1)}, ЛПВП{" "}
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
              {row("Ожидание / контрольный риск", pct(expected), pct(x.control_score2_pct))}
              {row("Нормированная оценка Cardio", num(z?.z_clipped ?? null), num(x.z_clipped))}
              {row("Вклад Cardio, лет", num(r.contributions?.cardio ?? null), num(x.contribution))}
              {row("LMB BioAge, лет", r.bioage_years == null ? "—" : fx(r.bioage_years, 2), x.bioage_years == null ? "—" : fx(x.bioage_years, 2))}
              {pheno != null && row("Разница с PhenoAge, лет", r.bioage_years == null ? "—" : sg(r.bioage_years - pheno, 2),
                x.bioage_years == null ? "—" : sg(x.bioage_years - pheno, 2))}
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
  code: string; name: string; title: string; indices: string[]; idx: Map<string, IndexRes>; domain?: DomainRes;
  zs: Record<string, ZRes>; catalog: Catalog;
}) {
  const { code, name, title, indices, idx, domain: d, zs, catalog } = props;
  return (
    <article className="branch" aria-label={name}>
      <header>
        <h3>{name}</h3>
        <span className="branch-code">{title}</span>
      </header>
      {indices.length === 0 && <p className="index-expl">Ввод показателей LQ One — следующая очередь (сопоставление полей готово).</p>}
      {indices.map((c) => (
        <IndexBlock key={c} code={c} res={idx.get(c)} catalog={catalog} />
      ))}
      <footer className="domain-line">
        <span title="Оценка системы — значение Z после правила объединения; безразмерная, не годы">Оценка системы</span>
        <span className={d?.status === "calculated" ? "num strong" : "muted"}>
          {d?.status === "calculated" ? fmt(d.score, 2) : DOMAIN_LABEL[d?.status ?? ""] ?? d?.status}
        </span>
      </footer>
      {d && (DOMAIN_INPUTS[code] ?? []).some((c) => c in zs) && (
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

function IndexBlock({ code, res, catalog }: { code: string; res: IndexRes | undefined; catalog: Catalog }) {
  const label = catalog.index_labels[code];
  if (!res) return null;
  const names: Record<string, string> = { birth_date: "дата рождения", sex_at_birth: "пол", frax_result: "результат FRAX" };
  catalog.observation_groups.forEach((g) => g.items.forEach((x) => (names[x.code] = x.name_ru)));
  catalog.questionnaire_groups.forEach((g) => g.items.forEach((q) => (names[q.code] = q.name)));
  const unit = unitRu(res.unit);
  const show = res.value !== null && (res.status === "calculated" || res.status === "not_applicable" || res.status === "awaiting_review");
  const extra = details(code, res);
  return (
    <div className="index-line">
      <div className="index-name">
        <strong>{label?.short ?? code}</strong>
        <StatusBadge status={res.status} />
      </div>
      <span className={show ? "index-val num" : "index-val empty"}>
        {show ? fmt(res.value, DIGITS[code] ?? 2) : "—"}
        {show && unit && <span className="unit">{unit}</span>}
      </span>
      <span className="index-expl">{label?.name}</span>
      {(res.reasons.length > 0 || res.warnings.length > 0 || res.missing_fields.length > 0) && (
        <ul className="notes">
          {res.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
          {res.warnings.map((r) => (
            <li key={r} className="warn">
              {r}
            </li>
          ))}
          {res.missing_fields.length > 0 && <li>не хватает: {res.missing_fields.map((f) => names[f] ?? f).join(", ")}</li>}
        </ul>
      )}
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

function details(code: string, res: IndexRes): string[] {
  const out: string[] = [];
  if (res.status !== "calculated") return out;
  const e = res.extra as Record<string, unknown>;
  if (code === "frax_kz")
    out.push(`перелом бедра: ${fmt(e.hip_10y_pct as number, 1)} % · ${e.with_bmd ? "с МПК" : "без МПК"} · ${e.source === "manual" ? "ручной ввод врача" : "автоматически"}`);
  if (code === "acr" && e.acr_mg_g !== undefined) out.push(`${fmt(e.acr_mg_g as number, 1)} мг/г`);
  if (code === "caide" && e.age_band) {
    const b = e.age_band as { label: string; points: number };
    out.push(`возрастная категория: ${b.label} (${b.points} балла). Балл возраста меняется ступенчато в 47 и 54 года — при сравнении визитов через эти границы оценка Brain меняется без изменения здоровья.`);
  }
  if (code === "score2" || code === "score2_op")
    out.push("Категорию сердечно-сосудистого риска определяет сам SCORE2, а не Z модели LMB.");
  return out;
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
