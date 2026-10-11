import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, idem } from "../api";
import { Alert, Button, Field, Modal, dateRu, sexLabel } from "../components/ui";
import type { Patient } from "../types";

export function Patients() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Patient[] | null>(null);
  const [err, setErr] = useState("");
  const [creating, setCreating] = useState(false);

  async function search(q: string) {
    setErr("");
    try {
      const isIin = /^\d{12}$/.test(q.trim());
      const path = isIin ? `/patients?iin=${q.trim()}` : `/patients?query=${encodeURIComponent(q.trim())}`;
      setRows(await api.get<Patient[]>(path));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  useEffect(() => {
    void search("");
  }, []);

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Регистр</p>
          <h1>Пациенты</h1>
        </div>
        <Button kind="primary" onClick={() => setCreating(true)}>
          Новый пациент
        </Button>
      </header>
      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          void search(query);
        }}
      >
        <input
          placeholder="Полная фамилия или ИИН (12 цифр)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Поиск пациента"
        />
        <Button type="submit">Найти</Button>
      </form>
      <p className="muted small">
        ФИО хранится в зашифрованном виде, поэтому поиск идёт по полной фамилии (без учёта регистра и «ё/е») или по ИИН.
        Пустой запрос показывает последние 50 карточек.
      </p>
      <Alert>{err}</Alert>
      {rows && rows.length === 0 && <p className="empty">Пациенты не найдены.</p>}
      {rows && rows.length > 0 && (
        <table className="ledger">
          <thead>
            <tr>
              <th>Пациент</th>
              <th>Дата рождения</th>
              <th>Пол</th>
              <th>Код</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>
                  <Link to={`/patients/${p.id}`} className="strong-link">
                    {p.last_name} {p.first_name} {p.middle_name ?? ""}
                  </Link>
                </td>
                <td className="num">{dateRu(p.birth_date)}</td>
                <td>{sexLabel(p.sex_at_birth)}</td>
                <td className="mono muted">{p.pseudonym_code}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {creating && <CreatePatient onClose={() => setCreating(false)} />}
    </section>
  );
}

function CreatePatient({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [f, setF] = useState({
    last_name: "",
    first_name: "",
    middle_name: "",
    iin: "",
    birth_date: "",
    sex_at_birth: "",
    phone: "",
    email: "",
  });
  const [err, setErr] = useState("");
  const [key] = useState(idem);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === "" ? null : v.trim()]));
    try {
      const p = await api.post<Patient>("/patients", body, key);
      nav(`/patients/${p.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  return (
    <Modal title="Новый пациент" onClose={onClose}>
      <form className="grid-form" onSubmit={submit}>
        <Field label="Фамилия">
          <input value={f.last_name} onChange={set("last_name")} required />
        </Field>
        <Field label="Имя">
          <input value={f.first_name} onChange={set("first_name")} required />
        </Field>
        <Field label="Отчество">
          <input value={f.middle_name} onChange={set("middle_name")} />
        </Field>
        <Field label="ИИН" hint="Хранится в зашифрованном виде">
          <input inputMode="numeric" maxLength={12} value={f.iin} onChange={set("iin")} />
        </Field>
        <Field label="Дата рождения">
          <input type="date" value={f.birth_date} onChange={set("birth_date")} required />
        </Field>
        <Field label="Пол (для алгоритмов)">
          <select value={f.sex_at_birth} onChange={set("sex_at_birth")} required>
            <option value="">—</option>
            <option value="female">женский</option>
            <option value="male">мужской</option>
          </select>
        </Field>
        <Field label="Телефон">
          <input value={f.phone} onChange={set("phone")} />
        </Field>
        <Field label="Электронная почта">
          <input type="email" value={f.email} onChange={set("email")} />
        </Field>
        <div className="span-2">
          <Alert>{err}</Alert>
          <div className="row">
            <Button kind="primary" type="submit">
              Создать карточку
            </Button>
            <Button onClick={onClose}>Отмена</Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
