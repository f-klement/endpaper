# Data model

Eight tables in `backend/models.py`. Six entities, one association table, and one key/value
store for runtime settings.

```
      User ──────┬──── added_by ────────► Book ◄──── book_tags ────► Tag
                 │                         │  ▲
                 ├──── UserBook ───────────┤  │
                 │     (read status)       │  │
                 ├──── Loan ───────────────┤  │
                 │     (to / by)           │  │
                 └──── Note ───────────────┘  │
                                              └── active loan = the Loan with returned_at IS NULL
```

## Tables

**`users`.** `username` is unique and case-sensitive. `password_hash` holds a bcrypt
digest; the plaintext is never stored or returned. `is_admin` is granted to whoever
registers first and is not editable through the API afterwards.

`appearance_palette`, `appearance_mode` and `appearance_wallpaper` are the member's own
look, nullable, with NULL meaning "has not chosen" rather than a value. Columns rather than
a `user_preferences` table: it is a one-to-one with no history, and a side table would add a
join to every read plus a row that both shadow-account paths in `auth_backends.py` would
have to remember to create. They are deliberately absent from `UserOut`; see
[theming.md](theming.md).

**`books`.** The catalogue. `isbn` is unique **but nullable**, which is deliberate: SQL
treats NULLs as distinct, so any number of manually-added books can coexist without an
ISBN while genuine duplicates are still rejected. `added_by_user_id` is nullable so
deleting an account does not cascade away its books.

Every ISBN is canonicalised to **ISBN-13 on the way in** (`backend/isbn.py`), so the same
book cannot be added twice under its ISBN-10 and ISBN-13 spellings. An ISBN that fails its
check digit is rejected rather than stored: a misread barcode produces an entry that can
never be matched against any metadata source.

`ownership` records whether a copy is **physically on the shelf**: `owned`, `not_owned` or
`unknown`. It is deliberately **not** the same axis as read status. See below.

Four columns are filled on demand from Google Books and are empty otherwise: `page_count`,
`language`, `categories` and `google_books_id`. `categories` is Google's own subject list,
stored as one delimited string because SQLite has no array type, and served as a list.
**The delimiter is a semicolon, not a comma**, and that is load bearing: Google's own
category names contain commas ("Fiction, general"). `google_books.join_categories` and
`split_categories` are the only two places that know this.

**`tags`.** 105 rows seeded at startup from `PREDEFINED_TAGS` in `main.py`, in three
categories: `type` (10), `genre` (88) and `age` (7), plus a fourth category, `custom`, for
tags a household invents for itself. Seeding is by name, so a predefined tag deleted by
hand comes back on the next restart, and renaming one means a migration rather than an
edit to the list: `seed_tags()` would otherwise leave the old row and insert a second
beside it.

The list is long on purpose. A curated vocabulary that does not contain the genre somebody
wants is a vocabulary they work around, so the picker groups by category and starts each
group collapsed rather than trimming the list to what fits on a screen.

**`book_tags`.** Many-to-many. Both foreign keys are `ON DELETE CASCADE`, so removing a
book drops its tag links without touching the tags themselves. That cascade did nothing
until `PRAGMA foreign_keys` was turned on: it is off by default in SQLite, which made every
`ForeignKey` in `models.py` a comment. See *Connection settings* below.

**`user_books`.** Per-person read status, rating and reading dates (`unread` / `reading` / `read`). This is the table
that makes "read" a property of *a person and a book*, not of a book. A row only appears
once someone sets a status, so **absence means `unread`**. Every query filtering on status
has to treat a missing row as unread, and the API fills in `"unread"` when building
`my_status`.

**`loans`.** One row per lending event, never deleted. `returned_at IS NULL` identifies
the single active loan; a returned loan is retained as history. Two separate foreign keys
point at `users` (borrower and lender), which is why the relationships declare explicit
`foreign_keys=`. `due_at` is optional, because most family lending has no deadline;
`is_overdue` is **computed per request, never stored**, since a stored flag would be wrong
from the moment the deadline passed until something happened to write to the row.

**A borrower need not be a member.** `loaned_to_user_id` is nullable, and
`loaned_to_name` holds a free-text name (120 characters) for somebody with no account: a
neighbour, a colleague, a book club. The whole point of recording a loan is remembering
who has the book, and the people most likely to keep one are exactly those who will never
have a login here. **Exactly one of the two is set**, enforced by the CHECK constraint
`ck_loans_one_borrower` rather than by the schema alone, for the same reason the open-loan
rule is an index: a restore and an import both write rows without going through
`LoanCreate`. The constraint also refuses an all-whitespace name, which satisfies
`IS NOT NULL` and identifies nobody. `LoanCreate` rejects both or neither with a 422.

Lending **from** an external, a book the household has borrowed rather than lent, is
deliberately not a loan. See [decisions.md](decisions.md).

**`notes`.** Free text, attached to a book and authored by a user.

**`settings`.** A small key/value store for things an admin changes at runtime rather than
at deploy time: the Google Books toggle and API key, the Goodreads lookup toggle, and the
default language. Values are strings; `backend/settings_store.py` handles typing. This
exists so turning a feature on does not require an environment change and a restart.

## What `user_books` carries beyond a status

`rating` is 1 to 5 or absent, per person for the same reason the status is: a shared shelf
does not mean a shared opinion of what is on it. Goodreads exports carry this, and the
importer parsed it and threw it away for months because there was nowhere to put it.

`started_at` and `finished_at` are **derived from status transitions**, not typed in.
Nobody fills in a date field; everybody moves a book to "reading" when they start it. The
rules, each of which exists for a case that came up:

| Transition | Effect |
|---|---|
| to `reading` or `read` | stamps `started_at` if it is not already set |
| to `read` | stamps `finished_at` if it is not already set |
| to anything but `read` | clears `finished_at` |
| to `unread` or `want_to_read` | clears `started_at` too |

Only stamping what is unset matters more than it looks: a UI with pressable buttons makes
re-selecting the current status easy, and that must not move a date already recording
something true. Clearing on the way back matters for the opposite reason: a book marked
unread again would otherwise sit in "books finished this year" forever.

## Series and location

`series_name` and `series_index` are two columns on `books`, not a `series` table. A series
has no attributes here beyond a name, and the questions asked of it ("what else is in this
one", "which numbers are missing") are answered by grouping on that name. A table would add
a join and an orphan-cleanup problem to buy nothing.

`series_index` is a **float**: omnibus editions and novellas really are numbered 2.5. The
gap calculation only considers whole numbers, so a 2.5 does not make 2 or 3 look absent.

`location` is free text, indexed. Deliberately not an enum or a table: nobody knows their
own shelf taxonomy before they start, and a wrong vocabulary imposed up front is worse than
a slightly untidy one that grows. `GET /api/books/locations` returns what is in use, which
the UI offers as suggestions rather than as a closed list.

## Ownership is not read status

`ownership` and `user_books.status` answer different questions, and conflating them is the
mistake the separation exists to prevent:

| | Question | Scope |
|---|---|---|
| `books.ownership` | Is a copy physically here? | The **object**. One value, shared. |
| `user_books.status` | Has this person read it? | The **person**. One row each. |

They are genuinely independent. A library borrowing is read and not owned; an unread gift
is owned and not read.

`unknown` exists because a **Goodreads export cannot answer the ownership question at
all.** It records what somebody read, not what is on their shelf. Defaulting those rows to
`owned` would assert something nobody checked; defaulting them to `not_owned` would be an
equally unfounded guess. So they arrive unverified, the app surfaces how many are waiting,
and a person confirms them in bulk.

Books added by scanning default to `owned`: somebody was holding the book when they
scanned the barcode on its back cover.

## Cascades

Deleting a book removes its `user_books`, `loans`, `notes` and `book_tags` rows. Books,
tags and users are never cascade-deleted by anything else. There is no delete-account
endpoint.

## The privacy rule

`books.is_private` is the only access control on content, and it means: *visible to the
account that added it, and to nobody else.*

This is enforced by one shared predicate, `visible_to(user_id)` in `models.py`:

```python
and_(
    Book.deleted_at.is_(None),
    or_(Book.is_private.is_(False), Book.added_by_user_id == user_id),
)
```

**Every query that returns or counts books must apply it.** It is used by the list,
search, export and all four statistics aggregations. Forgetting it in a new endpoint
leaks other people's private books and nothing else in the stack will catch it. That is why
it is a named function rather than a condition retyped at each call site.

**The trashed check rides along here on purpose.** Deleting a book stamps `deleted_at`
rather than dropping the row, so an accidental delete can be undone. Hiding a trashed book
needs exactly the same universal reach that privacy does, and every book query already
calls this function, which is why soft deletion did not have to be chased through twenty
call sites. A second rule that every query must remember would be the one eventually
forgotten. The trash view opts out with `in_trash_for(user_id)`, a separate function rather
than a flag on this one: a predicate that means "on the shelf" or "in the trash" depending
on an argument is one a caller can get backwards, and getting it backwards shows every
deleted book in the library.

Three details worth keeping:

- `.is_(False)` rather than `not Book.is_private`. The latter evaluates the Column
  object's Python truthiness and collapses to a constant, silently matching every row. It
  looks more idiomatic and is completely wrong.
- Fetching another user's private book returns **404, not 403**. A 403 would confirm that
  a book with that id exists, which is exactly what privacy is meant to withhold.
- The ISBN uniqueness check in `_create_book` deliberately does **not** apply it. The
  constraint is table-wide, so a clash with somebody else's private book is still a clash.
  That also makes it the one query that sees trashed rows, which is why re-adding a book
  the caller trashed purges that row rather than reporting a conflict about a book nobody
  can see.

Privacy can be changed by the book's owner or by an admin. Admins can also delete anyone's
note. There is no other privilege difference, and admin does not bypass the visibility
predicate in listings.

## Reading it from the API

`BookOut` is assembled per-request in `_book_to_out()`, which adds two fields that are not
columns:

- `active_loan`: the open `Loan`, or null.
- `my_status`: the caller's row from `user_books`, defaulting to `"unread"`.

Both depend on *who is asking*, so the same book row serialises differently for different
accounts. Do not cache `BookOut` across users.

## Connection settings

Three `PRAGMA`s are applied to every SQLite connection in `database.py`. Every one of them
is off, or too short, by default.

| Pragma | Why |
|---|---|
| `foreign_keys=ON` | Off by default, which makes every `ForeignKey` and the `ON DELETE CASCADE` on `book_tags` decorative. Migration `d4a91f3c72e8` had to delete association rows by hand for exactly this reason |
| `journal_mode=WAL` | Without it any write blocks every read for its duration, and this app has writes that are not short: an import, a restore, emptying the trash |
| `busy_timeout=5000` | Turns the remaining contention into a wait rather than an immediate "database is locked" |

## Indexes

Beyond the primary keys and the unique constraints, two sets are worth knowing about.

**Foreign keys** (migration `a17c5b2e94d0`). Not one foreign key column carried an index,
so the notes of one book, one member's shelf and everything under a tag were each a full
scan. Enforcing foreign keys is what made this urgent rather than merely wasteful: SQLite
checks the child side once per deleted parent row, so emptying the trash was quadratic.
`loans.loaned_by_user_id` is deliberately left alone, since nothing queries by it.

**One open loan per book** (migration `f2b8d6a03c17`). A partial unique index on
`loans(book_id) WHERE returned_at IS NULL`. Partial because a book lent, returned and lent
again is two rows with the same `book_id`, and only the open ones are exclusive. The rule
lived in application code in three places and one of them was wrong: merging two records
left both open loans open, so the merged book was out with two people at once.

**Exactly one borrower** (migration `d5c31b7a09fe`). The CHECK constraint
`ck_loans_one_borrower`: `(loaned_to_user_id IS NULL) <> (loaned_to_name IS NULL)`, plus a
`trim()` clause so an empty or whitespace name cannot pass. That migration drops the
partial index and recreates it around the table rewrite, because batch mode rebuilds a
SQLite table by reflecting it and a partial index returning as a plain unique one would
forbid ever lending a book twice.
