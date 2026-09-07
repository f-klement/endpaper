/**
 * What `POST /api/books/scan` will hold, applied before a value is sent.
 *
 * **The browser became a metadata producer the moment it started reading files,
 * and a member's own browser is not a trusted producer.** A book file is
 * somebody else's data, so a title out of one is untrusted input in exactly the
 * way a catalogue record is, and the rule this mirrors is the one
 * `backend/catalogue.py` already applies to catalogues: a value the columns
 * cannot hold loses that field, it never loses the record, and it never turns
 * into a 422 on a member's own request.
 *
 * **Cut or dropped, and the split is the part nobody would write down.** A cut
 * value has to still be an instance of what it was. A title cut to 500
 * characters is the same book through a narrower window; a language code cut to
 * 10 names a different language, and a cut ISBN fails its own checksum and so
 * names no book at all. Same rule as `catalogue._CUT_ON_UPLOAD` and
 * `_KEPT_WHOLE_ON_UPLOAD`, and **the same six names on the cut side**.
 *
 * The kept-whole sides differ by one name each way, because the two tables
 * answer for different fields: `google_books_id` is not something `BookCreate`
 * takes, and `location` is not a catalogue scalar at all. `location` is kept
 * whole for the reason the others are, that a cut value is a different value:
 * a shelf name cut to 120 characters names a shelf nobody has.
 *
 * **The numbers are not column widths.** They are the bounds the request bodies
 * already carry, and a value outside them is a row a member cannot afterwards
 * edit, because `BookDetailsUpdate` answers 422 for exactly those values.
 *
 * `tests/lib/bookBounds.test.ts` recomputes every number here from
 * `openapi.json` rather than restating it, so this table cannot drift from the
 * schema it describes.
 */

/** How wide a string may be. Every `maxLength` `BookCreate` declares. */
export const TEXT_CEILINGS = {
  author: 500,
  cover_url: 500,
  description: 10000,
  isbn: 20,
  language: 10,
  location: 120,
  publisher: 255,
  series_name: 255,
  subtitle: 500,
  title: 500,
} as const;

export type BoundedText = keyof typeof TEXT_CEILINGS;

/** What a number has to fall inside, closed at both ends. */
export const NUMBER_RANGES = {
  collection_id: [1, 9223372036854775807],
  page_count: [1, 100000],
  series_index: [0, 1000],
  year: [1, 2200],
} as const;

export type BoundedNumber = keyof typeof NUMBER_RANGES;

/**
 * Which fields may arrive cut, and which lose the whole value instead.
 *
 * Stated as the exclusion as well as the inclusion, and both are asserted: a
 * field that joins `TEXT_CEILINGS` and neither set is a field with no policy,
 * which is the shape that acquires one by default.
 */
export const CUT_TO_FIT: ReadonlySet<BoundedText> = new Set<BoundedText>([
  "author",
  "description",
  "publisher",
  "series_name",
  "subtitle",
  "title",
]);

export const KEPT_WHOLE: ReadonlySet<BoundedText> = new Set<BoundedText>([
  "cover_url",
  "isbn",
  "language",
  "location",
]);

/**
 * The value the column can hold, or `null`.
 *
 * Whitespace is trimmed first, because a file's own padding is not part of the
 * value and counting it against the ceiling would cut a title that fits.
 *
 * **Measured and cut in code points, never in UTF-16 units**, which is two
 * faults in one. The ceiling belongs to a Python `str` and to a SQLite column,
 * both of which count code points, so measuring in units refuses at 250 emoji
 * what the server would have taken 500 of. Worse, a cut landing between the
 * halves of a surrogate pair produces a lone surrogate, which is not a string
 * any encoder will emit: pydantic answers `string_unicode` and the whole book
 * is lost to a 422, which is the exact outcome this module exists to prevent.
 * The same class is already fixed twice in this tree, at `notifications.py` and
 * `z3950.py`; this is the third place it can happen.
 */
/**
 * How several authors become the one line `BookCreate.author` holds.
 *
 * **`backend/authors.py` splits on a comma and on nothing else**, so this is
 * the separator that survives the round trip rather than a formatting choice.
 *
 * **The exclusion, because it is real**: a creator whose own name contains a
 * comma arrives as two authors. Measured over 79 real EPUB files, 2 of 79
 * creator strings contained one and both were the same corporate name. The fix
 * is a wire field carrying authors separately, which is a schema change.
 *
 * **Here rather than in a page folder, because two of them had it.** The scan
 * page's file path and the Calibre import each declared it, each restating the
 * backend rule beside it, and a third reader would have made a third copy.
 */
export const AUTHOR_SEPARATOR = ", ";

/**
 * What the search endpoint will take as a query.
 *
 * **Here rather than beside either caller, because three had it.** The scan
 * page's search box, the shared search bar and the filename derivation each
 * declared the floor as a literal `2` against the same schema bound, so the
 * number had three homes and no owner. A file named for what a request will
 * hold is the home; a module named for filenames was the wrong one for a search
 * box's floor, and so was a component.
 *
 * Recomputed from `openapi.json` by `tests/lib/bookBounds.test.ts` the way every
 * ceiling above it is, so it cannot drift from the endpoint that enforces it.
 */
export const QUERY_FLOOR = 2;
export const QUERY_CEILING = 200;

export function boundText(
  field: BoundedText,
  value: string | null | undefined,
): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  const ceiling = TEXT_CEILINGS[field];
  const points = [...trimmed];
  if (points.length <= ceiling) return trimmed;
  return CUT_TO_FIT.has(field) ? points.slice(0, ceiling).join("") : null;
}

/**
 * The number the column can hold, or `null`.
 *
 * Never clamped. A page count of 300,000 is not 100,000 seen through a narrower
 * window, it is a fact the file got wrong, and storing the ceiling would turn a
 * wrong number into a plausible one.
 */
export function boundNumber(
  field: BoundedNumber,
  value: number | null | undefined,
): number | null {
  if (value === null || value === undefined) return null;
  if (!Number.isFinite(value)) return null;
  const [low, high] = NUMBER_RANGES[field];
  return value >= low && value <= high ? value : null;
}
