// Импорт анализов в браузере: файл не покидает компьютер.
// CSV и XLSX разбирает расчётный модуль (Python, Pyodide); у PDF читается текстовый слой (pdf.js),
// строки передаются тому же модулю. Сканы и изображения не распознаются — нужен ручной перенос.
import type { Engine, LabImport } from "./engine";

const SCAN_MESSAGE =
  "В файле нет текстового слоя (скан или изображение). Автоматическое распознавание сканов не выполняется — перенесите значения вручную.";

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

interface TextItem {
  str: string;
  transform: number[];
  width: number;
  height: number;
}

/** Текстовый слой PDF → строки; крупный промежуток между фрагментами становится табуляцией (граница ячейки). */
async function pdfLines(buf: ArrayBuffer): Promise<string[]> {
  const pdfjs = await import("pdfjs-dist");
  const worker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
  pdfjs.GlobalWorkerOptions.workerSrc = worker;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(buf), disableFontFace: true }).promise;
  const lines: string[] = [];
  for (let p = 1; p <= doc.numPages; p++) {
    const page = await doc.getPage(p);
    const tc = await page.getTextContent();
    const items = (tc.items as TextItem[]).filter((i) => typeof i.str === "string" && i.str.trim() !== "");
    items.sort((a, b) => b.transform[5] - a.transform[5] || a.transform[4] - b.transform[4]);
    let cur: TextItem[] = [];
    const flush = () => {
      if (!cur.length) return;
      cur.sort((a, b) => a.transform[4] - b.transform[4]);
      let line = "";
      let end = -Infinity;
      for (const it of cur) {
        const x = it.transform[4];
        const gap = x - end;
        const h = Math.abs(it.height || it.transform[3] || 10);
        if (line) line += gap > Math.max(5, h * 0.6) ? "\t" : gap > 0.5 ? " " : "";
        line += it.str;
        end = x + it.width;
      }
      lines.push(line);
      cur = [];
    };
    for (const it of items) {
      if (cur.length && Math.abs(cur[0].transform[5] - it.transform[5]) > 2.5) flush();
      cur.push(it);
    }
    flush();
  }
  await doc.destroy();
  return lines;
}

export async function readLabFile(file: File, engine: Engine, encounterDate: string): Promise<LabImport> {
  const name = file.name.toLowerCase();
  const buf = await file.arrayBuffer();
  if (/\.(png|jpe?g|tiff?|bmp|gif|heic|webp)$/.test(name)) return { items: [], unmatched: [], doc_date: null, lqone_doc: false, error: SCAN_MESSAGE };
  if (name.endsWith(".pdf")) {
    let lines: string[];
    try {
      lines = await pdfLines(buf);
    } catch (e) {
      return { items: [], unmatched: [], doc_date: null, lqone_doc: false, error: "PDF не открылся: " + (e instanceof Error ? e.message : String(e)) };
    }
    const letters = lines.join(" ").replace(/[^A-Za-zА-Яа-яЁё]/g, "").length;
    if (letters < 20) return { items: [], unmatched: [], doc_date: null, lqone_doc: false, error: SCAN_MESSAGE };
    return engine.labImport({ lines, encounter_date: encounterDate });
  }
  if (/\.(csv|txt|xlsx)$/.test(name)) return engine.labImport({ name: file.name, b64: toBase64(buf), encounter_date: encounterDate });
  if (name.endsWith(".xls"))
    return { items: [], unmatched: [], doc_date: null, lqone_doc: false, error: "Старый формат XLS не читается — сохраните таблицу как XLSX или CSV" };
  return { items: [], unmatched: [], doc_date: null, lqone_doc: false, error: "Поддерживаются PDF (с текстовым слоем), XLSX и CSV" };
}
