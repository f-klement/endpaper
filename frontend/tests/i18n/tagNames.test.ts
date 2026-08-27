/**
 * Tests for src/i18n/tagNames.ts.
 *
 * The table's completeness is a compile-time property (`Record<TagKey, string>`
 * against the generated union), so it is not re-tested here. What is tested is
 * everything the type system cannot see: which name a given tag prints, and
 * whether the German words are usable ones.
 */

import { describe, expect, it } from "vitest";

import { Locale, TagKey } from "../../src/api/generated/model";
import { tagName } from "../../src/i18n";
// The table itself, from the module rather than the barrel: `i18n/index.tsx`
// exports only `tagName`, so that a component cannot reach the words without
// the fallback around them.
import { TAG_NAMES } from "../../src/i18n/tagNames";

const de = TAG_NAMES[Locale.de];

/** A tag as `tagName` sees it: what it is called, and which seeded tag it is. */
function tag(name: string, key: TagKey | null = null) {
  return { name, key };
}

describe("tagName", () => {
  it("prints the German name of a seeded tag to a German reader", () => {
    expect(tagName(tag("Computing", TagKey.computing), Locale.de)).toBe(
      "Informatik",
    );
  });

  it("prints the stored name to an English reader", () => {
    expect(tagName(tag("Computing", TagKey.computing), Locale.en)).toBe(
      "Computing",
    );
  });

  it("leaves a tag the library invented exactly as it was typed", () => {
    // The user story this whole feature is bounded by: translation applies to
    // the seeded vocabulary and to nothing else.
    expect(tagName(tag("Holiday reads"), Locale.de)).toBe("Holiday reads");
  });

  it("leaves a renamed seeded tag alone, because it has no key", () => {
    // How a rename survives: the migration keys only the rows still carrying
    // the seeded name, so this one arrives with none and is theirs.
    expect(tagName(tag("Geschichten"), Locale.de)).toBe("Geschichten");
  });

  it("falls back to the stored name for a key it does not know", () => {
    // An older client against a newer API. The alternative is a blank chip.
    const unknown = { name: "Quantum Gardening", key: "quantum_gardening" };
    expect(tagName(unknown as { name: string; key: TagKey }, Locale.de)).toBe(
      "Quantum Gardening",
    );
  });
});

describe("the German tag names", () => {
  it("cover every key the backend can send", () => {
    // The compile error is the real guard. This is the tripwire under it: a
    // table cast or widened somewhere would silence the type and nothing else
    // would notice.
    expect(Object.keys(de).sort()).toEqual(Object.values(TagKey).sort());
  });

  it("are none of them blank", () => {
    expect(Object.entries(de).filter(([, value]) => !value.trim())).toEqual([]);
  });

  it("are distinct, so no two seeded tags read the same in a picker", () => {
    // **Seeded ones only, and the title says so because the stronger claim is
    // false.** `create_tag` and the importer fold a typed name against the
    // stored English names, so a member can invent "Informatik" beside the
    // seeded Computing and see two chips reading the same word. Why that is
    // not closed here: `src/i18n/tagNames.ts`.
    const seen = new Map<string, string[]>();
    for (const [key, value] of Object.entries(de)) {
      seen.set(value, [...(seen.get(value) ?? []), key]);
    }
    const collisions = [...seen.entries()].filter(
      ([, keys]) => keys.length > 1,
    );
    expect(collisions).toEqual([]);
  });
});
