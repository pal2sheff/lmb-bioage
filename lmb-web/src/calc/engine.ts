// Загрузка расчётного модуля lmb_engine в браузер через Pyodide (Python, собранный в WebAssembly).
// Используется тот же Python-код и та же конфигурация модели, что и на сервере.
import type { Catalog } from "../types";
import type { EngineResult } from "../components/ProfileView";

export interface EngineMeta {
  engine_version: string;
  model_version: string;
  model_config_sha256: string;
}

export interface CalcCase {
  birth_date: string;
  encounter_date: string;
  sex: "female" | "male" | "";
  measurements: Record<string, { value: number; unit: string; qualifier?: "lt" | "gt" }>;
  flags: Record<string, string>;
  frax: { major: number; hip: number; with_bmd: boolean; inputs_bound: boolean } | null;
}

/** Строка предложения импорта анализов (lmb_engine.labimport.candidates). */
export interface LabItem {
  row: number;
  name: string;
  comparator: "" | "<" | ">";
  value: string;
  unit_raw: string | null;
  unit: string | null;
  date: string | null;
  code: string;
  field: string;
  status: "ok" | "check" | "skip";
  reason: string;
  selected: boolean;
  transferable: boolean;
  alternative: boolean;
  date_differs: boolean;
  duplicate?: string;
}
export interface LabImport {
  items: LabItem[];
  unmatched: string[];
  doc_date: string | null;
  lqone_doc: boolean;
  error?: string;
}

export interface Engine {
  meta: EngineMeta;
  catalog: Catalog;
  calculate: (c: CalcCase) => EngineResult;
  labImport: (p: { name?: string; b64?: string; lines?: string[]; encounter_date: string }) => LabImport;
}

interface PyodideLike {
  FS: { mkdirTree: (p: string) => void; writeFile: (p: string, d: Uint8Array) => void };
  runPython: (code: string) => unknown;
  globals: { get: (name: string) => { calculate: (s: string) => string; lab_import: (s: string) => string } };
}

const base = import.meta.env.BASE_URL; // «./» — работает по любому адресу публикации

async function fetchBytes(path: string): Promise<Uint8Array> {
  const r = await fetch(base + path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`Не загружен файл ${path} (HTTP ${r.status})`);
  return new Uint8Array(await r.arrayBuffer());
}

export async function loadEngine(onStage: (text: string) => void): Promise<Engine> {
  onStage("Загрузка среды Python…");
  const pyodideUrl = new URL(base + "pyodide/pyodide.mjs", window.location.href).href;
  const mod = (await import(/* @vite-ignore */ pyodideUrl)) as {
    loadPyodide: (o: { indexURL: string }) => Promise<PyodideLike>;
  };
  const py = await mod.loadPyodide({ indexURL: new URL(base + "pyodide/", window.location.href).href });

  onStage("Загрузка расчётного модуля…");
  const manifest = JSON.parse(new TextDecoder().decode(await fetchBytes("engine/manifest.json"))) as EngineMeta & {
    files: { path: string }[];
  };
  for (const f of manifest.files) {
    const dst = "/lmb/" + f.path;
    py.FS.mkdirTree(dst.substring(0, dst.lastIndexOf("/")));
    py.FS.writeFile(dst, await fetchBytes("engine/" + f.path));
  }
  py.runPython("import sys\nsys.path.insert(0, '/lmb')\nimport bridge");
  const bridge = py.globals.get("bridge");
  const catalog = JSON.parse(new TextDecoder().decode(await fetchBytes("engine/catalog.json"))) as Catalog;
  return {
    meta: {
      engine_version: manifest.engine_version,
      model_version: manifest.model_version,
      model_config_sha256: manifest.model_config_sha256,
    },
    catalog,
    calculate: (c) => JSON.parse(bridge.calculate(JSON.stringify(c))) as EngineResult,
    labImport: (p) => JSON.parse(bridge.lab_import(JSON.stringify(p))) as LabImport,
  };
}
