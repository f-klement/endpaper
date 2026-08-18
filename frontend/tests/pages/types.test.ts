/** Tests for src/pages/types.ts: the shared tag grouping and constants. */

import { beforeEach, describe, expect, it } from "vitest";

import { TagCategory } from "../../src/api/generated/model";
import {
  TAG_BAR_CLASSES,
  TAG_CATEGORY_LABELS,
  TAG_CATEGORY_ORDER,
  TAG_CHIP_CLASSES,
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

  it("is broad-to-narrow, which is the order the UI reads in", () => {
    expect(TAG_CATEGORY_ORDER).toEqual([
      TagCategory.type,
      TagCategory.genre,
      TagCategory.age,
    ]);
  });
});

describe("style tables", () => {
  // A missing entry renders an unstyled pill rather than throwing, so a gap
  // here is the kind of thing only a test notices.
  it.each([
    ["labels", TAG_CATEGORY_LABELS],
    ["pill classes", TAG_PILL_CLASSES],
    ["bar classes", TAG_BAR_CLASSES],
    ["chip classes", TAG_CHIP_CLASSES],
  ])("%s cover every category", (_name, table) => {
    for (const category of Object.values(TagCategory)) {
      expect(table[category]).toBeDefined();
    }
  });

  it("chip classes carry both a resting and a selected style", () => {
    for (const category of Object.values(TagCategory)) {
      expect(TAG_CHIP_CLASSES[category].base).toBeTruthy();
      expect(TAG_CHIP_CLASSES[category].active).toBeTruthy();
    }
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
