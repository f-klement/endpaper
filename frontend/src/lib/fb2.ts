/**
 * A FictionBook 2 file's metadata, read in the member's own browser.
 *
 * **Endpaper never takes custody of a member's book file.** `epub.ts` states
 * that rule at length and it is the same rule here; this module reads bytes the
 * member already has and sends only what the file said.
 *
 * **FB2 is XML from the first byte, so there is no container to open.** A `.fb2`
 * is the document itself and a `.fb2.zip` is that document deflated into an
 * archive, which is why the two doors below are the same parse behind different
 * front halves.
 *
 * ## The corpus, and what it is not
 *
 * **Every figure in this file means 18 FictionBook files fetched from public
 * GitHub repositories on 2026-09-07**, which is stated once here rather than at
 * each site. 7 are copies of real published books carrying a real producer's
 * output (Санфиров, three Gaiman translations, Гюго, Кобрин, Черчилль); the
 * other 11 are the format's own specimen documents and the fixtures of four FB2
 * parsers. **It is a proxy and not somebody's library.** The library this was
 * meant to be checked against holds no FB2 at all: re-derived 2026-09-08, a
 * `find` over the household's whole books share, which is the Calibre library
 * plus six folders beside it, counted 2,372 files, of which 927 `epub`, 243
 * `pdf`, 1 `mobi` and **0 `fb2` or `fb2.zip`**; the Calibre library on its own
 * is 2,078 of those. A second `find`, by name rather than by extension
 * histogram, agrees on the zero. That is
 * the honest prevalence argument for this format and it is a cost argument: FB2
 * is dominant in the Russian language ebook world and close to absent elsewhere,
 * so what earns it a place is that it is a `DOMParser` and no dependency.
 *
 * ## What it cannot supply, stated as the exclusion
 *
 * A subtitle. FB2's `title-info` has one title element and no notion of a
 * second, so `subtitle` is always `null` here and nothing guesses one out of the
 * title. Page count, and a format's own `version`, for the reason `mobi.ts`
 * gives: there is no package document, so there is no package version.
 * Everything else in the minimum field set arrives: title, authors as separate
 * values, ISBN, series and index, publisher, year, language and description.
 *
 * **`<genre>` is read by nothing here, and that is a destination problem rather
 * than a reading one**, which is the sentence `mobi.ts` writes about the EXTH
 * subject: `OpfRecord` has no tags and the scan page's draft sends none, so
 * there is nowhere to put it. It is carried by every file in the corpus, 35
 * elements across 18, as `lang` is, so it is the one exclusion here worth
 * revisiting when a draft can carry a tag.
 *
 * **Lazy loaded**, like every reader: `lib/fileReaders.ts` imports this only
 * when a member picks a file whose name ends in one of the two extensions.
 */

import { plausibleYear } from "./bookBounds";
import { parseIsbn } from "./isbn";
import {
  declaresEntities,
  type OpfIdentifier,
  type OpfRecord,
} from "./fileReaders";
import { openZip, ZipError, zipFailureAs } from "./zip";

/**
 * How much of a bare `.fb2` is read off the disk.
 *
 * **The whole point of the number: a `.fb2` is a book, and this reads a header.**
 * Both doors read exactly this much: a bare file by slicing it and an archived
 * one by `readPrefix` on the zip seam, so the two see the same bytes and answer
 * the same way about them.
 * `<description>` is the first child of the root and the body follows it, so
 * everything this module wants sits at the front of the file. Measured over the
 * corpus: `</description>` ends at most 9,104 bytes in, median 2,472.5, against
 * files up to 5,616,072 bytes. 256 KiB is 28.8 times the largest header seen,
 * which leaves room for a long annotation and still never touches a body.
 *
 * **Past it is `too-large` and not `not-an-fb2`**, because a FictionBook with a
 * very long annotation is a FictionBook and a member told it is not one has been
 * told something false. The two are told apart by what the prefix holds: a
 * `<description>` opened and never closed, in a read that filled its bound.
 */
const MAX_HEADER_BYTES = 256 * 1024;

/**
 * How large a `.fb2.zip` entry may be at all.
 *
 * **The ceiling and not the read**, which are two questions and used to be one.
 * `lib/zip.ts` now takes both, so the read is `MAX_HEADER_BYTES` off the front
 * of the entry and this is only what the entry may declare or hold before it is
 * refused outright. Keeping it is the point: without a ceiling a prefix read
 * accepts anything, and an entry no reader could open would come back as a
 * header that happened to be short rather than as `too-large`.
 *
 * 32 MiB is 5.97 times the largest file in the corpus, 5,616,072 bytes. The
 * headroom is for the `<binary>` blocks: FB2 carries its cover, and sometimes
 * every illustration, base64 encoded inside the same document.
 */
const MAX_ARCHIVED_BYTES = 32 * 1024 * 1024;

/**
 * How far in the XML declaration is looked for.
 *
 * It is the first thing in the file when it is there at all, so this is a bound
 * on a scan rather than a claim about where a declaration may sit. Measured: the
 * longest in the corpus is 45 bytes.
 */
const DECLARATION_SCAN_BYTES = 1024;

/**
 * The end of `<description>`, as a pattern rather than a literal.
 *
 * `ETag ::= '</' Name S? '>'`, so `</description >` is well formed and a literal
 * misses it, which for this reader is a whole file refused. 0 of 18 corpus files
 * spell it that way; the reason to match it is that the slice below states its
 * own exclusions and this one does not belong among them.
 */
const DESCRIPTION_END = /<\/description\s*>/;

/**
 * Why a file yielded nothing. Closed, because each one is a different sentence
 * to a member holding a file that did not work.
 *
 * Only `not-an-fb2` is new. The other five are the names `lib/fileReaders.ts`
 * already carries for the same five things, which is the arrangement that
 * module's docstring argues for: `damaged` means the same to a member whichever
 * reader said it.
 */
export type Fb2Failure =
  /** Not a FictionBook document, or an archive holding no `.fb2` entry. */
  | "not-an-fb2"
  /** A zip whose own offsets do not agree with its length. */
  | "damaged"
  /** Encrypted, which here means DRM, and DRM is out of scope. */
  | "protected"
  /** The header, or the archived document, is longer than this will read. */
  | "too-large"
  /** Zip64, spanned, or a compression method `lib/zip.ts` does not implement. */
  | "unsupported"
  /** This browser has no `DecompressionStream("deflate-raw")`. */
  | "no-inflate";

export type Fb2Reading =
  | { readonly ok: true; readonly metadata: OpfRecord }
  | { readonly ok: false; readonly failure: Fb2Failure };

/**
 * Children of `parent` whose local name matches, in document order.
 *
 * A sibling walk and not a spread of `parent.children`, for the reason and the
 * measurement `opf.ts` states at its own copy of this: the collection is live,
 * indexing it is not required to be constant time, and the length is the
 * member's file's choice. Duplicated rather than imported because `opf.ts` does
 * not export it and this module does not own that file.
 *
 * **Scoping every read to a named parent is also the whole of this reader's
 * defence against the wrong author.** `<description>` carries a `document-info`
 * beside `title-info`, and `document-info` has `<author>` children naming
 * whoever produced the FB2 file rather than whoever wrote the book. 15 of the 18
 * corpus files carry one. A `getElementsByTagName("author")` would file the
 * converter as a co-author of every book.
 */
function childrenNamed(parent: Element, local: string): Element[] {
  const found: Element[] = [];
  for (
    let child = parent.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    if (child.localName === local) found.push(child);
  }
  return found;
}

function firstNamed(
  parent: Element | null | undefined,
  local: string,
): Element | null {
  if (parent === null || parent === undefined) return null;
  for (
    let child = parent.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    if (child.localName === local) return child;
  }
  return null;
}

function text(element: Element | null): string | null {
  const value = element?.textContent?.trim();
  return value ? value : null;
}

/** Runs of whitespace to one space. `<annotation>` is paragraphs, not a line. */
function collapse(value: string | null): string | null {
  if (value === null) return null;
  const collapsed = value.replace(/\s+/g, " ").trim();
  return collapsed ? collapsed : null;
}

/**
 * The encoding label the file declares, or `"utf-8"`.
 *
 * **This is the trap FB2 has that EPUB does not, and it is not a corner case.**
 * `windows-1251` is what the format's Windows era editors wrote, and **3 of 18
 * files in the corpus declare it**. Decoding one of those as UTF-8 does not
 * fail: it yields a record whose every Cyrillic title and author is mojibake,
 * which reaches the confirm step looking like data.
 *
 * A BOM outranks the declaration, because a BOM is bytes and a declaration is a
 * claim. The exclusion, stated: UTF-16 with no BOM is read as though it were
 * ASCII compatible and finds no declaration, so it decodes as UTF-8 and yields
 * nothing. XML requires the BOM for UTF-16, and no file in the corpus is UTF-16
 * at all.
 */
function declaredEncoding(raw: Uint8Array): string {
  if (raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) return "utf-8";
  if (raw[0] === 0xff && raw[1] === 0xfe) return "utf-16le";
  if (raw[0] === 0xfe && raw[1] === 0xff) return "utf-16be";

  // Built by hand rather than with a `TextDecoder`, so that sniffing an
  // encoding never itself needs one that may not exist. A byte over 0x7f cannot
  // be part of a declaration in any encoding this reaches, so it becomes a
  // space and the match simply fails.
  let head = "";
  const end = Math.min(raw.length, DECLARATION_SCAN_BYTES);
  for (let at = 0; at < end; at += 1) {
    const byte = raw[at]!;
    head += byte < 0x80 ? String.fromCharCode(byte) : " ";
  }
  const match = /^<\?xml[^>]*?encoding\s*=\s*["']([\w.:-]+)["']/.exec(head);
  return match ? match[1]! : "utf-8";
}

/**
 * The bytes as text.
 *
 * A label this engine has no table for falls back to UTF-8 rather than throwing:
 * `TextDecoder` raises a `RangeError` for an unknown label, and a file naming a
 * dead codepage is still a file whose element names are ASCII. What it loses is
 * that file's own non ASCII text, which is the smaller harm.
 */
function decode(raw: Uint8Array): string {
  const label = declaredEncoding(raw);
  try {
    return new TextDecoder(label).decode(raw);
  } catch {
    return new TextDecoder("utf-8").decode(raw);
  }
}

/**
 * The document's header as a document of its own, or `null`.
 *
 * **Two things happen here and both are load bearing.**
 *
 * The prefix is closed at the end of `<description>` and a `</FictionBook>` is
 * put after it, so what is parsed is a well formed document holding the header
 * and nothing else. Without it a bounded read of a real book hands the parser a
 * truncated document, which in `application/xml` is a `parsererror` and no
 * metadata at all. The exclusion: a `</description>` inside a comment or a
 * `CDATA` section earlier in the file closes the prefix in the wrong place, and
 * what that produces is a parse error and a refusal rather than a wrong record.
 *
 * The XML declaration is **removed**, which is a claim about bytes being made
 * about a string that is no longer those bytes: `decode` has already resolved
 * the encoding, and leaving a `encoding="windows-1251"` on a UTF-16 JavaScript
 * string is a statement no engine can act on correctly. It also takes this
 * module out of the way of the fault `tests/lib/opf.test.ts` documents, where
 * happy-dom's `DOMParser` falls back to HTML parsing on a **single quoted**
 * declaration and a perfectly ordinary document reads as nothing.
 */
function headerDocument(xml: string): string | null {
  const end = DESCRIPTION_END.exec(xml);
  if (end === null) return null;
  const header = xml.slice(0, end.index + end[0].length);
  return `${header.replace(/^\uFEFF?\s*<\?xml[^>]*\?>/, "")}</FictionBook>`;
}

/**
 * One author's name, in the order it reads.
 *
 * **FB2 separates the parts and this is the only place they are joined.** The
 * element carries `first-name`, `middle-name` and `last-name` as elements, which
 * is better than the display string every other format in this set supplies, and
 * `OpfRecord.authors` is a list of people rather than one line, so the joining
 * that happens here is within one person and never between two.
 *
 * **An author with no name at all but a nickname is a real file**, not a
 * hypothetical: 1 of 18 in the corpus. Falling back to it is the difference
 * between a co-author and an author list one short.
 */
function nameOf(author: Element): string | null {
  const parts: string[] = [];
  for (const part of ["first-name", "middle-name", "last-name"]) {
    const value = text(firstNamed(author, part));
    if (value !== null) parts.push(value);
  }
  if (parts.length > 0) return parts.join(" ");
  return text(firstNamed(author, "nickname"));
}

/**
 * The authors, separately and in document order.
 *
 * **A `Set` and not an array scan**, for the reason `opf.ts` measured on its own
 * creator loop: the count is the member's file's choice, `includes` inside the
 * loop is quadratic in it, and this reader's own bound admits far more of them
 * than that stays affordable for.
 */
function readAuthors(titleInfo: Element): string[] {
  const seen = new Set<string>();
  const authors: string[] = [];
  for (const author of childrenNamed(titleInfo, "author")) {
    const name = nameOf(author);
    if (name !== null && !seen.has(name)) {
      seen.add(name);
      authors.push(name);
    }
  }
  return authors;
}

/**
 * The series and the position in it.
 *
 * **FB2 is the one format in this set that carries a series as a typed field**,
 * and it carries it in attributes rather than in text: `<sequence name="..."
 * number="..."/>`. 7 of 18 files in the corpus carry one, 3 of the 7 real books
 * among them.
 *
 * **Several `<sequence>` elements are legal and occur**, 1 of 18 here, and they
 * mean either a book in two series or the same series named in two languages,
 * which is what an `xml:lang` on each of them says. Endpaper has one series
 * column, so the first named one wins and the rest are dropped. Passing over an
 * unnamed one rather than taking it is what stops a malformed first element
 * hiding a good second.
 *
 * **A nested `<sequence>` is a sub series and is not read.** 1 of 18 carries
 * one. Two columns cannot hold a series, a sub series and two positions, and
 * flattening them into one name would invent a series that file does not name.
 *
 * **`number` is optional and its absence is ordinary**: 2 of the 8 sequence
 * elements measured carry a name and no number, which is a book in a series
 * at an unknown position. That is `seriesName` set and `seriesIndex` null, and
 * it is why they are read separately rather than as a pair.
 */
function readSeries(titleInfo: Element): {
  seriesName: string | null;
  seriesIndex: number | null;
} {
  for (const sequence of childrenNamed(titleInfo, "sequence")) {
    const name = (sequence.getAttribute("name") ?? "").trim();
    if (name === "") continue;
    return {
      seriesName: name,
      seriesIndex: toNumber(sequence.getAttribute("number")),
    };
  }
  return { seriesName: null, seriesIndex: null };
}

function toNumber(raw: string | null): number | null {
  if (raw === null) return null;
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/**
 * The year the book was published.
 *
 * **`publish-info/year` first, and `title-info/date` is the fallback rather than
 * the source.** The format says the two are different facts: the first is the
 * year of the paper edition, the second is when the book was written. They
 * disagree in 8 of the 9 corpus files carrying both, and the disagreement is
 * not noise: Евгений Онегин is 1833 written against a 2023 Litres edition, and
 * Война и мир is 1869 against a 1957 printing. A catalogue row's year is the
 * edition's, which is also the choice `opf.ts` makes when an EPUB carries a
 * publication date and an original publication date.
 *
 * The date element's `value` attribute is preferred over its text because the
 * attribute is ISO and the text is whatever a person typed: the corpus holds
 * `25/08/2014`, `1948-53` and `1863-1869` in that position.
 */
function readYear(
  titleInfo: Element,
  publishInfo: Element | null,
): number | null {
  const published = yearIn(text(firstNamed(publishInfo, "year")));
  if (published !== null) return published;

  const date = firstNamed(titleInfo, "date");
  if (date === null) return null;
  return yearIn(date.getAttribute("value")) ?? yearIn(text(date));
}

/**
 * The first standalone four digit run, which is where a year hides in a date.
 *
 * **Standalone, because `<date>` text is whatever a person typed and one thing
 * people type there is the ISBN.** An unanchored `\d{4}` takes the first four
 * digits of any longer run: on `ISBN 5-17-002238-0, 2001` it reads `0022`, and
 * the year 22 is refused by the window below rather than by the pattern. **What
 * the window cannot refuse is the reason the anchor is here**: a non digit on
 * each side skips a digit run longer than four, so `20140825` yields nothing
 * where an unanchored pattern yields 2014, and 2014 is a year nothing after
 * this could tell from a real one.
 *
 * **It does not skip an identifier whose own groups are four digits, and that
 * is the exclusion rather than a corner case.** Measured over the 8 distinct
 * hyphen grouped ISBN literals under `frontend/`, 1 carries a group this takes,
 * and it is the ISBN in this reader's own fixtures: the pattern takes 9922 out
 * of `978-5-9922-1663-9`, which the window then refuses. **The window does not
 * close the class either**, which is worth saying because it looks as though it
 * would: an identifier carrying a group inside the window, which
 * `978-1-2001-…` does, still yields a year nothing here can tell from a real
 * one. **What bounds the exposure is where this is called from and not the
 * pattern**: `publish-info/year` and `title-info/date` and nothing else, so an
 * identifier reaches it by sitting inside a date element, which is a malformed
 * file rather than an ordinary one.
 *
 * **Applied here rather than at `readYear`**, so an implausible
 * `publish-info/year` falls through to `title-info/date` exactly as an absent
 * one does: each candidate is judged on its own, and the preference between
 * the two fields stays `readYear`'s.
 *
 * **The group and not the match**, because the match carries the delimiter that
 * anchored it: `25/08/2014` matches `/2014` and `Number("/2014")` is `NaN`. The
 * window refuses a `NaN`, so taking the match would cost a refusal rather than
 * a wrong year, and a refusal on a date this reader can read is still wrong.
 *
 * Written with a leading `(?:^|\D)` rather than a lookbehind: a lookbehind is a
 * syntax error at parse time on engines older than the one the archived door
 * needs, and this door reads a bare file that does not need that engine, so the
 * whole module would fail to load rather than one path failing to work.
 */
function yearIn(raw: string | null): number | null {
  const match = /(?:^|\D)(\d{4})(?!\d)/.exec(raw ?? "");
  return match === null ? null : plausibleYear(Number(match[1]));
}

/**
 * What `publish-info` says the ISBN is.
 *
 * **One element and sometimes several numbers.** 10 of 18 corpus files carry an
 * `<isbn>` and 2 of those 10 hold two of them separated by a comma, which is a
 * book printed in a joint edition by two publishers. Splitting is why the second
 * of a pair is still reachable, and it is why the first is found at all:
 * `parseIsbn` normalises by stripping punctuation, so an unsplit pair reaches it
 * as one 26 character number and parses as nothing.
 *
 * Everything goes through `parseIsbn`, so `Тут пишем ISBN код книги, если есть`,
 * which is what one file in the corpus has in that element, is not an ISBN.
 */
function readIdentifiers(publishInfo: Element | null): OpfIdentifier[] {
  const raw = text(firstNamed(publishInfo, "isbn"));
  if (raw === null) return [];
  return raw
    .split(/[,;]/)
    .map((part) => ({ scheme: "isbn", value: part.trim() }))
    .filter((identifier) => identifier.value !== "");
}

/**
 * Read a FictionBook document's header, or `null` when it is not one.
 *
 * Pure: it takes the text and returns a record, and it knows nothing about
 * files, archives or the API. `null` rather than a throw for the reason
 * `readOpf` gives: there is nothing a caller could do differently for each of
 * the ways a document can fail to be one.
 *
 * **`title-info` and never `src-title-info`.** The second holds the same fields
 * for the work in its original language, and 3 of 18 corpus files carry one; a
 * reader taking whichever came first would file a Russian translation of Gaiman
 * under its English title for some files and its Russian title for others.
 */
export function readFb2Description(xml: string): OpfRecord | null {
  // The entity refusal `fileReaders.declaresEntities` states, applied for the
  // same reason and with its own count: expansion happens inside the engine
  // before any code here runs, so a byte cap on the read does not reach it.
  // 0 of 18 corpus files contain `<!ENTITY`, and 0 carry a `<!DOCTYPE` at all.
  if (declaresEntities(xml)) return null;
  const header = headerDocument(xml);
  if (header === null) return null;

  const document = new DOMParser().parseFromString(header, "application/xml");
  // Both halves are needed. A parse error yields a document whose root is
  // `parsererror`, and a well formed document that is not a FictionBook yields
  // a root that is simply something else.
  const root = document.documentElement;
  if (!root || root.localName !== "FictionBook") return null;

  const description = firstNamed(root, "description");
  if (description === null) return null;
  const titleInfo = firstNamed(description, "title-info");
  if (titleInfo === null) return null;
  const publishInfo = firstNamed(description, "publish-info");

  const identifiers = readIdentifiers(publishInfo);
  const { seriesName, seriesIndex } = readSeries(titleInfo);

  return {
    // No package document, so no package version. Null rather than the
    // FictionBook namespace's own 2.0 or 2.1, which is a different fact under
    // a name that already means something else.
    version: null,
    title: text(firstNamed(titleInfo, "book-title")),
    // FB2 has no second title element. See this module's docstring.
    subtitle: null,
    authors: readAuthors(titleInfo),
    identifiers,
    isbn: firstIsbn(identifiers),
    publisher: text(firstNamed(publishInfo, "publisher")),
    year: readYear(titleInfo, publishInfo),
    language: text(firstNamed(titleInfo, "lang")),
    description: collapse(text(firstNamed(titleInfo, "annotation"))),
    seriesName,
    seriesIndex,
  };
}

function firstIsbn(identifiers: readonly OpfIdentifier[]): string | null {
  for (const identifier of identifiers) {
    const isbn = parseIsbn(identifier.value);
    if (isbn !== null) return isbn;
  }
  return null;
}

/**
 * Read one bare `.fb2`.
 *
 * **A prefix of the file and never the file.** `MAX_HEADER_BYTES` off the front
 * is what a `Blob.slice` costs, so picking a folder of 5 MB novels reads a few
 * kilobytes of each rather than all of them. The archived door reads the same
 * number of bytes by the same argument.
 *
 * Never returns a failure for anything but the file's own content. A read that
 * rejects is the disk rather than the book, and `ScanPage` already reports that
 * as one entry's unreadable file.
 */
export async function readFb2(file: Blob): Promise<Fb2Reading> {
  return fromBytes(
    new Uint8Array(await file.slice(0, MAX_HEADER_BYTES).arrayBuffer()),
    file.size > MAX_HEADER_BYTES,
  );
}

/**
 * The header out of however the bytes arrived.
 *
 * **Both doors decide here**, so a document too long to read is told apart from
 * one that is not a FictionBook in one place rather than two.
 *
 * **`more` is asked of the door rather than worked out from `raw.length`.** A
 * prefix that filled its bound is not the same fact as a file continuing past
 * it: a document of exactly `MAX_HEADER_BYTES` fills the bound with nothing cut
 * off, and calling that one too large tells a member their whole malformed file
 * was too long to read. Each door knows the difference for free, the bare one
 * from the file's size and the archived one from `ZipPrefix.partial`.
 *
 * **Three conditions, and naming one of them as the discriminator is how the
 * other two stop being checked.** There are bytes past the ones read, the prefix
 * opens a `<description`, and the prefix does not close it. Drop the first and a
 * short broken file is called too large; drop the third and so is an RSS feed,
 * which has a `<description>` of its own and closes it. Each condition has its
 * own arm in the tests, because a comment that justifies a guard by one of its
 * several conditions is a comment a reviewer agrees with while the hole
 * survives.
 */
function fromBytes(raw: Uint8Array, more: boolean): Fb2Reading {
  const xml = decode(raw);
  const metadata = readFb2Description(xml);
  if (metadata !== null) return { ok: true, metadata };
  const truncated =
    more && xml.includes("<description") && !DESCRIPTION_END.test(xml);
  return { ok: false, failure: truncated ? "too-large" : "not-an-fb2" };
}

/**
 * Read a `.fb2.zip`, which is the same document deflated.
 *
 * **The entry is found by name and not by position.** An archive here holds one
 * FictionBook, so the first entry whose name ends `.fb2` is it; an archive with
 * no such entry is not one of these whatever else it holds, which is the same
 * answer a CBZ gets from `readEpub` and for the same reason.
 */
export async function readFb2Archive(file: Blob): Promise<Fb2Reading> {
  try {
    const archive = await openZip(file);
    const entry = archive.entries.find((candidate) =>
      candidate.name.toLowerCase().endsWith(".fb2"),
    );
    if (entry === undefined) return { ok: false, failure: "not-an-fb2" };

    // The head of the entry and not the entry. `MAX_ARCHIVED_BYTES` is still
    // checked, so an entry too large to be a FictionBook is still refused;
    // what stops is the inflating of everything past the header.
    const head = await archive.readPrefix(entry, {
      prefix: MAX_HEADER_BYTES,
      limit: MAX_ARCHIVED_BYTES,
    });
    return fromBytes(head.bytes, head.partial);
  } catch (error) {
    if (error instanceof ZipError) {
      return { ok: false, failure: zipFailureAs(error, "not-an-fb2") };
    }
    throw error;
  }
}
