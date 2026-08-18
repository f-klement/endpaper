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

beforeEach(() => {
  localStorage.clear();
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
