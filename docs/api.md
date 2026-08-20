# API reference

Base URL is the app's own origin. Interactive docs (Swagger) at `/docs`, the OpenAPI schema
at `/openapi.json`. Both are generated from the code, so they cannot drift from it, and
that schema is the input to the frontend's generated client.

This page covers what the schema does not express: who may call what, and why a given
status code comes back.

## Authentication

Stateless JWT, HS256, seven-day expiry. Send it as `Authorization: Bearer <token>`. There
is no refresh token and nothing to revoke. See [security.md](security.md).

| Level | Meaning |
|---|---|
| public | No token required |
| user | Any valid token |
| owner | The member who added the book, or an admin |
| admin | An account with `is_admin` |

## Pagination

Listing endpoints return an envelope, not a bare array:

```json
{ "items": [ … ], "total": 128, "page": 1, "page_size": 24 }
```

`total` is the count of rows **matching the filters**, not the length of `items`. The grid
needs it to know when to stop asking. `page` is 1-based; `page_size` defaults to 50 and is
capped at 200, which is what stops a caller requesting the whole library and undoing the
point of paging. Out-of-range values are a 422; a page past the end is an empty `items`
with the real `total`, not an error.

Ordering is always tie-broken by `id`, so paging is stable: two books with the same title
cannot swap between pages.

## Endpoints

### Auth

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/auth/config` | public | `{registration_enabled}`; read before anyone has a token |
| POST | `/auth/register` | public | 201 with a token. **403** if disabled, **400** if taken, **429** if rate-limited |
| POST | `/auth/login` | public | 200 with a token, **401** otherwise, **429** if rate-limited |
| POST | `/auth/switch` | **admin** | 200 with a token for a test account. **404** if the name is not one, **401** on a wrong password, **429** if rate-limited |
| GET | `/auth/me` | user | The current account |
| POST | `/auth/logout` | public | 204. Clears the cover cookie; the token is the client's to discard |

The first account becomes admin. Under `local` that is the first to register; under `ldap`
and `proxy`, where `register` is 403 and admin normally comes from a configured group, it
is the first person to sign in. Without that rule a deployment with no admin group
configured would have a library nobody could administer. For the same reason an existing
admin is never demoted by switching an existing deployment to a directory: the demotion
only happens when an admin group is actually configured and the account is not in it.

`ALLOW_REGISTRATION=false` blocks new signups without affecting existing accounts, and is
read per request.

Login accepts passwords shorter than the registration minimum on purpose, and reports the
same message for an unknown username as for a wrong password. Both are explained in
[security.md](security.md).

`/auth/switch` exchanges a password an admin supplies for a session on an **admin-created
test account**, which is the only way to see the library as an ordinary member sees it
under `ldap` or `proxy`, where `/auth/login` cannot reach a local password. It takes the
same body as `/auth/login` and returns the same `Token`, cover cookie included.

Two refusals are the whole of it, and the server owns both whatever the client sends. The
target must be a test account: a directory-backed account is **never** one, in any mode,
because an admin able to mint a session for a directory member could read that member's
private books. And the password is required and checked. Unlike `/auth/login` the two
refusals differ (404 and 401), because the caller is an admin who can already list every
account, so there is nothing left to enumerate.

Under `proxy`, the token this returns overrides the identity in the proxy's header until it
is discarded, and only a token naming a test account does. See [security.md](security.md).

### Books

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books` | user | Paginated. Filter with `q`, `status`, `ownership`, `series`, `location`, `unrated`, `tags`, `sort` |
| POST | `/api/books` | user | **409** on a duplicate ISBN |
| POST | `/api/books/scan` | user | Same, named for the scan flow |
| GET | `/api/books/tags` | user | The seeded vocabulary plus the household's own |
| POST | `/api/books/tags` | user | Invent a tag. Returns the existing one on a name clash |
| DELETE | `/api/books/tags/{id}` | user | Only a custom tag. **400** for a seeded one |
| GET | `/api/books/lookup?isbn=` | user | Metadata lookup, **404** if unknown |
| GET | `/api/books/export?format=csv\|txt` | user | File download, not paginated |
| GET | `/api/books/search?q=` | user | Free-text search for the add flow. Needs no API key |
| GET | `/api/books/series` | user | Every series, with the gaps in it |
| GET | `/api/books/locations` | user | Distinct shelf locations, most-populated first |
| GET | `/api/books/duplicates` | user | Books that look like the same work |
| GET | `/api/books/trash` | user | What the caller has deleted and could put back |
| DELETE | `/api/books/trash` | user | Empties it for good. Returns `{purged}` |
| POST | `/api/books/merge` | user | Fold several entries into one |
| POST | `/api/books/bulk` | user | One verb applied to a selection of books |
| GET | `/api/books/{id}` | read | **404** if absent *or* invisible |
| DELETE | `/api/books/{id}` | write | 204. Moves it to the trash, reversibly |
| POST | `/api/books/{id}/restore` | trashed | Puts it back, with everything on it |
| DELETE | `/api/books/{id}/permanent` | trashed | 204. Destroys it and its cover file |
| PATCH | `/api/books/{id}/privacy` | **owner** | **403** for another member |
| PUT | `/api/books/{id}/status` | read | Sets *your* status only |
| PUT | `/api/books/{id}/refresh` | write | **400** without an ISBN |
| POST | `/api/books/{id}/cover` | write | multipart; **400** wrong format, **413** too large |
| POST/DELETE | `/api/books/{id}/tags/{tag_id}` | write | Idempotent both ways |
| PATCH | `/api/books/{id}` | write | Correct title, author, year, series or location |
| PATCH | `/api/books/{id}/rating` | read | Your own 1 to 5, or null to clear |
| PATCH | `/api/books/{id}/ownership` | write | Whether a copy is physically here |
| POST | `/api/books/{id}/enrich` | write | Fill gaps from Google Books |
| GET | `/api/books/{id}/enrich/candidates` | read | Other editions, for picking the right one |

"read" and "write" are the access rules in [security.md](security.md): read means the book
is public or yours; write additionally means public books are a shared shelf any member may
curate.

`/search` and `/bulk` are declared **before** the `/{book_id}` routes. FastAPI matches in
declaration order, so `/search` would otherwise be a request for the book with id
"search". `/export` is there for the same reason.

`q` matches title, author or ISBN, case-insensitively. `tags` is a comma-separated list of
ids combined with **AND**; non-numeric entries are ignored. `status=unread` matches books
with no `user_books` row as well as rows set to `unread`. `sort` accepts `title_asc`, `title_desc`, `author`, `year_asc`, `year_desc`, `newest` and
`series`. Series order sorts by name then index, with unserialised books **last**: mixing
them in by a NULL index would scatter them through the list rather than grouping them at
the end.

`unrated=true` lists what *you* have not rated. It is a correlated exists rather than a
reuse of the status join, and it names the table to correlate against explicitly, because
otherwise SQLAlchemy auto-correlates the subquery's own FROM away whenever a status filter
is also present and the request 500s. `ownership` accepts `owned`,
`not_owned` or `unknown`; `?ownership=unknown` is the query the whole bulk-confirmation
flow is built around.

### Editing, rating and reading dates

`PATCH /{id}` is a partial update: an absent field is left alone and an explicit null
clears. That distinction is the whole point, and it is why the handler uses
`exclude_unset` rather than dumping the model.

`PATCH /{id}/rating` needs only **read** access, like status, because a rating is one
person's opinion and changes nothing for anyone else. It deliberately does not touch the
reading dates: rating a book is not a claim to have finished it just now.

The reading dates are never sent by a client. They are stamped from status transitions;
see [data-model.md](data-model.md) for the rules.

### Series, shelves and duplicates

`GET /series` returns each series with `missing_indexes`, which is the question a series
view exists to answer. Only gaps **below the highest number held** are reported: a series
with no known length has no meaningful missing past the end, and reporting one would invent
a book nobody said exists.

`GET /duplicates` matches on normalised title plus first author, **not** on ISBN. The
unique ISBN already makes exact repeats impossible, so the case left to catch is the one it
cannot see: a hardback and a paperback are the same book and two legitimately different
ISBNs. Matching is deliberately lossy, because this is a suggestion a person confirms.

`POST /merge` takes `{book_ids, keep_id}` and `keep_id` must appear in `book_ids`, spelled
out rather than inferred so a mistyped request fails instead of silently keeping whichever
row sorted first. The survivor absorbs only what it is missing, and tags, notes, loans and
statuses are repointed rather than dropped. Where the same member holds a status on two of
the merged rows, the survivor's own row wins: deleting somebody's reading history to
satisfy a unique index is not an acceptable resolution.

### Bulk actions

`POST /bulk` takes `{book_ids, action, value}` and answers with a three-way count:

```json
{ "updated": 12, "unchanged": 3, "skipped": 1 }
```


| Action | `value` |
|---|---|
| `add_tag`, `remove_tag` | a tag id |
| `set_status` | a reading status |
| `set_ownership` | an ownership status |
| `set_location` | free text; an empty string clears |
| `delete` | none |

One endpoint rather than six, because every verb shares the same three steps: resolve the
ids the caller may actually touch, apply, and report. Six handlers would be six copies of
the permission walk, and the fifth one added would be the one that forgot it.

`skipped` covers both halves of "not yours to change", ids that do not exist and ids
belonging to another member's private book. Distinguishing them in the response would
disclose which of the two it was.

### Ownership

`PATCH /{id}/ownership` sets one book. A selection goes through `POST /bulk` with
`set_ownership`, like every other bulk verb.

A separate `/bulk/ownership` existed until v0.2.0 with an identical body, permission walk
and result. It was removed before the first tag rather than after, because dropping an
endpoint after a release is a breaking change rather than a tidy-up.

`skipped` is **not an error**. A selection can include a book the caller may not modify,
and reporting success for it would be a lie. `unchanged` separates "already set" from
"changed", so the client can say what actually happened. `book_ids` is capped at 500.

### Google Books

Three endpoints share one gate. Both the toggle and the API key are admin settings, and a
**400** naming which one is missing comes back if either is absent. The message says who
can fix it and never echoes the key.

| Endpoint | For |
|---|---|
| `GET /api/books/{id}/enrich/candidates` | The editions to choose between |
| `POST /api/books/{id}/enrich/apply?overwrite=` | Filling in from the chosen one |
| `POST /api/books/{id}/enrich?overwrite=` | Filling in without asking, from the best match |

The UI uses the first two. The button opens a picker and **nothing is written until an
edition is clicked**, because choosing automatically is wrong often enough to matter: a
paperback and its hardback are the same book, different page counts and different covers,
and a catalogue will happily return the other one.

`POST /enrich` keeps the automatic behaviour for a caller that wants it. Both share the
merge rule, and it is the server's rather than the client's: only empty fields are filled
unless `overwrite=true`, so a publisher somebody typed by hand is never quietly replaced.
Neither ever takes the ISBN: it is unique, and a chosen printing's ISBN is not this copy's.

The candidates endpoint deliberately carries no `suggested_tag_ids`: that book already has
tags, and they are somebody's deliberate choice.

**Neither needs an API key.** Enrichment runs the merged ISBN chain when the book has an
ISBN and the ranked search when it does not, so a 978-3 book Google does not carry is
filled in from the DNB instead of reporting that no key is configured. Google joins in as
one more source when a key is set.

### Free-text search

`GET /api/books/search?q=&limit=&lang=` is how a book with no barcode, a damaged one, or
one printed before ISBNs existed gets added. **It needs no API key.**

Six catalogues, in three tiers, all asked concurrently:

| Tier | Sources | For |
|---|---|---|
| Primary | Open Library, K10plus, DNB | Breadth and covers; German and European publishing; German legal deposit |
| Regional | BnF, Library of Congress | French; Spanish, Portuguese and Latin American |
| Keyed | Google Books | The blurb and the categories, when an API key is configured |

Regional sources are ranked one point below the primaries, so they surface the books
nobody else holds without reordering the ones everybody does. That penalty applies only
when they are the sole source for a row.

Three things happen to the results, and each exists because leaving it out produced a
visibly wrong answer:

* **Denoising.** Digitised copies, audiobooks and sound recordings are filtered out by
  extent and resource type. A scanned copy of a novel is a real catalogue record and a
  wrong answer to "which book am I holding".
* **Merging.** One book found by several catalogues is one row, matched by ISBN or by
  title, author and year, with the gaps filled from every source that answered. Two rows
  naming different languages are never merged: a translation is not the same book.
* **Ranking.** The SRU catalogues return catalogue order, which is roughly newest first.
  Results are scored against the query: how much of it a row accounts for, then how
  complete the row is, then how recent. Completeness can never outrank matching.

`lang` is the reader's own language and breaks ties only, so an English title searched
from a German interface still returns the English book first.

A source that fails is skipped rather than failing the search, and a source that has not
answered within `SEARCH_DEADLINE_SECONDS` is cancelled. One national catalogue having a
bad afternoon degrades the results, not the latency.

Deduplication is **across** sources only, never within one. Two printings of one book share
a title and an author, and choosing between them is the entire point of the picker.

`q` is 2 to 200 characters and `limit` is 1 to 20, both validated before any upstream call.
Results carry `suggested_tag_ids` and a `source` naming every catalogue that found the row.

**Nothing is written by a search.** The client prefills its confirm step from the chosen
result and posts it back to `/api/books/scan`, exactly as the ISBN path does.

`enrich` fills gaps only unless `overwrite=true`, which the UI never sends: a typed-in
publisher is a correction and outranks anything upstream says. It answers with
`updated_fields`, which is what makes it honest: finding the volume and having nothing to
add is the common case, and reporting plain success there is indistinguishable from a broken
button. An upstream failure is a **502**, not a 500. The fault is Google's, and a 500 sends
whoever is on call looking at the wrong service.

### Importing from Goodreads

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/imports/goodreads?create_missing=` | user | multipart CSV; **422** if it is not an export |

There is no Goodreads API to connect to: they stopped issuing developer keys in December
2020. A CSV export is the only route in, and linking out to their search is the only other
integration available.

Identifier columns in an export are **spreadsheet formulas** (`="9780441013593"`), which is
the one trap that makes an import silently match nothing. Only the three exclusive shelves
map to a status (`read`, `currently-reading`, `to-read`); anything else is counted in
`skipped`. Statuses are written to the **importing member's** `user_books` rows only.

Books created by an import get `ownership=unknown`, never `owned`. See
[data-model.md](data-model.md).

### Metadata lookup

`GET /api/books/lookup` asks four catalogues in two phases and merges what comes back.

**Phase one, asked together:** the **Deutsche Nationalbibliothek** and **K10plus**, the
union catalogue of the German library networks. Both are free, need no key, and answered
in 0.1s and 0.4s against a ten-ISBN sample. Their records are merged field by field,
nothing overwritten, so a page count from one and a subject heading from the other land on
the same book.

**Phase two, asked in turn, only if neither knew the book:** **Open Library**, then
**Google Books**. Open Library is the broadest source and the thinnest, and at 1.6s the
slowest by five times; Google is the only one with a key, a quota and a bill attached.
An ordinary lookup therefore spends no quota at all.

A 404 means every one of them was asked and none holds the ISBN. The ranking and the
measurements behind it are in `backend/metadata.py`.

The response also carries `suggested_tag_ids`, matched by comparing the sources' subject
strings against the seeded tag names.

The response is not a book and nothing is persisted. The client posts it back to
`/api/books/scan` after the member has had a chance to edit it.

`PUT /{id}/refresh` re-runs the same lookup and overwrites the stored fields, with one
exception: a cover the member uploaded (a `/covers/` URL) is never replaced by a remote one.

### Deleting, and taking it back

`DELETE /api/books/{id}` no longer destroys anything. It stamps `deleted_at`
and the row stays, with its notes, loans, tags and every member's reading
status still attached, which is what makes `POST /{id}/restore` an undo rather
than a re-add. The status code is unchanged at 204.

**`visible_to()` is what hides it.** The trashed check lives in the same
predicate as the privacy check, so every listing, search, export, statistic,
duplicate group, series gap and loans row excluded it without being edited.
That is the whole reason that predicate exists in one place. The trash view
opts out by using `in_trash_for()` instead, which is a separate function rather
than a flag, because a predicate that means "on the shelf" or "in the trash"
depending on an argument is one a caller can get backwards, and getting it
backwards shows every deleted book in the library.

Two consequences worth knowing:

* **A trashed row still holds its ISBN**, which is unique. Deleting a book and
  re-scanning it would otherwise report "already exists" for a book nobody can
  see, and mis-scan, delete, re-scan is the most common delete in this app. So
  creating a book whose ISBN is held by a **trashed row the caller could see**
  purges that row first. Somebody else's trashed private book still 409s:
  purging it would destroy data they never offered up.
* **The trash does not empty itself.** This app has no scheduler, and a sweep
  at startup would delete on restart timing rather than on any schedule anybody
  chose. `DELETE /api/books/trash` is the manual version, and it is scoped by
  `in_trash_for`, so it never reaches a book the caller could not see in it.

Merge is the exception: its losing rows are destroyed rather than trashed,
because their notes, loans and statuses have already been repointed to the
survivor and restoring one would produce an empty husk.

### Tags

Two vocabularies in one table, told apart by `tags.is_predefined`.

The **curated** list (type, genre, age) is seeded at every boot by `seed_tags()`
and is the same in every deployment. It is what makes the tag picker useful on
the first day, before anybody has typed anything. Jelu and Openreads make every
tag free-form instead; what was wrong here was not having the curated list, it
was having no way past it.

The **custom** group is whatever a household invents. Creating one is open to
any member rather than to admins: public books are a shared shelf anyone may
curate, and a vocabulary only an admin can extend is one nobody uses. A name
that already exists returns that tag rather than a 409, because somebody typing
a name that is already there wants that tag.

A seeded tag **cannot be deleted**. `seed_tags()` would put it back at the next
restart, so the delete would appear to work and then quietly undo itself.

The flag is a stored column rather than "is this name in `PREDEFINED_TAGS`",
because that test would silently reclassify a tag the moment somebody renamed
one in the seed list, and renaming a seeded tag has already happened once here
(migration `95b6a61d6668`).

### Importing a library

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/imports/preview` | user | Reads the file and reports what it is. Writes nothing |
| POST | `/api/imports/csv` | user | Applies it. `create_missing`, `apply_tags`, `overrides` |

Goodreads, LibraryThing, StoryGraph, Libib, Openreads, or anything else with a
title column. The approach is taken from **BookWyrm's** `bookwyrm/importers/`,
which solves the same problem well: rather than a class per service with a fixed
column list, each field carries a list of candidate header names matched against
whatever the file actually has. Two of its properties are load bearing:

* **A matched header is removed from the pool.** Goodreads has both `ISBN` and
  `ISBN13`; without removal the first field to want an ISBN claims both.
* **First match wins, in written order.** Goodreads has `Exclusive Shelf` (the
  status) and `Bookshelves` (free-form tags), and claiming the latter as the
  status imports an entire library as unread.

What is ours rather than theirs: the delimiter and the encoding are sniffed
instead of declared per service, because a file arrives as an upload with no
label saying where it came from. LibraryThing exports tab separated in Latin-1
with every value in square brackets, and asking somebody to know that is asking
them to debug a CSV.

Headers and values are normalised the same way (lower case, underscores and
hyphens as spaces), so `publication_year` and `Year Published` need one entry
between them. **A guess spelled with an underscore can therefore never match**,
which is the trap in that table.

`preview` exists because a column guessed wrong is invisible until after the
import, and after the import the fix is finding and deleting a few hundred
books. `overrides` (`title=Book Name,author=Written By`) corrects a guess; a
pair naming a header the file does not have is ignored rather than raising,
since it describes a different file.

`apply_tags` is **off by default**. A Goodreads export's tag column is its
shelves, which for most people is a few hundred one-off names, and turning all
of them into tags buries the curated list under somebody's filing habits from
another app.

Statuses are personal, so an import only ever writes the importing member's own
`user_books` rows. Created books arrive `ownership=unknown`: an export says what
somebody read, which is silent on whether a copy was ever in the house.

### Backup and restore

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/backup` | **admin** | The whole database plus every cover, as a zip |
| POST | `/api/backup/restore?confirm=true` | **admin** | multipart. Replaces everything. **400** without `confirm` |

The CSV export is not a backup and never was: it carries one row per book and
drops the notes, the loans, every member's reading status, the accounts and
every cover file. The archive holds `endpaper.json` (every row of every table,
including the `book_tags` association, which has no model of its own and is
therefore the one that gets forgotten) plus a `covers/` directory.

JSON rather than a copy of the SQLite file. A file copy taken while the app is
running is consistent only through SQLite's backup API, and a file dropped in
underneath a running process is not consistent at all. A dump read through one
ORM session is consistent by construction, and it can be inspected and repaired
in a text editor, which is the state a backup is usually opened in.

**Admin only in both directions**, and for different reasons. The archive
carries every account's password hash and every member's private books, and it
is deliberately **not** filtered by `visible_to`: a backup that quietly omitted
other people's private books would restore to a library missing rows, which is
the one thing a backup must never do.

`confirm=true` is a query parameter rather than a body field so the destructive
call cannot be made by anything replaying a plain upload. The archive is
validated in full before the first row is deleted, because a restore that fails
halfway leaves a library that is neither the backup nor what was there before.
Cover entries are taken by filename only: a zip entry may name any path it
likes, including one outside the covers directory.

### Loans

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/loans?active_only=&overdue_only=` | user | Paginated; defaults to active only |
| POST | `/api/loans` | user | Exactly one borrower. Optional `due_at`. **422** for both or neither borrower, **409** if already out, **404** for an unknown or invisible book |
| PUT | `/api/loans/{id}/return` | user | **400** if already returned |

**The borrower is either a member or a name.** `loaned_to_user_id` names a member;
`loaned_to_name` is free text (120 characters) for somebody with no account here. Sending
both, neither, or a name that is only whitespace is a **422**. `LoanOut` carries both
fields, one of them null, and `loaned_to` is populated only for a member. The rule is a
CHECK constraint in the database as well as a schema validator, so a restore or an import
cannot write a loan nobody can be asked about.

`due_at` is optional and `is_overdue` is computed per request. `overdue_only` filters in
SQL rather than by discarding rows after serialising them, so `total` and the paging
describe the same set as `items`. A returned loan is never overdue, however late it was:
the field answers "chase this", not "was this late".

A book has at most one open loan. Recording a return is a shelf action, not an ownership
one, so any member may do it for any book they can see. The listing excludes loans of books
the caller cannot see, which would otherwise disclose a private book's title and holder.

### Notes

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books/{id}/notes` | read | Oldest first |
| POST | `/api/books/{id}/notes` | read | 201; content must be non-empty |
| PUT | `/api/books/{id}/notes/{note_id}` | author or admin | **403** otherwise |
| DELETE | `/api/books/{id}/notes/{note_id}` | author or admin | 204 |

A `note_id` belonging to a different book returns 404. The ids must agree, so a note cannot
be reached through a book the caller happens to have access to.

### Settings, stats, users

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/settings/login-image` | **public** | **404** when none is set |
| POST | `/api/settings/login-image` | **admin** | **403** for a non-admin |
| GET | `/api/settings/features` | **public** | Feature flags and the default language |
| GET | `/api/settings` | **admin** | The full record, API key masked |
| PUT | `/api/settings` | **admin** | Partial update; absent fields are left alone |
| GET | `/api/stats` | user | Totals, per-member, per-tag, per-month |
| GET | `/api/users` | user | The member list |
| GET | `/api/users/test-accounts` | **admin** | The accounts an admin may switch into |
| POST | `/api/users/test-accounts` | **admin** | 201. **400** if the name is taken, **422** under the 8 character floor |
| GET | `/api/users/me/appearance` | user | The caller's own palette, mode and wallpaper |
| PUT | `/api/users/me/appearance` | user | Replaces all three |

`/api/settings/features` is public for the same reason the login image is: the login page
is localised, so the default language has to be known before a token exists. It carries no
secrets and nothing about the catalogue.

`GET /api/settings` never returns the Google Books API key, only a masked preview plus
`has_google_books_api_key`. A masked string is not a truth value, so the UI keys off the
boolean. On `PUT`, every field is optional and **absent means "leave alone"**: a form that
always submitted every field would blank the key whenever an admin toggled something else,
since the browser never received the real value to send back. An **empty string clears the
key**, deliberately and distinctly from omitting it.

The login image GET is public because the login page renders before anyone is signed in.
`/api/users` is readable by every member because the book detail page needs it for the
"Loan to…" picker; it exposes usernames and the admin flag, never password hashes.

Appearance is **not** a field on `UserOut`, which is served inside every book payload and
the member list: a field there would show every member what every other member's library
looks like. It has its own pair of endpoints instead, and they take no member id, so the
only appearance reachable is the caller's own. All three fields are nullable, null meaning
"has not chosen"; the `PUT` replaces the whole record, so an omitted field is a cleared one.
Which palettes and wallpapers exist is the frontend's business and the server does not hold
the list, but it does bound the shape: `^[a-z0-9-]{1,30}$`, and `mode` is one of three. A
client that does not have a stored palette shows its default instead, and overwrites the
stored value with that default the next time the member changes anything, because the write
is a whole record.

`/api/users/test-accounts` is a local account with a password an admin sets, for seeing the
library the way an ordinary member sees it. It works in **every** auth mode, which is the
point: `POST /auth/register` is 403 under `ldap` and `proxy`. The body is `UserCreate`, so
registration's password policy applies unchanged, and the account is never an admin.

The GET returns only test accounts, so the client cannot offer a directory member as a
switch target. That is presentation: `POST /auth/switch` refuses one regardless. Test
accounts do appear in `/api/users` like any other account, because the loan picker is a
list of everybody who could hold a book.

Every `/api/stats` aggregation applies the privacy predicate independently.

## System

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/healthz` | public | `{"status": "ok"}`. Runs a query, so it fails when the database does |

The Kubernetes probes point here rather than at `/`, which the SPA mount answers from disk:
a pod whose data volume never mounted stayed Ready and kept taking traffic. Unauthenticated
because a probe holds no token, and the only thing disclosed is that the service is up.

## Errors

`{"detail": ...}`, where `detail` is a **string** for a raised `HTTPException` and an
**array of per-field objects** for a 422. A non-JSON body is possible too, from a reverse
proxy's own error page. The frontend's mutator flattens all three.

A browser navigating to a non-API path gets a styled HTML page instead; anything under
`/api` or `/auth` always answers JSON, because whatever is calling it is code. An unknown
`/api/*` path is a JSON 404. Without that it would fall through to the SPA mount and return
`index.html` with a 200, so a typo in a `fetch()` call would look like success.

| Code | Means |
|---|---|
| 400 | Understood but not allowed in this state (no ISBN to refresh, already returned) |
| 401 | No usable token, or from `/auth/login` wrong credentials |
| 403 | Authenticated but not permitted (non-admin, non-owner) |
| 404 | Absent, **or** invisible to this account |
| 409 | Conflicts with existing data (duplicate ISBN, book already on loan) |
| 413 | Upload over the size cap |
| 422 | Request body or query failed validation |
| 429 | Rate-limited; carries `Retry-After` |
| 500 | A bug. Generic message only; the traceback is logged, never returned |

## Uploads

`multipart/form-data` with a single `file` field. The format is decided by the file's
**leading bytes**, not its name. JPEG, PNG and WebP are accepted, SVG is refused, and the
cap is 5 MB. A JPEG uploaded as `cover.png` is stored as `.jpg`. See
[security.md](security.md).
