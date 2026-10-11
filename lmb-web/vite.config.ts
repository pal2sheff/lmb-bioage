import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке запросы /api проксируются на локальный сервер FastAPI.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { sourcemap: false },
});
