import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { Alert, Loading, ageOn, dateRu, sexLabel } from "../components/ui";
import { Observations } from "../components/Observations";
import { Questionnaire } from "../components/Questionnaire";
import { Frax } from "../components/Frax";
import { Profile } from "../components/Profile";
import type { EncounterT, Patient } from "../types";

const TABS = [
  ["data", "Анализы и измерения"],
  ["questionnaire", "Анкета"],
  ["frax", "FRAX"],
  ["profile", "Профиль"],
] as const;

export function Encounter() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") ?? "data";
  const [enc, setEnc] = useState<EncounterT | null>(null);
  const [p, setP] = useState<Patient | null>(null);
  const [err, setErr] = useState("");
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    api
      .get<EncounterT>(`/encounters/${id}`)
      .then(async (e) => {
        setEnc(e);
        setP(await api.get<Patient>(`/patients/${e.patient_id}`));
      })
      .catch((e) => setErr(e instanceof ApiError ? e.message : "Ошибка"));
  }, [id]);

  if (!enc || !p) return err ? <Alert>{err}</Alert> : <Loading />;
  return (
    <section className="page">
      <nav className="crumbs">
        <Link to="/">Пациенты</Link> <span>/</span>{" "}
        <Link to={`/patients/${p.id}`}>
          {p.last_name} {p.first_name}
        </Link>{" "}
        <span>/</span> <span>визит {dateRu(enc.encounter_date)}</span>
      </nav>
      <header className="page-head">
        <div>
          <p className="eyebrow">Обследование · {dateRu(enc.encounter_date)}</p>
          <h1>
            {p.last_name} {p.first_name}
          </h1>
          <p className="facts">
            <span>возраст на дату обследования: {ageOn(p.birth_date, enc.encounter_date)}</span>
            <span>пол: {sexLabel(p.sex_at_birth)}</span>
          </p>
        </div>
      </header>
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            className={tab === k ? "tab active" : "tab"}
            onClick={() => setSp({ tab: k })}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="tab-body">
        {tab === "data" && <Observations encounterId={enc.id} onChange={bump} />}
        {tab === "questionnaire" && <Questionnaire encounterId={enc.id} onChange={bump} />}
        {tab === "frax" && <Frax encounterId={enc.id} version={version} />}
        {tab === "profile" && <Profile encounterId={enc.id} />}
      </div>
    </section>
  );
}
