/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Lever A is applied per file with a `@vitest-environment node` docblock, not
// here. A `projects` split with `isolate: false` was tried first and broke the
// run outright: vitest could not resolve `vitest/dist/workers/forks.js` and
// rolldown panicked with "Failed to get current dir". A docblock cannot do that,
// because it changes one file's environment rather than how workers are spawned.
//
// **`isolate: false` is below, and what pays for it is `tests/doubles/`.** It is
// worth 22.79s against 50.19s, both on the same worker and the same tree. It was
// refused once, and correctly: sharing the module registry makes a `vi.mock` lose
// to whichever file evaluated that module first, silently, in both directions
// measured. The setting became sound when the last module mock left the suite,
// not before. `tests/houseRules.test.ts` fails the build on a new one, and
// `docs/decisions.md` carries the argument.

import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

/**
 * The version the app shows, derived rather than declared.
 *
 * **Nothing is bumped before a tag.** `package.json` used to be the source, which
 * meant remembering to edit it, and `backend/pyproject.toml`, and later a mobile
 * manifest as well, every time. Both sat at 0.5.0 while v0.6.0 was being prepared
 * on 2026-08-23, which is what a number maintained by memory does. A guard that
 * failed the release on a mismatch was written first and then thrown away: it
 * turned one forgotten edit into a failed pipeline and a re-tag, which is more
 * ceremony rather than less.
 *
 * On a tag pipeline the tag is the answer, minus the `v`. Everywhere else
 * `git describe` says where you are, so a development build reads something like
 * `0.6.0-14-gbbdf755` and can never be mistaken for a release. If git is absent,
 * which is true inside the Docker build's frontend stage and in the test container,
 * the fallback is `unknown`: a plain marker rather than a number that looks real.
 * One token, never a space, so a version string can always be matched as one.
 */
function appVersion(): string {
  const tag = process.env.CI_COMMIT_TAG;
  if (tag) return tag.replace(/^v/, "");
  try {
    return execSync("git describe --tags --always --dirty", {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim()
      .replace(/^v/, "");
  } catch {
    return "unknown";
  }
}

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(appVersion()) },
  plugins: [
    react(),
    // Tailwind 4 runs as a Vite plugin; there is no postcss.config.js any more.
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/*.png", "icons/*.svg"],
      // The manifest is hand-maintained in public/manifest.json.
      manifest: false,
      workbox: {
        // **No `html`, and that omission is load bearing.** Precaching
        // `index.html` is what let the app boot from cache while signed out;
        // `navigateFallback` below is the other half of the same fix.
        //
        // Workbox's precache route does not only answer the exact URLs in the
        // manifest. `precacheAndRoute` takes a `directoryIndex` that defaults
        // to `"index.html"` (workbox-precaching's `generateURLVariations`, and
        // the built sw.js passes no override), so a request for `/` becomes
        // `/index.html`, matches the manifest entry, and is answered from the
        // cache without the network being touched. Endpaper can sit behind a
        // forward-auth portal, and that portal only ever sees a top-level
        // navigation: answering `/` from cache means it never sees one.
        //
        // Removing the entry rather than setting `directoryIndex: null` is the
        // difference between fixing the instance and removing the class. With
        // no HTML in the precache there is no cached shell for any route,
        // rewritten or exact, to serve.
        //
        // The cost is stated plainly: there is no offline app any more. There
        // never usefully was. Every screen's content comes from the API, and
        // the API is behind the same portal, so an offline shell could only
        // ever render a spinner over data it could not fetch, which is what
        // was reported. Assets still precache, which is the part that is worth
        // having: once a navigation is through the portal, the page paints from
        // cache.
        globPatterns: ["**/*.{js,css,ico,png,svg,woff2}"],
        // The other half, and it stays. The plugin defaults this to
        // "index.html", which registers a NavigationRoute answering EVERY
        // navigation from the precache. That default was removed when this bug
        // was first diagnosed; the diagnosis was incomplete, because it left
        // the precache route above still answering `/`.
        //
        // It is also now a hard requirement rather than a preference: Workbox
        // builds a navigate fallback with `createHandlerBoundToURL`, which
        // throws `non-precached-url` for a URL it has no cache key for. With no
        // HTML precached, setting this would break the worker outright.
        navigateFallback: undefined,
        // Drop precaches from earlier builds instead of letting them accumulate.
        //
        // **This does not touch a runtime cache**, which is the trap below: it
        // cleans precaches Workbox itself wrote in an earlier build, and a
        // runtime cache survives every deploy under its own name. Shipping a
        // fix therefore does not clear what is already in a reader's browser.
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // Remote covers, from every image service the backend may hand back.
            //
            // **This is the bug the owner reported as "covers used to show and
            // now show nowhere", and it was never server side.** Measured on
            // the live deployment: four books, all four with a `cover_url`,
            // three of the four URLs answering 200 image/jpeg (8 KB, 21 KB,
            // 30 KB) from inside the pod, the fourth a genuine 404; the CSP
            // permitting the host; and both resolvers answering as a public one
            // does. Everything the server does was right, so the failure was in
            // the browser, and it was these five lines.
            //
            // Three faults, and the first is what made it stick:
            //
            // 1. `CacheFirst` never revalidates. Whatever landed in the cache,
            //    good or bad, was served for **thirty days** without the
            //    network being consulted. That is why it reads as "they have
            //    all gone" rather than as something intermittent.
            // 2. No `cacheableResponse`. A cross-origin `<img>` is not a CORS
            //    request, so the response is **opaque**: a 404 and a real image
            //    are indistinguishable by status, and `CacheFirst` then pinned
            //    the 404 for a month.
            // 3. The cache name was inherited across deploys, so a fix would
            //    have helped nobody who already had the bad entries.
            //
            // `StaleWhileRevalidate` so a bad entry heals itself on the next
            // view, `statuses: [200]` so an opaque or error response is never
            // stored in the first place, and a **new cache name** so the
            // poisoned entries are orphaned rather than inherited. A cover is
            // tens of kilobytes; never revalidating was not worth this.
            //
            // Covers this app stores itself are `/covers/<id>.<ext>` on our own
            // origin and are **not** matched here: they are same origin, so
            // their responses carry a real status, which removes fault 2 at the
            // root. That is a second reason to store them beyond the ones in
            // `docs/decisions.md`.
            urlPattern:
              /^https:\/\/(covers\.openlibrary\.org|portal\.dnb\.de|books\.google\.com|[^/]+\.googleusercontent\.com)\//,
            handler: "StaleWhileRevalidate",
            options: {
              // Renamed from `book-covers`. Renaming is the only thing that
              // orphans what is already poisoned in a reader's browser; see
              // `claimAndCleanUp` below for the deletion.
              cacheName: "book-covers-v2",
              cacheableResponse: { statuses: [200] },
              expiration: { maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
        ],
        // Delete the cache the rule above replaced. Workbox will not do it on
        // its own: `cleanupOutdatedCaches` is about precaches, so an orphaned
        // runtime cache is never read again and still holds a month of wrong
        // answers in the reader's quota. `public/sw-cleanup.js` is four lines
        // that drop it on activate.
        importScripts: ["/sw-cleanup.js"],
      },
    }),
  ],

  server: {
    // `docs/` sits above this package, and Vite denies module reads outside the
    // project root by default. `tests/theme/palettes.test.ts` asserts the
    // contrast table in docs/decisions.md against the figures it computes, so
    // the prose cannot drift from the numbers again; it needs to read that one
    // file. Dev and test only: nothing here affects the built bundle, which is
    // served by FastAPI in production and never by Vite.
    fs: { allow: [".."] },
    // `bun run dev` serves the SPA; these two prefixes belong to the FastAPI
    // process, which is expected on :8000.
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/covers": "http://localhost:8000",
    },
  },

  test: {
    // happy-dom, not jsdom. Measured on this suite: `environment` was 160s of a
    // 322s run, paid once per test file to build a DOM, and happy-dom
    // constructs one substantially faster for the same API surface this suite
    // uses. The eighteen DOM-free files opt out entirely with a
    // `@vitest-environment node` docblock and are unaffected either way.
    //
    // **Recount that eleven with the docblock ANCHORED, or it comes out one too
    // high**:
    // `grep -rlE '^\s*\*\s*@vitest-environment node' tests | wc -l`.
    // The obvious `grep -rl '@vitest-environment node' tests` answers twelve,
    // because `tests/setup.ts` *mentions* the docblock in a comment explaining
    // that setup also runs for the files carrying it. `setup.ts` is not one of
    // them and does not opt out of anything. Counting the string rather than
    // the docblock turned this number from correct to wrong twice in one
    // ticket, in both directions, which is why the command is written down
    // rather than left to whoever edits next.
    //
    // Eleven described the tree from 2026-08-30, and it was thirteen by
    // 2026-09-04 without this comment moving: two files arrived carrying the
    // docblock and nothing recounts this sentence. Eighteen is 2026-09-04, after
    // five more DOM-free files were marked. **The effect of those five is below
    // this machine's noise floor** and is not claimed as a speedup: repeated
    // whole-suite runs on the same tree spread over roughly eight seconds, so a
    // change worth about one cannot be seen. They are marked because a file that
    // needs no DOM should not build one, which is the same reason the other
    // thirteen are.
    //
    // The risk is real and is why this is worth a note rather than a swap:
    // happy-dom is not jsdom, and a test relying on a corner jsdom implements
    // and it does not will fail on the DOM rather than on the assertion. The
    // suite passing in full is the evidence; if a future test fails for a
    // reason that makes no sense, this line is the first thing to suspect.
    environment: "happy-dom",
    // **Replacing a module is an alias here, never a `vi.mock`.** Under
    // `isolate: false` the module registry is shared between files, and a
    // `vi.mock` is a claim one file makes about a module that another file may
    // already have evaluated: the mock is then dropped and the real module is
    // what the test gets. Measured on this suite, both directions, one file
    // each way. An alias has no ordering, because there is no real module left
    // to lose to. `tests/houseRules.test.ts` fails the build on a `vi.mock`,
    // and `tests/doubles/README.md` is the whole argument.
    //
    // `test.alias` and not `resolve.alias`: the application build resolves the
    // real library, and only the suite sees the double.
    alias: {
      "@zxing/library": fileURLToPath(
        new URL("./tests/doubles/zxing.ts", import.meta.url),
      ),
    },
    isolate: false,
    globals: true,
    // Bounded, not one per core. vitest left alone forks per CPU: measured on a
    // four core CI host it sustained 3.2 of them for the whole run, which is
    // antisocial on a machine shared with anything else. Bounding the workers
    // caps the burst by making vitest choose to use less, rather than throttling
    // it into the same work at a slower rate with a CPU limit.
    //
    // The number follows the machine, because CI hosts are different shapes: the
    // runner sets `ENDPAPER_TEST_WORKERS` per host, alongside that host's CPU
    // limit, and the two have to stay in step. So change it where the runner
    // sets it rather than here, or a host will be told to use more workers than
    // it is allowed cores.
    //
    // The fallback is 2 and is what a local run gets. It is deliberately the low
    // number rather than the fast one: a development machine is usually doing
    // something else that matters more than this suite finishing sooner, and a
    // suite that saturates it has already caused an outage alert once.
    maxWorkers: Number(process.env.ENDPAPER_TEST_WORKERS) || 2,
    // The suite mirrors src/ rather than sitting beside it.
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
    // Not `false`, which is the usual answer for a suite that asserts on the
    // DOM rather than on paint. Under `false` Vite replaces every CSS module
    // with an empty string, `?raw` included, and `tests/theme/palettes.test.ts`
    // measures the palettes by reading `index.css` and `palettes.css` as text:
    // the shipped values, not a copy of them kept in TypeScript for the test's
    // convenience. Nothing imports a stylesheet the ordinary way here, so this
    // costs one file read and changes nothing else.
    // Unanchored deliberately: the module id a raw import produces ends in
    // `?raw`, so a pattern closed with `$` matches nothing at all and the test
    // silently measures an empty string.
    css: { include: [/\.css/] },
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // Bootstrap and type-only modules have nothing to assert against.
      exclude: ["src/main.tsx", "src/types.ts"],
      reporter: ["text", "html"],
    },
  },
});
