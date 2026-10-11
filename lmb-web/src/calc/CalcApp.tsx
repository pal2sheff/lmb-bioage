import { useEffect, useMemo, useRef, useState } from "react";
import { fmt, parseNumber } from "../api";
import { ProfileView, fieldNames, type EngineResult } from "../components/ProfileView";
import { Report } from "../components/Report";
import { Alert, Button, ageOn, dateRu } from "../components/ui";
import type { Catalog, Definition, IndexRes, QItem } from "../types";
import { unitRu } from "../units";
import { EXAMPLE, EXAMPLE_YOUNGER } from "./example";
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
const DRAFT_KEY = "lmb.calc.draft.v1";
/** Пункты анкеты, которые показываются не в анкете: источник ACR выбирается рядом с полями ACR. */
const NOT_IN_QUESTIONNAIRE = new Set(["acr_source", "frax_assumed_no"]);
/** Поля, у которых есть собственный элемент в форме (для перехода от сообщения). */
const FIELD_ID: Record<string, string> = {
  birth_date: "c-birth", sex_at_birth: "c-sex", frax_result: "f-major", frax_major_10y_pct: "f-major",
  frax_hip_10y_pct: "f-hip", acr_source: "acr-source",
};

/** Приведение формы из файла или черновика: берутся только известные поля (устаревшие игнорируются). */
export function sanitizeForm(x: unknown): FormState {
  const o = (x && typeof x === "object" ? x : {}) as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const values: FormState["values"] = {};
  if (o.values && typeof o.values === "object")
    for (const [k, v] of Object.entries(o.values as Record<string, unknown>)) {
      const vv = v as { text?: unknown; unit?: unknown } | null;
      if (vv && typeof vv.text === "string" && typeof vv.unit === "string") values[k] = { text: vv.text, unit: vv.unit };
    }
  const flags: Record<string, string> = {};
  if (o.flags && typeof o.flags === "object")
    for (const [k, v] of Object.entries(o.flags as Record<string, unknown>)) if (typeof v === "string") flags[k] = v;
  const fr = (o.frax && typeof o.frax === "object" ? o.frax : {}) as Record<string, unknown>;
  const sex = str(o.sex);
  const bmd = str(fr.with_bmd);
  return {
    birth_date: str(o.birth_date),
    encounter_date: str(o.encounter_date) || today(),
    sex: sex === "female" || sex === "male" ? sex : "",
    values,
    flags,
    frax: { major: str(fr.major), hip: str(fr.hip), with_bmd: bmd === "yes" || bmd === "no" ? bmd : "" },
  };
}

/** Форма → вход расчётного модуля. Пустое поле — null (не 0); «не знаю» не передаётся. */
export function toCase(f: FormState, catalog: Catalog): { kase: CalcCase; problems: { code: string; text: string }[] } {
  const problems: { code: string; text: string }[] = [];
  const names = fieldNames(catalog);
  const measurements: CalcCase["measurements"] = {};
  for (const [code, v] of Object.entries(f.values)) {
    const n = parseNumber(v.text);
    if (n === "invalid") problems.push({ code, text: `${names[code] ?? code}: не число — используйте цифры и запятую` });
    else if (n !== null) measurements[code] = { value: n, unit: v.unit };
  }
  const flags: Record<string, string> = {};
  for (const [k, v] of Object.entries(f.flags)) if (v && v !== "unknown") flags[k] = v.trim();
  let frax: CalcCase["frax"] = null;
  const major = parseNumber(f.frax.major);
  const hip = parseNumber(f.frax.hip);
  if (major !== null || hip !== null) {
    if (major === "invalid") problems.push({ code: "frax_major_10y_pct", text: "FRAX: риск основных переломов — не число" });
    if (hip === "invalid") problems.push({ code: "frax_hip_10y_pct", text: "FRAX: риск перелома бедра — не число" });
    if (major === null) problems.push({ code: "frax_major_10y_pct", text: "FRAX: укажите риск основных остеопоротических переломов" });
    if (hip === null) problems.push({ code: "frax_hip_10y_pct", text: "FRAX: укажите риск перелома бедра" });
    if (typeof major === "number" && typeof hip === "number") {
      if (!f.frax.with_bmd) problems.push({ code: "frax_result", text: "FRAX: укажите, рассчитан ли результат с МПК" });
      else {
        const bound = catalog.frax_risk_factors.every((k) => f.flags[k] === "yes" || f.flags[k] === "no");
        frax = { major, hip, with_bmd: f.frax.with_bmd === "yes", inputs_bound: bound };
      }
    }
  }
  return {
    kase: { birth_date: f.birth_date, encounter_date: f.encounter_date, sex: f.sex, measurements, flags, frax },
    problems,
  };
}

/** Ошибки по полям: ошибки ввода + противоречия + недопустимые значения из расчётного модуля. */
function fieldErrors(problems: { code: string; text: string }[], result: EngineResult | null): Map<string, string[]> {
  const m = new Map<string, string[]>();
  const add = (code: string, text: string) => {
    const list = m.get(code) ?? [];
    if (!list.includes(text)) m.set(code, [...list, text]);
  };
  problems.forEach((p) => add(p.code, p.text));
  if (result) {
    (result.input_checks ?? []).forEach((c) => c.fields.forEach((f) => add(f, c.message)));
    for (const i of result.indices as IndexRes[]) {
      if (i.status !== "invalid_input") continue;
      const fields = i.invalid_fields ?? [];
      if (fields.length === 1) i.reasons.forEach((r) => add(fields[0], r));
    }
  }
  return m;
}

/** Варианты единиц без дублей: синонимы с одинаковым множителем показываются одним пунктом. */
function unitOptions(d: Definition): string[] {
  const f = d.unit_factors ?? {};
  const all = [d.unit_canonical, ...d.allowed_units].filter((u): u is string => !!u);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const u of all) {
    const key = f[u] !== undefined ? `f:${f[u].toPrecision(10)}` : `u:${unitRu(u)}`;
    if (seen.has(key) || !d.allowed_units.includes(u)) continue;
    seen.add(key);
    out.push(u);
  }
  return out;
}

const numText = (v: number) => {
  const s = Number(v.toPrecision(6)).toString();
  return s.replace(".", ",");
};

type Section = "data" | "questionnaire" | "results";
const SECTIONS: [Section, string][] = [
  ["data", "Данные"],
  ["questionnaire", "Анкета"],
  ["results", "Результаты"],
];

function readDraft(): { form: FormState; saved_at: string } | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw) as { form?: unknown; saved_at?: string };
    return d.form ? { form: sanitizeForm(d.form), saved_at: d.saved_at ?? "" } : null;
  } catch {
    return null;
  }
}

const timeRu = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

export function CalcApp() {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [stage, setStage] = useState("Подготовка…");
  const [loadErr, setLoadErr] = useState("");
  const initialDraft = useMemo(readDraft, []);
  const [form, setForm] = useState<FormState>(initialDraft?.form ?? EMPTY);
  const [result, setResult] = useState<EngineResult | null>(null);
  const [problems, setProblems] = useState<{ code: string; text: string }[]>([]);
  const [msg, setMsg] = useState(initialDraft ? `Восстановлен черновик от ${timeRu(initialDraft.saved_at)}` : "");
  const [draft, setDraft] = useState(initialDraft ? `Черновик сохранён в браузере · ${timeRu(initialDraft.saved_at)}` : "");
  const [section, setSection] = useState<Section>("data");
  const [report, setReport] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const first = useRef(true);

  useEffect(() => {
    loadEngine(setStage)
      .then(setEngine)
      .catch((e: unknown) => setLoadErr(e instanceof Error ? e.message : String(e)));
  }, []);

  // черновик: сохраняется в этом браузере при каждом изменении (восстанавливается после обновления страницы)
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const t = setTimeout(() => {
      try {
        const saved_at = new Date().toISOString();
        window.localStorage.setItem(DRAFT_KEY, JSON.stringify({ saved_at, form }));
        setDraft(`Черновик сохранён в браузере · ${timeRu(saved_at)}`);
      } catch {
        setDraft("Черновик не сохраняется: хранилище браузера недоступно — сохраните случай в файл");
      }
    }, 400);
    return () => clearTimeout(t);
  }, [form]);

  // пересчёт при каждом изменении (модуль работает локально, расчёт занимает миллисекунды)
  useEffect(() => {
    if (!engine) return;
    const t = setTimeout(() => {
      const { kase, problems: p } = toCase(form, engine.catalog);
      setProblems(p);
      if (!form.birth_date || !form.encounter_date || !form.sex) {
        setResult(null);
        return;
      }
      try {
        setResult(engine.calculate(kase));
      } catch (e) {
        setProblems([...p, { code: "", text: "Ошибка расчётного модуля: " + (e instanceof Error ? e.message.split("\n").slice(-2).join(" ") : String(e)) }]);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [engine, form]);

  useEffect(() => {
    if (!focus) window.scrollTo({ top: 0 });
  }, [section, report, focus]);

  // переход к полю из сообщения
  useEffect(() => {
    if (!focus) return;
    const t = setTimeout(() => {
      const el = document.getElementById(focus);
      if (el) {
        el.scrollIntoView({ block: "center" });
        (el.querySelector("input, button, select") as HTMLElement | null)?.focus?.();
        if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement) el.focus();
        el.closest(".calc-row")?.classList.add("flash");
        setTimeout(() => el.closest(".calc-row")?.classList.remove("flash"), 1600);
      }
      setFocus(null);
    }, 60);
    return () => clearTimeout(t);
  }, [focus, section]);

  const qCodes = useMemo(
    () => new Set(engine ? engine.catalog.questionnaire_groups.flatMap((g) => g.items.map((i) => i.code)) : []),
    [engine],
  );
  function goTo(code: string) {
    setReport(false);
    if (qCodes.has(code) && !FIELD_ID[code]) {
      setSection("questionnaire");
      setFocus(`q-${code}`);
    } else {
      setSection("data");
      setFocus(FIELD_ID[code] ?? `v-${code}`);
    }
  }

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
      const data = JSON.parse(await file.text()) as { format?: string; form?: unknown };
      if (data.format !== FILE_FORMAT || !data.form) throw new Error("это не файл случая LMB BioAge");
      setForm(sanitizeForm(data.form));
      setMsg(`Открыт файл ${file.name}`);
    } catch (e) {
      setMsg("Не удалось открыть файл: " + (e instanceof Error ? e.message : String(e)));
    }
  }

  function loadExample(f: FormState, name: string) {
    setForm(f);
    setReport(false);
    setMsg(`Загружен синтетический пример: ${name}`);
  }

  function clearAll() {
    setForm({ ...EMPTY, encounter_date: today() });
    setReport(false);
    try {
      window.localStorage.removeItem(DRAFT_KEY);
    } catch {
      /* нет хранилища */
    }
    setMsg("Форма очищена");
  }

  const age = form.birth_date && form.encounter_date ? ageOn(form.birth_date, form.encounter_date) : null;
  const facts = [
    { label: "Возраст", value: age !== null && age >= 0 ? `${age} лет` : "—" },
    { label: "Пол", value: form.sex ? (form.sex === "female" ? "Женский" : "Мужской") : "—" },
    { label: "Обследование", value: form.encounter_date ? dateRu(form.encounter_date) : "—" },
  ];
  const qItems = engine ? questionnaireItems(engine.catalog, form) : [];
  const qDone = qItems.filter((i) => form.flags[i.code] && form.flags[i.code] !== "unknown").length;
  const errors = fieldErrors(problems, result);
  const errorCount = [...errors.keys()].length + (problems.some((p) => !p.code) ? 1 : 0);

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">
          LMB <em>BioAge</em>
        </span>
        <div className="topbar-facts" aria-label="Пациент">
          {facts.map((f) => (
            <span key={f.label} className="fact-chip">
              <span className="muted">{f.label}</span> <b className="num">{f.value}</b>
            </span>
          ))}
        </div>
        <div className="topbar-tools">
          {draft && <span className="draft-status muted small" role="status">{draft}</span>}
          {engine && (
            <details className="test-menu">
              <summary>Тестирование</summary>
              <div className="test-menu-body">
                <p className="muted small">Синтетические примеры (данные выдуманы)</p>
                <button type="button" onClick={(e) => { loadExample(EXAMPLE, "старше паспортного"); (e.currentTarget.closest("details") as HTMLDetailsElement).open = false; }}>
                  Пример 1: старше паспортного
                </button>
                <button type="button" onClick={(e) => { loadExample(EXAMPLE_YOUNGER, "моложе паспортного"); (e.currentTarget.closest("details") as HTMLDetailsElement).open = false; }}>
                  Пример 2: моложе паспортного
                </button>
              </div>
            </details>
          )}
        </div>
        {!engine && !loadErr && <span className="topbar-user muted small">{stage}</span>}
      </header>
      <main className="calc-main">
        {loadErr && (
          <Alert>
            Расчётный модуль не загрузился: {loadErr}. Откройте страницу через веб-адрес (http/https), а не как файл
            с диска.
          </Alert>
        )}
        <nav className="tabs" role="tablist" aria-label="Разделы">
          {SECTIONS.map(([key, label], n) => (
            <button key={key} type="button" role="tab" aria-selected={section === key && !report}
              className={section === key && !report ? "tab active" : "tab"} onClick={() => { setReport(false); setSection(key); }}>
              <span className="tab-step">{n + 1}</span> {label}
              {key === "data" && errorCount > 0 && <span className="tab-count" aria-label={`ошибок: ${errorCount}`}>{errorCount}</span>}
              {key === "questionnaire" && engine && <span className="muted small num">{qDone}/{qItems.length}</span>}
            </button>
          ))}
        </nav>

        {!engine && !loadErr && <p className="loading">{stage}</p>}
        <Alert kind="info">{msg}</Alert>

        {engine && section === "data" && !report && (
          <section aria-label="Данные обследования">
            <div className="toolbar calc-toolbar">
              <p className="muted small">
                Данные остаются в этом браузере и никуда не отправляются. Черновик сохраняется автоматически; чтобы
                перенести случай на другой компьютер, сохраните его в файл.
              </p>
              <div className="row">
                <Button onClick={clearAll}>Очистить</Button>
                <Button onClick={() => fileRef.current?.click()}>Открыть файл</Button>
                <Button kind="primary" onClick={save}>Сохранить в файл</Button>
              </div>
              <input ref={fileRef} type="file" accept=".json,application/json" hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void open(f);
                  e.target.value = "";
                }} />
            </div>
            <DataInputs catalog={engine.catalog} form={form} setForm={setForm} setValue={setValue} setFlag={setFlag}
              errors={errors} result={result} />
            <div className="next-row">
              <Button kind="primary" onClick={() => setSection("questionnaire")}>Далее: анкета</Button>
            </div>
          </section>
        )}

        {engine && section === "questionnaire" && !report && (
          <section aria-label="Анкета">
            <p className="muted small">«Не знаю» не считается ответом «нет». Пункты с отметкой «врач» подтверждает врач.</p>
            <Questionnaire catalog={engine.catalog} form={form} setFlag={setFlag} />
            <div className="next-row">
              <Button kind="primary" onClick={() => setSection("results")}>Далее: результаты</Button>
            </div>
          </section>
        )}

        {engine && section === "results" && !report && (
          <section id="profile" aria-label="Результаты">
            {result ? (
              <>
                <div className="toolbar results-toolbar no-print">
                  <span />
                  <Button kind="primary" onClick={() => setReport(true)}>Сформировать отчёт</Button>
                </div>
                <ProfileView result={result} catalog={engine.catalog} goTo={goTo} />
              </>
            ) : (
              <Empty go={() => setSection("data")} />
            )}
          </section>
        )}

        {engine && report && result && (
          <section aria-label="Отчёт">
            <Report result={result} catalog={engine.catalog} facts={facts} onBack={() => setReport(false)} />
          </section>
        )}
      </main>
    </div>
  );
}

/** Применимые вопросы анкеты: производитель денситометра нужен только для FRAX с МПК. */
function questionnaireItems(catalog: Catalog, form: FormState): QItem[] {
  return catalog.questionnaire_groups
    .flatMap((g) => g.items)
    .filter((i) => !NOT_IN_QUESTIONNAIRE.has(i.code) && i.kind !== "frax_list")
    .filter((i) => i.code !== "fn_bmd_device_make" || form.frax.with_bmd === "yes");
}

function Empty({ go }: { go: () => void }) {
  return (
    <div className="panel">
      <h3>Результаты появятся здесь</h3>
      <p className="muted">
        Укажите дату рождения, дату обследования и пол, затем вносите показатели — расчёт обновляется сразу.
        Синтетические примеры — в меню «Тестирование».
      </p>
      <Button kind="primary" onClick={go}>Перейти к данным</Button>
    </div>
  );
}

function FieldError({ list }: { list?: string[] }) {
  if (!list || list.length === 0) return null;
  return (
    <span className="field-error" role="alert">
      {list.join(" ")}
    </span>
  );
}

function DataInputs(props: {
  catalog: Catalog;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  setValue: (code: string, text: string, unit: string) => void;
  setFlag: (code: string, v: string) => void;
  errors: Map<string, string[]>;
  result: EngineResult | null;
}) {
  const { catalog, form, setForm, setValue, setFlag, errors, result } = props;
  const [pending, setPending] = useState<{ code: string; to: string } | null>(null);
  const acr = result?.indices.find((i) => i.code === "acr");
  const has = (c: string) => (form.values[c]?.text ?? "").trim() !== "";
  const bothAcr = has("acr_lab") && (has("u_albumin") || has("u_creatinine"));
  const fraxErr = (c: string) => errors.get(c);
  return (
    <div className="input-grid">
      <section className="card input-card">
        <h3 className="group-title">Пациент и обследование</h3>
        <div className="calc-row">
          <label htmlFor="c-birth">Дата рождения</label>
          <input id="c-birth" type="date" value={form.birth_date} onChange={(e) => setForm((f) => ({ ...f, birth_date: e.target.value }))} />
          <FieldError list={errors.get("birth_date")} />
        </div>
        <div className="calc-row">
          <label htmlFor="c-enc">Дата обследования</label>
          <input id="c-enc" type="date" value={form.encounter_date} onChange={(e) => setForm((f) => ({ ...f, encounter_date: e.target.value }))} />
        </div>
        <div className="calc-row" id="c-sex">
          <span>Пол (для алгоритмов)</span>
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
      </section>

      {catalog.observation_groups.map((g) => (
        <section key={g.title} className="card input-card">
          <h3 className="group-title">{g.title}</h3>
          {g.items.map((d) => {
            const cur = form.values[d.code];
            const opts = unitOptions(d);
            const factors = d.unit_factors ?? {};
            const raw = cur?.unit ?? d.unit_canonical ?? d.allowed_units[0] ?? "";
            // синоним показывается как равнозначная единица из списка (значение то же)
            const unit = opts.includes(raw) ? raw : opts.find((o) => factors[o] !== undefined && factors[o] === factors[raw]) ?? raw;
            const err = errors.get(d.code);
            const isPending = pending?.code === d.code;
            const v = parseNumber(cur?.text ?? "");
            const converted =
              isPending && typeof v === "number" && factors[raw] && factors[pending!.to]
                ? (v * factors[raw]) / factors[pending!.to]
                : null;
            return (
              <div key={d.code} className={err ? "calc-row has-error" : "calc-row"}>
                <label htmlFor={`v-${d.code}`}>{d.name_ru}</label>
                <span className="calc-val">
                  <input
                    id={`v-${d.code}`}
                    inputMode="decimal"
                    aria-invalid={!!err}
                    className={err ? "is-bad" : ""}
                    value={cur?.text ?? ""}
                    onChange={(e) => setValue(d.code, e.target.value, unit)}
                  />
                  {opts.length > 1 ? (
                    <select aria-label={`Единица: ${d.name_ru}`} value={unit}
                      onChange={(e) => {
                        const to = e.target.value;
                        const val = parseNumber(cur?.text ?? "");
                        if (typeof val === "number" && factors[to] !== factors[raw]) setPending({ code: d.code, to });
                        else setValue(d.code, cur?.text ?? "", to);
                      }}>
                      {opts.map((u) => (
                        <option key={u} value={u}>
                          {unitRu(u)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="unit">{unitRu(unit)}</span>
                  )}
                </span>
                {isPending && (
                  <div className="unit-confirm" role="group" aria-label="Смена единицы">
                    <span>
                      Значение {cur?.text} введено в «{unitRu(raw)}». Как сменить единицу на «{unitRu(pending!.to)}»?
                    </span>
                    {converted !== null && (
                      <Button small kind="primary" onClick={() => { setValue(d.code, numText(converted), pending!.to); setPending(null); }}>
                        Пересчитать значение: {numText(converted)}
                      </Button>
                    )}
                    <Button small onClick={() => { setValue(d.code, cur?.text ?? "", pending!.to); setPending(null); }}>
                      Изменить единицу без пересчёта
                    </Button>
                    <Button small onClick={() => setPending(null)}>Отмена</Button>
                  </div>
                )}
                <FieldError list={err} />
              </div>
            );
          })}
          {g.items.some((d) => d.code === "acr_lab") && bothAcr && (
            <div className={acr?.status === "awaiting_review" ? "calc-row q has-error" : "calc-row q"} id="acr-source">
              <span>Источник ACR для расчёта</span>
              <Segmented
                label="Источник ACR"
                value={form.flags.acr_source ?? ""}
                options={[
                  ["lab", "Готовый ACR лаборатории"],
                  ["calculated", "Расчёт по альбумину и креатинину"],
                ]}
                onChange={(v) => setFlag("acr_source", v)}
              />
              {acr && (acr.extra as { acr_lab_mg_mmol?: number }).acr_lab_mg_mmol !== undefined &&
                (acr.extra as { acr_calculated_mg_mmol?: number }).acr_calculated_mg_mmol !== undefined && (
                  <span className="muted small">
                    лаборатория {fmt((acr.extra as { acr_lab_mg_mmol: number }).acr_lab_mg_mmol, 2)} мг/ммоль · расчёт{" "}
                    {fmt((acr.extra as { acr_calculated_mg_mmol: number }).acr_calculated_mg_mmol, 2)} мг/ммоль
                  </span>
                )}
              {acr?.status === "awaiting_review" && (
                <span className="field-error" role="alert">Есть два значения ACR — выберите источник; без выбора ACR и почечный профиль не считаются.</span>
              )}
            </div>
          )}
        </section>
      ))}

      <section className="card input-card">
        <h3 className="group-title">FRAX — результат официального калькулятора</h3>
        <p className="muted small">
          Приложение FRAX не рассчитывает: перенесите оба 10-летних риска из официального калькулятора FRAX (модель
          Казахстана). Риск перелома бедра не может быть больше риска основных переломов.
        </p>
        <div className={fraxErr("frax_major_10y_pct") ? "calc-row has-error" : "calc-row"}>
          <label htmlFor="f-major">Основные остеопоротические переломы</label>
          <span className="calc-val">
            <input id="f-major" inputMode="decimal" aria-invalid={!!fraxErr("frax_major_10y_pct")}
              className={fraxErr("frax_major_10y_pct") ? "is-bad" : ""} value={form.frax.major}
              onChange={(e) => setForm((f) => ({ ...f, frax: { ...f.frax, major: e.target.value } }))} />
            <span className="unit">%</span>
          </span>
          <FieldError list={fraxErr("frax_major_10y_pct")} />
        </div>
        <div className={fraxErr("frax_hip_10y_pct") ? "calc-row has-error" : "calc-row"}>
          <label htmlFor="f-hip">Перелом бедра</label>
          <span className="calc-val">
            <input id="f-hip" inputMode="decimal" aria-invalid={!!fraxErr("frax_hip_10y_pct")}
              className={fraxErr("frax_hip_10y_pct") ? "is-bad" : ""} value={form.frax.hip}
              onChange={(e) => setForm((f) => ({ ...f, frax: { ...f.frax, hip: e.target.value } }))} />
            <span className="unit">%</span>
          </span>
          <FieldError list={fraxErr("frax_hip_10y_pct")} />
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
          <FieldError list={fraxErr("frax_result")} />
        </div>
      </section>
    </div>
  );
}

function Questionnaire({ catalog, form, setFlag }: { catalog: Catalog; form: FormState; setFlag: (code: string, v: string) => void }) {
  const items = new Set(questionnaireItems(catalog, form).map((i) => i.code));
  const qgroups = catalog.questionnaire_groups
    .map((g) => ({ ...g, items: g.items.filter((i) => items.has(i.code)) }))
    .filter((g) => g.items.length > 0);
  return (
    <div className="input-grid">
      {qgroups.map((g) => (
        <section key={g.title} className="card input-card">
          <h3 className="group-title">{g.title}</h3>
          {g.items.map((it) => (
            <QRow key={it.code} it={it} value={form.flags[it.code] ?? ""} onChange={(v) => setFlag(it.code, v)} />
          ))}
        </section>
      ))}
    </div>
  );
}

function QRow({ it, value, onChange }: { it: QItem; value: string; onChange: (v: string) => void }) {
  return (
    <div className="calc-row q" id={`q-${it.code}`}>
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
