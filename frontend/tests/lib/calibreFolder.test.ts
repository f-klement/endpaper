/** Tests for src/lib/calibreFolder.ts: a Calibre library as a picked folder. */

import { describe, expect, it } from "vitest";

import type { CalibreBook } from "../../src/lib/calibre";
import { filesOfEachBook } from "../../src/lib/calibreFolder";

function picked(path: string): File {
  const file = new File(["the bytes"], path.split("/").pop()!);
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  return file;
}

const DUNE: CalibreBook = {
  id: 1,
  path: "Frank Herbert/Dune (1)",
  uuid: null,
  title: "Dune",
  authors: ["Frank Herbert"],
  authorsSeparated: true,
  identifiers: [],
  isbn: null,
  publisher: null,
  year: null,
  language: null,
  description: null,
  seriesName: null,
  seriesIndex: null,
  files: [
    { format: "EPUB", name: "Dune" },
    { format: "PDF", name: "Dune" },
  ],
};

describe("each book's own files in a pick", () => {
  it("are found where Calibre puts them, and nothing else in the folder is", () => {
    const epub = picked("Calibre/Frank Herbert/Dune (1)/Dune.epub");
    const pdf = picked("Calibre/Frank Herbert/Dune (1)/Dune.pdf");

    const found = filesOfEachBook(
      [DUNE],
      [
        picked("Calibre/metadata.db"),
        picked("Calibre/Frank Herbert/Dune (1)/cover.jpg"),
        picked("Calibre/Frank Herbert/Dune (1)/metadata.opf"),
        // The same name in another book's directory is that book's file.
        picked("Calibre/Somebody/Other (2)/Dune.epub"),
        pdf,
        epub,
      ],
    );

    expect(found).toEqual(new Map([[1, [epub, pdf]]]));
  });

  it("leave out a book whose files the pick does not hold", () => {
    expect(filesOfEachBook([DUNE], [picked("Calibre/metadata.db")]).size).toBe(
      0,
    );
  });
});
