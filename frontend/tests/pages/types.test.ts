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
  BookCondition,
  BookFormat,
  LendingWillingness,
  Locale,
  ReadStatus,
  TagCategory,
} from "../../src/api/generated/model";
import {
  CONDITION_ORDER,
  FORMAT_LABELS,
  FORMAT_ORDER,
  LENDING_LABELS,
  LENDING_ORDER,
  MODE_LABELS,
  MODE_ORDER,
  STATUS_ORDER,
  TAG_CATEGORY_LABELS,
  TAG_CATEGORY_ORDER,
  TAG_CHIP_CLASSES,
  TAG_CHIP_SELECTED,
  TAG_PILL_CLASSES,
  everyOneOf,
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

describe("FORMAT_ORDER", () => {
  it("covers every format", () => {
    // **The list the type cannot check.** `FORMAT_LABELS` is a total `Record`,
    // so a format with no name is a compile error; this is a plain array, and
    // every dropdown and filter in the app is built from it. A format left out
    // is one a member can never choose and never filter by, with nothing red.
    expect(new Set(FORMAT_ORDER)).toEqual(new Set(Object.values(BookFormat)));
  });

  it("offers each one once", () => {
    // A duplicate is two identical options in every dropdown built from this.
    expect(FORMAT_ORDER).toHaveLength(new Set(FORMAT_ORDER).size);
  });

  it("keeps the catch-all last", () => {
    // Wherever the rest end up, "Other" is not a peer of the ones above it.
    expect(FORMAT_ORDER.at(-1)).toBe(BookFormat.other);
  });

  it("names every one of them", () => {
    for (const format of FORMAT_ORDER) {
      expect(FORMAT_LABELS[format]).toBeTruthy();
    }
  });
});

describe("the reading statuses", () => {
  it("refuses a list that leaves one of them out", () => {
    // Coverage is the compiler's job here rather than a runtime assertion's, so
    // what has to be pinned is that the compiler still refuses.
    // `@ts-expect-error` is itself an error when the line under it typechecks,
    // and `tsconfig.json` includes `tests`, so a helper that stops refusing
    // turns this directive unused and the typecheck red.
    //
    // **This pins the helper and not any call of it.** Deleting the wrapper
    // from `STATUS_ORDER` leaves the helper here, still called, still
    // refusing; the test below is the one that would notice. The first version
    // of this comment claimed otherwise, which is the rung where a comment
    // asserts a guard the code does not have.
    // @ts-expect-error did_not_finish is missing from this list
    const incomplete = everyOneOf<ReadStatus>()([
      ReadStatus.unread,
      ReadStatus.want_to_read,
      ReadStatus.reading,
      ReadStatus.read,
    ]);

    // The complete call carries no directive, so a signature that made **every**
    // call an error would go red here rather than passing as a suppressed one:
    // `@ts-expect-error` hides whatever error is on its line, not the error
    // that was meant. Written out rather than spread from `STATUS_ORDER`, which
    // would make this arm inherit whatever that constant's type had become.
    const complete = everyOneOf<ReadStatus>()([
      ReadStatus.unread,
      ReadStatus.want_to_read,
      ReadStatus.reading,
      ReadStatus.read,
      ReadStatus.did_not_finish,
    ]);

    // The refusal is entirely at compile time. At runtime both calls are the
    // identity, which is what makes the check free at every call site.
    expect(incomplete).toHaveLength(4);
    expect(complete).toHaveLength(5);
  });

  it("keeps the order in a shape this check can still read", () => {
    // **The guard on the constant rather than on the helper.** Two ways to
    // lose the refusal silently, both of which leave every other test in this
    // file passing: unwrap `STATUS_ORDER` back to a plain array literal, or
    // widen its type. Widening is the quiet one, because it looks like
    // consistency with the older lists in that file and it throws away the
    // members the first arm reads.
    //
    // The probe is tuple-ness rather than any one spelling of the widening.
    // `: readonly ReadStatus[]`, `: ReadStatus[]` and an `as ReadStatus[]`
    // inside the call all erase the same fact, and a probe naming one of them
    // is a guard enumerating something open.
    type Uncovered = Exclude<ReadStatus, (typeof STATUS_ORDER)[number]>;
    type Widened = typeof STATUS_ORDER extends readonly [
      ReadStatus,
      ...ReadStatus[],
    ]
      ? false
      : true;

    const offersEveryStatus: Widened extends true
      ? "STATUS_ORDER has been widened, which erases what this test reads"
      : [Uncovered] extends [never]
        ? true
        : Uncovered = true;

    expect(offersEveryStatus).toBe(true);
  });

  it("offers each status once", () => {
    // The type cannot see a duplicate: a list naming one status twice still
    // excludes nothing. Two identical pills in the filter strip is what that
    // would look like.
    expect(STATUS_ORDER).toHaveLength(new Set(STATUS_ORDER).size);
  });

  it("offers them in the order somebody reads a book", () => {
    // Not the alphabet and not the generated enum's declaration order, which
    // agrees with this today and is not a decision anybody made. Asserted as
    // the whole sequence, the way `TAG_CATEGORY_ORDER` is: the filter strip
    // and the status picker both render this, so a reflow here is a visible
    // change to two screens and should have to be argued for.
    expect([...STATUS_ORDER]).toEqual([
      ReadStatus.unread,
      ReadStatus.want_to_read,
      ReadStatus.reading,
      ReadStatus.read,
      ReadStatus.did_not_finish,
    ]);
  });
});

describe("the copy conditions", () => {
  // `CONDITION_ORDER` was the one list in this file with no guard of any kind,
  // and the wrapper it now carries closes only what the type can see. These are
  // the two properties it cannot: the compiler has no opinion on a duplicate,
  // and none at all on a sequence its docstring calls best to worst.
  it("offers each condition once", () => {
    expect(CONDITION_ORDER).toHaveLength(new Set(CONDITION_ORDER).size);
  });

  it("runs best to worst, with the provenance category last", () => {
    // `ex_library` is not a point on the scale, so sorting it into the middle
    // would imply it is one.
    expect([...CONDITION_ORDER]).toEqual([
      BookCondition.new,
      BookCondition.good,
      BookCondition.fair,
      BookCondition.poor,
      BookCondition.ex_library,
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
    const grouped = groupTagsByCategory(makeTagSet(), Locale.en);
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
    const grouped = groupTagsByCategory([], Locale.en);
    for (const category of Object.values(TagCategory)) {
      expect(grouped[category]).toEqual([]);
    }
  });

  it("keeps several tags in the same category", () => {
    const grouped = groupTagsByCategory(
      [
        makeTag({ name: "Fantasy", category: TagCategory.genre }),
        makeTag({ name: "Horror", category: TagCategory.genre }),
      ],
      Locale.en,
    );
    expect(grouped[TagCategory.genre]).toHaveLength(2);
  });

  it("orders the tags inside a category by name", () => {
    // Not the order it was given, which used to be the assertion here: the
    // endpoint's `Tag.category, Tag.name` is a codepoint sort, so an accented
    // tag arrived below every ASCII one inside its own category.
    const grouped = groupTagsByCategory(
      [
        makeTag({ name: "Horror", category: TagCategory.genre }),
        makeTag({ name: "Ökologie", category: TagCategory.genre }),
        makeTag({ name: "Fantasy", category: TagCategory.genre }),
      ],
      Locale.en,
    );
    expect(grouped[TagCategory.genre].map((tag) => tag.name)).toEqual([
      "Fantasy",
      "Horror",
      "Ökologie",
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
