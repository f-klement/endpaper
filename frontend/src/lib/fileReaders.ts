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
export interface OpfIdentifier {
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
 * **The shape is an OPF package document's and the name says so, because that
 * is where it came from.** Four of the five reader modules parse no package
 * document: they translate their own format into this, which is what lets the
 * scan page draft from any of them without asking which opened the file. Each
 * of those four sets `version` to `null`, saying at its own site that its
 * format has no package document, which is the one field here that only a
 * package document can fill.
 *
 * **That field is what the name rests on, and nothing reads it**: measured over
 * `src/`, 6 write sites and 0 reads. So the argument for the name is the shape
 * rather than a caller, and whoever proposes deleting `version` is also
 * proposing renaming this.
 *
 * **It lives here rather than in `opf.ts` so that the author of a sixth reader
 * does not import the EPUB module to say what a book is.** `opf.ts` reads it
 * back from here for the same reason: the format that shaped this record is a
 * producer of it like any other, not its owner.
 */
export interface OpfRecord {
  /** The `package` element's own `version`. `"2.0"` or `"3.0"` in practice. */
  readonly version: string | null;
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
  readonly identifiers: readonly OpfIdentifier[];
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
  | { readonly ok: true; readonly metadata: OpfRecord }
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
 * **A field the file did not give is `null` and never `""`.** `OpfRecord` says
 * every field is absent rather than empty, and a caller reading `record.title`
 * to decide whether the file named one would take `""` for a title.
 *
 * Stated here rather than at each reader, so that the author of a sixth meets
 * them at the type instead of by reading five modules.
 */
export type FileReader = (file: Blob) => Promise<FileReading>;

/**
 * Whether a document declares its own entities, which a reader refuses to parse.
 *
 * **The one attack a reader cannot bound after the fact.** Expansion happens
 * inside the engine's parser, before any code here sees a node, so a document
 * declaring nested entities is measured in what it expands to rather than in
 * what it weighs, and a caller's byte cap on the entry does not reach it.
 * Engines cap expansion themselves, but by how much is theirs to change and is
 * not something a reader can assert.
 *
 * Refusing costs nothing, and **each caller measured its own format rather than
 * inheriting a figure from here**: 0 of the 79 EPUBs `opf.ts` describes carry
 * `<!ENTITY` in either their container or their package document, and 0 of
 * `fb2.ts`'s 18 corpus files carry one. `cbz.ts` refuses on the specification
 * alone, having no corpus, and says so at its own site. None of these formats
 * has a use for a DTD internal subset.
 *
 * A plain substring rather than a regular expression over the prolog, which
 * would need to know where the prolog ends and would then be wrong about a
 * comment containing a tag. The exclusions, stated: an unescaped `<!ENTITY`
 * inside a `CDATA` section or inside a comment is refused as well. 0 of those
 * 79 files carry a `CDATA` section at all, and being told a file is not the
 * format it claimed is a smaller harm than an unbounded parse.
 *
 * **It sits at the seam because it is a rule about parsing a member's document
 * and not about any one format.** A reader that hands a whole document to
 * `DOMParser` as `application/xml` calls this first, and four do.
 *
 * **Two parses here do not, and both are deliberate.** `pdf.ts` cuts the packet
 * down to its root element, so what it parses has no prolog for a declaration
 * to sit in, and says so at its own site. `calibre.ts::plainText` parses
 * `text/html`, which has no internal subset to expand.
 */
export function declaresEntities(xml: string): boolean {
  return xml.includes("<!ENTITY");
}

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
