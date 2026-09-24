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
    ["a heading", { headings: ["lcsh:Mental health"] }],
    ["a Dewey division", { ddcDivisions: ["150"] }],
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

describe("the sort options", () => {
  it("offers each shelf order as its own value rather than one general one", () => {
    // Named for the scheme because a scheme decides how its numbers sort. An
    // LCC call number does not sort as text, so it files under its own rule in
    // `backend/filing.py` rather than under Dewey's.
    const values = SORT_OPTIONS.map((option) => option.value);

    expect(values).toContain(BookSort.ddc);
    expect(values).toContain(BookSort.lcc);
  });

  it("offers every sort the API accepts", () => {
    // The other direction, and the one that goes stale on its own: a sort
    // added to the enum is a sort the grid cannot reach until somebody adds it
    // here, with nothing failing.
    const values = SORT_OPTIONS.map((option) => option.value);

    expect([...values].sort()).toEqual(Object.values(BookSort).sort());
  });
});

describe("option lists", () => {
  it("offers the shared status order, behind one pill that narrows nothing", () => {
    // This was a containment check over `Object.values(ReadStatus)`, which the
    // strip now satisfies by construction: it is built from `STATUS_ORDER` and
    // `STATUS_LABELS` rather than written out. Order and names are what the
    // derivation could still lose, so both are asserted, and the five message
    // keys are written out rather than read back from `STATUS_LABELS`:
    // recomputing them from the table the strip is built from would restate the
    // derivation and could not fail. `All` leads rather than sitting among
    // them, being the absence of a filter and not a sixth status.
    expect(STATUS_FILTERS).toEqual([
      { label: "status.all", value: null },
      { label: "status.unread", value: ReadStatus.unread },
      { label: "status.want_to_read", value: ReadStatus.want_to_read },
      { label: "status.reading", value: ReadStatus.reading },
      { label: "status.read", value: ReadStatus.read },
      { label: "status.did_not_finish", value: ReadStatus.did_not_finish },
    ]);
  });

  it("gives every pill a label of its own", () => {
    // `BookFilters` keys the pills on the label rather than on the value, so
    // two statuses sharing a message key is a duplicate React key and a pill
    // that presses the wrong one. Written out by hand the five were distinct by
    // eye; read from a shared table it is a property somebody has to assert.
    const labels = STATUS_FILTERS.map((option) => option.label);

    expect(new Set(labels).size).toBe(labels.length);
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
