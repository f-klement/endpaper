/**
 * What a source said about one book, whatever kind of source said it.
 *
 * **Three families produce these and none of them owns the shape.** A picked
 * file, a store's own catalogue and a Calibre `metadata.db` each answer with
 * their own record, and every field below was declared identically in all
 * three: `lib/fileReaders.FileMetadata`, `lib/stores.StoreBook` and
 * `lib/calibre.CalibreBook` now extend this and add only what is theirs.
 *
 * **What a field holds is decided by what this app stores, never by what a
 * format or a vendor spells.** That rule was already written at two of the
 * three declarations and is the reason a fourth family fills these in rather
 * than adding to them.
 *
 * **A field the source did not state is `null` and never `""`.** A caller
 * reading `record.title` to decide whether the source named one would take an
 * empty string for a title.
 *
 * ## What is deliberately not here
 *
 * **`identifiers`, which all three also share by name and in no other way.**
 * The three element types are a file's open label, which may be absent;
 * Calibre's `type` column, which never is; and a scheme this app stores, which
 * a store adapter has already decided. Labelling is the reader's decision and
 * stays with the reader; what is shared is the bound, in `lib/bookRequest.ts`.
 *
 * **`subtitle`, which only a file states.** Holding it here would make every
 * store adapter and the Calibre reader write `null` for a field their sources
 * have no column for. The file family declares it and bounds it.
 *
 * ## Nothing here names the API
 *
 * `lib/calibre.ts` and `lib/stores.ts` import this, and
 * `tests/houseRules.test.ts` denies every reader in this directory the
 * generated client while `tests/lib/fileReaders.test.ts` walks the reader
 * import closure and refuses any module in it that spells a stored scheme.
 * This module is in that closure. `lib/bookRequest.ts` is where these values
 * become the request's, and no reader may reach it.
 */

export interface SourceRecord {
  readonly title: string | null;
  /**
   * Separate values, in whatever order the source gave them.
   *
   * **Neither joined nor split here**, and the two halves were bought
   * separately. A file separates its creators, so joining would throw away a
   * fact it supplied and make every later reader guess it back. A store that
   * carries its authors as one line is read as one author, because the
   * separator is undocumented in every store this has met and a wrong guess
   * turns one person into two. `lib/bookBounds.AUTHOR_SEPARATOR` is what the
   * request joins them with, and it is the separator the server splits on.
   */
  readonly authors: readonly string[];
  /** Canonical ISBN-13, from whichever spelling the source carried one in. */
  readonly isbn: string | null;
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly description: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
}
