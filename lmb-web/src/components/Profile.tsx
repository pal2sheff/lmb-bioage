import { useCallback, useEffect, useState } from "react";
import { api, ApiError, fmt, idem } from "../api";
import { useSession } from "../session";
import type { DomainRes, IndexRes, Run, ZRes } from "../types";
import { Alert, Button, StatusBadge, dateRu } from "./ui";
import { unitRu } from "../units";

const DIGITS: Record<string, number> = { caide: 0, egfr_ckdepi_cr_2021: 0, bmi: 1, score2: 1, score2_op: 1, frax_kz: 1, sii: 0, whtr: 3, aip: 3, tyg: 2 };
const DOMAIN_LABEL: Record<string, string> = {
  calculated: "доменная оценка рассчитана",
  model_not_configured: "входной индекс не активирован",
  not_included: "не включено в v0.3",
  missing_data: "не хватает входов",
  not_applicable: "входы неприменимы",
  invalid_input: "ошибка входных данных",
  awaiting_review: "ожидает подтверждения врача",
};
// подписи Z-оценок v0.3 (коды нормализации из конфигурации модели)
const Z_LABEL: Record<string, string> = {
  score2: "SCORE2", egfr: "eGFR", acr: "ACR", fib4: "FIB-4", homa_ir: "HOMA-IR", tyg: "TyG", aip: "AIP",
  whtr: "WHtR", nlr: "NLR", sii: "SII", caide: "CAIDE", frax_major: "FRAX осн.",
};
const GAP_LABEL: Record<string, string> = { target_population: "целевая популяция модели не утверждена" };

export function Profile({ encounterId }: { encounterId: string }) {
  const { catalog } = useSession();
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [repro, setRepro] = useState("");

  const loadLatest = useCallback(async () => {
    const list = await api.get<{ calculation_id: string }[]>(`/encounters/${encounterId}/calculations`);
    if (list.length) setRun(await api.get<Run>(`/calculations/${list[list.length - 1].calculation_id}`));
  }, [encounterId]);

  useEffect(() => {
    loadLatest().catch((e) => setErr(e instanceof ApiError ? e.message : "Ошибка"));
  }, [loadLatest]);

  async function calculate() {
    setBusy(true);
    setErr("");
    setRepro("");
    try {
      setRun(await api.post<Run>(`/encounters/${encounterId}/calculations`, { model_version: "v0.3" }, idem()));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function reproduce() {
    if (!run) return;
    const r = await api.post<{ identical: boolean }>(`/calculations/${run.calculation_id}/reproduce`);
    setRepro(r.identical ? "Расчёт воспроизведён: результат совпадает полностью" : "Результат не совпал — нужна проверка");
  }

  if (!catalog) return null;
  const idx = new Map((run?.result.indices ?? []).map((i) => [i.code, i]));
  const names: Record<string, string> = { birth_date: "дата рождения", sex_at_birth: "пол", frax_result: "результат FRAX" };
  catalog.observation_groups.forEach((g) => g.items.forEach((d) => (names[d.code] = d.name_ru)));
  catalog.questionnaire_groups.forEach((g) => g.items.forEach((q) => (names[q.code] = q.name)));
  const doms = new Map((run?.result.domains ?? []).map((d) => [d.domain, d]));

  return (
    <div>
      <div className="toolbar">
        <div>
          {run ? (
            <p className="muted small">
              Расчёт от {dateRu(run.created_at)} · модель {run.model_version}
              {run.model_revision ? `, ред. ${run.model_revision}` : ""} · модуль {run.engine_version} · входы{" "}
              <span className="mono">{run.result.input_version.slice(7, 19)}</span>
            </p>
          ) : (
            <p className="muted small">Расчёт ещё не выполнялся.</p>
          )}
        </div>
        <div className="row">
          {run && <Button onClick={() => void reproduce()}>Проверить воспроизводимость</Button>}
          <Button kind="primary" onClick={() => void calculate()} disabled={busy}>
            {busy ? "Считаем…" : "Рассчитать по текущим данным"}
          </Button>
        </div>
      </div>
      <Alert>{err}</Alert>
      <Alert kind="info">{repro}</Alert>
      {run && (
        <>
          <Integral run={run} />
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
                  {d && <ZLine domain={d} zs={run.result.zscores ?? {}} />}
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );

  function IndexLine({ code, res }: { code: string; res: IndexRes | undefined }) {
    const label = catalog!.index_labels[code];
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
            Z {Z_LABEL[c] ?? c}{" "}
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

const DOMAIN_TITLE: Record<string, string> = {
  cardio: "Cardio", metabolic: "Metabolic", renal: "Renal", hepatic: "Hepatic", inflammation: "Inflammation",
  brain: "Brain", bone: "Bone",
};

function reasonRu(r: string): string {
  // «Домен cardio: model_not_configured» → «Cardio: входной индекс не активирован»
  const m = /^Домен (\w+): (\w+)$/.exec(r);
  return m ? `${DOMAIN_TITLE[m[1]] ?? m[1]}: ${DOMAIN_LABEL[m[2]] ?? m[2]}` : r;
}

function Integral({ run }: { run: Run }) {
  if (run.status !== "calculated" || run.bioage_years === null) {
    const reasons = run.result.blocking_reasons;
    const gaps = reasons.find((r) => r.startsWith("Конфигурация модели неполная"));
    const other = reasons.filter((r) => r !== gaps);
    return (
      <section className="integral blocked">
        <div className="integral-figure">
          <span className="eyebrow">LMB BioAge · v0.3</span>
          <span className="integral-value">не рассчитан</span>
        </div>
        <div className="integral-why">
          <p>
            Итог не показывается без полной утверждённой конфигурации модели. Веса не перераспределяются, пропуски не
            заменяются нулями. Доступные индексы ниже рассчитаны и действуют самостоятельно.
          </p>
          <details>
            <summary>Причины ({reasons.length})</summary>
            <ul className="notes">
              {gaps && (
                <li>
                  Конфигурация модели неполная:{" "}
                  {gaps
                    .replace("Конфигурация модели неполная: ", "")
                    .split(", ")
                    .map((g) => GAP_LABEL[g] ?? g)
                    .join("; ")}
                </li>
              )}
              {other.map((r) => (
                <li key={r}>{reasonRu(r)}</li>
              ))}
            </ul>
          </details>
        </div>
      </section>
    );
  }
  const c = run.result.contributions ?? {};
  const max = Math.max(...Object.values(c).map(Math.abs), 0.01);
  return (
    <section className="integral">
      <div className="integral-figure">
        <span className="eyebrow">LMB BioAge · исследовательский режим</span>
        <span className="integral-value num">{fmt(run.bioage_years, 1)}</span>
        <span className="muted">ΔBioAge {fmt(run.delta_years, 2)} · постоянная {fmt(run.result.intercept, 2)}</span>
      </div>
      <div className="contrib">
        {Object.entries(c).map(([d, v]) => (
          <div key={d} className="contrib-row">
            <span>{d}</span>
            <span className="contrib-bar">
              <span className={v >= 0 ? "pos" : "neg"} style={{ width: `${(Math.abs(v) / max) * 50}%` }} />
            </span>
            <span className="num">
              {v >= 0 ? "+" : "−"}
              {fmt(Math.abs(v), 2)}
            </span>
            <span className="muted small">{v >= 0 ? "повышает расчётную оценку" : "снижает расчётную оценку"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
