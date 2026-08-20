import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, vi } from "vitest";

// jsdom has no layout engine; some libraries measure on mount.
if (!window.matchMedia) {
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
const INDEX_CSS = (import.meta.glob("../src/index.css", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>)["../src/index.css"];

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

const PALETTE_TOKENS = shippedPalette();

beforeEach(() => {
  localStorage.clear();
  for (const [token, value] of Object.entries(PALETTE_TOKENS)) {
    document.documentElement.style.setProperty(token, value);
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
