/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/**
 * Tests for src/lib/isbn.ts.
 *
 * Deliberately mirrors `backend/tests/test_isbn.py` case for case. The two
 * implementations are duplicated (the scanner cannot make a network call per
 * video frame), so the only thing keeping them in agreement is that both are
 * held to the same table.
 */

import { describe, expect, it } from "vitest";

import {
  isValidIsbn,
  isValidIsbn10,
  isValidIsbn13,
  isbn10ToIsbn13,
  normalise,
  parseIsbn,
} from "../../src/lib/isbn";

const DUNE_13 = "9780441013593";
const DUNE_10 = "0441013597";
/** An ISBN-10 whose check digit is X. Roughly one in eleven ends this way. */
const X_CHECK_10 = "043942089X";

describe("normalise", () => {
  it.each(["978-0-441-01359-3", "978 0 441 01359 3", "  9780441013593  "])(
    "strips the grouping publishers print: %s",
    (raw) => {
      expect(normalise(raw)).toBe(DUNE_13);
    },
  );

  it("upper-cases the check digit", () => {
    expect(normalise("043942089x")).toBe(X_CHECK_10);
  });
});

describe("isValidIsbn13", () => {
  it("accepts a real ISBN", () => {
    expect(isValidIsbn13(DUNE_13)).toBe(true);
  });

  it("rejects a single wrong digit", () => {
    // Previously accepted: no checksum was verified at all.
    expect(isValidIsbn13("9780441013594")).toBe(false);
  });

  it.each(["978044101359", "97804410135933", "978044101359X"])(
    "rejects wrong length or non-digits: %s",
    (candidate) => {
      expect(isValidIsbn13(candidate)).toBe(false);
    },
  );
});

describe("isValidIsbn10", () => {
  it("accepts a real ISBN", () => {
    expect(isValidIsbn10(DUNE_10)).toBe(true);
  });

  it("accepts an X check digit", () => {
    // The defect that made a real slice of older books unscannable.
    expect(isValidIsbn10(X_CHECK_10)).toBe(true);
  });

  it("rejects a wrong check digit", () => {
    expect(isValidIsbn10("0441013590")).toBe(false);
  });

  it("rejects X anywhere but the end", () => {
    expect(isValidIsbn10("X441013597")).toBe(false);
  });
});

describe("isbn10ToIsbn13", () => {
  it("produces the matching ISBN-13", () => {
    expect(isbn10ToIsbn13(DUNE_10)).toBe(DUNE_13);
  });

  it("converts an X check digit to a valid ISBN-13", () => {
    expect(isValidIsbn13(isbn10ToIsbn13(X_CHECK_10))).toBe(true);
  });
});

describe("parseIsbn", () => {
  it("returns the canonical form unchanged", () => {
    expect(parseIsbn(DUNE_13)).toBe(DUNE_13);
  });

  it("converts an ISBN-10 to ISBN-13", () => {
    // What makes the unique constraint mean anything: the same book scanned
    // in either form lands on one stored value.
    expect(parseIsbn(DUNE_10)).toBe(DUNE_13);
  });

  it.each(["978-0-441-01359-3", " 9780441013593 ", "0-441-01359-7"])(
    "accepts the forms people actually paste: %s",
    (raw) => {
      expect(parseIsbn(raw)).toBe(DUNE_13);
    },
  );

  it("accepts an X check digit", () => {
    expect(parseIsbn(X_CHECK_10)).not.toBeNull();
  });

  // Typed explicitly: a mixed table of string/null/undefined otherwise infers
  // a union of tuples, and the callback parameter stops being assignable.
  const rejected: [string | null | undefined, string][] = [
    ["9780441013594", "one digit misread"],
    ["0441013590", "bad ISBN-10 check digit"],
    ["12345", "too short"],
    ["not an isbn", "words"],
    ["", "empty"],
    [null, "null"],
    [undefined, "undefined"],
  ];

  it.each(rejected)("rejects %s (%s)", (raw) => {
    expect(parseIsbn(raw)).toBeNull();
  });

  it("rejects a valid EAN-13 that is not a book", () => {
    // A food packet's barcode passes the EAN-13 checksum but is not Bookland.
    expect(parseIsbn("5012345678900")).toBeNull();
  });

  it("accepts the 979 range", () => {
    expect(parseIsbn("9791234567896")).toBe("9791234567896");
  });
});

describe("isValidIsbn", () => {
  it("agrees with parseIsbn", () => {
    expect(isValidIsbn(DUNE_10)).toBe(true);
    expect(isValidIsbn("9780441013594")).toBe(false);
  });
});
