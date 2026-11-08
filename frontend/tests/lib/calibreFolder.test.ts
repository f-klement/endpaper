/**
 * @vitest-environment jsdom
 *
 * jsdom for `opf.test.ts`'s reason: the property hands the package document
 * reader drawn documents, and happy-dom misreads one whose XML declaration is
 * single quoted.
 */
/** Tests for src/lib/calibreFolder.ts: a Calibre library as a picked folder. */

import { describe, expect, it } from "vitest";

import {
  crossCheck,
  MAX_OPF_BYTES,
  type CalibreBook,
} from "../../src/lib/calibre";
import * as calibreFolder from "../../src/lib/calibreFolder";
import { crossCheckFolder, filesOfEachBook } from "../../src/lib/calibreFolder";
import { readOpf } from "../../src/lib/opf";
import { holds, PROFILE, PROPERTY, witness } from "../property";
import { expectAnswer, overrunBreach, type ValueDoor } from "./readerContract";
import {
  declares,
  OPF,
  render,
  xmlDocument,
  type XmlDocument,
} from "./xmlArbitrary";

function picked(path: string, content = "the bytes"): File {
  const file = new File([content], path.split("/").pop()!);
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

/**
 * A package document filling DUNE's empty publisher, padded to exactly
 * `bytes` by a trailing comment. ASCII throughout, so its length is its size.
 */
function packageOf(bytes: number): File {
  const head =
    '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><metadata><dc:title>Dune</dc:title><dc:publisher>Ace</dc:publisher></metadata></package><!--';
  const tail = "-->";
  return picked(
    "Calibre/Frank Herbert/Dune (1)/metadata.opf",
    head + "x".repeat(bytes - head.length - tail.length) + tail,
  );
}

describe("a metadata.opf at the size the walk reads", () => {
  it("is read when it is exactly that size", async () => {
    const checked = await crossCheckFolder([DUNE], [packageOf(MAX_OPF_BYTES)]);

    expect(checked.crossChecked).toBe(1);
    expect(checked.books[0]?.publisher).toBe("Ace");
  });

  it("is left unread one byte past it", async () => {
    expect(
      await crossCheckFolder([DUNE], [packageOf(MAX_OPF_BYTES + 1)]),
    ).toEqual({ books: [DUNE], crossChecked: 0, filled: 0, disagreed: 0 });
  });
});

/**
 * `crossCheckFolder` as a door: the `metadata.opf` beside a book, any text at
 * all, in; the book as the database and that file together say, out. Drawn
 * past the size the walk reads too, so the bound is reached as well as the
 * parse.
 */
const folderDoor: ValueDoor<XmlDocument, calibreFolder.FolderCrossCheck> = {
  module: calibreFolder,
  ceilings: () => ({ refusesEntities: true }),
  open: (document) =>
    crossCheckFolder(
      [DUNE],
      [picked("Calibre/Frank Herbert/Dune (1)/metadata.opf", render(document))],
    ),
};

describe("any metadata.opf beside a book in a picked folder", () => {
  it(
    "leaves the book as the database said unless it is a package document it reads",
    PROPERTY,
    async () => {
      expect(
        await holds(
          xmlDocument(OPF, [MAX_OPF_BYTES]),
          async (document) => {
            const { outcome } = await expectAnswer(folderDoor, document);
            const text = render(document);
            const size = new Blob([text]).size;
            const read = size > MAX_OPF_BYTES ? null : readOpf(text);
            const expected = read === null ? null : crossCheck(DUNE, read);
            expect(outcome).toEqual({
              answered: {
                books: [expected?.book ?? DUNE],
                crossChecked: expected === null ? 0 : 1,
                filled: expected?.filled ?? 0,
                disagreed: expected?.disagreed ?? 0,
              },
            });
            return { checked: expected !== null, size };
          },
          {
            "is a book checked against the file beside it": (_, { checked }) =>
              checked,
            "is a file past the size the walk reads": (_, { size }) =>
              size > MAX_OPF_BYTES,
          },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("draws a document that declares an entity", async () => {
    await witness(xmlDocument(OPF, [MAX_OPF_BYTES]), {
      "declares an entity": declares,
    });
  });

  it("declares the parse ceiling it is held to, so deleting it reds", async () => {
    expect(
      await overrunBreach(folderDoor, { ceiling: "refusesEntities" }),
    ).toContain("declaring an entity");
  });
});
