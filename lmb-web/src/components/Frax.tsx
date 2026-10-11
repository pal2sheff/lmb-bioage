import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, attachmentUrl, fmt, idem, parseNumber } from "../api";
import { useSession } from "../session";
import type { Attachment, FraxInputs, FraxJob } from "../types";
import { Alert, Button, Field, dateRu } from "./ui";

const ERR: Record<string, string> = {
  auth_failed: "ошибка авторизации",
  quota_exhausted: "исчерпан лимит",
  rate_limited: "превышена частота запросов",
  timeout: "истекло время ожидания",
  network_error: "сетевая ошибка",
  bad_request: "сервис отклонил запрос",
  unsupported_country_model: "неподдерживаемая модель страны",
  unit_mismatch: "несоответствие единиц",
  response_schema_invalid: "некорректный ответ сервиса",
  provider_unavailable: "сервис недоступен",
  mapping_not_verified: "сопоставление полей API не подтверждено",
};
const JOB_STATUS: Record<string, string> = {
  queued: "в очереди",
  running: "выполняется",
  calculated: "получен",
  external_error: "ошибка",
  integration_not_configured: "интеграция не подключена",
};

export function Frax({ encounterId, version }: { encounterId: string; version: number }) {
  const { catalog } = useSession();
  const [inputs, setInputs] = useState<FraxInputs | null>(null);
  const [jobs, setJobs] = useState<FraxJob[]>([]);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(async () => {
    try {
      const [i, j] = await Promise.all([
        api.get<FraxInputs>(`/encounters/${encounterId}/frax/inputs`),
        api.get<FraxJob[]>(`/encounters/${encounterId}/frax-jobs`),
      ]);
      setInputs(i);
      setJobs(j.reverse());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }, [encounterId]);

  useEffect(() => {
    void load();
  }, [load, version]);

  const names: Record<string, string> = {};
  catalog?.observation_groups.forEach((g) => g.items.forEach((d) => (names[d.code] = d.name_ru)));
  catalog?.questionnaire_groups.forEach((g) => g.items.forEach((q) => (names[q.code] = q.name)));

  async function request() {
    setErr("");
    setInfo("");
    try {
      const j = await api.post<FraxJob & { created: boolean }>(`/encounters/${encounterId}/frax-jobs`, {}, idem());
      setInfo(
        j.status === "integration_not_configured"
          ? "Автоматический запрос недоступен: интеграция с FRAX не подключена. Используйте ручной ввод."
          : j.created
            ? "Запрос поставлен в очередь"
            : "Для этих данных запрос уже есть — лимит не расходуется",
      );
      if (j.quota_warning) setInfo(j.quota_warning);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  async function act(path: string) {
    setErr("");
    try {
      await api.post(path);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  if (!inputs) return null;
  const req = inputs.request as null | {
    age_years: number;
    sex: string;
    bmi_kg_m2: number;
    risk_factors: Record<string, string>;
    fn_bmd: null | { kind: string; value: number; device_make?: string };
  };

  return (
    <div className="frax">
      <div className="two-col">
        <section className="panel">
          <h3>Что будет отправлено</h3>
          <p className="muted small">
            Только расчётные признаки: без ФИО, ИИН, даты рождения и идентификаторов. Модель: Казахстан.
          </p>
          {inputs.status === "ready" && req ? (
            <dl className="kv">
              <dt>Возраст</dt>
              <dd className="num">{req.age_years}</dd>
              <dt>Пол</dt>
              <dd>{req.sex === "female" ? "женский" : "мужской"}</dd>
              <dt>ИМТ</dt>
              <dd className="num">{fmt(req.bmi_kg_m2, 1)} кг/м²</dd>
              {Object.entries(req.risk_factors).map(([k, v]) => (
                <div key={k} className="kv-pair">
                  <dt>{names[k] ?? k}</dt>
                  <dd>{v === "yes" ? "да" : "нет"}</dd>
                </div>
              ))}
              <dt>МПК шейки бедра</dt>
              <dd>
                {req.fn_bmd
                  ? req.fn_bmd.kind === "t_score"
                    ? `T = ${fmt(req.fn_bmd.value, 1)}`
                    : `${fmt(req.fn_bmd.value, 3)} г/см² (${req.fn_bmd.device_make})`
                  : "нет — расчёт без МПК"}
              </dd>
            </dl>
          ) : (
            <Alert kind="warn">
              <strong>Запрос невозможен:</strong>{" "}
              {inputs.status === "not_applicable" ? "неприменимо" : inputs.status === "missing_data" ? "не хватает данных" : "проверьте данные"}
              <ul>
                {inputs.problems.map((p) => (
                  <li key={p}>{names[p] ?? p}</li>
                ))}
              </ul>
            </Alert>
          )}
          <div className="row">
            <Button kind="primary" onClick={() => void request()} disabled={inputs.status !== "ready"}>
              Запросить FRAX
            </Button>
            <span className="muted small">
              Провайдер:{" "}
              {inputs.provider === "not_configured" ? "не настроен — используйте ручной ввод" : inputs.provider}
            </span>
          </div>
          <Alert kind="info">{info}</Alert>
          <Alert>{err}</Alert>
        </section>
        <ManualEntry
          encounterId={encounterId}
          blockedReason={inputs.status === "not_applicable" ? inputs.problems.join("; ") : ""}
          inputsReady={inputs.status === "ready"}
          withBmd={!!req?.fn_bmd}
          onDone={load}
        />
      </div>

      <h3 className="group-title">Результаты и запросы</h3>
      {jobs.length === 0 && <p className="empty">Запросов пока не было.</p>}
      {jobs.length > 0 && (
        <table className="ledger">
          <thead>
            <tr>
              <th>Источник</th>
              <th>Статус</th>
              <th className="num">Основные переломы, 10 лет</th>
              <th className="num">Перелом бедра, 10 лет</th>
              <th>МПК</th>
              <th>Входы</th>
              <th>Файл</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className={j.is_active_choice ? "is-active" : ""}>
                <td>
                  {j.source === "manual" ? "ручной ввод" : "автоматический"}
                  {j.manual_calculated_on && <span className="muted small"> · {dateRu(j.manual_calculated_on)}</span>}
                  {j.manual_source_note && <div className="muted small">{j.manual_source_note}</div>}
                </td>
                <td>
                  {JOB_STATUS[j.status] ?? j.status}
                  {j.error_code && <span className="muted small"> · {ERR[j.error_code] ?? j.error_code}</span>}
                </td>
                <td className="num strong">{j.frax_major_10y_pct === null ? "—" : `${fmt(j.frax_major_10y_pct, 1)} %`}</td>
                <td className="num strong">{j.frax_hip_10y_pct === null ? "—" : `${fmt(j.frax_hip_10y_pct, 1)} %`}</td>
                <td>{j.with_bmd === null ? "—" : j.with_bmd ? "с МПК" : "без МПК"}</td>
                <td>
                  {!j.inputs_bound ? (
                    <span className="tone-review" title="Факторы риска в системе были заполнены не полностью">
                      анкета неполная
                    </span>
                  ) : j.inputs_current ? (
                    "текущие"
                  ) : (
                    <span className="tone-review">устарели</span>
                  )}
                </td>
                <td>
                  {j.attachment_id ? (
                    <a href={attachmentUrl(j.attachment_id)} download>
                      скачать
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <div className="row-actions">
                    {j.is_active_choice && <span className="badge tone-ok">● действует</span>}
                    {!j.is_active_choice && j.status === "calculated" && j.inputs_current && (
                      <Button small onClick={() => void act(`/frax-jobs/${j.id}/activate`)}>
                        Сделать действующим
                      </Button>
                    )}
                    {j.status === "external_error" && j.inputs_current && (
                      <Button small onClick={() => void act(`/frax-jobs/${j.id}/retry`)}>
                        Повторить
                      </Button>
                    )}
                    {j.conflict_note && <span className="muted small">{j.conflict_note}</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">
        FRAX не используется для оценки эффективности лечения остеопороза и постановки целей терапии.
      </p>
    </div>
  );
}

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";

function ManualEntry(props: {
  encounterId: string;
  blockedReason: string;
  inputsReady: boolean;
  withBmd: boolean;
  onDone: () => Promise<void>;
}) {
  const [major, setMajor] = useState("");
  const [hip, setHip] = useState("");
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("Официальный калькулятор FRAX, модель Казахстана");
  const [bmdChoice, setBmdChoice] = useState<boolean | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploaded, setUploaded] = useState<{ file: File; id: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const disabled = !!props.blockedReason || busy;
  // если данные визита полные, признак «с МПК» берётся из них; иначе врач выбирает явно
  const withBmd = props.inputsReady ? props.withBmd : bmdChoice;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setOk("");
    const m = parseNumber(major);
    const h = parseNumber(hip);
    if (typeof m !== "number" || typeof h !== "number") return setErr("Укажите оба риска числом");
    if (withBmd === null) return setErr("Укажите, рассчитан ли результат с МПК шейки бедра");
    setBusy(true);
    try {
      let attachmentId: string | null = null;
      if (file) {
        // повторная отправка формы не загружает тот же файл второй раз
        if (uploaded && uploaded.file === file) attachmentId = uploaded.id;
        else {
          const a = await api.upload<Attachment>(`/encounters/${props.encounterId}/attachments`, file, {
            kind: "frax_result",
          });
          setUploaded({ file, id: a.id });
          attachmentId = a.id;
        }
      }
      await api.post(
        `/encounters/${props.encounterId}/frax-manual`,
        {
          frax_major_10y_pct: m,
          frax_hip_10y_pct: h,
          with_bmd: withBmd,
          calculated_on: on,
          national_model: "Kazakhstan",
          source_note: note,
          attachment_id: attachmentId,
        },
        idem(),
      );
      setOk(file ? "Результат внесён и подтверждён, файл сохранён на сервере клиники" : "Результат внесён и подтверждён");
      setMajor("");
      setHip("");
      setFile(null);
      setUploaded(null);
      setBmdChoice(null);
      (e.target as HTMLFormElement).reset();
      await props.onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h3>Ручной ввод официального результата</h3>
      <p className="muted small">
        Перенесите оба 10-летних риска из официального калькулятора FRAX (модель Казахстана). Ввод доступен и без
        заполненной анкеты.
      </p>
      {props.blockedReason && <Alert kind="warn">{props.blockedReason}</Alert>}
      {!props.blockedReason && !props.inputsReady && (
        <Alert kind="info">
          Факторы риска в системе заполнены не полностью: результат будет сохранён для визита с пометкой «анкета
          неполная» и не устареет при её заполнении.
        </Alert>
      )}
      <div className="grid-form">
        <Field label="Основные остеопоротические переломы, %">
          <input inputMode="decimal" value={major} onChange={(e) => setMajor(e.target.value)} disabled={disabled} />
        </Field>
        <Field label="Перелом бедра, %">
          <input inputMode="decimal" value={hip} onChange={(e) => setHip(e.target.value)} disabled={disabled} />
        </Field>
        <Field label="Дата расчёта">
          <input type="date" value={on} onChange={(e) => setOn(e.target.value)} disabled={disabled} />
        </Field>
        {props.inputsReady ? (
          <Field label="Расчёт">
            <input value={props.withBmd ? "с МПК шейки бедра" : "без МПК"} disabled />
          </Field>
        ) : (
          <div className="field">
            <span className="field-label">Расчёт</span>
            <div className="segmented" role="radiogroup" aria-label="Расчёт с МПК">
              {[
                [false, "без МПК"],
                [true, "с МПК"],
              ].map(([v, label]) => (
                <button
                  key={String(v)}
                  type="button"
                  role="radio"
                  aria-checked={bmdChoice === v}
                  className={bmdChoice === v ? "seg on" : "seg"}
                  onClick={() => setBmdChoice(v as boolean)}
                  disabled={disabled}
                >
                  {label as string}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="span-2">
          <Field label="Источник">
            <input value={note} onChange={(e) => setNote(e.target.value)} disabled={disabled} />
          </Field>
        </div>
        <div className="span-2">
          <div className="field">
            <span className="field-label" id="frax-file-label">
              Файл результата (PDF, PNG или JPEG)
            </span>
            <label className={disabled ? "file-pick is-disabled" : "file-pick"}>
              <input
                type="file"
                accept={ACCEPT}
                aria-labelledby="frax-file-label"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                disabled={disabled}
              />
              <span className="btn btn-ghost btn-sm">Выбрать файл</span>
              <span className={file ? "file-name" : "file-name muted"}>{file ? file.name : "файл не выбран"}</span>
            </label>
            <span className="field-hint">Необязательно. Файл хранится только на сервере клиники в зашифрованном виде.</span>
          </div>
        </div>
      </div>
      <Alert>{err}</Alert>
      <Alert kind="info">{ok}</Alert>
      <Button kind="primary" type="submit" disabled={disabled}>
        {busy ? "Сохранение…" : "Внести и подтвердить"}
      </Button>
    </form>
  );
}
