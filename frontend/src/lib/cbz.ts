/**
 * A comic archive's metadata, read in the member's own browser.
 *
 * A CBZ is a zip of page images, so this is `lib/zip.ts` plus one entry:
 * `ComicInfo.xml`, the schema ComicRack defined and every reader after it
 * kept. **Endpaper never takes custody of a member's book file**, and
 * `lib/epub.ts` states that rule and why it is about custody rather than about
 * where bytes travel; nothing here is a second copy of it.
 *
 * **Most comics carry nothing, and that is the case this reader is shaped
 * around.** Measured 2026-09-07 over **81 CBZ archives** in the Internet
 * Archive's `comics` collection, read through that site's own zip listing
 * endpoint so that no page image was fetched: **6 of the 81 carry a
 * `ComicInfo.xml`** and the other 75 are pages and nothing else. The six come
 * from three uploads between them, so the figure says the document is rare and
 * does not say how rare. So an archive that says nothing is the ordinary
 * archive rather than a broken one, and what it gets is an empty record and
 * the filename path behind it. Only a file that is not an archive at all is a
 * failure here.
 *
 * **Lazy loaded**, for the reason `lib/epub.ts` gives: `fileReaders.ts` imports
 * it when a member picks a `.cbz`, so a session that never opens the scan page
 * pays for none of this.
 *
 * ## A single issue and a collected volume, which the ticket asked about
 *
 * **They come through identically, and the file is why.** `Series` plus
 * `Number` means "the Nth thing in this series" for an issue and for a
 * collected volume alike, and ComicInfo carries no field that separates them:
 * `Format` is free text a writer may leave blank, and `Count` counts the
 * series either way. Endpaper's `series_name` plus `series_index` says exactly
 * that and no more, so both become a row in one series at one index and a
 * member holding both has two rows to tell apart by hand. Inventing the
 * distinction here would be inventing a fact the file does not carry.
 *
 * **The file's own `Title` is the title, and the series and the number go to
 * the series columns.** That is what `dc:title` does for an EPUB, and this app
 * already renders the series line beside every title it shows: the library
 * list, the table's own series column and the book page's heading all print
 * `Saga, book 12` from `series_name` and `series_index`. So composing
 * `Saga #12` into the title as well prints the same two facts twice on three
 * surfaces, which is what the first draft of this module did.
 *
 * **The composition survives for the file that gives no `Title`**, which is
 * most single issues: there the series and the number are the only name the
 * object has, and `Saga #12` is what a comic catalogue calls it. `Series` with
 * no `Number` is the series alone.
 *
 * ## CBR: a parser is refused here, not a format
 *
 * **A CBR is a RAR archive, so a reader for one is a RAR decoder**, and this is
 * the module somebody would add it beside. Two reasons not to, and the second
 * is the one that settles it:
 *
 * 1. A WebAssembly decoder is a large payload on a route most sessions never
 *    open, bought for the one small metadata document read below.
 * 2. **The standard unrar source forbids using it to recreate the RAR
 *    compression algorithm.** That is not a free software licence, and this
 *    repository publishes an image. Owner's decision, 2026-09-05.
 *
 * **What a member holding one gets today is nothing**, and that is worth
 * stating precisely rather than as "it falls back": `.cbr` is not in
 * `fileName.SUPPORTED_EXTENSIONS`, so the picker counts it under
 * `fallback.skipped` and never queues it. `csv_import.FORMAT_GUESSES` does
 * read the word, so a CBR named in an export lands on `BookFormat.COMIC`
 * rather than on `OTHER`.
 *
 * ## What this cannot supply, stated as the exclusion
 *
 * **Page count and the cover: not read.** Both would mean opening a page
 * image, which is megabytes for a field the catalogue supplies.
 *
 * **Everybody but the writer.** `Penciller`, `Inker`, `Colorist`, `Letterer`,
 * `CoverArtist` and `Editor` are named by the schema and read by nothing here,
 * for the rule `opf.readAuthors` states at its own site: this tree has one
 * author field, and an illustrator filed as the author is a wrong fact. A
 * comic's artist is not less than its writer; there is nowhere to say so.
 *
 * **The month and the day.** The column holds a year.
 *
 * **Whether the entries are images.** This does not check, because the set of
 * image formats is open and refusing one nobody listed would refuse a real
 * comic. A zip that is not a comic yields an empty record and falls to its
 * name, which is what a comic carrying no `ComicInfo.xml` does anyway.
 */

import { parseIsbn } from "./isbn";
import { declaresEntities, type OpfIdentifier, type OpfRecord } from "./opf";
import { openZip, ZipError, type ZipArchive, type ZipFailure } from "./zip";

/**
 * How much `ComicInfo.xml` may inflate to.
 *
 * **Chosen rather than measured, and what it is chosen against is stated**,
 * because this repository holds no CBZ corpus. The fields read below are a few
 * hundred bytes; everything else a real file carries is the optional `<Pages>`
 * block, one `<Page>` element per page.
 *
 * **There is no per element bound and so no floor here, which is the honest
 * half.** Two of the eight attributes the schema gives a page, `Key` and
 * `Bookmark`, are unbounded strings, so a single element can be as long as the
 * document. With both empty a fully attributed element measures about 150
 * bytes, which puts a mebibyte at roughly 7,000 pages: an estimate, resting on
 * that assumption, and more pages than an archive of one comic has.
 *
 * It is a bound on **output**, so a document declaring itself small and
 * inflating to gigabytes is stopped by this rather than by the declaration.
 * `lib/zip.ts` carries that rule.
 */
const MAX_COMIC_INFO_BYTES = 1024 * 1024;

/** The entry, wherever it sits. Compared lowercased: writers differ on case. */
const COMIC_INFO_NAME = "comicinfo.xml";

/**
 * Why a file yielded nothing.
 *
 * A subset of `fileReaders.FileFailure`, and only `not-a-comic` is new. The
 * other five are names that union already carried, because a damaged archive
 * is damaged whatever format claimed it and a member reading the sentence does
 * not care which reader said so.
 *
 * **There is no reason here for "carried no metadata", deliberately.** That is
 * the ordinary archive, not a failure: it yields a record with nothing in it,
 * and the scan page says the file carried no title and falls to its name.
 */
export type CbzFailure =
  /** Not an archive at all, so nothing here can be a comic. */
  | "not-a-comic"
  /** A zip whose own offsets do not agree with its length. */
  | "damaged"
  /** Encrypted, which here means DRM, and DRM is out of scope. */
  | "protected"
  /** An entry inflates past what this will read. */
  | "too-large"
  /** Zip64, spanned, or a compression method this does not implement. */
  | "unsupported"
  /** This browser has no `DecompressionStream("deflate-raw")`. */
  | "no-inflate";

export type CbzReading =
  | { readonly ok: true; readonly metadata: OpfRecord }
  | { readonly ok: false; readonly failure: CbzFailure };

/**
 * A zip's refusal in the words a member needs.
 *
 * A `Record` rather than a switch, so a `ZipFailure` added to that closed union
 * is a type error here rather than a file that silently reports the last arm.
 */
const FROM_ZIP: Record<ZipFailure, CbzFailure> = {
  "not-a-zip": "not-a-comic",
  zip64: "unsupported",
  encrypted: "protected",
  unsupported: "unsupported",
  truncated: "damaged",
  "too-large": "too-large",
  "no-inflate": "no-inflate",
};

const utf8 = new TextDecoder("utf-8");

/**
 * What an archive with no readable `ComicInfo.xml` says, which is nothing.
 *
 * A function rather than a shared constant: `OpfRecord` is readonly to a
 * caller and its two arrays are still one object, so a module level literal
 * would hand every reading of every file the same two arrays.
 */
function nothing(): OpfRecord {
  return {
    version: null,
    title: null,
    subtitle: null,
    authors: [],
    identifiers: [],
    isbn: null,
    publisher: null,
    year: null,
    language: null,
    description: null,
    seriesName: null,
    seriesIndex: null,
  };
}

/**
 * The first entry named `ComicInfo.xml`, at any depth, or `undefined`.
 *
 * **The schema puts it at the archive root and this looks deeper anyway.** In
 * the 81 archive survey above, all 6 documents found were at the root and **40
 * of the 81 archives wrap every entry in a folder**, so the wrapped document
 * is a shape the corpus makes plausible and does not contain: this is chosen
 * against that, not measured. A root only match reads nothing on such an
 * archive and says nothing about why, which is the worse of the two failures.
 * First in central directory order, so an archive carrying two answers the
 * same way on every reader.
 *
 * Matched on the lowercased basename: `ComicInfo.xml` is the spelling the
 * schema names and it is not the only one written.
 */
function findComicInfo(archive: ZipArchive) {
  return archive.entries.find(
    (entry) => entry.name.toLowerCase().split("/").pop() === COMIC_INFO_NAME,
  );
}

/** The trimmed text of the first child element with this name, or `null`. */
function field(root: Element, name: string): string | null {
  // A sibling walk rather than `getElementsByTagName`, which searches the whole
  // subtree: a `<Pages>` block holds a `<Page>` per page and none of these
  // names may be answered from inside it.
  for (
    let child = root.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    if (child.localName !== name) continue;
    const value = child.textContent?.trim();
    return value ? value : null;
  }
  return null;
}

function toNumber(raw: string | null): number | null {
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

/**
 * The year, refusing the schema's own spelling of "unknown".
 *
 * ComicRack writes `-1` into its numeric fields where nothing is known, so a
 * reader taking the number at face value files a comic in the year minus one.
 * That is not this module bounding a value, which `lib/bookBounds.ts` does
 * downstream: it is reading the format correctly, because `-1` is not what the
 * file says the year is.
 */
function readYear(root: Element): number | null {
  const year = toNumber(field(root, "Year"));
  return year !== null && year > 0 ? year : null;
}

/**
 * The writers, separately.
 *
 * The schema's own separator is the comma, and **the exclusion is that a name
 * written in catalogue order is split by it**: a `Writer` of `Moore, Alan` is
 * two names here, because nothing in the field says which of the two shapes it
 * is in. The natural order is what the schema asks for and what real files
 * carry.
 *
 * A `Set` and not an array scan, for the reason `opf.readAuthors` gives at its
 * own site: the number of commas is the file's choice inside a bound measured
 * in mebibytes, so `includes` in this loop is quadratic in a number a member
 * supplied file decides.
 */
function readWriters(root: Element): string[] {
  const raw = field(root, "Writer");
  if (raw === null) return [];
  const seen = new Set<string>();
  const writers: string[] = [];
  for (const part of raw.split(",")) {
    const name = part.trim();
    if (name !== "" && !seen.has(name)) {
      seen.add(name);
      writers.push(name);
    }
  }
  return writers;
}

/**
 * What the object is called.
 *
 * The rule and the reason for it are in this module's own docstring, because
 * it is the one decision here a reader is likely to disagree with. **The file
 * always wins**: composing is what happens when it named nothing.
 */
function readTitle(
  series: string | null,
  number: string | null,
  storyTitle: string | null,
): string | null {
  if (storyTitle !== null) return storyTitle;
  if (series === null) return null;
  return number === null ? series : `${series} #${number}`;
}

/**
 * Read a `ComicInfo.xml`, or `null` when it is not one.
 *
 * Pure, and the same shape `opf.readOpf` has: takes the XML, returns a record,
 * knows nothing about zips or files. `null` rather than a throw, because
 * "this archive's `ComicInfo.xml` is not one" is the same outcome to a caller
 * as an archive that carried none.
 *
 * **Entities are refused before anything is read**, through the same
 * `opf.declaresEntities` the package document goes through and for the reason
 * stated there: expansion happens inside the engine's parser, before a node
 * exists to bound. A comic's metadata has no use for a DTD internal subset.
 */
export function readComicInfo(xml: string): OpfRecord | null {
  if (declaresEntities(xml)) return null;
  const document = new DOMParser().parseFromString(xml, "application/xml");
  // Both halves are needed. A parse error yields a document whose root is
  // `parsererror`, and a well formed document that is not a ComicInfo yields a
  // root that is simply something else.
  const root = document.documentElement;
  if (!root || root.localName !== "ComicInfo") return null;

  const series = field(root, "Series");
  const number = field(root, "Number");

  // The barcode field, which carries an ISBN on a collected volume and an
  // ordinary product code on an issue. `parseIsbn` decides which: a value
  // whose own check digit does not close is not an ISBN however it was
  // labelled, so nothing here has to know the difference.
  const gtin = field(root, "GTIN");
  const identifiers: OpfIdentifier[] =
    gtin === null ? [] : [{ scheme: "GTIN", value: gtin }];

  return {
    // The `package` element's version, which a ComicInfo has no counterpart
    // for. Left null rather than filled with the schema's own version, which
    // would be a different fact under the same name.
    version: null,
    title: readTitle(series, number, field(root, "Title")),
    // ComicInfo has no subtitle, and `Title` is the title rather than one: see
    // this module's docstring for why that took two attempts to get right.
    subtitle: null,
    authors: readWriters(root),
    identifiers,
    isbn: gtin === null ? null : parseIsbn(gtin),
    publisher: field(root, "Publisher"),
    year: readYear(root),
    language: field(root, "LanguageISO"),
    description: field(root, "Summary"),
    seriesName: series,
    seriesIndex: toNumber(number),
  };
}

/**
 * Read one comic archive's metadata.
 *
 * Never throws for anything the file did, for the reason `readEpub` states: a
 * picked file that is not a comic is one entry's outcome, which is what lets a
 * member point at a folder and get a queue rather than an error page. The one
 * thing it does not catch is a bug in this module.
 */
export async function readCbz(file: Blob): Promise<CbzReading> {
  try {
    const archive = await openZip(file);
    const entry = findComicInfo(archive);
    if (entry === undefined) return { ok: true, metadata: nothing() };

    const metadata = readComicInfo(
      utf8.decode(await archive.read(entry, MAX_COMIC_INFO_BYTES)),
    );
    // An unreadable `ComicInfo.xml` leaves the archive exactly where one that
    // never carried the entry stands, which is on its file name.
    return { ok: true, metadata: metadata ?? nothing() };
  } catch (error) {
    if (error instanceof ZipError) {
      return { ok: false, failure: FROM_ZIP[error.failure] };
    }
    throw error;
  }
}
