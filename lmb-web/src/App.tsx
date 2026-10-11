import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "./components/ui";
import { Encounter } from "./pages/Encounter";
import { Login, TotpSetup } from "./pages/Login";
import { PatientCard } from "./pages/PatientCard";
import { Patients } from "./pages/Patients";
import { SessionProvider, useSession } from "./session";

function Shell() {
  const { me, ready, needTotp, catalog, logout } = useSession();
  if (!ready) return <Loading />;
  if (!me) return <Login />;
  if (needTotp) return <TotpSetup />;
  if (!catalog) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1>Нет доступа</h1>
          <p>Кабинет врача доступен пользователям с ролью «врач».</p>
          <button className="btn btn-ghost" onClick={() => void logout()}>
            Выйти
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="wordmark">
          LMB <em>BioAge</em>
        </Link>
        <span className="research-flag">Исследовательская модель · не валидирована</span>
        <div className="topbar-user">
          <span>{me.full_name}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => void logout()}>
            Выйти
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Patients />} />
          <Route path="/patients/:id" element={<PatientCard />} />
          <Route path="/encounters/:id" element={<Encounter />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <Shell />
      </SessionProvider>
    </BrowserRouter>
  );
}
