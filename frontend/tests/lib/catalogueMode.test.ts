/**
 * Tests for src/lib/catalogueMode.ts.
 */

import { describe, expect, it } from "vitest";

import { CATALOGUE_MODES, catalogueMode } from "../../src/lib/catalogueMode";

describe("catalogueMode", () => {
  it("reads an unanswered flag as a household", () => {
    // The flags are fetched, so there is a moment before they arrive. A
    // household briefly seeing a cataloguer's table is the wrong way round:
    // every existing library is a household.
    expect(catalogueMode(undefined)).toBe("household");
    expect(catalogueMode(false)).toBe("household");
    expect(catalogueMode(true)).toBe("cataloguer");
  });

  it("answers with a mode the modes list holds", () => {
    // The type says so and the type is erased. Two callers key a
    // `Record<CatalogueMode, ...>` on this answer, so a mode outside the list
    // is an undefined lookup rather than a compile error.
    for (const flag of [undefined, false, true]) {
      expect(CATALOGUE_MODES).toContain(catalogueMode(flag));
    }
  });
});
