import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/michroma";
import App from "./App";
import { applyTheme } from "./lib/theme";
import { STATIC } from "./lib/snapshot";
import "./styles.css";

applyTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {STATIC ? <MemoryRouter><App /></MemoryRouter> : <BrowserRouter><App /></BrowserRouter>}
  </StrictMode>,
);
