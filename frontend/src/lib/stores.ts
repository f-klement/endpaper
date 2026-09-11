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
 *
 * **Its adapter answers `ownership` too**, and `null` is a real answer rather
 * than a gap: it says the store draws no line between its rows, so the read's
 * own `ownershipStated` speaks for all of them. Answer it per row only where
 * the store records the difference, which of the six below is Kobo alone.
 *
 * **And it answers `identifiers`**, where `[]` is a real answer for the same
 * reason: it says the store's rows carry the store's own device reference and
 * nothing another system could resolve, which is what four of the six below say
 * and why. A store whose identifier has no scheme yet needs one added to
 * `StoreIdentifierScheme`, to `enums.BookIdentifierScheme` and to a migration,
 * because the endpoint refuses a scheme it does not know.
 */

import type { MessageKey } from "../i18n/en";
import type { AppleBooksFailure, AppleBooksLibrary } from "./appleBooks";
import type {
  DigitalEditionsFailure,
  DigitalEditionsLibrary,
} from "./adobeDigitalEditions";
import type { MoonReaderFailure, MoonReaderLibrary } from "./moonReader";
import type { KindleFailure, KindleLibrary } from "./kindle";
import type { KoboAcquisition, KoboFailure, KoboLibrary } from "./kobo";
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
 * What a store said about this member's claim on one book.
 *
 * **Two of `books.ownership`'s three members and not the third.** A store lists
 * what the account holds, so `not_owned` is a thing a member says about a book
 * and never a thing a catalogue says: the wishlist is the route that writes it.
 * `unknown` is the endpoint's word for a source that could not answer, which is
 * what a subscription title and a public library loan both are.
 */
export type StoreOwnership = "owned" | "unknown";

/**
 * Who is naming a book, where that name is not an ISBN.
 *
 * **The closed half of `fileReaders.FileIdentifier`**, which is the same two
 * fields with `scheme` typed `string | null` because an EPUB labels its own
 * identifiers and `opf.ts` reads whatever the file said. Nothing here is read
 * off a file: a store's format carries the identifier in a field whose name
 * already says what it is, so the adapter below labels it, and a label an
 * adapter chose can be a closed union rather than free text.
 *
 * **A union rather than the endpoint's enum**, because
 * `tests/houseRules.test.ts` denies every reader in this directory the
 * generated client. `LibrarySettingsPage/types.ts` holds a total `Record` over
 * this, so a scheme added here without a home there is a compile error rather
 * than a value the endpoint's enum does not have, answered with a 422 in the
 * middle of somebody's import.
 */
export type StoreIdentifierScheme = "asin" | "google_books";

/** One identifier a store gave a book, with what the adapter says it is. */
export interface StoreIdentifier {
  readonly scheme: StoreIdentifierScheme;
  readonly value: string;
}

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
  /**
   * What the store's own catalogue calls this book, where that is not an ISBN.
   *
   * **A list and never one value**, `fileReaders.FileMetadata.identifiers`'
   * shape and for a reason this side has too: a store carrying two is a store
   * this app should keep two of, and a single field would make the adapter
   * choose one silently. Empty is the ordinary answer for a store whose row
   * carries only its own device reference.
   *
   * **Distinct from `key` above, and the two were conflated in the ticket that
   * asked for this.** `key` tells two rows of one import apart and is whatever
   * is unique within that source: for the Kindle catalogue that happens to be
   * the ASIN and for a Takeout it is the path inside the archive, not the
   * volume id. So reading `key` would have kept one store's identifier and one
   * store's file path under one name.
   */
  readonly identifiers: readonly StoreIdentifier[];
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly description: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
  /** What kind of copy this is, or `null` where the store does not say. */
  readonly format: StoreFormat | null;
  /**
   * What the store said about this row, or `null` where it said nothing per
   * row and `StoreLibrary.ownershipStated` is the answer for all of them.
   *
   * **A row and not a library, because that is where the fact is.** A Kobo
   * holds a purchase, a Kobo Plus title and an OverDrive loan in one `content`
   * table and records which on every row, so one boolean for the read can only
   * be wrong about some of them: it said owned, and a three week public library
   * book went onto a shelf as something the member has.
   *
   * **`null` is a real answer and not a gap**, `identifiers`' empty list rule.
   * It says this store's catalogue draws no distinction between its rows, which
   * is true of every store here but Kobo, so the one thing the read can say
   * about ownership is the thing it says about all of them at once.
   *
   * **This is what the import reads first.** `LibrarySettingsPage/types.ts`
   * takes the row's answer where there is one and falls back to
   * `ownershipStated` below where there is not, because the row's answer is the
   * narrower claim: a library wide `true` over a measured `unknown` would put a
   * guess where a measurement was.
   */
  readonly ownership: StoreOwnership | null;
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
  /**
   * What this store said about owning the books it listed, for the rows that
   * said nothing themselves.
   *
   * **Written as the fallback under `StoreBook.ownership`, and still the only
   * thing the import reads.** `LibrarySettingsPage/types.ts::storeToBookCreate`
   * takes this flag and every book of the read on it, and consults no per row
   * answer, so a Kobo OverDrive loan arrives as a book the member owns. That is
   * the defect `StoreBook.ownership` was added to settle and the half of it
   * this module could reach: the wiring is one expression in a file this work
   * did not own, and the issue carries it.
   *
   * A store whose catalogue records nothing per row has one answer for the
   * whole read and this is it. Kobo is the only store here that records it per
   * row.
   *
   * **`false` means the import sends `ownership: unknown`**, which is a value
   * `books.ownership` has had since the Goodreads import needed it. Without
   * this flag every store import wrote `owned`, so wiring that store would have
   * told a member they own a book they have for three weeks.
   *
   * Every store here says `true` except Adobe Digital Editions, which is a
   * fulfilment client for public library loans as much as for purchases and
   * **records a three week loan and a purchase identically**: the loan is a
   * token travelling with the book file, which is the protection on it and is
   * not something this app opens. `adobeDigitalEditions.ts` carries the sources.
   *
   * **`true` still means the store judged ownership rather than that every row
   * is a purchase**, and `kindle.ts` is the case left. It keeps a Kindle
   * Unlimited or Prime title for a stated reason: `<origins><origin><type>` is
   * the only element in that format that could tell one from a purchase, and it
   * is in neither published capture the reader was built from, so an arm
   * reading it could not be shown to fire. So `fromKindle` leaves
   * `StoreBook.ownership` unset and this flag is what its books are imported
   * on, which is the same imprecision stated where somebody wiring it reads it.
   */
  readonly ownershipStated: boolean;
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
  | KindleFailure
  | DigitalEditionsFailure
  | MoonReaderFailure;

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
  adobe: {
    name: "stores.adobe.name",
    explain: "stores.adobe.explain",
    choose: "stores.adobe.choose",
    accept: ".xml,text/xml,application/xml",
    // **Two bounds in one sentence, and the first is the one a member meets.**
    // Since 2.0 the catalogue is one XML file per book, and this picker takes
    // one file, so a modern install imports one book per pick. The second is
    // the ownership bound: this store cannot say whether a title was bought or
    // borrowed, so everything from it arrives as unknown rather than owned.
    caveat: "stores.adobe.oneBook",
    open: openDigitalEditions,
  },
  moonReader: {
    name: "stores.moonReader.name",
    explain: "stores.moonReader.explain",
    choose: "stores.moonReader.choose",
    // The app's own backup extensions, not `.zip`: a backup is a zip and is
    // never named one, so offering `.zip` would show a member an empty dialog.
    accept: ".mrpro,.mrstd",
    caveat: null,
    open: openMoonReader,
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
      // **None, and `contentId` is not one.** `kobo.ts` says that column holds
      // a store UUID for a purchase and a `file:///mnt/onboard/...` URL for a
      // sideloaded file, and nothing on the row says which. So it identifies
      // the book on **that device**, which is what `key` above is for, and
      // labelling it with a scheme would assert a store where half the rows
      // have none.
      identifiers: [],
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
      ownership: KOBO_OWNERSHIP[book.acquisition],
    })),
    skipped: library.skipped,
    // A Kobo row is read or it is not one. Nothing is named and unopenable.
    refused: 0,
    // Every row above answered for itself, and this is nonetheless what the
    // import takes all of them on: see `ownershipStated`. `true` is what keeps
    // a purchase importing as owned until that is wired.
    ownershipStated: true,
  };
}

/**
 * What each thing a Kobo records amounts to on a shelf.
 *
 * **The judgement is here and the fact is in the reader**, which is the seam
 * `StoreBook.ownership` describes: `kobo.ts` says a row is a Kobo Plus title
 * and this says what a Kobo Plus title is worth as a claim on a book. A member
 * reads for as long as they subscribe and loses it when they stop, and an
 * OverDrive title is a public library's book for three weeks, so neither is
 * theirs and `unknown` is the whole of what a catalogue establishes.
 *
 * **A total `Record` and not a lookup with a default.** A value added to
 * `KoboAcquisition` and not given a home here is a compile error, where a
 * default would silently file Kobo's next arrangement as a purchase, which is
 * the direction that puts a book nobody bought on somebody's shelf.
 *
 * **`unrecorded` is `unknown`**, because it is a device older than schema
 * version 16, which has no `Accessibility` column: it cannot say that a row is
 * an advert and cannot say that it is a purchase either. Reading the second out
 * of the first is the guess this app has a word for not making.
 *
 * **`sideloaded` is `owned` and that is the entry that concedes something.** It
 * is a file the member put on the device, which is usually theirs and is also
 * where a public library loan lands when it arrives as a file.
 *
 * **The route decides that and not the lender.** `9` is what Kobo records for
 * a title borrowed through the integration on the device; a loan fulfilled
 * through Adobe and transferred to the device is a file the member copied, and
 * lands here. That is how a library outside the integration works, and it is
 * how OverDrive itself works when the member transfers the title with Adobe
 * Digital Editions, so the same lender reaches this reader by both routes.
 * `adobeDigitalEditions.ts` is why the second cannot be separated from a
 * purchase, and that is a fact about its catalogue rather than about this one:
 * it records a three week loan and a purchase identically.
 *
 * The concession is deliberate, because answering `unknown` sends every
 * sideloaded book on every device to be reviewed to catch the ones that are
 * loans, and nothing on the row separates them.
 *
 * **`unrecorded` costs the same and more of it**, every book on such a device
 * rather than some of them, and is answered the other way because the two are
 * different kinds of thing: `sideloaded` is something the device recorded and
 * `unrecorded` is the absence of any record at all. Declining to read a fact
 * that is there is a judgement about the fact; declining to invent one that is
 * not there is the only thing available.
 */
const KOBO_OWNERSHIP: Record<KoboAcquisition, StoreOwnership> = {
  purchase: "owned",
  sideloaded: "owned",
  subscription: "unknown",
  loan: "unknown",
  unrecorded: "unknown",
};

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
      // **The volume id, which is not the key.** `key` is the path inside the
      // archive, because two folders may hold two editions of one title and
      // that is what tells the rows apart; the volume id is what Google calls
      // the book, and `takeout.ts` measured it as the only identifier the
      // archive carries. Every pair that gets this far has one: a sidecar with
      // no volume id is not a Play Books book and is counted as skipped.
      identifiers: [{ scheme: "google_books", value: book.volumeId }],
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
      // The archive is a list of what the account holds and draws no line
      // through it, so the answer is the read's and not this row's.
      ownership: null,
    })),
    skipped: library.skipped,
    refused: library.refused.length,
    ownershipStated: true,
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
      // **None, and `assetId` is not one**, `fromKobo`'s rule for the same
      // shape of column. `appleBooks.ts` says that value is the library's own
      // reference and that Apple's store id is a separate column this reader
      // does not read, so the store's own name for the book is not in hand.
      identifiers: [],
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
      // `appleBooks.ts` reads no column separating a purchase from anything
      // else, so the answer is the read's and not this row's.
      ownership: null,
    })),
    skipped: library.skipped,
    // A row is read or it is not one. Nothing is named and unopenable.
    refused: 0,
    ownershipStated: true,
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
 * A Kindle for PC library, where the ASIN is the identifier and not the ISBN.
 *
 * This route was preferred over the Amazon account export because the export
 * carried neither an ASIN nor an ISBN and this catalogue carries an ASIN on
 * every entry, 1,032 of 1,032. It goes into `identifiers` and never into
 * `isbn`: that field is the importer's match key and every path into it check
 * digits its input, so an ASIN written there would match nothing and would take
 * the deduplication down with it for the rows that do carry one.
 */
function fromKindle(library: KindleLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: book.asin,
      title: book.title,
      authors: book.authors,
      // The catalogue has no element for one: `kindle.ts` measured 0 of 1,032.
      isbn: null,
      // The ASIN, which every entry carries and which is why this route was
      // preferred over the account export. It is `key` as well, and that is a
      // coincidence of this catalogue rather than the two being one field: see
      // `StoreBook.identifiers`.
      identifiers: [{ scheme: "asin", value: book.asin }],
      publisher: book.publisher,
      year: book.year,
      language: null,
      description: null,
      seriesName: null,
      seriesIndex: null,
      // Every row this reader keeps is a book. `kindle.ts` skips the rest.
      format: "ebook",
      // **The one store that could answer here and does not.** `<origins>` is
      // the element that would, and `StoreLibrary.ownershipStated` carries why
      // `kindle.ts` does not read it and what that costs.
      ownership: null,
    })),
    skipped: library.skipped,
    refused: 0,
    ownershipStated: true,
  };
}

/** An Adobe Digital Editions catalogue, which is XML and loads no engine. */
async function openDigitalEditions(file: File): Promise<StoreReading> {
  const { readDigitalEditionsCatalogueFile } =
    await import("./adobeDigitalEditions");
  const read = await readDigitalEditionsCatalogueFile(file);
  if (!read.ok) return { ok: false, failure: read.failure };
  return { ok: true, library: fromDigitalEditions(read.library) };
}

/**
 * **The one store whose books arrive as `unknown` rather than owned**, and the
 * flag rather than a literal here so the reader stays the thing that decides.
 */
function fromDigitalEditions(library: DigitalEditionsLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: String(book.record),
      title: book.title,
      authors: book.authors,
      // `dc:identifier` is opaque and its scheme is not published, so it is
      // never read as an ISBN. It reaches `identifiers` with no scheme to name
      // it, which is a member `StoreIdentifierScheme` does not have, so it is
      // carried no further than the read. Ticketed, not dropped silently.
      isbn: null,
      identifiers: [],
      publisher: book.publisher,
      year: null,
      language: null,
      description: null,
      seriesName: null,
      seriesIndex: null,
      format: "ebook",
      // Nothing on a record tells one from another, which is the finding this
      // reader exists to state, so the answer is the read's for all of them.
      ownership: null,
    })),
    skipped: library.skipped,
    refused: 0,
    // The catalogue records a three week loan and a purchase identically.
    ownershipStated: library.ownershipStated,
  };
}

/**
 * A Moon+ Reader library, out of the backup the app itself writes.
 *
 * **Two stages, and neither is optional.** The backup is a zip whose every
 * entry has been renamed to its line number in `_names.list`, so the database
 * cannot be found by name: the index is read first and it says which entry the
 * database became. `moonReader.ts` owns both steps and this only sequences them.
 */
async function openMoonReader(file: File): Promise<StoreReading> {
  const [{ openZip }, { openSqliteFile }, moon] = await Promise.all([
    import("./zip"),
    import("./sqlite"),
    import("./moonReader"),
  ]);
  const archive = await openZip(file);
  const namesEntry = moon.namesEntryIn(archive.entries);
  if (namesEntry === null)
    return { ok: false, failure: "not-a-moon-reader-backup" };
  const names = archive.find(namesEntry);
  if (names === undefined)
    return { ok: false, failure: "not-a-moon-reader-backup" };
  const tag = moon.databaseTagName(
    namesEntry,
    new TextDecoder().decode(await archive.read(names, MOON_INDEX_LIMIT)),
  );
  if (tag === null) return { ok: false, failure: "not-a-moon-reader-backup" };
  const entry = archive.find(tag);
  if (entry === undefined)
    return { ok: false, failure: "not-a-moon-reader-backup" };
  const opened = await openSqliteFile(
    new File([await archive.read(entry, MOON_DATABASE_LIMIT)], tag),
  );
  if (!opened.ok) return { ok: false, failure: opened.failure };
  try {
    const read = moon.readMoonReaderLibrary(opened.database);
    if (!read.ok) return { ok: false, failure: read.failure };
    return { ok: true, library: fromMoonReader(read.library) };
  } finally {
    opened.database.close();
  }
}

/**
 * What one entry of a Moon+ backup may inflate to.
 *
 * **The seam has no opinion about what an entry is for**, which is why `read`
 * takes a limit from its caller. The index is a line per file and the database
 * is a catalogue: neither is a book, so both are bounded well below the engine's
 * own ceiling rather than at it.
 */
const MOON_INDEX_LIMIT = 4 * 1024 * 1024;
const MOON_DATABASE_LIMIT = 64 * 1024 * 1024;

function fromMoonReader(library: MoonReaderLibrary): StoreLibrary {
  return {
    books: library.books.map((book) => ({
      key: book.path,
      title: book.title,
      authors: book.authors,
      // Neither published reading of this database has a column for any of
      // these. `moonReader.ts` lists what the app does not record.
      isbn: null,
      identifiers: [],
      publisher: null,
      year: null,
      language: null,
      description: null,
      seriesName: null,
      seriesIndex: null,
      // **The first store whose format is not collapsed to `ebook`.** Moon+
      // holds files the member put there, so the extension is evidence the way
      // `fileName.FORMAT_FOR_EXTENSION` treats it, and the reader has already
      // narrowed it to what a filename can mean.
      format: book.format,
      // A backup lists files and says nothing about any of them, so the answer
      // is the read's and not this row's.
      ownership: null,
    })),
    skipped: library.skipped,
    refused: 0,
    // A file on the member's own device, put there by them.
    ownershipStated: true,
  };
}
