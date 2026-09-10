/**
 * The Google Play Books library inside a Google Takeout archive.
 *
 * **Read against a real export taken 2026-09-10**, 37,684,641 bytes over 48
 * entries, none of them a directory, so 48 files and 24 books. That date is
 * the fact here that goes stale: Google documents none of this and changes it
 * without notice, so every number below is what one archive held on one day
 * rather than a specification.
 *
 * ## What the archive is, and what it is not
 *
 * `Takeout/Google Play Books/<Title>/<Title>.html` and `<Title>.pdf`, one pair
 * per book, and nothing else. **There is no JSON of any kind**, which the
 * ticket this was built from assumed there was.
 *
 * **The files named `.pdf` are EPUBs.** All 24 are a zip whose first entry is a
 * stored `mimetype` reading `application/epub+zip`. So this is not a new format
 * reader: it is an archive walker that decides what a file is from its content
 * and hands each book to `epub.readEpub`, which already exists.
 *
 * **Which is why it reads in the browser rather than in the backend's import
 * seam**, where the ticket first put it. That seam is fed decoded text and this
 * archive is 37 MB of the member's own books: uploading it to be unzipped
 * server side is exactly the custody `epub.ts` refuses to take. What a reader
 * per service buys there is a CSV; what it would cost here is the books.
 *
 * ## The signature is a pair, not a folder name
 *
 * Takeout localises its folder names to the account's language, so
 * `Takeout/Google Play Books` is one spelling of a name this cannot enumerate.
 * What it matches instead is structural and the same in every language: an
 * `.html` entry with exactly one same named sibling, whose text carries a
 * Google Books volume id. A pair whose sidecar carries no volume id is not a
 * Play Books book and is counted rather than read further.
 *
 * **The sibling's extension is not required to be `.pdf`.** Google mislabels
 * these files by accident, and a reader keyed on the mistake stops working on
 * the day it is corrected. This one starts working better: an entry named
 * `.epub` passes the same sniff.
 *
 * **The cost, stated because it is real**: an archive holding other Takeout
 * products is searched for that shape, so an unrelated `.html` with a same
 * named sibling is parsed once, bounded by `MAX_SIDECAR_BYTES`, discarded, and
 * counted in `skipped`. No other entry's bytes are read at all. What is given
 * up is the ability to say "this zip is a Takeout with no books in it", because
 * the only signature trusted here is a book itself: such an archive answers
 * `not-a-takeout`, the same as a zip that is not a Takeout, and its `skipped`
 * count goes with the answer.
 *
 * ## What a member is told
 *
 * **An entry that cannot be read is one refused book and never a broken
 * import**, which is the rule `docs/device-libraries.md` states for a store.
 * Every outcome here is a value: the archive fails as a whole only when it is
 * not a readable zip or holds no book pair at all, and everything else is a
 * count or a named refusal beside the title it belongs to.
 *
 * Measured on the export above, by walking it with a second implementation
 * rather than this one: **23 books and 1 refusal**, nothing skipped, nothing
 * ignored, and 94.9% of the inflation budget unspent, the reads inside the
 * books included. The refused file is an EPUB
 * whose `mimetype` entry reads `application/epub+zip\r\n`, a trailing newline
 * where OCF requires that entry stored, first and exact.
 *
 * **A refusal is not proof the file was broken**, and this part is an
 * inference rather than a measurement. Every one of the 24 sidecars carries
 * `.narrator`, `.audio-bookmark` and `.document-position` rules in its
 * stylesheet, which no book in that export uses, so the same template is
 * evidently written for audiobooks and for documents a member uploaded. **No
 * such entry was in the archive read**, so what is measured is the stylesheet
 * and not the behaviour. It is still the reason a pair with no readable EPUB is
 * not imported from its sidecar alone, which would otherwise file an audiobook
 * as an ebook on the strength of a sidecar that cannot tell them apart.
 *
 * ## What this archive cannot supply
 *
 * - **An ISBN, anywhere.** The EPUB identifiers are UUIDs and Project
 *   Gutenberg URLs. The volume id is the only usable key, and it is one this
 *   app already speaks: `google_books.py` takes it verbatim.
 * - **Authors as separate values, from the sidecar.** Its author line is one
 *   string. The EPUB beside it carries `dc:creator` separately, 23 of 24, and
 *   `metadata.authors` is that. **Neither is parsed out of the title**, and the
 *   export gives both halves of that reason: 1 book in 24 has no author in
 *   either place and its title names the scanner that made the file, so a title
 *   split invents a person out of a machine; 2 more carry their author's name
 *   inside the title as well as in the author line, which is what makes such a
 *   split look like it works.
 * - **A note's date.** It is written as three lines, a label, a day and a
 *   clock time, and a timezone spelled out as a name. Localised prose, and a
 *   timezone written as a name in the account's language is not a timestamp. A
 *   wrong parse dates a member's own note wrongly, so nothing here parses it.
 * - **The words of an annotation.** The passage a highlight marks is the book's
 *   text, which this app takes no custody of, and the member's note beside it
 *   is their own words with nowhere yet to go: `kobo.ts` refuses a read status
 *   for the same reason, that whether an import writes one is a decision about
 *   the import flow. Both are counted and neither is carried out of the parse.
 *   Measured: 15 annotations over 8 books, every one of them a highlight with
 *   an empty note.
 */

import { boundText } from "./bookBounds";
import { readEpub, type EpubFailure } from "./epub";
import type { FileMetadata } from "./fileReaders";
import {
  openZip,
  ZipError,
  zipFailureAs,
  type ZipArchive,
  type ZipEntry,
} from "./zip";

/**
 * How much one sidecar may inflate to.
 *
 * Measured at 3,643 bytes over the 24 in that export, smallest 2,434. 256 KiB
 * is seventy times the largest, which leaves room for a member who highlighted
 * a great deal and still refuses a file that is not a page of metadata.
 */
const MAX_SIDECAR_BYTES = 256 * 1024;

/**
 * How much one book file may inflate to.
 *
 * Measured at 13,528,679 bytes, median 741,527. 32 MiB is 2.4 times the
 * largest, and it is a bound on **output**, so an entry declaring a small size
 * and inflating to gigabytes is stopped by this rather than by the claim.
 *
 * **The peak this reader holds is about twice it**, which the first draft of
 * this paragraph understated: the inflated entry and the `Blob` built over it
 * are two copies, both live across the awaited read, and `readEpub` then
 * inflates up to 4.06 MiB more inside. So one book at a time costs up to about
 * 68 MiB and is released before the next is touched. The whole file has to be
 * in hand because a zip is read from its end.
 */
const MAX_BOOK_BYTES = 32 * 1024 * 1024;

/**
 * How much more than its own size the archive may inflate to, plus one file's
 * ceiling.
 *
 * **The second half of that sentence is not a hedge and the figure is
 * measured.** `epub.readSpending` bounds a package document at
 * `MAX_PACKAGE_BYTES` rather than at what is left, so a document under that
 * ceiling is read whole however little remains and the overspend is noticed at
 * the next pair. Measured by the security seat against this module: one book in
 * a 5,197 byte archive inflates 4,194,501 bytes, 807 times, and is accepted.
 *
 * **It is one shot rather than per book, and that is the whole difference.**
 * Fifty of the same book inflate 8,389,002 against an allowance of 5,181,840
 * and 48 of them are refused, so the absolute overspend is about 4.06 MiB
 * whatever the archive holds. The same 4.06 MiB is reachable by picking one
 * crafted `.epub` on the scan page, which is `epub.ts`'s own per file bound.
 *
 * **Closing it in code was refused rather than missed**: passing the remainder
 * down as the ceiling would charge an honestly oversized package document
 * against a budget it never spent, which is the case `readSpending`'s declared
 * size gate exists to keep free. A stated bound that quietly stops being the
 * bound is this repository's own named failure, so the sentence carries it.
 *
 * **A ratio and not a number of bytes, because the honest case scales exactly
 * the way the attack does.** A total byte ceiling that a member with 500 books
 * does not hit is one no bomb hits either: that export is 24 books and inflates
 * to 38,010,932 bytes, so a library ten times the size is ten times the total,
 * and any figure between the two refuses a real library rather than a crafted
 * file. `backend/backup.py` reached the same pair of instruments for the same
 * question, a per entry ceiling and a ratio, and this reader has no use for its
 * third, because it holds one book at a time. `MAX_BOOK_BYTES` says what that
 * comes to and is the only place that says it.
 *
 * **The ratio is what a Takeout cannot fake.** An EPUB is already a zip of
 * deflated entries, so an archive of them barely compresses: that export
 * measures 1.009, 38,010,932 bytes out of 37,684,641. 20 is nineteen times the
 * headroom a real archive uses, and a zip bomb needs three orders of magnitude
 * more than that to be worth writing.
 *
 * **A read that was refused is charged the ceiling it was granted**, which is
 * the half two review rounds were spent on. `zip.ts` refuses an entry by
 * inflating it to that ceiling and then throwing the bytes away, so charging
 * what came back charges nothing for the most expensive thing either reader can
 * do, and a crafted archive repeats it per entry. Measured by the security seat
 * against this module rather than against a description of it: with the outer
 * read charged that way and the inner one not, a 1,006,742 byte archive
 * inflated 852,026,600 bytes, 846 times its own size, and never spent its
 * allowance.
 *
 * **What it charges.** Every entry either reader inflates, in the outer archive
 * and inside each book, arriving or refused: `readEpub` is handed a `charge`
 * and `epub.readSpending` applies the same rule to its container and package
 * document. What it does not charge is the 20 byte signature read, and each
 * archive's central directory, which is stored rather than deflated and so is a
 * slice of bytes already paid for.
 */
const MAX_INFLATION_RATIO = 20;

/**
 * The OCF signature, and it is a signature rather than a name.
 *
 * EPUB requires this entry first in the archive, stored uncompressed, with
 * exactly these bytes and no padding. All three are checked, so what identifies
 * a book here is a magic number at a fixed position and not a string that could
 * appear anywhere in a member's file.
 *
 * **Exact costs one real book in 24 and the leniency would cost more.** The
 * refused file carries a trailing `\r\n`; accepting bytes that merely start
 * with this would accept any zip whose first stored entry begins with it, and
 * `readEpub` does not read this entry at all, so nothing downstream would
 * notice. The book is not lost silently: it is named in `refused` with its
 * title, which is the sentence a member can act on.
 */
const EPUB_MIMETYPE = "application/epub+zip";

/** Method 0, stored. Spelled here because the sniff is about the storage. */
const METHOD_STORED = 0;

/**
 * A Google Books volume id: twelve characters of the URL safe alphabet.
 *
 * Measured over all 24, every one twelve characters and every one distinct,
 * including the two pairs of titles that differ only by a `(1)` suffix. It is
 * a bound rather than a list of spellings, and it is what tells the volume id
 * line of the sidecar's metadata block from the reading state line beside it
 * without matching an English label that a German export does not carry.
 */
const VOLUME_ID = /^[A-Za-z0-9_-]{12}$/;

/**
 * The reading state, and this one is English only.
 *
 * There is no structure to read it from: it is a sentence in a `meta-entry`
 * div, in the language the export was taken in. So a line that is not the
 * volume id and does not match this leaves `finished` as `null`, which says the
 * sidecar carried a line this reader could not identify rather than saying the
 * member has not finished the book. `TakeoutBook.finished` states what that
 * costs, which is more than the language.
 */
const FINISHED = /\bfinished\b/i;

/** Why an archive yielded no library at all. */
export type TakeoutFailure =
  /** Not a zip, so not a Takeout archive. */
  | "not-an-archive"
  /** A zip holding no Google Play Books book pair. */
  | "not-a-takeout"
  /** A zip whose own offsets do not agree with its length. */
  | "damaged"
  /** An entry is encrypted. */
  | "protected"
  /** The archive inflates past what this will read. */
  | "too-large"
  /** Zip64, spanned, or a compression method this does not implement. */
  | "unsupported"
  /** This browser has no `DecompressionStream("deflate-raw")`. */
  | "no-inflate";

/** One book the export says this member has. */
export interface TakeoutBook {
  /**
   * The pair's path inside the archive, without the extension, which is what
   * makes it unique: two books share one folder in that export, told apart by
   * a `(1)` on the file's own name. Grouping by folder, or by title, loses one
   * of them, and their volume ids show they are different editions.
   */
  readonly path: string;
  /** The Google Books volume id. The only identifier the archive carries. */
  readonly volumeId: string;
  /** What the sidecar's heading called it, which is Google's own title. */
  readonly title: string | null;
  /** The sidecar's author line: one string, unsplit, never from the title. */
  readonly author: string | null;
  /**
   * Whether the member finished it: `false` where the sidecar carried no
   * metadata line but the volume id, and `null` where it carried one this
   * reader could not identify.
   *
   * **`null` is wider than "a language this could not read", and saying so is
   * the point.** A line Play Books adds for something else entirely, a purchase
   * date say, lands here too and turns every book in an English export into
   * "not known". That is the safe direction and it is not a free one.
   */
  readonly finished: boolean | null;
  /** Passages the member marked. A count: their text is the book's. */
  readonly annotations: number;
  /** What the EPUB beside the sidecar said about itself. */
  readonly metadata: FileMetadata;
}

/** One book the export names and this could not read. */
export interface TakeoutRefusal {
  /** The pair's path, as `TakeoutBook.path`. */
  readonly path: string;
  /** What the sidecar called it, so a member is told which book. */
  readonly title: string | null;
  /** Why, in `readEpub`'s own words. */
  readonly failure: EpubFailure;
}

export interface TakeoutLibrary {
  /**
   * The books, which can be none of them.
   *
   * **An export whose every file was refused is a library with no books in it
   * and not an archive with nothing in it**, `kobo.ts`'s distinction: the two
   * are different sentences, and `refused` is what makes the true one sayable.
   */
  readonly books: readonly TakeoutBook[];
  /** The books named in the export whose file could not be read. */
  readonly refused: readonly TakeoutRefusal[];
  /**
   * Pairs that were read and were not a Play Books book: a sidecar carrying no
   * volume id, or one too large to be a page of metadata.
   *
   * **It is answered rather than dropped, and that is the likely future.** The
   * day Google stops writing the volume id where this looks, every pair lands
   * here, and an archive reporting `not-a-takeout` with 24 of these would be
   * telling a member their own export is not one. So a count here keeps the
   * answer `ok`; see `readTakeoutArchive`.
   *
   * **There is no count of what was never read.** Entries that are not half of
   * a pair are most of a Takeout, their unit is zip entries rather than books,
   * and no member can act on the number, so it is not reported.
   */
  readonly skipped: number;
}

export type TakeoutReading =
  | { readonly ok: true; readonly library: TakeoutLibrary }
  | { readonly ok: false; readonly failure: TakeoutFailure };

const utf8 = new TextDecoder("utf-8");

/**
 * What is left of the archive's inflation allowance.
 *
 * A budget rather than a count of entries: what costs a member's tab is bytes
 * inflated, and an archive of a thousand small books is cheaper than one of ten
 * large ones.
 */
class Budget {
  private left: number;

  constructor(archiveBytes: number) {
    this.left = archiveBytes * MAX_INFLATION_RATIO;
  }

  /** What is left to inflate with. Compared against a declared size. */
  get remaining(): number {
    return this.left;
  }

  /** What this read may produce: the caller's own ceiling, or what is left. */
  ceiling(limit: number): number {
    return Math.max(0, Math.min(limit, this.left));
  }

  charge(bytes: number): void {
    this.left -= bytes;
  }
}

/** One `.html` entry and the single sibling named beside it. */
interface Pair {
  readonly path: string;
  readonly sidecar: ZipEntry;
  readonly book: ZipEntry;
}

/** A zip path minus its last extension, or `null` where it has none. */
function stem(name: string): string | null {
  const cut = name.lastIndexOf(".");
  const slash = name.lastIndexOf("/");
  return cut > slash + 1 ? name.slice(0, cut) : null;
}

/** The extension, lower cased, of a name `stem` answered for. */
function extension(name: string): string {
  return name.slice(name.lastIndexOf(".")).toLowerCase();
}

/**
 * The `.html` and sibling pairs, and how many entries were not part of one.
 *
 * **A group of three is not a pair**, and neither is a group of two `.html`
 * entries: a zip may name one path twice, and a group this cannot resolve to
 * one sidecar and one file is left alone rather than guessed at.
 *
 * **A name that walks out of its own directory is not a pair either.** Nothing
 * here writes a file, so `../../x` cannot escape onto a disk, but it can name
 * a path this reader would then report to a member as a book in their export.
 */
function pairsIn(entries: readonly ZipEntry[]): Pair[] {
  const groups = new Map<string, ZipEntry[]>();
  for (const entry of entries) {
    const key = entry.name.endsWith("/") ? null : stem(entry.name);
    if (key === null || !isPlainPath(entry.name)) continue;
    const group = groups.get(key);
    if (group) group.push(entry);
    else groups.set(key, [entry]);
  }

  const pairs: Pair[] = [];
  for (const [path, group] of groups) {
    const sidecars = group.filter((entry) => extension(entry.name) === ".html");
    const others = group.filter((entry) => extension(entry.name) !== ".html");
    // **Exactly one of each, and both halves of that are load bearing.** A zip
    // may name one path twice, so two sidecars is a group this cannot resolve
    // to one book any more than three files is, and taking the first would pick
    // between two titles by directory order.
    if (sidecars.length !== 1 || others.length !== 1) continue;
    pairs.push({ path, sidecar: sidecars[0]!, book: others[0]! });
  }
  return pairs;
}

/** Whether a zip path stays inside the directories it names. */
function isPlainPath(name: string): boolean {
  if (name.startsWith("/") || name.includes("\\")) return false;
  return !name.split("/").includes("..");
}

/** What one sidecar said, or `null` where it was not a Play Books sidecar. */
interface Sidecar {
  readonly volumeId: string;
  readonly title: string | null;
  readonly author: string | null;
  readonly finished: boolean | null;
  readonly annotations: number;
}

/**
 * The value under a label, where the sidecar writes both on their own lines.
 *
 * Both labelled blocks are shaped that way, `Volume ID\n<id>` and `by\n<name>`,
 * so the value is the first line after the first and the label is never read.
 * That is what keeps this independent of the language the export was taken in.
 */
function labelled(text: string | null | undefined): string | null {
  const lines = (text ?? "").split("\n").slice(1);
  return lines.map((line) => line.trim()).find((line) => line !== "") ?? null;
}

/**
 * Read one sidecar.
 *
 * **Parsed as HTML rather than as the XHTML it declares itself to be.** A
 * document parsed as `text/html` runs no script, fetches no external DTD and
 * expands only the named entities the HTML parser knows, so the entity
 * exposures `xmlEntities.declaresEntities` exists to refuse are not reachable
 * here. An XML parse would also lose the whole book to one unescaped `&`, which
 * is a member's own title rather than a broken file.
 */
function readSidecar(html: string): Sidecar | null {
  const document = new DOMParser().parseFromString(html, "text/html");

  let volumeId: string | null = null;
  let finished: boolean | null = false;
  for (const entry of document.querySelectorAll("div.meta-entry")) {
    const text = entry.textContent ?? "";
    const value = labelled(text);
    if (value !== null && VOLUME_ID.test(value)) {
      volumeId ??= value;
      continue;
    }
    // Not the volume id, so it is the sentence about reading state or one this
    // export has that no measured one did. Either way it is not `false`.
    if (FINISHED.test(text)) finished = true;
    else if (text.trim() !== "" && finished === false) finished = null;
  }
  if (volumeId === null) return null;

  return {
    volumeId,
    title: boundText("title", document.querySelector("h1")?.textContent),
    author: boundText(
      "author",
      labelled(document.querySelector("div.author")?.textContent),
    ),
    finished,
    annotations: document.querySelectorAll("div.annotation").length,
  };
}

/**
 * Whether this archive is an EPUB, asked of its bytes.
 *
 * The suffix is not asked, because the suffix is the thing this archive gets
 * wrong: 24 of 24 books in that export are named `.pdf`.
 */
async function isEpub(archive: ZipArchive): Promise<boolean> {
  const mimetype = archive.find("mimetype");
  if (mimetype === undefined || mimetype.method !== METHOD_STORED) return false;
  const first = archive.entries.every(
    (entry) => entry.headerOffset >= mimetype.headerOffset,
  );
  if (!first) return false;
  // **Both declared sizes, and the second is not decoration.** Asking for the
  // signature's length and comparing what comes back would refuse an entry two
  // bytes longer as `too-large`, which names a bomb rather than a file that is
  // not an EPUB. The entry is stored, so its two sizes are the same number, and
  // checking only the uncompressed one leaves an entry declaring 20 out and 31
  // in to trip `zip.ts`'s own compressed bound and reach a member as
  // `too-large` for the same wrong reason.
  if (
    mimetype.uncompressedSize !== EPUB_MIMETYPE.length ||
    mimetype.compressedSize !== EPUB_MIMETYPE.length
  ) {
    return false;
  }
  const bytes = await archive.read(mimetype, EPUB_MIMETYPE.length);
  // **The bytes, and not only their length.** Every impostor a test builds is
  // refused by the length above, so this line is the one no fixture reaches and
  // the one that decides: without it any zip whose first stored entry is called
  // `mimetype` and is 20 bytes long is an EPUB.
  return utf8.decode(bytes) === EPUB_MIMETYPE;
}

/**
 * Read one book file: the sniff, then the reader that already exists.
 *
 * **The inner archive is opened twice and the second open is the point.** This
 * one answers whether the bytes are an EPUB at all, which is the gate; the
 * second is `readEpub`'s own, because a reader takes a `Blob` and believes
 * nothing about where it came from. Handing it an opened archive would make it
 * trust this module's parse of a member's file.
 */
async function readBook(
  blob: Blob,
  budget: Budget,
): Promise<EpubFailure | FileMetadata> {
  let archive: ZipArchive;
  try {
    archive = await openZip(blob);
    if (!(await isEpub(archive))) return "not-an-epub";
  } catch (error) {
    if (error instanceof ZipError) return zipFailureAs(error, "not-an-epub");
    throw error;
  }
  // **The budget goes in with it.** Those two entries are deflated inside a
  // blob this reader already paid for, so what they inflate to is new bytes and
  // nothing outside `readEpub` can see how many.
  const reading = await readEpub(blob, (bytes) => budget.charge(bytes));
  return reading.ok ? reading.metadata : reading.failure;
}

/**
 * Read a Google Takeout archive's Play Books library, or say why there is not
 * one.
 *
 * Never throws for anything the file did, which is `fileReaders.FileReader`'s
 * contract for every reader here and the reason a member pointing at an archive
 * gets a queue rather than an error page. Only a bug in this module throws.
 */
export async function readTakeoutArchive(file: Blob): Promise<TakeoutReading> {
  let archive: ZipArchive;
  try {
    archive = await openZip(file);
  } catch (error) {
    if (error instanceof ZipError) {
      return { ok: false, failure: zipFailureAs(error, "not-an-archive") };
    }
    throw error;
  }

  const pairs = pairsIn(archive.entries);
  const budget = new Budget(file.size);
  const books: TakeoutBook[] = [];
  const refused: TakeoutRefusal[] = [];
  let skipped = 0;

  for (const pair of pairs) {
    const sidecar = await readPairSidecar(archive, pair, budget);
    // **A pair the budget stopped this reaching is a refusal and not a skip,
    // and the difference is what a member is told.** It is a book the export
    // carried; counting it as "not a Play Books book" would say the archive
    // held less than it did.
    if (sidecar === "too-large") {
      refused.push({ path: pair.path, title: null, failure: "too-large" });
      continue;
    }
    if (sidecar === "not-a-book") {
      skipped += 1;
      continue;
    }

    const read = await readPairBook(archive, pair, budget);
    if (typeof read === "string") {
      refused.push({ path: pair.path, title: sidecar.title, failure: read });
      continue;
    }
    books.push({
      path: pair.path,
      volumeId: sidecar.volumeId,
      title: sidecar.title,
      author: sidecar.author,
      finished: sidecar.finished,
      annotations: sidecar.annotations,
      metadata: read,
    });
  }

  // **`skipped` is in the condition, and omitting it was the likely future.**
  // The day Google moves the volume id, every pair lands in `skipped` and this
  // would tell a member their own export is not a Takeout. The cost is stated
  // rather than hidden: a zip holding one `a.html` beside one `a.css` now
  // answers `ok` with an empty library where it used to answer `not-a-takeout`.
  if (books.length === 0 && refused.length === 0 && skipped === 0) {
    return { ok: false, failure: "not-a-takeout" };
  }
  return { ok: true, library: { books, refused, skipped } };
}

/**
 * One entry's bytes, charged whether they arrive or not.
 *
 * **A read that throws is the expensive one, and charging what came back
 * charges nothing for it.** `zip.ts` refuses an entry by inflating it to the
 * ceiling and then throwing the bytes away, so a crafted archive repeats that
 * per entry for free. Charged the ceiling instead, a refusal costs what it may
 * have inflated. The declared size gates at each caller are the other half:
 * they mean an entry refused without inflating anything never reaches here.
 *
 * **`epub.readSpending` is the same three rules one level down**, and is a
 * second site rather than a shared helper because the two spend different
 * things: this one spends a running total, that one reports to whoever holds
 * one. Written the same way deliberately, because the rule is one rule.
 */
async function readCharged(
  archive: ZipArchive,
  entry: ZipEntry,
  limit: number,
  budget: Budget,
): Promise<Uint8Array<ArrayBuffer>> {
  const ceiling = budget.ceiling(limit);
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await archive.read(entry, ceiling);
  } catch (error) {
    budget.charge(ceiling);
    throw error;
  }
  budget.charge(bytes.length);
  return bytes;
}

/**
 * The sidecar half of one pair.
 *
 * **Three answers, because the two refusals are different sentences.** A
 * sidecar larger than a page of metadata is not one whatever the budget says,
 * and that is a pair this reader has no reason to think was a book. A sidecar
 * the budget cannot afford is a book the archive carried and this stopped
 * short of. Reading both off what the read threw would collapse them, since
 * `zip.ts` answers `too-large` for either.
 *
 * **What a lying directory still buys, since it is worth naming**: a sidecar
 * understating its size passes both gates, overruns the read and lands in
 * `not-a-book` where `too-large` is the true answer. A wrong word and not a
 * free read, because `readCharged` keeps the granted ceiling on the throw.
 */
async function readPairSidecar(
  archive: ZipArchive,
  pair: Pair,
  budget: Budget,
): Promise<Sidecar | "not-a-book" | "too-large"> {
  if (pair.sidecar.uncompressedSize > MAX_SIDECAR_BYTES) return "not-a-book";
  if (pair.sidecar.uncompressedSize > budget.remaining) return "too-large";
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await readCharged(archive, pair.sidecar, MAX_SIDECAR_BYTES, budget);
  } catch (error) {
    if (!(error instanceof ZipError)) throw error;
    // A sidecar that will not come out of the archive is not evidence there was
    // a book behind it: nothing has said yet that this pair is one.
    return "not-a-book";
  }
  return readSidecar(utf8.decode(bytes)) ?? "not-a-book";
}

/**
 * The book half of one pair, charged to the budget.
 *
 * **The declared size is asked first, because a refusal there inflated
 * nothing.** `readCharged` keeps a granted ceiling on any failure, which is
 * right for an entry whose directory lied and wrong for one that told the
 * truth about being too big: without this gate a single oversized book would
 * spend a small archive's whole allowance and refuse every book after it.
 */
async function readPairBook(
  archive: ZipArchive,
  pair: Pair,
  budget: Budget,
): Promise<EpubFailure | FileMetadata> {
  if (pair.book.uncompressedSize > MAX_BOOK_BYTES) return "too-large";
  if (pair.book.uncompressedSize > budget.remaining) return "too-large";
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await readCharged(archive, pair.book, MAX_BOOK_BYTES, budget);
  } catch (error) {
    if (error instanceof ZipError) return zipFailureAs(error, "not-an-epub");
    throw error;
  }
  return readBook(new Blob([bytes]), budget);
}
