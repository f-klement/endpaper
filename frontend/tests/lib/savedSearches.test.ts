/**
 * Tests for src/lib/savedSearches.ts.
 *
 * The behaviours worth pinning are the ones that lose somebody's work: saving
 * twice under one name, and every way storage can refuse to co-operate.
 *
 * **The two verbs are pure and the storing is the preference's**, so the rules
 * about names and the cap are asserted on a list rather than through a browser,
 * and only the arms that are about storage touch it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_FILTERS } from "../../src/lib/bookFilters";
import {
  MAX_SAVED,
  savedSearchesPreference,
  withSearchDeleted,
  withSearchSaved,
  type SavedSearch,
} from "../../src/lib/savedSearches";

const UNREAD = { ...DEFAULT_FILTERS, status: "unread" as never };
const READ = { ...DEFAULT_FILTERS, status: "read" as never };

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

/** Save through the preference, which is what a caller of the hook does. */
function save(name: string, filters = UNREAD): readonly SavedSearch[] {
  const next = withSearchSaved(savedSearchesPreference.read(), name, filters);
  savedSearchesPreference.write(next);
  return savedSearchesPreference.read();
}

describe("withSearchSaved", () => {
  it("keeps a named view", () => {
    const saved = save("Loft");
    expect(saved).toHaveLength(1);
    expect(saved[0]!.name).toBe("Loft");
    expect(saved[0]!.filters.status).toBe("unread");
  });

  it("updates rather than duplicating when the name is reused", () => {
    save("Loft", UNREAD);
    const saved = save("Loft", READ);
    expect(saved).toHaveLength(1);
    expect(saved[0]!.filters.status).toBe("read");
  });

  it("treats a name as the same one whatever its case", () => {
    save("Loft");
    expect(save("LOFT")).toHaveLength(1);
  });

  it("trims the name", () => {
    expect(save("  Loft  ")[0]!.name).toBe("Loft");
  });

  it("refuses a name that is only space", () => {
    expect(save("   ")).toHaveLength(0);
  });

  it("caps how many are kept, dropping the oldest", () => {
    for (let i = 0; i < MAX_SAVED + 3; i += 1) save(`View ${i}`);
    const saved = savedSearchesPreference.read();
    expect(saved).toHaveLength(MAX_SAVED);
    expect(saved[0]!.name).toBe("View 3");
  });

  it("is pure, so it writes nothing by itself", () => {
    withSearchSaved([], "Loft", UNREAD);
    expect(localStorage.getItem(savedSearchesPreference.key)).toBeNull();
  });
});

describe("withSearchDeleted", () => {
  it("forgets one and leaves the rest", () => {
    save("Loft");
    const both = save("Attic");
    const next = withSearchDeleted(both, both[0]!.id);
    savedSearchesPreference.write(next);

    const saved = savedSearchesPreference.read();
    expect(saved).toHaveLength(1);
    expect(saved[0]!.name).toBe("Attic");
  });
});

describe("when storage cannot be trusted", () => {
  it("reads corrupt contents as empty rather than throwing", () => {
    localStorage.setItem(savedSearchesPreference.key, "{not json");
    expect(savedSearchesPreference.read()).toEqual([]);
  });

  it("ignores a shape from another version", () => {
    localStorage.setItem(
      savedSearchesPreference.key,
      JSON.stringify({ version: 99, searches: [{ id: "1", name: "Old" }] }),
    );
    expect(savedSearchesPreference.read()).toEqual([]);
  });

  it("reads as empty when storage refuses to answer", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(savedSearchesPreference.read()).toEqual([]);
  });

  it("saves silently when storage is full", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => savedSearchesPreference.write([])).not.toThrow();
  });
});

/**
 * A matching envelope says nothing about what is inside it.
 *
 * Every entry is rebuilt rather than cast, because the entries are JSON a
 * browser has been holding since whichever version wrote them. Casting them
 * made the whole class below reachable: a value of the wrong kind survived into
 * a request and threw while the page was drawing.
 */
describe("a stored entry this version cannot use", () => {
  function stored(searches: unknown[]): void {
    localStorage.setItem(
      savedSearchesPreference.key,
      JSON.stringify({ version: 1, searches }),
    );
  }

  it("drops a list filter that is not a list", () => {
    // The concrete defect. A `tagIds` holding a string has a truthy `length`
    // and no `join`, so applying the saved view threw during a render.
    stored([{ id: "1", name: "Loft", filters: { ...UNREAD, tagIds: "3" } }]);
    expect(savedSearchesPreference.read()[0]!.filters.tagIds).toEqual([]);
  });

  it("drops a list holding something that is not a value", () => {
    stored([
      { id: "1", name: "Loft", filters: { ...UNREAD, headings: [{}, "a"] } },
    ]);
    expect(savedSearchesPreference.read()[0]!.filters.headings).toEqual([]);
  });

  it("keeps the fields that are the right kind", () => {
    stored([{ id: "1", name: "Loft", filters: { ...UNREAD, tagIds: "3" } }]);
    expect(savedSearchesPreference.read()[0]!.filters.status).toBe("unread");
  });

  it("drops an entry with no usable name, which could not be told apart", () => {
    stored([{ id: "1", name: "   ", filters: UNREAD }]);
    expect(savedSearchesPreference.read()).toEqual([]);
  });

  it("drops an entry with no id, which could never be deleted", () => {
    stored([{ name: "Loft", filters: UNREAD }]);
    expect(savedSearchesPreference.read()).toEqual([]);
  });

  it("drops an entry that is not an object at all", () => {
    stored(["Loft", 3, null]);
    expect(savedSearchesPreference.read()).toEqual([]);
  });

  it("keeps the good entries beside the bad ones", () => {
    stored([{ id: "1", name: "Loft", filters: UNREAD }, null]);
    const saved = savedSearchesPreference.read();
    expect(saved).toHaveLength(1);
    expect(saved[0]!.name).toBe("Loft");
  });

  it("gives an entry with no filters at all the whole library", () => {
    stored([{ id: "1", name: "Loft" }]);
    expect(savedSearchesPreference.read()[0]!.filters).toEqual(DEFAULT_FILTERS);
  });

  it("carries no field the filter set does not have", () => {
    stored([
      { id: "1", name: "Loft", filters: { ...UNREAD, smuggled: "value" } },
    ]);
    expect(
      Object.keys(savedSearchesPreference.read()[0]!.filters).sort(),
    ).toEqual(Object.keys(DEFAULT_FILTERS).sort());
  });

  it("drops a field only a later version knew about, on the next save", () => {
    // The cost of rebuilding rather than casting, asserted rather than left to
    // be discovered on a downgrade. A save rewrites every entry in this
    // version's shape, so an unknown field does not survive one, and deleting a
    // different search is enough to do it.
    stored([
      { id: "1", name: "Loft", filters: { ...UNREAD, shelfDepth: "deep" } },
      { id: "2", name: "Attic", filters: UNREAD },
    ]);

    const next = withSearchDeleted(savedSearchesPreference.read(), "2");
    savedSearchesPreference.write(next);

    const raw = localStorage.getItem(savedSearchesPreference.key) ?? "";
    expect(raw).not.toContain("shelfDepth");
  });

  it("hands back nothing a reader can edit, entry, filters or list", () => {
    // The freeze is the door's and is shallow, so this codec owes the rest. A
    // saved search's filters reach a component through one shared snapshot, and
    // neither type carries a `readonly`, so the freeze is the only refusal.
    stored([{ id: "1", name: "Loft", filters: { ...UNREAD, tagIds: [1, 2] } }]);
    const entry = savedSearchesPreference.read()[0]!;

    expect(Object.isFrozen(entry)).toBe(true);
    expect(Object.isFrozen(entry.filters)).toBe(true);
    expect(Object.isFrozen(entry.filters.tagIds)).toBe(true);
    expect(() => (entry.filters.tagIds as number[]).push(99)).toThrow();
  });

  it("never hands out a list the defaults own", () => {
    // An entry with no stored list used to carry `DEFAULT_FILTERS`' own array by
    // reference, so a push into it edited the default for the whole document.
    stored([{ id: "1", name: "Loft", filters: { status: "unread" } }]);
    const entry = savedSearchesPreference.read()[0]!;

    expect(Object.isFrozen(entry.filters.headings)).toBe(true);
    expect(() => (entry.filters.headings as string[]).push("x")).toThrow();
    expect(DEFAULT_FILTERS.headings).toEqual([]);
  });

  it("caps what a browser already holds, dropping the oldest", () => {
    // The read cap took the *first* of an oversized list while a save kept the
    // *last*, so a browser holding more than the cap showed one set and kept
    // another. Only a version with a larger cap could produce one and none has
    // shipped, so the two were made to agree.
    stored(
      Array.from({ length: MAX_SAVED + 2 }, (_, i) => ({
        id: `${i}`,
        name: `View ${i}`,
        filters: UNREAD,
      })),
    );
    const saved = savedSearchesPreference.read();
    expect(saved).toHaveLength(MAX_SAVED);
    expect(saved[0]!.name).toBe("View 2");
  });
});
