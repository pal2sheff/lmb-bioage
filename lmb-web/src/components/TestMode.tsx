// Переключатель исследовательского расчёта (решение владельца 11.10.2026): явный, по умолчанию включён.
// Состояние запоминается в этом браузере — удобство врача, не настройка модели.
import { useState } from "react";

const KEY = "lmb.researchMode";

export function useResearchMode(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(KEY) !== "0";
    } catch {
      return true;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      window.localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      /* хранилище недоступно — режим действует до перезагрузки */
    }
  };
  return [on, set];
}

export function ResearchToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="research-toggle no-print">
      <span className="switch">
        <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)}
          aria-label="Исследовательский режим" />
        <span />
      </span>
      Исследовательский режим
    </label>
  );
}

const CHECK_KEY = "lmb.cardioCheck";

/** Проверочный расчёт Cardio — включается явно, по умолчанию выключен. */
export function useCardioCheck(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(CHECK_KEY) === "1";
    } catch {
      return false;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      window.localStorage.setItem(CHECK_KEY, v ? "1" : "0");
    } catch {
      /* хранилище недоступно */
    }
  };
  return [on, set];
}
