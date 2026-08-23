/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/** Tests for src/pages/Home/types.ts. */

import { describe, expect, it } from "vitest";

import {
  BookSort,
  LendingWillingness,
  ReadStatus,
} from "../../../src/api/generated/model";
import {
  DEFAULT_FILTERS,
  LENDING_FILTERS,
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
    ["a lending answer", { lending: LendingWillingness.happy }],
    ["the talk-about-it filter", { discuss: true }],
    ["a collection", { collection: 3 }],
    // Both spellings of the field narrow the view, so both count.
    ["the unfiled books", { collection: "unfiled" as const }],
    ["an author", { author: "ursula k le guin" }],
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

describe("the lending filter", () => {
  it("offers every answer, plus one that narrows nothing", () => {
    const values = LENDING_FILTERS.map((option) => option.value);
    expect(values).toContain(null);
    for (const willingness of Object.values(LendingWillingness)) {
      expect(values).toContain(willingness);
    }
  });

  it("starts on the one that narrows nothing", () => {
    expect(DEFAULT_FILTERS.lending).toBeNull();
  });

  it("starts with the talk-about-it filter off", () => {
    // Off is the whole library. The books nobody has offered to talk about
    // are not a view worth having, which is why this is a toggle rather than
    // a third dropdown.
    expect(DEFAULT_FILTERS.discuss).toBe(false);
  });
});
