// Отчёт врача для печати: те же данные расчётного модуля, сведённые в таблицы.
import { fmt } from "../api";
import type { Catalog } from "../types";
import { unitRu } from "../units";
import { signed } from "./Charts";
import { CalcDetails, ClinicalStatusLine, DIGITS, DOMAIN_LABEL, type EngineResult, ResearchCard } from "./ProfileView";
import { useResearchMode } from "./TestMode";
import { Button, StatusBadge } from "./ui";

export function Report(props: {
  result: EngineResult;
  catalog: Catalog;
  facts: { label: string; value: string }[];
}) {
  const { result, catalog, facts } = props;
  const [research] = useResearchMode();
  const idx = new Map(result.indices.map((i) => [i.code, i]));
  const doms = new Map(result.domains.map((d) => [d.domain, d]));
  const r = result.research;
  const contrib = research && r?.status === "calculated" ? r.contributions : null;
  return (
    <article className="report">
      <div className="toolbar no-print">
        <p className="muted">Отчёт формируется из текущих данных. Перед печатью проверьте разделы «Данные обследования» и «Анкета».</p>
        <Button kind="primary" onClick={() => window.print()}>
          Печать отчёта
        </Button>
      </div>
      <header className="report-head card">
        <div>
          <span className="eyebrow">Отчёт врача</span>
          <h1>LMB BioAge — профиль систем</h1>
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

      <ClinicalStatusLine result={result} catalog={catalog} />
      {research && r && <ResearchCard result={result} catalog={catalog} pheno={idx.get("phenoage")} />}

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
              <th className="r">Оценка системы</th>
            </tr>
          </thead>
          <tbody>
            {catalog.branches.map((b) => {
              const d = doms.get(b.code);
              const rows = b.indices.length ? b.indices : [""];
              return rows.map((code, i) => {
                const res = code ? idx.get(code) : undefined;
                const label = code ? catalog.index_labels[code] : undefined;
                const show = res && res.value !== null && res.status !== "missing_data" && res.status !== "invalid_input";
                return (
                  <tr key={b.code + code} className={i === 0 ? "group-start" : ""}>
                    {i === 0 && (
                      <td rowSpan={rows.length}>
                        <strong>{b.name}</strong>
                        <div className="muted small">{b.title}</div>
                      </td>
                    )}
                    <td>{label ? <>{label.short} <span className="muted small">{label.name}</span></> : <span className="muted">нет показателей в этой версии</span>}</td>
                    <td className="r num">
                      {show ? (
                        <>
                          {fmt(res!.value, DIGITS[code] ?? 2)} <span className="unit">{unitRu(res!.unit)}</span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{res ? <StatusBadge status={res.status} /> : null}</td>
                    {i === 0 && (
                      <td rowSpan={rows.length} className="r num">
                        {d?.status === "calculated" ? fmt(d.score, 2) : <span className="muted small">{DOMAIN_LABEL[d?.status ?? ""] ?? "—"}</span>}
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

      {contrib && (
        <section className="card report-section">
          <h2>Вклады систем в исследовательскую оценку</h2>
          <table className="report-table compact">
            <tbody>
              {Object.entries(contrib).map(([d, v]) => (
                <tr key={d}>
                  <td>{catalog.branches.find((b) => b.code === d)?.name ?? d}</td>
                  <td className="r num">{signed(v, 2)}</td>
                  <td className="muted small">{v > 0 ? "повышает расчётную оценку" : v < 0 ? "снижает расчётную оценку" : "не меняет"}</td>
                </tr>
              ))}
              <tr>
                <td>Постоянная модели</td>
                <td className="r num">{signed(r!.intercept, 2)}</td>
                <td />
              </tr>
              <tr className="sum">
                <td>
                  <strong>Разница с календарным возрастом</strong>
                </td>
                <td className="r num strong">{signed(r!.delta_years!, 2)}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </section>
      )}

      <CalcDetails result={result} open />
    </article>
  );
}
