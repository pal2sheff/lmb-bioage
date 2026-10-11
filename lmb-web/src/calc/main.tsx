import "@fontsource/manrope/cyrillic-400.css";
import "@fontsource/manrope/cyrillic-500.css";
import "@fontsource/manrope/cyrillic-600.css";
import "@fontsource/manrope/cyrillic-700.css";
import "@fontsource/manrope/latin-400.css";
import "@fontsource/manrope/latin-500.css";
import "@fontsource/manrope/latin-600.css";
import "@fontsource/manrope/latin-700.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import "./calc.css";
import { CalcApp } from "./CalcApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CalcApp />
  </StrictMode>,
);
