import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, vi } from "vitest";

// jsdom has no layout engine; some libraries measure on mount.
//
// Guarded on `window` existing at all, not just on the method. This file is the
// suite-wide setup, so it also runs for the files carrying
// `@vitest-environment node`: the pure helpers, the house rules, the palette
// maths. Reaching for a bare `window` there is a ReferenceError that collects
// zero tests and reports the file as failed with no assertion named, which is a
// confusing way to learn that a docblock took effect.
// happy-dom implements no modal dialogue functions at all, where jsdom shipped
// stubs that throw "not implemented". The app calls `confirm()` before the
// destructive actions (emptying the trash, deleting a curated tag, a bulk
// delete), and tests spy on it to assert that a given action does or does not
// ask. `vi.spyOn` on a missing property fails outright, so these have to exist
// before a spy can replace them. Defaults are deliberately the safe answers: a
// confirm nobody stubbed says no, so a test that forgets to stub cannot
// silently perform a deletion.
if (typeof window !== "undefined") {
  window.confirm ??= () => false;
  window.alert ??= () => undefined;
  window.prompt ??= () => null;
}

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

/**
 * The stylesheet, read as text.
 *
 * No stylesheet is loaded here in the ordinary way: `vite.config.ts` processes
 * CSS only so that it can be read like this, and nothing under test imports
 * one. Every custom property on the document is therefore empty unless a test
 * writes it, and `patterns.ts` resolves the wallpaper's colours off the
 * document at runtime rather than owning any hex, so without them the app under
 * test is one with no palette, which is not the app.
 */
const INDEX_CSS = (
  import.meta.glob("../src/index.css", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>
)["../src/index.css"];

/**
 * The six palette steps the wallpaper reads, taken from the stylesheet itself.
 *
 * They were six literals with a comment claiming they were the shipped values,
 * and one of them was not: `--color-paper-950` read `#1a1816` where the
 * stylesheet says `#100e0c`, so every dark mode alpha in the suite was solved
 * against a page 27% lighter than the one that ships. Nothing failed, because
 * the assertions were self-consistent with the wrong ground. A comment is not
 * a mechanism, so the values are extracted instead.
 *
 * Four of the six are inks and two are the page each mode is drawn on. The page
 * is read for the same reason the inks are: every layer's opacity is solved
 * from how far its ink moves the page it sits on, so a tile with no page has no
 * opacity to be drawn at and is not painted.
 */
const WALLPAPER_TOKENS = [
  "--color-accent-700",
  "--color-accent-300",
  "--color-bloom-700",
  "--color-bloom-300",
  "--color-paper-50",
  "--color-paper-950",
];

function shippedPalette(): Record<string, string> {
  if (!INDEX_CSS || INDEX_CSS.length < 1000) {
    // Under `css: false` a raw CSS import is an empty string, and every test
    // that draws a tile would then quietly run with no palette at all.
    throw new Error("tests/setup.ts could not read src/index.css");
  }
  const code = INDEX_CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  const tokens: Record<string, string> = {};
  for (const token of WALLPAPER_TOKENS) {
    const declared = [
      ...code.matchAll(new RegExp(`${token}\\s*:\\s*([^;]+);`, "g")),
    ].map((match) => match[1]!.trim());
    // Exactly one, deliberately. Endpaper declares all six in `@theme static`
    // and overrides none of them under `:root.dark`, so first-match and
    // only-match are the same answer today. If that stops being true, taking
    // the first would silently hand the dark solve a light page, which is the
    // bug this replaced. Failing here makes somebody choose instead.
    if (declared.length !== 1 || !/^#[0-9a-f]{6}$/i.test(declared[0]!)) {
      throw new Error(
        `${token}: expected one literal hex in index.css, found ${JSON.stringify(declared)}`,
      );
    }
    tokens[token] = declared[0]!;
  }
  return tokens;
}

/**
 * Parsed once per worker **process**, not once per test file.
 *
 * This file is the suite-wide setup, so anything at module scope runs again for
 * every one of the seventy-eight files, and vitest gives each file a fresh
 * module registry: a plain module-level `let` is therefore not a cache, it is
 * the same work with an extra branch. `globalThis` outlives the registry
 * because the fork pool reuses the process, so with two workers this parses
 * twice for the whole run instead of seventy-eight times.
 *
 * The work and its errors are unchanged; only how often it happens is.
 */
const PALETTE_CACHE_KEY = "__endpaper_palette_tokens__";

function paletteTokensOnce(): Record<string, string> {
  const store = globalThis as Record<string, unknown>;
  store[PALETTE_CACHE_KEY] ??= shippedPalette();
  return store[PALETTE_CACHE_KEY] as Record<string, string>;
}

beforeEach(() => {
  // Same guard as the matchMedia shim above, and for the same reason: this hook
  // runs for the `@vitest-environment node` files too, which have neither a
  // localStorage nor a document. The network stub below is installed either way,
  // because a node-environment test reaching the real network is exactly as
  // wrong as a jsdom one doing it.
  if (typeof document !== "undefined") {
    localStorage.clear();
    // `sessionStorage` too, because `api/mutator.ts` records its edge-sign-out
    // reload marker there. A marker left behind by one test makes the next one
    // take the "we have already reloaded once" branch, which is the difference
    // between reloading and rendering a dead end.
    sessionStorage.clear();
    for (const [token, value] of Object.entries(paletteTokensOnce())) {
      document.documentElement.style.setProperty(token, value);
    }
  }
  // Anything the test forgot to stub should fail loudly rather than reach the
  // real network. Tests install their own handlers via mockApi().
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) =>
      Promise.reject(
        new Error(
          `Unhandled request: ${String(input)}. Stub it with mockApi()`,
        ),
      ),
    ),
  );
});

// jsdom implements <dialog> but not showModal/close, so a dialog opened the way
// the app opens one stays shut and its contents never reach the accessibility
// tree. The gap is jsdom's, not the app's: real browsers have had these for
// years. Toggling `open` is enough to make the element behave for a test.
beforeAll(() => {
  // Third and last of the DOM guards in this file. See the matchMedia shim.
  if (typeof window === "undefined") return;
  const dialog = window.HTMLDialogElement?.prototype;
  if (dialog && !dialog.showModal) {
    dialog.showModal = function showModal(this: HTMLDialogElement) {
      this.open = true;
    };
    dialog.close = function close(this: HTMLDialogElement) {
      this.open = false;
      this.dispatchEvent(new Event("close"));
    };
  }
});

//: The real `window.location`, captured before any test can replace it.
//
// **Three test files replace it wholesale** with `Object.defineProperty`,
// because a real navigation is not a thing a test environment can do. Neither
// `vi.unstubAllGlobals()` nor `vi.restoreAllMocks()` undoes that: they know
// about stubs vitest installed, and a direct `defineProperty` is not one.
//
// That costs nothing while every file gets its own window and is a leak the
// moment they share one. Measured under `isolate: false`, one worker, file
// order seeded: `tests/api/mutator.test.ts` leaves a location of
// `{href: "/", pathname: "/"}` behind, with no origin, and the next file that
// renders an `<img src="/covers/1.jpg">` gets an error event instead of a
// load, because a relative URL cannot resolve against it. Three of
// `CoverImage.test.tsx`'s eight tests then found the placeholder where they
// expected the cover, with nothing in either file wrong on its own.
//
// Restored here rather than in the three files, because the next file to
// replace it should not have to know this.
const REAL_LOCATION =
  typeof window === "undefined"
    ? undefined
    : Object.getOwnPropertyDescriptor(window, "location");

//: The URL the environment starts at, so a test that navigates cannot decide
//: where the next one begins. Replacing the location object does not restore
//: this: a navigation changes the real one, and `document.baseURI` follows it.
const REAL_HREF =
  typeof window === "undefined" ? undefined : window.location.href;

afterEach(() => {
  // `cleanup()` unmounts React trees, of which a node-environment file has none.
  if (typeof document !== "undefined") cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (
    REAL_LOCATION &&
    Object.getOwnPropertyDescriptor(window, "location") !== REAL_LOCATION
  ) {
    Object.defineProperty(window, "location", REAL_LOCATION);
  }
  // **And the URL itself.** Measured under a shared environment: the download
  // tests leave it at `blob:mock-url`, after which a relative `src` on an image
  // cannot resolve at all, happy-dom fires `error` instead of loading, and the
  // next file's cover tests find the placeholder they were checking against.
  // Several files navigate less dramatically and leave a path behind.
  //
  // **Assigned rather than pushed.** `history.pushState` refuses to cross an
  // origin, and the download tests leave the document on `blob:mock-url`, whose
  // origin is null: measured, the reset itself then threw a SecurityError and
  // failed the very file that had navigated. Setting `href` has no such rule.
  if (REAL_HREF && window.location.href !== REAL_HREF) {
    window.location.href = REAL_HREF;
  }
});
