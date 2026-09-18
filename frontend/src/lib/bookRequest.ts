/**
 * What a `SourceRecord` becomes on the wire, decided once for every source.
 *
 * **The vocabulary seam, and it is the whole reason this is a module.** What
 * the app holds and what the request carries are two vocabularies:
 * `seriesName` is `series_name`, several authors are one line joined with the
 * separator the server splits on, and a value the column cannot hold loses that
 * field rather than the book. Three builders spelled that mapping out, one per
 * family, so a field added to `BookCreate` that a source can state was three
 * edits and nothing went red after the first two.
 *
 * **Not `lib/bookBounds.ts`, and the split is where that module's own rule puts
 * it.** That one holds `BookCreate`'s scalar bounds keyed by field name, with
 * every number recomputed from `openapi.json` by its test and no import of the
 * generated client anywhere in it. This one names the API: it decides which
 * field a record's value is, and it bounds the `value` inside a list, which is
 * the bound `IDENTIFIER_VALUE_MAX` already said did not belong there.
 *
 * **No reader may import this**, which is what keeps `lib/calibre.ts` and
 * `lib/stores.ts` testable against a database or an archive rather than against
 * a schema.
 *
 * **What enforces that is narrower than the rule, and the gap is written down
 * rather than left to be found.** `tests/houseRules.test.ts` refuses every
 * module in this directory that handles bytes a **static** import of the
 * generated client, which is what stops either of those two naming the API
 * itself. Static, because the arm needs a `from` clause: a dynamic
 * `await import()` of `api/generated/model` would pass it, and `lib/stores.ts`
 * already writes ten dynamic imports of its own. What that would leak is types
 * and enums rather than a call, because the endpoints half of the generated
 * client is refused by a plain substring test whatever the spelling.
 *
 * **That half is not named here on purpose.** The substring test reads a
 * module's whole source, so writing the path in prose makes this file an
 * offender: it did, and `the generated client stays behind hooks.ts` caught it
 * on the merge.
 *
 * It does not see an import of this module, whose specifier carries no
 * `api/` at all. `tests/lib/fileReaders.test.ts` walks an import closure and
 * refuses any module in it that spells a stored scheme, which would see the
 * edge, but that closure is seeded from what the seam's registry loads, so a
 * reader the registry never loads is outside it and `calibre.ts` and
 * `stores.ts` are two such. Measured 2026-09-18 by three separate
 * reimplementations of that walk: the closure holds 15 modules and covers 8 of
 * the 15 modules the reader rule watches.
 *
 * So the edge is refused by name for eight of them and by review for the rest,
 * and the reason to refuse it is the sentence above rather than a test.
 * `lib/sourceRecord.ts` is inside that closure and says so at its own site,
 * which is why the same claim there is a stronger one than this.
 *
 * **What each family still decides for itself**, because a single door that
 * flattened any of these would be wrong rather than tidy: what a missing title
 * means, which is `null` for an import nobody is watching and an editable blank
 * on the scan page; what kind of copy this is; what a store said about owning
 * it; and which scheme a label names, which is the reader's reading of its own
 * source.
 */

import type { BookCreate, BookIdentifierIn } from "../api/generated/model";
import { BookIdentifierScheme } from "../api/generated/model";
import { AUTHOR_SEPARATOR, boundNumber, boundText } from "./bookBounds";
import type { SourceRecord } from "./sourceRecord";
import type { StoreIdentifier, StoreIdentifierScheme } from "./stores";

/**
 * The bibliographic half of a request, under the names the endpoint uses.
 *
 * **Every name is taken from `BookCreate` rather than written out**, so a field
 * renamed on the schema is a compile error here rather than a value the server
 * ignores. `tests/lib/bookRequest.test.ts` asks the same question of the
 * committed `openapi.json`, which is the half a type cannot answer: the
 * generated client and the schema are regenerated together.
 *
 * `title` is picked and then replaced, which reads like a detour and is not:
 * picking it is what asserts the endpoint still has a field of that name, and
 * replacing it is what makes it nullable. `BookCreate.title` is required,
 * because a request has to carry one; this says what the source stated, and
 * what an absent title means is the caller's decision.
 */
export type BoundRecord = Omit<
  Pick<
    BookCreate,
    | "title"
    | "author"
    | "isbn"
    | "publisher"
    | "year"
    | "description"
    | "language"
    | "series_name"
    | "series_index"
  >,
  "title"
> & { title: string | null };

/**
 * A source's record, bounded and renamed for the request.
 *
 * **Every value is bounded on the way through**, because a source is somebody
 * else's data whatever route it took to the disk it is on: a `metadata.db`, a
 * store's export and a picked ebook are all untrusted input. The rule is
 * `lib/bookBounds.ts`': a value the column cannot hold loses that field, never
 * the book, and never turns into a 422 in the middle of a member's own import
 * of nine hundred books.
 *
 * **It answers `title: null` rather than refusing.** The three callers answer
 * that differently on purpose, and each says why at its own site.
 *
 * `tests/lib/bookRequest.test.ts` checks every key here against the committed
 * `openapi.json`, and asserts that no field of `SourceRecord` can stop reaching
 * the wire without an arm going red.
 */
export function boundRecord(record: SourceRecord): BoundRecord {
  return {
    title: boundText("title", record.title),
    author: boundText("author", record.authors.join(AUTHOR_SEPARATOR)),
    isbn: boundText("isbn", record.isbn),
    publisher: boundText("publisher", record.publisher),
    year: boundNumber("year", record.year),
    description: boundText("description", record.description),
    language: boundText("language", record.language),
    series_name: boundText("series_name", record.seriesName),
    series_index: boundNumber("series_index", record.seriesIndex),
  };
}

/**
 * What a source's name for a book is called on the wire.
 *
 * **A total `Record` rather than a cast**, although the two vocabularies spell
 * their members identically today: a scheme added to `StoreIdentifierScheme`
 * with no home here is a compile error, where a cast would send the endpoint a
 * value its enum does not have and get a 422 in the middle of somebody's
 * device. `LibrarySettingsPage/types.STORE_FORMATS` keeps the same discipline
 * for the other enum a store answers with.
 *
 * It is here rather than in `lib/stores.ts` because that module may not name
 * the API at all, and here rather than in a page folder because both import
 * flows and the scan page reach it.
 */
const STORE_SCHEMES: Record<StoreIdentifierScheme, BookIdentifierScheme> = {
  asin: BookIdentifierScheme.asin,
  google_books: BookIdentifierScheme.google_books,
};

/**
 * The form of a value each scheme's own issuer writes.
 *
 * **A property of the scheme, so it lives at the door both readers go through**
 * rather than in either of them. `lib/calibre.ts` decides which scheme a
 * Calibre type names and `lib/stores.ts` labels what a store adapter read; if
 * one of them folded a value and the other did not, one ASIN spelled two ways
 * would be two rows on one Book, which is what
 * `uq_book_identifiers_book_scheme_value` is keyed to allow and nothing on a
 * screen tells apart. Found by the design seat, 2026-09-11, against a first
 * draft that folded in one reader and claimed the benefit for both.
 *
 * **The alphabet decides, not a preference.** Amazon issues a token with no
 * lower case in it, so upper casing one recovers the value the store issued. A
 * Google Books volume id's alphabet has both cases, so folding one would name a
 * different book, and its entry is the identity for that reason rather than
 * because nobody got to it. A scheme added here has to answer the question.
 *
 * **And a fold reaches only its own alphabet, never `toUpperCase`.** This is
 * the door, and the door is the one place that cannot assume a value was
 * vetted: `kindle.ts` takes the `ASIN` element's text as written, so nothing
 * has proved the token's shape by the time it arrives here.
 *
 * **The reason is that `toUpperCase` is not one function.** It is whatever
 * Unicode table the engine was built against, so two members on browsers of
 * different vintages canonicalise one value two ways and file two rows for one
 * identifier, which is the row this table exists to prevent, reintroduced by
 * the table. Measured on one machine, 2026-09-11, over all 1,112,064 non
 * surrogate code points: node 24.10.0 at Unicode 16.0 folds 1,552 of them and
 * bun 1.4.2 at Unicode 17.0 folds 1,580, a strict superset by set difference,
 * 28 one way and none the other. Two engines is two tables, which is the claim.
 * **`[a-z]` is the same 26 in every version there will ever be**, and swept the
 * same way on both engines it changes 26, none outside `[a-z]` and none
 * changing length.
 *
 * The count also says what a wide fold would touch: 1,526 of node's 1,552 are
 * outside `[a-z]`, so it rewrites characters no scheme here has a claim on,
 * which is the refusal the whitespace paragraph below already makes. `parseIsbn`
 * is the precedent and it points the same way: it normalises only what it has
 * proved. Found by the design seat, measured by the security seat.
 *
 * Total over `StoreIdentifierScheme`, `STORE_SCHEMES`' discipline.
 */
const CANONICAL_VALUE: Record<
  StoreIdentifierScheme,
  (value: string) => string
> = {
  asin: (value) => value.replace(/[a-z]/g, (one) => one.toUpperCase()),
  google_books: (value) => value,
};

/**
 * How wide an identifier the column takes.
 *
 * **Not in `lib/bookBounds.ts`**, and the split is where that module's own rule
 * puts it: it holds `BookCreate`'s scalar `maxLength`s, keyed by field name, and
 * this bound is on the `value` inside a list rather than on a field. Recomputed
 * from `openapi.json` by this module's tests rather than restated, which is the
 * discipline `bookBounds.ts` keeps for every number in it.
 */
const IDENTIFIER_VALUE_MAX = 60;

/**
 * How many identifiers one request may carry.
 *
 * `BookCreate.identifiers` declares `maxItems`, and a payload over it is a 422
 * for the **whole book** rather than for the extra entry, which is the outcome
 * `boundIdentifiers` exists to prevent. No store produces more than one today;
 * this binds the case where one grows to.
 *
 * Recomputed from `openapi.json` beside the width above, for its reason.
 */
const IDENTIFIER_LIMIT = 8;

/**
 * Every character the endpoint refuses inside an identifier.
 *
 * **The families, not a list of spellings**, which is what lets this be checked
 * against the server's rule rather than against a set of examples somebody
 * thought of. `BookIdentifierIn.an_opaque_token` refuses whitespace and every
 * character in the Unicode categories `Cc` and `Cf`; this is that same rule in
 * the one notation JavaScript has for it.
 *
 * **It has to be the same rule, and a narrower one here costs the book.** This
 * filter used to be `/\s/u` alone. Measured over all 1,112,064 non surrogate
 * code points by both critic seats independently: **229 passed this filter and
 * were refused by the server**, among them SOFT HYPHEN, ZERO WIDTH SPACE, NUL
 * and U+0085, and none went the other way. `importing.writeBooks` files the 422
 * under `failures`, so each one lost a book. With the categories added the two
 * rules are equal sets, 0 code points in either direction.
 *
 * Wider than the server's would be safe and is not free either: it would drop
 * an identifier the endpoint would have taken, silently.
 */
const REFUSED_INSIDE_AN_IDENTIFIER = /[\s\p{Cc}\p{Cf}]/u;

/**
 * The identifiers the endpoint will take, out of what a reader gave.
 *
 * **The bound, not the mapping.** Which scheme a row belongs to is its reader's
 * decision and is made there: a store's adapter labels what it read,
 * `lib/calibre.identifiersWithScheme` reads a Calibre type, and
 * `ScanPage/types.identifiersFromFile` reads a label an EPUB wrote. What is
 * left is one rule about what may cross the wire, and all three reach it.
 *
 * **A value the endpoint would refuse loses that identifier, never the book**,
 * which is `lib/bookBounds.ts`' rule applied to a field it does not cover: an
 * import of nine hundred books must not turn into a 422 over one row whose
 * catalogue held something odd. The Kindle catalogue is where that can happen:
 * `kindle.ts` takes the `ASIN` element's text as written, so the value is
 * whatever that file said.
 *
 * **So this has to refuse everything the endpoint refuses**, which is four
 * rules and not three: empty, too wide, anything invisible inside, and more
 * entries than one request may carry. A rule missing here does not fail
 * anywhere; it turns into a lost book on somebody's own import.
 *
 * **Two things happen here that are not refusals**, and both are here rather
 * than in a reader because both are properties of the scheme: a value is put in
 * the form its issuer writes (`CANONICAL_VALUE`), and a repeat of one already
 * kept is folded. The fold is paired with the ceiling above it: that ceiling
 * truncates, so a repeat left standing costs the book a different identifier.
 *
 * **Trimmed first, and the server does not**: `max_length` is a field
 * constraint and runs before `BookIdentifierIn`'s validator, so the server
 * measures what arrived and this measures what it is about to send. Trimming
 * here is therefore the thing that makes a padded value survive at all, rather
 * than a copy of the server's order. The two agree on every value inside the
 * budget, which is every value any reader here produces: the widest is 12
 * characters.
 *
 * **Whitespace inside is dropped rather than removed**, which is the server's
 * rule and the reason for it: an identifier is an opaque token, so whitespace
 * in the middle means the reader picked up something that is not the
 * identifier, and closing it up here would send a value this app invented.
 */
export function boundIdentifiers(
  identifiers: readonly StoreIdentifier[],
): BookIdentifierIn[] {
  const kept: BookIdentifierIn[] = [];
  const folded = new Set<string>();
  for (const identifier of identifiers) {
    if (kept.length >= IDENTIFIER_LIMIT) break;
    const scheme = STORE_SCHEMES[identifier.scheme];
    // **Canonical before the bounds, and that is the rule rather than a
    // detail.** What is measured has to be what is sent, the reason the trim
    // runs first. **Nothing today depends on it**, because neither fold can
    // change a length, and what makes that true is `CANONICAL_VALUE` reaching
    // only `[a-z]`: a fold spelled `toUpperCase` grows 102 of the 1,112,064 non
    // surrogate code points, 16 of them threefold (U+0390 among them), so a
    // value at the ceiling would canonicalise past it and lose the book. Those
    // two counts are the ones both engines agreed on.
    const value = CANONICAL_VALUE[identifier.scheme](identifier.value.trim());
    // Code points, never UTF-16 units, `bookBounds.boundText`'s measurement:
    // the ceiling belongs to a Python `str` and to a SQLite column and both
    // count code points.
    if (value.length === 0 || [...value].length > IDENTIFIER_VALUE_MAX)
      continue;
    if (REFUSED_INSIDE_AN_IDENTIFIER.test(value)) continue;
    // **The fold is here because the ceiling is here.** It is not to save the
    // server work: `identifiers.add_identifiers` drops an in payload repeat as
    // well as one the Book already carries, and says so. It is that
    // `IDENTIFIER_LIMIT` truncates before the server ever sees the payload, so
    // without this a library filing one ASIN under fifteen marketplaces spends
    // every slot on one fact and its volume id never crosses the wire.
    //
    // **A set and not a scan over `kept`**, though `kept` is capped at eight
    // immediately above, so a scan would be linear in rows here today. Its
    // bound would be a neighbouring rule rather than its own, and the same scan
    // in a loop without that cap cost 564,831ms on 200,000 rows for one book,
    // which is a row count `lib/sqlite.MAX_ROWS_PER_QUERY` admits and which
    // this runs on the browser's main thread. Both figures are one core of the
    // machine this repository is developed on, 2026-09-11, the first by the
    // security seat: with the set, 200,000 rows for one book is 69ms all
    // distinct and 257ms all the same value.
    //
    // The separator cannot occur inside either half: both scheme names are
    // alphanumeric with an underscore, and a value carrying whitespace was
    // refused two lines up.
    const key = `${scheme} ${value}`;
    if (folded.has(key)) continue;
    folded.add(key);
    kept.push({ scheme, value });
  }
  return kept;
}
