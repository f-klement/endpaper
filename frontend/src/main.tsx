import React from "react";
import ReactDOM from "react-dom/client";

import App from "./app/App";
import { applyAppearance, patternFor, readCachedAppearance } from "./theme";
import "./index.css";

// Before React mounts, not in an effect. Resolving the appearance after the
// first render paints a light page and then flips it, which is the flash every
// dark-themed site is judged by. All three parts go together: the palette, the
// mode and the wallpaper, whose ink is read off the palette's own tokens.
//
// From the cache rather than the server, because the server cannot answer in
// time and an inline blocking script is not available under this CSP. See
// `theme/appearance.ts`. The cache is the account that used this device last,
// which is right for the login screen and right for the overwhelmingly common
// case of one person and one browser; `AppearanceSync` reconciles it with the
// account's stored preference as soon as the session is known.
const bootAppearance = readCachedAppearance();
applyAppearance(bootAppearance, patternFor(bootAppearance.wallpaper));

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing #root element, check index.html");
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
