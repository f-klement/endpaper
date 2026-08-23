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

export default defineConfig({
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
    // uses. The eleven DOM-free files opt out entirely with a
    // `@vitest-environment node` docblock and are unaffected either way.
    //
    // The risk is real and is why this is worth a note rather than a swap:
    // happy-dom is not jsdom, and a test relying on a corner jsdom implements
    // and it does not will fail on the DOM rather than on the assertion. The
    // suite passing in full is the evidence; if a future test fails for a
    // reason that makes no sense, this line is the first thing to suspect.
    environment: "happy-dom",
    globals: true,
    // Two, not one per core. vitest left alone forks per CPU: measured on a
    // four core CI host it sustained 3.2 of them for the whole run, which is
    // antisocial on a machine shared with anything else. Two workers bound the
    // burst by choosing to use less, rather than being throttled into it by a
    // CPU limit, which is the same work done slower. Keep in step with the CI
    // runner's own limits.
    maxWorkers: 2,
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
