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
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/covers\.openlibrary\.org\//,
            handler: "CacheFirst",
            options: {
              cacheName: "book-covers",
              expiration: { maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
        ],
      },
    }),
  ],

  server: {
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
    // The suite mirrors src/ rather than sitting beside it.
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // Bootstrap and type-only modules have nothing to assert against.
      exclude: ["src/main.tsx", "src/types.ts"],
      reporter: ["text", "html"],
    },
  },
});
