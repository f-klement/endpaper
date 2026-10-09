/**
 * Tests for src/lib/savedSearches.ts.
 *
 * The behaviours worth pinning are the ones that lose somebody's work: saving
 * twice under one name, and every way storage can refuse to co-operate.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAX_SAVED,
  deleteSearch,
  readSavedSearches,
  saveSearch,
} from "../../src/lib/savedSearches";

interface Filters {
  status: string | null;
}

const UNREAD: Filters = { status: "unread" };
const READ: Filters = { status: "read" };

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("saveSearch", () => {
  it("keeps a named view", () => {
    saveSearch("Loft", UNREAD);
    expect(readSavedSearches<Filters>()).toMatchObject([
      { name: "Loft", filters: UNREAD },
    ]);
  });

  it("updates rather than duplicating when the name is reused", () => {
    // Saving twice under one name is how somebody adjusts a view. Two entries
    // called "Loft" would leave them unable to tell which is which.
    saveSearch("Loft", UNREAD);
    saveSearch("Loft", READ);

    const saved = readSavedSearches<Filters>();
    expect(saved).toHaveLength(1);
    expect(saved[0]!.filters).toEqual(READ);
  });

  it("treats a name as the same one whatever its case", () => {
    saveSearch("Loft", UNREAD);
    saveSearch("loft", READ);
    expect(readSavedSearches<Filters>()).toHaveLength(1);
  });

  it("trims the name", () => {
    saveSearch("  Loft  ", UNREAD);
    expect(readSavedSearches<Filters>()[0]!.name).toBe("Loft");
  });

  it("refuses a name that is only space", () => {
    saveSearch("   ", UNREAD);
    expect(readSavedSearches<Filters>()).toEqual([]);
  });

  it("caps how many are kept, dropping the oldest", () => {
    for (let n = 0; n <= MAX_SAVED; n += 1) saveSearch(`View ${n}`, UNREAD);

    const saved = readSavedSearches<Filters>();
    expect(saved).toHaveLength(MAX_SAVED);
    expect(saved.map((search) => search.name)).not.toContain("View 0");
  });
});

describe("deleteSearch", () => {
  it("forgets one and leaves the rest", () => {
    saveSearch("Loft", UNREAD);
    const [kept] = saveSearch("Kitchen", READ);

    deleteSearch(kept!.id);

    expect(readSavedSearches<Filters>().map((s) => s.name)).toEqual([
      "Kitchen",
    ]);
  });
});

describe("when storage cannot be trusted", () => {
  it("reads corrupt contents as empty rather than throwing", () => {
    localStorage.setItem("savedSearches", "{not json");
    expect(readSavedSearches<Filters>()).toEqual([]);
  });

  it("ignores a shape from another version", () => {
    // Reading a future version's rows would apply filters this build does not
    // understand, which is a worse outcome than losing the saved views.
    localStorage.setItem(
      "savedSearches",
      JSON.stringify({
        version: 99,
        searches: [{ id: "1", name: "X", filters: {} }],
      }),
    );
    expect(readSavedSearches<Filters>()).toEqual([]);
  });

  it("reads as empty when storage refuses to answer", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readSavedSearches<Filters>()).toEqual([]);
  });

  it("saves silently when storage is full", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveSearch("Loft", UNREAD)).not.toThrow();
  });
});
