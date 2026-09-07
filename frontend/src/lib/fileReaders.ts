import type { CbzFailure } from "./cbz";
import type { EpubFailure } from "./epub";
import type { Fb2Failure } from "./fb2";
import type { MobiFailure } from "./mobi";
import type { PdfFailure } from "./pdf";
import type { OpfRecord } from "./opf";
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
 * **An extension with no reader is not an error.** `.m4b` and `.mp3` are the
 * standing case: audio is grouped and read by `lib/audiobook.ts` on a separate
 * path, because which files are one book is decided before any of them is
 * drafted from. `null` here means exactly that, and the caller falls through to
 * the filename path.
 */
export type FileFailure =
  CbzFailure | EpubFailure | Fb2Failure | MobiFailure | PdfFailure;

export type FileReading =
  | { readonly ok: true; readonly metadata: OpfRecord }
  | { readonly ok: false; readonly failure: FileFailure };

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
