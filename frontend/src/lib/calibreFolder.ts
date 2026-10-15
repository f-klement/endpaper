/**
 * A Calibre library as a directory picker hands it over.
 *
 * `calibre.ts` reads the index and the file beside one book, and says which
 * file in a pick is the index; this is the half that walks the whole pick: the
 * `metadata.opf` beside every book, and each book's own files. Both doors a library comes in
 * by use it, the Settings import and a folder picked on the scan page, so a
 * library read through one is read the same way through the other.
 *
 * **One library, one writer.** Nothing here opens a library. A picked folder
 * is a set of snapshots the page cannot write to, the index among them is read
 * into memory by `sqlite.ts`, and a book file is never opened here at all:
 * pairing it with its book reads its path, and only `fileDigest.ts` reads any
 * of its bytes, for the fingerprint.
 */

import {
  crossCheck,
  indexOpfFiles,
  libraryFilePath,
  libraryPathOf,
  MAX_OPF_BYTES,
  type CalibreBook,
} from "./calibre";
import { readOpf } from "./opf";

/** What checking a library against the `metadata.opf` files did. */
export interface FolderCrossCheck {
  readonly books: readonly CalibreBook[];
  /** Books that had a `metadata.opf` beside them and were checked against it. */
  readonly crossChecked: number;
  /** Fields the files supplied where the database had none. */
  readonly filled: number;
  /** Fields both carried, differently. The database kept its own. */
  readonly disagreed: number;
}

/**
 * Every book checked against the `metadata.opf` beside it in the pick.
 *
 * **One file's failure is never the library's.** A file that is not a package
 * document, is larger than this will read, or went away between the pick and
 * the read leaves that book with what the database said, which is what the
 * database being the primary route means.
 *
 * **Read together rather than one after another**: no read depends on another,
 * and the books come back in the index's order whatever order the reads finish
 * in.
 *
 * @param onProgress Told every fifty books rather than every book: a set on
 * each of nine hundred is nine hundred renders of a screen showing one number.
 */
export async function crossCheckFolder(
  books: readonly CalibreBook[],
  files: readonly File[],
  onProgress: (done: number, total: number) => void = () => {},
): Promise<FolderCrossCheck> {
  const index = indexOpfFiles(files);
  let done = 0;
  onProgress(0, books.length);
  const merged = await Promise.all(
    books.map(async (book) => {
      const opf = await readBeside(index.get(book.path.normalize("NFC")));
      done += 1;
      if (done % 50 === 0) onProgress(done, books.length);
      return opf === null ? null : crossCheck(book, opf);
    }),
  );
  return {
    books: merged.map((one, at) => one?.book ?? books[at]!),
    crossChecked: merged.filter((one) => one !== null).length,
    filled: merged.reduce((sum, one) => sum + (one?.filled ?? 0), 0),
    disagreed: merged.reduce((sum, one) => sum + (one?.disagreed ?? 0), 0),
  };
}

/** The package document beside one book, or `null` for every way there is not one. */
async function readBeside(file: File | undefined) {
  if (file === undefined || file.size > MAX_OPF_BYTES) return null;
  try {
    return readOpf(await file.text());
  } catch {
    return null;
  }
}

/**
 * Each book's own files in the pick, by the book's Calibre id.
 *
 * **Found by where Calibre puts a file, never by its name or its contents**:
 * `calibre.libraryFilePath` from the index, compared with where the browser
 * says each picked file sits. A book whose files the pick does not hold is
 * absent, and so is a picked file the index names for no book.
 */
export function filesOfEachBook(
  books: readonly CalibreBook[],
  files: readonly File[],
): Map<number, File[]> {
  const byPath = new Map<string, File>();
  for (const file of files) {
    const path = libraryPathOf(file);
    if (path !== null) byPath.set(path, file);
  }
  const found = new Map<number, File[]>();
  for (const book of books) {
    const held = book.files.flatMap((one) => {
      const path = libraryFilePath(book, one);
      const file = path === null ? undefined : byPath.get(path);
      return file === undefined ? [] : [file];
    });
    if (held.length > 0) found.set(book.id, held);
  }
  return found;
}
