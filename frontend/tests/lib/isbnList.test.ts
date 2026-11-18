/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom.
 */
/** Tests for src/lib/isbnList.ts. */

import { describe, expect, it } from "vitest";

import { readIsbnList } from "../../src/lib/isbnList";

const DUNE_13 = "9780441013593";
const DUNE_10 = "0441013597";
const OTHER_13 = "9780306406157";

describe("readIsbnList", () => {
  it("reads one ISBN a line, canonical and in the order written", () => {
    expect(readIsbnList(`${OTHER_13}\n${DUNE_13}\n`).isbns).toEqual([
      OTHER_13,
      DUNE_13,
    ]);
  });

  it.each([
    ["commas", `${DUNE_13},${OTHER_13}`],
    ["semicolons", `${DUNE_13};${OTHER_13}`],
    ["tabs and spaces", `${DUNE_13}\t ${OTHER_13}`],
    ["quoted CSV cells", `"${DUNE_13}","${OTHER_13}"`],
    ["Windows line breaks", `${DUNE_13}\r\n${OTHER_13}`],
  ])("separates on %s", (_name, text) => {
    expect(readIsbnList(text).isbns).toEqual([DUNE_13, OTHER_13]);
  });

  it("keeps the hyphens a publisher prints inside one ISBN", () => {
    expect(readIsbnList("978-0-441-01359-3").isbns).toEqual([DUNE_13]);
  });

  it("reads an ISBN-10 as its ISBN-13", () => {
    expect(readIsbnList(DUNE_10).isbns).toEqual([DUNE_13]);
  });

  it("queues an ISBN written twice, by either spelling, once and counts the repeat", () => {
    const list = readIsbnList(`${DUNE_13} ${DUNE_10} ${DUNE_13}`);
    expect([list.isbns, list.repeated]).toEqual([[DUNE_13], 2]);
  });

  it("reports an ISBN whose check digit fails as written, and does not queue it", () => {
    const list = readIsbnList(`978-0-441-01359-4 ${DUNE_13}`);
    expect([list.isbns, list.invalid]).toEqual([
      [DUNE_13],
      ["978-0-441-01359-4"],
    ]);
  });

  it("reports thirteen digits outside the Bookland prefixes as invalid", () => {
    expect(readIsbnList("4006381333931").invalid).toEqual(["4006381333931"]);
  });

  it("reports one typo written twice once", () => {
    expect(readIsbnList("9780441013594 9780441013594").invalid).toEqual([
      "9780441013594",
    ]);
  });

  it("counts a token not shaped like an ISBN as ignored rather than invalid", () => {
    const list = readIsbnList(`ISBN\n${DUNE_13}\nDune 1965`);
    expect([list.isbns, list.invalid, list.ignored]).toEqual([
      [DUNE_13],
      [],
      3,
    ]);
  });

  it("reads an ISBN behind the label copied text puts on it", () => {
    const list = readIsbnList(
      `ISBN:${DUNE_13} isbn-10:${DUNE_10} ISBN13${OTHER_13}`,
    );
    expect([list.isbns, list.repeated, list.ignored]).toEqual([
      [DUNE_13, OTHER_13],
      1,
      0,
    ]);
  });

  it("names a labelled ISBN whose check digit fails as written", () => {
    expect(readIsbnList("ISBN:9780441013594").invalid).toEqual([
      "ISBN:9780441013594",
    ]);
  });

  it("reads an empty text as nothing at all", () => {
    expect(readIsbnList("  \n ")).toEqual({
      isbns: [],
      invalid: [],
      repeated: 0,
      ignored: 0,
    });
  });
});
