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
| GET | `/auth/me` | user | The current account |

The first account to register becomes admin. `ALLOW_REGISTRATION=false` blocks new signups
without affecting existing accounts, and is read per request.

Login accepts passwords shorter than the registration minimum on purpose, and reports the
same message for an unknown username as for a wrong password. Both are explained in
[security.md](security.md).

### Books

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/books` | user | Paginated. Filter with `q`, `status`, `ownership`, `series`, `location`, `unrated`, `tags`, `sort` |
| POST | `/api/books` | user | **409** on a duplicate ISBN |
| POST | `/api/books/scan` | user | Same, named for the scan flow |
| GET | `/api/books/tags` | user | The seeded tag list |
| GET | `/api/books/lookup?isbn=` | user | Metadata lookup, **404** if unknown |
| GET | `/api/books/export?format=csv\|txt` | user | File download, not paginated |
| GET | `/api/books/google/search?q=` | user | Free-text search for the add flow. **400** if the feature is off |
| GET | `/api/books/series` | user | Every series, with the gaps in it |
| GET | `/api/books/locations` | user | Distinct shelf locations, most-populated first |
| GET | `/api/books/duplicates` | user | Books that look like the same work |
| POST | `/api/books/merge` | user | Fold several entries into one |
| POST | `/api/books/bulk` | user | One verb applied to a selection of books |
| POST | `/api/books/bulk/ownership` | user | Mark up to 500 books at once |
| GET | `/api/books/{id}` | read | **404** if absent *or* invisible |
| DELETE | `/api/books/{id}` | write | 204; cascades to notes, loans, statuses |
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

Both `/google/search` and `/bulk/ownership` are declared **before** the `/{book_id}`
routes. FastAPI matches in declaration order, and while a two-segment path cannot currently
collide with a one-segment one, the ordering is what keeps that true if either is later
reshaped. `/export` is there for the same reason and does collide.

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

`POST /bulk` takes `{book_ids, action, value}` and answers with the same three-way count as
`/bulk/ownership`:

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

`PATCH /{id}/ownership` sets one book. `POST /bulk/ownership` takes `{book_ids, ownership}`
and returns a three-way count rather than a bare success:

```json
{ "updated": 12, "unchanged": 3, "skipped": 1 }
```

`skipped` is **not an error**. A selection can include a book the caller may not modify,
and reporting success for it would be a lie. `unchanged` separates "already set" from
"changed", so the client can say what actually happened. `book_ids` is capped at 500.

### Google Books

Three endpoints share one gate. Both the toggle and the API key are admin settings, and a
**400** naming which one is missing comes back if either is absent. The message says who
can fix it and never echoes the key.

| Endpoint | For |
|---|---|
| `GET /api/books/google/search?q=&limit=` | Adding a book with no scannable barcode |
| `POST /api/books/{id}/enrich?overwrite=` | Filling in a book already in the catalogue |
| `GET /api/books/{id}/enrich/candidates` | Choosing between editions of one book |

`q` is 2 to 200 characters and `limit` is 1 to 20, both validated before the upstream call.
A one-character search would spend somebody's quota on a result nobody wants. Search results
carry `suggested_tag_ids`; the candidates endpoint deliberately does not, because that book
already has tags and they are somebody's deliberate choice.

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

`GET /api/books/lookup` tries **Open Library** first, falls back to **Google Books**, and
404s if neither knows the ISBN. It also returns `suggested_tag_ids`, matched by comparing
the source's subject strings against the seeded tag names.

The response is not a book and nothing is persisted. The client posts it back to
`/api/books/scan` after the member has had a chance to edit it.

`PUT /{id}/refresh` re-runs the same lookup and overwrites the stored fields, with one
exception: a cover the member uploaded (a `/covers/` URL) is never replaced by a remote one.

### Loans

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/loans?active_only=&overdue_only=` | user | Paginated; defaults to active only |
| POST | `/api/loans` | user | Optional `due_at`. **409** if already out, **404** for an unknown or invisible book |
| PUT | `/api/loans/{id}/return` | user | **400** if already returned |

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

Every `/api/stats` aggregation applies the privacy predicate independently.

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
