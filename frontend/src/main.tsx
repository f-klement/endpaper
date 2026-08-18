import React from "react";
import ReactDOM from "react-dom/client";

import App from "./app/App";
import { applyTheme, readStoredPreference, resolveTheme } from "./theme";
import "./index.css";

// Before React mounts, not in an effect. Resolving the theme after the first
// render paints a light page and then flips it, which is the flash every
// dark-themed site is judged by.
applyTheme(resolveTheme(readStoredPreference()));

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing #root element, check index.html");
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
