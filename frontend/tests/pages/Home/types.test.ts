/** Tests for src/pages/Home/types.ts. */

import { describe, expect, it } from "vitest";

import { BookSort, ReadStatus } from "../../../src/api/generated/model";
import {
  DEFAULT_FILTERS,
  SORT_OPTIONS,
  STATUS_FILTERS,
  hasActiveFilters,
} from "../../../src/pages/Home/types";

describe("DEFAULT_FILTERS", () => {
  it("starts unfiltered", () => {
    expect(hasActiveFilters(DEFAULT_FILTERS)).toBe(false);
  });

  it("sorts by title, which is what the API also defaults to", () => {
    expect(DEFAULT_FILTERS.sort).toBe(BookSort.title_asc);
  });
});

describe("hasActiveFilters", () => {
  it("is false for the defaults", () => {
    expect(hasActiveFilters(DEFAULT_FILTERS)).toBe(false);
  });

  it.each([
    ["a search term", { query: "dune" }],
    ["a status", { status: ReadStatus.read }],
    ["a tag", { tagIds: [1] }],
  ])("is true with %s", (_label, overrides) => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, ...overrides })).toBe(true);
  });

  it("does not count sorting as filtering", () => {
    // Sorting changes the order, not the set, so an empty result while
    // sorted should still read as "nothing here", not "adjust your filters".
    expect(
      hasActiveFilters({ ...DEFAULT_FILTERS, sort: BookSort.newest }),
    ).toBe(false);
  });
});

describe("option lists", () => {
  it("offers every reading status, plus All", () => {
    const values = STATUS_FILTERS.map((option) => option.value);
    expect(values).toContain(null);
    for (const status of Object.values(ReadStatus)) {
      expect(values).toContain(status);
    }
  });

  it("offers only sorts the API accepts", () => {
    const accepted = new Set<string>(Object.values(BookSort));
    for (const option of SORT_OPTIONS) {
      expect(accepted.has(option.value)).toBe(true);
    }
  });

  it("gives every sort a distinct value", () => {
    const values = SORT_OPTIONS.map((option) => option.value);
    expect(new Set(values).size).toBe(values.length);
  });
});
