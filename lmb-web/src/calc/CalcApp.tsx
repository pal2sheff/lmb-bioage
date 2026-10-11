import { useEffect, useMemo, useRef, useState } from "react";
import { fmt, parseNumber } from "../api";
import { ProfileView, type EngineResult } from "../components/ProfileView";
import { Alert, Button } from "../components/ui";
import type { Catalog, QItem } from "../types";
import { unitRu } from "../units";
import { EXAMPLE } from "./example";
import { loadEngine, type CalcCase, type Engine } from "./engine";

export interface FormState {
  birth_date: string;
  encounter_date: string;
  sex: "" | "female" | "male";
  values: Record<string, { text: string; unit: string }>;
  flags: Record<string, string>;
  frax: { major: string; hip: string; with_bmd: "" | "yes" | "no" };
}

const today = () => new Date().toISOString().slice(0, 10);
const EMPTY: FormState = {
  birth_date: "",
  encounter_date: today(),
  sex: "",
  values: {},
  flags: {},
  frax: { major: "", hip: "", with_bmd: "" },
};
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
const FILE_FORMAT = "lmb-bioage-case";

/** Форма → вход расчётного модуля. Пустое поле — null (не 0); «не знаю» не передаётся. */
export function toCase(f: FormState, catalog: Catalog): { kase: CalcCase; problems: string[] } {
  const problems: string[] = [];
  const names: Record<string, string> = {};
  catalog.observation_groups.forEach((g) => g.items.forEach((d) => (names[d.code] = d.name_ru)));
  const measurements: CalcCase["measurements"] = {};
  for (const [code, v] of Object.entries(f.values)) {
    const n = parseNumber(v.text);
    if (n === "invalid") problems.push(`${names[code] ?? code}: не число`);
    else if (n !== null) measurements[code] = { value: n, unit: v.unit };
  }
  const flags: Record<string, string> = {};
  for (const [k, v] of Object.entries(f.flags)) if (v && v !== "unknown") flags[k] = v.trim();
  let frax: CalcCase["frax"] = null;
  const major = parseNumber(f.frax.major);
  const hip = parseNumber(f.frax.hip);
  if (major !== null || hip !== null) {
    if (typeof major !== "number" || typeof hip !== "number") problems.push("FRAX: укажите оба риска числом");
    else if (!f.frax.with_bmd) problems.push("FRAX: укажите, рассчитан ли результат с МПК");
    else {
      const bound = catalog.frax_risk_factors.every((k) => f.flags[k] === "yes" || f.flags[k] === "no");
      frax = { major, hip, with_bmd: f.frax.with_bmd === "yes", inputs_bound: bound };
    }
  }
  return {
    kase: { birth_date: f.birth_date, encounter_date: f.encounter_date, sex: f.sex, measurements, flags, frax },
    problems,
  };
}

export function CalcApp() {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [stage, setStage] = useState("Подготовка…");
  const [loadErr, setLoadErr] = useState("");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [result, setResult] = useState<EngineResult | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadEngine(setStage)
      .then(setEngine)
      .catch((e: unknown) => setLoadErr(e instanceof Error ? e.message : String(e)));
  }, []);

  // пересчёт при каждом изменении (модуль работает локально, расчёт занимает миллисекунды)
  useEffect(() => {
    if (!engine) return;
    const t = setTimeout(() => {
      if (!form.birth_date || !form.encounter_date || !form.sex) {
        setResult(null);
        setProblems([]);
        return;
      }
      const { kase, problems: p } = toCase(form, engine.catalog);
      setProblems(p);
      try {
        setResult(engine.calculate(kase));
      } catch (e) {
        setProblems([...p, "Ошибка расчётного модуля: " + (e instanceof Error ? e.message.split("\n").slice(-2).join(" ") : String(e))]);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [engine, form]);

  function setValue(code: string, text: string, unit: string) {
    setForm((f) => ({ ...f, values: { ...f.values, [code]: { text, unit } } }));
  }
  function setFlag(code: string, v: string) {
    setForm((f) => ({ ...f, flags: { ...f.flags, [code]: v } }));
  }

  function save() {
    const blob = new Blob([JSON.stringify({ format: FILE_FORMAT, version: 1, saved_at: new Date().toISOString(), engine: engine?.meta ?? null, form }, null, 1)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `lmb-case-${form.encounter_date || today()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    setMsg("Случай сохранён в файл на этом компьютере");
  }

  async function open(file: File) {
    setMsg("");
    try {
      const data = JSON.parse(await file.text()) as { format?: string; form?: FormState };
      if (data.format !== FILE_FORMAT || !data.form) throw new Error("это не файл случая LMB BioAge");
      setForm({ ...EMPTY, ...data.form, frax: { ...EMPTY.frax, ...data.form.frax } });
      setMsg(`Открыт файл ${file.name}`);
    } catch (e) {
      setMsg("Не удалось открыть файл: " + (e instanceof Error ? e.message : String(e)));
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">
          LMB <em>BioAge</em>
        </span>
        {!engine && !loadErr && <span className="topbar-user muted small">{stage}</span>}
      </header>
      <main className="calc-main">
        {loadErr && (
          <Alert>
            Расчётный модуль не загрузился: {loadErr}. Откройте страницу через веб-адрес (http/https), а не как файл
            с диска.
          </Alert>
        )}
        <div className="calc-layout">
          <section className="calc-form" aria-label="Данные пациента">
            <div className="calc-actions row">
              <Button small onClick={() => setForm(EXAMPLE)}>
                Синтетический пример
              </Button>
              <Button small onClick={() => setForm({ ...EMPTY, encounter_date: today() })}>
                Очистить
              </Button>
              <Button small onClick={save}>
                Сохранить в файл
              </Button>
              <Button small onClick={() => fileRef.current?.click()}>
                Открыть файл
              </Button>
              <a className="btn btn-sm to-result" href="#profile">
                К профилю ↓
              </a>
              <input
                ref={fileRef}
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void open(f);
                  e.target.value = "";
                }}
              />
            </div>
            <p className="muted small">
              Данные остаются в этом браузере и никуда не отправляются. После закрытия вкладки они исчезают — чтобы
              вернуться к случаю, сохраните его в файл.
            </p>
            <Alert kind="info">{msg}</Alert>
            {engine ? <Inputs catalog={engine.catalog} form={form} setForm={setForm} setValue={setValue} setFlag={setFlag} /> : null}
          </section>

          <section className="calc-result" id="profile" aria-label="Результат">
            {!engine && !loadErr && <p className="loading">{stage}</p>}
            {engine && !result && (
              <div className="panel">
                <h3>Профиль появится здесь</h3>
                <p className="muted">
                  Укажите дату рождения, дату обследования и пол, затем вносите показатели — расчёт обновляется
                  сразу. Для знакомства нажмите «Синтетический пример».
                </p>
              </div>
            )}
            {problems.length > 0 && (
              <Alert kind="warn">
                <strong>Проверьте ввод:</strong>
                <ul>
                  {problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </Alert>
            )}
            {engine && result && (
              <>
                <div className="toolbar no-print">
                  <p className="muted small">
                    Расчёт выполнен в браузере тем же модулем, что и на сервере. Возраст на дату обследования:{" "}
                    {ageText(form)}.
                  </p>
                  <Button small onClick={() => window.print()}>
                    Печать
                  </Button>
                </div>
                <ProfileView result={result} catalog={engine.catalog} />
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function ageText(f: FormState): string {
  if (!f.birth_date || !f.encounter_date) return "—";
  const b = new Date(f.birth_date);
  const d = new Date(f.encounter_date);
  let a = d.getFullYear() - b.getFullYear();
  if (d.getMonth() < b.getMonth() || (d.getMonth() === b.getMonth() && d.getDate() < b.getDate())) a -= 1;
  return `${a} полных лет`;
}

function Inputs(props: {
  catalog: Catalog;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  setValue: (code: string, text: string, unit: string) => void;
  setFlag: (code: string, v: string) => void;
}) {
  const { catalog, form, setForm, setValue, setFlag } = props;
  const qgroups = useMemo(
    () =>
      catalog.questionnaire_groups
        .map((g) => ({ ...g, items: g.items.filter((i) => i.kind !== "frax_list") }))
        .filter((g) => g.items.length > 0),
    [catalog],
  );
  return (
    <>
      <h3 className="group-title">Пациент и обследование</h3>
      <div className="calc-row">
        <label htmlFor="c-birth">Дата рождения</label>
        <input id="c-birth" type="date" value={form.birth_date} onChange={(e) => setForm((f) => ({ ...f, birth_date: e.target.value }))} />
      </div>
      <div className="calc-row">
        <label htmlFor="c-enc">Дата обследования</label>
        <input id="c-enc" type="date" value={form.encounter_date} onChange={(e) => setForm((f) => ({ ...f, encounter_date: e.target.value }))} />
      </div>
      <div className="calc-row">
        <span id="c-sex">Пол (для алгоритмов)</span>
        <Segmented
          label="Пол (для алгоритмов)"
          value={form.sex}
          options={[
            ["female", "Женский"],
            ["male", "Мужской"],
          ]}
          onChange={(v) => setForm((f) => ({ ...f, sex: v as FormState["sex"] }))}
        />
      </div>

      {catalog.observation_groups.map((g) => (
        <div key={g.title}>
          <h3 className="group-title">{g.title}</h3>
          {g.items.map((d) => {
            const cur = form.values[d.code];
            const unit = cur?.unit ?? d.unit_canonical ?? d.allowed_units[0] ?? "";
            const bad = cur ? parseNumber(cur.text) === "invalid" : false;
            return (
              <div key={d.code} className="calc-row">
                <label htmlFor={`v-${d.code}`}>{d.name_ru}</label>
                <span className="calc-val">
                  <input
                    id={`v-${d.code}`}
                    inputMode="decimal"
                    aria-invalid={bad}
                    className={bad ? "is-bad" : ""}
                    value={cur?.text ?? ""}
                    onChange={(e) => setValue(d.code, e.target.value, unit)}
                  />
                  {d.allowed_units.length > 1 ? (
                    <select aria-label={`Единица: ${d.name_ru}`} value={unit} onChange={(e) => setValue(d.code, cur?.text ?? "", e.target.value)}>
                      {d.allowed_units.map((u) => (
                        <option key={u} value={u}>
                          {unitRu(u)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="unit">{unitRu(unit)}</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ))}

      {qgroups.map((g) => (
        <div key={g.title}>
          <h3 className="group-title">{g.title}</h3>
          {g.items.map((it) => (
            <QRow key={it.code} it={it} value={form.flags[it.code] ?? ""} onChange={(v) => setFlag(it.code, v)} />
          ))}
        </div>
      ))}

      <h3 className="group-title">FRAX — официальный результат (модель Казахстана)</h3>
      <p className="muted small">
        Перенесите оба 10-летних риска из официального калькулятора FRAX. Формула FRAX здесь не воспроизводится.
      </p>
      <div className="calc-row">
        <label htmlFor="f-major">Основные остеопоротические переломы</label>
        <span className="calc-val">
          <input id="f-major" inputMode="decimal" value={form.frax.major} onChange={(e) => setForm((f) => ({ ...f, frax: { ...f.frax, major: e.target.value } }))} />
          <span className="unit">%</span>
        </span>
      </div>
      <div className="calc-row">
        <label htmlFor="f-hip">Перелом бедра</label>
        <span className="calc-val">
          <input id="f-hip" inputMode="decimal" value={form.frax.hip} onChange={(e) => setForm((f) => ({ ...f, frax: { ...f.frax, hip: e.target.value } }))} />
          <span className="unit">%</span>
        </span>
      </div>
      <div className="calc-row">
        <span>Расчёт FRAX</span>
        <Segmented
          label="Расчёт FRAX с МПК"
          value={form.frax.with_bmd}
          options={[
            ["no", "без МПК"],
            ["yes", "с МПК"],
          ]}
          onChange={(v) => setForm((f) => ({ ...f, frax: { ...f.frax, with_bmd: v as FormState["frax"]["with_bmd"] } }))}
        />
      </div>
      <p className="muted small calc-foot">
        Справочно: {fmt(catalog.observation_groups.reduce((n, g) => n + g.items.length, 0), 0)} показателей,{" "}
        {fmt(qgroups.reduce((n, g) => n + g.items.length, 0), 0)} пунктов анкеты. «Не знаю» не считается ответом «нет».
      </p>
    </>
  );
}

function QRow({ it, value, onChange }: { it: QItem; value: string; onChange: (v: string) => void }) {
  return (
    <div className="calc-row q">
      <span>
        {it.name}
        {it.doctor_only && <span className="tag">врач</span>}
      </span>
      {it.kind === "choice" && (
        <Segmented
          label={it.name}
          value={value || "unknown"}
          options={(it.options ?? []).map((o) => [o, OPTION_LABEL[o] ?? o] as [string, string])}
          onChange={onChange}
        />
      )}
      {it.kind === "integer" && (
        <input
          className="calc-int"
          inputMode="numeric"
          aria-label={it.name}
          placeholder="не знаю"
          value={value === "unknown" ? "" : value}
          onChange={(e) => onChange(e.target.value.trim())}
        />
      )}
      {it.kind === "text" && <input aria-label={it.name} maxLength={50} value={value} onChange={(e) => onChange(e.target.value)} />}
    </div>
  );
}

function Segmented(props: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={props.label}>
      {props.options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={props.value === v}
          className={props.value === v ? "seg on" : "seg"}
          onClick={() => props.onChange(v)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
