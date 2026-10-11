import { useEffect, useRef, type ReactNode } from "react";
import type { Status } from "../types";

// Цвет всегда дублируется знаком и текстом (ТЗ 11.3).
const STATUS: Record<Status, { label: string; mark: string; tone: string }> = {
  calculated: { label: "Рассчитано", mark: "●", tone: "ok" },
  missing_data: { label: "Не хватает данных", mark: "○", tone: "muted" },
  invalid_input: { label: "Ошибка ввода", mark: "✕", tone: "error" },
  not_applicable: { label: "Неприменимо", mark: "⊘", tone: "na" },
  model_not_configured: { label: "Модель не настроена", mark: "◇", tone: "na" },
  integration_not_configured: { label: "Интеграция не подключена", mark: "◇", tone: "na" },
  external_error: { label: "Ошибка внешнего сервиса", mark: "!", tone: "error" },
  awaiting_review: { label: "Требуется подтверждение", mark: "◐", tone: "review" },
  not_included: { label: "Не включено в версию", mark: "–", tone: "na" },
};

export function StatusBadge({ status }: { status: Status }) {
  const s = STATUS[status] ?? { label: status, mark: "?", tone: "muted" };
  return (
    <span className={`badge tone-${s.tone}`}>
      <span aria-hidden="true">{s.mark}</span> {s.label}
    </span>
  );
}

export function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  kind?: "primary" | "ghost" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  small?: boolean;
}) {
  return (
    <button
      type={props.type ?? "button"}
      className={`btn btn-${props.kind ?? "ghost"}${props.small ? " btn-sm" : ""}`}
      onClick={props.onClick}
      disabled={props.disabled}
    >
      {props.children}
    </button>
  );
}

export function Field(props: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{props.label}</span>
      {props.children}
      {props.hint && <span className="field-hint">{props.hint}</span>}
    </label>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "warn"; children: ReactNode }) {
  if (!children) return null;
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Modal(props: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} className="modal" onClose={props.onClose} onCancel={props.onClose}>
      <header className="modal-head">
        <h3>{props.title}</h3>
        <button className="icon-btn" aria-label="Закрыть" onClick={props.onClose}>
          ×
        </button>
      </header>
      <div className="modal-body">{props.children}</div>
    </dialog>
  );
}

export function Loading({ text = "Загрузка…" }: { text?: string }) {
  return <p className="loading">{text}</p>;
}

export function sexLabel(s: string) {
  return s === "female" ? "женский" : "мужской";
}

export function ageOn(birth: string, on: string): number {
  const b = new Date(birth + "T00:00:00");
  const d = new Date(on + "T00:00:00");
  let a = d.getFullYear() - b.getFullYear();
  if (d.getMonth() < b.getMonth() || (d.getMonth() === b.getMonth() && d.getDate() < b.getDate())) a -= 1;
  return a;
}

export function dateRu(iso: string | null | undefined) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}
