// Клиент API: cookie сеанса + заголовок CSRF. Технические ответы сервера переводятся в понятный текст.

let csrf: string | null = null;

export function setCsrf(token: string | null) {
  csrf = token;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : describe(detail));
    this.status = status;
    this.detail = detail;
  }
}

function describe(detail: unknown): string {
  if (Array.isArray(detail)) {
    // ошибки валидации FastAPI
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const d = detail as { status?: string; problems?: string[] };
    if (d.problems) return d.problems.join("; ");
  }
  return "Ошибка запроса";
}

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const h: Record<string, string> = { Accept: "application/json", ...headers };
  const isForm = body instanceof FormData;
  // для FormData браузер сам выставляет multipart/form-data с границей
  if (body !== undefined && !isForm) h["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) h["X-CSRF-Token"] = csrf;
  const r = await fetch(`/api/v1${path}`, {
    method,
    headers: h,
    credentials: "same-origin",
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  let data: unknown = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail ?? `HTTP ${r.status}`;
    throw new ApiError(r.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown, h?: Record<string, string>) => request<T>("POST", p, b ?? {}, h),
  put: <T,>(p: string, b?: unknown) => request<T>("PUT", p, b),
  patch: <T,>(p: string, b?: unknown, h?: Record<string, string>) => request<T>("PATCH", p, b, h),
  /** Загрузка файла на сервер клиники (хранится только на его диске, зашифрованным). */
  upload: <T,>(p: string, file: File, fields: Record<string, string>) => {
    const fd = new FormData();
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
    fd.append("file", file);
    return request<T>("POST", p, fd);
  },
};

/** Адрес скачивания вложения: сервер расшифровывает файл и отдаёт его с запретом кеширования. */
export function attachmentUrl(id: string): string {
  return `/api/v1/attachments/${id}`;
}

export function idem(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

/** Число с десятичной запятой или точкой; пустое поле — null, а не 0. */
export function parseNumber(s: string): number | null | "invalid" {
  const t = s.trim().replace(/\s/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : "invalid";
}

export function fmt(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
