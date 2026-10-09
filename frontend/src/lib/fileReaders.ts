import type { CbzFailure } from "./cbz";
import type { EpubFailure } from "./epub";
import type { Fb2Failure } from "./fb2";
import type { MobiFailure } from "./mobi";
import type { PdfFailure } from "./pdf";
import { supportedExtension, type SupportedExtension } from "./fileName";

/**
 * Which reader, if any, opens a file of a given extension.
 *
 * **A registry rather than a branch at the call site**, and the branch it
 * replaces said so itself: "a reader for another format joins here". Two
 * tickets joining there at once is two trios editing one expression, which is
 * the collision a worktree does not prevent. Here each format is a key.
 *
 * **Every reader answers the same shape**, which is what lets the page treat
 * them alike: a record it can draft from, or a reason a member can be told.
 * `FileFailure` is the union of every reader's reasons. A reader adding one
 * widens it here, and `FILE_FAILURES` in the scan page is a total `Record` over
 * it, so a reason with no sentence for a member is a compile error rather than
 * a file reported with the last arm's.
 *
 * **The union overlaps and that is the point.** `damaged`, `protected` and
 * `too-large` mean the same thing to a member whichever reader said them, so
 * they are one name each rather than one per format; only the "this is a
 * different kind of file" reason is per format, because that is the sentence
 * that tells somebody to look at what they picked.
 * That is the contract `backend/decoders.py` states for the catalogue readers,
 * arrived at independently on this side and worth naming as the same idea.
 *
 * **An extension may be readerless only where the picker routes the file
 * away**, and audio is the one such route: `ScanPage.pickFiles` splits a pick
 * on `fileName.FORMAT_FOR_EXTENSION` calling a file an audiobook and hands that
 * half to `lib/audiobook.ts`, because which files are one book is decided
 * before any of them is drafted from.
 *
 * **So `.m4b` and `.mp3` never reach `readerFor` at all**, and the `null` it
 * answers for them is consulted by nothing. Every other supported extension has
 * a reader, and `tests/lib/fileReaders.test.ts` asks `readerFor` itself rather
 * than reading this map, so an extension the door drops fails there too.
 */
export type FileFailure =
  CbzFailure | EpubFailure | Fb2Failure | MobiFailure | PdfFailure;

/** One identifier a file carried, with whatever the file said it was. */
export interface FileIdentifier {
  /**
   * How to read `value`, or `null` where nothing said. **`opf.ts` is the only
   * reader that takes this from the file**, as `opf:scheme` in EPUB 2 or the
   * `identifier-type` refinement in EPUB 3, and it is also the only place that
   * interprets it, in `readIsbn`. The others label it themselves, because their
   * formats carry the identifier in a field whose name already says what it is:
   * `cbz.ts`, `mobi.ts` and `fb2.ts` write a literal, and `pdf.ts` infers it
   * from the value, XMP naming no scheme of its own.
   */
  readonly scheme: string | null;
  readonly value: string;
}

/**
 * What a reader says one book is, whichever format it read.
 *
 * **Not one format's record, which is what a sixth reader has to know before
 * it fills any of this in.** 10 of the 11 fields go through
 * `ScanPage/types.draftFromFile` into `BookLookup` one line each, and only
 * `identifiers` does not, so what a field holds is decided by what this app
 * stores rather than by what any format spells. 6 of them carry a Dublin Core
 * element's name, and every one is normalised rather than copied. The other 5
 * name nothing in OPF at all: `subtitle` is a `title-type` refinement
 * resolved, `isbn` is a parsed and check digit tested ISBN drawn from the
 * identifiers whatever labelled them, `year` is a single number windowed out
 * of whichever date the format offers, and the two series fields are Calibre's
 * own `meta` names or an EPUB 3 collection.
 *
 * **So the name is the family's and never a format's**, beside `FileReader`,
 * `FileReading` and `FileFailure`. `tests/lib/fileReaders.test.ts` holds that
 * against every module importing this one; `docs/decisions.md` carries why it
 * had to be bought rather than chosen.
 *
 * **It lives here rather than in `opf.ts` so that the author of a sixth reader
 * does not import the EPUB module to say what a book is.** `opf.ts` reads it
 * back from here for the same reason: the format that shaped this record is a
 * producer of it like any other, not its owner.
 */
export interface FileMetadata {
  readonly title: string | null;
  readonly subtitle: string | null;
  /**
   * Separate values, in document order.
   *
   * **Not one string.** A creator is one person and the file already separates
   * them, so joining here would throw away a fact the file supplied and make
   * every later reader guess it back.
   */
  readonly authors: readonly string[];
  readonly identifiers: readonly FileIdentifier[];
  /** Canonical ISBN-13, from whichever spelling the format carried one in. */
  readonly isbn: string | null;
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly description: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
}

export type FileReading =
  | { readonly ok: true; readonly metadata: FileMetadata }
  | { readonly ok: false; readonly failure: FileFailure };

/**
 * What every reader is, and the three rules none of them stated for itself.
 *
 * **A reader never throws for anything the file did.** A picked file that is
 * not what it claimed is one entry's failure, which is what lets a member point
 * at a folder and get a queue rather than an error page. Only a bug in a reader
 * throws. That distinction is load bearing and nothing enforces it:
 * `ScanPage/hooks.ts` catches everything a reader throws and reports the file
 * as unreadable, so a reader that throws for a bad file is downgraded in
 * silence rather than found.
 *
 * **A file that carried no metadata is `ok` with a record of nulls, never a
 * failure.** `FileFailure` has no name for it on purpose: the scan page sees no
 * title and falls to `lib/fileName.ts`, which for a PDF is the ordinary outcome
 * rather than the exception. A reason here would put a sentence in front of a
 * member for the common case.
 *
 * **A field the file did not give is `null` and never `""`.** `FileMetadata` says
 * every field is absent rather than empty, and a caller reading `record.title`
 * to decide whether the file named one would take `""` for a title.
 *
 * Stated here rather than at each reader, so that the author of a sixth meets
 * them at the type instead of by reading five modules.
 */
export type FileReader = (file: Blob) => Promise<FileReading>;

/**
 * Readers by extension, loaded on demand.
 *
 * **Each entry imports its own module**, so a format nobody picked costs no
 * bytes: the import route is a page most sessions never open, and a reader for
 * a format this member does not own should not be in the chunk either.
 *
 * A `Partial` because most extensions have no reader, which is the honest
 * shape: a total map would need a `null` per format and would read as though
 * the absent ones were an oversight.
 */
export const READERS: Partial<
  Record<SupportedExtension, () => Promise<FileReader>>
> = {
  ".epub": async () => (await import("./epub")).readEpub,
  // **One reader under three keys**, because `.mobi`, `.azw` and `.azw3` are
  // the same container and `readMobi` reads no byte that says which. Three
  // entries rather than one shared thunk so that the map stays a map: an
  // extension is looked up here and nothing has to know that two of them are
  // aliases of a third.
  ".mobi": async () => (await import("./mobi")).readMobi,
  ".azw": async () => (await import("./mobi")).readMobi,
  ".azw3": async () => (await import("./mobi")).readMobi,
  // **Two keys and two functions, where the Amazon container has three keys and
  // one.** A `.fb2` is the document and a `.fb2.zip` is that document inside an
  // archive, so what differs is the front half rather than the extension: one
  // reads a prefix off the disk, the other opens a zip. Both end in the same
  // parse.
  ".fb2": async () => (await import("./fb2")).readFb2,
  ".fb2.zip": async () => (await import("./fb2")).readFb2Archive,
  ".cbz": async () => (await import("./cbz")).readCbz,
  // **A reader whose ordinary answer is a record of nulls.** Most PDFs carry
  // no usable title, and that is `ok` here rather than a failure: an empty
  // record leaves the caller on the filename path, which is where an extension
  // with no reader leaves it too. Same outcome, reached with a reader present.
  ".pdf": async () => (await import("./pdf")).readPdf,
};

/** The reader for this file, or `null` if its name says nothing opens it. */
export async function readerFor(name: string): Promise<FileReader | null> {
  const extension = supportedExtension(name);
  if (extension === null) return null;
  const load = READERS[extension];
  return load ? await load() : null;
}
