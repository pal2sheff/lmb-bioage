import { fmt } from "../api";
import type { Catalog, DomainRes, IndexRes, Run, ZRes } from "../types";
import { StatusBadge } from "./ui";
import { BranchContributions, DeviationChart, IndicatorDrivers, signed } from "./Charts";
import { TestModeToggle, useTestMode } from "./TestMode";
import { unitRu } from "../units";

/** Результат расчётного модуля (pipeline.run) — одинаковый у сервера и браузерного калькулятора. */
export type EngineResult = Run["result"] & {
  status: "calculated" | "blocked";
  bioage_years: number | null;
  delta_years: number | null;
};

const DIGITS: Record<string, number> = { caide: 0, egfr_ckdepi_cr_2021: 0, bmi: 1, score2: 1, score2_op: 1, frax_kz: 1, sii: 0, whtr: 3, aip: 3, tyg: 2 };
const DOMAIN_LABEL: Record<string, string> = {
  calculated: "доменная оценка рассчитана",
  model_not_configured: "входной индекс не активирован",
  not_included: "не входит в модель",
  missing_data: "не хватает входов",
  not_applicable: "входы неприменимы",
  invalid_input: "ошибка входных данных",
  awaiting_review: "ожидает подтверждения врача",
};
// подписи Z-оценок (коды нормализации из конфигурации модели)
const Z_LABEL: Record<string, string> = {
  score2: "SCORE2", egfr: "eGFR", acr: "ACR", fib4: "FIB-4", homa_ir: "HOMA-IR", tyg: "TyG", aip: "AIP",
  whtr: "WHtR", nlr: "NLR", sii: "SII", caide: "CAIDE", frax_major: "FRAX осн.",
};

/** Профиль девяти веток: итог (или причины блокировки), индексы, доменные оценки и Z-оценки. */
export function ProfileView({ result, catalog }: { result: EngineResult; catalog: Catalog }) {
  const idx = new Map(result.indices.map((i) => [i.code, i]));
  const names: Record<string, string> = { birth_date: "дата рождения", sex_at_birth: "пол", frax_result: "результат FRAX" };
  catalog.observation_groups.forEach((g) => g.items.forEach((d) => (names[d.code] = d.name_ru)));
  catalog.questionnaire_groups.forEach((g) => g.items.forEach((q) => (names[q.code] = q.name)));
  const doms = new Map(result.domains.map((d) => [d.domain, d]));
  const [testMode, setTestMode] = useTestMode();
  const bio = result.research?.status === "calculated" ? result.research : null;
  return (
    <>
      <Integral result={result} catalog={catalog} pheno={testMode ? idx.get("phenoage") : undefined} />
      <TestModeToggle on={testMode} onChange={setTestMode} />
      <div className="dv-stack">
        <BranchContributions
          domains={result.domains}
          catalog={catalog}
          intercept={result.intercept}
          total={bio !== null}
        />
        <IndicatorDrivers domains={result.domains} catalog={catalog} />
      </div>
      {result.trajectories && <DeviationChart data={result.trajectories} />}
      <h3 className="section-title">Системы организма и показатели</h3>
      <div className="branch-grid">
        {catalog.branches.map((b, n) => {
          const d = doms.get(b.code);
          return (
            <article key={b.code} className="branch" style={{ animationDelay: `${n * 40}ms` }}>
              <header>
                <span className="branch-no">{String(n + 1).padStart(2, "0")}</span>
                <div>
                  <h3>{b.title}</h3>
                  <p>{b.name}</p>
                </div>
              </header>
              {b.indices.length === 0 && (
                <p className="muted small">Ввод показателей LQ One (сопоставление полей готово) — следующая очередь.</p>
              )}
              {b.indices.map((code) => (
                <IndexLine key={code} code={code} res={idx.get(code)} />
              ))}
              <footer className="domain-line">
                <span title="Доменная оценка — значение Z после правила объединения ветки; безразмерная, не годы">
                  Домен
                </span>
                <span className={d?.status === "calculated" ? "num strong" : "muted"}>
                  {d?.status === "calculated" ? fmt(d.score, 2) : DOMAIN_LABEL[d?.status ?? ""] ?? d?.status}
                </span>
              </footer>
              {d && <ZLine domain={d} zs={result.zscores ?? {}} />}
            </article>
          );
        })}
      </div>
    </>
  );

  function IndexLine({ code, res }: { code: string; res: IndexRes | undefined }) {
    const label = catalog.index_labels[code];
    if (!res) return null;
    const unit = unitRu(res.unit);
    const show = res.value !== null && (res.status === "calculated" || res.status === "not_applicable" || res.status === "awaiting_review");
    return (
      <div className="index-line">
        <div className="index-head">
          <span title={label?.name}>
            <strong>{label?.short ?? code}</strong> <span className="muted small">{label?.name}</span>
          </span>
          <span className="num index-val">
            {show ? (
              <>
                {fmt(res.value, DIGITS[code] ?? 2)}
                {unit && <span className="unit"> {unit}</span>}
              </>
            ) : (
              "—"
            )}
          </span>
        </div>
        {code === "frax_kz" && res.status === "calculated" && (
          <p className="small">
            перелом бедра: <span className="num">{fmt(res.extra.hip_10y_pct as number, 1)} %</span> ·{" "}
            {res.extra.with_bmd ? "с МПК" : "без МПК"} · {res.extra.source === "manual" ? "ручной ввод" : "автоматически"}
          </p>
        )}
        {code === "caide" && res.status === "calculated" && res.extra.age_band ? (
          <p className="small">
            возрастная категория CAIDE: {(res.extra.age_band as { label: string }).label} (
            {(res.extra.age_band as { points: number }).points} балла) · балл возраста меняется ступенчато в 47 и 54
            года — при сравнении визитов через эти границы Brain меняется без изменения здоровья
          </p>
        ) : null}
        {(code === "score2" || code === "score2_op") && res.status === "calculated" && (
          <p className="small">
            категория сердечно-сосудистого риска определяется по самому {code === "score2" ? "SCORE2" : "SCORE2-OP"}{" "}
            (регион high), а не по Z LMB
          </p>
        )}
        {code === "acr" && res.status === "calculated" && (
          <p className="small">
            <span className="num">{fmt(res.extra.acr_mg_g as number, 1)}</span> мг/г
          </p>
        )}
        <StatusBadge status={res.status} />
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
      </div>
    );
  }
}

function ZLine({ domain, zs }: { domain: DomainRes; zs: Record<string, ZRes> }) {
  // Z-оценки входов домена: исходное Z_raw; если оно ограничено ±3, это видно
  const codes = (DOMAIN_INPUTS[domain.domain] ?? []).filter((c) => c in zs);
  if (codes.length === 0) return null;
  return (
    <p className="z-line small">
      {codes.map((c, i) => {
        const z = zs[c];
        return (
          <span key={c}>
            {i > 0 && " · "}
            {c === "score2" ? (
              <span title="Отклонение SCORE2 от авторского ожидания модели; не категория риска">
                Z SCORE2 от авторского ожидания
              </span>
            ) : (
              <>Z {Z_LABEL[c] ?? c}</>
            )}{" "}
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
    </p>
  );
}

const DOMAIN_INPUTS: Record<string, string[]> = {
  cardio: ["score2"], metabolic: ["homa_ir", "tyg", "aip", "whtr"], renal: ["egfr", "acr"], hepatic: ["fib4"],
  inflammation: ["nlr", "sii"], brain: ["caide"], bone: ["frax_major"],
};

function Integral({ result, catalog, pheno }: { result: EngineResult; catalog: Catalog; pheno?: IndexRes }) {
  const r = result.research;
  const age = result.age_years ?? null;
  const ok = r?.status === "calculated" && r.bioage_years !== null && r.delta_years !== null;
  const title = Object.fromEntries(catalog.branches.map((b) => [b.code, b.title]));
  const reasons = (r?.reasons ?? result.blocking_reasons).map((x) => {
    const m = /^Домен (\w+): (\w+)$/.exec(x);
    return m ? `${title[m[1]] ?? m[1]}: ${DOMAIN_LABEL[m[2]] ?? m[2]}` : x;
  });
  const phenoOk = pheno && pheno.status === "calculated" && pheno.value !== null;
  return (
    <section className={ok ? "integral" : "integral blocked"} aria-label="LMB BioAge">
      <div className="ages">
        <div className="age-cell">
          <span className="eyebrow">Паспортный возраст</span>
          <span className="age-value num">{age ?? "—"}</span>
          <span className="age-unit">лет</span>
        </div>
        <div className="age-cell bio">
          <span className="eyebrow">Биологический возраст · LMB BioAge</span>
          {ok ? (
            <>
              <span className="age-value num">{fmt(r!.bioage_years, 1)}</span>
              <span className={`age-delta ${r!.delta_years! > 0 ? "up" : "down"}`}>
                {signed(r!.delta_years!, 1)} {r!.delta_years! > 0 ? "старше паспортного" : "моложе паспортного"}
              </span>
            </>
          ) : (
            <span className="age-value muted-value">не рассчитан</span>
          )}
        </div>
        {pheno && (
          <div className="age-cell pheno">
            <span className="eyebrow">PhenoAge · контроль</span>
            {phenoOk ? (
              <>
                <span className="age-value num">{fmt(pheno.value, 1)}</span>
                <span className="age-delta">
                  {ok ? <>LMB − PhenoAge: {signed(r!.bioage_years! - pheno.value!, 1)}</> : <>к паспортному: {signed(pheno.value! - (age ?? 0), 1)}</>}
                </span>
              </>
            ) : (
              <span className="age-note">
                не рассчитан{pheno.missing_fields.length > 0 ? " — нужны альбумин, вч-СРБ, лейкоциты, MCV, RDW, щелочная фосфатаза" : pheno.reasons[0] ? ` — ${pheno.reasons[0]}` : ""}
              </span>
            )}
          </div>
        )}
      </div>
      {!ok && reasons.length > 0 && (
        <details className="integral-why">
          <summary>Почему не рассчитан ({reasons.length})</summary>
          <ul className="notes">
            {reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
