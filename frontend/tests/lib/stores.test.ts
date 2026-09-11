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
import { STORES, STORE_IDS, type StoreReading } from "../../src/lib/stores";
import { A_VOLUME_ID, bookEntries, LIBRARY_FOLDER } from "./takeoutFixtures";
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
  async function takeoutFile(entries: Awaited<ReturnType<typeof bookEntries>>) {
    return new File([await buildZip({ entries })], "takeout.zip");
  }

  it("takes the title from the store's own index", async () => {
    // The sidecar is Google's index, and the Calibre import already keeps this
    // rule: the index leads and the file fills what it left empty.
    const library = libraryIn(
      await STORES.playBooks.open(
        await takeoutFile(
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
        await takeoutFile(
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
        await takeoutFile(
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
      await STORES.playBooks.open(await takeoutFile([...good, ...broken])),
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
