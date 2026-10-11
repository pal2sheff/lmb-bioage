// Исследовательский расчёт LMB v0.3 (решение владельца 11.10.2026): только для врача, по переключателю
// режима тестирования. Числа приходят из расчётного модуля; здесь только отображение.
import { useState } from "react";
import { fmt } from "../api";
import type { Catalog, ResearchRes } from "../types";
import { Bar, signed } from "./Charts";

const KEY = "lmb.researchMode";
const V03 = ["cardio", "metabolic", "renal", "hepatic", "inflammation", "brain", "bone"];
const STATUS_RU: Record<string, string> = {
  blocked: "не рассчитан",
  not_applicable: "неприменим",
  model_not_configured: "режим не настроен",
};
const DOMAIN_STATUS_RU: Record<string, string> = {
  model_not_configured: "входной индекс не активирован",
  missing_data: "не хватает входов",
  not_applicable: "входы неприменимы",
  invalid_input: "ошибка входных данных",
  awaiting_review: "ожидает подтверждения врача",
};

/** Переключатель режима тестирования: запоминается в этом браузере (удобство, не настройка модели). */
export function useResearchMode(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      window.localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      /* хранилище недоступно — режим действует до перезагрузки */
    }
  };
  return [on, set];
}

export function ResearchToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="research-toggle no-print">
      <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span>
        Режим тестирования: исследовательский расчёт LMB v0.3
        <span className="muted small"> — только для врача, в пациентский отчёт не входит</span>
      </span>
    </label>
  );
}

function reasonRu(r: string, title: Record<string, string>): string {
  const m = /^Домен (\w+): (\w+)$/.exec(r);
  if (m) return `${title[m[1]] ?? m[1]}: ${DOMAIN_STATUS_RU[m[2]] ?? m[2]}`;
  return r;
}

export function ResearchBlock({ r, catalog }: { r: ResearchRes; catalog: Catalog }) {
  const title = Object.fromEntries(catalog.branches.map((b) => [b.code, b.title]));
  const ok = r.status === "calculated" && r.bioage_years !== null && r.delta_years !== null && r.contributions;
  const rows = ok ? V03.map((d) => ({ d, v: r.contributions![d], z: r.domain_scores![d] })) : [];
  const max = Math.max(0.5, ...rows.map((x) => Math.abs(x.v)));
  return (
    <details className="research" open aria-labelledby="research-title">
      <summary>
        <span id="research-title">Исследовательский расчёт LMB v0.3</span>
        <span className="research-status">{ok ? "рассчитан" : STATUS_RU[r.status] ?? r.status}</span>
      </summary>
      <p className="research-limits" role="note">
        {r.limitations.join(" ")}
      </p>
      {ok ? (
        <div className="research-body">
          <div className="research-figure">
            <span className="eyebrow">Исследовательский итог</span>
            <span className="research-value num">{fmt(r.bioage_years, 1)}</span>
            <span className="small">
              календарный возраст {Math.round(r.bioage_years! - r.delta_years!)} · отклонение <span className="num strong">{signed(r.delta_years!, 2)}</span>
            </span>
          </div>
          <div className="dv-rows" role="table" aria-label="Вклады доменов исследовательского расчёта">
            {rows.map(({ d, v, z }) => (
              <div key={d} className="dv-row" role="row" title={`${title[d]}: доменная оценка ${fmt(z, 2)} × коэффициент`}>
                <span className="dv-label" role="cell">
                  <strong>{title[d]}</strong>
                  <span className="muted small">оценка {fmt(z, 2)}</span>
                </span>
                <Bar value={v} max={max} />
                <span className="dv-val num" role="cell">
                  {signed(v)}
                  <span className="muted small"> {v > 0 ? "повышает" : v < 0 ? "снижает" : "не меняет"}</span>
                </span>
              </div>
            ))}
            <div className="dv-row research-const" role="row">
              <span className="dv-label" role="cell">
                <strong>Постоянная модели</strong>
              </span>
              <span />
              <span className="dv-val num" role="cell">{signed(r.intercept)}</span>
            </div>
            <div className="dv-row research-sum" role="row">
              <span className="dv-label" role="cell">
                <strong>Отклонение (сумма)</strong>
              </span>
              <span />
              <span className="dv-val num strong" role="cell">{signed(r.delta_years!)}</span>
            </div>
          </div>
        </div>
      ) : (
        <ul className="notes">
          {r.reasons.map((x) => (
            <li key={x}>{reasonRu(x, title)}</li>
          ))}
        </ul>
      )}
      <p className="small muted research-meta">
        Модель {r.model_version} · конфигурация {r.model_config_sha256.slice(0, 8)} · режим {r.mode ?? "—"} · научный
        статус: {r.scientific_status === "not_validated" ? "не валидирована" : r.scientific_status}
        {r.research_population && (
          <>
            {" "}· техническая область {r.research_population.age_min}–{r.research_population.age_max} лет, синтетические
            профили
          </>
        )}
        . Изменение результата не означает доказанного омоложения или лечебного эффекта.
      </p>
    </details>
  );
}
