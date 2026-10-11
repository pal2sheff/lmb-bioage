import { useCallback, useEffect, useState } from "react";
import { api, ApiError, idem, parseNumber } from "../api";
import { useSession } from "../session";
import type { Definition, Obs } from "../types";
import { Alert, Button, dateRu } from "./ui";
import { unitRu } from "../units";

const Q = { eq: "", lt: "<", gt: ">" } as const;

export function Observations({ encounterId, onChange }: { encounterId: string; onChange: () => void }) {
  const { catalog } = useSession();
  const [obs, setObs] = useState<Obs[]>([]);
  const [history, setHistory] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setObs(await api.get<Obs[]>(`/encounters/${encounterId}/observations?history=${history}`));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }, [encounterId, history]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = async () => {
    await load();
    onChange();
  };
  if (!catalog) return null;
  const current = new Map(obs.filter((o) => o.is_current && o.review_status !== "rejected").map((o) => [o.code, o]));

  return (
    <div>
      <div className="toolbar">
        <p className="muted small">
          Значение без числа сохраняется как «нет данных», а не как ноль. Исправление создаёт новую редакцию — прежняя
          остаётся в истории и в старых расчётах.
        </p>
        <label className="check">
          <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /> показать историю
          редакций
        </label>
      </div>
      <Alert>{err}</Alert>
      {catalog.observation_groups.map((g) => (
        <section key={g.title} className="obs-group">
          <h3 className="group-title">{g.title}</h3>
          <div className="obs-table" role="table">
            <div className="obs-row obs-head" role="row">
              <span>Показатель</span>
              <span>Значение</span>
              <span>Единица</span>
              <span>Дата образца</span>
              <span>Образец</span>
              <span>Статус</span>
              <span />
            </div>
            {g.items.map((d) => (
              <ObsRow key={d.code} def={d} cur={current.get(d.code)} encounterId={encounterId} onSaved={reload} />
            ))}
            {history &&
              obs
                .filter((o) => !o.is_current && g.items.some((d) => d.code === o.code))
                .map((o) => (
                  <div key={o.id} className="obs-row obs-old" role="row">
                    <span className="muted">
                      {g.items.find((d) => d.code === o.code)?.name_ru} · ред. {o.revision}
                    </span>
                    <span className="num">
                      {Q[o.qualifier]}
                      {o.value ?? "—"}
                    </span>
                    <span>{unitRu(o.unit)}</span>
                    <span>{dateRu(o.sample_date)}</span>
                    <span className="mono small">{o.sample_id}</span>
                    <span className="muted small">заменено</span>
                    <span />
                  </div>
                ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function ObsRow({
  def,
  cur,
  encounterId,
  onSaved,
}: {
  def: Definition;
  cur: Obs | undefined;
  encounterId: string;
  onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(!cur);
  const [value, setValue] = useState(cur?.value?.toString().replace(".", ",") ?? "");
  const [unit, setUnit] = useState(cur?.unit ?? def.unit_canonical ?? def.allowed_units[0] ?? "");
  const [qual, setQual] = useState<"eq" | "lt" | "gt">(cur?.qualifier ?? "eq");
  const [date, setDate] = useState(cur?.sample_date ?? "");
  const [sample, setSample] = useState(cur?.sample_id ?? "");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setEditing(!cur);
  }, [cur]);

  async function save() {
    setErr("");
    const v = parseNumber(value);
    if (v === "invalid") return setErr("Не число");
    if (v === null && !cur) return;
    setBusy(true);
    const body = { value: v, unit: v === null ? null : unit, qualifier: qual, sample_date: date || null, sample_id: sample || null };
    try {
      if (cur) {
        if (reason.trim().length < 3) {
          setBusy(false);
          return setErr("Укажите причину исправления");
        }
        await api.patch(`/observations/${cur.chain_id}`, { ...body, change_reason: reason.trim() }, { "If-Match": String(cur.revision) });
      } else {
        await api.post(`/encounters/${encounterId}/observations`, { code: def.code, ...body, source: "manual" }, idem());
      }
      setReason("");
      await onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function review(decision: "confirm" | "reject") {
    if (!cur) return;
    try {
      await api.post(`/observations/${cur.chain_id}/review`, { decision }, { "If-Match": String(cur.revision) });
      await onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  const status = cur
    ? cur.review_status === "pending"
      ? <span className="badge tone-review">◐ ждёт подтверждения</span>
      : <span className="badge tone-ok">● ред. {cur.revision}</span>
    : <span className="muted small">не внесено</span>;

  return (
    <>
      <div className={`obs-row${editing ? " is-editing" : ""}`} role="row">
        <span className="obs-name">{def.name_ru}</span>
        {editing ? (
          <>
            <span className="val-edit">
              <select aria-label="Знак" value={qual} onChange={(e) => setQual(e.target.value as "eq" | "lt" | "gt")}>
                <option value="eq">=</option>
                <option value="lt">&lt;</option>
                <option value="gt">&gt;</option>
              </select>
              <input aria-label={def.name_ru} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
            </span>
            <select aria-label="Единица" value={unit} onChange={(e) => setUnit(e.target.value)}>
              {def.allowed_units.map((u) => (
                <option key={u} value={u}>
                  {unitRu(u)}
                </option>
              ))}
            </select>
            <input aria-label="Дата образца" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <input aria-label="Номер образца" placeholder="№" value={sample} onChange={(e) => setSample(e.target.value)} />
          </>
        ) : (
          <>
            <span className="num strong">
              {Q[cur!.qualifier]}
              {cur!.value === null ? "нет данных" : cur!.value.toLocaleString("ru-RU")}
            </span>
            <span>{unitRu(cur!.unit)}</span>
            <span>{dateRu(cur!.sample_date)}</span>
            <span className="mono small">{cur!.sample_id ?? ""}</span>
          </>
        )}
        <span>{status}</span>
        <span className="row-actions">
          {editing ? (
            <Button small kind="primary" onClick={() => void save()} disabled={busy}>
              Сохранить
            </Button>
          ) : cur?.review_status === "pending" ? (
            <>
              <Button small kind="primary" onClick={() => void review("confirm")}>
                Подтвердить
              </Button>
              <Button small kind="danger" onClick={() => void review("reject")}>
                Отклонить
              </Button>
            </>
          ) : (
            <Button small onClick={() => setEditing(true)}>
              Исправить
            </Button>
          )}
          {editing && cur && (
            <Button small onClick={() => setEditing(false)}>
              Отмена
            </Button>
          )}
        </span>
      </div>
      {editing && cur && (
        <div className="obs-reason">
          <input placeholder="Причина исправления (обязательно)" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      )}
      {err && (
        <div className="obs-reason">
          <Alert>{err}</Alert>
        </div>
      )}
    </>
  );
}
