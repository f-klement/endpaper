/**
 * Build the app, then assert two things about what came out of it.
 *
 * 1. The generated service worker cannot answer a navigation out of the
 *    precache.
 * 2. The shell references its scripts at `/assets/`, absolute, which is what
 *    the backend's cache and fallback rules are keyed on.
 *
 * Both are properties of the **build**, and neither is visible in a config or a
 * source file, which is why they are here together rather than in the suite.
 *
 * Run it with `bun run check:build`. It is a build check rather than a vitest
 * test, and the reason is the whole point of the check: the thing to inspect is
 * `dist/sw.js`, which does not exist until a build has run. Vitest reads files
 * through `import.meta.glob`, which is expanded when a test module is
 * transformed, so a test could only ever see an artefact built before the suite
 * started. Reading it any other way means `node:fs`, and this project has no
 * `@types/node` on purpose (see `tests/houseRules.test.ts`). Building an
 * artefact and scanning it is what `ci/make-public-tree.sh` does, and this
 * follows it: produce the bytes, inspect the bytes, exit non-zero.
 *
 * Nothing here is type checked. `tsconfig.json` includes `src`, `tests` and
 * `vite.config.ts` and not this directory, which is what lets the file import
 * `node:fs` at all.
 *
 * ── What it is guarding ──────────────────────────────────────────────────────
 *
 * Endpaper can sit behind a forward-auth portal, and a portal only ever gets to
 * answer a **top-level navigation**. A precached `index.html` takes that
 * navigation away from it: `precacheAndRoute` applies a `directoryIndex` that
 * defaults to `"index.html"`, so a request for `/` is rewritten, matches, and
 * is served from the cache with no network involved. The app then boots looking
 * signed in, every request it makes is redirected, and the reader gets a
 * spinner over a page that reloads for ever.
 *
 * That was reported live. The first attempt at a fix set `navigateFallback:
 * undefined`, which removed the NavigationRoute and left the precache route,
 * and the config comment then described the bug as solved from v0.2.0 to
 * v0.5.0 while the build kept shipping it. So this check reads the build, not
 * the config.
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { build, type ResolvedConfig } from "vite";

/**
 * Where the build wrote, asked for rather than assumed.
 *
 * This hardcoded "dist" and passed it to `build()` as an outDir *override*,
 * which is the same mistake in miniature as the bug being guarded: a future
 * `outDir` in `vite.config.ts` would leave the check passing against a path the
 * real build no longer used.
 *
 * A capture plugin rather than `resolveConfig()` first, and that is not a
 * stylistic choice: resolving the config separately before building **changed
 * the artefact**. The generated worker came back unminified, comments and all,
 * which no ordinary `bun run build` produces. A check that perturbs what it
 * measures is worth nothing, so this adds a plugin with one hook to the build
 * that is happening anyway.
 */
let resolved: ResolvedConfig | undefined;

await build({
  logLevel: "warn",
  plugins: [
    {
      name: "endpaper:capture-resolved-config",
      configResolved(config) {
        resolved = config;
      },
    },
  ],
});

if (!resolved) {
  console.error("FAIL: the build never resolved a config");
  process.exit(1);
}

const OUT_DIR = resolve(resolved.root, resolved.build.outDir);
const SW = resolve(OUT_DIR, "sw.js");

/** Every `url` in the built worker, minified form and readable form alike. */
function precachedURLs(source: string): string[] {
  const found = [...source.matchAll(/"?url"?\s*:\s*"([^"]+)"/g)].map(
    (match) => match[1]!,
  );
  return [...new Set(found)];
}

const failures: string[] = [];

function reject(reason: string): void {
  failures.push(reason);
}

if (!existsSync(SW)) {
  console.error(`FAIL: the build produced no ${SW}`);
  process.exit(1);
}

const source = readFileSync(SW, "utf8");

// A guard that inspects nothing is worse than no guard: if the worker stops
// precaching altogether, or the plugin renames what it emits, every assertion
// below would pass while measuring an empty string.
// `precacheAndRoute([`, not `precacheAndRoute(`: Workbox's template carries the
// sentence "The precacheAndRoute() method" in a comment directly above the
// call, so the looser pattern counted two whenever the worker came back
// unminified. Requiring the array argument matches the call in both forms.
const precacheCalls = source.match(/precacheAndRoute\(\s*\[/g)?.length ?? 0;
if (precacheCalls !== 1) {
  reject(
    `expected exactly one precacheAndRoute call, found ${precacheCalls}. ` +
      "Nothing below this line was actually checked.",
  );
}

const urls = precachedURLs(source);
if (urls.length < 5) {
  reject(
    `only ${urls.length} precached URLs, which is too few to be a real ` +
      "manifest. Has globPatterns stopped matching?",
  );
}

// The finding itself. Any HTML in the precache is a shell that can be served
// to somebody the portal has signed out.
const html = urls.filter((url) => url.endsWith(".html"));
if (html.length > 0) {
  reject(
    `the precache manifest contains HTML: ${html.join(", ")}. A request for ` +
      "/ is rewritten to index.html by the precache route's directoryIndex " +
      "and answered from cache, so the forward-auth portal never sees the " +
      "navigation. Remove html from workbox.globPatterns in vite.config.ts.",
  );
}

// The other half of the same fix. A navigate fallback answers every navigation
// from the precache by construction.
for (const marker of ["createHandlerBoundToURL", "NavigationRoute"]) {
  if (source.includes(marker)) {
    reject(
      `the worker registers a navigation fallback (${marker}). Navigations ` +
        "must reach the network so the portal can answer them.",
    );
  }
}

// ── The shell's asset paths ──────────────────────────────────────────────────
//
// `backend/main.py` keys two rules on the **first path segment** being
// `assets/`: a year of `immutable` caching, and a refusal to answer a missing
// one with the SPA shell. That second rule is what stops a stale client's
// missing chunk arriving as HTML inside a script tag.
//
// It holds only because Vite's `base` is unset, so it defaults to `/` and the
// shell writes `src="/assets/index-<hash>.js"`. Set `base: "./"`, which is the
// ordinary change for serving from a subpath, and a deep link at `/book/12`
// resolves its chunk to `/book/assets/index-<hash>.js`: a first segment of
// `book`, so the guard does not fire, and the fallback answers a script load
// with the shell.
//
// Asserted against the built HTML rather than against `vite.config.ts`, because
// `base` can also arrive as `vite build --base=...` and a source check would
// not see it. Case is not checked and needs no fold: a differently cased path
// is a different resource on a case-sensitive filesystem, and on a
// case-insensitive one the file is found and served with `no-cache`, which is
// the safe direction either way.
const shellPath = resolve(OUT_DIR, "index.html");

if (!existsSync(shellPath)) {
  reject(`the build produced no ${shellPath}`);
} else {
  const shell = readFileSync(shellPath, "utf8");
  const references = [...shell.matchAll(/(?:src|href)="([^"]*assets\/[^"]*)"/g)].map(
    (match) => match[1]!,
  );

  if (references.length === 0) {
    reject(
      "the built index.html references nothing under assets/, so the check " +
        "below measured nothing. Has the build stopped emitting hashed assets?",
    );
  }

  const relative = references.filter((url) => !url.startsWith("/assets/"));
  if (relative.length > 0) {
    reject(
      `the shell references assets by a relative path: ${relative.join(", ")}. ` +
        "The backend keys its cache policy and its SPA fallback on the first " +
        "path segment being `assets`, which a relative reference from a deep " +
        "link is not: see HASHED_ASSET_DIR in backend/main.py. Unset `base` " +
        "in vite.config.ts, or change both rules together.",
    );
  }
}

if (failures.length > 0) {
  console.error(`==> ${OUT_DIR} REJECTED`);
  for (const failure of failures) console.error(`    FAIL: ${failure}`);
  process.exit(1);
}

console.log(
  `==> ${SW} OK: ${urls.length} precached URLs, no HTML, no navigation fallback`,
);
console.log("==> index.html OK: every asset referenced at /assets/");
