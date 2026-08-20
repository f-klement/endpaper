import React from "react";
import ReactDOM from "react-dom/client";

import App from "./app/App";
import {
  applyTheme,
  applyWallpaper,
  currentPattern,
  readStoredPreference,
  resolveTheme,
} from "./theme";
import "./index.css";

// Before React mounts, not in an effect. Resolving the appearance after the
// first render paints a light page and then flips it, which is the flash every
// dark-themed site is judged by. The wallpaper goes with it: painted from an
// effect it lands a frame after the page, and the provider then renders the
// pattern already on the body rather than choosing a second one.
const bootTheme = resolveTheme(readStoredPreference());
applyTheme(bootTheme);
applyWallpaper(currentPattern(), bootTheme);

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing #root element, check index.html");
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
