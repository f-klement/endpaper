/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom.
 */
/**
 * Tests for src/lib/isbnLabel.ts.
 *
 * Separate from `isbn.test.ts` for the reason the module is separate: that one
 * mirrors `backend/tests/test_isbn.py` case for case and this rule has no
 * Python counterpart.
 */
import { describe, expect, it } from "vitest";

import { parseIsbn } from "../../src/lib/isbn";
import { stripIsbnPrefix } from "../../src/lib/isbnLabel";

const DUNE_13 = "9780441013593";
const DUNE_10 = "0441013597";

describe("stripIsbnPrefix", () => {
  /**
   * The four spellings four readers each used to decide for themselves.
   *
   * `appleBooks.ts` and `adobeDigitalEditions.ts` took `urn:` as optional;
   * `opf.ts` and `calibre.ts` required it, so both refused `ISBN:` and `isbn_`
   * on a value that had announced itself as an ISBN. They now share one rule
   * and this is the test of it.
   */
  it.each([
    ["urn:isbn:9780441013593", ":9780441013593"],
    ["URN:ISBN:9780441013593", ":9780441013593"],
    ["isbn_9780441013593", "_9780441013593"],
    ["ISBN:9780441013593", ":9780441013593"],
    ["isbn 9780441013593", " 9780441013593"],
  ])("takes the label off %s", (written, bare) => {
    expect(stripIsbnPrefix(written)).toBe(bare);
  });

  it("leaves the separator behind, because parseIsbn is what removes it", () => {
    /*
     * The rule takes letters and nothing else, so every row above keeps its
     * separator. Adding a class for it would be dead code: `normalise` drops
     * anything not alphanumeric, and a reader who saw such a class would take
     * it for the thing that makes `isbn_` work.
     */
    expect(stripIsbnPrefix("urn:isbn:9780441013593")).toBe(":9780441013593");
    expect(parseIsbn(stripIsbnPrefix("urn:isbn:9780441013593"))).toBe(DUNE_13);
  });

  it("leaves a value carrying no label exactly as it found it", () => {
    expect(stripIsbnPrefix(DUNE_13)).toBe(DUNE_13);
    expect(stripIsbnPrefix("B0012345AB")).toBe("B0012345AB");
    expect(stripIsbnPrefix("")).toBe("");
  });

  it("strips only from the front, which no reader tested before", () => {
    /*
     * The arm that fails if the `^` comes off. Three readers carried this rule
     * with the anchor untested: removing it left 57, 59 and 85 arms green in
     * `appleBooks.ts`, `opf.ts` and `calibre.ts`, because every case they had
     * put the label at the front. Unanchored, the value below strips from the
     * middle and `parseIsbn` is handed a number the file never wrote.
     */
    const embedded = `${DUNE_13}isbn${DUNE_10}`;

    expect(stripIsbnPrefix(embedded)).toBe(embedded);
    expect(parseIsbn(stripIsbnPrefix(embedded))).toBeNull();
  });

  it("hands parseIsbn something it can read, which is the point of it", () => {
    /*
     * Without the strip, `urn:isbn:` normalises to a twenty character string
     * and is refused. Measured: of the 4 ISBNs `opf.ts` found over 79 real
     * EPUBs, 2 are written this way.
     */
    expect(parseIsbn("urn:isbn:9780441013593")).toBeNull();
    expect(parseIsbn(stripIsbnPrefix("urn:isbn:9780441013593"))).toBe(DUNE_13);
  });
});
