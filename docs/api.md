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
| GET | `/api/books/tags` | user | The seeded vocabulary plus this library's own |
| POST | `/api/books/tags` | user | Invent a tag. Returns the existing one on a name clash |
| DELETE | `/api/books/tags/{id}` | user | Only a custom tag. **400** for a seeded one |
| GET | `/api/books/lookup?isbn=` | user | Metadata lookup, **404** if unknown |
| GET | `/api/books/export?format=csv\|txt\|marcxml` | user | File download, not paginated. `marcxml` needs library mode, **403** without |
| GET | `/api/books/search?q=&harder=` | user | Free-text search for the add flow. Needs no API key. `harder` also asks the slow catalogues |
| GET | `/api/books/series` | user | Every series, with the gaps in it |
| GET | `/api/books/authors` | user | Everybody credited on the shelf, with counts, spellings and merges |
| GET | `/api/books/authors/suggestions` | user | Names that look like one person |
| POST | `/api/books/authors/merge` | user | `{keys, keep_name}`. Says two spellings are one person. **404** for an author the caller cannot see |
| DELETE | `/api/books/authors/aliases/{id}` | user | 204. Undoes one merge. **404** for one the caller cannot see |
| GET | `/api/books/authors/authority` | user | What the authority files hold under a name. `author` is a key or any spelling; `q` retypes the search and forces the name route. Writes nothing. **503** if the file is unreachable, because nothing here is blocked by that |
| GET | `/api/books/authors/wikipedia` | user | `lang` is `en` or `de`, the language the reader chose in the app rather than the browser's. One row per author carrying a confirmed `wikidata` identifier and none for anybody else, so the button a client draws from this is a property of the shelf rather than of the network. `language` names the Wikipedia edition `url` points at, or is **null** where the URL is the Wikidata item's own page, which is what an author with no article anywhere and an unreachable Wikidata both fall to. Never **503**: nothing here is a supplier, so an outage costs the language and not the link. Reads which language editions exist and no article text: `docs/featurelist.md` refuses author biographies and this does not touch that |
| POST | `/api/books/authors/identifiers` | user | `{author, scheme, identifier}`. Says a candidate record is this author's. Confirming a `gnd` also stores the ISNI, LCNAF number, VIAF cluster and Wikidata item that record carries, **and the six national library numbers (`blbnb`, `arbabn`, `bne`, `ptbnp`, `iccu`, `bnchl`) from the VIAF cluster it names**, all re-read by the server and never from the body. A cluster that does not name the confirmed GND record back is discarded rather than stored. Where VIAF produces no cluster at all, the six are read from the Wikidata item instead: one source answers per confirmation, never both, so the two can never disagree. **409** for retyping one already held |
| DELETE | `/api/books/authors/identifiers/{id}` | user | 204. The only correction there is: an identifier is removed and re-imported, never edited |
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

`books.lending` is the library's standing answer to "would you lend this copy": `happy`,
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
the library's alias rows, which is what keeps an old link working after a tidy-up,
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
book the library holds.

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

A library that holds two paperbacks of one title owns two objects, and every per-object
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
not titles**, so a library with a spare paperback has a total one higher than its number
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

Names are unique **case insensitively** and outside ASCII too, enforced by a unique index on
a stored fold of the name rather than on `lower(name)`, which SQLite evaluates and which
folds only the 26 ASCII letters. Creating one
with a name already in use returns the existing row rather than an error, because somebody
typing a name that is there means that collection; renaming **onto** an occupied name is a
409, because that would silently merge two shelves.

Deleting is admin only, the same asymmetry as `DELETE /api/books/tags/{id}` and for the same
reason: creating is additive and undone by deleting, while deleting strips a label off every
book in the house at once with no undo.

**A collection is shelving, never permission.** Filing a book into one changes nothing about
who can see it: `is_private` remains the only access control on content. Every count here is
filtered by the caller's visibility, because the count is the one thing a library wide
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

**The candidates come from two places, and the rule between them is worth knowing.** Open
Library merges printings under a *work*, and `GET /{id}/enrich/candidates` asks that
cluster with the book's own ISBN: every row in it is a printing of the same book by Open
Library's own merge rather than by a title match. Underneath it sits the free text search
across every catalogue the library has switched on, which is the only answer for a book
with no ISBN, for a work Open Library has not merged, and for a good deal of German
publishing, where Open Library returns 404. A new install has all nine on; see the
provider list below.

**Open Library switched off answers no cluster at all**, because nothing else here holds
one. The search half still answers, so the endpoint degrades rather than failing.

Three rules hold that together:

* **The cluster leads, and never fills the page.** It is capped one row short, so a work
  merged wrongly is never the whole answer.
* **A printing declaring another language is dropped, and one declaring the wanted
  language is ranked first.** A work spans translations, and an English printing cannot
  fill in a German copy's publisher or page count. An entry declaring **no** language is
  kept, because 22% to 33% of live entries declare none and the wanted printing is often
  among them. Where no entry declares the wanted language, nothing in the payload can pick
  it out and the search half is what answers: that residual is why the cluster is capped
  one row short.
* **Rows are deduplicated on the ISBN alone.** Every row here shares a title and an
  author by construction, so anything looser collapses the page to one row.

`POST /enrich` keeps the automatic behaviour for a caller that wants it. Both share the
merge rule, and it is the server's rather than the client's: only empty fields are filled
unless `overwrite=true`, so a publisher somebody typed by hand is never quietly replaced.
Neither ever takes the ISBN: a chosen printing's ISBN is not this copy's, and the column is
unique among uncopied rows so writing one could collide with a book already here.

Candidates are read only evidence. A Member selects one through `POST /enrich/apply` before
its Classifications can add a row or complete a caption. Automatic enrichment and Refresh
Metadata change scalar fields only. They neither write Classifications nor report them in
`updated_fields`.

The candidates endpoint deliberately carries no `suggested_tag_ids`: that book already has
tags, and they are somebody's deliberate choice.

**A catalogue record the response schema refuses costs one row, on this endpoint and on
`/api/books/search` alike.** Both answer with the same model built straight from a
catalogue, and both go through one builder for that reason: a record carrying more headings
than a book may hold loses the ninth rather than the whole result, and a caption longer than
the column loses that heading. The headings are ordered by scheme before the cut, so a Dewey
number outranks a subject heading whichever catalogue supplied it. One record can now exceed
the ceiling by itself: a Library of Congress record carries up to 14 LCSH headings beside
its two classifications, and the parser emits the classifications first for that reason.

**Classifications are the exception, and are added rather than merged.** `overwrite` does
not reach them: a heading is a catalogue's citation, not a value somebody typed, so there is
nothing here to overrule. A Member selected candidate adds the headings the book does not
already carry, fills in a caption where it had none, and never replaces a caption already
stored. `POST /enrich/apply` reports `classifications` in `updated_fields` when one changes.

**Neither needs an API key.** Enrichment runs the merged ISBN chain when the book has an
ISBN and the ranked search when it does not, so a 978-3 book Google does not carry is
filled in from the DNB instead of reporting that no key is configured. Google joins in as
one more source when a key is set.

### Free-text search

`GET /api/books/search?q=&limit=&lang=&harder=` is how a book with no barcode, a damaged
one, or one printed before ISBNs existed gets added. **It needs no API key.**

It answers with an object, not a bare list: `matches`, plus `asked` and `unasked` naming
the catalogues this fan out did and did not reach. See *Searching harder* below.

Eight catalogues, in three tiers, all asked concurrently:

| Tier | Sources | For |
|---|---|---|
| Primary | Open Library, K10plus, DNB | Breadth and covers; German and European publishing; German legal deposit |
| Regional | BnF, Library of Congress, Austrian National Library, National Library of Greece | French; Spanish, Portuguese and Latin American; Austrian imprints; Greek publishing |
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
  naming different languages are never merged: a translation is not the same book. A merged
  row takes `classifications` from the first source that has any, and an **empty list counts
  as no answer**. Two populated lists are not unioned: the leading source's win.
* **Ranking.** The SRU catalogues return catalogue order, which is roughly newest first.
  Results are scored against the query: how much of it a row accounts for, then how
  complete the row is, then how recent. Completeness can never outrank matching.

`lang` is the reader's own language and breaks ties only, so an English title searched
from a German interface still returns the English book first.

A source that fails is skipped rather than failing the search, and a source that has not
answered within `SEARCH_DEADLINE_SECONDS` is cancelled. One national catalogue having a
bad afternoon degrades the results, not the latency.

#### Searching harder

A catalogue can be slow enough that the shared deadline cancels it before it ever answers,
which makes it a burned connection and never a record. Switching such a catalogue on would
therefore change nothing, so it is left out of the ordinary search and reached by asking
for it: `harder=true`, under a longer deadline of its own.

Nothing is left out on the ISBN path and nothing needed to be. That chain asks one source
at a time and stops at the first hit, so a slow catalogue there is reached only when every
faster one has already missed, which is exactly when a reader wants it.

`harder` is a request rather than an instruction, and three things can make the answer an
ordinary search anyway: this library has no such catalogue switched on, the one long fan
out allowed at a time is already running, or the query reduced to no usable terms. The
response says which catalogues were reached rather than leaving a client to infer it:

| field | meaning |
|---|---|
| `asked` | the catalogues this fan out reached |
| `unasked` | the switched on catalogues it did not, which is exactly what asking harder would add |

So a client offers the second search when `unasked` is not empty, and never has to guess
whether the first one already ran.

**An empty `asked` beside a non empty `unasked` is a distinct state from finding nothing**:
every catalogue this library has switched on is a slow one and nobody has asked for them
yet, so "no matches" would be a claim about the book from a request that asked nobody. Both
empty is the other way of asking nothing, and it is the reader's doing rather than the
library's: a query of two characters can reduce to no usable terms, `and` and `a b` both
do, and nothing was asked because there was no question. The two are told apart by
`unasked` and not by `asked` alone.

**Which catalogues are slow is a property of the catalogue, not a setting.** It is decided
from measured latency against the ordinary deadline, and the settings screen says so on the
row, so a catalogue that is off because it is slow does not read as one that is broken.

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

`GET /api/books/lookup` asks eight catalogues in two phases and merges what comes back.

**Phase one, asked together:** the **Deutsche Nationalbibliothek** and **K10plus**, the
union catalogue of the German library networks. Both are free, need no key, and are the
two fastest sources here that answer broadly: 0.26s and 0.51s at the ninetieth percentile
over the 500 ISBN sample below. They are asked together, so the pair costs the slower of the two rather than
the sum. Their records are merged field by field,
nothing overwritten, so a page count from one and a subject heading from the other land on
the same book.

**Phase two, asked in turn, only if neither knew the book:** **Open Library**, then the
**Czech National Library**, then the **Spanish National Library**, then the **National
Library of Greece**, then the **Austrian National Library**, then **Google Books**. Phase
two stops at the first hit, so it is ordered by how often a source answers a book phase one
missed: of 278 such ISBNs in 500, Open Library answers 82, the NKP 42, the BNE 40, the NLG
34 and the ÖNB 1. Open Library is the broadest source and much the slowest, which is why it
is here rather than in phase one; Google is the only one with a key, a quota and a bill
attached, and an ordinary lookup therefore spends no quota at all.

**A national catalogue is never in phase one**, however well it does on the whole sample.
Phase one is paid on every lookup by every install, and what a national catalogue answers
is concentrated in the country it serves: the NLG answers 34 of the books phase one missed
and **all 34 are Greek**. Pooled over ten countries that reads like the best second slot
there is. A Greek library can promote it in Settings, which is what the provider list is
for.

**And in phase two it is asked only about the ISBNs it could hold.** An ISBN names its own
registration group, `978-3` for German language publishing, `978-960` and `978-618` for
Greek, and a catalogue whose collecting remit is one of those is skipped for a book from
another. So a German library stops paying a round trip to Athens on every scan the German
pair misses. Measured over the same 500 ISBNs: **1.435s per lookup becoming 1.336s**, and
**872 phase two requests becoming 673**, for the same 395 books.

**The Spanish National Library declares no remit**, unlike the two above it, and that is a
measurement rather than an omission: it alone answers four books outside `978-84`, one
Portuguese, one Argentine and two Uruguayan. A remit would stop it being asked about them.
So it is the one national catalogue in phase two that every lookup can reach.

**No book is lost to it, and that is a measured bound rather than an intention.** A
catalogue may carry a remit only if there is no book it alone answers outside that remit,
which rules the Czech National Library out on two: a Portuguese one and an Argentinian one
that nothing else in the roster holds. `backend/sources.py` carries the table and the
measurement, as `SERVES_GROUPS`.

**Three things are asked anyway**, and each is a place the rule declines to make a claim
rather than a hole in it. Phase one is never filtered, so a catalogue a library has
promoted there is asked about every ISBN whatever its remit. An ISBN whose registration
group this build cannot decode goes to everybody. And so does one whose **Bookland
prefix** no remit mentions: `978` and `979` are separate assignment spaces, a catalogue
whose country has no `979` group yet cannot say so, and silence there is read as no claim.
Without that last one every `979` ISBN would have lost both national catalogues, and the
500 ISBN sample is entirely `978`, so nothing in it would have said so.

**The Czech National Library answers a scan and never a search**, which is the one
asymmetry in this table and is the server's rather than a preference: it returns a single
filled in record per reply whatever page size is asked for, so ten search results would be
ten requests. A lookup wants one record and gets one.

**No order of these seven finds more books than another.** Every enabled source is asked
until one answers, so the order decides latency and which records are merged, never
coverage. Reordering is not the fix for a book the chain misses.

The one thing that does change what a source is asked about is its **remit**, above, and
it is a different axis from the order: a national catalogue below phase one is asked about
the registration groups it collects and no others. The bound on that is zero books, so the
sentence above holds in practice as well as in principle.

**What the chain covers without a Google Books key, which is what a stock install runs.**
Seven of the eight are free; Google Books needs a key you supply. Measured over 500
domestic ISBNs across ten countries, the seven free sources answer **395 and miss 105**,
and outside German language publishing they miss **101 of 400**. The same books under an
earlier release answered 300: the three national catalogues added since, the NLG, the NKP
and the BNE, account for part of that and a fix to how a qualified `020` is read accounts
for the rest, 51 records that three sources already held and this app was refusing. So a statement that this chain covers a given country is
still a statement about a keyed install: an earlier survey put Italy at 36% missed keyless
against 0% with a key, and Greece at 86% against 54%, and the Greek half of that has since
moved on its own, from 7 of 50 keyless to 39 of 50. The per source figures are in
`backend/sources.py`, `MEASURED`.

Open Library is read as three records rather than one: the **edition** for the printing,
the **work** behind it for the subjects and the author the edition mostly omits, and one
call for the author's name. Measured over 35 live ISBNs on 2026-08-24 against what shipped
before, with no losses: subjects on 28 records rather than 16 (178 entries rather than 36),
a page count on 20 rather than 0, a language on 27 rather than 0, an author on 35 rather
than 34, and classifications on 12 rather than 0. The cost is roughly 0.2s: the same 35
ISBNs measured 1.24s then 1.15s before the change and 1.34s then 1.46s after it, which is
network variance around two extra requests on a source that is only asked when the DNB and
K10plus have both missed.

A 404 means every source whose remit reaches this ISBN was asked and none holds it. That
is still a claim about the book rather than about the library, which is why a library whose
whole list is national catalogues and whose book is foreign to all of them gets a 404 here
and not the 409 below: the catalogues are switched on, they simply do not collect it.
The ranking and the measurements behind it are in `backend/metadata.py`.

The response carries `classifications`, each a scheme, a number and the caption the
catalogue gave it, and `suggested_tag_ids`. Four schemes are produced. `ddc` and `lcc`
arrive with no caption (MARC carries the notation and the printed schedule carries the
words). `gnd`, the German subject authority file, arrives as an authority record number with
the heading text as its caption (`gnd`, `4203576-4`, `Schatz`). `lcsh` arrives as the
authorised heading string itself, subdivisions included
(`Computer software -- Development`), with no caption: the Library of Congress publishes no
identifier for it in this record, so the string is the access point.

**`lcsh` reaches only the search response**, not this one. The Library of Congress is not
one of the eight sources a lookup asks, so a scan never sees an LCSH heading; a picked search
result carries it into `POST /{id}/enrich/apply`, which is how it reaches a book.

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
a payload.** `max_length` caps one request. The capped writers, creation or selected
enrichment through `POST /{id}/enrich/apply`, and merge, count the rows already there and
stop. A backup restore is deliberately uncapped because it restores a whole database. The
writes are additive across requests and neither `POST /{id}/enrich/apply` nor `POST /merge`
carries a rate limiter. At the ceiling an incoming heading is dropped rather than a stored
one evicted, and a caption still fills in on a heading already held. **Which one is dropped
is decided by order**: the list is sorted by scheme before it is cut, in the order DDC, LCC,
GND, LCSH, so a Dewey number outranks a subject heading whichever catalogue supplied it. GND
leads LCSH because its number is an identifier that outlives its own caption, where an LCSH
number is the heading text and moves when the Library of Congress revises it. The reason the number matters:
`BookOut.classifications` is on every listing row, so an inflated book is paid for on every
page that contains it. Measured on 2026-08-24 against one catalogue, which is not the whole
of what a book can carry: 3.07 headings per record over 85 DNB lookups, and 8 of 189 records
from four DNB searches above eight.

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

The **custom** group is whatever a library invents. Creating one is open to
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

**`key` is sent beside it, and says *which* seeded tag the row is.** The flag
cannot: it records that a row was seeded, which is not enough to pick a
translated name for it. `name` is the English name, and the client prints the
one matching the reader's language by looking the key up in
`frontend/src/i18n/tagNames.ts`. It is null on a tag the library invented and
null on a seeded row somebody renamed, and both are then shown as typed.
`TagStat` carries it too, because the stats page prints tag names of its own.

A key the running version does not recognise is **forgotten rather than
refused** (`schemas.tag.known_key`): the tag list is one response for the whole
vocabulary, so a row written by a newer version would otherwise 500 every page
that draws a tag.

### Custom fields

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books/custom-fields` | member | Every field the library has defined, in the order it defined them |
| POST | `/api/books/custom-fields` | member | 201; a name that already exists returns that field; 409 past 25 |
| PATCH | `/api/books/custom-fields/{id}` | member | Rename. Every value under it is kept. 409 on a collision |
| DELETE | `/api/books/custom-fields/{id}` | **admin** | 204, and the values go with it |
| GET | `/api/books/{book_id}/custom-fields` | member | Only the fields this book has something in |
| PUT | `/api/books/{book_id}/custom-fields/{field_id}` | member | An empty value clears it. Returns the book's whole list |

A fact the library keeps about a book that this schema has no column for. The
definition is library wide, like a tag, and the value is per book. The first
concrete use, and the reason it exists, is a link to the same book in a
calibre-web instance.

**Defining is open to any member and deleting is admin only**, the same split
`DELETE /api/books/tags/{id}` makes and the sharper case of it: deleting a field
destroys, in one request with no undo, content every member typed by hand, on
books the caller may not see.

**No usage count is published**, unlike `TagOut.book_count`. A count of the books
carrying a field is drawn across books the caller may not see, so it would have to
be scoped to the viewer, and a viewer-scoped number in a delete confirmation would
understate what is about to be destroyed.

**A field's `kind` is chosen once and never changed.** Changing it would
reinterpret every value already under it in both directions. Delete and redefine
is the honest version, and it says out loud that the values go.

**One verb for setting and clearing.** Emptying the box and saving is what a
person does, and a separate DELETE would leave a client deciding which of two
verbs an empty box means. Clearing deletes the row rather than storing an empty
one, which is what makes "a book with no value shows nothing" a property of the
schema.

`CustomFieldValueOut.href` is what a client points an `<a>` at, and it is decided
on **this read** rather than trusted from storage: a `url` field whose value is
not an `http` or `https` URL with a real host comes back with `href` null and is
rendered as text. A write that fails the same test answers **422** rather than
degrading silently, because a field somebody declared a link and cannot click,
with nothing saying why, is worse than an error. See [security.md](security.md).

These are served here rather than on `BookOut`, like notes and quotes and unlike
tags: a page of 25 book cards has nowhere to render them, and `books_to_out` is a
fixed statement budget that a test reads out of its own docstring.

### Importing a library

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/imports/preview` | user | Reads the file and reports what it is. Writes nothing |
| POST | `/api/imports/csv` | user | Applies it. `create_missing`, `apply_tags`, `overrides` |
| POST | `/api/imports/marc/preview` | user | Reads a MARCXML file and reports what it holds. Writes nothing. **403** without library mode |
| POST | `/api/imports/marc` | user | Applies it. `create_missing`, default **true**. **403** without library mode |

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

### MARC21, in and out

The exchange format every other library system speaks, and a **library mode**
feature at both ends: `POST /api/imports/marc` and
`GET /api/books/export?format=marcxml` both answer **403** with the mode off.
Enforced on the server rather than by hiding the controls, for the reason
`routers/public.py` states about the public catalogue: disabling a button in a
browser is advice to one client. 403 rather than the 404 the public catalogue
gives, because the caller here holds a session and
`GET /api/settings/features` already publishes `library_mode` to anybody.

**MARCXML only, never ISO 2709.** The binary serialisation carries a directory
of byte offsets that has to agree with the field data after every change, and
every consumer that reads it reads MARCXML too.

**The reader is the one that parses live catalogue answers.** `backend/marc.py`
composes `metadata.py`'s MARC primitives rather than restating them, so an
uploaded record is read exactly as a DNB or K10plus answer is: the non-sorting
delimiters in both spellings, NFC normalisation, the repeated `082 $a`, the
`020 $q` that marks a cross reference to another edition, the ISBD punctuation
that introduces the next subfield. What `marc.py` adds is policy, and it differs
in three places from a lookup's:

* **A record with no title is the only refusal.** A lookup also refuses a title
  naming a volume slot and refuses a disc, because a catalogue's identifier
  index matches cross references and the wrong record poisons an entry. An
  upload is a cataloguer handing over their own file.
* **Author identifiers are not read**, though `100 $0` is the same subfield the
  DNB is trusted for. A catalogue is not read for a person's identifier until
  somebody has compared it live, and nobody can compare an arbitrary upload.
* **`050` and `650 $2 lcsh` are read**, which no catalogue this app queries
  sends: they are the Library of Congress call number and subject heading, and
  both have columns here.

**Matching is ISBN, then author and title together, never title alone.** The CSV
importer matches on title alone, which is right for a reading history: the worst
case is a status on the wrong edition of a book somebody read. The worst case
for a catalogue is two different books folded into one record, and every library
holds more than one *Selected poems*. Both use `importing.identity_key`, which
is also what the duplicate finder computes.

**One unreadable record costs one record.** A catalogue export is the product of
years and is not uniformly clean, so a record with no `245 $a` is counted in
`skipped` and the rest of the batch completes. The **file** being the wrong
thing is a 400: not XML, a doctype, an encoding this reader refuses (which
includes a declared multi-byte one such as `EUC-JP`), no `<record>` element, or
more than 20,000 records. A body declaring more than the upload cap is a 413
from the body size middleware, before a byte is spooled.

**A record's values are held to the bounds `POST /api/books` applies.** Strings
are cut to the column, and a number outside the schema's range is stored as
absent rather than clamped: `264 $c` of `9999`, MARC's own open ended date, is
no year at all, and a `245 $n` past the series ceiling is no volume number. See
[security.md](security.md#the-two-catalogue-uploads-which-are-not-images) for
what that cost before it existed.

**The preview models both of the import's refusals.** `already_held` counts what
will be matched and filled in; `blocked` counts what will be refused because its
ISBN belongs to a book the caller cannot see. Without the second,
`readable - already_held` overstated what an import would add by exactly the
number another member holds privately. `blocked` is a count and never a title,
for the reason the 404-not-403 rule exists.

**More than 20,000 records aborts rather than truncating**, which is the
opposite of the CSV reader and deliberate. A truncated reading history is a
partial reading history. A truncated catalogue transfer is an institution being
told its holdings moved when most of them did not, silently.

**A doctype is refused, and a UTF-16 file with it.** `xml.etree` expands
internal entities, so a 5 MB upload carrying one can define an entity worth a
thousand times its own bytes and the upload cap stops bounding the work. The
doctype check is a byte scan, exact for the ASCII compatible encodings and blind
to the others, so the encodings it cannot see are refused first: that is what
makes the scan a guarantee rather than a guess.

**A MARC import writes nothing personal.** A catalogue record carries no reading
status, no rating and no review, so no `user_books` row is touched and
`statuses_updated` comes back zero. `create_missing` defaults to **true** here
and to false on the CSV path: a reading history is mostly books the household
does not own, and a catalogue transfer that adds no records has transferred
nothing.

**The export carries the classifications**, which is the half another
institution shelves by: `082` for Dewey, `050` for Library of Congress, `650`
with `$0` and `$2` for a GND or LCSH heading. It carries no `008`, because that
field encodes place of publication, illustration codes, literary form and
intended audience, none of which this app holds, and filling forty positions
with guesses writes assertions nobody here can support.

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
| GET | `/api/loans/overdue` | user | The overdue loans themselves, paginated, most overdue first. **Narrower than `?overdue_only=true`**: see below |
| GET | `/api/loans/overdue/mine` | user | The in app reminder: how many overdue loans this member is being chased about |
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

**`days_out` and `days_overdue` are computed per request too, and are whole days.**
`days_out` is how long the book has been away, counting to `returned_at` on a closed loan
and to now on an open one; it is the number that means something for lending with no
deadline, which is most of it. `days_overdue` is how far past `due_at` a loan is, and is
`0` both for a loan that is not overdue and for one that went overdue within the last day,
so it is read together with `is_overdue` rather than on its own. Both are computed on the
server so that a row on a screen and a line in an overdue reminder cannot come to disagree
about the same loan: they are one function, and the digest calls it.

A book has at most one open loan. Recording a return is a shelf action, not an ownership
one, so any member may do it for any book they can see. The listing excludes loans of books
the caller cannot see, which would otherwise disclose a private book's title and holder.

**A book marked `lending = never` is refused once, not forbidden.** The first request gets
a **409** whose detail is an object, `{"message": ..., "code": "not_lendable"}`; the same
request carrying `acknowledge_not_lendable: true` creates the loan. The code is there
because the client has to branch on it: this 409 puts a confirmation in front of the lend
button, and the already-out 409 does not, so matching on the prose would break the moment
it was reworded. The flag is **not stored**, and the book still says it is never lent
afterwards: it answers one request rather than changing the library's mind. `in_use` and
`happy` are not checked at all. The reasoning is in [decisions.md](decisions.md).

**Overdue reminders** go out as one digest on every channel switched on, hourly from a
task started with the app. Three of them **push**: a **webhook** (the JSON below, POSTed to
an admin-configured URL), **email** over SMTP, and a **Telegram** chat. Each is toggled by
itself and they all carry the same digest, rendered as JSON for the webhook and as plain
text for the two a person reads. `POST /api/loans/overdue/notify` runs the same pass
immediately, which is what makes the feature testable by a person and what an external
cron would call instead. It answers
`{sent, loans, skipped_private, reason, detail, senders}` rather than a bare 204, because
"nothing is overdue" and "the receiver refused it" both look like silence otherwise.

The fourth is the **in app** notice, and it is not a push. A member reads the count from
`GET /api/loans/overdue/mine`, which answers `{enabled, count}`, and the loans themselves
from `GET /api/loans/overdue`. It is the only channel that needs nothing obtained first, so
it is the only one that ships switched **on**.

**`GET /api/loans/overdue` is not `GET /api/loans?overdue_only=true`, and the difference is
which question the answer is to, not who may read it.** The loans list is rooted at the
shelf and stops there, so it answers with every overdue loan over a book the caller can
see, housemates' loans included. That is the household's loans list working as designed:
bare `/api/loans` with no parameter answers the same set, and `overdue_only` opens nothing
that was closed. The overdue endpoint applies `notifications.overdue_for_viewer` on top: a
member reads the loans they lent or borrowed, and staff read every overdue loan on their
shelf.

**In library mode that narrowing lifts for every member**, so the overdue endpoint answers
with every overdue loan over a book the caller can see, which is the same set
`?overdue_only=true` answers. The mode exists for a library whose volunteers are not
admins and still have to chase a book somebody else lent out. It is a clause about who is
**party to a loan** and not about which books exist: both arms are rooted at the shelf
either way, so a private book somebody else added is as far out of reach with the mode on
as with it off, for a member and for an admin alike.

That is the rule the count above is computed with, so a screen showing one and counting the
other disagrees with itself: measured for a non admin member, a nudge reading the wide set
said 2 above a page listing 1. Both are narrowed by the shelf first, so **neither can reach
a book `visible_to` excludes**, and the choice between them is about a surface being
consistent rather than about access.

It also honours `overdue_in_app_enabled` and answers an empty page when that switch is off,
because the switch is spelled "show overdue loans in the app" and this is what it shows.
The loans list is not affected: a list of the household's loans is not the reminder
channel.

`reason` is `disabled`, `no_url`, `nothing_due`, `unreachable`, `misconfigured` or
`in_app_only`, and is **null exactly when `sent` is true**. It is a closed set because a
client has to render the difference and cannot branch on prose; `detail` is the same outcome
as a sentence, for a log or a caller with no message catalogue. A 200 with `sent: false` is
the ordinary answer for all six: none of them is an error in the request. `in_app_only` is
the run where the in app notice is the only channel on, so nothing was sent anywhere and
nothing was meant to be.

`senders` holds one `{sender, sent, loans, skipped_private, reason, detail}` per channel this
run had something to report, in the order in app, webhook, email, Telegram. A pushing sender
is reported when it was **tried**, and a run with nothing overdue tries none, so the list is
empty in two cases: every channel off, and nothing overdue while the in app notice is off.
The in app row appears even on a run that pushed nothing, including one with nothing overdue,
because "is it on" is the question a household with no receiver is asking.

**`sent` at the top is true when any sender that pushes delivered**, which is also the
condition `notified_at` is stamped on: a reminder went out. Stamping only on a clean sweep
would turn one broken receiver into an hourly repeat of the same list on the channels that
work, so a failed channel is reported here rather than compensated for. **The in app row
never sets it**, and that is not a detail: it delivers nothing, so counting it would stamp
every overdue loan on every run and cut the three that do push from one attempt an hour to
one per reminder interval.

**The withheld count is per sender as well as at the top.** The three that push exclude the
same private books, because each goes to a channel rather than to a person, so their three
numbers agree. The in app row reports **0**: its audience is a member, so nothing is
withheld from it.

**A channel's standing record** is `GET /api/settings/sender-health`, admin only, one
`{sender, last_run_at, sent, reason, detail, failing_since, failures, broken}` per channel
that is switched on. Every run writes it, the manual one included, so a failure survives the
run that produced it rather than living only in the container log. `sent` is null until the
channel has run at all, because "not yet" and "fine" are different answers.

`broken` is a judgement rather than a fact, and it is two rules. A refusal the app made
itself (`no_url`, `misconfigured`) counts at once, since all of those are raised before a
socket is opened and nothing will work until a setting changes. A destination that could not
be reached counts only after **24 hours** and at least **two** consecutive failures: one
failed send is a network, every send failing for a day is a configuration, and a design that
cannot tell them apart is one a household switches off.

**Any write to a channel's own settings clears its record**, not the on/off switch alone.
Replacing an expired bot token, or correcting a mail server, port or encryption choice, is
the write that repairs the channel, so it is the write that has to clear it;
`notifications._CONFIGURED_BY` is the list of rows that count. The reminder interval is
outside that rule, being about how often a loan is chased rather than about any channel.
Nothing else clears a record: a run records only the senders it **attempted**, and a run with
nothing overdue attempts none, so a household in its steady state produces no evidence either
way. `last_run_at` is therefore worth reading beside `broken`, because it says how old the
verdict is.

**It is per sender per run, and never per loan.** There is no loan id in the record, so no
screen built on it can say that a particular borrower was or was not told; the most it
supports is "this channel is not getting through". Two screens draw it and both say what
they are describing: Lending settings, under the switch that repairs the channel, and the
overdue page, beside the loans, where the note above the lines states in as many words that
they are about the channel and not about any one loan. Anything stronger would need a per
loan per sender table, which [decisions.md](decisions.md) records as more than this feature
warrants.

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

Three properties of the request are load bearing. **Private books are excluded, on every
channel that pushes**, in the query rather than afterwards: none of the three has a member
identity behind it, and each lands where the whole household reads. The in app notice is
the exception and it is the rule rather than a hole in it: that query is rooted at the
Shelf, so each reader gets what `visible_to()` already says they may see, their own private
books included. `skipped_private` counts what
was held back, never names it. The webhook body is signed with HMAC-SHA256 in
`X-Endpaper-Signature: sha256=<hex>` when a secret is set, over the raw bytes, so a
receiver verifying a re-serialised payload will fail. And **redirects are not followed**,
unlike the metadata lookups: these are the requests whose payload is catalogue content
going somewhere unauthenticated.

Two properties belong to the added channels. **Telegram's host is a constant, not a
setting**: `api.telegram.org`, so the app rather than the configuration chooses where the
titles go, which is the one thing this channel has that an arbitrary webhook URL does not.
The message is sent with **no `parse_mode`**, because with one set a book called
`Kiss & Tell` or `a_b` makes Telegram reject the send and the reminder stops for everyone.
**SMTP always verifies**: the TLS context is built in `mailer.send` and there is no
setting, parameter or environment variable that relaxes certificate or hostname checking. A
mail password configured with neither STARTTLS nor implicit TLS is refused before a socket
is opened, rather than sent in the clear.

A loan is chased again only once `overdue_reminder_days` have passed since its last
reminder. `notified_at` is stamped after a delivery that succeeded, so a failure retries
on the next run. The in app notice ignores that column entirely, in both directions: it
does not stamp it, and it does not read it, because a loan is on the member's screen for as
long as it is overdue.

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
| GET | `/api/settings/sender-health` | **admin** | What each switched-on reminder channel last did. See the Loans section |
| GET | `/api/stats` | user | Totals, per-member, per-tag, per-month, pages read |
| GET | `/api/users` | user | The member list |
| GET | `/api/users/test-accounts` | **admin** | The accounts an admin may switch into |
| POST | `/api/users/test-accounts` | **admin** | 201, and takes an optional address. **400** if the name is taken, **422** under the 8 character floor or if the address is not one |
| GET | `/api/users/me/appearance` | user | The caller's own palette, mode and wallpaper |
| PUT | `/api/users/me/appearance` | user | Replaces all three |
| GET | `/api/users/me/email` | user | The caller's own address, whether it is theirs to change, and whether the account came from a directory |
| PUT | `/api/users/me/email` | user | Sets or clears it. **409** where the directory owns it, **422** if it is not an address |
| GET | `/api/users/emails` | **admin** | Every member's address |
| PUT | `/api/users/{user_id}/email` | **admin** | Same body and the same two refusals, for anybody. **404** for no such member |

**`editable` and `from_directory` are two flags because there are three cases.** A local
account is neither owned nor from a directory; a directory account whose directory carries
an address attribute is read only; and a directory account whose directory carries **none**
is editable, empty, and belonged to somebody nobody ever asked for an address. The third is
the only case where a screen has something to explain, and `editable` alone reads the same
on it as on the first.

`/api/settings/features` is public for the same reason the login image is: the login page
is localised, so the default language has to be known before a token exists. It carries no
secrets and nothing about the catalogue. Since the public catalogue it also carries
`public_catalogue_published`, which is what tells a browser holding no token whether there
is a catalogue to offer. It is the **server's conjunction** of library mode and the publish
switch, never either row, so a client cannot get the nesting rule wrong. `library_mode` is
deliberately **not** on this model: the cataloguer column set it changes is a later ticket,
so it would be an unread field on the one endpoint a stranger can call.

#### The provider list

`GET /api/settings` carries `catalogue_sources`: the **whole** roster, in the order this
library asks it, one entry per catalogue. A switched off source is still listed, because
the screen has to be able to offer it back; leaving it out would make "off" and "not in
this build" the same thing on screen.

Only `source` and `enabled` are the library's to set. The rest are computed on the server
so a browser cannot get the rule wrong: `answers_lookup` and `answers_search` say which
questions this catalogue can answer at all (the BnF and the Library of Congress answer
title search only), `asked_first` says whether it is in the leading pair asked together on
every ISBN lookup, `serves_groups` names the registration groups this catalogue's remit
covers and is empty for one with no remit to state, and `needs_a_key` with `ready` say
whether it can answer at all in this deployment.

`serves_groups` is the third thing a row can be, beside on and off: asked, at the position
it holds, for some books and not others. Without it a national catalogue reads as switched
on and answers nothing on nine scans in ten.

**It is the remit a catalogue declares, not the filter that was applied to it**, and the
difference shows on one row. Phase one is never filtered, but a catalogue promoted into
phase one still reports its remit here: a list of just the Austrian and Greek national
libraries returns both with `asked_first` true and `serves_groups` populated, and both are
then asked about every ISBN. `asked_first` is the field that answers "is this filtered",
so anything drawing this reads that one first.

**What the order decides, and what it does not.** It is the order sources are **asked**.
It is not the order they are **believed** when two disagree about one field, which stays
in the backend: no single order reproduces both of today's behaviours, so one list driving
both would silently move something nobody touched. `backend/sources.py` carries the
argument in full.

**Off means not asked**, on every path in the catalogue chain that reaches a source for a
record. It is not a claim about every request the application makes: the cover store still
asks Open Library and the DNB for an image, and the author authority still asks three more
hosts. `backend/sources.py` states that boundary.

With every capable source switched off, **all four routes that reach a catalogue answer
409** naming the setting rather than 404 or an empty page: `GET /api/books/lookup`,
`GET /api/books/search`, `GET /api/books/{id}/enrich/candidates` and
`POST /api/books/{id}/enrich`. A 404 there would be a claim about the book made by an app
that asked nobody, and an empty result page reads the same way. Enrichment refuses up
front rather than per half, so one request cannot answer 409 for its ISBN half and fail
for its search half.

**`GET /api/books/search` names the title search in its message.** The other three name
the ISBN lookup, which is what the shared sentence has always said.

`PUT /api/settings` takes `catalogue_sources` as a list of `{source, enabled}`. It is
**merged against what is stored, not taken whole**: a payload naming one source says
nothing about the others, and completing it from the defaults would read a request to
disable one catalogue as an instruction to switch six on. A name this build does not know
is refused with 422, and the list is bounded at the size of the roster.

`PUT /api/settings` accepts `library_mode`, `public_catalogue_enabled` and
`public_catalogue_indexing_enabled`, and **refuses no combination of them**: an admin may
store a publish row while library mode is off, and the catalogue stays unpublished because
the routes ask `public_catalogue_is_published` rather than reading a row. Refusing the
write instead would make the order two toggles are saved in matter, and would lose an
admin's stated intent the moment they turned library mode off to look at something.

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

An address is the same case as appearance and is handled the same way: **not** a field on
`UserOut`, so no book payload and no member list carries one. It is served by the four
routes above and nowhere else, and
`tests/test_house_rules.py::TestAnAddressIsServedOnlyWhereItIsNamed` fails if **any** other
model this app builds puts an address in front of a caller, whether by naming one on the
wire or by carrying a model that does. Two models are exempt, so the third fails, and one
added to `UserOut` fails at once.

Who may write it is two rules. A member writes their own; an admin writes anybody's. Both
are **409** where the deployment's directory owns the address, which is the case when
`LDAP_EMAIL_ATTRIBUTE` or `PROXY_EMAIL_HEADER` names where one comes from: there the next
sign in overwrites whatever was typed, so the write is refused rather than reverted later.
409 and not 403, because nothing about the caller's rights is wrong and there is no
permission an admin could grant themselves. `editable` on the response carries the same
answer per member, so the client can draw the field read only instead of offering an edit
that will be refused.

The body is `{"email": ...}`; `null` and an empty string both clear it, and anything else
must pass the address rule the household recipient list already passes, which is a **422**
if it does not. That rule rejects whitespace, newlines, commas and semicolons, the
characters that turn one header into two.

Nothing sends to these addresses yet. The mail sender still posts one digest to
`overdue_mail_to`, so filling the field in changes no behaviour: see the Loans section.

`/api/users/test-accounts` is a local account with a password an admin sets, for seeing the
library the way an ordinary member sees it. It works in **every** auth mode, which is the
point: `POST /auth/register` is 403 under `ldap` and `proxy`. The body is `UserCreate`, so
registration's password policy applies unchanged, and the account is never an admin.

The GET returns only test accounts, so the client cannot offer a directory member as a
switch target. That is presentation: `POST /auth/switch` refuses one regardless. Test
accounts do appear in `/api/users` like any other account, because the loan picker is a
list of everybody who could hold a book.

`PUT /api/settings` also carries the reminder fields, for all four channels; the in app
one is a single switch, since it has no destination and no credential.
`overdue_webhook_url` and `telegram_chat_id` are returned **in full**, unlike the Google
Books key: a destination nobody can read back is a destination nobody can proofread, and an
admin who can read it is an admin who can change it. A URL whose scheme is not `http` or
`https` is a **422**, checked again in `notifications.py` before any send because a restore
writes the settings table through Core. `overdue_webhook_secret`, `mail_password` and
`telegram_bot_token` follow the API key exactly: masked on the way out, absent means "leave
alone", an empty string clears. `overdue_reminder_days` is 1 to 365; zero would mean
resending the same list on every tick.

**Ten of these settings may be pinned by the deployment**, through `GOOGLE_BOOKS_API_KEY`,
the seven standard `MAIL_*` variables, `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Where
one is set it **wins over the stored value**, `GET /api/settings` reports the value in
force rather than the row, and `PUT` answers **409** naming the variable rather than
storing something nothing will read. `mail_from_env` lists which of the mail settings that
applies to, so a client can disable a field instead of offering an edit that can only fail.
Reporting where a value comes from is not reporting the value: a pinned secret is still
masked. The eighth standard mail name, `MAIL_DEBUG`, is deliberately **not** honoured,
because smtplib's debug output writes the AUTH exchange to stderr.

`StatsOut.pages_by_month` is the pages the requesting member read, by month, computed from
the positive deltas between their consecutive page-unit entries per book. **Page-tracked
books only**, which the heading on the stats page says as well: an audiobook records a percentage, and converting that into a page count
would produce a number that adds up with the others while meaning something else. The
first entry on a book counts in full; a backwards step counts nothing, which covers both a
re-read and a corrected typo and refuses to let the second inflate the figure.

Every `/api/stats` aggregation applies the privacy predicate independently.

### The public catalogue

**The only endpoints in this API that answer without a session.** Off by default: both
`library_mode` and `public_catalogue_enabled` have to be on, and the conjunction is
evaluated on the server, so a publish row left on while library mode is off serves nothing.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/public/books` | **public** | Search the published catalogue. **404** when nothing is published |
| GET | `/api/public/books/{book_id}` | **public** | One record. **404** for a book that is private, trashed or absent |
| GET | `/sru` | **public** | The SRU base URL. Same switches, same rate limit. Not in the OpenAPI schema |
| GET | `/robots.txt` | **public** | Generated from the switches. Not in the OpenAPI schema |

**`HEAD` answers 404 where `GET` answers 200**, on these routes and on every other GET
endpoint in this API. FastAPI's `APIRoute` does not add `HEAD` the way Starlette's `Route`
does, so a HEAD request only partially matches and falls through to the JSON 404 fallback.
It is not fixed here because `custom_operation_id` drops the path from the operation id, so
declaring `methods=["GET", "HEAD"]` gives the HEAD operation the same id as its GET and
`assert_unique_operation_ids()` refuses to start the app. That is a boot failure rather
than client noise, and it is why this is a separate change. In practice crawlers issue GET,
and `robots.txt` is itself a GET, so what meets the 404 is `curl -I` and a monitor.

**Everything about these is 404 rather than 403**, which is the house rule applied where it
matters most. A 403 on the listing would confirm that this deployment holds a catalogue it
is withholding; a 403 on an item would confirm the id exists, and a stranger counting
through ids would learn how many private books a library holds.

**The payload is `PublicBookOut`, not `BookOut`**, and it is a separate model rather than
an exclusion list: an exclusion list publishes every field somebody forgets to add to it.
It carries the bibliographic record, the format, the tags and the classifications, and
nothing about a member, the household or the transaction. Ownership, lending willingness,
reading status, member names, notes, purchase details, the shelf location, the collection
and the copy count are all absent. A locally uploaded `cover_url` is dropped and only an
https URL from a metadata source survives, because `/covers/<id>` is served behind
`book_for_read` and a public reader cannot fetch it.

The query parameters are a subset of `GET /api/books`: `q`, `tags`, `format`, `series`,
`sort` and the paging pair. `status`, `unrated`, `discuss`, `ownership` and `lending` are
absent by construction, the first three because there is no viewer to read them against
and the last two because a filter over a column nobody can see is a way to read that
column one query at a time. **`collection_id` is absent too**: the ids are consecutive, so
the filter is enumerable, and what it enumerates is the household's own grouping of its
shelves, which the payload withholds.

`sort` is a **subset** of the signed in listing's, so `sort=newest` is a **422**: it orders
by `added_at`, a withheld column, and an ordering returns the whole ordering of its column
in one request. `tags` is bounded at 400 characters and 32 ids, and a longer list is a 422
rather than a truncation.

**`id` is published and discloses more than an identifier.** It is the insert order, so the
catalogue comes back in acquisition order with no `sort` at all, and `max(id)` against the
number of rows returned gives the count of rows that were withheld. It stays published
because it is the URL a record is read at; see [security.md](security.md).

Rate limited at **120 a minute, keyed on the source address**, which is the weakest key in
`ratelimit.py` and the only one available: there is no username, and `X-Forwarded-For` is
not trusted. See [security.md](security.md).

Unless indexing is separately allowed, every response carries `X-Robots-Tag: noindex,
nofollow` and `/robots.txt` disallows everything.

### SRU

`/sru` is the same catalogue over the protocol other library systems speak: CQL in a query
string, MARCXML out. It runs the **same** gate as the JSON catalogue above, which means the
same two switches, the same 404 rather than 403, and the same 120 a minute counter shared
with it rather than a second budget of its own.

It is **not** in the OpenAPI schema, for the reason `/robots.txt` is not: it is a document
another institution's software fetches, not an operation this application's own client
calls.

| Parameter | Taken | Notes |
|---|---|---|
| `operation` | `explain`, `searchRetrieve` | Absent means `searchRetrieve` when `query` came with it and `explain` otherwise, which is SRU 2.0's rule. `scan` is diagnostic 4 |
| `version` | `1.1`, `1.2` | Nominally mandatory and defaulted anyway, because clients omit it. `2.0` is diagnostic 5 |
| `query` | CQL | Mandatory for a search |
| `startRecord` | 1 and up | Past the end of a non-empty result set is diagnostic 61 |
| `maximumRecords` | 0 and up | **Clamped**, never refused. The cap is advertised in `explain` |
| `recordSchema` | `marcxml` or its URI | Anything else is diagnostic 66 |
| `recordPacking` | `xml` | `string` is diagnostic 71 |

Anything else is refused, `x-` prefixed extensions excepted, and **which refusal depends on
whether the specification defines the parameter**. `sortKeys` is diagnostic 80, `stylesheet`
is 110, `resultSetTTL` is 50 and `recordXPath` is 72, each the number for declining that
feature; a parameter nobody defines is diagnostic 8, which means there is no such
parameter. Telling a client that `sortKeys` does not exist would send it looking for a typo.
That set was checked against SRU 1.2's own searchRetrieve parameter table rather than
assembled from memory.

**Sorting is refused in both spellings**, because SRU 1.2 moved it out of the parameters
and into CQL: `sortby dc.date` at the end of a query is diagnostic 80, the same answer the
retired `sortKeys` parameter gets. Without that arm the client using the current spelling
was told its CQL was malformed while the one using the retired spelling got a straight
answer.

`stylesheet` is a refusal rather than a gap: honouring it would put a client supplied URL
into a processing instruction at the top of the response.

**Every refusal is an HTTP 200 carrying an SRU diagnostic**, which is what the protocol
says and what a client can read. The two exceptions are the gate's, not the protocol's: an
unpublished catalogue is 404 and a caller over the rate is 429.

`operation=explain` reports the indexes that are actually implemented, because the document
is generated from the same table the query compiler reads. Today that is `cql.serverChoice`
and `bib.anywhere`, `dc.title`, `dc.creator`, `dc.publisher`, `dc.identifier`,
`dc.language`, `dc.description`, `dc.subject`, `dc.date`, `bath.isbn` and `rec.id`.
`dc.subject` searches the library's own tags; classification headings are not indexed.

CQL is bounded five ways on the parse, because it is an outside input on an endpoint
anybody can reach: query length, nesting depth, search clauses, words in a term and masking
characters in a term. Each is refused with the diagnostic the specification has for it.
Masking (`*` and `?`) is supported and anchoring (`^`) is not.

There is a sixth bound on what the query costs to **run**, which is a different question:
comparing a term against an index is charged against a budget of **64 units** and a query
that would spend more is refused. One comparison costs **1 unit** through most indexes and
**8** through `dc.description` and `dc.subject`, which measured an order of magnitude
dearer than the rest. `cql.serverChoice` and `bib.anywhere` compare three columns, so one
comparison through either costs **3**.

**`=` compares a term once; `any` and `all` compare once per word.** So
`dc.description all "a study of the keepers of chartreuse windmills"` is eight words,
therefore eight comparisons at 8, and spends the whole budget; the same phrase under `=` is
one comparison and spends 8.

The diagnostic names the index and what one comparison through it costs, in that same unit,
so a refusal says what to send instead: `dc.description: 8 a comparison, 64 a query`. See [security.md](security.md) for the measurements
and the corpus they were taken on.

An integer larger than the catalogue's storage can hold is refused too, on `rec.id`,
`dc.date` and `startRecord`. It was a 500 until it was not.

**CQL booleans are left associative and all have equal precedence**, which is not SQL's
rule: `a or b and c` is `(a or b) and c`. Parentheses are how a client says otherwise.

The records are `marc.py`'s, so they carry exactly the fields the MARC export does, which
is a subset of what `PublicBookOut` publishes. See [security.md](security.md).

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
`CrashLoopBackOff` is visible to every alert a library has, where a pod that is 1/1 Ready
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
