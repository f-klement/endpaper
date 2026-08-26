/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/** Tests for src/pages/types.ts: the shared tag grouping and constants. */

import { beforeEach, describe, expect, it } from "vitest";

import {
  LendingWillingness,
  TagCategory,
} from "../../src/api/generated/model";
import {
  LENDING_LABELS,
  LENDING_ORDER,
  MODE_LABELS,
  MODE_ORDER,
  TAG_CATEGORY_LABELS,
  TAG_CATEGORY_ORDER,
  TAG_CHIP_CLASSES,
  TAG_CHIP_SELECTED,
  TAG_PILL_CLASSES,
  groupTagsByCategory,
} from "../../src/pages/types";
import { makeTag, makeTagSet, resetIds } from "../factories";

beforeEach(resetIds);

describe("TAG_CATEGORY_ORDER", () => {
  it("covers every category", () => {
    expect(new Set(TAG_CATEGORY_ORDER)).toEqual(
      new Set(Object.values(TagCategory)),
    );
  });

  it("is broad-to-narrow, with this library's own tags last", () => {
    // Custom sits at the end rather than being interleaved: scattering
    // "Holiday reads" through a curated genre list is what makes the curated
    // list hard to scan, and being easy to scan on the first day is the whole
    // reason it is curated.
    expect(TAG_CATEGORY_ORDER).toEqual([
      TagCategory.type,
      TagCategory.genre,
      TagCategory.age,
      TagCategory.custom,
    ]);
  });
});

describe("style tables", () => {
  // A missing entry renders an unstyled pill rather than throwing, so a gap
  // here is the kind of thing only a test notices.
  it.each([
    ["labels", TAG_CATEGORY_LABELS],
    ["pill classes", TAG_PILL_CLASSES],
    ["chip classes", TAG_CHIP_CLASSES],
  ])("%s cover every category", (_name, table) => {
    for (const category of Object.values(TagCategory)) {
      expect(table[category]).toBeTruthy();
    }
  });

  it("carries no hue of its own but the accent", () => {
    // Type, genre and age used to be a blue, a purple and a green, which was
    // the one place in this app where a colour was chosen at random. All four
    // selected chips failed AA on top of that, the green at 2.28:1. Custom
    // keeps the accent, because a tag the library invented reading as theirs
    // is a distinction with a reason.
    //
    // The four named here are the four that were deleted, and this asserts it
    // of these tables only. `amber` and `orange` are still untokenised on the
    // reading badge, the loan badge and the ownership chip: they are a separate
    // family with a separate fix, and naming them in a rule that covers three
    // constants would read as a house rule the tree does not keep.
    const written = [
      ...Object.values(TAG_PILL_CLASSES),
      ...Object.values(TAG_CHIP_CLASSES),
      TAG_CHIP_SELECTED,
    ].join(" ");

    expect(written).not.toMatch(/\b(blue|purple|green|indigo)-/);
  });

  it("selects with the accent fill and its paired foreground", () => {
    // `text-white` on the fill is a bet that loses in nine themes of twelve.
    expect(TAG_CHIP_SELECTED).toContain("bg-accent-fill");
    expect(TAG_CHIP_SELECTED).toContain("text-on-accent");
    expect(TAG_CHIP_SELECTED).not.toContain("text-white");
  });
});

describe("groupTagsByCategory", () => {
  it("puts each tag under its own category", () => {
    const grouped = groupTagsByCategory(makeTagSet());
    expect(grouped[TagCategory.type].map((tag) => tag.name)).toEqual([
      "Fiction",
    ]);
    expect(grouped[TagCategory.genre].map((tag) => tag.name)).toEqual([
      "Fantasy",
    ]);
    expect(grouped[TagCategory.age].map((tag) => tag.name)).toEqual(["Adult"]);
  });

  it("returns an entry for every category, even when empty", () => {
    // Callers index straight into the result, so a missing key would be a
    // crash rather than an empty section.
    const grouped = groupTagsByCategory([]);
    for (const category of Object.values(TagCategory)) {
      expect(grouped[category]).toEqual([]);
    }
  });

  it("keeps several tags in the same category", () => {
    const grouped = groupTagsByCategory([
      makeTag({ name: "Fantasy", category: TagCategory.genre }),
      makeTag({ name: "Horror", category: TagCategory.genre }),
    ]);
    expect(grouped[TagCategory.genre]).toHaveLength(2);
  });

  it("preserves the order it was given", () => {
    const grouped = groupTagsByCategory([
      makeTag({ name: "Horror", category: TagCategory.genre }),
      makeTag({ name: "Fantasy", category: TagCategory.genre }),
    ]);
    expect(grouped[TagCategory.genre].map((tag) => tag.name)).toEqual([
      "Horror",
      "Fantasy",
    ]);
  });
});

describe("the light and dark modes", () => {
  it("offers every one it can name", () => {
    // Two facts, one per constant, and a mode present in one and not the other
    // is either a button with no label or a label nobody can reach.
    expect([...MODE_ORDER].sort()).toEqual(Object.keys(MODE_LABELS).sort());
  });

  it("offers the default last", () => {
    // A default reads better as the thing you return to than the thing you
    // start at, and both screens take their order from here.
    expect(MODE_ORDER[MODE_ORDER.length - 1]).toBe("system");
  });
});

describe("the lending willingness", () => {
  it("names every answer the backend can send", () => {
    // A `Record<...>` rather than a lookup with a default, so a fourth value
    // added to the enum is a compile error here and not a blank cell.
    expect(Object.keys(LENDING_LABELS).sort()).toEqual(
      Object.values(LendingWillingness).sort(),
    );
  });

  it("offers every one of them, and nothing else", () => {
    expect([...LENDING_ORDER].sort()).toEqual(
      Object.values(LendingWillingness).sort(),
    );
  });

  it("offers the yes first and the no last", () => {
    // The order somebody would say them in, rather than the order the enum
    // happens to declare.
    expect(LENDING_ORDER[0]).toBe(LendingWillingness.happy);
    expect(LENDING_ORDER[LENDING_ORDER.length - 1]).toBe(
      LendingWillingness.never,
    );
  });
});
