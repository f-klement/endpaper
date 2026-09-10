/**
 * What a Kindle desktop app says about the books in somebody's library.
 *
 * **Not an integration with a company.** The app keeps a catalogue of the
 * account's library beside the downloaded files, so this reads a file the
 * member already has on a machine they own. Nothing here talks to Amazon,
 * nothing here opens a book, and nothing here touches the protection on one: it
 * reads catalogue metadata about what somebody owns.
 *
 * **The line, because this is the store where it is easiest to cross.** The
 * downloaded book beside this catalogue is protected. None of that is read,
 * named or looked for. Had the metadata only been reachable that way, the
 * answer would have been that this store is not importable and the ticket would
 * have closed saying so. It is reachable without going near it, which is why
 * there is a reader at all.
 *
 * Pure, in `kobo.ts`'s shape: it takes the document and returns records. What
 * it does not take is a connection, an engine or a network, and **it needs no
 * SQLite**: the catalogue that carries the metadata is XML, so this store costs
 * a reader and not the engine `docs/device-libraries.md` measured for the last
 * one.
 *
 * ## Which app, because one of the two stopped writing this file
 *
 * **Windows writes it and never stopped.** The desktop installer keeps it under
 * `%LOCALAPPDATA%\Amazon\Kindle\Cache\`, on the 1.x line and the 2.x line
 * alike, and the Microsoft Store app keeps it under
 * `%LOCALAPPDATA%\Packages\<the package directory>\LocalState\Classic\Data\Cache\`.
 *
 * **macOS stopped.** Kindle Classic, 1.40.1 or earlier, kept it under
 * `~/Library/Application Support/Kindle/Cache/`, and under
 * `~/Library/Containers/com.amazon.Kindle/Data/Library/` for the sandboxed copy
 * from the App Store. The app that replaced it keeps a SQLite database instead
 * and writes no such file, so **a Mac running anything current has no library
 * for this reader to read**. That is a fact about the store rather than about
 * this module, and it is stated here because it is the first thing somebody
 * will test this against.
 *
 * **The file is written when the app quits**, so a copy taken while it is
 * running can be missing whatever was bought since it started.
 *
 * ## Which file, because the app writes two and only one names a book
 *
 * `KindleSyncMetadataCache.xml` is the library: one entry per title, carrying
 * the identifier, the title, the authors, the publisher and the publication
 * date.
 *
 * `book_asset.db` sits beside it and is **not** a library. It is SQLite, which
 * makes it the file this repository's existing engine would reach for first,
 * and reading it would have been the obvious mistake: its `Book` table is
 * `(id, asin, type, revision, sampling)` and its `Asset` table is a download
 * ledger of guids, sizes and local filenames. There is no title, no author and
 * no publisher in any of its nine tables. **Nine is the count of the tables the
 * app declared**: `sqlite_master` lists ten, the tenth being SQLite's own
 * `sqlite_sequence`. Measured against the published capture named below.
 *
 * ## The identifier, which is what this reader was written to establish
 *
 * **Every entry carries an ASIN and no entry carries an ISBN.** There is no
 * element for an ISBN in this format at all, so it is absent by construction
 * rather than usually missing. Measured over the two published captures named
 * below, 1,032 entries: 1,032 carry an ASIN, 1,032 distinct across the two,
 * every one ten characters and every one beginning `B`. None of the 1,032 is
 * shaped like an ISBN-10.
 *
 * **Every one of those 1,032 rows is a book or a sample**, so the shape above
 * is measured over `EBOK` and `EBSP` and over nothing else. A personal
 * document is the one row this reader keeps whose identifier no capture here
 * shows, and what makes that gap safe is the consequence rather than an
 * inference: an entry with no ASIN is skipped, so such a row would be counted
 * in `skipped` rather than shelved without an identifier.
 *
 * **A `B` prefixed ASIN is not an ISBN and is not read as one.** Amazon issues
 * an ISBN-10 as the ASIN of a printed edition, and a printed edition is not
 * something a Kindle app holds, so the shape that would tempt a reader into
 * calling one an ISBN is the shape this file cannot contain. Running the value
 * through `parseIsbn` would put a wrong scheme on a right looking number, which
 * is the refusal `mobi.ts` records for EXTH 113.
 *
 * ## What is deliberately not read
 *
 * - **`origins`.** `<origins><origin><type>` is in the file the current
 *   Microsoft Store app writes and in neither capture here, carrying
 *   `Purchase`, `KindleUnlimited`, `Prime`, `Sample` or `KindleDictionary`. It
 *   is the only element in this format that could tell a subscription borrow or
 *   a bundled dictionary from a purchase, **and this reader keeps all three**.
 *   `kobo.ts` keeps Kobo Plus on the same terms, so the family is consistent
 *   rather than this one being lax. It is not read because no capture here
 *   carries one, so an arm reading it could not be shown to fire.
 * - **What that costs, measured**: 12 of the 279 entries in the 2018 capture
 *   are bundled dictionaries, carrying a title of hyphens and an empty
 *   purchase date, and they import as books. The other capture is not counted
 *   here, because its publisher deleted most of its entries by hand and it is
 *   therefore no sample of what a library holds. A rule on what a title looks
 *   like would be a heuristic over a member's own data, which is why the
 *   answer is the element above rather than a guess here.
 * - **`purchase_date`.** When the member bought it is a fact about their
 *   account rather than about the book, and it is the only field here that is
 *   about them. `kobo.ts` refuses a read status on the same ground.
 * - **`content_type`.** It is the MIME type of the downloaded file and it
 *   settles nothing: 1,032 of 1,032 entries read
 *   `application/x-mobipocket-ebook`, the 2021 capture included, which is after
 *   the format the app actually ships had changed. A field whose every value is
 *   one value tells no book from another, so this reader reports no format.
 * - **`textbook_type`.** 276 of the 279 are empty and the other 3 carry three
 *   different words. Nothing this app stores has anywhere to put it.
 * - **`pronunciation`.** Both `<title>` and `<author>` carry the attribute, and
 *   all 584 occurrences in the 2018 capture are empty. It is furigana, the
 *   reading of a name rather than the name, and Japanese libraries fill it, so
 *   it is neither a second title nor a second author.
 *
 * ## What a Kindle library cannot supply, stated rather than discovered
 *
 * **No ISBN, no language, no series and no description.** The format has no
 * element for any of them, which is why none of them is a `KindleField`: a
 * field this reader could want and a document could lack is a different thing
 * from a field the format never had. A heuristic pulling a series out of a
 * title is the thing not to add, for `mobi.ts`'s reason.
 *
 * **One publisher.** `<publishers>` is a list and carried at most one member in
 * all 1,032 entries: 250 of the 2018 capture's 279 carry exactly one and 29
 * carry none. A second is not kept, because this app's record of a book has
 * one.
 *
 * **The authors are a real list, and that is the improvement over the last
 * store.** 11 of the 2018 capture's 279 entries name more than one, and 49 of
 * the 2021 capture's 753 do; the widest names 9 and 23 respectively. Kobo's
 * `Attribution` is one string and cannot express that.
 *
 * **They are written surname first**, as the file writes them, and nothing here
 * reorders or splits one. `pdf.ts` carries why: the separator that would split
 * a list is also how a single name is written surname first, so a reader
 * guessing at it files one person as two.
 *
 * ## Where the format was read, and what was not done
 *
 * Read on 2026-09-10 off two files published in public repositories, plus
 * `book_asset.db` from the first of them.
 *
 * | capture | its own `sync_time` | entries |
 * |---|---|---|
 * | `github.com/anorman68/kindleLibrary`, blob `86f318d` | `2018-08-23`, `softwareVersion:51068` | 279 |
 * | `github.com/MrMikey59/Kindle-Book-List` | `2021-12-05`, `softwareVersion:62002` | 753 |
 *
 * `book_asset.db` is blob `cd5ab9a` of the first. A captured file is a stronger
 * source than prose about one, which is why the counts above are counts.
 *
 * **Both `softwareVersion` values are 1.x builds**, three years apart, so what
 * the pair shows is a format that did not move over that span and not one that
 * survived a major version. What says it survived into the current Windows app
 * is working code against the paths above rather than a capture here.
 *
 * **The second capture appears to spell three element names with a capital
 * letter, and that is a word processor rather than the format.** Its publisher
 * says in that repository that they reformatted and truncated it by hand in
 * one; every value in it carries trailing whitespace inside its element, and
 * `add_update_list`, `authors` and `author` read capitalised, which is what
 * autocapitalisation does to the first word of a line. The same repository's
 * own field table names all three in lower case and the unprocessed 2018
 * capture spells them in lower case. So that file is evidence about the
 * vocabulary and the identifier and is not a sample of a library's composition,
 * and **this reader refuses it**, which is XML being case sensitive rather than
 * a defect here.
 *
 * **A declaration is optional.** The 2018 capture begins with a newline and
 * then `<response>`; that second repository states the file as the app saves it
 * begins `<?xml version="1.0"?>`. Both are read.
 *
 * **No machine here was read**, because there is no Windows or Mac machine
 * here. Every fixture in `tests/lib/kindle.test.ts` is constructed from the
 * vocabulary this docstring names and none is a copy of either capture, which
 * are real people's libraries: a real person's titles are not test data.
 *
 * **Two captures are two accounts**, which is the caveat to carry into every
 * count above. What they cannot show is a value some other account carries and
 * none of these 1,032 entries does, which is what `ELEMENTS` and `OWNED` below
 * are each built to survive.
 */

import { declaresEntities } from "./xmlEntities";
import { leadingYear } from "./year";

/** One book the app says this member's account holds. */
export interface KindleBook {
  /**
   * Amazon's own reference for this title, and the stable one.
   *
   * Unique in the library, unaffected by a title being edited, and the only
   * identifier this format carries. The docstring above says why it is never
   * read as an ISBN.
   *
   * **On a book it is ten characters beginning `B`, measured; on a personal
   * document it is whatever that row carries and no capture here shows one.**
   * A caller deciding what to match on should read `personal` beside this.
   */
  readonly asin: string;
  readonly title: string | null;
  /** Every `<author>`, in the document's order and in its spelling. */
  readonly authors: readonly string[];
  readonly publisher: string | null;
  readonly year: number | null;
  /**
   * A document the member sent to their own Kindle rather than bought.
   *
   * The Kindle spelling of what `kobo.ts` calls a sideloaded book, and kept for
   * the same reason: it is something they hold. `OWNED` says where the two
   * values come from and why neither capture could show one.
   */
  readonly personal: boolean;
}

/** A field no entry in this document carried. */
export type KindleField = "title" | "authors" | "publisher" | "year";

/**
 * Every field `missing` can name, so the list is one thing rather than two.
 *
 * Declared beside the type it enumerates and asserted against it: a field added
 * to `KindleField` and not here would never be reported missing, and the reader
 * would say a document supplied something it had never looked for.
 * `tests/lib/kindle.test.ts` recomputes the pair rather than restating either.
 */
const FIELDS: readonly KindleField[] = [
  "title",
  "authors",
  "publisher",
  "year",
];

/** Why a document yielded no library. Closed, one sentence each on screen. */
export type KindleFailure =
  /** Not this catalogue: unparseable, or XML that is something else. */
  | "not-a-kindle-library"
  /** This catalogue, with no entries in it at all. */
  | "empty"
  /** Past `MAX_CACHE_BYTES`. */
  | "too-large";

export interface KindleLibrary {
  /**
   * The books, which can be none of them.
   *
   * **A library whose every entry was refused is a library with no books in it
   * and not an empty one**, and the two are different sentences: an account
   * holding nothing but samples holds plenty, none of which the member owns.
   * Reporting that as `empty` would throw away `skipped`, which is the count
   * that makes the true sentence sayable.
   */
  readonly books: readonly KindleBook[];
  /**
   * Entries under `<add_update_list>` that were not a book this member owns.
   *
   * A sample, a magazine or newspaper issue, an entry carrying a content type
   * this reader does not know, and an entry with no ASIN. A number rather than
   * a list: it exists so a member can be told the account held more than this,
   * and which of those an entry was is a fact about Amazon rather than about
   * their library.
   */
  readonly skipped: number;
  /** The document's own `<cache_metadata><version>`, where it carries one. */
  readonly schemaVersion: number | null;
  /**
   * Fields no entry in this document carried. Sorted, so it compares.
   *
   * **Occupancy and not a schema, which is the difference from `kobo.ts`'s
   * field of the same name.** There a missing field is a column the device does
   * not have, which no amount of data can produce; here there is no schema to
   * ask, so what this says is that nothing in the document filled the field.
   * `docs/decisions.md` carries the pair, because one word rendering two
   * different facts on one import surface is the thing to know before writing
   * the sentence a member reads.
   */
  readonly missing: readonly KindleField[];
}

export type KindleReading =
  | { readonly ok: true; readonly library: KindleLibrary }
  | { readonly ok: false; readonly failure: KindleFailure };

/** The file the desktop app keeps its library in, below `Cache/`. */
export const CACHE_FILENAME = "KindleSyncMetadataCache.xml";

/**
 * How much document this reader will parse.
 *
 * **Chosen rather than measured**, and wide on purpose: an entry runs 596 bytes
 * in the 2018 capture and 686 in the 2021 one, so this is a library of between
 * 24,000 and 28,000 titles and 100 times the larger capture.
 *
 * **It bounds a dimension that is not the one that costs.** Measured on builder
 * under this suite's jsdom, timing `parseFromString` apart from everything this
 * module then does. A document nested 16,000 elements deep
 * weighs 112,157 bytes and spends 26,168 ms in the parser. A flat one of 32,000
 * sibling elements weighs 256,156 bytes, 2.3 times as much, and spends 98 ms.
 * **So what costs is nesting depth and not size**: doubling the depth took 3.4,
 * then 4.4, then 4.5, then 4.7 times the wall clock, and 112,157 bytes is 0.67%
 * of this number. No value of it is a fix.
 *
 * **Depth is the dimension it does not bound, rather than the only one it
 * does. Size it holds.** Same node, same jsdom, medians of three, timing the
 * parser alone on a flat document of sibling entries, once with the sizes taken
 * in ascending order and once descending, in milliseconds:
 *
 * | MiB | ascending | descending |
 * |---|---|---|
 * | 1 | 123 | 119 |
 * | 2 | 237 | 232 |
 * | 4 | 489 | 468 |
 * | 8 | 953 | 923 |
 * | 16 | 1913 | 2361 |
 *
 * The top doubling costs 2.01 times the time for twice the size in the
 * ascending row and 2.56 in the descending one, and the top half 3.91 and 5.04.
 * The bound is adequate at either end, which is all this has to establish.
 *
 * **The cap is the one point the instrument cannot pin.** The two orders agree
 * within 4.29% at every size below it and differ by 23.4% there, because
 * whichever order reaches the cap first meets a colder heap.
 *
 * **Every figure in this section is taken inside one row and none of them is
 * written down without being recomputed.** `tests/lib/kindle.test.ts` derives
 * all six from the table above and refuses any the table does not produce. A
 * ratio derived by hand here was wrong repeatedly, which is what a number in
 * prose costs.
 *
 * **Memory is not measured here**, because the instrument reached for returned
 * negative figures at the two sizes that matter, which is a garbage collection
 * running between two samples rather than a measurement.
 *
 * **This module's own walk is not free, and it is also not the cost above.** On
 * the nested documents it measured 0 ms at every depth, so none of the
 * quadratic is here. On a flat document at this number it is 970 ms of a 2,950
 * ms median over three runs, so at the size this bound admits, the walk is
 * about a third of the read and the parser is the rest.
 *
 * How deep a parser will descend is a refusal a caller cannot make after the
 * parse, which is the shape `xmlEntities.ts` exists for and where the remedy
 * belongs. **It is not built here** because every reader handing a whole
 * document to `DOMParser` has the same hole and `opf.ts` was measured on the
 * same curve, so a guard in this module would close one of five.
 *
 * **The name says bytes and one of the two comparisons is on code units**, so
 * both are spelled at their own site. `readKindleCacheFile` compares
 * `File.size`, which is bytes. `readKindleLibrary` compares `String.length`,
 * which is code units, and that is sound in this direction only: a UTF-8 byte
 * decodes to at most one code unit, so a string past this count came from a
 * file past this many bytes.
 */
export const MAX_CACHE_BYTES = 16 * 1024 * 1024;

/**
 * Every element name this module spells, and the only place any of them is
 * spelled.
 *
 * **Nothing outside this list is ever looked up, and that is a property of the
 * types rather than of care taken.** `KindleElement` is this array's own member
 * type and every lookup below takes one, so the names that reach the document
 * are literals spelled here and a member supplied file decides which of them
 * are found and never what they are. That is the whole of the argument
 * `kobo.ts::WANTED` makes about a statement, made about a document: an element
 * named `title/../../*[1]` on a hostile file matches no member here and is not
 * read, because nothing here composes a path out of anything the file said.
 *
 * The second half is that an element that is nowhere in the document costs its
 * field and is reported in `missing` rather than costing the library. **A store
 * that cannot be read is one skipped source and never a broken import**: every
 * outcome here is a value in a closed union, so a caller importing from several
 * places at once loses this one and keeps the rest.
 */
const ELEMENTS = [
  "response",
  "cache_metadata",
  "version",
  "add_update_list",
  "meta_data",
  "ASIN",
  "title",
  "authors",
  "author",
  "publishers",
  "publisher",
  "publication_date",
  "cde_contenttype",
] as const;

type KindleElement = (typeof ELEMENTS)[number];

/**
 * The two elements without which this is not a Kindle library.
 *
 * **A `<response>` is not a signature.** Anything that ever answered an HTTP
 * request keeps one, and refusing on the root alone would call every such
 * document a Kindle library with nothing in it. What is Amazon's own is a
 * `<response>` whose child is an `<add_update_list>`, which is the shape this
 * catalogue is: a list of adds and updates replayed into the library an account
 * holds.
 *
 * **The pair is matched without a namespace, which widens this further than the
 * paragraph above concedes**, so it is said here rather than inherited silently
 * from `childrenNamed`: a document declaring a prefix and spelling `x:response`
 * and `x:add_update_list` is read as this catalogue. Both captures carry 0
 * occurrences of `xmlns` and this format uses none, so requiring the null
 * namespace would be right today and would lose a whole library the day Amazon
 * added one. What the looser rule costs is a mis-import of a file the member
 * supplied themselves, which is the cheaper of the two.
 */
const ROOT: KindleElement = "response";
const LIST: KindleElement = "add_update_list";

/** One title in that list. */
const ENTRY: KindleElement = "meta_data";

/**
 * `cde_contenttype` values that mean the member has the book, and which of them
 * they sent themselves.
 *
 * One map rather than a set beside a predicate, so what is owned and what was
 * sent cannot drift apart.
 *
 * The sources below give five values between them and this reader handles all
 * five; what makes an unknown sixth safe is the refusing arm at the foot of
 * this comment rather than the list being closed. `EBOK` is a
 * book in the account's library and `PDOC` a personal document, a file the
 * member sent to their own Kindle. `EBSP` is a sample, the opening pages the
 * store gives away: **a sample's title is the book's title**, so nothing else
 * in the entry tells the two apart and a reader that keeps one tells a member
 * they own a book they have read the first chapter of. `MAGZ` and `NWPR` are
 * one issue of a magazine and of a newspaper, which are periodicals rather than
 * books.
 *
 * **Read out of calibre rather than out of a capture**, which is why the values
 * named here are not only the two a capture shows. It is one field across four
 * containers: `<cde_contenttype>` here, EXTH 501 in a MOBI, `cde_content_type`
 * in a KFX, `cdeType` in an APNX. `mobi/writer8/exth.py` writes `EBOK` for
 * everything that is not a periodical and maps a news doctype to `NWPR` and a
 * news magazine to `MAGZ`; `mobi/reader/headers.py` reads 501 and calls `EBSP`
 * a sample book; the MobileRead wiki's MOBI page gives the same three with
 * `PDOC` as a personal document. Neither capture carries a `PDOC`, a `MAGZ` or
 * an `NWPR` row, so those three arms are built from that vocabulary rather than
 * from a row, and saying so is what this paragraph is for.
 *
 * **An unrecognised value is skipped rather than kept**, and that direction is
 * the decision, `kobo.ts`'s for the same reason. This is an inclusion list,
 * which is the shape that goes stale, and the alternative goes stale in the
 * direction where the next content type Amazon invents becomes a book on
 * somebody's shelf. Losing a real book is visible in `skipped`; gaining a book
 * nobody bought is not visible at all.
 */
const OWNED = new Map<string, boolean>([
  ["EBOK", false],
  ["PDOC", true],
]);

/**
 * Children of `parent` whose name matches, in document order.
 *
 * **A sibling walk and not a spread of `parent.children`**, which is live and
 * is not required to index in constant time, so spreading one costs whatever
 * the host charges per index over a length a member supplied file decides.
 * `opf.ts` measured the shape: 4 times the elements took 14.8 times the wall
 * clock under its jsdom.
 *
 * **By name and not by namespace.** Both captures declare none: 0 occurrences
 * of `xmlns` in either. What that concedes is at `ROOT` above, which is where
 * it decides something.
 *
 * **Not shared with `opf.ts`, which has the same four lines, and the reason is
 * the parameter rather than taste.** That one takes a `string`, because a
 * package document's Dublin Core names are open; this one takes a
 * `KindleElement`, which is what makes the argument at `ELEMENTS` a property of
 * the types. Merging them widens this parameter back to `string` and dissolves
 * that argument, which is the consequence that stops somebody doing it. The
 * milder reason, that a helper reading a document belongs to the format that
 * spells it, is `xmlEntities.ts`'s rule and is true here too, and on its own a
 * generic helper rebuts it.
 */
function childrenNamed(parent: Element, name: KindleElement): Element[] {
  const found: Element[] = [];
  for (
    let child = parent.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    if (child.localName === name) found.push(child);
  }
  return found;
}

/** The first such child's text, or `null` where there is none worth having. */
function childText(parent: Element, name: KindleElement): string | null {
  const value = childrenNamed(parent, name)[0]?.textContent?.trim();
  return value ? value : null;
}

/**
 * The document's own version, where it states one.
 *
 * Informational, and read rather than acted on: every decision below is taken
 * from the elements that are actually there, which is the same question asked
 * of the document rather than of a number the document states about itself.
 * Both captures carry `1`.
 */
function schemaVersionOf(root: Element): number | null {
  const metadata = childrenNamed(root, "cache_metadata")[0];
  if (metadata === undefined) return null;
  const stated = childText(metadata, "version");
  if (stated === null) return null;
  const version = Number(stated);
  return Number.isInteger(version) ? version : null;
}

/** Every `<author>` an entry names, in the document's order. */
function readAuthors(entry: Element): string[] {
  return childrenNamed(entry, "authors")
    .flatMap((authors) => childrenNamed(authors, "author"))
    .map((author) => author.textContent?.trim() ?? "")
    .filter((name) => name !== "");
}

/** The publisher, of which this format's list carries at most one. */
function readPublisher(entry: Element): string | null {
  const publishers = childrenNamed(entry, "publishers")[0];
  return publishers === undefined ? null : childText(publishers, "publisher");
}

/**
 * Whether this is a book the member holds and whether they sent it themselves,
 * or `null` for one of the other things an account's catalogue lists.
 *
 * **An entry carrying no content type is refused**, which is the opposite of
 * `kobo.ts`'s rule for a column its device never had, and the difference is
 * that this is not a schema. A missing column is a firmware with nowhere to
 * record the answer, and every row on that device shares it; a missing element
 * is one entry among others that carry it, so what it says is that this entry
 * is not the shape the rest are.
 */
function ownership(entry: Element): boolean | null {
  const kind = childText(entry, "cde_contenttype");
  return kind === null ? null : (OWNED.get(kind) ?? null);
}

/**
 * Read a Kindle desktop library, or say why there is not one.
 *
 * Never throws for anything a document can contain. Every way this can fail is
 * a value in `KindleReading`, because the caller's job is the same for all of
 * them: report one source it could not read and carry on with the others.
 * `tests/lib/kindle.test.ts` asserts that against documents built to break it.
 *
 * **A document declaring its own entities is refused as not this catalogue**,
 * `opf.ts`'s answer to the one attack a reader cannot bound after the fact:
 * expansion happens inside the parser, before a line here runs. Both captures
 * carry 0 occurrences of `<!ENTITY` and 0 of `<!DOCTYPE`, so nothing real is
 * lost, and being told a file is not the format it claimed is a smaller harm
 * than an unbounded parse. It is not a fourth failure because it is not a
 * fourth sentence: the member is holding a file this app will not read.
 *
 * **`missing` is derived from the values the entries yielded and not from a
 * second reading of the document**, because the two would be free to disagree
 * and the disagreement would be invisible. What follows from that, stated
 * because it reads oddly at first: a document whose every publication date the
 * year window refuses reports `year` missing, which is the true sentence about
 * what this reader could take out of it.
 */
export function readKindleLibrary(xml: string): KindleReading {
  if (xml.length > MAX_CACHE_BYTES) return { ok: false, failure: "too-large" };
  if (declaresEntities(xml)) {
    return { ok: false, failure: "not-a-kindle-library" };
  }

  const document = new DOMParser().parseFromString(xml, "application/xml");
  // Both halves are needed. A parse error yields a document whose root is
  // `parsererror`, and a well formed document that is not this catalogue yields
  // a root that is simply something else.
  const root = document.documentElement;
  if (!root || root.localName !== ROOT) {
    return { ok: false, failure: "not-a-kindle-library" };
  }
  const list = childrenNamed(root, LIST)[0];
  if (list === undefined) return { ok: false, failure: "not-a-kindle-library" };

  // **Walked down from the list rather than searched for by name.** A document
  // wide search reads a `<meta_data>` from anywhere, including one nested
  // inside another entry, which would make the number of entries the
  // document's to choose rather than the list's to state.
  const entries = childrenNamed(list, ENTRY);
  if (entries.length === 0) return { ok: false, failure: "empty" };

  let skipped = 0;
  const books: KindleBook[] = [];
  const filled = new Set<KindleField>();
  for (const entry of entries) {
    const title = childText(entry, "title");
    const authors = readAuthors(entry);
    const publisher = readPublisher(entry);
    const year = leadingYear(childText(entry, "publication_date"));
    if (title !== null) filled.add("title");
    if (authors.length > 0) filled.add("authors");
    if (publisher !== null) filled.add("publisher");
    if (year !== null) filled.add("year");

    const asin = childText(entry, "ASIN");
    const personal = ownership(entry);
    if (asin === null || personal === null) {
      skipped += 1;
      continue;
    }
    books.push({ asin, title, authors, publisher, year, personal });
  }

  const missing = FIELDS.filter((field) => !filled.has(field)).sort();
  return {
    ok: true,
    library: { books, skipped, schemaVersion: schemaVersionOf(root), missing },
  };
}

/**
 * The same, from a file a member picked.
 *
 * **The size is refused before the bytes are read, not after**, which is
 * `sqlite.openSqliteFile`'s reason and the whole of why this second entry point
 * exists: decoding a two gigabyte file into a string to then decline it has
 * already spent the memory the bound protects. A caller reaching the pure
 * function with a string of its own is still bounded, one copy later.
 */
export async function readKindleCacheFile(file: File): Promise<KindleReading> {
  if (file.size > MAX_CACHE_BYTES) return { ok: false, failure: "too-large" };
  return readKindleLibrary(await file.text());
}
