/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

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
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        // No navigation fallback, and that is the fix for a real bug rather
        // than a lost feature.
        //
        // The plugin defaults this to "index.html", which registers a
        // NavigationRoute answering EVERY navigation from the precache without
        // touching the network. Endpaper sits behind a forward-auth portal, so
        // when the portal cookie expires the shell was still served from cache,
        // the app booted looking signed in, and every request it then made was
        // redirected to a login page it could not reach. The result was an
        // endless spinner and a console full of network errors.
        //
        // An offline shell cannot be honest here anyway: everything on every
        // screen comes from the API, and the API is behind the same portal. So
        // navigations go to the network, where the portal can redirect them,
        // and the precache keeps doing the part it is good at, which is
        // serving the assets instantly once you are through.
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
    environment: "jsdom",
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
