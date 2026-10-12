import { useCallback, useEffect, useState } from "react";
import { api, ApiError, idem } from "../api";
import { useSession } from "../session";
import type { Run } from "../types";
import { openMethod, ProfileView } from "./ProfileView";
import { Alert, Button, dateRu } from "./ui";

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
  return (
    <div>
      <div className="toolbar">
        <div>
          {run ? (
            <p className="muted small">Расчёт от {dateRu(run.created_at)}</p>
          ) : (
            <p className="muted small">Расчёт ещё не выполнялся.</p>
          )}
        </div>
        <div className="row">
          {run && <Button onClick={openMethod}>О методике</Button>}
          {run && <Button onClick={() => void reproduce()}>Проверить воспроизводимость</Button>}
          <Button kind="primary" onClick={() => void calculate()} disabled={busy}>
            {busy ? "Считаем…" : "Рассчитать по текущим данным"}
          </Button>
        </div>
      </div>
      <Alert>{err}</Alert>
      <Alert kind="info">{repro}</Alert>
      {run && (
        <ProfileView
          result={{ ...run.result, status: run.status, bioage_years: run.bioage_years, delta_years: run.delta_years,
            model_version: run.model_version, model_config_sha256: run.model_config_sha256, engine_version: run.engine_version }}
          catalog={catalog}
          meta={<p className="small muted">Редакция модели {run.model_revision ?? "—"} · расчёт {run.calculation_id}</p>}
        />
      )}
    </div>
  );
}
