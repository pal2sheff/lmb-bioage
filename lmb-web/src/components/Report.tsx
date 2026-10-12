// Отчёт врача для печати: те же данные расчётного модуля, сведённые в таблицы.
// PhenoAge — самостоятельный показатель; сравнения с LMB в отчёте нет (решение владельца 11.10.2026).
// Методические пояснения — одним компактным блоком в конце (уточнение 11.10.2026, 21:24).
// Аудит 12.10.2026: диаграмма вкладов; клинические индексы и безразмерные оценки систем — в разных частях.
import { fmt } from "../api";
import type { Catalog, IndexRes } from "../types";
import { unitRu } from "../units";
import { BranchContributions, signed } from "./Charts";
import { AcrSource, DIGITS, DOMAIN_LABEL, type EngineResult, Methodology, reasonsRu } from "./ProfileView";
import { useResearchMode } from "./TestMode";
import { Button, StatusBadge } from "./ui";

const MODEL_DOMAINS = ["cardio", "metabolic", "renal", "hepatic", "inflammation", "brain", "bone"];

export function Report(props: {
  result: EngineResult;
  catalog: Catalog;
  facts: { label: string; value: string }[];
  onBack?: () => void;
}) {
  const { result, catalog, facts, onBack } = props;
  const [research] = useResearchMode();
  const idx = new Map(result.indices.map((i) => [i.code, i]));
  const doms = new Map(result.domains.map((d) => [d.domain, d]));
  const r = result.research;
  const rOk = research && r?.status === "calculated" && r.bioage_years !== null;
  const pheno = idx.get("phenoage");
  const lmbNote = !research ? "расчёт выключен" : rOk ? "" : r ? `не рассчитан${r.reasons.length ? `: ${reasonsRu(r.reasons, catalog).slice(0, 2).join("; ")}` : ""}` : "";
  return (
    <article className="report">
      <div className="toolbar no-print">
        <p className="muted">Отчёт формируется из текущих данных. Перед печатью проверьте разделы «Данные» и «Анкета».</p>
        <div className="row">
          {onBack && <Button onClick={onBack}>К результатам</Button>}
          <Button kind="primary" onClick={() => window.print()}>
            Печать отчёта
          </Button>
        </div>
      </div>
      <header className="report-head card">
        <div>
          <span className="eyebrow">Отчёт врача</span>
          <h1>LMB BioAge — результаты обследования</h1>
        </div>
        <dl className="report-facts">
          {facts.map((f) => (
            <div key={f.label}>
              <dt>{f.label}</dt>
              <dd className="num">{f.value}</dd>
            </div>
          ))}
        </dl>
      </header>

      <section className="card report-section">
        <h2>Возрастные показатели</h2>
        <table className="report-table compact">
          <tbody>
            <tr>
              <td><strong>Календарный возраст</strong></td>
              <td className="r num">{result.age_years ?? "—"} лет</td>
              <td />
            </tr>
            <tr>
              <td><strong>LMB BioAge</strong> <span className="muted small">расчётная оценка</span></td>
              <td className="r num">{rOk ? `${fmt(r.bioage_years, 1)} лет` : "—"}</td>
              <td className="small">{rOk ? `разница с календарным ${signed(r.delta_years!, 1)} лет` : lmbNote}</td>
            </tr>
            <tr>
              <td><strong>PhenoAge</strong> <span className="muted small">фенотипический возраст</span></td>
              <td className="r num">{pheno?.status === "calculated" ? `${fmt(pheno.value, 1)} лет` : "—"}</td>
              <td>{pheno && pheno.status !== "calculated" ? <StatusBadge status={pheno.status} /> : null}</td>
            </tr>
            {[["muscle_age", "Мышечный возраст", "модель 0.1-synthetic"], ["lqone_bioage", "Возраст по LQ1", "из отчёта LQ One"]].map(([code, title, sub]) => {
              const x = idx.get(code);
              if (!x || x.status === "missing_data") return null;
              const d = (x.extra as { delta_years?: number | null }).delta_years;
              return (
                <tr key={code}>
                  <td><strong>{title}</strong> <span className="muted small">{sub}</span></td>
                  <td className="r num">{x.status === "calculated" ? `${fmt(x.value, 1)} лет` : "—"}</td>
                  <td className="small">
                    {x.status === "calculated"
                      ? [d != null ? `разница с календарным ${signed(d, 1)} лет` : null, code === "lqone_bioage" ? lqMeta(x) : null].filter(Boolean).join(" · ")
                      : <StatusBadge status={x.status} />}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="card report-section">
        <h2>Клинические индексы и показатели</h2>
        <div className="table-wrap">
          <table className="report-table">
            <thead>
              <tr>
                <th>Система</th>
                <th>Показатель</th>
                <th className="r">Значение</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {catalog.branches.map((b) => {
                const rows = b.indices.length ? b.indices : [""];
                return rows.map((code, i) => {
                  const res = code ? idx.get(code) : undefined;
                  const label = code ? catalog.index_labels[code] : undefined;
                  return (
                    <tr key={b.code + code} className={i === 0 ? "group-start" : ""}>
                      {i === 0 && (
                        <td rowSpan={rows.length}>
                          <strong>{b.name}</strong>
                        </td>
                      )}
                      <td>
                        {label ? (
                          <>
                            {label.short} <span className="muted small">{label.name}</span>
                            {code === "acr" && res && (
                              <div>
                                <AcrSource res={res} />
                              </div>
                            )}
                          </>
                        ) : (
                          <span className="muted">нет подключённых показателей</span>
                        )}
                      </td>
                      <td className="r num">{res ? <ReportValue code={code} res={res} /> : "—"}</td>
                      <td>{res && res.status !== "calculated" ? <StatusBadge status={res.status} /> : null}</td>
                    </tr>
                  );
                });
              })}
              {(catalog.future_branches ?? []).map((b) => (
                <tr key={b.code} className="group-start">
                  <td>
                    <strong>{b.name}</strong>
                  </td>
                  <td colSpan={3} className="muted">
                    в работе: {b.note}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {research && r && (
        <section className="card report-section report-model">
          <h2>Модельная часть: LMB BioAge</h2>
          <div className="report-chart">
            <BranchContributions domains={result.domains} intercept={result.intercept} delta={rOk ? r.delta_years : null}
              interactive={false} />
          </div>
          <table className="report-table compact model-table">
            <thead>
              <tr>
                <th>Система</th>
                <th className="r">Оценка системы</th>
                <th className="r">Коэффициент</th>
                <th className="r">Вклад, лет</th>
              </tr>
            </thead>
            <tbody>
              {MODEL_DOMAINS.map((code) => {
                const d = doms.get(code);
                const name = catalog.branches.find((b) => b.code === code)?.name ?? code;
                return (
                  <tr key={code}>
                    <td>{name}</td>
                    <td className="r num">{d?.status === "calculated" ? signed(d.score!, 2) : <span className="muted small">{DOMAIN_LABEL[d?.status ?? ""] ?? "—"}</span>}</td>
                    <td className="r num">{d?.coefficient != null ? fmt(d.coefficient, 1) : "—"}</td>
                    <td className="r num">{d?.contribution != null ? signed(d.contribution, 2) : "—"}</td>
                  </tr>
                );
              })}
              <tr>
                <td>Постоянная модели</td>
                <td />
                <td />
                <td className="r num">{signed(result.intercept, 2)}</td>
              </tr>
              <tr className="sum">
                <td colSpan={3}>
                  <strong>Разница с календарным возрастом</strong>
                </td>
                <td className="r num strong">{rOk ? signed(r.delta_years!, 2) : "не рассчитана"}</td>
              </tr>
            </tbody>
          </table>
          <p className="muted small">Оценка системы — безразмерная (объединённые Z показателей); вклад = коэффициент × оценка.</p>
        </section>
      )}

      <section className="card report-section report-method">
        <h2>О методике</h2>
        <Methodology result={result} catalog={catalog} />
      </section>
    </article>
  );
}

function lqMeta(res: IndexRes): string {
  const e = res.extra as { device_model?: string | null; software_version?: string | null; reliability_pct?: number | null; measured_on?: string | null };
  return [e.device_model, e.software_version ? `версия ${e.software_version}` : null,
    e.reliability_pct != null ? `достоверность ${fmt(e.reliability_pct, 1)} %` : null,
    e.measured_on ? e.measured_on.split("-").reverse().join(".") : null].filter(Boolean).join(" · ");
}

/** Значение показателя в отчёте; у FRAX — оба риска и отметка о переносе из официального калькулятора. */
function ReportValue({ code, res }: { code: string; res: IndexRes }) {
  if (res.status !== "calculated" || res.value === null) return <>—</>;
  if (code === "frax_kz") {
    const e = res.extra as { hip_10y_pct?: number; with_bmd?: boolean };
    return (
      <span className="frax-report">
        основные {fmt(res.value, 1)} % · бедро {fmt(e.hip_10y_pct, 1)} %
        <span className="muted small"> (официальный FRAX, {e.with_bmd ? "с МПК" : "без МПК"})</span>
      </span>
    );
  }
  return (
    <>
      {fmt(res.value, DIGITS[code] ?? 2)} <span className="unit">{unitRu(res.unit)}</span>
    </>
  );
}
