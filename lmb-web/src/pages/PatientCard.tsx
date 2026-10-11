import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, idem } from "../api";
import { Alert, Button, Field, Loading, ageOn, dateRu, sexLabel } from "../components/ui";
import type { EncounterT, Patient } from "../types";

export function PatientCard() {
  const { id } = useParams();
  const nav = useNavigate();
  const [p, setP] = useState<Patient | null>(null);
  const [encs, setEncs] = useState<EncounterT[]>([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([api.get<Patient>(`/patients/${id}`), api.get<EncounterT[]>(`/patients/${id}/encounters`)])
      .then(([pp, ee]) => {
        setP(pp);
        setEncs(ee);
      })
      .catch((e) => setErr(e instanceof ApiError ? e.message : "Ошибка"));
  }, [id]);

  async function newEncounter() {
    setErr("");
    try {
      const e = await api.post<EncounterT>(`/patients/${id}/encounters`, { encounter_date: date }, idem());
      nav(`/encounters/${e.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  if (!p) return err ? <Alert>{err}</Alert> : <Loading />;
  const today = new Date().toISOString().slice(0, 10);
  return (
    <section className="page">
      <nav className="crumbs">
        <Link to="/">Пациенты</Link> <span>/</span> <span>карточка</span>
      </nav>
      <header className="page-head patient-head">
        <div>
          <p className="eyebrow mono">{p.pseudonym_code}</p>
          <h1>
            {p.last_name} {p.first_name} {p.middle_name ?? ""}
          </h1>
          <p className="facts">
            <span>{dateRu(p.birth_date)}</span>
            <span>{ageOn(p.birth_date, today)} лет</span>
            <span>пол: {sexLabel(p.sex_at_birth)}</span>
            {p.iin_masked && <span className="mono">ИИН {p.iin_masked}</span>}
            {p.phone && <span>{p.phone}</span>}
          </p>
        </div>
      </header>
      <div className="two-col">
        <div>
          <h2 className="section-title">Обследования</h2>
          {encs.length === 0 && <p className="empty">Обследований пока нет.</p>}
          <ol className="timeline">
            {encs.map((e) => (
              <li key={e.id}>
                <Link to={`/encounters/${e.id}`}>
                  <span className="num">{dateRu(e.encounter_date)}</span>
                  <span className="muted">возраст на дату: {ageOn(p.birth_date, e.encounter_date)}</span>
                </Link>
              </li>
            ))}
          </ol>
        </div>
        <aside className="panel">
          <h3>Новое обследование</h3>
          <Field label="Дата обследования" hint="От неё считается возраст во всех индексах">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Alert>{err}</Alert>
          <Button kind="primary" onClick={() => void newEncounter()}>
            Открыть визит
          </Button>
        </aside>
      </div>
    </section>
  );
}
