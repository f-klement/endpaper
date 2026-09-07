/**
 * What a Calibre record becomes on the wire.
 *
 * The same job `ScanPage/types.ts` does for a scanned or picked book, in the
 * page folder that owns the other end of it: this module is where what a reader
 * produced becomes what a request carries. `lib/calibre.ts` stays pure and
 * knows nothing about the API, which is what lets it be tested against a
 * database rather than against a schema.
 *
 * **Every value is bounded on the way through.** A `metadata.db` is somebody
 * else's data whatever route it took to the disk it is on, so the rule is the
 * one `lib/bookBounds.ts` carries: a value the column cannot hold loses that
 * field, never the book, and never turns into a 422 in the middle of a member's
 * own import of nine hundred books.
 */

import type { BookCreate } from "../../../api/generated/model";
import { BookFormat } from "../../../api/generated/model";
import {
  AUTHOR_SEPARATOR,
  boundNumber,
  boundText,
} from "../../../lib/bookBounds";
import type { CalibreBook } from "../../../lib/calibre";

/**
 * Calibre formats that mean a recording rather than a book to read.
 *
 * Calibre files an audiobook as an ordinary book with an audio file attached,
 * so the format column is the only thing that separates the two. Everything
 * else with a file is an ebook, and a record with no file at all is neither:
 * see `formatOf`.
 */
const AUDIO_FORMATS = new Set(["M4A", "M4B", "MP3", "OGG", "OPUS", "AAC"]);

/**
 * What kind of object this copy is, or `null` when the library does not say.
 *
 * **A book with no file is not an ebook**, and answering `ebook` for one would
 * assert something the library does not: a Calibre record with no file is a
 * book somebody catalogued, which is exactly what an unowned record looks like
 * here. `null` is the value the column takes for "not said".
 */
export function formatOf(book: CalibreBook): BookFormat | null {
  if (book.formats.length === 0) return null;
  const audio = book.formats.every((format) =>
    AUDIO_FORMATS.has(format.trim().toUpperCase()),
  );
  return audio ? BookFormat.audiobook : BookFormat.ebook;
}

/**
 * One Calibre book as `POST /api/books/scan` takes it, or `null`.
 *
 * `null` for a book with no title, which is the one field the API requires. A
 * Calibre library carries them: `Unknown` is what Calibre writes where nobody
 * said, `lib/calibre.ts` refuses that placeholder by name, and the record left
 * over has nothing to file it under. Reported before the write rather than left
 * to a 422 halfway through the batch.
 *
 * **No cover, no tags, no files, and that is scope rather than a rule.** Each
 * is a second request a book against a route that already makes one; whether an
 * import should make them is a decision about the import flow. `lib/calibre.ts`
 * lists what the reader deliberately leaves behind and why.
 */
export function toBookCreate(book: CalibreBook): BookCreate | null {
  const title = boundText("title", book.title);
  if (title === null) return null;

  return {
    title,
    author: boundText("author", book.authors.join(AUTHOR_SEPARATOR)),
    isbn: boundText("isbn", book.isbn),
    publisher: boundText("publisher", book.publisher),
    year: boundNumber("year", book.year),
    description: boundText("description", book.description),
    language: boundText("language", book.language),
    series_name: boundText("series_name", book.seriesName),
    series_index: boundNumber("series_index", book.seriesIndex),
    format: formatOf(book),
    // Calibre has no shelf and no notion of a private book, so both take the
    // value the column has for "not said" rather than one invented here.
    location: null,
    is_private: false,
    // The library names neither, and an empty list is what the endpoint
    // already takes.
    classifications: [],
  };
}
