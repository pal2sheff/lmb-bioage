import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/golos-text/400.css";
import "@fontsource/golos-text/500.css";
import "@fontsource/golos-text/600.css";
import "@fontsource/literata/500.css";
import "@fontsource/literata/600.css";
import "@fontsource/literata/500-italic.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "../styles.css";
import "./calc.css";
import { CalcApp } from "./CalcApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CalcApp />
  </StrictMode>,
);
