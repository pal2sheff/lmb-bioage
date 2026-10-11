// Отчёт врача для печати: те же данные расчётного модуля, сведённые в таблицы.
// PhenoAge — самостоятельный показатель; сравнения с LMB в отчёте нет (решение владельца 11.10.2026).
// Методические пояснения — одним компактным блоком в конце (уточнение 11.10.2026, 21:24).
import { fmt } from "../api";
import type { Catalog, IndexRes } from "../types";
import { unitRu } from "../units";
import { signed } from "./Charts";
import { AcrSource, DIGITS, DOMAIN_LABEL, type EngineResult, Methodology, reasonsRu } from "./ProfileView";
import { useResearchMode } from "./TestMode";
import { Button, StatusBadge } from "./ui";

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
          </tbody>
        </table>
      </section>

      <section className="card report-section">
        <h2>Показатели по системам</h2>
        <div className="table-wrap">
          <table className="report-table">
            <thead>
              <tr>
                <th>Система</th>
                <th>Показатель</th>
                <th className="r">Значение</th>
                <th>Статус</th>
                <th className="r">{research ? "Оценка системы" : ""}</th>
              </tr>
            </thead>
            <tbody>
              {catalog.branches.map((b) => {
                const d = doms.get(b.code);
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
                      {i === 0 && (
                        <td rowSpan={rows.length} className="r num">
                          {!research ? null : d?.status === "calculated" ? (
                            fmt(d.score, 2)
                          ) : (
                            <span className="muted small">{DOMAIN_LABEL[d?.status ?? ""] ?? "—"}</span>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                });
              })}
            </tbody>
          </table>
        </div>
      </section>

      {rOk && r.contributions && (
        <section className="card report-section">
          <h2>Вклады систем в LMB BioAge, лет</h2>
          <table className="report-table compact">
            <tbody>
              {Object.entries(r.contributions).map(([d, v]) => (
                <tr key={d}>
                  <td>{catalog.branches.find((b) => b.code === d)?.name ?? d}</td>
                  <td className="r num">{signed(v, 2)}</td>
                  <td className="muted small">{v > 0 ? "повышает расчётную оценку" : v < 0 ? "снижает расчётную оценку" : "не меняет"}</td>
                </tr>
              ))}
              <tr>
                <td>Постоянная модели</td>
                <td className="r num">{signed(r.intercept, 2)}</td>
                <td />
              </tr>
              <tr className="sum">
                <td>
                  <strong>Разница с календарным возрастом</strong>
                </td>
                <td className="r num strong">{signed(r.delta_years!, 2)}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </section>
      )}

      <section className="card report-section report-method">
        <h2>О методике</h2>
        <Methodology result={result} catalog={catalog} />
      </section>
    </article>
  );
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
