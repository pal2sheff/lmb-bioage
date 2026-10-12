// Отчёт врача для печати: те же данные расчётного модуля, сведённые в таблицы.
// PhenoAge — самостоятельный показатель; сравнения с LMB в отчёте нет (решение владельца 11.10.2026).
// Методические пояснения — одним компактным блоком в конце (уточнение 11.10.2026, 21:24).
// Аудит 12.10.2026: диаграмма вкладов; клинические индексы и безразмерные оценки систем — в разных частях.
import type { ReactNode } from "react";
import { fmt } from "../api";
import type { Catalog, IndexRes, MuscleMeasurements } from "../types";
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
                const rows = branchRows(b.code, b.indices, idx, catalog, result.muscle_measurements);
                return rows.map((row, i) => (
                  <tr key={b.code + row.key} className={i === 0 ? "group-start" : ""}>
                    {i === 0 && (
                      <td rowSpan={rows.length}>
                        <strong>{b.name}</strong>
                      </td>
                    )}
                    <td>{row.label}</td>
                    <td className="r num">{row.value}</td>
                    <td>{row.status}</td>
                  </tr>
                ));
              })}
              {(catalog.future_branches ?? []).map((b) => (
                <tr key={b.code} className="group-start">
                  <td>
                    <strong>{b.name}</strong>
                  </td>
                  <td colSpan={3} className="muted">
                    <span className="badge-dev">В работе</span> в расчёт не входит
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

interface Row {
  key: string;
  label: ReactNode;
  value: ReactNode;
  status: ReactNode;
}
const kg = (v: number | null | undefined, d = 2) => (v == null ? "—" : `${fmt(v, d)} кг`);

/** Строки ветки в таблице отчёта. Мышечная ветка — исходные данные и ASMI (мышечный возраст — модель
 *  0.1-synthetic — в отчёт не входит); LQ1 — одна строка «Возраст по LQ1». */
function branchRows(code: string, indices: string[], idx: Map<string, IndexRes>, catalog: Catalog, m?: MuscleMeasurements): Row[] {
  const fromIndex = (c: string): Row => {
    const res = idx.get(c);
    const label = catalog.index_labels[c];
    return {
      key: c,
      label: label ? (
        <>
          {label.short} <span className="muted small">{label.name}</span>
          {c === "acr" && res && (
            <div>
              <AcrSource res={res} />
            </div>
          )}
        </>
      ) : c,
      value: res ? <ReportValue code={c} res={res} /> : "—",
      status: res && res.status !== "calculated" ? <StatusBadge status={res.status} /> : null,
    };
  };
  if (code === "muscle") {
    const any = m && (m.grip_used_kg != null || m.chair_stand_5x_s != null || m.chair_stand_unable ||
      [m.visbody_seg_arm_left_kg, m.visbody_seg_arm_right_kg, m.visbody_seg_leg_left_kg, m.visbody_seg_leg_right_kg].some((v) => v != null));
    if (!any) return [fromIndex("asmi")];
    const rows: Row[] = [
      { key: "grip", label: <>Сила хвата <span className="muted small">правая · левая · используемый максимум</span></>,
        value: `${kg(m?.grip_right_kg, 1)} · ${kg(m?.grip_left_kg, 1)} · ${kg(m?.grip_used_kg, 1)}`, status: null },
      { key: "chair", label: <>Пять вставаний со стула <span className="muted small">без помощи рук</span></>,
        value: m?.chair_stand_unable ? "не удалось выполнить" : m?.chair_stand_5x_s != null ? `${fmt(m.chair_stand_5x_s, 1)} с` : "—", status: null },
      { key: "segments", label: <>Сегменты Visbody <span className="muted small">левая рука · правая рука · левая нога · правая нога</span></>,
        value: [m?.visbody_seg_arm_left_kg, m?.visbody_seg_arm_right_kg, m?.visbody_seg_leg_left_kg, m?.visbody_seg_leg_right_kg]
          .map((v) => (v == null ? "—" : fmt(v, 2))).join(" · ") + " кг", status: null },
      { key: "asm", label: <>ASM и рост <span className="muted small">Visbody, расчёт по четырём сегментам</span></>,
        value: `${kg(m?.asm_kg)} · ${m?.height_m != null ? `${fmt(m.height_m, 2)} м` : "—"}`, status: null },
      fromIndex("asmi"),
    ];
    return rows;
  }
  if (!indices.length) return [{ key: "", label: <span className="muted">нет подключённых показателей</span>, value: "—", status: null }];
  return indices.map(fromIndex);
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
