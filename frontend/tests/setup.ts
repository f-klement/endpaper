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
 * The four palette steps the wallpaper reads.
 *
 * The suite runs with `css: false`, so no stylesheet is loaded and every custom
 * property is empty. `patterns.ts` resolves the wallpaper's ink off these at
 * runtime rather than owning any hex, so without them the app under test is one
 * with no palette, which is not the app. They are the shipped values.
 */
const PALETTE_TOKENS: Record<string, string> = {
  "--color-accent-700": "#0f766e",
  "--color-accent-300": "#71d8c1",
  "--color-bloom-700": "#9f1239",
  "--color-bloom-300": "#fda4af",
};

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
