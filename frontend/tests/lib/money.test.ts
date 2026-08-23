/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/**
 * Tests for src/lib/money.ts.
 *
 * A price is stored as an integer count of cents, so every value entered by a
 * person crosses this module. The cases that matter are the ones where a
 * wrong answer is silent: a comma from a German keyboard, and a typo that
 * must not become zero.
 */

import { describe, expect, it } from "vitest";

import { formatMinor, parseMinor } from "../../src/lib/money";

describe("formatMinor", () => {
  it("shows cents as a decimal", () => {
    expect(formatMinor(1299)).toBe("12.99");
  });

  it("always shows two places, so a column of prices lines up", () => {
    expect(formatMinor(1200)).toBe("12.00");
    expect(formatMinor(5)).toBe("0.05");
  });

  it("shows nothing when there is no price", () => {
    expect(formatMinor(null)).toBe("");
    expect(formatMinor(undefined)).toBe("");
  });

  it("shows a free book as zero rather than as blank", () => {
    expect(formatMinor(0)).toBe("0.00");
  });
});

describe("parseMinor", () => {
  it("reads a decimal price as cents", () => {
    expect(parseMinor("12.99")).toBe(1299);
  });

  it("reads a comma as a decimal separator", () => {
    // What a German keyboard produces, and the same number.
    expect(parseMinor("12,99")).toBe(1299);
  });

  it("reads a whole number", () => {
    expect(parseMinor("12")).toBe(1200);
  });

  it("reads one decimal place", () => {
    expect(parseMinor("12.5")).toBe(1250);
  });

  it("treats an empty field as clearing the price", () => {
    expect(parseMinor("")).toBeNull();
    expect(parseMinor("   ")).toBeNull();
  });

  it("refuses a typo rather than storing zero", () => {
    for (const raw of ["twelve", "12.999", "1 2", "-5", "12.9.9", "€12"]) {
      expect(parseMinor(raw)).toBeUndefined();
    }
  });
});
