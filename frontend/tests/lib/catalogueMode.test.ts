/**
 * Tests for src/lib/catalogueMode.ts.
 */

import { describe, expect, it } from "vitest";

import { catalogueMode } from "../../src/lib/catalogueMode";

describe("catalogueMode", () => {
  it("reads an unanswered flag as a household", () => {
    // The flags are fetched, so there is a moment before they arrive. A
    // household briefly seeing a cataloguer's table is the wrong way round:
    // every existing library is a household.
    expect(catalogueMode(undefined)).toBe("household");
    expect(catalogueMode(false)).toBe("household");
    expect(catalogueMode(true)).toBe("cataloguer");
  });
});
