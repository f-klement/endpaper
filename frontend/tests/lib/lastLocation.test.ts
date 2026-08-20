/**
 * Tests for src/lib/lastLocation.ts.
 *
 * The whole value of this module is that it survives between books, so the
 * cases worth pinning are the ones where it must NOT remember: a cleared
 * field, and a browser that refuses storage.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAX_LOCATION_LENGTH,
  normaliseLocation,
  readLastLocation,
  rememberLastLocation,
} from "../../src/lib/lastLocation";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("normaliseLocation", () => {
  it("trims surrounding space", () => {
    expect(normaliseLocation("  Loft box 2  ")).toBe("Loft box 2");
  });

  it("treats a null as empty", () => {
    expect(normaliseLocation(null)).toBe("");
    expect(normaliseLocation(undefined)).toBe("");
  });

  it("caps at the column's length", () => {
    expect(normaliseLocation("x".repeat(500))).toHaveLength(MAX_LOCATION_LENGTH);
  });

  it("does not leave a trailing space when the cap falls on one", () => {
    const cut = `${"x".repeat(MAX_LOCATION_LENGTH - 1)} y`;
    expect(normaliseLocation(cut)).toBe("x".repeat(MAX_LOCATION_LENGTH - 1));
  });
});

describe("rememberLastLocation", () => {
  it("carries a shelf over to the next book", () => {
    rememberLastLocation("Living room shelf 3");
    expect(readLastLocation()).toBe("Living room shelf 3");
  });

  it("forgets when the field is cleared", () => {
    rememberLastLocation("Loft box 2");
    rememberLastLocation("");
    expect(readLastLocation()).toBe("");
  });

  it("forgets when the field holds only space", () => {
    rememberLastLocation("Loft box 2");
    rememberLastLocation("   ");
    expect(readLastLocation()).toBe("");
  });

  it("stores the trimmed form, not what was typed", () => {
    rememberLastLocation("  Kitchen  ");
    expect(localStorage.getItem("lastLocation")).toBe("Kitchen");
  });
});

describe("when storage is unavailable", () => {
  it("reads as empty rather than throwing", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readLastLocation()).toBe("");
  });

  it("writes silently rather than failing the add", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => rememberLastLocation("Kitchen")).not.toThrow();
  });
});
