/**
 * The store registry, against real files of each store's own kind.
 *
 * **What is under test here is the row, not the reader.** `kobo.test.ts` and
 * `takeout.test.ts` already hold their readers against databases and archives
 * built to break them, and none of that is repeated. What only this file can
 * see is the seam: that a row's opener answers rather than throws, that what a
 * store said becomes the one record the import writes from, and that the two
 * stores whose fields disagree are resolved the way `fromTakeout` says they
 * are.
 *
 * **The engine is loaded for real**, `LibrarySettingsPage/hooks.test.tsx`'s
 * arrangement and its reason: `sqlite.ts` fetches the `.wasm` Vite emitted and
 * a stub with no `arrayBuffer` reports every run as a browser that cannot
 * compile WebAssembly. Replacing the global is what `tests/setup.ts` already
 * does, so this is that stub with one more URL in it and not a module mock.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { en } from "../../src/i18n";
import {
  PRODUCED_VALUE,
  producedValue,
  storeIdentifier,
  STORES,
  STORE_IDS,
  type StoreIdentifierScheme,
  type StoreReading,
} from "../../src/lib/stores";
import {
  A_VOLUME_ID,
  bookEntries,
  LIBRARY_FOLDER,
  takeoutFile,
} from "./takeoutFixtures";
import { databaseOf } from "./sqliteFixtures";
import { buildZip, packageDocument } from "../zipFixtures";

const require = createRequire(import.meta.url);

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.endsWith(".wasm")) throw new Error(`unexpected fetch: ${url}`);
      const path = require.resolve("sql.js/dist/sql-wasm-browser.wasm");
      const bytes = readFileSync(path);
      return {
        ok: true,
        status: 200,
        arrayBuffer: async () =>
          bytes.buffer.slice(
            bytes.byteOffset,
            bytes.byteOffset + bytes.byteLength,
          ),
      } as unknown as Response;
    }),
  );
});

/**
 * A Kobo `content` table, trimmed to the columns the adapter carries a field
 * for.
 *
 * **Narrower than `kobo.test.ts`'s and deliberately not shared with it.** That
 * file is testing which columns a reader will read and what it does when one is
 * missing, so its schema has to carry columns nothing reads. This one is
 * testing that what the reader answered arrives in a `StoreBook`, so it carries
 * the columns that become fields and nothing else. One fixture serving both
 * would have to be the wider of the two, and every future column added for the
 * reader's sake would then look like something this file cares about.
 */
const KOBO_SCHEMA = [
  `CREATE TABLE content (
     ContentID TEXT NOT NULL PRIMARY KEY,
     MimeType TEXT,
     BookID TEXT,
     Title TEXT,
     Attribution TEXT,
     Publisher TEXT,
     Language TEXT,
     ISBN TEXT,
     Series TEXT,
     SeriesNumber TEXT,
     DateCreated TEXT,
     Accessibility INTEGER,
     IsDownloaded BOOL
   )`,
];

/** One purchased EPUB, with every column the adapter reads filled in. */
const PURCHASED = `INSERT INTO content
  (ContentID, MimeType, BookID, Title, Attribution, Publisher, Language, ISBN,
   Series, SeriesNumber, DateCreated, Accessibility, IsDownloaded)
  VALUES ('a1b2c3d4-0000-4000-8000-000000000001', 'application/epub+zip', NULL,
          'Dune', 'Frank Herbert', 'Chilton Books', 'en', '9780441013593',
          'Dune Chronicles', '1', '1965-08-01T00:00:00.000', 1, 'true')`;

/** A row the store is advertising, which nobody owns. */
const ADVERT = `INSERT INTO content
  (ContentID, MimeType, BookID, Title, Accessibility, IsDownloaded)
  VALUES ('advert-1', 'application/epub+zip', NULL, 'Try this', 4, 'true')`;

async function koboFile(...rows: string[]): Promise<File> {
  return new File([await databaseOf(...KOBO_SCHEMA, ...rows)], "whatever.bin");
}

/** The library, or the failure raised where the assertion can see it. */
function libraryIn(reading: StoreReading) {
  if (!reading.ok) throw new Error(`expected a library: ${reading.failure}`);
  return reading.library;
}

describe("what a store is", () => {
  it("offers every row it holds, in the order it holds them", () => {
    // Derived rather than listed, so a row added to `STORES` is offered
    // without a second edit. The failure this refuses is the one the whole
    // ticket is: a reader that ships and no member can reach.
    expect(STORE_IDS).toEqual(Object.keys(STORES));
    expect(STORE_IDS.length).toBeGreaterThan(1);
  });

  it("says everything a member reads in words the catalogue carries", () => {
    // The type already refuses a key that is not a `MessageKey`. What it
    // cannot see is a key that resolves to nothing at runtime, which is what a
    // catalogue edit under a row would leave behind.
    for (const id of STORE_IDS) {
      const store = STORES[id];
      for (const key of [store.name, store.explain, store.choose]) {
        expect(en[key]).toBeTruthy();
      }
      if (store.caveat !== null) expect(en[store.caveat]).toBeTruthy();
      expect(store.accept).not.toBe("");
    }
  });

  it("names tolino on the Kobo row and says what that rests on", () => {
    // The ticket's whole finding: a claim of support with no bound is worse
    // than silence, because it turns an inference into a promise. So the
    // sentence has to carry both halves, and it is the only row with a caveat.
    const tolino = STORES.kobo.caveat;
    expect(tolino).not.toBeNull();
    const sentence = en[tolino!];
    expect(sentence).toContain("tolino");
    expect(sentence).toContain("never been run");
    expect(STORES.playBooks.caveat).toBeNull();
  });
});

describe("a Kobo becomes the record the import writes from", () => {
  it("carries every field the device filled in", async () => {
    const library = libraryIn(
      await STORES.kobo.open(await koboFile(PURCHASED)),
    );

    expect(library.books).toHaveLength(1);
    expect(library.books[0]).toEqual({
      key: "a1b2c3d4-0000-4000-8000-000000000001",
      title: "Dune",
      authors: ["Frank Herbert"],
      isbn: "9780441013593",
      // **Empty, and `ContentID` above is not an identifier.** `kobo.ts` says
      // that column holds a store UUID for a purchase and a `file:///` URL for
      // a sideloaded book, with nothing on the row saying which, so it names
      // the book on that device and is `key`.
      identifiers: [],
      publisher: "Chilton Books",
      year: 1965,
      language: "en",
      // A Kobo keeps none, so this is `null` rather than absent from the
      // record: `StoreBook` is one shape whatever store filled it.
      description: null,
      seriesName: "Dune Chronicles",
      seriesIndex: 1,
      format: "ebook",
      ownership: "owned",
    });
  });

  /**
   * What each thing a Kobo records is worth as a claim on a book.
   *
   * **The row is where this is decided and this is where that is held.** A Kobo
   * keeps a purchase, a Kobo Plus title and an OverDrive loan in one table, so
   * a reader answering one value for the whole device can only be wrong about
   * some of them, and the way it was wrong was to call a three week public
   * library book something the member owns.
   *
   * `8` and `9` are the two that matter and the other three are here so that a
   * mapping answering `unknown` for everything fails rather than passing the
   * two cases somebody thought to write.
   */
  it.each([
    [-1, "owned"],
    [1, "owned"],
    [2, "owned"],
    [8, "unknown"],
    [9, "unknown"],
  ])("imports accessibility %i as %s", async (accessibility, ownership) => {
    const row = `INSERT INTO content
      (ContentID, MimeType, BookID, Title, Accessibility, IsDownloaded)
      VALUES ('1', 'application/epub+zip', NULL, 'Dune', ${accessibility},
              'true')`;
    const library = libraryIn(await STORES.kobo.open(await koboFile(row)));

    expect(library.books[0]?.ownership).toBe(ownership);
  });

  it("says nothing about a device too old to have recorded it", async () => {
    // No `Accessibility` column at all, so the row is kept and what it was
    // cannot be recovered. `unknown` is this app's word for exactly that, and
    // answering `owned` would be reading a purchase out of a firmware that had
    // nowhere to write one.
    const older = [
      `CREATE TABLE content (
         ContentID TEXT NOT NULL PRIMARY KEY,
         BookID TEXT,
         Title TEXT
       )`,
      `INSERT INTO content (ContentID, BookID, Title)
         VALUES ('1', NULL, 'Dune')`,
    ];
    const file = new File([await databaseOf(...older)], "whatever.bin");
    const library = libraryIn(await STORES.kobo.open(file));

    expect(library.books).toHaveLength(1);
    expect(library.books[0]?.ownership).toBe("unknown");
  });

  it("answers per row rather than leaving it to the read", async () => {
    // The flag on the read is the fallback for a store that draws no line
    // through its rows, and a Kobo does draw one. What is asserted is the
    // record, not the import: `stores.ts::ownershipStated` says the import
    // still takes every book on the flag, so the loan below reaches a member's
    // shelf as owned and this test is what will stop that being silent.
    const loan = `INSERT INTO content
      (ContentID, MimeType, BookID, Title, Accessibility, IsDownloaded)
      VALUES ('loan-1', 'application/epub+zip', NULL, 'Borrowed', 9, 'true')`;
    const library = libraryIn(
      await STORES.kobo.open(await koboFile(PURCHASED, loan)),
    );

    // Keyed rather than positional: the reader sends no `ORDER BY`, so the
    // order rows come back in is the engine's business.
    const owned = (key: string) =>
      library.books.find((book) => book.key === key)?.ownership;

    expect(library.ownershipStated).toBe(true);
    expect(owned("a1b2c3d4-0000-4000-8000-000000000001")).toBe("owned");
    expect(owned("loan-1")).toBe("unknown");
  });

  it("keeps the count of rows that were not this member's books", async () => {
    // The number that makes the true sentence sayable: a device carrying two
    // hundred adverts has plenty on it and none of it theirs.
    const library = libraryIn(
      await STORES.kobo.open(await koboFile(PURCHASED, ADVERT)),
    );

    expect(library.books).toHaveLength(1);
    expect(library.skipped).toBe(1);
    expect(library.refused).toBe(0);
  });

  it("says nothing about the kind of copy where the device did not", async () => {
    // **`null`, not `ebook`.** Every format a Kobo does settle is a book to
    // read, so the temptation is to answer `ebook` for the whole device. That
    // answers for the device rather than reading it, and `formatOf` refuses
    // the same thing on the Calibre side for the same reason.
    const unmapped = `INSERT INTO content
      (ContentID, MimeType, BookID, Title, Accessibility, IsDownloaded)
      VALUES ('sound-1', 'application/octet-stream', NULL, 'A recording', 1,
              'true')`;
    const library = libraryIn(await STORES.kobo.open(await koboFile(unmapped)));

    expect(library.books[0]?.format).toBeNull();
  });
});

describe("a Play Books export becomes the same record", () => {
  /**
   * An archive out of entries already built, where the fixtures' own
   * `archiveOf` takes the specs. Named apart from it deliberately: two
   * functions of one name in one file is this commit's own subject.
   */
  async function archiveOf(entries: Awaited<ReturnType<typeof bookEntries>>) {
    return new File([await buildZip({ entries })], "takeout.zip");
  }

  it("takes the title from the store's own index", async () => {
    // The sidecar is Google's index, and the Calibre import already keeps this
    // rule: the index leads and the file fills what it left empty.
    const library = libraryIn(
      await STORES.playBooks.open(
        await archiveOf(
          await bookEntries({
            sidecar: { title: "What the store calls it" },
            epubTitle: "What the file calls it",
          }),
        ),
      ),
    );

    expect(library.books).toHaveLength(1);
    expect(library.books[0]?.title).toBe("What the store calls it");
    expect(library.books[0]?.format).toBe("ebook");
  });

  it("takes the authors from the file, which separates them", async () => {
    // The one field where the file wins, and structure is the reason: the
    // sidecar's author line is one string and the EPUB carries `dc:creator`
    // separately, so preferring the index would throw away a division the file
    // already made.
    const library = libraryIn(
      await STORES.playBooks.open(
        await archiveOf(
          await bookEntries({
            sidecar: { author: "One Unsplit Line" },
            opf: packageDocument(
              `<dc:identifier id="pub-id">urn:uuid:1</dc:identifier>
               <dc:title>Dune</dc:title>
               <dc:creator>Frank Herbert</dc:creator>
               <dc:creator>Brian Herbert</dc:creator>`,
            ),
          }),
        ),
      ),
    );

    expect(library.books[0]?.authors).toEqual([
      "Frank Herbert",
      "Brian Herbert",
    ]);
  });

  it("falls back to the index's one author where the file names none", async () => {
    const library = libraryIn(
      await STORES.playBooks.open(
        await archiveOf(
          await bookEntries({
            sidecar: { author: "Only In The Index" },
            opf: packageDocument(
              `<dc:identifier id="pub-id">urn:uuid:1</dc:identifier>
               <dc:title>Dune</dc:title>`,
            ),
          }),
        ),
      ),
    );

    expect(library.books[0]?.authors).toEqual(["Only In The Index"]);
  });

  it("counts a book the export named and could not open", async () => {
    // A refusal is not a skip: the export carried the book, so reporting it as
    // "not a Play Books book" would say the archive held less than it did.
    const good = await bookEntries({ name: "Dune" });
    const broken = await bookEntries({ name: "Torn", mimetype: "text/plain" });
    const library = libraryIn(
      await STORES.playBooks.open(await archiveOf([...good, ...broken])),
    );

    expect(library.books).toHaveLength(1);
    expect(library.refused).toBe(1);
  });
});

/**
 * One Kindle for PC catalogue holding one owned book.
 *
 * **Constructed, and narrower than `kindle.test.ts`'s.** That file is testing
 * which elements the reader reads and what it does when one is missing, so its
 * documents carry elements nothing reads. This one is testing that what the
 * reader answered arrives in a `StoreBook`, which is `koboRows`' split and its
 * reason. No XML declaration, because the published capture carries none.
 */
const KINDLE_CATALOGUE = `
<response>
  <sync_time>2019-01-01T00:00:00+0000;softwareVersion:51068</sync_time>
  <cache_metadata><version>1</version></cache_metadata>
  <add_update_list><meta_data>
    <ASIN>B000000001</ASIN>
    <title pronunciation="">A Constructed Title</title>
    <authors><author pronunciation="">Surname, Given</author></authors>
    <publishers><publisher>A Constructed Publisher</publisher></publishers>
    <publication_date>1965-08-01T00:00:00+0000</publication_date>
    <cde_contenttype>EBOK</cde_contenttype>
  </meta_data></add_update_list>
</response>`;

/**
 * One Adobe Digital Editions record, in the whole library layout.
 *
 * **No XML declaration, which is what lets this file keep the suite's
 * happy-dom.** That parser reads a declaration written with single quotes as
 * HTML and hands back a document whose root is `html`, which is why
 * `adobeDigitalEditions.test.ts` takes jsdom in a docblock and asserts that
 * case by name. The reader matches every element by local name, so the plainest
 * document it accepts is enough for the seam, which is all this file tests.
 */
function adobeCatalogue(identifier: string): string {
  return `<manifest><contentRecord>
    <title>A Constructed Title</title>
    <creator>Surname, Given</creator>
    <identifier>${identifier}</identifier>
  </contentRecord></manifest>`;
}

async function adobeBook(identifier: string) {
  const library = libraryIn(
    await STORES.adobe.open(
      new File([adobeCatalogue(identifier)], "A Book.epub.xml"),
    ),
  );
  expect(library.books).toHaveLength(1);
  return library.books[0]!;
}

describe("what a store calls a book, where that is not an ISBN", () => {
  // **The gap this closed.** Two of the four stores read an identifier and no
  // ISBN, and `BookCreate` had one identifier field and it was `isbn`, so the
  // fact that decided the Kindle route survived the read and not the import.

  it("takes the Google volume id off a Play Books export", async () => {
    const library = libraryIn(
      await STORES.playBooks.open(
        new File([await buildZip({ entries: await bookEntries() })], "t.zip"),
      ),
    );

    expect(library.books[0]?.identifiers).toEqual([
      { scheme: "google_books", value: A_VOLUME_ID },
    ]);
  });

  it("does not confuse it with the key, which is the path in the archive", () => {
    // Two folders may hold two editions of one title, which is what the path
    // tells apart; the volume id is what Google calls the book. Reading `key`
    // would have kept a file path under an identifier's name.
    expect(A_VOLUME_ID).not.toBe(LIBRARY_FOLDER);
  });

  it("takes the ASIN off a Kindle catalogue and leaves the ISBN alone", async () => {
    // 1,032 of 1,032 entries carry an ASIN and none carries an ISBN, which is
    // why this route was preferred over the account export. It goes into
    // `identifiers` and never into `isbn`: that field check digits its input on
    // the server, so an ASIN there would match nothing.
    const library = libraryIn(
      await STORES.kindle.open(
        new File([KINDLE_CATALOGUE], "KindleSyncMetadataCache.xml"),
      ),
    );

    expect(library.books).toHaveLength(1);
    expect(library.books[0]?.identifiers).toEqual([
      { scheme: "asin", value: "B000000001" },
    ]);
    expect(library.books[0]?.isbn).toBeNull();
  });

  // **One assertion an arm.** A mutation putting the raw identifier in the match
  // key and one copying the ISBN into `identifiers` are different defects, and
  // an arm asserting both reddens on either without its name saying which.

  it("takes the ISBN off a Digital Editions record that carried one", async () => {
    // The catalogue publishes no scheme for `dc:identifier`, so the value
    // decides: `adobeDigitalEditions.ts` check digits it and this is where the
    // answer becomes the field the importer matches on.
    expect((await adobeBook("urn:isbn:9780306406157")).isbn).toBe(
      "9780306406157",
    );
  });

  it("does not also file that ISBN under identifiers", async () => {
    // That field is for a name that is not an ISBN, and the match key already
    // holds this one, so a copy here would be one fact in two places.
    expect((await adobeBook("urn:isbn:9780306406157")).identifiers).toEqual([]);
  });

  it("leaves the ISBN null where that identifier was not an ISBN", async () => {
    const uuid = "urn:uuid:00000000-0000-4000-8000-000000000001";

    expect((await adobeBook(uuid)).isbn).toBeNull();
  });

  it("files nothing under identifiers where it was not an ISBN either", async () => {
    // The unchanged half: this store's identifier has no scheme to name it, a
    // member `StoreIdentifierScheme` does not have, so it goes no further than
    // the read.
    const uuid = "urn:uuid:00000000-0000-4000-8000-000000000001";

    expect((await adobeBook(uuid)).identifiers).toEqual([]);
  });
});

describe("which store a file belongs to is decided by the bytes", () => {
  // **The property another store's arrival can break.** A row carries no
  // filename and `accept` is advice to the file dialog, so the openers have to
  // tell the files apart themselves. A store whose file is a family rather than
  // a name, or one whose vendor renames it, is then a row plus a reader rather
  // than a change to this shape.
  it("refuses a Takeout archive handed to the Kobo row", async () => {
    const zip = await buildZip({
      entries: await bookEntries({ name: "Dune" }),
    });

    expect(
      await STORES.kobo.open(new File([zip], "KoboReader.sqlite")),
    ).toEqual({ ok: false, failure: "not-a-database" });
  });

  it("refuses a Kobo device handed to the Play Books row", async () => {
    const device = await koboFile(PURCHASED);

    expect(
      await STORES.playBooks.open(
        new File([await device.arrayBuffer()], "takeout.zip"),
      ),
    ).toEqual({ ok: false, failure: "not-an-archive" });
  });

  it("reads the right store whatever the file is called", async () => {
    // The other direction, and the one that says the name is not consulted at
    // all rather than merely not trusted: both fixtures carry the other
    // store's name and both read.
    const device = libraryIn(
      await STORES.kobo.open(
        new File(
          [await (await koboFile(PURCHASED)).arrayBuffer()],
          "takeout.zip",
        ),
      ),
    );
    const zip = await buildZip({
      entries: await bookEntries({ name: "Dune" }),
    });
    const archive = libraryIn(
      await STORES.playBooks.open(new File([zip], "KoboReader.sqlite")),
    );

    expect(device.books).toHaveLength(1);
    expect(archive.books).toHaveLength(1);
  });
});

describe("an unreadable store is one skipped source, never a broken import", () => {
  // Every arm answers rather than throws. That is the property the card is
  // built on: a member picking two stores where one moved keeps the other, and
  // it can only be true if the opener has a value for every way a file fails.
  it("answers when the file is not a database at all", async () => {
    const reading = await STORES.kobo.open(new File(["nonsense"], "kobo.bin"));

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
  });

  it("answers when the database is somebody else's", async () => {
    const other = new File(
      [await databaseOf(`CREATE TABLE shelves (id INTEGER PRIMARY KEY)`)],
      "other.sqlite",
    );

    expect(await STORES.kobo.open(other)).toEqual({
      ok: false,
      failure: "not-a-kobo-device",
    });
  });

  it("answers when the device carries no book rows", async () => {
    expect(await STORES.kobo.open(await koboFile())).toEqual({
      ok: false,
      failure: "empty",
    });
  });

  it("answers when the archive is not a zip", async () => {
    const reading = await STORES.playBooks.open(
      new File(["nonsense"], "takeout.zip"),
    );

    expect(reading).toEqual({ ok: false, failure: "not-an-archive" });
  });

  it("answers when the zip holds no Play Books book", async () => {
    const zip = await buildZip({
      entries: [{ name: `${LIBRARY_FOLDER}/notes.txt`, data: "nothing here" }],
    });

    expect(await STORES.playBooks.open(new File([zip], "takeout.zip"))).toEqual(
      { ok: false, failure: "not-a-takeout" },
    );
  });
});

/**
 * The value rule, which was spelled twice before it was spelled here.
 *
 * `lib/calibre.ts` and `pages/ScanPage/types.ts` each carried a private
 * `PRODUCED_VALUE`, identically named and identically typed, and the two were
 * held in agreement by tests that read the other module's source text. Those
 * two arms are gone. What replaces them is this file measuring the rule and
 * each walk's own test measuring that its walk consults it.
 */
describe("what a scheme's own producers write", () => {
  const SHAPES = Object.entries(PRODUCED_VALUE) as [
    StoreIdentifierScheme,
    RegExp,
  ][];

  /**
   * The one form a value rule may take: a whole value, one character class, one
   * bounded repeat.
   *
   * **Stated as the form rather than as the characters a bad rule would use**,
   * which is the difference between a guard and a spell checker:
   * `^(?:[A-Za-z0-9_-]{1,12}){1,12}$` carries no `+`, no `*` and no `|`, begins
   * `^` and ends `$`, and backtracks exponentially. The scan this replaced
   * admitted it, and so did the scan's own author's mutation. Found by the
   * security seat.
   *
   * **A trailing `\$` is why the anchor is read as a form too.** A source
   * ending in an escaped literal dollar satisfies `endsWith("$")` and anchors
   * nothing, so `^[A-Za-z0-9]{10}\$` would admit that value followed by
   * anything at all.
   *
   * **This is deliberately narrower than the property that justifies it, and
   * that gap is the thing to read before widening either.** `^B[A-Za-z0-9]{9}$`
   * is anchored, flagless and constant work, has every property named above,
   * and is refused here; so is `^[A-Z]{2}[0-9]{8}$`. A prefixed rule is not
   * hypothetical, it is what `PRODUCED_VALUE`'s own `asin` comment spends a
   * paragraph declining. **The cheap way past a red arm here is to re-spell the
   * rule as one wide class, which admits everything the prefix excluded**, so
   * the answer is to widen this form with the reason written down rather than
   * to loosen the class. Found by the design seat.
   *
   * **The one position sweep below depends on this.** It varies the last
   * character only, and that bounds the whole value because this form
   * guarantees a single class. Widen the form to two concatenated classes and
   * the sweep silently stops bounding the other positions.
   */
  const VALUE_RULE = /^\^\[[^\]]+\]\{\d+(?:,\d+)?\}\$$/;

  const wellFormed = (shape: RegExp) => VALUE_RULE.test(shape.source);

  /** No flags, which are part of the rule and change what anchoring means. */
  const unflagged = (shape: RegExp) => shape.flags === "";

  /** One value each rule admits, so a sweep can vary a single character of it. */
  const SAMPLE: Record<StoreIdentifierScheme, string> = {
    asin: "B000R34YKC",
    google_books: "s7NIrgEACAAJ",
  };

  const DIGITS = "0123456789";
  const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const LOWER = "abcdefghijklmnopqrstuvwxyz";

  /**
   * Which of the 128 ASCII code points each rule admits in one position, in
   * code point order.
   *
   * **The set and not its size, and the difference is a live evasion.**
   * `[A-Za-z0-8\x7f]` is 62 characters too: it drops the digit `9` from
   * Amazon's alphabet and admits DEL, and against a count it passed every arm
   * in all three files that touch this rule, every positive sample here being
   * 9 free. Found by the design seat. A comparison of the characters fails
   * naming the one that arrived, which is what stops the answer being to bump
   * the literal.
   *
   * Total over the union, `PRODUCED_VALUE`'s own discipline: a scheme added
   * with no alphabet here does not compile, so the sweep cannot quietly stop
   * covering one.
   */
  const ALPHABET: Record<StoreIdentifierScheme, string> = {
    asin: DIGITS + UPPER + LOWER,
    google_books: `-${DIGITS}${UPPER}_${LOWER}`,
  };

  it("carries a shape for every scheme the union names", () => {
    // **Completeness is the type's job, not this arm's**: the table is a
    // `Record<StoreIdentifierScheme, RegExp>`, so a scheme added to that union
    // with no shape here does not compile. What this arm buys is that the
    // sweeps below are reading a populated table rather than agreeing over an
    // empty one, which is the way every arm in this block passes for nothing.
    expect(SHAPES.length).toBeGreaterThan(1);
    expect(SHAPES.map(([scheme]) => scheme).sort()).toEqual([
      "asin",
      "google_books",
    ]);
  });

  it("writes every shape as one class repeated a bounded number of times", () => {
    // **The table is what this guards, not today's two entries.** Both of those
    // do constant work and neither can backtrack. A consolidated table is where
    // somebody later adds a scheme whose rule nests a quantifier or alternates,
    // and that is the edit that introduces the class: these values come off a
    // member's own `metadata.db`, EPUB or export, so the cost is theirs.
    expect(SHAPES.filter(([, s]) => !wellFormed(s)).map(([k]) => k)).toEqual(
      [],
    );
  });

  it("names a rule written any other way", () => {
    // The predicate's own negative cases, one property each, so dropping any
    // one part of the form leaves one of these admitted. Deliberately not
    // described by position: this list grows, and a comment saying which entry
    // is which goes stale on the next append. Each carries its own reason where
    // it needs one.
    expect(
      [
        /[A-Za-z]{3}/,
        /^[A-Za-z]{3}/,
        /[A-Za-z]{3}$/,
        /^[A-Za-z]{3}\$/,
        /^[A-Za-z]{3}|x$/,
        /^[A-Za-z]+$/,
        /^(?:[A-Za-z0-9_-]{1,12}){1,12}$/,
        // **A well formed core with something on either side of it**, which is
        // what pins `VALUE_RULE`'s own two anchors. Every case above fails
        // inside the core, so deleting either anchor from `VALUE_RULE` left all
        // of them refused and every arm green, while the first of these matched
        // arbitrary input and the second matched any string holding an `x`.
        // Measured by the security seat.
        /^[A-Za-z0-9]{10}$|.*/,
        new RegExp("x|^[A-Za-z0-9]{10}$"),
      ].filter(wellFormed),
    ).toEqual([]);
    expect(wellFormed(/^[A-Za-z0-9]{10}$/)).toBe(true);
    // A range is the form too, so a rule of two lengths needs no argument.
    expect(wellFormed(/^[A-Za-z0-9]{10,13}$/)).toBe(true);
  });

  it("carries no flag on any shape", () => {
    expect(SHAPES.filter(([, s]) => !unflagged(s)).map(([k]) => k)).toEqual([]);
  });

  it("names a rule carrying a flag, whichever flag it is", () => {
    // `m` is the one that matters and it defeats the form above without
    // touching it: `^` and `$` then match at a line break, so an ASIN followed
    // by a newline and anything at all is admitted. `g` and `y` carry a
    // `lastIndex`, so one object answers differently on successive calls.
    expect(
      ["m", "g", "y", "i", "s", "u"]
        .map((flag) => new RegExp("^[A-Za-z0-9]{10}$", flag))
        .filter(unflagged),
    ).toEqual([]);
    expect(unflagged(/^[A-Za-z0-9]{10}$/)).toBe(true);
  });

  it("refuses a value carried past the anchor by a line break", () => {
    // The consequence, asserted through the door rather than off the pattern,
    // so the two readings have to agree.
    expect(producedValue("asin", "B000R34YKC\nEVIL")).toBe(false);
    expect(producedValue("google_books", "s7NIrgEACAAJ\nEVIL")).toBe(false);
  });

  it("admits the alphabet it names and no character more", () => {
    // **A complete ASCII sweep read back as a set, never a list of what it
    // refuses.** The instrument this adds to: a 15 candidate sample passed 88
    // of 88 against `[A-Za-z0-9.]`, because no candidate carried a `.` at
    // length ten, and the form assertion above does not move for that edit
    // either, being about the pattern's shape rather than its class. Every one
    // of the 128 ASCII code points is tried in the last position of a value
    // each rule admits, and the characters that came back are compared, not
    // how many there were. **Above ASCII this is a sample of five and not a
    // sweep**, so it bounds nothing there.
    const admitted = Object.fromEntries(
      SHAPES.map(([scheme]) => {
        const stem = SAMPLE[scheme].slice(0, -1);
        let taken = "";
        for (let code = 0; code < 128; code += 1) {
          const one = String.fromCharCode(code);
          if (producedValue(scheme, stem + one)) taken += one;
        }
        return [scheme, taken];
      }),
    );

    expect(admitted).toEqual(ALPHABET);
    // The count as well, so the boundary argument above stays attached to
    // something that fails: 62 is the alphanumerics, 64 the URL safe set.
    //
    // **Sorted numerically and not by the default comparator**, which sorts
    // lexicographically: `[9, 62, 64].sort()` is `[62, 64, 9]`, so a scheme
    // with a single digit alphabet would have to have its expectation written
    // in that order to pass. Found by the security seat.
    expect(
      Object.values(ALPHABET)
        .map((one) => one.length)
        .sort((a, b) => a - b),
    ).toEqual([62, 64]);
    expect(
      ["\u00e9", "\u00fc", "\u4e2d", "\u{1f600}", "\u00a0"].filter((one) =>
        SHAPES.some(([scheme]) =>
          producedValue(scheme, SAMPLE[scheme].slice(0, -1) + one),
        ),
      ),
    ).toEqual([]);
  });

  it("is sweeping a value each rule actually admits", () => {
    // The sweep varies the last character of `SAMPLE`, so a sample the rule
    // already refuses would report every count as zero and leave the table
    // above a pair of constants nothing measured.
    expect(
      SHAPES.filter(([scheme]) => !producedValue(scheme, SAMPLE[scheme])).map(
        ([scheme]) => scheme,
      ),
    ).toEqual([]);
  });

  it("asks the table rather than a second spelling of it", () => {
    // Driven off the table, so a scheme added to it is swept without an edit
    // here. What it refuses is `producedValue` growing a rule of its own: a
    // literal list would agree with a function that stopped reading the table.
    const corpus = [
      "B000R34YKC",
      "aB3-dE6_gH9j",
      "",
      "   ",
      "B000R34YK.",
      "aB3-dE6_gH9.",
      "162380874X",
    ];
    const disagreed = SHAPES.flatMap(([scheme, shape]) =>
      corpus
        .filter((value) => producedValue(scheme, value) !== shape.test(value))
        .map((value) => `${scheme}: ${value}`),
    );

    expect(disagreed).toEqual([]);
    // Both answers appear, so an agreement that held because nothing passed is
    // not what was measured.
    expect(
      new Set(
        SHAPES.flatMap(([scheme]) =>
          corpus.map((value) => producedValue(scheme, value)),
        ),
      ),
    ).toEqual(new Set([true, false]));
  });

  it("takes ten characters of Amazon's alphabet, in either case", () => {
    expect(producedValue("asin", "B000R34YKC")).toBe(true);
    expect(producedValue("asin", "b000r34ykc")).toBe(true);
  });

  it("takes a printed edition's ISBN-10, which is what Amazon issued", () => {
    // Not narrowed to a `B` prefix: calibre's own regression fixture carries
    // `amazon_ca` of this value, and four of the eight `ASIN` and `AMAZON`
    // values in the 931 file library are an ISBN-10.
    expect(producedValue("asin", "162380874X")).toBe(true);
  });

  it("refuses an Amazon value of any other length", () => {
    expect(producedValue("asin", "B000R34YK")).toBe(false);
    expect(producedValue("asin", "B000R34YKCD")).toBe(false);
  });

  it("refuses a character Amazon's alphabet does not have", () => {
    expect(producedValue("asin", "B000R34YK.")).toBe(false);
    expect(producedValue("asin", "B000R34YK-")).toBe(false);
  });

  it("refuses the uuid calibre mints where a file has no ASIN", () => {
    // On its length and never by recognising a uuid, which would be an
    // inclusion list over an open set: calibre may mint a different filler.
    expect(producedValue("asin", "00000000-0000-4000-8000-000000000001")).toBe(
      false,
    );
  });

  it("takes twelve characters of the URL safe alphabet for a volume id", () => {
    expect(producedValue("google_books", "s7NIrgEACAAJ")).toBe(true);
    expect(producedValue("google_books", A_VOLUME_ID)).toBe(true);
  });

  it("refuses a volume id of any other length", () => {
    expect(producedValue("google_books", "aB3-dE6_gH9")).toBe(false);
    expect(producedValue("google_books", "aB3-dE6_gH9jk")).toBe(false);
  });

  it("refuses a character the URL safe alphabet does not have", () => {
    expect(producedValue("google_books", "aB3-dE6_gH9.")).toBe(false);
    expect(producedValue("google_books", "aB3-dE6_gH9+")).toBe(false);
  });

  it("refuses a padded value rather than trimming it", () => {
    // Closing it up would send a value this app invented rather than the one
    // the file carried.
    expect(producedValue("asin", " B000R34YKC")).toBe(false);
    expect(producedValue("asin", "B000R34YKC ")).toBe(false);
    expect(producedValue("google_books", " s7NIrgEACAAJ")).toBe(false);
  });

  it("builds the row a walk keeps, with the value as it was written", () => {
    // Neither trimmed nor lower cased: the canonical form of a scheme's value
    // is `lib/bookRequest.CANONICAL_VALUE`'s, which is the one door
    // every reader's value passes through, and doing it here as well would
    // make that door optional.
    expect(storeIdentifier("asin", "b000r34ykc")).toEqual({
      scheme: "asin",
      value: "b000r34ykc",
    });
  });

  it("answers nothing for a value the scheme's readers would not produce", () => {
    // `null` rather than a throw, because the caller is walking a library: an
    // import of nine hundred books must not turn on one library's odd row.
    expect(storeIdentifier("asin", "9780441013593")).toBeNull();
    expect(storeIdentifier("google_books", "aB3-dE6_gH9.")).toBeNull();
  });
});

/**
 * The Google half is one rule and `takeout.ts` holds a second copy of it, on
 * purpose.
 *
 * That module's `VOLUME_ID` is the same regex doing a different job: it tells
 * the volume id line of a sidecar's metadata block from the reading state line
 * beside it, without matching an English label a German export does not carry.
 * Folding it into `PRODUCED_VALUE` would mean that widening the identifier rule
 * to thirteen characters silently widens a line discriminator, and a reading
 * state line of thirteen safe characters would be read as a volume id.
 *
 * **So the two stay apart and their agreement is this sweep.** It replaces one
 * that read `takeout.ts`'s source for the constant, which could say the two
 * spellings matched and could not say the constant was reached: a reader that
 * kept the literal and stopped consulting it passed. This asks the reader.
 */
describe("the Takeout reader and the value rule admit the same volume ids", () => {
  /**
   * Nine sidecar lines: two real shapes, two lengths either side, two
   * characters outside the alphabet and three that are nothing but one
   * character of it repeated.
   */
  const CANDIDATES = [
    "aB3-dE6_gH9j",
    "s7NIrgEACAAJ",
    "aB3-dE6_gH9",
    "aB3-dE6_gH9jk",
    "aB3-dE6_gH9.",
    "aB3-dE6_gH9+",
    "____________",
    "------------",
    "000000000000",
  ];

  it("takes a line as the volume id exactly where the rule admits it", async () => {
    // One archive holding one book per candidate, so this is one read rather
    // than nine. A sidecar whose metadata line is not a volume id makes the
    // pair not a book at all, so a candidate the reader refused is a candidate
    // absent from the library.
    const library = libraryIn(
      await STORES.playBooks.open(
        await takeoutFile(
          CANDIDATES.map((volumeId, at) => ({
            name: `Book${at}`,
            sidecar: { volumeId },
          })),
        ),
      ),
    );
    const taken = new Set(
      library.books.flatMap((book) =>
        book.identifiers.map((identifier) => identifier.value),
      ),
    );

    expect(
      CANDIDATES.filter(
        (candidate) =>
          taken.has(candidate) !== producedValue("google_books", candidate),
      ),
    ).toEqual([]);
    // Both answers appear, so an agreement that held because the archive was
    // unreadable is not what was measured.
    expect(taken.size).toBeGreaterThan(0);
    expect(taken.size).toBeLessThan(CANDIDATES.length);
  });
});

/**
 * Every member a reader's library declares is read by the adapter it reaches.
 *
 * **The seam is a reader's only consumer**, so a member no `from*` reads is a
 * value produced for nobody. Five `schemaVersion` fields and five `missing`
 * fields lived that way behind 23 union members and seven helpers until the
 * seam was asked what it read.
 *
 * **Nothing here lists a store.** The adapters are found by their own
 * declaration, each names the interface it takes, and the module that interface
 * comes from is read off the import that brought it in. So a seventh store adds
 * no line to this file and cannot be left out of it either.
 *
 * **The count is crossed against `STORE_IDS`**, which is derived from `STORES`
 * rather than from the source text, so a declaration this regex stopped
 * matching fails here rather than passing on a shorter list.
 *
 * **What this does not reach.** A member read by the adapter and then dropped
 * on the floor is **unguarded**: `void library.schemaVersion;` as `fromKobo`'s
 * first statement satisfies every arm below, measured by the design seat, and
 * nothing about `StoreLibrary`'s own fields observes it. A field on a `*Book`
 * rather than on a `*Library` is covered instead, by `storeToBookCreate`'s
 * total mapping.
 */
describe("a reader's library says nothing the seam drops", () => {
  // **`import.meta.glob` and not `node:fs`**, which `houseRules.test.ts`
  // prefers for a reason that bites here: this file runs under happy-dom, where
  // `import.meta.url` is not a `file:` URL and `fileURLToPath` throws before an
  // assertion runs. `licence.test.ts` takes the node environment instead,
  // because it reads across the trees and the glob is rooted at `frontend/`.
  const MODULES = import.meta.glob("../../src/lib/*.ts", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  function sourceOf(module: string): string {
    const source = MODULES[`../../src/lib/${module}.ts`];
    if (source === undefined) throw new Error(`no source for ${module}`);
    return source;
  }

  /**
   * The source with comments removed, so a rule cannot be satisfied by prose.
   *
   * **The eighth copy in this tree**, each keeping its own for the same stated
   * reason: a test importing another test file evaluates that file's
   * `describe`s. Counted rather than listed, because a list of the other seven
   * goes stale in the direction where a ninth is written and nobody here knows.
   * Ticketed at eight, since the reason for copying stops holding somewhere
   * below it and `tests/lib/sqliteFixtures.ts` is the precedent for a shared
   * helper that is not a test.
   *
   * Same known defect as every other copy: it cuts inside a string literal
   * containing `//`. No module under `src/lib/` is shaped that way.
   */
  function withoutProse(source: string): string {
    return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
  }

  /** The index just past the delimiter closing the one that opens at `open`. */
  function past(code: string, open: number): number {
    const openers = "([{";
    const closers = ")]}";
    let depth = 0;
    for (let at = open; at < code.length; at += 1) {
      if (openers.includes(code[at]!)) depth += 1;
      else if (closers.includes(code[at]!)) {
        depth -= 1;
        if (depth === 0) return at + 1;
      }
    }
    throw new Error(`unbalanced from ${open}`);
  }

  interface Adapter {
    /** The function, for the message a failure carries. */
    readonly name: string;
    /** The reader's library interface, which its parameter names. */
    readonly library: string;
    /** Members it reads off that parameter. */
    readonly reads: ReadonlySet<string>;
    /** Members the interface declares. */
    readonly declared: readonly string[];
  }

  const ADAPTERS: readonly Adapter[] = (() => {
    const seam = withoutProse(sourceOf("stores"));
    const declaration = /function (from\w+)\((\w+): (\w+)\): StoreLibrary \{/g;
    return [...seam.matchAll(declaration)].map((match) => {
      const [whole, name, parameter, library] = match;
      const opens = match.index + whole!.length - 1;
      const body = seam.slice(opens, past(seam, opens));
      const reads = new Set(
        [...body.matchAll(new RegExp(`\\b${parameter}\\.(\\w+)`, "g"))].map(
          (read) => read[1]!,
        ),
      );
      // A destructure reads by name without spelling the parameter before it,
      // so the names inside one count as reads. Without this arm a rewrite
      // using it would fail here for no fault of its own.
      //
      // **`[^{}]`, not `[^}]`.** The body this searches begins with the
      // function's own opening brace, so the looser class matched from there to
      // the pattern's closing brace and handed the split `const { books` as its
      // first name. Measured: the arm reported `books` unread against an
      // adapter that destructured it, and `skipped` clean, which is a guard
      // failing on correct code and half silent about it.
      const unpacked = new RegExp(`\\{([^{}]*)\\}\\s*=\\s*${parameter}\\b`);
      for (const spelt of unpacked.exec(body)?.[1]?.split(",") ?? []) {
        const named = /^\s*(\w+)/.exec(spelt)?.[1];
        if (named !== undefined) reads.add(named);
      }
      const from = new RegExp(
        `import type \\{([^}]*\\b${library}\\b[^}]*)\\} from "\\./(\\w+)"`,
      ).exec(seam);
      if (from === null)
        throw new Error(`${library!} is imported from nowhere`);
      const module = withoutProse(sourceOf(from[2]!));
      const shape = new RegExp(`export interface ${library} \\{`).exec(module);
      if (shape === null) throw new Error(`${library!} is declared nowhere`);
      const opensShape = shape.index + shape[0].length - 1;
      const members = module.slice(opensShape, past(module, opensShape));
      return {
        name: name!,
        library: library!,
        reads,
        // **`readonly` is optional and nothing in this repository requires
        // it**: `frontend/` has no eslint config, `tsc` does not check it and
        // prettier does not add it, and `lib/audiobookGroups.ts`,
        // `lib/audiobook.ts` and `lib/bookFilters.ts` declare members without
        // it today. A pattern spelling the keyword read a dead member added
        // with it and passed over the same member added without, on three of
        // the six libraries; it was the other seat that spelled it that way,
        // because every mutation the author picked spelled it the way the
        // author could see.
        //
        // **It reads a line start, so a member whose type opens a block over
        // reports the names inside it**: `meta: {` with `count: number;` on
        // the next line contributes `count` as well. Nothing in the tree has
        // that shape, and the failure is loud and names the inner name, so the
        // relaxed anchor is the cheaper trade. The same member written on one
        // line reports correctly, as does a multi line union.
        declared: [
          ...members.matchAll(/^\s*(?:readonly\s+)?(\w+)\??\s*:/gm),
        ].map((member) => member[1]!),
      };
    });
  })();

  it("finds one adapter for every store the card offers", () => {
    expect(ADAPTERS.map((adapter) => adapter.name)).toHaveLength(
      STORE_IDS.length,
    );
  });

  it.each(ADAPTERS)("reads every member $library declares", (adapter) => {
    // The instrument first: an adapter whose body or whose interface came back
    // empty would satisfy the subset below without observing anything.
    expect(adapter.declared.length).toBeGreaterThan(0);
    expect(adapter.reads.size).toBeGreaterThan(0);

    expect(
      adapter.declared.filter((member) => !adapter.reads.has(member)),
      `${adapter.library} declares this and ${adapter.name} never reads it: ` +
        "give the member a consumer at the seam, or take it out of the reader",
    ).toEqual([]);
  });
});
