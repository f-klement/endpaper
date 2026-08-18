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

**`tags`.** About 30 rows seeded at startup from `PREDEFINED_TAGS` in `main.py`, in three
categories: `type`, `genre`, `age`. Users pick from this list; they cannot invent tags.
Seeding is by name, so a tag deleted by hand comes back on the next restart.

**`book_tags`.** Many-to-many. Both foreign keys are `ON DELETE CASCADE`, so removing a
book drops its tag links without touching the tags themselves.

**`user_books`.** Per-person read status, rating and reading dates (`unread` / `reading` / `read`). This is the table
that makes "read" a property of *a person and a book*, not of a book. A row only appears
once someone sets a status, so **absence means `unread`**. Every query filtering on status
has to treat a missing row as unread, and the API fills in `"unread"` when building
`my_status`.

**`loans`.** One row per lending event, never deleted. `returned_at IS NULL` identifies
the single active loan; a returned loan is retained as history. Two separate foreign keys
point at `users` (borrower and lender), which is why the relationships declare explicit
`foreign_keys=`. `due_at` is optional, because most household lending has no deadline;
`is_overdue` is **computed per request, never stored**, since a stored flag would be wrong
from the moment the deadline passed until something happened to write to the row.

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
or_(Book.is_private.is_(False), Book.added_by_user_id == user_id)
```

**Every query that returns or counts books must apply it.** It is used by the list,
search, export and all four statistics aggregations. Forgetting it in a new endpoint
leaks other people's private books and nothing else in the stack will catch it. That is why
it is a named function rather than a condition retyped at each call site.

Two details worth keeping:

- `.is_(False)` rather than `not Book.is_private`. The latter evaluates the Column
  object's Python truthiness and collapses to a constant, silently matching every row. It
  looks more idiomatic and is completely wrong.
- Fetching another user's private book returns **404, not 403**. A 403 would confirm that
  a book with that id exists, which is exactly what privacy is meant to withhold.

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
