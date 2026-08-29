# Data model

Thirteen tables in `backend/models.py`, counted off `Base.metadata`: eleven entities, one
association table (`book_tags`), and one key/value store for runtime settings
(`settings`).

```
      User ──────┬──── added_by ────────► Book ◄──── book_tags ────► Tag
                 │                         │  ▲
                 ├──── UserBook ───────────┤  │
                 │     (read status)       │  │
                 ├──── ReadingProgress ────┤  │
                 │     (where you are)     │  │
                 ├──── Loan ───────────────┤  │
                 │     (to / by)           │  │
                 ├──── Note ───────────────┤  │
                 │     (what you thought)  │  │
                 └──── Quote ──────────────┘  │
                       (what it said)         │
                                              └── active loan = the Loan with returned_at IS NULL

      Collection ◄──── collection_id ───── Book       (one collection, or none)
                                            │
                                            └──────► Classification
                                                     (DDC 004, GND 4203576-4 Schatz)
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

`email` is where a reminder addressed to this member would go. Nullable, and NULL is every
row before it existed: no address means the household mailbox, which is the only mode the
mail sender has, so the column changes nothing until somebody fills a field in. It is
deliberately absent from `UserOut` for the same reason the appearance columns are, and it
is served only by the four routes in `routers/users.py` that exist for it. Who may write
it is not a property of the row but of the deployment: with `LDAP_EMAIL_ATTRIBUTE` or
`PROXY_EMAIL_HEADER` set, the directory owns the value and re-applies it at each sign in
exactly as it re-applies `is_admin`, and the field is read only for everybody including an
admin; unset, a member writes their own and an admin writes anybody's. There is no second
column recording which of those applies, because the answer is a configuration lookup:
`auth_backends.directory_owns_email` is the one place it is decided, and three call sites in
two modules ask it.

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
which is what lets a library own two paperbacks of one title while a re-scan of a book
already on the shelf is still refused. See *Copies* below. `added_by_user_id` is nullable so
deleting an account does not cascade away its books.

Every ISBN is canonicalised to **ISBN-13 on the way in** (`backend/isbn.py`), so the same
book cannot be added twice under its ISBN-10 and ISBN-13 spellings. An ISBN that fails its
check digit is rejected rather than stored: a misread barcode produces an entry that can
never be matched against any metadata source.

`ownership` records whether a copy is **physically on the shelf**: `owned`, `not_owned` or
`unknown`. It is deliberately **not** the same axis as read status. See below.

`lending` records whether the library will lend the copy: `happy`, `in_use` or `never`,
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
tags a library invents for itself. Seeding is by name, so a predefined tag deleted by
hand comes back on the next restart, and renaming one means a migration rather than an
edit to the list: `seed_tags()` would otherwise leave the old row and insert a second
beside it.

**`tags.key` is what a translated name is looked up by**, and it is nullable. A seeded row
carries the `TagKey` naming which curated tag it is; a tag the library invented has none,
and neither has a seeded row somebody renamed, because migration `c1f8a7e3d240` keyed only
the rows whose name still matched the English seed name exactly. So a null key means "this
row is theirs" and both cases fall back to the name as typed. `name` holds the **English**
name and nothing else translates it in the database: the German names live in
`frontend/src/i18n/tagNames.ts`, typed `Record<TagKey, string>` against the generated
client, so a seeded tag with no German name fails the frontend build the way a missing
message in `de.ts` does. Matching never reads it: `ddc.tag_names` projects a classification
number onto an English seed name, and the suggestion travels as a tag id. The cost of that,
which predates the key and is not closed by it: a household that renamed **Computing** gets
no tag suggested for DDC 004, silently, because the projection looks up a name.

Two derived columns on this table are recomputed after a restore rather than trusted from
the archive, in `backup._repair_seeded_tags`: `is_predefined`, and `key` by the migration's
rule. An archive taken before either existed carries neither, and a restored library would
otherwise read as one that had renamed its entire vocabulary.

The list is long on purpose. A curated vocabulary that does not contain the genre somebody
wants is a vocabulary they work around, so the picker groups by category and starts each
group collapsed rather than trimming the list to what fits on a screen.

**`book_tags`.** Many-to-many. Both foreign keys are `ON DELETE CASCADE`, so removing a
book drops its tag links without touching the tags themselves. That cascade did nothing
until `PRAGMA foreign_keys` was turned on: it is off by default in SQLite, which made every
`ForeignKey` in `models.py` a comment. See *Connection settings* below.

**`collections`.** Named parts of the shelf, pointed at by `books.collection_id`. Library
wide, one per book or none, and never a privacy boundary. See *Collections* below.

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

**`classifications`.** What a published scheme says a book is about: a scheme, a number
and the caption that scheme gave the number, as three columns rather than the one string
`"004 Informatik"` a catalogue hands over. That string cannot be sorted, cannot be matched
across languages and does not say which scheme it came from.

**Tags, `books.categories` and this are one store with three jobs, not three vocabularies.**
The difference is provenance. A tag is this library's own word. A category is whatever the
publisher claimed, uncontrolled. A row here is somebody at a national library placing the
book in a published schedule, and only that one means anything to another institution.

| Layer | What it is |
|---|---|
| `tags` | this library's own language, curated or invented |
| `books.categories` | whatever the publisher claimed |
| `classifications` | an assertion from a published scheme |

**Four schemes, and `number` means the same thing in three of them.** DDC and LCC are shelf
orders; GND is the German national subject authority file, and what the column holds for it
is the authority record number (`gnd`, `4203576-4`, `Schatz`). What those three share is the
job the column does: the identifier is stable and the caption is whatever the supplying
record wrote. That was measured across languages for Dewey; for GND the DNB is the only
supplier here, so every caption is German today. What differs is that a Dewey number also
sorts and a GND number does not, which costs nothing here because nothing sorts on it.

**LCSH is the exception and is stored as one.** The Library of Congress supplies no
identifier for a subject heading: no `valueURI` on any of 2,280 `<subject>` elements across
900 live records, measured 2026-08-24. The authorised heading string is the access point, so
it goes in `number` and `label` stays empty, because putting the same words in both would
state one fact twice. What that costs is worth knowing: a heading the Library of Congress
later revises (`Afro-Americans` became `African Americans`) changes this scheme's
identifier, where a GND number survives its own recaptioning. That is also why LCSH sorts
last at the ceiling.

| Scheme | Comes from | Caption |
|---|---|---|
| `ddc` | DNB and K10plus MARC 082, Library of Congress MODS, Open Library `dewey_decimal_class` | none, since 2026-08-24 |
| `lcc` | Library of Congress, Open Library `lc_classifications` | none |
| `gnd` | DNB MARC 650, 651, 655, 689 and 600 | the heading text |
| `lcsh` | Library of Congress MODS `<subject authority="lcsh">` | none: the heading **is** the number |

`number` is 120 characters, which is LCSH's doing. A notation never approaches it; an LCSH
heading carries its subdivisions (`Computer software -- Development`), and the longest of
1,559 measured live is 91. A bound of 40, which is what the column held until 2026-08-24,
refuses 399 of them, 25.6%, and refuses exactly the subdivided ones.

**Open Library's `subjects` are not on this list, and that is the decision rather than an
omission.** They are uncontrolled strings somebody typed (`open_syllabus_project`,
`fiction classics`), so they go to `subjects` with the publisher's own list. Only fields that
name a published scheme reach this table. The same rule keeps out the other 22 authority
values the Library of Congress mixes into one record (`fast`, `lcshac`, `rvm`, `sears` and
the rest): each is a separate authority file, so folding them into `lcsh` would make the
scheme name a lie. Argued in [`decisions.md`](decisions.md).

**An author identifier is not one of these.** The DNB writes it in the same `$0`, and
`100 $0` says who wrote the book where every scheme here says what the book is about. It is
deliberately read by nothing: see [decisions.md](decisions.md).

**The number is what gets matched, never the caption.** `004` is Informatik in a German
record and Computing in an English one, so a rule reading the caption matches on the least
portable part of the heading. `backend/ddc.py` projects the number onto the library's tag
vocabulary through the 100 published Dewey divisions. Measured against the DNB over ten
German ISBNs on 2026-08-23: eight carried a DDC heading, and none of the eight captions
matched any of the 105 seeded tag names. Only DDC is projected: a GND number is an
identifier rather than a place in a schedule, so there is no arithmetic that takes
`4203576-4` to a division.

**The projection is a suggestion, and no server path writes a tag from it.** Auto-applying a
machine derived tag turns a curated list into a generated one nobody can later tell apart,
so the ids are returned and the client offers them. The web client offers them **ticked**,
so on an ordinary scan they land unless the member unticks them; which of those two is "a
suggestion" is argued in [decisions.md](decisions.md). See
`serialisation.suggested_tag_ids`.

**At most 8 per book**, counted by both capped writers of the table rather than only by the
request schema (`backup.restore` is the third writer and is deliberately uncapped: it
reinstates a database rather than adding to one): they are additive across requests and neither the enrichment apply endpoint
nor the merge carries a rate limiter, and `BookOut.classifications` is on every listing row,
so an inflated book is paid for on every page that contains it. At the ceiling an incoming
heading is dropped rather than a stored one evicted, and **which one survives is decided by
order**: `_headings` sorts by scheme before it slices, so a Dewey number outranks a subject
heading, and that is done there rather than in a parser because by then `_merge` has
concatenated up to four catalogues. The order is DDC, LCC, GND, LCSH; the two subject
vocabularies come last because a record supplies several of each and one classification, and
GND comes before LCSH because its number is an identifier that outlives its caption where an
LCSH number is the caption. Re-measured on 2026-08-24, when the subject headings
started arriving: 3.07 headings per record over 85 DNB lookups and 2.9 over 189 records from
four DNB searches, with 1 and 8 records respectively above eight. Both are one catalogue's
figures and this bounds a book several can feed, so neither is headroom for the total.

`number` is a **normalised** notation, not whatever the source sent: every source path goes
through `ddc.notation`, which strips MARC's segmentation prime (`005.13/3` becomes
`005.133`, which is what the DNB stores for the same heading) and refuses anything that is
not a Dewey number. 53 of 463 live K10plus values carry that prime, measured 2026-08-23, so
without the strip an eighth of one catalogue's headings are a second spelling the unique
index cannot collapse.

`label` is null where the source carried the number alone, which is every MARC 082: the
field holds the notation and the printed schedule holds the words. Since the DNB moved to
MARC21 on 2026-08-24 **no source supplies a Dewey caption at all**, where `dc:subject` used
to answer `830 Deutsche Literatur`. A GND heading still arrives captioned, and
`catalogue.Record` still fills a missing caption from any source that has one. Unique per book, scheme
and number (`uq_classifications_book_scheme_number`), so selecting the same record twice
fills nothing in twice; **not** unique on the number alone, because a book carries a DDC and
an LCC at once and often two DDC numbers at two precisions. `ON DELETE
CASCADE`, like `book_tags` and unlike `notes`: a heading means nothing without its book.

**`reading_progress`.** An append-only log of where a member has got to in a book. One
row is one moment somebody recorded a position, and nothing ever updates one. See
*Progress is a log* below.

**`loans`.** One row per lending event, never deleted. `returned_at IS NULL` identifies
the single active loan; a returned loan is retained as history. Two separate foreign keys
point at `users` (borrower and lender), which is why the relationships declare explicit
`foreign_keys=`. `due_at` is optional, because most library lending has no deadline;
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

Lending **from** an external, a book the library has borrowed rather than lent, is
deliberately not a loan. See [decisions.md](decisions.md).

**`notes`.** Free text, attached to a book and authored by a user.

**`quotes`.** A passage copied out of a book: `text`, an optional `page`, and an optional
`note` about it. Three columns rather than one, and each of the three is a decision:

* `text` and `note` are separate because `text` is meant to be a **faithful
  transcription** and `note` is the member's own words. Fold them together and the one
  field in this schema that is supposed to be verbatim is where people write their
  opinions. BookWyrm, which is the best worked example of this feature anywhere, keeps
  them apart for the same reason; BookLogr instead hangs a `quote_page` off its notes
  table, and nothing there can then tell a quote from a note that remembered a page.
* `text` is `String(2000)` where `notes.content` is unbounded `Text`. A quote is an
  excerpt of somebody else's copyrighted words, and 2,000 characters is about one printed
  page. The bound is also the stored-denial-of-service guard, which is why it is in the
  database and not only in `QuoteCreate`. **The width is not what enforces it**: SQLite
  ignores VARCHAR width, measured at 50,000 characters stored in a `String(2000)` column
  through Core, so `ck_quotes_text_bounds` is the rule and it covers `note` too.
* `page` is an integer, bounded 1 to 100,000 by `ck_quotes_page_bounds` as well as by the
  schema, so the list can come back in reading order. The cost is accepted rather than
  worked around: a passage from a roman-numbered preface has no page here and goes in
  unpaged.

A quote hangs off the **book row**, not off `copy_group`, because a page number is a fact
about an edition. It is visible to whoever can see the book, like a note and unlike
reading progress. Both choices are argued in [decisions.md](decisions.md).

**`settings`.** A small key/value store for things an admin changes at runtime rather than
at deploy time: the Google Books toggle and API key, the Goodreads lookup toggle, the
default language, the days between reminders, and one group per reminder channel: the
webhook (its toggle, URL and signing secret), mail (its toggle, the seven standard `MAIL_*`
settings and the recipient list) and Telegram (its toggle, bot token and chat id). Values
are strings; `backend/settings_store.py` handles typing. This exists so turning a feature
on does not require an environment change and a restart.

**A settings row is not always the value in force.** Ten of these may be pinned by the
deployment through an environment variable, and where one is, it wins and the app refuses
to store a different value beside it. `settings_store.in_force` is the reader that applies
that rule, and every consumer goes through it rather than through `get_raw`.

**`custom_fields` and `custom_field_values`.** A fact this library keeps about a book that
the schema does not know about. The definition is library wide (a `name`, unique
case-insensitively, and a `kind` of `text` or `url`); the value is per book, one row per
`(book_id, field_id)`, and **exists only when there is something in it**. The first concrete
use, and the reason the pair exists, is a link to the same book in a calibre-web instance.

Two tables rather than a JSON column on `books`, because a rename has to keep every value
under it: a value references the definition by id and never carries its name, so renaming is
one UPDATE of one row. A JSON blob would be a rewrite of every row that mentions the old
name.

`MAX_CUSTOM_FIELDS` is 25 and is **the only ceiling the feature needs**: a book holds at most
one value per definition, so bounding the definitions bounds every book's payload and every
rename's blast radius. `ck_custom_field_values_bounds` refuses a zero-length value, which is
what makes "a book with no value shows nothing" a property of the schema rather than a filter
somebody has to remember, and it caps the value at 500 characters, which SQLite's VARCHAR
width does not.

Whether a value renders as a **link** is decided on every read, not stored:
`custom_fields.link_target` hands back a target only for `http` or `https` with a real host,
no credentials and a parseable port. A `url` field whose value does not survive that is
served as text. See [security.md](security.md).

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

### Where these rules live

`backend/reading.py` owns the table. A caller asks `Reading.by(db, member_id)` and gets one
member's record, so the `user_id` filter is a property of construction rather than of
remembering, exactly as `Shelf.seen_by` is for the privacy predicate. Absence-means-unread
is `Records.status_of`, the date rules are `_stamp_reading_dates`, and the three writes that
are reading events (`mark`, `mark_each`, `begin`) stamp while the two that are not (`rate`,
`offer_to_discuss`) deliberately do not.

Two module functions read across members and both are named rather than left to a comment:
`discussers()`, for the one public column above, and `resolve_merge()`, which folds
everybody's records onto the surviving book when two rows turn out to be one. Left out, the
losers' rows are cascade deleted and those members lose their history.

`backend/tests/test_reading.py::TestReadingIsTheOnlyWayIn` holds it: no module but
`reading.py`, `shelf.py`, `backup.py` and `models.py` may even import `UserBook`, and the
two ways past a member are counted by call site so neither list grows quietly. `shelf.py`
is on that list because three of its Book listing filters join `user_books`, which is the
Shelf's rule and not this one.

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
through `Reading.begin`, over `_stamp_reading_dates`, which owns those rules. It **never** sets `read`, whatever
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

`collection_id` is the other half of "where does this live", and it is the opposite shape: a
real row, because a typo would otherwise make a second shelf rather than a second spelling.
See *Collections* below.

`author` is the third member of the same family and is derived the same way, with one
addition: a table of the decisions grouping cannot make. See *Authors* below.

## Authors

**There is no `authors` table.** `books.author` is a single free text column holding a
**comma separated** credit line, and an author is a name inside it. Everything the author
pages serve is a `GROUP BY` over that column, exactly as the series pages are a `GROUP BY`
over `series_name`. `backend/authorship.py` is the whole of the derivation: it owns the index query, the alias rows and the merge writes, over the pure rules in `backend/authors.py`.

An author is addressed by a **key**, which is derived from the name rather than being an
identity behind it: `authors.author_key(name)` casefolds, strips accents, turns punctuation
into a space and collapses the result. A merge retires the keys it folds along with the
spellings, so a key is exactly as durable as the name, and a link carrying a retired one
resolves through the alias rows rather than by the key surviving. So `J.R.R. Tolkien`, `J. R. R. Tolkien` and `j r r tolkien` are one
person with no decision required of anybody, while `JRR Tolkien` is not: that fold needs the
spaces dropped too, which also folds `Ann Aker` into `Anna Ker`, so it is offered as a
suggestion instead. See [decisions.md](decisions.md), *Three keys*.

**Two stored tables, and they answer different questions about the same key.** That
sentence used to read "`author_aliases` is the one stored table in the feature", which
stopped being true when `author_identifiers` arrived.

**`author_aliases`** holds decisions rather than data:

| Column | |
|---|---|
| `alias_key` | the key of the spelling being folded away. **Unique**: a spelling means one person |
| `canonical_name` | the name to show, as a member typed or picked it. Need not be a name any book carries |
| `created_by_user_id` | provenance, read by nothing, nullable so deleting an account keeps the library's decisions |

Nothing in it is a foreign key, because there is no author row to point at, and that is what
makes it survive: a spelling no book carries any more leaves an alias that matches nothing
and costs one row, and the same alias starts working again by itself the day an import
re-creates that spelling. Merging never writes to `books`, so undoing one is deleting the
row and the credit lines still say what the covers say.

**`author_identifiers`** holds which record in an external authority file a spelling
means:

| Column | |
|---|---|
| `author_key` | the key of the spelling, the same fold `author_aliases.alias_key` uses |
| `scheme` | which file. The closed set is `enums.AuthorityScheme` and it is the only place that states how many there are: `gnd`, `isni`, `lcnaf`, `viaf`, `wikidata`, and one per national library for Brazil, Argentina, Spain, Portugal, Italy and Chile |
| `identifier` | the number, stored bare without MARC's `(DE-588)` wrapper |
| `provenance` | `catalogue` where a record for this book's own ISBN asserted it, `member` where a person confirmed a candidate |
| `created_by_user_id` | set on a `member` row and null on a `catalogue` one, by check constraint |

**Per spelling, not per person**, which is the same shape as the aliases and for a sharper
reason: two spellings a member folded into one author may carry different numbers, and that
disagreement is evidence rather than noise. One row per person would have to pick a winner
at write time with nothing left to inspect, so both are stored and the author listing
reports the conflict. `(author_key, scheme)` is unique, so an identifier cannot be retyped;
correcting a wrong one is a delete, and a later import may write it back.

Like the aliases, nothing here is a foreign key to an author, for the same reason: there is
no author row to point at.

**Splitting is on the comma, and that is not the rule `categories` uses.** Categories are
semicolon joined because Google's category names contain commas; author names contain commas
too, and this field is comma separated anyway, because every writer of it joins with `", "`
and every importer runs a single name through `flip_catalogue_name` first. The residue is a
name that reached the column in catalogue order regardless ("Le Guin, Ursula K."), which
splits into two people; repairing that is what merging is for, and the `fragment` suggestion
rule is aimed at it.

**The privacy rule reaches all of it, and it is on the shelf rather than on the mapping.**
The index is built from one query that applies `visible_to`, so a private book cannot put a
name in the list, add to a count, appear in a suggestion or answer the `?author=` filter. An
author whose every book is private therefore appears for nobody else: nothing they can see is
credited to a spelling that resolves to that person. Merging an author nobody can see is
**404**, not 403.

The **mapping** is library wide, like a collection's name: every member resolves a spelling
to the same person, so identity does not fork per reader and an old link resolves the same way
for everybody. What is filtered beside the shelf is what a member has evidence for: a folded
spelling is listed, and its undo offered, only where it appears on a book they can see.

## Copies

A library that genuinely owns two paperbacks of one title has two objects, and the whole
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

## Collections

**`collections`.** A named part of the shelf: physical and ebook, kept and sold, one
person's and another's. `books.collection_id` is nullable and points at one of them.

**One collection per book, not many.** All three splits above are partitions, so the answer
is a column rather than a join table. A list would need a rule in every filter, sort, export
cell and payload field for a book in three at once, and it would be a second tag system with
a worse picker: tags are already the many-to-many axis, and an overlapping label belongs
there.

**One column holds one axis**, and the three splits above are three axes. Two objects on
different shelves are two rows (see *With copies* below). A **single** object that is both
"Ebooks" and "Sold" has no second row to occupy: pick one axis for the collection and put
the other on a tag. That is the case the multi-axis pitch creates and the one copies does
not answer.

**Null means unfiled, and no collection was ever invented for existing books.** The
migration backfills nothing. A default collection would need a name chosen in one language
for libraries that never asked for the feature, and renaming a seeded string later means a
migration. So "in no collection" is an ordinary permanent state, like a null `format` or
`lending`, and the API names it: `GET /api/books?unfiled=true`.

**Library wide, and never a privacy boundary.** Any member may create one, rename it, and
file any book they can write to. Filing changes nothing about who can see the book:
`visible_to()` remains the only access control on content, and it is not given a collection
to consult. `Collection.created_by_user_id` is provenance and no query reads it, which is
what keeps that true rather than merely intended.

The one thing a library wide label could disclose is a **count**, so every count is
filtered: `routers/collections._counts` and the `by_collection` statistic both apply
`visible_to`. A member filing a private book onto a shared shelf does not thereby tell
everybody it exists.

**Deleting a collection unfiles its books and destroys none.** `ON DELETE SET NULL` in the
database rather than a loop in the handler, because a restore and a hand-edited row reach
the table without passing through one, and a row pointing at a destroyed collection is a
dangling foreign key. That makes `PRAGMA foreign_keys=ON` load bearing here.

**The name is unique case insensitively**, through `uq_collections_name_folded`, a unique
index on the stored `name_folded`. "Ebooks" and "ebooks" as two shelves is a typo nothing
downstream can tell apart.

`name_folded` is `name.lower()`, computed in Python by a `@validates` hook on the model and
written on every ORM write of the name. `name` itself stays exactly what somebody typed,
because that is what a picker shows.

**It used to be a functional index on `lower(name)`, and that was ASCII only** (issue #77).
SQLite folds the 26 ASCII letters and leaves every other letter alone, so `Ästhetik` and
`ästhetik` were two shelves while `Fiction` and `fiction` were one. `COLLATE NOCASE` folds
the same 26 letters: measured, `'Ästhetik' = 'ästhetik' COLLATE NOCASE` is 0. A Unicode
aware `lower()` in SQLite needs the ICU extension, which this image does not build. So the
fold moved to Python, where it is correct, and the copy that a stored column implies is
kept in step by having exactly one place that derives it. `backup.restore` is the one
writer a validator cannot reach, because Core `insert()` never fires one, so `_parse_row`
recomputes the value on the way in.

### With copies

`collection_id` is **per row, so per copy**, exactly like `location`: the paperback and the
epub of one title are two objects and belong on different shelves. A group therefore spans
collections, and `POST /api/books/{id}/copies` does not inherit the field, unlike
`is_private`, which it does. The difference is the test for any future per-copy field:
privacy is inherited because getting it wrong discloses a book, and a collection is not
because getting it wrong is visible and one press to correct.

`copy_count` still counts the whole group across collections. It answers "how many do we
own", not "how many are on this screen".

The unique ISBN index stays **table-wide** rather than gaining a collection scope. Scoping
it would let "add this book to Ebooks too" create a second ungrouped row with the same ISBN,
which is the exact state the constraint exists to refuse. Putting one title in two
collections is a copy, made deliberately, with a token.

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

Deleting a book removes its `user_books`, `loans`, `notes`, `book_tags` and
`custom_field_values` rows. Deleting a custom field definition removes its values, and
`custom_fields.remove` does that itself rather than trusting the cascade, for the reason
`delete_tag` clears its association rows: SQLite enforces a foreign key only while
`PRAGMA foreign_keys` is on, and a migration's connection does not have it. Books,
tags, collections and users are never cascade-deleted by anything else: deleting a
collection sets `books.collection_id` to null and leaves every book where it was. There is no delete-account
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

**Every query that returns or counts books applies it, and none of them says so.**
`backend/shelf.py` owns the predicate: a caller asks `Shelf.seen_by(db, member_id)` and
narrows what comes back, so visibility is a property of how the query was built rather
than something each endpoint has to remember. It used to be retyped at each call site,
and forgetting it in a new endpoint leaked other people's private books with nothing else
in the stack to catch it.

**The trashed check rides along here on purpose.** Deleting a book stamps `deleted_at`
rather than dropping the row, so an accidental delete can be undone. Hiding a trashed book
needs exactly the same universal reach that privacy does, and every book query already
went through this function, which is why soft deletion did not have to be chased through
twenty call sites. A second rule that every query must remember would be the one eventually
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

**A custom field value obeys this rule without carrying a copy of it.** Every reader and
writer in `custom_fields.py` takes `Book` objects rather than book ids, and a `Book` can only
have been fetched, which means it has already been through the Shelf or through
`dependencies.py`. So there is no second predicate to apply and nothing to forget: a caller
that reaches for a value with an id off a URL gets a type error at the call site.
`CustomField` deliberately carries no `values` relationship, so a definition cannot be walked
to every book's value for it.

Privacy can be changed by the book's owner or by an admin. Admins can also delete anyone's
note. There is no other privilege difference, and admin does not bypass the visibility
predicate in listings.

## Reading it from the API

`BookOut` is assembled per-request in `_book_to_out()`, which adds two fields that are not
columns:

- `active_loan`: the open `Loan`, or null.
- `my_status`, `my_rating`, `my_started_at`, `my_finished_at`, `my_wants_to_discuss`: the
  caller's row from `user_books`, with the status defaulting to `"unread"`. Read through
  `Reading.of`, one statement for the page.
- `discuss_with`: every member who has offered to talk about this book, the caller
  included. **Not scoped to the caller**, unlike everything else in this list, which is the
  point of the flag rather than an oversight. See *What `user_books` carries* above.
- `my_progress_page`, `my_progress_percent`, `my_progress_recorded_at`: the caller's newest
  row from `reading_progress`. The percentage is the derived one.
- `collection_name`: the name of the collection `collection_id` points at, or null. A
  projection of that row rather than a second copy of it, batched in one statement for the
  page, so a rename is visible on the next fetch and nothing is migrated.
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

**One name per collection, case insensitively** (migrations `c2f95a80d417`, then
`e7b3d02a5c94`). `uq_collections_name_folded`, a unique index on the stored `name_folded`.
It began as a functional index on `lower(name)`, on the argument that a stored column is the
same name written twice; what that bought was a rule that held for ASCII and nothing else,
so the second migration reversed it. That migration also **merges** any pair a live library
already holds, into the lower id, because the new index cannot keep both and an upgrade has
nobody to ask. `books.collection_id` is indexed beside it, because filtering the library by
collection is a browse over the whole catalogue rather than a search.

**One person per spelling** (migration `a9c4e7b21d03`). `author_aliases.alias_key` is
unique, so re-merging a spelling somewhere else replaces the row rather than adding a second
one for a reader to choose between. No index on `canonical_name`: the table is read whole on
every author request (it is one row per merge a library has made) and never searched.

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
