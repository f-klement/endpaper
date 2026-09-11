/**
 * What an Adobe Digital Editions catalogue says about the books in it, which
 * does not include who owns them.
 *
 * **Not an integration with a company.** The app keeps a catalogue beside the
 * books it has fulfilled, so this reads a file the member already has on a
 * machine they own. Nothing here talks to Adobe, nothing here opens a book, and
 * nothing here touches the protection on one.
 *
 * Pure, in `kobo.ts`'s shape: it takes the document and returns records. It
 * needs no SQLite, for `kindle.ts`'s reason and not a second measurement: the
 * catalogue is XML, so the store costs a reader and no engine.
 *
 * ## The finding this reader exists to state
 *
 * **A catalogue record does not say whether the book is a purchase or a library
 * loan, so this reader claims neither.** Adobe Digital Editions is a
 * fulfilment client for public library loans as much as for purchases, and both
 * land in the same catalogue looking the same.
 *
 * Where the difference actually lives, which is why no amount of reading here
 * recovers it: the loan is a token that travels with the book file. A borrowed
 * book will not open on a second computer however that computer is activated,
 * because the loan token is not copied, while a purchased one will; and the
 * app's own failure when it cannot find one is `W_ADEPT_CORE_LOAN_NOT_ONRECORD`,
 * a record the DRM subsystem keeps rather than the catalogue. The expiry itself
 * sits in the licence token in the fulfilment envelope.
 *
 * **That envelope is the protection on the file, so reading it is the one thing
 * this may not do.** Had ownership been reachable only that way, the answer
 * would have been that this store is not importable. It is not reachable at
 * all, which is a different answer and a smaller one: the catalogue is
 * metadata, it reads, and what it cannot say is said out loud in
 * `ownershipStated` rather than guessed.
 *
 * **What a caller owes because of it.** `backend/schemas/book.py` defaults a
 * created book to `OwnershipStatus.OWNED`, and `books.ownership` has an
 * `unknown` member for exactly this case, a source that cannot answer the
 * question. A wiring that imports this store on the default asserts that
 * somebody owns a book they have for three weeks. `ownershipStated` is typed as
 * the literal `false` so that wiring meets it in the compiler rather than in
 * this paragraph.
 *
 * ## Where the catalogue sits, and that it is two layouts
 *
 * Under the member's own documents: `My Digital Editions` on Windows,
 * `Digital Editions` on macOS.
 *
 * **The 1.x line kept one `manifest.xml` for the whole library. The 2.0 line
 * and later keep a `Manifest` directory holding one XML file per book**, named
 * for the book file it describes, `<the book's file name>.xml`. So this store
 * has no one filename and none is exported here. `stores.ts` says at its own
 * site that a filename is never a signature anyway, and this is the store that
 * could not have supplied one.
 *
 * **One reader reads both**, because the difference between them is how many
 * records a document holds and this counts them rather than expecting one.
 *
 * **So on every install since 2.0 this store imports one book per file picked**,
 * which is a fact about the store rather than about this reader and is stated
 * here for `kindle.ts`'s reason: the registry row a member meets carries a
 * bound, and a bound nobody wrote down is one a member discovers by importing
 * a library of three hundred books one at a time. Reading a directory is a
 * question about the picker rather than about the catalogue.
 *
 * **It names the file it describes by the name of the manifest file itself, and
 * that name is not read.** A path to a fulfilled book is a path to a protected
 * file, and this module has no use for one: `readDigitalEditionsLibrary` takes
 * a string and cannot see a name, and the file entry point reads size and bytes
 * and nothing else.
 *
 * ## The vocabulary, and how much of it is attested
 *
 * `contentRecord` is the per book element, in Adobe's own `de` prefix. Inside
 * it the metadata is Dublin Core, and `dc:title` and `dc:publisher` are
 * attested verbatim.
 *
 * **`dc:creator` and `dc:identifier` are read on the strength of the sibling
 * format rather than of a capture**, and this is the weakest claim in the
 * module. Adobe's own fulfilment file for the same book carries `dc:title`,
 * `dc:creator`, `dc:publisher` and `dc:identifier` in one metadata block, and
 * the app's library view has an Author column, so the record has to carry an
 * author somewhere. **What being wrong costs is a field, never a book**: an
 * element nothing in the document spells is reported in `missing`, which is the
 * true sentence about what this reader could take out of that document.
 *
 * **No year, no language, no series, no description, no format.** No published
 * source shows a record carrying any of them, and an element invented here
 * would be a schema this reader made up. A field it never looks for is not the
 * same thing as a field a document did not fill, which is why none of them is a
 * `DigitalEditionsField`, `kindle.ts`'s distinction.
 *
 * **`de:thumbnailID` is deliberately not read.** It is a path to a cover file
 * on the member's own disk, and this app takes a cover from a book rather than
 * from a path into somebody's documents directory.
 *
 * **Matched by local name and not by namespace, which is necessary here rather
 * than conceded.** The `de` prefix's namespace URI is not published anywhere
 * this trio could find, so requiring one would mean inventing it. What that
 * costs is at `hasRecords` below.
 *
 * ## Where the format was read, and what was not done
 *
 * **No machine was read, and there is none to read here.** Every fixture in
 * `tests/lib/adobeDigitalEditions.test.ts` is constructed from the vocabulary
 * this docstring names. Nothing below is a copy of anybody's catalogue.
 *
 * Read on 2026-09-11:
 *
 * | source | what it establishes |
 * |---|---|
 * | Adobe Support Community, `Titled Corrupted, possible to edit eBooks metadata` | `manifest.xml` under `Documents\My Digital Editions`, carrying `<dc:title>` and `<de:thumbnailID>` |
 * | Adobe Support Community, `DE's publisher metadata, where to enter it in Acrobat` | `<dc:publisher>` in that file; the library view's columns are Title, Author, Publisher, Last Read |
 * | Adobe Support Community, `Problem with ADE 2.0 to renew a loan` | `<de:contentRecord>` is the per book section; 2.0 keeps a `Manifest` directory where 1.7.2 kept one file; `W_ADEPT_CORE_LOAN_NOT_ONRECORD` |
 * | Adobe Support Community, `stuck at loading library` | that directory holds one `.epub.xml` per book, on the 4.5 line |
 * | Adobe Digital Editions FAQ, `Can I transfer eBooks that I have already purchased or downloaded to another computer?` | a borrowed book's loan token is not copied between computers, and a purchased book opens on a second computer activated with the same ID |
 * | `shkspr.mobi/blog/2021/07/a-brief-look-at-acsm-files/`, 2021-07-24 | the fulfilment token's `<expiration>` and `<licenseToken><permissions>`, and the `dc:` metadata block beside them |
 *
 * **Four of those six are a support forum, which is a weaker source than the
 * captures `kindle.ts` was built from.** No capture of this catalogue was
 * found, in a search that covered a code host's index as well as the web, so
 * the element names above are as strong as the evidence got. Every one of them
 * fails the same way, into `missing`.
 */

import { declaresEntities } from "./xmlEntities";

/** One book the catalogue lists, with no claim about who owns it. */
export interface DigitalEditionsBook {
  /**
   * Which record in the catalogue this was, counting from 1 and counting the
   * ones that were skipped.
   *
   * **The only value this format is certain to carry**, which is why it is
   * here. Every metadata element above is optional in a way no source could
   * bound, so a caller needing one value per book that is never absent and
   * never repeated has nothing else to take. `stores.StoreBook.key` is that
   * caller, and it asks for uniqueness within one source rather than across
   * them.
   *
   * **Not the index of this book in `books`**, which is a different number the
   * moment a record is skipped, and not a fact a caller could recompute from
   * what it was given.
   *
   * **Not stable across imports.** A record removed from the catalogue moves
   * every record after it, so this identifies a book within one reading and
   * makes no claim beyond it.
   */
  readonly record: number;
  readonly title: string;
  /** Every `dc:creator` the record names, in the document's order. */
  readonly authors: readonly string[];
  readonly publisher: string | null;
  /**
   * The record's `dc:identifier`, exactly as written.
   *
   * **Opaque, and never read as an ISBN.** What scheme this carries is not
   * published: Dublin Core does not fix one, an EPUB's own identifier is as
   * often a UUID as anything else, and no source here shows what Adobe writes.
   * Putting an unknown scheme through `parseIsbn` would put a right looking
   * number in a field every lookup treats as an ISBN, which is the refusal
   * `kindle.ts` records for a `B` prefixed ASIN.
   */
  readonly identifier: string | null;
}

/** A field no record in this document carried. */
export type DigitalEditionsField = "authors" | "publisher" | "identifier";

/**
 * Every field `missing` can name, so the list is one thing rather than two.
 *
 * Declared beside the type it enumerates and asserted against it: a field added
 * to `DigitalEditionsField` and not here would never be reported missing, and
 * the reader would say a document supplied something it had never looked for.
 * `tests/lib/adobeDigitalEditions.test.ts` recomputes the pair rather than
 * restating either.
 *
 * **`title` is not a member and cannot be.** A record without one is skipped,
 * so a document that filled no title yields no books at all and says so through
 * `skipped`. A field that can only ever be reported on an empty library is a
 * field reported to nobody.
 */
const FIELDS: readonly DigitalEditionsField[] = [
  "authors",
  "publisher",
  "identifier",
];

/** Why a document yielded no library. Closed, one sentence each on screen. */
export type DigitalEditionsFailure =
  /**
   * Not this catalogue: unparseable, XML that is something else, or a document
   * declaring its own entities.
   *
   * **There is no `empty` beside it, and the absence is a fact about the format
   * rather than a corner left unfinished.** `kobo.ts` and `kindle.ts` can each
   * say "this is your device, with nothing on it" because each has a signature
   * that survives the library being empty: a `content` table, a `<response>`
   * whose child is an `<add_update_list>`. The root element of this catalogue is
   * not published, so a document with no `contentRecord` in it is a document
   * with nothing here to recognise, and calling it an empty Digital Editions
   * library would be a sentence about a file this reader cannot identify.
   */
  | "not-a-digital-editions-catalogue"
  /** Past `MAX_CATALOGUE_BYTES`. */
  | "too-large";

export interface DigitalEditionsLibrary {
  /**
   * The books, which can be none of them.
   *
   * **A catalogue whose every record was refused is a library with no books in
   * it and not an unrecognised file**, and the two are different sentences.
   * Reporting the first as the second would send a member looking for a
   * catalogue they are already holding.
   */
  readonly books: readonly DigitalEditionsBook[];
  /**
   * Records that carried no title.
   *
   * A number rather than a list, `kobo.ts`'s rule: it exists so a member can be
   * told the catalogue held more than this, and a record with nothing to file it
   * under is nothing this app could show them.
   */
  readonly skipped: number;
  /**
   * Always `null`, because this catalogue states no version of itself.
   *
   * Kept rather than dropped: it is the shape every store reader answers in, and
   * a reader missing a field of it is a reader a caller has to special case. A
   * version element arriving in some later app has a home, and until then this
   * says what is true.
   */
  readonly schemaVersion: null;
  /**
   * Fields no record in this document carried. Sorted, so it compares.
   *
   * **Occupancy and not a schema**, `kindle.ts`'s distinction and for its
   * reason: there is no schema here to ask, so what this says is that nothing in
   * the document filled the field. That covers the two elements this reader
   * takes on the weaker evidence, which is what makes being wrong about them
   * cost a field rather than a library.
   */
  readonly missing: readonly DigitalEditionsField[];
  /**
   * Whether this catalogue said who owns these books. It never did.
   *
   * **A marker for the wiring to read, and it is not an enforcement.** Measured
   * by the design seat: widening this to `boolean` leaves `tsc --noEmit` and the
   * whole suite green, because nothing requires a caller to read a property.
   * What it buys is that the fact is in the type a wiring seat opens rather than
   * only in a paragraph it may not, and the literal `false` is the narrowest
   * true statement about every catalogue this reader has read.
   *
   * **The enforcement is owed elsewhere and is not this module's to build**:
   * `BookCreate` defaults a created book to owned, so a store that cannot say
   * has to send `unknown`, which is a field on the common record and a line in
   * the adapter. Until that exists, importing this store claims ownership
   * nobody checked.
   */
  readonly ownershipStated: false;
}

export type DigitalEditionsReading =
  | { readonly ok: true; readonly library: DigitalEditionsLibrary }
  | { readonly ok: false; readonly failure: DigitalEditionsFailure };

/**
 * How much document this reader will parse.
 *
 * **Chosen rather than measured, and it is `kindle.ts`'s number for
 * `kindle.ts`'s reason.** That module measured the parser's curve against the
 * same `DOMParser` on the same host and states both what the bound holds, size,
 * and the dimension it does not, nesting depth. Neither figure is re-derived
 * here, because a number copied into a second file is a number that goes stale
 * in one of them.
 *
 * **What is this format's own**: a record is a handful of short elements, so a
 * document at this bound is a catalogue far past any library a person has. The
 * bound is not sized to that, it is sized to what a parser will be asked to do
 * with a file somebody else wrote.
 *
 * **The name says bytes and one of the two comparisons is on code units**, so
 * both are spelled at their own site, `kindle.ts`'s arrangement.
 * `readDigitalEditionsCatalogueFile` compares `File.size`, which is bytes.
 * `readDigitalEditionsLibrary` compares `String.length`, which is code units,
 * and that is sound in this direction only: a UTF-8 byte decodes to at most one
 * code unit, so a string past this count came from a file past this many bytes.
 */
export const MAX_CATALOGUE_BYTES = 16 * 1024 * 1024;

/**
 * Every element name this module spells, and the only place any of them is
 * spelled.
 *
 * **Nothing outside this list is ever looked up, and that is a property of the
 * types rather than of care taken.** `DigitalEditionsElement` is this array's
 * own member type and every lookup below takes one, so the names that reach the
 * document are literals spelled here and a member supplied file decides which of
 * them are found and never what they are. `kindle.ts::ELEMENTS` makes the
 * argument in full.
 */
const ELEMENTS = [
  "contentRecord",
  "title",
  "creator",
  "publisher",
  "identifier",
] as const;

type DigitalEditionsElement = (typeof ELEMENTS)[number];

/** One book in the catalogue. */
const RECORD: DigitalEditionsElement = "contentRecord";

/**
 * The records in a document, in document order.
 *
 * **The root itself counts**, which is what reads a 2.0 style per book manifest:
 * there the whole file is one record. Otherwise they are looked for below the
 * root, because the element that holds them is not published and a rule naming
 * it would be a rule this trio invented.
 */
function recordsIn(root: Element): Element[] {
  return root.localName === RECORD ? [root] : descendantsNamed(root, RECORD);
}

/**
 * Elements below `parent` with this local name, in document order.
 *
 * **Below rather than directly below, and that is the fix to a real hole.** The
 * one source this module has for `dc:creator` and `dc:identifier` is Adobe's
 * fulfilment file carrying the `dc:` terms in one metadata block, which is to
 * say inside a container. A reader taking only direct children would answer
 * nothing at all for a record shaped that way, and because a record with no
 * title is skipped, the cost would be every book rather than a field. Measured
 * by the design seat against the previous draft: a record wrapping its four
 * elements one level down yielded 0 books and 1 skipped.
 *
 * **Two subtrees are not descended into, and each is a different rule.** A match
 * is not descended into, so an element's own text is its answer and one nested
 * inside it is not a second. And a `contentRecord` below `parent` is somebody
 * else's book: not descending into one is what keeps a nested record from being
 * counted twice when this is looking for records, and what keeps an outer record
 * from taking an inner one's title when it is looking for a field. A document
 * wide `getElementsByTagName` can do neither, which is why this walk exists.
 *
 * **An explicit stack and not recursion, and it is load bearing at a depth
 * nothing can afford to reach.** A recursive walk deep enough throws a
 * `RangeError` where this contract promises a value, and a document that deep is
 * well inside the byte bound: 50,000 nested three character elements weigh under
 * 400 KB. So the stack is what keeps the promise for such a file, and it costs
 * nothing to keep.
 *
 * **No test observes it, and the reason is a measurement rather than a
 * preference.** Both routes to a document that deep were priced on builder under
 * this suite's jsdom. A recursive walk returns cleanly at depth 8,000, measured
 * by the security seat, and at 10,000; it throws at 50,000. Reaching 50,000
 * costs 281,633 ms building the tree a node at a time, and building it from the
 * leaf upwards, which is nine times cheaper at 10,000 at 1,087 ms against 9,683,
 * throws inside jsdom's own tree mutation before it gets there. The parser is no
 * cheaper: `kindle.ts` measured 26,168 ms at depth 16,000.
 *
 * **So the rule is held by a reading of this source rather than by a document.**
 * `tests/lib/adobeDigitalEditions.test.ts` asserts that no function declared in
 * this module names itself in its own body. **Every declaration and not this
 * one**, which is the scope the first attempt got wrong: it read this function
 * alone, and the design seat walked past it in one edit by delegating the body
 * to a sibling that recursed. Verified on the mutation rather than by reading:
 * making `recordsIn` recurse leaves all 51 other arms green and reddens that one
 * by name.
 *
 * **Two shapes are outside it**, and the arm names both: mutual recursion, which
 * needs a call graph that `typescript` at 7.0.2 ships no parser for, and a
 * shorthand method in an object literal, which this module has none of. A
 * function bound to a name by `=` is inside, reached by depth rather than by
 * matching the arrow's spelling, which is what every pattern over a signature
 * loses to.
 */
function descendantsNamed(
  parent: Element,
  name: DigitalEditionsElement,
): Element[] {
  const found: Element[] = [];
  // Reversed on the way in, so popping yields document order.
  const pending: Element[] = childElements(parent).reverse();
  while (pending.length > 0) {
    const element = pending.pop()!;
    if (element.localName === name) {
      found.push(element);
      continue;
    }
    if (element.localName === RECORD) continue;
    for (const child of childElements(element).reverse()) {
      pending.push(child);
    }
  }
  return found;
}

/**
 * The element children of `parent`, in document order.
 *
 * **A sibling walk and not a spread of `parent.children`**, which is live and is
 * not required to index in constant time, so spreading one costs whatever the
 * host charges per index over a length a member supplied file decides.
 * `opf.ts` measured the shape: 4 times the elements took 14.8 times the wall
 * clock under its jsdom.
 */
function childElements(parent: Element): Element[] {
  const found: Element[] = [];
  for (
    let child = parent.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    found.push(child);
  }
  return found;
}

/**
 * What a record says under this name: its own children, or failing those, what
 * it holds further down.
 *
 * **The record's own first, and the order is the whole of this function.**
 * Descending alone reads the first match in document order, so a container that
 * is not a record and sits before the record's own elements wins: measured by
 * the design seat against the previous draft, a `<de:cover>` holding a
 * `dc:title` and a `dc:creator` gave a record the caption for its title and the
 * photographer for an author, and moving that container after the record's own
 * two elements gave the right answers. **That trade was the wrong way round.**
 * A read that goes no deeper loses a field, which `missing` reports; a read that
 * prefers whatever came first puts a wrong book on a shelf, which nothing
 * reports.
 *
 * **Descending is still needed and is still second.** The one source for
 * `dc:creator` and `dc:identifier` has the `dc:` terms in one metadata block, so
 * a record that keeps them in a container is the shape this format most likely
 * takes, and reading only direct children answers nothing for it: 0 books and 1
 * skipped, measured on the same fixture.
 *
 * **What is left, stated rather than hidden.** A record with a foreign container
 * and no element of its own under that name still answers out of the container.
 * What makes that the right way round is not that a value beats none, which for
 * three of the four names would be a reported `missing` and is the direction
 * `kobo.ts` calls the safer one: it is that a container is this store's expected
 * shape, so refusing one would skip every wrapped record rather than lose a
 * field on an odd one.
 *
 * **By local name and not by namespace**, which the module docstring gives the
 * reason for. What it concedes is that a `de:title` and a `dc:title` are the
 * same element to this reader, and that a prefix bound to some other namespace
 * is read as Adobe's. On a file the member supplied themselves, that costs a
 * mis-read of their own file and nothing else.
 */
function within(record: Element, name: DigitalEditionsElement): Element[] {
  const own = childElements(record).filter((child) => child.localName === name);
  return own.length > 0 ? own : descendantsNamed(record, name);
}

/**
 * The first such element's text, or `null` where there is none worth having.
 *
 * **The first and not a join**, which is the same refusal the two identifiers
 * get: a record carrying two is a record this reader has no way to choose
 * between, so it takes the one the document put first rather than a value that
 * is neither.
 */
function firstText(
  record: Element,
  name: DigitalEditionsElement,
): string | null {
  const value = within(record, name)[0]?.textContent?.trim();
  return value ? value : null;
}

/** Every `dc:creator` a record names, in the document's order. */
function readAuthors(record: Element): string[] {
  return within(record, "creator")
    .map((creator) => creator.textContent?.trim() ?? "")
    .filter((name) => name !== "");
}

/**
 * Read a Digital Editions catalogue, or say why there is not one.
 *
 * Never throws for anything a document can contain. Every way this can fail is a
 * value in `DigitalEditionsReading`, because the caller's job is the same for
 * all of them: report one source it could not read and carry on with the others.
 * `tests/lib/adobeDigitalEditions.test.ts` asserts that against documents built
 * to break it.
 *
 * **A document declaring its own entities is refused as not this catalogue**,
 * `xmlEntities.ts`'s rule and the one attack a reader cannot bound after the
 * fact: expansion happens inside the parser, before a line here runs. Being told
 * a file is not the format it claimed is a smaller harm than an unbounded parse.
 * It is not a third failure because it is not a third sentence: the member is
 * holding a file this app will not read.
 *
 * **A record with no title is skipped rather than shelved.** The API requires a
 * title and `storeToBookCreate` drops a book without one anyway, so keeping it
 * here would move the loss from a number a member is shown to a preview row that
 * quietly disappears.
 *
 * **`missing` is derived from the values the records yielded and not from a
 * second reading of the document**, `kindle.ts`'s reason: the two would be free
 * to disagree and the disagreement would be invisible.
 */
export function readDigitalEditionsLibrary(
  xml: string,
): DigitalEditionsReading {
  if (xml.length > MAX_CATALOGUE_BYTES) {
    return { ok: false, failure: "too-large" };
  }
  if (declaresEntities(xml)) {
    return { ok: false, failure: "not-a-digital-editions-catalogue" };
  }

  const document = new DOMParser().parseFromString(xml, "application/xml");
  // A parse error yields a document whose root is `parsererror`, which is an
  // element like any other and holds no records, so both halves of "this is not
  // the catalogue" land on the one arm below.
  const root = document.documentElement;
  const records = root ? recordsIn(root) : [];
  if (records.length === 0) {
    return { ok: false, failure: "not-a-digital-editions-catalogue" };
  }

  let skipped = 0;
  const books: DigitalEditionsBook[] = [];
  const filled = new Set<DigitalEditionsField>();
  records.forEach((record, index) => {
    const authors = readAuthors(record);
    const publisher = firstText(record, "publisher");
    const identifier = firstText(record, "identifier");
    if (authors.length > 0) filled.add("authors");
    if (publisher !== null) filled.add("publisher");
    if (identifier !== null) filled.add("identifier");

    const title = firstText(record, "title");
    if (title === null) {
      skipped += 1;
      return;
    }
    books.push({ record: index + 1, title, authors, publisher, identifier });
  });

  return {
    ok: true,
    library: {
      books,
      skipped,
      schemaVersion: null,
      missing: FIELDS.filter((field) => !filled.has(field)).sort(),
      ownershipStated: false,
    },
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
 *
 * **The file's name is not read**, and on this store that is the line rather
 * than a detail: the manifest is named for the protected book beside it, and
 * this reader has no use for a path to one.
 */
export async function readDigitalEditionsCatalogueFile(
  file: File,
): Promise<DigitalEditionsReading> {
  if (file.size > MAX_CATALOGUE_BYTES) {
    return { ok: false, failure: "too-large" };
  }
  return readDigitalEditionsLibrary(await file.text());
}
