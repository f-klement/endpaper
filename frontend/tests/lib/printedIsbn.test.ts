/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom.
 */
/** Tests for src/lib/printedIsbn.ts. */

import { describe, expect, it } from "vitest";

import { readPrintedIsbns } from "../../src/lib/printedIsbn";

const EXAMPLE_13 = "9783161484100";
const DUNE_13 = "9780441013593";

describe("readPrintedIsbns", () => {
  it("reads the hyphenated ISBN of a copyright page", () => {
    expect(readPrintedIsbns("ISBN 978-3-16-148410-0").isbns).toEqual([
      EXAMPLE_13,
    ]);
  });

  it("joins the space separated groups printed under a barcode", () => {
    expect(readPrintedIsbns("9 783161 484100").isbns).toEqual([EXAMPLE_13]);
  });

  it("reads a barcode's digits with the price add-on printed after them", () => {
    // As the engine returned it for `9 783161 484100  51299`, measured: the
    // first space lost, the add-on kept apart.
    expect(readPrintedIsbns("9783161 484100 51299").isbns).toEqual([
      EXAMPLE_13,
    ]);
  });

  it.each([
    ["no space after the label", "ISBN978-3-16-148410-0"],
    ["an ISBN-13 label with a colon", "ISBN-13:978-3-16-148410-0"],
    ["a full stop after it", "ISBN 978-3-16-148410-0."],
  ])("cuts off %s", (_name, text) => {
    expect(readPrintedIsbns(text).isbns).toEqual([EXAMPLE_13]);
  });

  it("reads an ISBN-10 ending in X as its ISBN-13", () => {
    expect(readPrintedIsbns("ISBN 0-8044-2957-x").isbns).toEqual([
      "9780804429573",
    ]);
  });

  it("finds the ISBN among the other lines of a copyright page", () => {
    const page = [
      "First published 1965",
      "Printed in 2019",
      "ISBN 978-0-441-01359-3",
      "10 9 8 7 6 5 4 3 2 1",
    ].join("\n");
    expect(readPrintedIsbns(page)).toEqual({ isbns: [DUNE_13], misread: [] });
  });

  it("reads each ISBN of a page once, by either spelling, in reading order", () => {
    const page = "ISBN 978-3-16-148410-0\nISBN 0-441-01359-7\n9 783161 484100";
    expect(readPrintedIsbns(page).isbns).toEqual([EXAMPLE_13, DUNE_13]);
  });

  it("reports a read whose check digit fails as read, and not as an ISBN", () => {
    expect(readPrintedIsbns("ISBN 978-3-16-148410-1")).toEqual({
      isbns: [],
      misread: ["978-3-16-148410-1"],
    });
  });

  it("does not cut a misread EAN into an ISBN-10 its first digits happen to spell", () => {
    // 0441013597 passes the ISBN-10 check. Printed as the first ten digits of
    // a longer group, it is part of something else and must not be offered.
    expect(readPrintedIsbns("0441013597123")).toEqual({
      isbns: [],
      misread: ["0441013597123"],
    });
  });

  it("reads a printer's key as nothing, not as a misread", () => {
    expect(readPrintedIsbns("10 9 8 7 6 5 4 3 2 1")).toEqual({
      isbns: [],
      misread: [],
    });
  });

  it("finds nothing in text with no ISBN shaped number", () => {
    expect(readPrintedIsbns("Printed in Germany\n12,99 EUR\n2019")).toEqual({
      isbns: [],
      misread: [],
    });
  });

  it("reports twelve digits, a dropped digit, as nothing rather than a misread", () => {
    expect(readPrintedIsbns("978-3-16-14841-0")).toEqual({
      isbns: [],
      misread: [],
    });
  });
});
