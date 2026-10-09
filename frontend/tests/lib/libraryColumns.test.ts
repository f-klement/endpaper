/**
 * Tests for src/lib/libraryColumns.ts.
 *
 * Three properties carry this module and each of them has a way of going
 * quietly wrong: a household's choice must survive a mode switch in both
 * directions, a mode must never draw a column it does not offer, and every way
 * storage can refuse to answer has to end in a table rather than an error.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CATALOGUE_MODES } from "../../src/lib/catalogueMode";
import {
  ALWAYS_SHOWN,
  AVAILABLE_COLUMNS,
  COLUMN_KEYS,
  COLUMN_SPECS,
  DEFAULT_COLUMNS,
  clearColumns,
  isDefaultColumns,
  readColumns,
  toggledColumns,
  writeColumns,
  type ColumnKey,
} from "../../src/lib/libraryColumns";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

/** The table exactly as it shipped, in the order it drew them. */
const THE_TABLE_BEFORE_THIS_TICKET: ColumnKey[] = [
  "title",
  "author",
  "series",
  "year",
  "publisher",
  "format",
  "condition",
  "lending",
  "discuss",
  "location",
  "pageCount",
  "language",
  "status",
  "rating",
  "tags",
  "ownership",
  "addedBy",
  "addedAt",
  "price",
  "purchasedAt",
  "purchaseSource",
];

describe("the two column sets", () => {
  it("leaves a household's table exactly as it was", () => {
    // Not a nicety. The ticket's third user story is that switching modes
    // must not rearrange anybody's catalogue, and the cheapest way to break
    // that is to reorder the household's columns while inserting the
    // cataloguer's.
    expect(DEFAULT_COLUMNS.household).toEqual(THE_TABLE_BEFORE_THIS_TICKET);
    expect(AVAILABLE_COLUMNS.household).toEqual(THE_TABLE_BEFORE_THIS_TICKET);
  });

  it("offers the cataloguer's two in library mode and nowhere else", () => {
    for (const key of ["callNumber", "classification"] as const) {
      expect(AVAILABLE_COLUMNS.cataloguer).toContain(key);
      expect(AVAILABLE_COLUMNS.household).not.toContain(key);
    }
  });

  it("does not offer location as a call number", () => {
    // The obvious shortcut and the mistake: `location` is prose about a shelf
    // in this house. It is its own column, in both modes, and it is not what
    // the call number column draws.
    expect(AVAILABLE_COLUMNS.household).toContain("location");
    expect(AVAILABLE_COLUMNS.cataloguer).toContain("location");
    expect(COLUMN_SPECS.location.label).not.toBe(COLUMN_SPECS.callNumber.label);
  });

  it("puts the household's own columns away for a cataloguer", () => {
    // User story 2: a list that is half irrelevant. These stay available, so a
    // small archive that does lend books can turn them back on.
    for (const key of ["ownership", "lending", "status", "rating"] as const) {
      expect(DEFAULT_COLUMNS.cataloguer).not.toContain(key);
      expect(AVAILABLE_COLUMNS.cataloguer).toContain(key);
    }
  });

  it("shows a cataloguer the call number and the subjects", () => {
    for (const key of ["callNumber", "classification"] as const) {
      expect(DEFAULT_COLUMNS.cataloguer).toContain(key);
    }
  });

  it("never defaults to a column its mode does not offer", () => {
    for (const mode of ["household", "cataloguer"] as const) {
      for (const key of DEFAULT_COLUMNS[mode]) {
        expect(AVAILABLE_COLUMNS[mode]).toContain(key);
      }
    }
  });

  it("names every column exactly once, in one order", () => {
    // `COLUMN_KEYS` is the table's column order and the type behind every set
    // here. A repeat would draw a column twice and give two cells one React key.
    expect(new Set(COLUMN_KEYS).size).toBe(COLUMN_KEYS.length);
    expect(Object.keys(COLUMN_SPECS).sort()).toEqual([...COLUMN_KEYS].sort());
  });

  it("keeps both sets in the table's own order", () => {
    for (const mode of ["household", "cataloguer"] as const) {
      const positions = DEFAULT_COLUMNS[mode].map((key) =>
        COLUMN_KEYS.indexOf(key),
      );
      expect(positions).toEqual([...positions].sort((a, b) => a - b));
    }
  });
});

describe("readColumns and writeColumns", () => {
  it("starts each mode on its own default", () => {
    expect(readColumns("household")).toEqual([...DEFAULT_COLUMNS.household]);
    expect(readColumns("cataloguer")).toEqual([...DEFAULT_COLUMNS.cataloguer]);
  });

  it("remembers a choice", () => {
    writeColumns("household", ["title", "author", "location"]);
    expect(readColumns("household")).toEqual(["title", "author", "location"]);
  });

  it("keeps a household's choice through a switch in both directions", () => {
    // The ticket's third testing decision, and the reason the two modes have
    // two storage keys rather than one record holding both.
    writeColumns("household", ["title", "author", "location"]);

    // Into library mode: the cataloguer starts on its own default and edits it.
    expect(readColumns("cataloguer")).toEqual([...DEFAULT_COLUMNS.cataloguer]);
    writeColumns("cataloguer", ["title", "callNumber"]);

    // And back out again.
    expect(readColumns("household")).toEqual(["title", "author", "location"]);
    // And back in, to prove the first read did not disturb it either.
    expect(readColumns("cataloguer")).toEqual(["title", "callNumber"]);
  });

  it("drops a stored column the mode does not offer", () => {
    // Not reachable through the picker. Reachable by hand, by a shared
    // browser profile, or by a version that offered more.
    writeColumns("household", ["title", "callNumber", "author"] as ColumnKey[]);
    expect(readColumns("household")).toEqual(["title", "author"]);
  });

  it("draws the title even when the stored set leaves it out", () => {
    writeColumns("household", ["author", "publisher"]);
    expect(readColumns("household")).toEqual(["title", "author", "publisher"]);
  });

  it("puts the columns back in the table's order", () => {
    writeColumns("household", ["publisher", "author", "title"]);
    expect(readColumns("household")).toEqual(["title", "author", "publisher"]);
  });

  it("falls back to the default when the stored set names nothing it knows", () => {
    // A set written by a version whose columns were all called something else.
    // The forced title would otherwise leave a one column table.
    localStorage.setItem("libraryColumns.household", "spine,dustJacket");
    expect(readColumns("household")).toEqual([...DEFAULT_COLUMNS.household]);
  });

  it("falls back to the default when storage refuses to answer", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readColumns("cataloguer")).toEqual([...DEFAULT_COLUMNS.cataloguer]);
  });

  it("says nothing when storage refuses to keep a choice", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => writeColumns("household", ["title"])).not.toThrow();
  });

  it("hands back a copy, not the default set itself", () => {
    // The defaults are exported and shared. A caller sorting or splicing what
    // it was handed would edit them for every later reader.
    const first = readColumns("household");
    first.pop();
    expect(readColumns("household")).toEqual([...DEFAULT_COLUMNS.household]);
  });
});

describe("clearColumns", () => {
  it("goes back to the default rather than storing a copy of it", () => {
    writeColumns("cataloguer", ["title", "callNumber"]);
    clearColumns("cataloguer");

    expect(readColumns("cataloguer")).toEqual([...DEFAULT_COLUMNS.cataloguer]);
    expect(localStorage.getItem("libraryColumns.cataloguer")).toBeNull();
  });

  it("leaves the other mode alone", () => {
    writeColumns("household", ["title", "author"]);
    clearColumns("cataloguer");
    expect(readColumns("household")).toEqual(["title", "author"]);
  });

  it("says nothing when storage refuses", () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => clearColumns("household")).not.toThrow();
  });
});

describe("toggledColumns", () => {
  it("turns one off and leaves the rest", () => {
    expect(
      toggledColumns("household", ["title", "author", "year"], "author"),
    ).toEqual(["title", "year"]);
  });

  it("turns one on in the table's order, not at the end", () => {
    expect(toggledColumns("household", ["title", "year"], "author")).toEqual([
      "title",
      "author",
      "year",
    ]);
  });

  it("refuses to turn the title off", () => {
    // It is the only cell that links to the book, so a table without it is a
    // table you cannot leave.
    expect(
      toggledColumns("household", ["title", "author"], ALWAYS_SHOWN),
    ).toEqual(["title", "author"]);
  });

  it("refuses to turn on a column this mode does not offer", () => {
    expect(toggledColumns("household", ["title"], "callNumber")).toEqual([
      "title",
    ]);
    expect(toggledColumns("cataloguer", ["title"], "callNumber")).toEqual([
      "title",
      "callNumber",
    ]);
  });
});

describe("the specs are the only place a mode is named", () => {
  it("derives both sets from one table rather than a second list", () => {
    // The lists used to be literals, so a fourth cataloguer column would have
    // been a compile error in the label map and none at all in the household's
    // list, and would have reached every household silently. Every membership
    // is now read from `COLUMN_SPECS`, so this is a check on the derivation
    // rather than a second copy of it.
    for (const mode of CATALOGUE_MODES) {
      expect(AVAILABLE_COLUMNS[mode]).toEqual(
        COLUMN_KEYS.filter((key) => COLUMN_SPECS[key].offeredTo.includes(mode)),
      );
      expect(DEFAULT_COLUMNS[mode]).toEqual(
        COLUMN_KEYS.filter((key) => COLUMN_SPECS[key].defaultIn.includes(mode)),
      );
    }
  });

  it("offers the always-shown column in every mode", () => {
    // No type says this and `normalise` cannot rescue it: it filters over
    // `AVAILABLE_COLUMNS[mode]`, so its forced-title arm cannot fire for a key
    // the mode does not offer. `title: { offeredTo: HOUSEHOLD }` compiles and
    // hands a cataloguer a table with no link to any book.
    for (const mode of CATALOGUE_MODES) {
      expect(AVAILABLE_COLUMNS[mode]).toContain(ALWAYS_SHOWN);
      expect(readColumns(mode)).toContain(ALWAYS_SHOWN);
    }
    // The cause as well as the symptom, so a reader knows where to fix it.
    expect([...COLUMN_SPECS[ALWAYS_SHOWN].offeredTo]).toEqual([
      ...CATALOGUE_MODES,
    ]);
  });

  it("gives every column at least one mode", () => {
    // A spec offered to nobody is a column that exists and can never be drawn.
    for (const key of COLUMN_KEYS) {
      expect(COLUMN_SPECS[key].offeredTo.length).toBeGreaterThan(0);
    }
  });
});

describe("a title-only table", () => {
  it("is a choice the picker can produce", () => {
    // Turning off every other household chip.
    const stripped = AVAILABLE_COLUMNS.household.reduce<ColumnKey[]>(
      (columns, key) => toggledColumns("household", columns, key),
      [...DEFAULT_COLUMNS.household],
    );
    expect(stripped).toEqual(["title"]);
  });

  it("survives a reload rather than reverting to the default", () => {
    // `readColumns` used to decide on its own result, which always carries the
    // forced title, so it could not tell this from a value naming nothing it
    // knows. It decides on the stored tokens.
    writeColumns("household", ["title"]);
    expect(readColumns("household")).toEqual(["title"]);
  });
});

describe("storage never holds a copy of the default", () => {
  it("clears the key when a choice lands back on the default", () => {
    // Turning one column off and straight back on is the ordinary way to get
    // here. Storing a frozen copy would stop the browser following the default
    // if a later version changed it, and would leave the reset control hidden
    // because there is nothing to reset from.
    writeColumns(
      "household",
      toggledColumns("household", DEFAULT_COLUMNS.household, "price"),
    );
    expect(localStorage.getItem("libraryColumns.household")).not.toBeNull();

    writeColumns("household", [...DEFAULT_COLUMNS.household]);
    expect(localStorage.getItem("libraryColumns.household")).toBeNull();
    expect(readColumns("household")).toEqual([...DEFAULT_COLUMNS.household]);
  });

  it("clears the key for a default set given in any order", () => {
    // `isDefaultColumns` compares joined strings, so an unordered set equal to
    // the default would have slipped past the guard and been stored raw: a
    // frozen copy of the default, with the reset control hidden because the
    // normalised set on screen reports itself as the default. `writeColumns`
    // normalises its input first, so the guard holds for any caller rather
    // than only for the one that happens to pass a canonical set.
    writeColumns("household", [...DEFAULT_COLUMNS.household].reverse());
    expect(localStorage.getItem("libraryColumns.household")).toBeNull();
  });

  it("stores a set the mode does not fully offer in its normalised form", () => {
    // The same slip in its other shape: an extra key made the join differ from
    // the default's, so the guard read false.
    writeColumns("household", [
      ...DEFAULT_COLUMNS.household,
      "callNumber",
    ] as ColumnKey[]);
    expect(localStorage.getItem("libraryColumns.household")).toBeNull();
  });

  it("says when a set is the default and when it is not", () => {
    expect(isDefaultColumns("household", [...DEFAULT_COLUMNS.household])).toBe(
      true,
    );
    expect(isDefaultColumns("household", ["title", "author"])).toBe(false);
    // Each mode against its own, never against the other's.
    expect(isDefaultColumns("cataloguer", [...DEFAULT_COLUMNS.household])).toBe(
      false,
    );
  });
});
