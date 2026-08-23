# Data model

Nine tables in `backend/models.py`. Seven entities, one association table, and one key/value
store for runtime settings.

```
      User ──────┬──── added_by ────────► Book ◄──── book_tags ────► Tag
                 │                         │  ▲
                 ├──── UserBook ───────────┤  │
                 │     (read status)       │  │
                 ├──── ReadingProgress ────┤  │
                 │     (where you are)     │  │
                 ├──── Loan ───────────────┤  │
                 │     (to / by)           │  │
                 └──── Note ───────────────┘  │
                                              └── active loan = the Loan with returned_at IS NULL
```

## Tables

**`users`.** `username` is unique and case-sensitive. `password_hash` holds a bcrypt
digest; the plaintext is never stored or returned. `is_admin` is granted to whoever
registers first and is not editable through the API afterwards.

`is_test_account` marks an account an admin created for testing. It decides two things and
nothing else: the account is the only kind `/auth/switch` will issue a session for, and a
directory identity of the same name will not adopt its row (it is renamed aside instead).
A column rather than "`auth_source` is local", because a local account from before a
deployment moved to a directory is also local and belongs to a real person. See
[security.md](security.md) and [decisions.md](decisions.md).

`appearance_palette`, `appearance_mode` and `appearance_wallpaper` are the member's own
look, nullable, with NULL meaning "has not chosen" rather than a value. Columns rather than
a `user_preferences` table: it is a one-to-one with no history, and a side table would add a
join to every read plus a row that both shadow-account paths in `auth_backends.py` would
have to remember to create. They are deliberately absent from `UserOut`; see
[theming.md](theming.md).

**`books`.** The catalogue, one row per **object on the shelf** rather than per title.
Everything in it that is not the work is already per copy: `location`, `condition`,
`format`, `lending`, `ownership` and the four purchase columns.

`isbn` is nullable, which is deliberate: SQL treats NULLs as distinct, so any number of
manually-added books can coexist without an ISBN. It is unique through
`uq_books_isbn_single_copy`, a **partial** index over the rows whose `copy_group` is null,
which is what lets a household own two paperbacks of one title while a re-scan of a book
already on the shelf is still refused. See *Copies* below. `added_by_user_id` is nullable so
deleting an account does not cascade away its books.

Every ISBN is canonicalised to **ISBN-13 on the way in** (`backend/isbn.py`), so the same
book cannot be added twice under its ISBN-10 and ISBN-13 spellings. An ISBN that fails its
check digit is rejected rather than stored: a misread barcode produces an entry that can
never be matched against any metadata source.

`ownership` records whether a copy is **physically on the shelf**: `owned`, `not_owned` or
`unknown`. It is deliberately **not** the same axis as read status. See below.

`lending` records whether the household will lend the copy: `happy`, `in_use` or `never`,
and null while nobody has been asked. A third axis again, and not a fact about right now:
see *Three axes, not one* below.

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

**`user_books`.** Per-person read status, rating, reading dates (`unread` / `want_to_read` /
`reading` / `read` / `did_not_finish`) and the "ask me about this book" flag. This is the table
that makes "read" a property of *a person and a book*, not of a book. A row only appears
once someone sets a status, so **absence means `unread`**. Every query filtering on status
has to treat a missing row as unread, and the API fills in `"unread"` when building
`my_status`. Setting anything on a book with no row creates one, which is why the discuss
endpoint reads like the status and rating ones.

**Cover images are files** under `data/covers/<book id>.<ext>`, not a column. `cover_url` is
the pointer a client renders: `/covers/<id>.<ext>` for a cover this app holds, the remote URL
for a book whose download failed. `docs/decisions.md` records why that rather than a BLOB,
with the measurements, and what it costs.

The cost, in one line so it is not rediscovered: **a row delete does not delete a file.**
Purging a book, emptying the trash and merging two books each deal with the cover
explicitly, and nothing decides whether a cover exists by reading `cover_url`. The column and
the directory can drift, so the filesystem is the authority.

**`reading_progress`.** An append-only log of where a member has got to in a book. One
row is one moment somebody recorded a position, and nothing ever updates one. See
*Progress is a log* below.

**`loans`.** One row per lending event, never deleted. `returned_at IS NULL` identifies
the single active loan; a returned loan is retained as history. Two separate foreign keys
point at `users` (borrower and lender), which is why the relationships declare explicit
`foreign_keys=`. `due_at` is optional, because most household lending has no deadline;
`is_overdue` is **computed per request, never stored**, since a stored flag would be wrong
from the moment the deadline passed until something happened to write to the row.

`notified_at` is the one piece of state the overdue digest keeps: when a reminder last
went out for this loan, or null if none ever has. Stamped only after a delivery that
succeeded, so a failed one retries on the next run. Without it the digest either sends
once and forgets a book that is still out, or repeats the same list every hour.

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
at deploy time: the Google Books toggle and API key, the Goodreads lookup toggle, the
default language, and the four that configure overdue reminders (the toggle, the webhook
URL, its signing secret, and the days between reminders). Values are strings; `backend/settings_store.py` handles typing. This
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
| to `reading`, `read` or `did_not_finish` | stamps `started_at` if it is not already set |
| to `read` | stamps `finished_at` if it is not already set |
| to anything but `read` | clears `finished_at` |
| to `unread` or `want_to_read` | clears `started_at` too |

Only stamping what is unset matters more than it looks: a UI with pressable buttons makes
re-selecting the current status easy, and that must not move a date already recording
something true. Clearing on the way back matters for the opposite reason: a book marked
unread again would otherwise sit in "books finished this year" forever.

`did_not_finish` needed **no fourth rule**, and that is the point of listing it in the table
rather than as an exception. It is a claim that reading started, so it stamps `started_at`
alongside the other two; it is not a finish, so the third row already clears `finished_at`
for it. What it must never do is reach the fourth row: clearing `started_at` would erase
that the book was ever picked up, which is the one thing the status is for.

It also deletes no `reading_progress` row. How far somebody got before giving up is exactly
the interesting part.

No migration was needed: `user_books.status` is a plain `String(20)`, so a new member of the
enum is a new value in a text column, and existing rows are untouched.

`wants_to_discuss` is "ask me about this book", and it is **the one column on this table
meant to be read by other people.** The status, the rating and both dates are private to
the member who set them and reach the API only as the caller's own `my_*` fields. This one
is the opposite: a flag whose entire purpose is that somebody browsing the shelf notices it
and asks, so `BookOut.discuss_with` names everybody who has set it, on every book the
caller can see. It discloses the usernames and nothing else, in particular not whether
those members have read the book.

It is NOT NULL with a default of false rather than nullable, unlike `books.lending`. There
is nothing between yes and no here, and absence of the row already means "has not said" for
every member who never touched the book, so a nullable column would be a second and weaker
spelling of the same thing.

Per member rather than per book because two people can hold the same copy and feel entirely
differently about it, which is the same reason the rating is per member.

## Progress is a log

`reading_progress` answers "where am I" the same way a bank statement answers "how much
have I got": by recording every movement rather than by keeping one number.

| Column | Rule |
|---|---|
| `user_id`, `book_id` | Whose reading of which book. Personal, like a status |
| `recorded_at` | Server-stamped. Ordered under `(user_id, book_id)`, never on its own |
| `page` | The page reached |
| `percent` | 0 to 100, for anything with no page count |
| `minutes` | How long the sitting was. Optional, and nothing derives from it |

**A log, not a `current_page` column on `user_books`.** A column answers "where am I" and
destroys everything else on every save. The questions this table exists for, "how much did
I read in March" and "how long did that one take", are about the history.

**Exactly one unit per row**, enforced by `ck_reading_progress_one_unit`:
`(page IS NULL) <> (percent IS NULL)`. An audiobook has no pages, and neither has a book
whose `page_count` no provider supplied. Carrying both units on one row would need a rule
for which wins; carrying one needs no such rule. A second CHECK,
`ck_reading_progress_bounds`, refuses page 0, a percent outside 0 to 100, and zero minutes.
Both are in the database and not only in `ProgressCreate`, for the same reason
`ck_loans_one_borrower` is: a restore inserts through Core.

**The displayed percentage is derived, never stored twice.** `page / books.page_count`
when the page count is known, else the stored `percent`, else nothing. Clamped at 100,
because a provider's page count is off by one often enough that the last page computes to
101. `serialisation.derived_percent` is the single definition.

**Recording progress promotes an unstarted book to `reading`** and stamps `started_at`,
through `_stamp_reading_dates`, which owns those rules. It **never** sets `read`, whatever
the page number: `page_count` is a provider's figure, and there is already an explicit
control for finishing.

**A status change never deletes progress rows.** That is deliberately unlike `started_at`
and `finished_at`, which are derived from the current status and are therefore cleared on
the way back to unread. These rows claim nothing about now, and a re-read is a real thing
whose earlier passes are worth keeping. A merge repoints them onto the surviving book
rather than letting the cascade take them.

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

## Copies

A household that genuinely owns two paperbacks of one title has two objects, and the whole
of the previous paragraph is per object. So a copy is a **second row**, and `copy_group` is
what joins it to the first.

**The token is the difference between a copy and a duplicate**, and that distinction is the
feature. Two rows with no group naming the same book are an accident: the partial unique
index refuses the second one, and `/duplicates` offers whatever slipped past it for merge.
Two rows sharing a group are a deliberate statement by somebody who pressed "add another
copy", and neither the index nor the duplicate finder touches them.

| | Accidental duplicate | Deliberate copy |
|---|---|---|
| How it arises | A re-scan, a CSV import, a hand entry | `POST /api/books/{id}/copies`, one press |
| `copy_group` | null on both rows | the same token on every row |
| The unique index | refuses it | does not apply |
| `/duplicates` | offers it for merge | collapses the group to one row and never reports it |
| Merging them | the point | allowed, and means "they were never two objects" |

An **opaque shared label, not a self-referencing foreign key.** "Is a copy of" is symmetric:
two paperbacks are peers and neither is the original. A self-FK would invent a distinguished
row, and a distinguished row needs a rule for what happens when it is purged, which five
delete paths would each have to remember. A shared label needs no such rule. It is not a
foreign key either, so nothing dangles when a member of the group is destroyed.

**Cleared when a group shrinks to one row, and only on a purge.** The token is what suspends
the unique index for that ISBN, so a group of one should be exclusive again. Never on a
trash: a trashed copy can be restored, and clearing the token underneath it would leave two
formerly grouped rows with one ISBN and no token, which is exactly what the index refuses.
The restore would then fail on a button that has nothing to do with copies.

**Loans needed no change.** `uq_loans_one_open_per_book` is one open loan per book row, and
a copy is a book row, so "one is lent out and one is on the shelf" is already expressible. A
copy **count** column could not have said that, which is why this is rows: see
[decisions.md](decisions.md).

## Three axes, not one

`ownership`, `lending` and `user_books.status` answer different questions, and conflating
any two of them is the mistake the separation exists to prevent:

| | Question | Scope |
|---|---|---|
| `books.ownership` | Is a copy physically here? | The **object**. One value, shared. |
| `books.lending` | Would we lend it? | The **object**. One value, shared. |
| `user_books.status` | Has this person read it? | The **person**. One row each. |

`lending` is a standing intention and not a state. It is not "is this book out": that is
the open `Loan`, and a book can be marked happy to lend while it is at somebody's house, or
marked never lent and out with a sibling anyway. Storing the answer on the loan would mean
it only existed while the book was somewhere else.

`in_use` is why it is three values rather than a boolean. "I need it myself at the moment"
is a real answer and is not a refusal: come back later, which yes-or-no cannot say. `never`
is the opposite, a rule rather than a state, and nothing about the shelf changes it.

Null rather than a default, like `format` and `condition`: an unanswered question is not an
answer, and a guess written into every imported book at once is worse than a blank, because
nobody re-checks a field that looks filled in.

What creating a loan does about it is in [api.md](api.md) and [decisions.md](decisions.md):
refused once, then allowed.

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
endpoint, test accounts included: removing a member means deciding what happens to the
books they added, the loans they are in and the notes they wrote.

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
- `my_status`, `my_rating`, `my_started_at`, `my_finished_at`, `my_wants_to_discuss`: the
  caller's row from `user_books`, with the status defaulting to `"unread"`.
- `discuss_with`: every member who has offered to talk about this book, the caller
  included. **Not scoped to the caller**, unlike everything else in this list, which is the
  point of the flag rather than an oversight. See *What `user_books` carries* above.
- `my_progress_page`, `my_progress_percent`, `my_progress_recorded_at`: the caller's newest
  row from `reading_progress`. The percentage is the derived one.
- `copy_count`: how many copies of this title the caller may see, this row included. 1 for
  almost every book, and it counts only visible rows for the same reason everything else
  here does.

All of them are filled in one query each for the whole page, not one per book.
`serialisation.books_to_out` carries the measured statement counts; they are not repeated
here, because a number restated in three places is a number that is wrong in two of them.

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

**Reading progress** (migration `f7c2a1e50b93`). One composite index, on
`(user_id, book_id, recorded_at)`, which is the only question asked of the table: this
member, this book, in order. `recorded_at` deliberately has **no** index of its own: the
per-month statistic reads it under `user_id` and the history reads it under
`(user_id, book_id)`, so the composite serves both, and a second index on an append-only
table would be a write cost with no read behind it.

**One ISBN per uncopied book** (migration `b1e7c94a2d05`). `uq_books_isbn_single_copy`, a
partial unique index on `books(isbn) WHERE copy_group IS NULL`, which replaced the plain
UNIQUE the column used to carry. `ix_books_isbn` survives it, rebuilt non-unique, because
the scan flow still looks an ISBN up on every add: the index is the lookup, the partial one
is the rule. `deleted_at` is deliberately **not** in the predicate. A trashed row keeps its
claim on the ISBN, which is the trap `_create_book` frees the holders to resolve, and excluding
trashed rows here would move that trap rather than remove it.

**Lending willingness** (migration `d1a7f36b9c58`). `ix_books_lending`, for the same reason
`ix_books_format` exists: "what could we lend the book club" is a filter over the whole
catalogue, which is a browse action rather than a search.

`reading_progress.book_id` is indexed as well, for the reason in *Foreign keys* above
rather than for any query: it is a child of a table whose rows get deleted, and purging a
book from the trash checks it once per deleted row.

**Exactly one borrower** (migration `d5c31b7a09fe`). The CHECK constraint
`ck_loans_one_borrower`: `(loaned_to_user_id IS NULL) <> (loaned_to_name IS NULL)`, plus a
`trim()` clause so an empty or whitespace name cannot pass. That migration drops the
partial index and recreates it around the table rewrite, because batch mode rebuilds a
SQLite table by reflecting it and a partial index returning as a plain unique one would
forbid ever lending a book twice.
