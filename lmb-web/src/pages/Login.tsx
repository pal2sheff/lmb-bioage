import { useEffect, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { api, ApiError, setCsrf } from "../api";
import { Alert, Button, Field } from "../components/ui";
import { useSession } from "../session";

export function Login() {
  const { refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const r = await api.post<{ csrf_token: string }>("/auth/login", {
        email,
        password,
        totp: totp.trim() || undefined,
      });
      setCsrf(r.csrf_token);
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Сервер недоступен");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-mark">
        <span className="wordmark">
          LMB <em>BioAge</em>
        </span>
        <p>Кабинет врача клиники Love my body</p>
      </div>
      <form className="auth-card" onSubmit={submit}>
        <h1>Вход</h1>
        <Field label="Электронная почта">
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Пароль">
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        <Field label="Код из приложения-аутентификатора" hint="Шесть цифр. Если второй фактор ещё не подключён, оставьте пустым.">
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            value={totp}
            onChange={(e) => setTotp(e.target.value)}
          />
        </Field>
        <Alert>{err}</Alert>
        <Button kind="primary" type="submit" disabled={busy}>
          {busy ? "Проверяем…" : "Войти"}
        </Button>
      </form>
    </div>
  );
}

export function TotpSetup() {
  const { refresh, logout, me } = useSession();
  const [uri, setUri] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .post<{ otpauth_uri: string; secret: string }>("/auth/totp/enroll")
      .then((r) => {
        setUri(r.otpauth_uri);
        setSecret(r.secret);
        return QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 220 });
      })
      .then(setQr)
      .catch((e) => setErr(e instanceof ApiError ? e.message : "Ошибка"));
  }, []);

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await api.post("/auth/totp/confirm", { code: code.trim() });
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-mark">
        <span className="wordmark">
          LMB <em>BioAge</em>
        </span>
        <p>{me?.full_name}</p>
      </div>
      <form className="auth-card" onSubmit={confirm}>
        <h1>Второй фактор</h1>
        <p className="lead">
          Для доступа к медицинским данным подключите приложение-аутентификатор: отсканируйте код и введите шесть цифр.
        </p>
        {qr && <img className="qr" src={qr} alt="QR-код для приложения-аутентификатора" />}
        {uri && (
          <p className="mono small">
            Ключ вручную: <strong>{secret}</strong>
          </p>
        )}
        <Field label="Код из приложения">
          <input inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} required />
        </Field>
        <Alert>{err}</Alert>
        <div className="row">
          <Button kind="primary" type="submit">
            Подтвердить
          </Button>
          <Button onClick={() => void logout()}>Выйти</Button>
        </div>
      </form>
    </div>
  );
}
