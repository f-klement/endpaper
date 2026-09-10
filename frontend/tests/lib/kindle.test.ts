/**
 * @vitest-environment jsdom
 *
 * **jsdom rather than the suite's happy-dom, and this is not a preference.**
 * `opf.ts`'s tests carry the same docblock for the same parser, and this file
 * re-measured it rather than inheriting it: 10 documents put through both
 * environments on 2026-09-10, 8 agreeing and 2 not, and the same two
 * disagreements over a wider set of 18 by a second instrument. happy-dom reads a
 * declaration spelled with single quotes as HTML, so a perfectly ordinary
 * catalogue comes back with a `documentElement` of `html` and reads as no
 * catalogue at all; and it recovers an unclosed element into a well formed
 * document, where a browser and jsdom both report `parsererror`. The first
 * would hide a real reader working, the second would hide a real one failing.
 * `a declaration written with single quotes` below is the arm that catches the
 * first coming back.
 */
/**
 * The Kindle desktop reader, against Kindle shaped documents built here.
 *
 * **Every document below is constructed, and none came off a machine.** There
 * is no Windows or Mac machine reachable from where this was written, so the
 * element vocabulary is taken from a published capture of a real
 * `KindleSyncMetadataCache.xml`, which `src/lib/kindle.ts` names with its blob,
 * its own recorded sync date and the app version that wrote it. That module is
 * the one home of those: a sha in two files is a sha that drifts in one of
 * them.
 *
 * **Nothing here is a copy of that capture.** It is one person's real library,
 * and their titles are not test data. What is quoted from it is the shape of an
 * entry and nothing that was in one.
 *
 * A fixture presented as a real machine's file when it is not would be worse
 * than no fixture, so this paragraph is the fixture's provenance and is meant to
 * be read before the assertions below are trusted.
 */

import { describe, expect, it, vi } from "vitest";

import {
  MAX_CACHE_BYTES,
  readKindleCacheFile,
  readKindleLibrary,
  type KindleBook,
  type KindleLibrary,
} from "../../src/lib/kindle";

// The module's own source, for the one rule below that recomputes a list rather
// than restating it. A `?raw` specifier is a different module id, so this is a
// string and not a second evaluation of the reader.
import readerSource from "../../src/lib/kindle.ts?raw";

/** One `<meta_data>`, with only the elements it is given. */
function entry(elements: string): string {
  return `<meta_data>${elements}</meta_data>`;
}

/**
 * A cache document holding whatever entries it is given.
 *
 * **No XML declaration**, because the capture carries none: it begins with a
 * newline and then `<response>`. A reader that needed one would read no real
 * file at all.
 */
function cache(...entries: string[]): string {
  return `
<response>
  <sync_time>2019-01-01T00:00:00+0000;softwareVersion:51068</sync_time>
  <cache_metadata>
    <version>1</version>
  </cache_metadata>
  <add_update_list>${entries.join("")}</add_update_list>
</response>`;
}

/**
 * One owned book carrying every element this reader knows.
 *
 * `content_type`, `textbook_type` and `purchase_date` are here and are read by
 * nothing, which is what proves the reader names its elements rather than
 * taking whatever an entry holds.
 */
const OWNED = entry(`
  <ASIN>B000000001</ASIN>
  <title pronunciation="">A Constructed Title</title>
  <authors>
    <author pronunciation="">Surname, Given</author>
  </authors>
  <publishers>
    <publisher>A Constructed Publisher</publisher>
  </publishers>
  <publication_date>1965-08-01T00:00:00+0000</publication_date>
  <purchase_date>2019-02-03T04:05:06+0000</purchase_date>
  <textbook_type></textbook_type>
  <cde_contenttype>EBOK</cde_contenttype>
  <content_type>application/x-mobipocket-ebook</content_type>
`);

/**
 * The `FIELDS` array as `kindle.ts` declares it, in the order it declares it.
 *
 * Read out of the source rather than restated, so the two rules below that turn
 * on it cannot agree with a declaration that has moved.
 */
function declaredFields(): string[] {
  const array = /const FIELDS: readonly KindleField\[\] = \[([^\]]+)\]/.exec(
    readerSource,
  );
  expect(array, "the FIELDS declaration moved").not.toBeNull();
  return [...array![1]!.matchAll(/"([^"]+)"/g)].map((match) => match[1]!);
}

/** The library, or a failure raised where the assertion can see it. */
function libraryOn(...entries: string[]): KindleLibrary {
  const read = readKindleLibrary(cache(...entries));
  if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
  return read.library;
}

function booksOn(...entries: string[]): readonly KindleBook[] {
  return libraryOn(...entries).books;
}

describe("reading a library", () => {
  it("gives back a book with every element the entry carries", () => {
    const [book] = booksOn(OWNED);

    expect(book).toEqual({
      asin: "B000000001",
      title: "A Constructed Title",
      authors: ["Surname, Given"],
      publisher: "A Constructed Publisher",
      year: 1965,
      personal: false,
    } satisfies KindleBook);
  });

  it("reports the document's own version", () => {
    expect(libraryOn(OWNED).schemaVersion).toBe(1);
  });

  it("keeps every author an entry names, in the document's order", () => {
    // The improvement over the Kobo reader, which has one string and cannot
    // express this. 8 of the capture's 279 entries name two and the widest
    // names nine.
    const [book] = booksOn(
      entry(`
        <ASIN>B000000002</ASIN>
        <authors>
          <author>Second, Written</author>
          <author>First, Written</author>
        </authors>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(book?.authors).toEqual(["Second, Written", "First, Written"]);
  });

  it("leaves a surname first name exactly as the file writes it", () => {
    // Never reordered and never split. The separator that would split a list is
    // also how one name is written, so a guess files one person as two.
    const [book] = booksOn(
      entry(`
        <ASIN>B000000003</ASIN>
        <authors><author>Surname, Given Middle</author></authors>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(book?.authors).toEqual(["Surname, Given Middle"]);
  });

  it("has no publisher where the list is there and empty", () => {
    // 29 of the capture's 279 entries are this, so it is the ordinary case
    // rather than a malformed one.
    const [book] = booksOn(
      entry(`
        <ASIN>B000000004</ASIN>
        <title>A Constructed Title</title>
        <publishers></publishers>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(book?.publisher).toBeNull();
  });

  it("takes one publisher from a list that carries two", () => {
    // This app's record of a book has one. The capture carries no entry with
    // two, so what this pins is the reader's answer rather than the format's.
    const [book] = booksOn(
      entry(`
        <ASIN>B000000005</ASIN>
        <publishers>
          <publisher>First Imprint</publisher>
          <publisher>Second Imprint</publisher>
        </publishers>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(book?.publisher).toBe("First Imprint");
  });

  it("reads an author only where the wrapper the format uses holds it", () => {
    // An `<author>` directly under the entry is not where this format puts one.
    // Reading it would be reading a document shape nothing attests.
    const [book] = booksOn(
      entry(`
        <ASIN>B000000006</ASIN>
        <author>Loose, Name</author>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(book?.authors).toEqual([]);
  });
});

describe("what the member owns", () => {
  /** The ASINs that came back, in the order the document listed them. */
  function keptOn(...entries: string[]): string[] {
    const read = readKindleLibrary(cache(...entries));
    // **Raised rather than answered as `[]`.** Every refusal case below asserts
    // an empty list, and a reader that failed outright would satisfy all of
    // them while filtering nothing.
    if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
    return read.library.books.map((book) => book.asin);
  }

  /** An entry at one content type. */
  function ofType(asin: string, kind: string): string {
    return entry(`
      <ASIN>${asin}</ASIN>
      <title>A Constructed Title</title>
      <cde_contenttype>${kind}</cde_contenttype>
    `);
  }

  it("keeps a book in the account's library", () => {
    expect(keptOn(ofType("B000000010", "EBOK"))).toEqual(["B000000010"]);
  });

  it("keeps a document the member sent to their own Kindle", () => {
    // The Kindle spelling of a sideloaded book, which `kobo.ts` keeps too.
    // Neither capture carries one, so `kindle.ts::OWNED` names where the
    // spelling comes from instead.
    const [book] = booksOn(ofType("B000000016", "PDOC"));

    expect(book).toMatchObject({ asin: "B000000016", personal: true });
  });

  it("refuses one issue of a magazine and one of a newspaper", () => {
    // Periodicals rather than books. Both spellings come from the same
    // vocabulary the two kept values do.
    expect(
      keptOn(ofType("B000000017", "MAGZ"), ofType("B000000018", "NWPR")),
    ).toEqual([]);
  });

  it("refuses a sample, which nobody bought", () => {
    // A sample's title is the book's title, so nothing else in the entry tells
    // the two apart. 9 of the capture's 279 entries are one.
    expect(keptOn(ofType("B000000011", "EBSP"))).toEqual([]);
  });

  it("refuses a content type it does not recognise", () => {
    // The direction is the decision: a value Amazon invents loses a real book
    // visibly, in `skipped`, rather than gaining one nobody bought invisibly.
    expect(keptOn(ofType("B000000012", "FROMTHEFUTURE"))).toEqual([]);
  });

  it("refuses an entry that says nothing about what it is", () => {
    expect(
      keptOn(
        entry(`<ASIN>B000000013</ASIN><title>A Constructed Title</title>`),
      ),
    ).toEqual([]);
  });

  it("refuses an entry with no identifier", () => {
    // The ASIN is the only identifier this format carries, so an entry without
    // one is a book nothing downstream could ever match.
    expect(
      keptOn(
        entry(`<title>A Constructed Title</title>
               <cde_contenttype>EBOK</cde_contenttype>`),
      ),
    ).toEqual([]);
  });

  it("refuses an entry whose identifier is only whitespace", () => {
    expect(
      keptOn(
        entry(`<ASIN>   </ASIN>
               <cde_contenttype>EBOK</cde_contenttype>`),
      ),
    ).toEqual([]);
  });

  it("counts what it refused, so a member can be told there was more", () => {
    const library = libraryOn(
      OWNED,
      ofType("B000000014", "EBSP"),
      ofType("B000000015", "FROMTHEFUTURE"),
    );

    expect(library).toMatchObject({ skipped: 2 });
    expect(library.books).toHaveLength(1);
  });
});

describe("the year an entry claims", () => {
  /** The year read off a publication date of this value. */
  function yearOf(published: string): number | null {
    const [book] = booksOn(
      entry(`
        <ASIN>B000000020</ASIN>
        <publication_date>${published}</publication_date>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );
    return book?.year ?? null;
  }

  it("reads the year out of the timestamp shape every entry uses", () => {
    // 279 of 279 in the capture are this shape, offset included.
    expect(yearOf("1965-08-01T00:00:00+0000")).toBe(1965);
  });

  it("keeps the years at each end of the plausible window", () => {
    expect(yearOf("1450-01-01T00:00:00+0000")).toBe(1450);
    expect(yearOf("2100-01-01T00:00:00+0000")).toBe(2100);
  });

  it("refuses the year immediately outside each end", () => {
    expect(yearOf("1449-01-01T00:00:00+0000")).toBeNull();
    expect(yearOf("2101-01-01T00:00:00+0000")).toBeNull();
  });

  it("refuses a date field carrying something that is not a date", () => {
    expect(yearOf("sometime")).toBeNull();
  });
});

describe("a document this reader does not have all of", () => {
  it("names the fields no entry could fill", () => {
    const library = libraryOn(
      entry(`
        <ASIN>B000000030</ASIN>
        <title>A Constructed Title</title>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(library.missing).toEqual(["authors", "publisher", "year"]);
  });

  it("counts a field one entry filled as filled for the document", () => {
    // 29 of the capture's 279 entries carry no publisher, and a library where
    // 29 books lack one is not a library with no publishers in it.
    const library = libraryOn(
      OWNED,
      entry(`
        <ASIN>B000000031</ASIN>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(library.missing).toEqual([]);
  });

  it("reads a field off an entry it refused", () => {
    // `missing` describes the document rather than the shelf: a sample carrying
    // a publisher proves the document can carry one, and the member is owed
    // that distinction rather than a field marked absent because the only entry
    // holding it was not theirs.
    const library = libraryOn(
      entry(`
        <ASIN>B000000032</ASIN>
        <title>A Constructed Title</title>
        <authors><author>Surname, Given</author></authors>
        <publishers><publisher>An Imprint</publisher></publishers>
        <publication_date>1965-08-01T00:00:00+0000</publication_date>
        <cde_contenttype>EBSP</cde_contenttype>
      `),
    );

    expect(library).toMatchObject({ books: [], skipped: 1, missing: [] });
  });

  it("names them in one order however the reader listed them", () => {
    // **The arm the sort has, and what it rests on is asserted rather than
    // relied on.** Its whole power is that `FIELDS` is declared in the union's
    // order rather than the alphabet's: alphabetise that four line array and
    // the sort becomes unobservable here, silently and with every arm still
    // green, so whoever deletes the sort next is not caught. Measured, on a
    // mutation chosen by the seat that did not write this arm.
    //
    // The fixture fills `year` alone, so the three that remain put `publisher`
    // where the two orders disagree about it. No other fixture here does, and
    // a comparator wrong only about `publisher` passes without one.
    const declared = declaredFields().filter((field) => field !== "year");
    const sorted = [...declared].sort();
    expect(
      declared,
      "FIELDS is now in alphabetical order, so this arm no longer observes " +
        "the sort in readKindleLibrary: put the declaration back into the " +
        "order KindleField names, or pin the sort another way",
    ).not.toEqual(sorted);

    const library = libraryOn(
      entry(`
        <ASIN>B000000033</ASIN>
        <publication_date>1965-08-01T00:00:00+0000</publication_date>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(library.missing).toEqual(sorted);
  });

  it("says the year is missing when every date it holds is not a year", () => {
    // The consequence `kindle.ts` states and which reads oddly at first: the
    // element is there on every entry and no entry yielded a year, so a year is
    // what this reader could not take out of the document. Calibre's placeholder
    // for a book with no date is the value that produces it.
    const library = libraryOn(
      entry(`
        <ASIN>B000000034</ASIN>
        <title>A Constructed Title</title>
        <authors><author>Surname, Given</author></authors>
        <publishers><publisher>An Imprint</publisher></publishers>
        <publication_date>0101-01-01T00:00:00+0000</publication_date>
        <cde_contenttype>EBOK</cde_contenttype>
      `),
    );

    expect(library.missing).toEqual(["year"]);
  });

  it("has nothing missing on a document carrying every element", () => {
    expect(libraryOn(OWNED).missing).toEqual([]);
  });

  it("says a document with no version has no version", () => {
    const read = readKindleLibrary(
      `<response><add_update_list>${OWNED}</add_update_list></response>`,
    );

    expect(read.ok && read.library.schemaVersion).toBeNull();
  });

  it("says a version that is not a number is no version", () => {
    const read = readKindleLibrary(`
      <response>
        <cache_metadata><version>one</version></cache_metadata>
        <add_update_list>${OWNED}</add_update_list>
      </response>`);

    expect(read.ok && read.library.schemaVersion).toBeNull();
  });

  /**
   * The two spellings of the field list, held against each other.
   *
   * **Recomputed from the module's own source rather than restated here**, in
   * both directions: a member added to the type and not to the array would
   * never be reported missing, and one added to the array and not to the type
   * would not compile. Restating either list in this file would give the pair a
   * third home and this test would agree with whichever it was written from.
   */
  it("can report every field its own type names", () => {
    const union = /export type KindleField =([^;]+);/.exec(readerSource);
    expect(union).not.toBeNull();
    const named = [...union![1]!.matchAll(/"([^"]+)"/g)]
      .map((match) => match[1])
      .sort();

    expect([...declaredFields()].sort()).toEqual(named);
    // A pattern that matched nothing would satisfy the equality with two empty
    // lists, which is the evasion this second assertion closes.
    expect(named.length).toBeGreaterThan(0);
  });
});

describe("the timings this reader publishes", () => {
  /**
   * The two rows of the size table in `kindle.ts`, as numbers.
   *
   * Read out of the docstring rather than restated, because the whole of this
   * guard is that the figures beside the table are the table's own.
   */
  function curve(): { mib: number; asc: number; desc: number }[] {
    return [
      ...readerSource.matchAll(/^ \* \| (\d+) \| (\d+) \| (\d+) \|$/gm),
    ].map((row) => ({
      mib: Number(row[1]),
      asc: Number(row[2]),
      desc: Number(row[3]),
    }));
  }

  /**
   * The prose the table's figures are quoted in, table included.
   *
   * **It opens on the table and closes before the memory paragraph**, and both
   * edges decide something. Opening on the sentence that states the ratios left
   * the gap above it unscanned, where a figure from an instrument this module no
   * longer quotes sat green. Closing later than this reaches the walk
   * paragraph, whose figures are a different measurement the table does not
   * produce: they are integers today, so nothing collects them, and a
   * percentage written there would redden this with a message about the table.
   */
  function claims(): string {
    const from = readerSource.indexOf("| 16 | 1913 | 2361 |");
    const to = readerSource.indexOf("**Memory is not measured here**");
    expect(from, "the table moved").toBeGreaterThan(0);
    expect(to, "the paragraph this window closes before moved").toBeGreaterThan(
      from,
    );
    return readerSource.slice(from, to);
  }

  it("reads a table with both orders at every size", () => {
    // Without this the assertion below is satisfied by an empty table producing
    // an empty set of figures, which is the evasion a derived guard is
    // otherwise open to.
    expect(curve().map((row) => row.mib)).toEqual([1, 2, 4, 8, 16]);
  });

  it("states no figure its own table does not produce", () => {
    // **A number in prose does not recount itself**, which is the same reason
    // two other rules in this branch derive their lists. A ratio derived by
    // hand in that paragraph was wrong repeatedly, each time under a sentence
    // forbidding what it had done.
    //
    // **Every decimal in the section, not every ratio.** Collecting only
    // figures written to two places left `2.0 to 2.6` admissible beside them,
    // and 2.6 is not a figure the table produces. So the two percentages are
    // derived here as well and the pattern takes any number of places.
    const rows = curve();
    const [, , half, eight, cap] = rows as [
      unknown,
      unknown,
      (typeof rows)[number],
      (typeof rows)[number],
      (typeof rows)[number],
    ];
    const widest = Math.max(
      ...rows
        .slice(0, 4)
        .map((row) => (Math.abs(row.asc - row.desc) / row.asc) * 100),
    );
    const expected = new Set([
      (cap.asc / eight.asc).toFixed(2),
      (cap.desc / eight.desc).toFixed(2),
      (cap.asc / half.asc).toFixed(2),
      (cap.desc / half.desc).toFixed(2),
      (((cap.desc - cap.asc) / cap.asc) * 100).toFixed(1),
      widest.toFixed(2),
    ]);

    const stated = new Set(claims().match(/\b\d+\.\d+\b/g) ?? []);
    expect([...stated].sort()).toEqual([...expected].sort());
  });
});

describe("an unreadable store is one skipped source, never a broken import", () => {
  /**
   * The rule the whole ticket turns on, asserted as a property rather than as a
   * list of cases.
   *
   * A member picks several sources at once and one of them is a file that is
   * not what they thought it was, or one the app has since changed. That has to
   * cost the one source and nothing else, so every outcome of this reader is a
   * value in a closed union and none of them is a throw. The documents below
   * are built to break it.
   *
   * **Each case carries the reading it should produce.** Asserting only that
   * the answer is one of the two shapes is a tautology: a case flipping from a
   * library to a failure would pass it silently.
   */
  const HOSTILE = [
    {
      what: "a file that is not XML at all",
      xml: "not xml, just words",
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "an empty file",
      xml: "",
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "XML that is somebody else's",
      xml: "<notes><note>remember the milk</note></notes>",
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "a response that is not this catalogue",
      // The reason the root is not the signature: anything that answered a
      // request keeps one.
      xml: "<response><status>ok</status></response>",
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "a document that declares its own entities",
      xml: `<!DOCTYPE response [<!ENTITY a "aa">]><response><add_update_list>${OWNED}</add_update_list></response>`,
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "a document with an unclosed element",
      xml: "<response><add_update_list></response>",
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "a document whose tags do not match",
      xml: "<response></other>",
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "an element inside the list spelled with a capital letter",
      // The 2021 capture reads this way because its publisher reformatted it
      // by hand in a word processor, which `kindle.ts` states. The refusal
      // follows from XML being case sensitive, and this is the arm that runs
      // it rather than leaving it asserted.
      xml: `<response><Add_update_list>${OWNED}</Add_update_list></response>`,
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "a root spelled in capitals",
      // XML is case sensitive and this reader is too. A document naming its
      // root `RESPONSE` is not the one Amazon writes, and reading it as one
      // would be reading HTML's rule into a format that does not have it.
      xml: `<RESPONSE><add_update_list>${OWNED}</add_update_list></RESPONSE>`,
      expected: { failure: "not-a-kindle-library" },
    },
    {
      what: "an entry holding nothing at all",
      xml: cache(entry("")),
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "an entry whose elements are all empty",
      xml: cache(
        entry(
          `<ASIN></ASIN><title></title><authors></authors>` +
            `<publishers></publishers><publication_date></publication_date>` +
            `<cde_contenttype></cde_contenttype>`,
        ),
      ),
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "an entry nested inside another entry",
      // Counted once, by the list rather than by the document: a document wide
      // search for the name would find both and report two books.
      xml: cache(
        `<meta_data>
           <ASIN>B000000040</ASIN>
           <cde_contenttype>EBOK</cde_contenttype>
           ${OWNED}
         </meta_data>`,
      ),
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "an entry outside the list",
      xml: `<response><add_update_list>${OWNED}</add_update_list>${OWNED}</response>`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a declaration written with single quotes",
      // Legal XML, and the arm the environment docblock above names: under
      // happy-dom this document parses as HTML and reads as no catalogue.
      xml: `<?xml version='1.0' encoding='utf-8'?><response><add_update_list>${OWNED}</add_update_list></response>`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a byte order mark before the root",
      xml: `\ufeff<response><add_update_list>${OWNED}</add_update_list></response>`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a doctype that declares no entities",
      // The refusal is on a declaration, not on a doctype: a document naming
      // one and declaring nothing has nothing to expand.
      xml: `<!DOCTYPE response><response><add_update_list>${OWNED}</add_update_list></response>`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "an element named like a path expression",
      xml: cache(
        entry(`<ASIN>B000000041</ASIN>
               <cde_contenttype>EBOK</cde_contenttype>
               <title>A Constructed Title</title>
               <this-is-not-read>../../*[1]</this-is-not-read>`),
      ),
      expected: { books: 1, skipped: 0 },
    },
  ];

  it.each(HOSTILE)(
    "answers rather than throwing for $what",
    ({ xml, expected }) => {
      const read = readKindleLibrary(xml);

      expect(
        read.ok
          ? { books: read.library.books.length, skipped: read.library.skipped }
          : { failure: read.failure },
      ).toEqual(expected);
    },
  );

  it("says a file is not a Kindle library rather than saying it is empty", () => {
    // Two different sentences to a member holding a file that did not work, and
    // the wrong one sends them looking for books in an app that has plenty.
    expect(
      readKindleLibrary("<response><status>ok</status></response>"),
    ).toEqual({ ok: false, failure: "not-a-kindle-library" });
  });

  it("says a library is empty when it is this catalogue with nothing in it", () => {
    expect(readKindleLibrary(cache())).toEqual({
      ok: false,
      failure: "empty",
    });
  });

  it("keeps the count when a document holds only what it refuses", () => {
    // Not the same thing as an empty library, and the member is owed the
    // difference: an account holding nothing but samples holds plenty, none of
    // which they own.
    const library = libraryOn(
      entry(`<ASIN>B000000050</ASIN>
             <title>A Constructed Title</title>
             <cde_contenttype>EBSP</cde_contenttype>`),
    );

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });

  it("reads a document whose entry order is not the order it reports", () => {
    // Nothing here sorts, so the document's order is the answer's order and a
    // caller can rely on it.
    const asins = booksOn(
      entry(`<ASIN>B000000063</ASIN><cde_contenttype>EBOK</cde_contenttype>`),
      entry(`<ASIN>B000000061</ASIN><cde_contenttype>EBOK</cde_contenttype>`),
      entry(`<ASIN>B000000062</ASIN><cde_contenttype>EBOK</cde_contenttype>`),
    ).map((book) => book.asin);

    expect(asins).toEqual(["B000000063", "B000000061", "B000000062"]);
  });
});

describe("the document this reader will parse is bounded", () => {
  it("refuses a document past the bound rather than parsing it", () => {
    // The string is one code unit past the count, which is the comparison the
    // reader makes. A document this size is not built here: what is asserted is
    // the refusal, and building 16 MiB of well formed XML to assert it would
    // cost the suite the memory the bound exists to protect.
    expect(readKindleLibrary("x".repeat(MAX_CACHE_BYTES + 1))).toEqual({
      ok: false,
      failure: "too-large",
    });
  });

  it("reads a file a member picked", async () => {
    const file = new File([cache(OWNED)], "KindleSyncMetadataCache.xml");
    const read = await readKindleCacheFile(file);

    expect(read.ok && read.library.books.map((book) => book.asin)).toEqual([
      "B000000001",
    ]);
  });

  it("refuses a file past the bound before reading a byte of it", async () => {
    // **The property is that `text` is never called**, which is the whole
    // reason the file entry point exists: decoding two gigabytes into a string
    // to then decline it has already spent the memory the bound protects. A
    // test asserting only the failure passes on a reader that reads the file
    // first.
    const file = new File([cache(OWNED)], "KindleSyncMetadataCache.xml");
    Object.defineProperty(file, "size", { value: MAX_CACHE_BYTES + 1 });
    const text = vi.spyOn(file, "text");

    expect(await readKindleCacheFile(file)).toEqual({
      ok: false,
      failure: "too-large",
    });
    expect(text).not.toHaveBeenCalled();
  });
});
