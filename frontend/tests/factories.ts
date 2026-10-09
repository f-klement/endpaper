/**
 * Fixture builders.
 *
 * Each returns a complete, valid object so a test states only the field it
 * actually cares about. Shapes come from the generated model, so a schema
 * change that breaks a fixture surfaces here rather than in twenty tests.
 */

import {
  ReadStatus,
  TagCategory,
  TagKey,
  type BookOut,
  type CollectionOut,
  type LoanOut,
  type NoteOut,
  type PageBookOut,
  type ProgressOut,
  type QuoteOut,
  type QuoteWithBookOut,
  type PageLoanOut,
  type StatsOut,
  type TagOut,
  type UserOut,
} from "../src/api/generated/model";

let nextId = 1;
export function resetIds(): void {
  nextId = 1;
}
function id(): number {
  return nextId++;
}

/**
 * The instant a picked day ends where the viewer is.
 *
 * **`due_at` is the one dated field a browser *derives*, which is why it is the
 * one a plain UTC stamp gets wrong.** Two fields are browser written, not one:
 * `LoanCreate.due_at` and `DigitalReferenceIn.file_modified_at` both carry
 * `UtcDateTimeIn`. The difference is where the value comes from.
 * `file_modified_at` is an instant the browser already had, a `File`'s own
 * modified time, and `toISOString()` just spells it; no local day is involved,
 * so no zone can put it on the wrong one. `due_at` is a **day somebody picked**
 * turned into the instant that day ends where they are, by
 * `src/lib/date.ts`'s `endOfDayInstant`.
 *
 * Every other stamp here is the server's, written in UTC and carrying `Z`. A
 * fixture spelling `due_at` as a plain midnight or midday UTC stamp is a value
 * that door cannot produce, and a midnight one renders as the 4th west of UTC
 * while the arm beside it talks about the 5th.
 *
 * **Built with the numeric constructor rather than by calling the module under
 * test**, which would make every assertion over it agree with the code by
 * construction. This is the same second expression `tests/lib/date.test.ts`
 * uses to state the same rule, and it is deliberately duplicated: a fixture
 * importing the thing it is a fixture for is how a test stops being able to
 * fail.
 */
export function endOfDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year!, month! - 1, date!, 23, 59, 59).toISOString();
}

export function makeUser(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: id(),
    username: "reader",
    is_admin: false,
    created_at: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

export function makeTag(overrides: Partial<TagOut> = {}): TagOut {
  return {
    id: id(),
    name: "Fantasy",
    category: TagCategory.genre,
    ...overrides,
  };
}

/**
 * One tag per category, for the grouped pickers.
 *
 * Keyed, because all three are seeded names and a seeded row carries its key:
 * a set without one would be three tags a German reader is shown in English,
 * which is the state this fixture is least like. `makeTag` stays unkeyed,
 * which is the other real shape, a tag the library invented.
 */
export function makeTagSet(): TagOut[] {
  return [
    makeTag({
      name: "Fiction",
      category: TagCategory.type,
      key: TagKey.fiction,
    }),
    makeTag({
      name: "Fantasy",
      category: TagCategory.genre,
      key: TagKey.fantasy,
    }),
    makeTag({ name: "Adult", category: TagCategory.age, key: TagKey.adult }),
  ];
}

/**
 * A book payload.
 *
 * `authors` is derived rather than defaulted, because the server derives it on
 * every serialisation: a factory that let the credit line and the split names
 * disagree would let a test pass against a payload the API cannot produce. The
 * real rule lives in `backend/authors.split_authors`; this only has to agree
 * with it for the shapes tests use.
 */
export function makeBook(overrides: Partial<BookOut> = {}): BookOut {
  const book = {
    id: id(),
    isbn: "9780441013593",
    title: "Dune",
    subtitle: null,
    author: "Frank Herbert",
    publisher: "Chilton",
    year: 1965,
    description: null,
    cover_url: null,
    added_at: "2026-01-01T12:00:00Z",
    is_private: false,
    added_by: null,
    active_loan: null,
    my_status: ReadStatus.unread,
    // Null rather than a value: nobody has been asked whether this copy is
    // lent out, which is what the column means on a real book too.
    lending: null,
    my_wants_to_discuss: false,
    discuss_with: [],
    tags: [],
    // **The per-viewer half, in full.** `BookOut` is `BookColumns` plus
    // `ViewerFields`, and the twelve on that side carry no defaults: a server
    // that computed eleven of them and forgot the twelfth used to answer 200
    // with a plausible wrong value, so the type refuses one now. A fixture
    // omitting one is the same omission, and the same refusal catches it.
    collection_name: null,
    copy_count: 1,
    my_rating: null,
    my_started_at: null,
    my_finished_at: null,
    my_progress_page: null,
    my_progress_percent: null,
    my_progress_recorded_at: null,
    ...overrides,
  };
  return {
    ...book,
    authors:
      book.authors ??
      (book.author ?? "")
        .split(",")
        .map((name) => name.trim())
        .filter(Boolean),
  };
}

export function makeLoan(overrides: Partial<LoanOut> = {}): LoanOut {
  return {
    id: id(),
    book_id: 1,
    loaned_to_user_id: 2,
    loaned_by_user_id: 1,
    loaned_at: "2026-02-01T12:00:00Z",
    returned_at: null,
    book: null,
    loaned_to: makeUser({ username: "borrower" }),
    loaned_by: makeUser({ username: "lender" }),
    ...overrides,
  };
}

export function makeNote(overrides: Partial<NoteOut> = {}): NoteOut {
  return {
    id: id(),
    book_id: 1,
    user_id: 1,
    content: "A note",
    is_private: false,
    created_at: "2026-03-01T12:00:00Z",
    updated_at: "2026-03-01T12:00:00Z",
    author: makeUser(),
    ...overrides,
  };
}

export function makeQuote(overrides: Partial<QuoteOut> = {}): QuoteOut {
  return {
    id: id(),
    book_id: 1,
    user_id: 1,
    text: "A line worth keeping",
    page: null,
    note: null,
    created_at: "2026-03-01T12:00:00Z",
    updated_at: "2026-03-01T12:00:00Z",
    author: makeUser(),
    ...overrides,
  };
}

/** A row of the cross-book listing, which carries its book's three scalars. */
export function makeQuoteWithBook(
  overrides: Partial<QuoteWithBookOut> = {},
): QuoteWithBookOut {
  return {
    ...makeQuote(),
    book_title: "Dune",
    book_author: "Frank Herbert",
    book_cover_url: null,
    ...overrides,
  };
}

export function makeCollection(
  overrides: Partial<CollectionOut> = {},
): CollectionOut {
  return { id: id(), name: "Ebooks", book_count: 0, ...overrides };
}

export function makeStats(overrides: Partial<StatsOut> = {}): StatsOut {
  return { total: 0, per_user: [], by_tag: [], by_month: [], ...overrides };
}

/** One recorded reading position. Page unit by default; pass `percent` for the
 * other, never both: the API accepts exactly one. */
export function makeProgress(
  overrides: Partial<ProgressOut> = {},
): ProgressOut {
  return {
    id: id(),
    book_id: 1,
    recorded_at: "2026-03-02T12:00:00Z",
    page: 64,
    percent: null,
    minutes: null,
    ...overrides,
  };
}

/** Wrap rows in the pagination envelope the listing endpoints return. */
export function makeBookPage(
  items: BookOut[],
  overrides: Partial<PageBookOut> = {},
): PageBookOut {
  return { items, total: items.length, page: 1, page_size: 24, ...overrides };
}

export function makeLoanPage(
  items: LoanOut[],
  overrides: Partial<PageLoanOut> = {},
): PageLoanOut {
  return { items, total: items.length, page: 1, page_size: 50, ...overrides };
}
