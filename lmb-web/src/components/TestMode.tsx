// Переключатель исследовательского расчёта (решение владельца 11.10.2026): явный, по умолчанию включён.
// С 11.10.2026 (21:24) находится в разделе «О методике»; основной экран показывает оценку и графики без переключателей.
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
          aria-label="Расчётная оценка LMB и инфографика" />
        <span />
      </span>
      Расчётная оценка LMB и инфографика (локальный тестовый режим)
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

const MUSCLE_KEY = "lmb.muscleTest";

/** Мышечный возраст (модель 0.1-synthetic) — только в режиме тестирования, по умолчанию выключен
 *  (решение владельца 12.10.2026, 22:05). В обычном режиме показываются исходные измерения и ASMI. */
export function useMuscleTest(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(MUSCLE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      window.localStorage.setItem(MUSCLE_KEY, v ? "1" : "0");
    } catch {
      /* хранилище недоступно */
    }
  };
  return [on, set];
}

export function MuscleTestToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="research-toggle no-print">
      <span className="switch">
        <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)}
          aria-label="Мышечный возраст (тестирование)" />
        <span />
      </span>
      Мышечный возраст (тестирование, модель 0.1-synthetic)
    </label>
  );
}
