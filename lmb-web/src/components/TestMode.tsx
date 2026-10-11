// Режим тестирования (решение владельца 11.10.2026): показывает контрольный PhenoAge рядом с
// биологическим возрастом LMB. Состояние запоминается в этом браузере (удобство, не настройка модели).
import { useState } from "react";

const KEY = "lmb.testMode";

export function useTestMode(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(KEY) === "1";
    } catch {
      return false;
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

export function TestModeToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="research-toggle no-print">
      <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span>
        Режим тестирования <span className="muted small">— контрольный PhenoAge для сверки расчёта</span>
      </span>
    </label>
  );
}
