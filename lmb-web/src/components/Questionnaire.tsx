import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { useSession } from "../session";
import { Alert, Button } from "./ui";

type Answers = Record<string, { answer: string | null; answered: boolean }>;

const OPTION_LABEL: Record<string, string> = {
  yes: "Да",
  no: "Нет",
  unknown: "Не знаю",
  type1: "1 тип",
  type2: "2 тип",
  other: "Другой",
  active: "Активен",
  inactive: "Неактивен",
};

export function Questionnaire({ encounterId, onChange }: { encounterId: string; onChange: () => void }) {
  const { catalog } = useSession();
  const [saved, setSaved] = useState<Answers | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .get<Answers>(`/encounters/${encounterId}/questionnaire`)
      .then(setSaved)
      .catch((e) => setErr(e instanceof ApiError ? e.message : "Ошибка"));
  }, [encounterId]);

  if (!catalog || !saved) return null;
  const value = (code: string) => draft[code] ?? saved[code]?.answer ?? "";
  const dirty = Object.keys(draft).length > 0;
  const labelOf = (code: string) =>
    catalog.questionnaire_groups.flatMap((g) => g.items).find((i) => i.code === code)?.name ?? code;

  async function save() {
    setErr("");
    setMsg("");
    try {
      const r = await api.put<Answers>(`/encounters/${encounterId}/questionnaire`, { answers: draft });
      setSaved(r);
      setDraft({});
      setMsg("Ответы сохранены");
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  return (
    <div>
      <div className="toolbar">
        <p className="muted small">«Не знаю» хранится отдельно и не считается ответом «нет».</p>
        <Button kind="primary" onClick={() => void save()} disabled={!dirty}>
          {dirty ? `Сохранить изменения (${Object.keys(draft).length})` : "Сохранено"}
        </Button>
      </div>
      <Alert>{err}</Alert>
      <Alert kind="info">{msg}</Alert>
      {catalog.questionnaire_groups.map((g) => (
        <section key={g.title} className="q-group">
          <h3 className="group-title">{g.title}</h3>
          {g.items.map((it) => (
            <div key={it.code} className={`q-row${draft[it.code] !== undefined ? " is-dirty" : ""}`}>
              <div className="q-label">
                {it.name}
                {it.doctor_only && <span className="tag">врач</span>}
              </div>
              <div className="q-control">
                {it.kind === "choice" && (
                  <div className="segmented" role="radiogroup" aria-label={it.name}>
                    {it.options!.map((o) => (
                      <button
                        key={o}
                        type="button"
                        role="radio"
                        aria-checked={value(it.code) === o}
                        className={value(it.code) === o ? "seg on" : "seg"}
                        onClick={() => setDraft({ ...draft, [it.code]: o })}
                      >
                        {OPTION_LABEL[o] ?? o}
                      </button>
                    ))}
                  </div>
                )}
                {it.kind === "integer" && (
                  <span className="int-field">
                    <input
                      inputMode="numeric"
                      aria-label={it.name}
                      value={value(it.code) === "unknown" ? "" : value(it.code)}
                      placeholder="не знаю"
                      onChange={(e) => {
                        const v = e.target.value.trim();
                        setDraft({ ...draft, [it.code]: v === "" ? "unknown" : v });
                      }}
                    />
                    {it.range && (
                      <span className="muted small">
                        {it.range[0]}–{it.range[1]} лет; пусто — «не знаю»
                      </span>
                    )}
                  </span>
                )}
                {it.kind === "text" && (
                  <input value={value(it.code)} maxLength={50} onChange={(e) => setDraft({ ...draft, [it.code]: e.target.value })} />
                )}
                {it.kind === "frax_list" && (
                  <div className="checks">
                    {catalog.frax_risk_factors.map((f) => {
                      const list = value(it.code).split(",").filter(Boolean);
                      const on = list.includes(f);
                      return (
                        <label key={f} className="check">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => {
                              const next = on ? list.filter((x) => x !== f) : [...list, f];
                              setDraft({ ...draft, [it.code]: next.join(",") });
                            }}
                          />{" "}
                          {labelOf(f)}
                        </label>
                      );
                    })}
                    <p className="muted small">
                      Используется, только если владелец модели разрешит этот режим (раздел 21 ТЗ).
                    </p>
                  </div>
                )}
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
