/**
 * Tests for src/lib/libraryView.ts.
 *
 * A remembered view is a convenience, so every way storage can refuse to answer
 * has to end in a rendered library rather than an error. That is most of what
 * is worth pinning here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_LIBRARY_VIEW,
  readLibraryView,
  writeLibraryView,
} from "../../src/lib/libraryView";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("readLibraryView", () => {
  it("starts on the covers", () => {
    expect(readLibraryView()).toBe("grid");
    expect(DEFAULT_LIBRARY_VIEW).toBe("grid");
  });

  it("remembers a choice", () => {
    writeLibraryView("table");
    expect(readLibraryView()).toBe("table");
  });

  it("remembers the dense rows", () => {
    /** A third view was one entry in `LIBRARY_VIEWS`, and the type, the
     * validation and the storage followed from it. */
    writeLibraryView("list");
    expect(readLibraryView()).toBe("list");
  });

  it("ignores a value it does not know", () => {
    // A value written by a future version, or by hand.
    localStorage.setItem("libraryView", "carousel");
    expect(readLibraryView()).toBe("grid");
  });

  it("falls back to the default when storage refuses to answer", () => {
    // A private window. The library still has to render.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readLibraryView()).toBe("grid");
  });
});

describe("writeLibraryView", () => {
  it("says nothing when storage refuses to keep it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => writeLibraryView("table")).not.toThrow();
  });
});
