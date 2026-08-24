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
| GET | `/api/books` | user | Paginated. Filter with `q`, `status`, `ownership`, `format`, `lending`, `discuss`, `series`, `author`, `location`, `collection_id`, `unfiled`, `unrated`, `tags`, `sort` |
| POST | `/api/books` | user | **409** on an ISBN already in the catalogue |
| POST | `/api/books/scan` | user | Same, named for the scan flow |
| GET | `/api/books/tags` | user | The seeded vocabulary plus the household's own |
| POST | `/api/books/tags` | user | Invent a tag. Returns the existing one on a name clash |
| DELETE | `/api/books/tags/{id}` | user | Only a custom tag. **400** for a seeded one |
| GET | `/api/books/lookup?isbn=` | user | Metadata lookup, **404** if unknown |
| GET | `/api/books/export?format=csv\|txt` | user | File download, not paginated |
| GET | `/api/books/search?q=` | user | Free-text search for the add flow. Needs no API key |
| GET | `/api/books/series` | user | Every series, with the gaps in it |
| GET | `/api/books/authors` | user | Everybody credited on the shelf, with counts, spellings and merges |
| GET | `/api/books/authors/suggestions` | user | Names that look like one person |
| POST | `/api/books/authors/merge` | user | `{keys, keep_name}`. Says two spellings are one person. **404** for an author the caller cannot see |
| DELETE | `/api/books/authors/aliases/{id}` | user | 204. Undoes one merge. **404** for one the caller cannot see |
| GET | `/api/books/locations` | user | Distinct shelf locations, most-populated first |
| GET | `/api/books/duplicates` | user | Books that look like the same work |
| GET | `/api/books/trash` | user | What the caller has deleted and could put back |
| DELETE | `/api/books/trash` | user | Empties it for good. Returns `{purged}` |
| POST | `/api/books/merge` | user | Fold several entries into one |
| POST | `/api/books/bulk` | user | One verb applied to a selection of books |
| POST | `/api/books/covers/backfill?after_id=` | user | Fetch and store the covers of books that have none. Bounded per run: send the reply's `next_after_id` back to carry on, and it returns 0 at the end. `after_id` is 0 to 2^63-1; outside that is a **422** |
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
| PATCH | `/api/books/{id}/collection` | write | File this copy into a collection, or `null` for none. **400** for an unknown collection |
| PATCH | `/api/books/{id}/discuss` | read | Offer to talk about this book, or withdraw the offer |
| POST | `/api/books/{id}/enrich` | write | Fill gaps from Google Books |
| GET | `/api/books/{id}/enrich/candidates` | read | Other editions, for picking the right one |
| GET | `/api/books/{id}/copies` | read | Every copy of this title the caller may see, this one included |
| POST | `/api/books/{id}/copies` | write | Record another copy of it. **201** |

"read" and "write" are the access rules in [security.md](security.md): read means the book
is public or yours; write additionally means public books are a shared shelf any member may
curate.

`/authors` and `/authors/suggestions` are declared before `/{book_id}` too, or the first
would be a request for the book with id "authors".

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

`lending` accepts `happy`, `in_use` or `never`, and matches nothing on a book nobody has
answered for: null is not one of the three.

`collection_id` and `unfiled` are **two parameters for two questions**, and sending both is
a **422** rather than one silently winning. "Books in collection 3" and "books in no
collection" are alternatives, and a caller that asked for both has made a mistake worth
being told about: choosing one for them is how a filter quietly shows the wrong shelf. An
id no collection has selects nothing, rather than answering 404: this is a filter, not a
lookup.

`discuss=true` lists books **somebody** has offered to talk about, not the caller's own
offers. That is deliberate and matches what the grid draws: the marker is on every book
with an offer on it, whoever made it, so a filter scoped to the caller would hide half of
what it claims to select. It is a correlated exists and names the table to correlate
against for the same reason `unrated` does.

### Editing, rating and reading dates

`PATCH /{id}` is a partial update: an absent field is left alone and an explicit null
clears. That distinction is the whole point, and it is why the handler uses
`exclude_unset` rather than dumping the model.

`PATCH /{id}/rating` needs only **read** access, like status, because a rating is one
person's opinion and changes nothing for anyone else. It deliberately does not touch the
reading dates: rating a book is not a claim to have finished it just now.

The reading dates are never sent by a client. They are stamped from status transitions;
see [data-model.md](data-model.md) for the rules.

### Willing to lend, and willing to talk

Two fields that look alike and are not.

`books.lending` is the household's standing answer to "would you lend this copy": `happy`,
`in_use` (wanted by its owner at the moment, so ask again later) or `never`. Null means
nobody has been asked. It is set through `PATCH /{id}` with everything else about the copy,
and it is **not** a fact about whether the book is out right now: that is `active_loan`.

`user_books.wants_to_discuss` is one member's "ask me about this book", set through
`PATCH /{id}/discuss` with **read** access, like status and rating. It creates the
`user_books` row when there is none, since a row appears only once somebody sets something.

The two per-member fields it produces on `BookOut` differ in scope, and that is the feature
rather than an oversight:

| Field | Whose | Why |
|---|---|---|
| `my_wants_to_discuss` | the caller's | Drives the caller's own checkbox |
| `discuss_with` | **everybody's** | A flag meaning "ask me" is worth nothing if only the person who set it can see it |

`discuss_with` discloses the usernames of members who opted in and nothing else. In
particular it says nothing about their reading status, which stays in `my_status` and stays
the caller's own.

### Reading progress

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books/{id}/progress` | read | The caller's own entries, newest first |
| POST | `/api/books/{id}/progress` | read | 201. Exactly one of `page` and `percent`; optional `minutes` |
| DELETE | `/api/books/{id}/progress/{progress_id}` | read, own rows | 204 |

Read access is enough, like status and rating: a position is personal and changes nothing
for anyone else. Every query filters on `user_id` **as well** as on the book, so a member
never sees another member's progress even on a public book that both are reading.

**Exactly one unit.** `{"page": 64}` or `{"percent": 40}`, never both and never neither;
both and neither are a **422**. A percent exists for an audiobook and for a book whose
`page_count` no provider supplied. `page` must be at least 1, `percent` is 0 to 100, and
`minutes` is 1 to 1440. The same rule is a CHECK constraint in the database, because a
restore does not go through this schema.

Recording progress on an unstarted book **promotes it to `reading`** and stamps
`started_at`. It never sets `read`, whatever the page number: `page_count` comes from a
metadata provider and is off by one often enough that the last page is not a finish
signal, and there is already an explicit control for finishing. A status change never
deletes progress rows, unlike the reading dates, which are derived and are cleared.

Another member's entry, and an entry belonging to a different book, are both **404**, not
403: a 403 would confirm the id exists. Deleting the last entry does not put the book back
to unread.

`BookOut` carries `my_progress_page`, `my_progress_percent` and
`my_progress_recorded_at`, all of them the caller's own. The percentage is **derived**,
never stored twice: `page / page_count` when the page count is known, else the recorded
`percent`, else null, clamped at 100. `ProgressOut` deliberately does not repeat it.

### Authors

There is no author table. `books.author` is a comma separated credit line, an author is a
name inside it, and `GET /authors` groups the column. Each entry carries a `key`
(casefolded, unaccented, punctuation turned to spaces), the `name` to show, a
`book_count`, every `spelling` on the shelf most used first, and `merged`, the spellings
folded in by a member with the alias row id behind each one.

**Link either; the key is not more durable than the name.** `GET /api/books?author=` takes
a key, a display name, or a spelling a merge has folded away, and resolves all three through
the household's alias rows, which is what keeps an old link working after a tidy-up,
**including a spelling no book carries any more**: the middle of a chain of merges is on
nothing, and resolving through the shelf instead of through the mapping answered it with an
empty library. A merge moves the key
too (folding "Le Guin" into "Ursula K. Le Guin" retires `le guin` as an entry key), so
nothing here is an identity in the sense a row id would be. The pages link the **name**,
because that is what the library's filter chip then shows back. An unknown name is an empty
shelf rather than a 404: this is a filter on a listing, and a stale bookmark should not be
an error page.

`GET /authors/suggestions` offers groups of names that look like one person, each with the
rules that produced it: `spelling` (the same name with the spaces moved), `initials` (an
abbreviated given name against a full one, which requires an abbreviation on one side or
every pair of people sharing a surname would be offered), and `fragment` (one name's words
sitting inside another's, which is what a credit line stored in catalogue order splits
into). It is a suggestion and never a verdict.

`POST /authors/merge` is reached two ways from the page, because a suggestion is not the
only case: accepting a suggested group, or selecting names by hand, which is the only path
to a **misspelling** (no rule joins `Tolkein` to `Tolkien`) and to a **rename** (one name
selected, a new one typed).

It takes `{keys, keep_name}` and writes **nothing to `books`**: it
records one row per spelling saying who that spelling means. `keep_name` is free text and
need not be a name any book carries, because "Le Guin, Ursula K." splits into two people
neither of whom is spelled correctly. A `keep_name` that is itself already folded into
somebody resolves to them, so one lookup is always enough. `DELETE
/authors/aliases/{id}` undoes exactly one merge, and since nothing was rewritten the shelf
returns to precisely what it was.

`BookOut` carries `authors`, the credit line split into the names in it, derived on every
serialisation and never stored. It costs no statement, and it exists so a client can link
each name without reimplementing the separator rule.

### Series, shelves and duplicates

`GET /series` returns each series with `missing_indexes`, which is the question a series
view exists to answer. Only gaps **below the highest number held** are reported: a series
with no known length has no meaningful missing past the end, and reporting one would invent
a book nobody said exists.

`GET /duplicates` matches on normalised title plus first author, **not** on ISBN. An
accidental exact repeat is already refused by the partial unique index, so the case left to
catch is the one it cannot see: a hardback and a paperback are the same book and two
legitimately different ISBNs. Matching is deliberately lossy, because this is a suggestion a
person confirms.

**Deliberate copies never appear here.** Each `copy_group` is collapsed to one row before
the matching runs, so two paperbacks of one title are not offered for merge. They would
otherwise be the strongest match this endpoint can produce, and merging them destroys a
book the household owns.

`POST /merge` takes `{book_ids, keep_id}` and `keep_id` must appear in `book_ids`, spelled
out rather than inferred so a mistyped request fails instead of silently keeping whichever
row sorted first. The survivor absorbs only what it is missing, and tags, notes, quotes,
classifications, loans and statuses are repointed rather than dropped. A classification
both rows carry is dropped rather than moved (the pair is unique per book, scheme and
number), though the survivor takes its caption first if it had none. The survivor is
capped at 8 like every other book, and a merge that would carry it past that drops the
overflow, which is where those rows were going anyway before classifications were
repointed at all. Where the same member holds a status
on two of the merged rows, the survivor's own row wins: deleting somebody's reading history to
satisfy a unique index is not an acceptable resolution.

Merging two rows that were copies of each other is a member saying they were never two
objects, and it works: the survivor is left an ordinary book with no `copy_group`.

### Multiple copies of one title

A household that owns two paperbacks of one title owns two objects, and every per-object
fact in the catalogue (location, condition, what was paid, who has it) is already recorded
per book. So a copy is a **second book row**, joined to the first by a shared `copy_group`.

`POST /api/books/{id}/copies` is the only way to make one. It takes the per-copy fields and
nothing else:

```json
{ "location": "Loft", "condition": "good", "format": "paperback" }
```

Everything about the work (title, author, ISBN, cover, series, description) and the tags are
taken from the book being copied. Nothing personal is: status, rating, progress, notes,
quotes and loans belong to a person and an object, and the copy is an object nobody has
read yet.
`is_private` is **inherited and cannot be set here**, because a public copy of a private
book discloses the book. The caller owns the copy, so `PATCH /{id}/privacy` can change it
afterwards.

Three consequences worth knowing before relying on any of them.

**Scanning a book already on the shelf still answers 409**, whether or not copies exist. The
overwhelmingly common reason for that scan is a second pass through the same bookcase, so a
copy is something a person asks for by pressing a button that says so, never something the
app infers. The 409 body carries `book_id` when the holder is visible, which is what lets a
client offer both actions: open the one we have, or add another copy.

**Each copy lends separately.** One open loan per book row, and a copy is a book row, so
"one is out and one is on the shelf" is expressible without any change to the loan rules.

**The library lists every copy**, and `copy_count` on every book payload says how many the
caller can see. Counting only visible copies matters: a member who makes their own copy
private does not thereby announce it on everybody else's card. Statistics count **items,
not titles**, so a household with a spare paperback has a total one higher than its number
of distinct works.

**A CSV round trip collapses them.** `/export` writes one row per copy, which is correct,
but re-importing that file creates one book: the importer matches by ISBN and, where the
ISBN belongs to a book it cannot see, refuses rather than inserting. Both halves are
deliberate. A copy is something a person says they own, one press at a time, and an export
listing a book three times is an artefact of the export rather than evidence of three
paperbacks. Restore the whole library from `/api/backup` instead, which carries `copy_group`
with the rows and reproduces the groups exactly.

### Collections

A collection is a named part of the shelf: physical and ebook, kept and sold, one person's
and another's. A book is in **one** or in none.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/collections` | user | Every collection, with the caller's own `book_count` |
| POST | `/api/collections` | user | **201**. A name that already exists returns that collection |
| PATCH | `/api/collections/{id}` | user | Rename. **409** if another collection has that name |
| DELETE | `/api/collections/{id}` | **admin** | 204. Its books are unfiled, never deleted |

Names are unique **case insensitively**, enforced by an index on `lower(name)`. Creating one
with a name already in use returns the existing row rather than an error, because somebody
typing a name that is there means that collection; renaming **onto** an occupied name is a
409, because that would silently merge two shelves.

Deleting is admin only, the same asymmetry as `DELETE /api/books/tags/{id}` and for the same
reason: creating is additive and undone by deleting, while deleting strips a label off every
book in the house at once with no undo.

**A collection is shelving, never permission.** Filing a book into one changes nothing about
who can see it: `is_private` remains the only access control on content. Every count here is
filtered by the caller's visibility, because the count is the one thing a household-wide
label could otherwise disclose.

`BookOut` carries `collection_id` and `collection_name`. The name is a projection of the row
the id names, assembled per request in one statement for the whole page, so a rename is
visible on the next fetch and nothing has to be migrated.

Two interactions worth knowing.

**Per copy.** Two copies of one title are two objects, and each carries its own collection.
`POST /api/books/{id}/copies` does not inherit it: a new copy is unfiled unless the payload
names one. `copy_count` still counts the whole group across collections, so a library
filtered to one collection can show a book whose card reads 2: it answers "how many do we
own", not "how many are on this screen".

**Not a duplicate rule.** `/duplicates` ignores collections, and the unique ISBN index is
table-wide rather than per collection. A **merge** fills the survivor's empty collection
from a loser's, like `location`, and never overrides one it already has. Adding "the same book" to a second collection is
therefore a **copy**, made with the copies endpoint, not a second ungrouped row.

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
| `set_collection` | a collection id; null or an empty string unfiles them |
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
Neither ever takes the ISBN: a chosen printing's ISBN is not this copy's, and the column is
unique among uncopied rows so writing one could collide with a book already here.

The candidates endpoint deliberately carries no `suggested_tag_ids`: that book already has
tags, and they are somebody's deliberate choice.

**Classifications are the exception, and are added rather than merged.** `overwrite` does
not reach them: a heading is a catalogue's citation, not a value somebody typed, so there is
nothing here to overrule. Enrichment adds the ones the book does not already carry, fills in
a caption where it had none, and never replaces a caption already stored. Both endpoints
report `classifications` in `updated_fields` when a row was added.

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

The response carries `classifications`, each a scheme, a number and the caption the
catalogue gave it (`ddc`, `004`, `Informatik`), and `suggested_tag_ids`.

**The suggestion has two routes and they fail on opposite records.** One compares the
sources' subject strings against the seeded tag names, which works on an English record and
scores zero on a German one. The other reads the **DDC number**, which is the same in both
languages: `004` is Informatik in a German record and Computing in an English one, and both
resolve to Computing. Measured against the DNB over ten German ISBNs, eight carried a DDC
heading and none of the eight captions matched a seeded tag name.

**The server applies nothing**: the ids are returned and no endpoint writes a tag from
them. The web client pre-selects them on the confirm form, so on an ordinary scan they do
land unless the member unchecks them. Which of those two is "a suggestion" is a settled
question, in `docs/decisions.md`.

The response is not a book and nothing is persisted. The client posts it back to
`/api/books/scan` after the member has had a chance to edit it, `classifications` included,
and a row is written for each.

**A book carries at most 8 classifications, and that is a bound on the book rather than on
a payload.** `max_length` caps one request; both writers of the table (the add and enrich
paths, and the merge) count the rows already there and stop, because they are additive
across requests and neither `POST /{id}/enrich/apply` nor `POST /merge` carries a rate
limiter. At the ceiling an incoming heading is dropped rather than a stored one evicted,
and a caption still fills in on a heading already held. The reason the number matters:
`BookOut.classifications` is on every listing row, so an inflated book is paid for on every
page that contains it.

`PUT /{id}/refresh` re-runs the same lookup and overwrites the stored fields, with one
exception: a cover the member uploaded (a `/covers/` URL) is never replaced by a remote one.

### Deleting, and taking it back

`DELETE /api/books/{id}` no longer destroys anything. It stamps `deleted_at`
and the row stays, with its notes, quotes, classifications, loans, tags and every
member's reading status still attached, which is what makes `POST /{id}/restore` an undo rather
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

* **A trashed row still holds its ISBN**, and still holds its claim on it. Deleting a book and
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
because their notes, quotes, loans and statuses have already been repointed
to the survivor and restoring one would produce an empty husk.

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
drops the notes, the quotes, the classifications, the loans, every member's reading status,
the accounts and every cover file. The archive holds `endpaper.json` (every row of every table,
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
| POST | `/api/loans` | user | Exactly one borrower. Optional `due_at`. **422** for both or neither borrower, **409** if already out **or** marked never lent, **404** for an unknown or invisible book |
| PUT | `/api/loans/{id}/return` | user | **400** if already returned |
| POST | `/api/loans/overdue/notify` | **admin** | Runs the overdue digest now and reports what it sent |

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

**A book marked `lending = never` is refused once, not forbidden.** The first request gets
a **409** whose detail is an object, `{"message": ..., "code": "not_lendable"}`; the same
request carrying `acknowledge_not_lendable: true` creates the loan. The code is there
because the client has to branch on it: this 409 puts a confirmation in front of the lend
button, and the already-out 409 does not, so matching on the prose would break the moment
it was reworded. The flag is **not stored**, and the book still says it is never lent
afterwards: it answers one request rather than changing the household's mind. `in_use` and
`happy` are not checked at all. The reasoning is in [decisions.md](decisions.md).

**Overdue reminders** go out as one JSON digest POSTed to an admin-configured webhook,
hourly from a task started with the app. `POST /api/loans/overdue/notify` runs the same
pass immediately, which is what makes the feature testable by a person and what an
external cron would call instead. It answers
`{sent, loans, skipped_private, reason, detail}` rather than a bare 204, because "nothing
is overdue" and "the receiver refused it" both look like silence otherwise.

`reason` is `disabled`, `no_url`, `nothing_due` or `unreachable`, and is **null exactly
when `sent` is true**. It is a closed set because a client has to render the difference and
cannot branch on prose; `detail` is the same outcome as a sentence, for a log or a caller
with no message catalogue. A 200 with `sent: false` is the ordinary answer for all four:
none of them is an error in the request.

```json
{
  "event": "overdue_loans",
  "generated_at": "2026-08-22T09:00:00",
  "count": 1,
  "loans": [
    { "loan_id": 7, "book_id": 12, "title": "Dune", "borrower": "kim",
      "due_at": "2026-08-01T00:00:00", "days_overdue": 21 }
  ]
}
```

Three properties of the request are load bearing. **Private books are excluded**, in the
query rather than afterwards: a webhook has no member identity and lands in a channel the
whole household reads. `skipped_private` counts what was held back, never names it. The
body is signed with HMAC-SHA256 in `X-Endpaper-Signature: sha256=<hex>` when a secret is
set, over the raw bytes, so a receiver verifying a re-serialised payload will fail. And
**redirects are not followed**, unlike the metadata lookups: this is the one request in
the app whose payload is catalogue content going somewhere unauthenticated.

A loan is chased again only once `overdue_reminder_days` have passed since its last
reminder. `notified_at` is stamped after a delivery that succeeded, so a failure retries
on the next run.

### Notes

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books/{id}/notes` | read | Oldest first |
| POST | `/api/books/{id}/notes` | read | 201; content must be non-empty |
| PUT | `/api/books/{id}/notes/{note_id}` | author or admin | **403** otherwise |
| DELETE | `/api/books/{id}/notes/{note_id}` | author or admin | 204 |

A `note_id` belonging to a different book returns 404. The ids must agree, so a note cannot
be reached through a book the caller happens to have access to.

### Quotes

A passage copied out of a book, the page it is on, and optionally a remark about it. Same
access rules as notes: a quote is visible to whoever can see the book, and only its author
or an admin may change it.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books/quotes` | signed in | Every visible quote, newest first, paginated |
| GET | `/api/books/{id}/quotes` | read | In reading order: by page, unpaged last |
| POST | `/api/books/{id}/quotes` | read | 201; `text` must be non-empty |
| PUT | `/api/books/{id}/quotes/{quote_id}` | author or admin | **403** otherwise |
| DELETE | `/api/books/{id}/quotes/{quote_id}` | author or admin | 204 |

`GET /api/books/quotes` is declared **before** `/{book_id}`, like `/export` and `/trash`,
or it would be a request for the book with id "quotes". It is a book query: it returns a
title, an author and a cover per row, so `visible_to()` filters both the rows and the
count.

Bounds, all of them 422 rather than 500: `text` is 1 to 2,000 characters, `note` is at
most 1,000, and `page` is 1 to 100,000. All three are stated again as CHECK constraints
(`ck_quotes_text_bounds`, `ck_quotes_page_bounds`), because a restore inserts through Core
and never sees the schema, and because SQLite does not enforce a `VARCHAR` width.

The excerpt's ceiling is lower than a note's 10,000 on purpose: a quote is a verbatim
excerpt of somebody else's copyrighted text, and 2,000 characters is about one printed
page.

A `quote_id` belonging to a different book returns 404, for the same reason a `note_id`
does.

### Settings, stats, users

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/settings/login-image` | **public** | **404** when none is set |
| POST | `/api/settings/login-image` | **admin** | **403** for a non-admin |
| GET | `/api/settings/features` | **public** | Feature flags and the default language |
| GET | `/api/settings` | **admin** | The full record, API key masked |
| PUT | `/api/settings` | **admin** | Partial update; absent fields are left alone |
| GET | `/api/stats` | user | Totals, per-member, per-tag, per-month, pages read |
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

`PUT /api/settings` also carries the four overdue-reminder fields.
`overdue_webhook_url` is returned **in full**, unlike the Google Books key: a destination
nobody can read back is a destination nobody can proofread, and an admin who can read it
is an admin who can change it. A URL whose scheme is not `http` or `https` is a **422**,
checked again in `notifications.py` before any send because a restore writes the settings
table through Core. `overdue_webhook_secret` follows the API key exactly: masked on the way
out, absent means "leave alone", an empty string clears.
`overdue_reminder_days` is 1 to 365; zero would mean resending the same list on every tick.

`StatsOut.pages_by_month` is the pages the requesting member read, by month, computed from
the positive deltas between their consecutive page-unit entries per book. **Page-tracked
books only**, which the heading on the stats page says as well: an audiobook records a percentage, and converting that into a page count
would produce a number that adds up with the others while meaning something else. The
first entry on a book counts in full; a backwards step counts nothing, which covers both a
re-read and a corrected typo and refuses to let the second inflate the figure.

Every `/api/stats` aggregation applies the privacy predicate independently.

## System

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/healthz` | public | `{"status": "ok"}`, or **503** when the database or the data volume does not answer |

The Kubernetes probes point here rather than at `/`, which the SPA mount answers from disk:
a pod whose data volume never mounted stayed Ready and kept taking traffic. Unauthenticated
because a probe holds no token, and the only thing disclosed is that the service is up.

It runs two checks, and the second is there because the first is not enough. `SELECT 1` on an
already-open SQLite handle is served from the page cache and issues no RPC, so during a total
NFS outage on 2026-08-22 this endpoint answered 200 continuously and the pod stayed 1/1 Ready
for 39 hours. A `stat` of the data directory is a namespace operation and has to cross the
wire.

### What a deployer has to set

The stat carries its own timeout, `main.STORAGE_TIMEOUT_SECONDS`, currently **2 seconds**. A
hung mount can only ever surface as a timeout, so if the handler is the slower of the two the
kubelet gives up while it is still waiting and the pod reports a hang rather than a failure,
which is the outcome the internal timeout exists to prevent.

**Set `timeoutSeconds: 5` on both probes.** Kubernetes defaults it to **1**, which is shorter
than the internal timeout and therefore wrong: leaving it unset defeats this check. The
numbers, rather than the direction of the inequality, because the person who has to act on
this is reading these docs and not the source:

| Setting | Value | Why |
|---|---|---|
| `main.STORAGE_TIMEOUT_SECONDS` | 2 | The handler gives up here and answers 503 |
| probe `timeoutSeconds` | 5 | Comfortably longer, so the failure is a 503 and not a hang |
| probe `periodSeconds` | 10 or more | Longer than the handler's worst case, so probes cannot queue |

**This is the liveness probe too, and that is intended.** Once the check works, a hung mount
restarts the pod, and the restarted pod runs `init_db()` against the same mount and blocks
there, so it will not come Ready and will keep restarting. That is the correct outcome and
not an accident: a pod whose storage is gone cannot serve, and a container in
`CrashLoopBackOff` is visible to every alert a household has, where a pod that is 1/1 Ready
and serving nothing is visible to none of them. It also recovers on its own the moment the
mount does. What would be wrong is answering 200 while the data is unreachable, which is what
happened for 39 hours.

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
