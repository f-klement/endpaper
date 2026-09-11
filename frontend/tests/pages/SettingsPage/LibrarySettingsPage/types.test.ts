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
import type {
  StoreBook,
  StoreIdentifierScheme,
} from "../../../../src/lib/stores";
import {
  formatOf,
  storeIdentifiers,
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
      BookIdentifierIn: {
        properties: { value: { maxLength: number } };
      };
    };
  };
};

/** What the endpoint says an identifier may be, read back rather than typed. */
const IDENTIFIER_CEILING =
  SCHEMA.components.schemas.BookIdentifierIn.properties.value.maxLength;

/**
 * How many the endpoint will take in one request, read back the same way.
 *
 * A payload over this is a 422 for the whole book rather than for the extra
 * entry, so it is the fourth rule `storeIdentifiers` has to keep.
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

  it("decides ownership on the flag alone, not on anything in the book", () => {
    // The flag is a fact about the read and every book in one read shares it.
    // Asserted against a book carrying an identifier, a title and a format,
    // because a later reader looking for something to key this on is the way
    // it acquires a second input.
    const rich = storeBook({
      title: "Small Gods",
      format: "ebook",
      identifiers: [{ scheme: "asin", value: "B00J4YQKHY" }],
    });

    expect(storeToBookCreate(rich, false)!.ownership).toBe("unknown");
    expect(storeToBookCreate(storeBook({ title: "x" }), true)!.ownership).toBe(
      "owned",
    );
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

describe("the identifiers a store gave, bounded for the wire", () => {
  it("spells every scheme a store can answer the way the endpoint does", () => {
    // The mapping is a total `Record`, the format mapping's rule. What the type
    // cannot see is a value that compiles and is not one the endpoint's own
    // enum holds, which is a 422 in the middle of somebody's device.
    const known = new Set(Object.values(BookIdentifierScheme) as string[]);
    const schemes: StoreIdentifierScheme[] = ["asin", "google_books"];
    for (const scheme of schemes) {
      expect(known).toContain(
        storeIdentifiers([{ scheme, value: "x" }])[0]!.scheme,
      );
    }
  });

  it("trims a reader's own padding off a value", () => {
    // A store's XML indents its elements, and the unique index is on the exact
    // characters, so padding would earn a second row for one identifier.
    expect(
      storeIdentifiers([{ scheme: "asin", value: "\n  B00J4YQKHY\n" }]),
    ).toEqual([{ scheme: "asin", value: "B00J4YQKHY" }]);
  });

  it("drops a value the column cannot hold rather than losing the book", () => {
    // `lib/bookBounds.ts`' rule applied to a field it does not cover: an import
    // of nine hundred books must not turn into a 422 over one odd row.
    expect(
      storeIdentifiers([
        { scheme: "asin", value: "B".repeat(IDENTIFIER_CEILING + 1) },
        { scheme: "asin", value: "B00J4YQKHY" },
      ]),
    ).toEqual([{ scheme: "asin", value: "B00J4YQKHY" }]);
  });

  it("keeps a value spending the whole budget", () => {
    // The other side, without which the drop above is satisfied by a rule that
    // drops everything. Exactly on the boundary the schema declares.
    expect(
      storeIdentifiers([
        { scheme: "asin", value: "B".repeat(IDENTIFIER_CEILING) },
      ]),
    ).toHaveLength(1);
  });

  it("measures the budget in code points, never in UTF-16 units", () => {
    // A ceiling belongs to a Python `str` and to a SQLite column, both of which
    // count code points, so measuring in units refuses half of what the server
    // would take. `lib/bookBounds.ts` records the same fault costing a 422.
    expect(
      storeIdentifiers([
        { scheme: "asin", value: "\u{1f4d6}".repeat(IDENTIFIER_CEILING) },
      ]),
    ).toHaveLength(1);
  });

  // **One arm per case `tests/schemas/test_identifier.py` names**, because this
  // filter and that validator have to be the same rule: a character this keeps
  // and the server refuses is a 422 for the whole book, which `writeBooks`
  // files under `failures`. Five of these nine passed the `/\s/u` filter this
  // replaced, measured by both critic seats over every non surrogate code point.
  it.each([
    ["a space in the middle", "B00J4 YQKHY"],
    ["a tab", "B00J4\tYQKHY"],
    ["a no-break space, Zs", "B00J4\u00a0YQKHY"],
    ["a zero width space, Cf", "B00J4\u200bYQKHY"],
    ["a soft hyphen, Cf", "B00J4\u00adYQKHY"],
    ["a byte order mark, Cf", "B00J4\ufeffYQKHY"],
    ["a C1 control, Cc", "B00J4\u0085YQKHY"],
    ["a NUL, which is Cc", "B00J4\u0000YQKHY"],
    ["a left-to-right mark, Cf", "B00J4\u200eYQKHY"],
  ])("drops a value carrying %s", (_name, value) => {
    expect(storeIdentifiers([{ scheme: "asin", value }])).toEqual([]);
  });

  it("keeps the two real shapes, which the same rule must not refuse", () => {
    // The other side, without which the nine arms above are satisfied by a
    // filter that drops everything. Both measured by their own readers: an
    // ASIN is ten characters and a Google volume id is twelve of the URL safe
    // alphabet, which includes the two characters a charset rule would have
    // been tempted to exclude.
    expect(
      storeIdentifiers([
        { scheme: "asin", value: "B00J4YQKHY" },
        { scheme: "google_books", value: "zy-CAlFP_gYC" },
      ]),
    ).toHaveLength(2);
  });

  it("sends no more than one request may carry", () => {
    // Over `maxItems` the endpoint answers 422 for the whole book, so a store
    // that grew a longer list would cost a member the book rather than the
    // extra entry. No store produces more than one today; this binds the case
    // where one does.
    const many = Array.from({ length: IDENTIFIER_LIMIT + 3 }, (_, index) => ({
      scheme: "asin" as const,
      value: `B${String(index).padStart(9, "0")}`,
    }));

    expect(storeIdentifiers(many)).toHaveLength(IDENTIFIER_LIMIT);
  });

  it("drops an empty value", () => {
    expect(storeIdentifiers([{ scheme: "asin", value: "   " }])).toEqual([]);
  });
});
