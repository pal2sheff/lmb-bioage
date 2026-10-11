import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Браузерный калькулятор: статический сайт без сервера. Расчёт — lmb_engine в Pyodide.
// Перед сборкой: python3 scripts/export_engine_bundle.py (готовит calc-public/).
export default defineConfig({
  root: "calc",
  base: "./",
  publicDir: "../calc-public",
  plugins: [react()],
  build: { outDir: "../dist-calc", emptyOutDir: true, sourcemap: false },
});
