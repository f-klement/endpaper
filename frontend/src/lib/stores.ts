/**
 * Which stores a member can import from, as data.
 *
 * **A store is a row, not a branch**, which is `lib/fileReaders.ts`'s answer to
 * the same question on the scan path and `backend/targets.py`'s on the
 * catalogue path. The reason is the same in all three: two tickets adding a
 * source at once must not be two tickets editing one expression. Here each
 * store is a key.
 *
 * **A store is one row plus its reader**, and the row's `open` is where the
 * store's own record becomes the common one. That adaptation cannot be shared:
 * a Kobo answers `KoboBook` and a Takeout answers `TakeoutBook`, and nothing
 * short of rewriting both readers would make them one type. So `open` is a few
 * lines per store, and everything else a member meets, the name, the sentence,
 * what file to pick and what has not been tested, is a field.
 *
 * ## What a reader still owes, and what this does not change
 *
 * `KoboReading` and `TakeoutReading` already have the shape this needs: an
 * answer, never a throw. Nothing here widens that contract. What this adds is
 * the second half of it, which no reader could state for itself: **an
 * unreadable store is one skipped source, never a broken import.** A member
 * picking two stores where one moved keeps the other, and `StoreFailure` is
 * what lets the card name the one that was lost.
 *
 * **The union overlaps and that is the point**, `fileReaders.FileFailure`'s
 * rule. `damaged` and `too-large` mean the same thing to a member whichever
 * reader said them, so they are one name each rather than one per store, and
 * `STORE_FAILURES` in the card is a total `Record` over the union: a reader
 * that grows a reason with no sentence for a member is a compile error rather
 * than a source reported with the last arm's words.
 *
 * ## Nothing here speaks the API's vocabulary
 *
 * **A store's record is not a request**, which is `lib/calibre.ts`'s
 * arrangement: what a reader produced becomes what a request carries in
 * `LibrarySettingsPage/types.ts`, and that is where `StoreFormat` is mapped to
 * the enum the endpoint takes. Keeping this module off `api/` is also what
 * `tests/houseRules.test.ts` requires of every reader in this directory, and it
 * refuses the import rather than the request: a module that cannot name the
 * client cannot grow a call to it by accident.
 *
 * ## Nothing is uploaded
 *
 * Every opener below reads the file in the browser and hands the page records.
 * That is not this module's discipline: the readers hold the only copy of a
 * member's bytes and `tests/houseRules.test.ts` denies every module in this
 * directory the network, this one included.
 *
 * ## A row carries no filename, and that is the load bearing absence
 *
 * **Which store a picked file belongs to is decided by the opener, from the
 * bytes, and never by matching a name here.** `calibre.ts` and `kobo.ts` each
 * export a `DATABASE_FILENAME` and neither is a signature: `kobo.ts` says in as
 * many words that what makes a device a Kobo is a `content` table carrying
 * `ContentID` and `BookID`, and `takeout.ts` refuses to key on an extension
 * Google gets wrong.
 *
 * A field on the row holding "the file this store keeps" would be a constant
 * that some store cannot supply, and a store whose file is a family rather than
 * a name would then need this shape reopened rather than a row added. `accept`
 * is the only thing here that mentions a name and it is advice to the file
 * dialog, stated at its own site; `tests/lib/stores.test.ts` feeds each opener
 * the other store's file to hold that apart.
 *
 * ## The next store
 *
 * **A new store is one row here plus its own opener**, in the shape of the two
 * below, and nothing else in this module or in the card changes for it: a new
 * failure name widens `StoreFailure` and the card's total `Record` fails to
 * compile until it has a sentence for a member.
 */

import type { MessageKey } from "../i18n/en";
import type { AppleBooksFailure, AppleBooksLibrary } from "./appleBooks";
import type { KindleFailure, KindleLibrary } from "./kindle";
import type { KoboFailure, KoboLibrary } from "./kobo";
import type { SqliteFailure } from "./sqlite";
import type { TakeoutFailure, TakeoutLibrary } from "./takeout";

/**
 * What kind of copy a store says a book is.
 *
 * **This app's vocabulary, narrowed to what a store can hold.** A store's shelf
 * is files, so the two physical members of the endpoint's own enum cannot
 * appear and `other` would say nothing. `LibrarySettingsPage/types.ts` holds a
 * total `Record` over this, so a kind added here without a home there is a
 * compile error rather than a book filed as nothing.
 */
export type StoreFormat = "ebook" | "audiobook" | "comic";

/**
 * One book a store says this member has, whichever store said it.
 *
 * **Not one store's record**, `fileReaders.FileMetadata`'s rule and for its
 * reason: what a field holds is decided by what this app stores rather than by
 * what any vendor spells, so a third store fills these in rather than adding
 * to them. Every field but `key` goes into a `BookCreate` one line each, in
 * `LibrarySettingsPage/types.ts`.
 *
 * **A field the store did not carry is `null` and never `""`.** A caller
 * reading `book.title` to decide whether the store named one would take an
 * empty string for a title.
 */
export interface StoreBook {
  /**
   * What the store calls this book, unique within the one source.
   *
   * Not shown and not written: it exists so that two rows of one import can be
   * told apart when they carry the same title, which on a device holding two
   * editions of a book is ordinary. Unique within a source rather than across
   * them, because two stores number their own shelves.
   */
  readonly key: string;
  readonly title: string | null;
  /**
   * Separate values, in the order the store gave them.
   *
   * **Never split out of one string here.** A store that carries its authors
   * as one line is read as one author: the separator is undocumented in every
   * store this has met, and a wrong guess turns one person into two.
   */
  readonly authors: readonly string[];
  readonly isbn: string | null;
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly description: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
  /** What kind of copy this is, or `null` where the store does not say. */
  readonly format: StoreFormat | null;
}

/**
 * What one source turned out to hold.
 *
 * Three numbers rather than one, because they are three different sentences to
 * the person holding the file. A store carrying two hundred adverts and no
 * books has plenty on it and none of it theirs; an export whose every file was
 * refused named the books and could not open them. `kobo.ts` and `takeout.ts`
 * each draw that distinction for themselves and this is where it survives.
 */
export interface StoreLibrary {
  readonly books: readonly StoreBook[];
  /** Rows the store held that were not a book this member has. */
  readonly skipped: number;
  /** Books the store named and its reader could not open. */
  readonly refused: number;
}

/**
 * Why a picked file yielded no library.
 *
 * The union of every store's reasons, and the overlaps are deliberate: see the
 * module docstring. Widened by a reader growing a reason, never by a store
 * being added on its own.
 */
export type StoreFailure =
  | SqliteFailure
  | KoboFailure
  | TakeoutFailure
  | AppleBooksFailure
  | KindleFailure;

export type StoreReading =
  | { readonly ok: true; readonly library: StoreLibrary }
  | { readonly ok: false; readonly failure: StoreFailure };

/**
 * What a row's `open` is.
 *
 * **It never throws for anything the file did**, which is the contract its
 * readers already keep and the whole of why one bad file costs one source. A
 * throw here is a bug in this module, and the hook reports it as one.
 */
export type StoreReader = (file: File) => Promise<StoreReading>;

/** One store, as a member meets it. */
export interface Store {
  /** What it is called where a member reads it. */
  readonly name: MessageKey;
  /** What it is, in one sentence, including which file to go and find. */
  readonly explain: MessageKey;
  /** The picker's label, which names the file. */
  readonly choose: MessageKey;
  /**
   * The picker's `accept`.
   *
   * Advice to the file dialog and nothing else: the reader decides what the
   * file is from its bytes, so a member who renamed theirs can still pick it
   * through the dialog's own "all files".
   */
  readonly accept: string;
  /**
   * What this row claims that has not been tested, or `null` where there is
   * nothing to say.
   *
   * **A field rather than a paragraph in one card**, so the next store that
   * supports a device nobody here owns states its bound in the same place and
   * in the same words. A claim with no bound is the failure this field exists
   * to make hard: it turns an inference into a promise.
   */
  readonly caveat: MessageKey | null;
  /** Loads the reader on demand and answers in the common shape. */
  readonly open: StoreReader;
}

/**
 * The stores, in the order a member sees them.
 *
 * **Each opener imports its own reader**, so a session that never opens this
 * card downloads none of them, and a member with one store does not pay for
 * the other's engine. `sqlite.ts` is a third of a megabyte of WebAssembly and
 * is reached only from inside `kobo.open`.
 */
export const STORES = {
  kobo: {
    name: "stores.kobo.name",
    explain: "stores.kobo.explain",
    choose: "stores.kobo.choose",
    accept: ".sqlite,.db,application/vnd.sqlite3,application/x-sqlite3",
    caveat: "stores.kobo.tolino",
    open: openKobo,
  },
  playBooks: {
    name: "stores.playBooks.name",
    explain: "stores.playBooks.explain",
    choose: "stores.playBooks.choose",
    accept: ".zip,application/zip",
    caveat: null,
    open: openPlayBooks,
  },
  appleBooks: {
    name: "stores.appleBooks.name",
    explain: "stores.appleBooks.explain",
    choose: "stores.appleBooks.choose",
    accept: ".sqlite,application/vnd.sqlite3,application/x-sqlite3",
    // **The sidecar, not the device.** A member who copies the database and
    // leaves its `-wal` behind gets a store that reads as empty: measured at 0
    // rows from the file alone against 3 with it. That is a copy taken wrong
    // rather than a library that is bare, and only the member can fix it, so it
    // is said where the copy is made.
    caveat: "stores.appleBooks.sidecar",
    open: openAppleBooks,
  },
  kindle: {
    name: "stores.kindle.name",
    explain: "stores.kindle.explain",
    choose: "stores.kindle.choose",
    accept: ".xml,text/xml,application/xml",
    // Windows writes this catalogue and the current Kindle for Mac does not
    // write it at all, so a Mac owner picking this row has nothing to pick.
    // Measured by the trio that built the reader; `kindle.ts` carries it.
    caveat: "stores.kindle.windowsOnly",
    open: openKindle,
  },
} satisfies Record<string, Store>;

export type StoreId = keyof typeof STORES;

/**
 * The ids, in the order above.
 *
 * Derived rather than listed, so a row added to `STORES` is offered without a
 * second edit. A list here would go stale in the direction where a store ships
 * and no member is shown it, which is the failure this whole ticket is.
 */
export const STORE_IDS = Object.keys(STORES) as readonly StoreId[];

/**
 * A Kobo device's library, off the file it keeps below `.kobo/`.
 *
 * The engine is opened, read and closed here rather than handed out: it holds
 * the whole file in WebAssembly memory until it is told not to, and the
 * `finally` covers the failure paths as well as the good one.
 */
async function openKobo(file: File): Promise<StoreReading> {
  const [{ openSqliteFile }, { readKoboLibrary }] = await Promise.all([
    import("./sqlite"),
    import("./kobo"),
  ]);
  const opened = await openSqliteFile(file);
  if (!opened.ok) return { ok: false, failure: opened.failure };
  try {
    const read = readKoboLibrary(opened.database);
    if (!read.ok) return { ok: false, failure: read.failure };
    return { ok: true, library: fromKobo(read.library) };
  } finally {
    opened.database.close();
  }
}

function fromKobo(library: KoboLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: book.contentId,
      title: book.title,
      authors: book.authors,
      isbn: book.isbn,
      publisher: book.publisher,
      year: book.year,
      language: book.language,
      // A Kobo keeps none: `kobo.ts` lists what the device cannot supply.
      description: null,
      seriesName: book.seriesName,
      seriesIndex: book.seriesIndex,
      // **`null` where `MimeType` settled nothing**, rather than `ebook` for
      // everything on the device. Every format a Kobo does settle is a book to
      // read, so the mapping itself is not the question; asserting a kind for
      // a row that named none would be answering for the device.
      format: book.format === null ? null : "ebook",
    })),
    skipped: library.skipped,
    // A Kobo row is read or it is not one. Nothing is named and unopenable.
    refused: 0,
  };
}

/** The Play Books library inside a Google Takeout archive. */
async function openPlayBooks(file: File): Promise<StoreReading> {
  const { readTakeoutArchive } = await import("./takeout");
  const read = await readTakeoutArchive(file);
  if (!read.ok) return { ok: false, failure: read.failure };
  return { ok: true, library: fromTakeout(read.library) };
}

/**
 * A Takeout book is two records, and which one wins is decided per field.
 *
 * **The sidecar is Google's own index and is primary**, which is the rule the
 * Calibre import already keeps: the store's index leads and the file fills what
 * it left empty. `takeout.ts` says the sidecar's heading is Google's title, and
 * it carries one for every pair, where the EPUB beside it may not.
 *
 * **Authors are the exception, and structure is the reason.** The sidecar's
 * author line is one string and the EPUB carries `dc:creator` separately, so
 * preferring the sidecar would throw away a division the file already made and
 * leave every later reader to guess it back from a separator Google does not
 * document. So the EPUB's list wins wherever it has one.
 */
function fromTakeout(library: TakeoutLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: book.path,
      title: book.title ?? book.metadata.title,
      authors:
        book.metadata.authors.length > 0
          ? book.metadata.authors
          : book.author === null
            ? []
            : [book.author],
      isbn: book.metadata.isbn,
      publisher: book.metadata.publisher,
      year: book.metadata.year,
      language: book.metadata.language,
      description: book.metadata.description,
      seriesName: book.metadata.seriesName,
      seriesIndex: book.metadata.seriesIndex,
      // Every pair that got this far is one whose sibling read as an EPUB, so
      // this is what the archive held rather than what its folder is called.
      format: "ebook",
    })),
    skipped: library.skipped,
    refused: library.refused.length,
  };
}

/**
 * An Apple Books library, off the Core Data store on a member's own Mac.
 *
 * The engine is opened, read and closed here, `openKobo`'s rule and its reason.
 */
async function openAppleBooks(file: File): Promise<StoreReading> {
  const [{ openSqliteFile }, { readAppleBooksLibrary }] = await Promise.all([
    import("./sqlite"),
    import("./appleBooks"),
  ]);
  const opened = await openSqliteFile(file);
  if (!opened.ok) return { ok: false, failure: opened.failure };
  try {
    const read = readAppleBooksLibrary(opened.database);
    if (!read.ok) return { ok: false, failure: read.failure };
    return { ok: true, library: fromAppleBooks(read.library) };
  } finally {
    opened.database.close();
  }
}

function fromAppleBooks(library: AppleBooksLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: book.assetId,
      title: book.title,
      authors: book.authors,
      isbn: book.isbn,
      // **Three fields an Apple Books library does not answer**, and `null` here
      // rather than a guess: `appleBooks.ts` lists what the store cannot supply.
      // The description is the one it holds and this does not take, because the
      // column is HTML and the only cleaner is inside `calibre.ts`.
      publisher: null,
      description: null,
      year: book.year,
      language: book.language,
      seriesName: null,
      seriesIndex: null,
      // Every format this store settles is a book to read, `fromKobo`'s rule.
      format: book.format === null ? null : "ebook",
    })),
    skipped: library.skipped,
    // A row is read or it is not one. Nothing is named and unopenable.
    refused: 0,
  };
}

/** A Kindle for PC library, off the XML catalogue the app keeps. */
async function openKindle(file: File): Promise<StoreReading> {
  const { readKindleCacheFile } = await import("./kindle");
  const read = await readKindleCacheFile(file);
  if (!read.ok) return { ok: false, failure: read.failure };
  return { ok: true, library: fromKindle(read.library) };
}

/**
 * **The ASIN becomes the key and is then dropped, and that is worth saying
 * here** rather than only in the reader that found it.
 *
 * This route was preferred over the Amazon account export because the export
 * carried neither an ASIN nor an ISBN and this catalogue carries an ASIN on
 * every entry. It still does. But `BookCreate` has one identifier field and it
 * is `isbn`, so nothing this app stores can hold an ASIN, and `key` is not
 * written. So the identifier that decided the route survives the read and not
 * the import: what a member keeps is the title, the authors, the publisher and
 * the year. The gap is a ticket rather than a thing to fix by putting an ASIN
 * in a field named for an ISBN, which would make every ISBN lookup wrong.
 */
function fromKindle(library: KindleLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: book.asin,
      title: book.title,
      authors: book.authors,
      // The catalogue has no element for one: `kindle.ts` measured 0 of 1,032.
      isbn: null,
      publisher: book.publisher,
      year: book.year,
      language: null,
      description: null,
      seriesName: null,
      seriesIndex: null,
      // Every row this reader keeps is a book. `kindle.ts` skips the rest.
      format: "ebook",
    })),
    skipped: library.skipped,
    refused: 0,
  };
}
