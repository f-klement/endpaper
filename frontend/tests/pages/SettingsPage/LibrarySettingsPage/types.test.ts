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

import {
  BookFormat,
  BookIdentifierScheme,
} from "../../../../src/api/generated/model";
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

/**
 * How many the endpoint will take in one request, read back the same way.
 *
 * A payload over this is a 422 for the whole book rather than for the extra
 * entry, so it is the fourth rule `boundIdentifiers` has to keep.
 */
const IDENTIFIER_LIMIT = (
  SCHEMA.components.schemas.BookCreate.properties as {
    identifiers: { maxItems: number };
  }
).identifiers.maxItems;

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

  it("carries what the library's own identifiers table named", () => {
    // The two schemes this app has, out of a row set holding a type for each
    // and two it declines. Which type is which scheme is the reader's rule and
    // is tested against a real database in `tests/lib/calibre.test.ts`; what is
    // tested here is that the builder sends the answer at all.
    expect(
      toBookCreate(
        book({
          identifiers: [
            { type: "isbn", value: "9780441013593" },
            { type: "amazon_de", value: "B000R34YKC" },
            { type: "google", value: "s7NIrgEACAAJ" },
            { type: "goodreads", value: "234225" },
          ],
        }),
      )!.identifiers,
    ).toEqual([
      { scheme: BookIdentifierScheme.asin, value: "B000R34YKC" },
      { scheme: BookIdentifierScheme.google_books, value: "s7NIrgEACAAJ" },
    ]);
  });

  it("sends no identifier for a library that named none", () => {
    expect(toBookCreate(book())!.identifiers).toEqual([]);
  });

  it("folds the marketplaces a library spelled one ASIN under", () => {
    // **What the fold buys is the row that is not an ASIN.** Eight entries is
    // all one request may carry and the ceiling truncates, so a library filing
    // one ASIN under enough marketplaces spends every slot on one fact. The arm
    // asserts the volume id still arrives, which is what truncation was taking.
    const marketplaces = [
      "amazon",
      "amazon_com",
      "amazon_de",
      "amazon_uk",
      "amazon_fr",
      "amazon_it",
      "amazon_es",
      "amazon_jp",
      "amazon_ca",
    ].map((type) => ({ type, value: "B000R34YKC" }));

    expect(
      toBookCreate(
        book({
          identifiers: [
            ...marketplaces,
            // Lower cased by whoever typed it, which is one identifier and not
            // a second: Amazon issues a token with no lower case in it, so the
            // canonical form recovers the issued value rather than inventing
            // one.
            { type: "amazon_pl", value: "b000r34ykc" },
            { type: "google", value: "s7NIrgEACAAJ" },
          ],
        }),
      )!.identifiers,
    ).toEqual([
      { scheme: BookIdentifierScheme.asin, value: "B000R34YKC" },
      { scheme: BookIdentifierScheme.google_books, value: "s7NIrgEACAAJ" },
    ]);
  });

  it("bounds a Calibre book's identifiers by what one request may carry", () => {
    // **The one bound of the four that binds on this path**, and the reason
    // this builder goes through `boundIdentifiers` at all: the reader answers
    // one entry a matching row and is unbounded in entries, where `BookCreate`
    // declares `maxItems`, so a payload over it is a 422 for the whole book.
    // Distinct values, because identical ones are folded by the reader.
    const many = Array.from({ length: IDENTIFIER_LIMIT + 3 }, (_, index) => ({
      type: "amazon",
      value: `B${String(index).padStart(9, "0")}`,
    }));

    expect(toBookCreate(book({ identifiers: many }))!.identifiers).toHaveLength(
      IDENTIFIER_LIMIT,
    );
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
    identifiers: [],
    publisher: "Chilton Books",
    year: 1965,
    language: "en",
    description: null,
    seriesName: "Dune Chronicles",
    seriesIndex: 1,
    format: "ebook",
    // **Stated rather than left to the cast**: a store with nothing per row to
    // say is the common case and it is what the fallback arms below exercise.
    ownership: null,
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
      Object.keys(storeToBookCreate(storeBook(), true)!).filter(
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
      const created = storeToBookCreate(storeBook({ format: kind }), true);
      expect(known).toContain(created!.format);
    }
  });

  it("carries what the store said about the kind of copy", () => {
    // Carried rather than derived: `lib/stores.ts` is where each store answers
    // that, because the answer is the store's. A Kobo says it in a mime type
    // and a Takeout says it by the file having read as an EPUB.
    expect(
      storeToBookCreate(storeBook({ format: null }), true)!.format,
    ).toBeNull();
    expect(storeToBookCreate(storeBook(), true)!.format).toBe("ebook");
  });

  it("joins authors with the separator the server splits on", () => {
    expect(
      storeToBookCreate(
        storeBook({ authors: ["Terry Pratchett", "Neil Gaiman"] }),
        true,
      )!.author,
    ).toBe("Terry Pratchett, Neil Gaiman");
  });

  it("is null for a book with no title, which the endpoint requires", () => {
    // Reported in the preview rather than left to a 422 halfway through a
    // device: a Kobo row can carry a null `Title` and still be owned.
    expect(storeToBookCreate(storeBook({ title: null }), true)).toBeNull();
  });

  it("cuts a title the column cannot hold rather than losing the book", () => {
    const long = "a".repeat(600);

    expect(
      storeToBookCreate(storeBook({ title: long }), true)!.title,
    ).toHaveLength(500);
  });

  it("says nothing about a shelf or a private book, because no store does", () => {
    expect(storeToBookCreate(storeBook(), true)).toMatchObject({
      location: null,
      is_private: false,
      classifications: [],
    });
  });

  it("carries the store's own name for the book, which used to be dropped", () => {
    // The whole of the ticket: an ASIN and a Google volume id both survived the
    // read and not the import, because `BookCreate` had one identifier field
    // and it was `isbn`.
    expect(
      storeToBookCreate(
        storeBook({ identifiers: [{ scheme: "asin", value: "B00J4YQKHY" }] }),
        true,
      )!.identifiers,
    ).toEqual([{ scheme: "asin", value: "B00J4YQKHY" }]);
  });

  it("says the member owns it where the store established that", () => {
    expect(storeToBookCreate(storeBook(), true)!.ownership).toBe("owned");
  });

  it("says ownership is unknown where the store could not establish it", () => {
    // **Not an omission, because omitting it is what already happened and the
    // server's default is `owned`.** An Adobe Digital Editions catalogue records
    // a three week library loan and a purchase identically, so a reader that
    // sent nothing told a member they own a book they have until it expires.
    expect(storeToBookCreate(storeBook(), false)!.ownership).toBe("unknown");
  });

  it("takes the row's own answer over the library's", () => {
    // **This arm replaced one asserting the opposite**, which was true when the
    // flag was the only input and became false the moment a reader could answer
    // per row. `kobo.ts` reads `Accessibility` and knows a Kobo Plus title from
    // a purchase, so a library wide `true` overwriting that would put a guess
    // where a measurement was.
    expect(
      storeToBookCreate(storeBook({ ownership: "unknown" }), true)!.ownership,
    ).toBe("unknown");
    expect(
      storeToBookCreate(storeBook({ ownership: "owned" }), false)!.ownership,
    ).toBe("owned");
  });

  it("falls back to the library where the row says nothing", () => {
    // The other half, and the half Adobe Digital Editions relies on: that
    // reader answers `null` per row because its catalogue records a three week
    // loan and a purchase identically, so the library's answer is all there is.
    expect(
      storeToBookCreate(storeBook({ ownership: null }), false)!.ownership,
    ).toBe("unknown");
    expect(
      storeToBookCreate(storeBook({ ownership: null }), true)!.ownership,
    ).toBe("owned");
  });

  it("decides ownership on those two inputs and nothing else in the book", () => {
    // Asserted against a book carrying an identifier, a title and a format,
    // because a later reader looking for something else to key this on is the
    // way it acquires a third input.
    const rich = storeBook({
      title: "Small Gods",
      format: "ebook",
      identifiers: [{ scheme: "asin", value: "B00J4YQKHY" }],
      ownership: null,
    });

    expect(storeToBookCreate(rich, false)!.ownership).toBe("unknown");
  });

  it("never puts one in the field the ISBN lookup reads", () => {
    // The refusal this ticket is, asserted rather than described: `books.isbn`
    // check digits its input, so an ASIN there matches nothing and takes the
    // deduplication down with it for the rows that do carry one.
    const created = storeToBookCreate(
      storeBook({
        isbn: null,
        identifiers: [{ scheme: "asin", value: "B00J4YQKHY" }],
      }),
      true,
    );

    expect(created!.isbn).toBeNull();
    expect(created!.identifiers).toHaveLength(1);
  });
});
