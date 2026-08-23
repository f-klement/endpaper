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
  type BookOut,
  type CollectionOut,
  type LoanOut,
  type NoteOut,
  type PageBookOut,
  type ProgressOut,
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

export function makeUser(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: id(),
    username: "reader",
    is_admin: false,
    created_at: "2026-01-01T00:00:00",
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

/** One tag per category, for the grouped pickers. */
export function makeTagSet(): TagOut[] {
  return [
    makeTag({ name: "Fiction", category: TagCategory.type }),
    makeTag({ name: "Fantasy", category: TagCategory.genre }),
    makeTag({ name: "Adult", category: TagCategory.age }),
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
    added_at: "2026-01-01T00:00:00",
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
    loaned_at: "2026-02-01T00:00:00",
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
    created_at: "2026-03-01T00:00:00",
    updated_at: "2026-03-01T00:00:00",
    author: makeUser(),
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
    recorded_at: "2026-03-02T10:00:00",
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
