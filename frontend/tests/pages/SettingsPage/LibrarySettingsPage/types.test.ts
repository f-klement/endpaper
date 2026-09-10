/**
 * @vitest-environment node
 *
 * Touches no DOM. Building one costs more than this file spends running.
 */
/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/types.ts.
 *
 * What a record read off somebody's own library becomes on the wire, checked
 * against the committed `openapi.json` rather than against a copy of it kept
 * here: a bound that agrees with a constant somebody typed is a bound that
 * agrees with nothing.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { BookFormat } from "../../../../src/api/generated/model";
import type { CalibreBook } from "../../../../src/lib/calibre";
import type { StoreBook } from "../../../../src/lib/stores";
import {
  formatOf,
  storeToBookCreate,
  toBookCreate,
} from "../../../../src/pages/SettingsPage/LibrarySettingsPage/types";

const SCHEMA = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../../openapi.json", import.meta.url)),
    "utf-8",
  ),
) as {
  components: {
    schemas: {
      BookCreate: {
        properties: Record<string, unknown>;
        required?: string[];
      };
    };
  };
};

function book(overrides: Partial<CalibreBook> = {}): CalibreBook {
  return {
    id: 1,
    path: "Herbert, Frank/Dune (1)",
    title: "Dune",
    authors: ["Frank Herbert"],
    identifiers: [],
    isbn: "9780441013593",
    publisher: "Chilton Books",
    year: 1965,
    language: "eng",
    description: "A desert planet.",
    seriesName: "Dune Chronicles",
    seriesIndex: 1,
    formats: ["EPUB"],
    ...overrides,
  };
}

describe("one Calibre record as a request", () => {
  it("sends nothing the endpoint does not take", () => {
    // The failure this catches is a field renamed on the schema and left here,
    // which passes the type check while the server ignores it.
    const allowed = new Set(
      Object.keys(SCHEMA.components.schemas.BookCreate.properties),
    );

    expect(
      Object.keys(toBookCreate(book())!).filter((k) => !allowed.has(k)),
    ).toEqual([]);
  });

  it("carries the identifier, the series and the position in it", () => {
    // The three things the ticket's own "done when" names, and the three the
    // network route measured as carrying none of.
    expect(toBookCreate(book())).toMatchObject({
      isbn: "9780441013593",
      series_name: "Dune Chronicles",
      series_index: 1,
    });
  });

  it("joins authors with the separator the server splits on", () => {
    expect(
      toBookCreate(book({ authors: ["Terry Pratchett", "Neil Gaiman"] }))!
        .author,
    ).toBe("Terry Pratchett, Neil Gaiman");
  });

  it("is null for a book with no title, which the endpoint requires", () => {
    // Calibre writes `Unknown` where nobody said, and `lib/calibre.ts` refuses
    // that by name. What is left has nothing to file it under, and reporting it
    // here is what stops a 422 halfway through nine hundred books.
    expect(SCHEMA.components.schemas.BookCreate.required).toContain("title");
    expect(toBookCreate(book({ title: null }))).toBeNull();
  });

  it("cuts a title the column cannot hold rather than losing the book", () => {
    const long = "a".repeat(600);

    expect(toBookCreate(book({ title: long }))!.title).toHaveLength(500);
  });

  it("drops a value that cannot be cut and still sends the book", () => {
    // A cut ISBN fails its own check digit and names no book at all, so it is
    // dropped where a title is cut. `lib/bookBounds.ts` carries the split.
    const created = toBookCreate(book({ isbn: "9".repeat(40) }));

    expect(created!.isbn).toBeNull();
    expect(created!.title).toBe("Dune");
  });

  it("says nothing about a shelf or a private book, because Calibre does not", () => {
    expect(toBookCreate(book())).toMatchObject({
      location: null,
      is_private: false,
      classifications: [],
    });
  });
});

describe("what kind of object the copy is", () => {
  it("is an ebook when the library holds a file for it", () => {
    expect(formatOf(book({ formats: ["EPUB", "PDF"] }))).toBe("ebook");
  });

  it("is an audiobook when every file it holds is a recording", () => {
    expect(formatOf(book({ formats: ["M4B"] }))).toBe("audiobook");
  });

  it("is an ebook when the library holds both", () => {
    // A book with a readable file is a book to read. Calling the pair an
    // audiobook because one of the two is would be the wrong half.
    expect(formatOf(book({ formats: ["EPUB", "M4B"] }))).toBe("ebook");
  });

  it("is a comic when every file it holds is a comic archive", () => {
    // The same file picked on the scan page is a comic, and one question with
    // two answers is what this stops. `lib/fileName.FORMAT_FOR_EXTENSION` is
    // the other half.
    expect(formatOf(book({ formats: ["CBZ"] }))).toBe("comic");
  });

  it("calls a CBR a comic although nothing here will parse one", () => {
    // This answers what the copy is, not what can be read. The refusal in
    // `lib/cbz.ts` is a refusal of a parser rather than of the format.
    expect(formatOf(book({ formats: ["CBR"] }))).toBe("comic");
  });

  it("is an ebook when the library holds a readable file and a comic", () => {
    // The same rule the audio pair follows: a record with a readable file is a
    // book to read, and one comic file among several does not rename it.
    expect(formatOf(book({ formats: ["EPUB", "CBZ"] }))).toBe("ebook");
  });

  it("says nothing for a record with no file at all", () => {
    // Not an ebook. A Calibre record with no file is a book somebody
    // catalogued, and answering `ebook` asserts something the library does not.
    expect(formatOf(book({ formats: [] }))).toBeNull();
  });
});

function storeBook(overrides: Partial<StoreBook> = {}): StoreBook {
  return {
    key: "a1b2c3d4",
    title: "Dune",
    authors: ["Frank Herbert"],
    isbn: "9780441013593",
    publisher: "Chilton Books",
    year: 1965,
    language: "en",
    description: null,
    seriesName: "Dune Chronicles",
    seriesIndex: 1,
    format: "ebook",
    ...overrides,
  } as StoreBook;
}

describe("one store record as a request", () => {
  it("sends nothing the endpoint does not take", () => {
    // The same failure the Calibre arm catches, and it has to be asked twice:
    // a field renamed on the schema passes the type check on both builders and
    // is ignored by the server on both.
    const allowed = new Set(
      Object.keys(SCHEMA.components.schemas.BookCreate.properties),
    );

    expect(
      Object.keys(storeToBookCreate(storeBook())!).filter(
        (k) => !allowed.has(k),
      ),
    ).toEqual([]);
  });

  it("spells every kind a store can answer the way the endpoint does", () => {
    // The mapping is a total `Record`, so a kind added to `StoreFormat` with no
    // home there is a compile error. What the type cannot see is a value that
    // compiles and is not one the endpoint's own enum holds, which is a 422 in
    // the middle of somebody's device.
    const known = new Set(Object.values(BookFormat) as string[]);
    for (const kind of ["ebook", "audiobook", "comic"] as const) {
      const created = storeToBookCreate(storeBook({ format: kind }));
      expect(known).toContain(created!.format);
    }
  });

  it("carries what the store said about the kind of copy", () => {
    // Carried rather than derived: `lib/stores.ts` is where each store answers
    // that, because the answer is the store's. A Kobo says it in a mime type
    // and a Takeout says it by the file having read as an EPUB.
    expect(storeToBookCreate(storeBook({ format: null }))!.format).toBeNull();
    expect(storeToBookCreate(storeBook())!.format).toBe("ebook");
  });

  it("joins authors with the separator the server splits on", () => {
    expect(
      storeToBookCreate(
        storeBook({ authors: ["Terry Pratchett", "Neil Gaiman"] }),
      )!.author,
    ).toBe("Terry Pratchett, Neil Gaiman");
  });

  it("is null for a book with no title, which the endpoint requires", () => {
    // Reported in the preview rather than left to a 422 halfway through a
    // device: a Kobo row can carry a null `Title` and still be owned.
    expect(storeToBookCreate(storeBook({ title: null }))).toBeNull();
  });

  it("cuts a title the column cannot hold rather than losing the book", () => {
    const long = "a".repeat(600);

    expect(storeToBookCreate(storeBook({ title: long }))!.title).toHaveLength(
      500,
    );
  });

  it("says nothing about a shelf or a private book, because no store does", () => {
    expect(storeToBookCreate(storeBook())).toMatchObject({
      location: null,
      is_private: false,
      classifications: [],
    });
  });
});
