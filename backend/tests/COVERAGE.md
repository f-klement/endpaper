# Backend test coverage

**2163 tests**, in 51 files. Line coverage was last measured at **96%** (4303 statements,
186 missed) when the suite held 1571, which is 568 tests ago, and has not been re-measured
since: the gate runs `pytest` without `--cov`, and a percentage carried forward across that
many new tests is a number that looks measured and is not.

```bash
uv run pytest                                    # the suite
uv run pytest --cov --cov-report=term-missing    # coverage, with unhit lines
uv run pytest tests/test_dependencies.py -k private   # one area
```

The tree mirrors `backend/`: the tests for `routers/books.py` are at
`tests/routers/test_books.py`. Support files that mirror nothing (`conftest.py`,
`helpers.py`) sit at the root of the tree.

Nothing here touches the network or a real database. Outbound calls to all six metadata
catalogues (Open Library, K10plus, the DNB, the BnF, the Library of Congress, Google Books)
are intercepted with `respx` through `tests.helpers.silence_catalogues`; the database is a
throwaway SQLite file that is dropped and recreated between tests.

**`silence_catalogues` is called last, and that is load bearing.** respx resolves routes in
registration order and the first match wins, and a route whose pattern is *equal* to an
existing one replaces it rather than being appended. Registering the same
`url__startswith` pattern twice therefore silently discarded the test's own response, which
is why the helper uses regexes.

---

## What each file covers

| File | Tests | Covers |
|---|---:|---|
| `test_dependencies.py` | 44 | **Authorization and pagination.** The regression suite for the access-control holes described below |
| `test_config.py` | 52 | Settings resolution, the startup secret guard, upload limits, the frontend switch |
| `test_isbn.py` | 37 | Parsing, check digits, ISBN-10 to ISBN-13, the equivalent forms |
| `test_ddc.py` | 29 | **Dewey headings.** That a number splits from its caption and a year does not, that the segmentation prime is stripped rather than rejected, that the projection reads the number, and that every mapped tag name is a tag that exists |
| `test_backup.py` | 63 | **The whole library out and back.** Round trip, refusing a bad archive, zip path traversal, and that an archive written before a table existed still restores |
| `test_metadata.py` | 108 | **The catalogue chain.** Source ranking, the merge, the cross-reference guards, denoising, the relevance ranking, the search deadline, outcomes, the cache, that a classification keeps its number, its caption and its scheme, and what a MARC record carries that a Dublin Core crosswalk had cleaned up: repeated subfields, non-sorting delimiters, decomposed text |
| `test_errors.py` | 38 | Content-negotiated errors, the 500 handler, API-vs-SPA routing |
| `test_auth_backends.py` | 60 | Local, LDAP and proxy identity sources, and that a directory identity never adopts a test account |
| `test_csv_import.py` | 60 | **Reading anybody's export.** One real shape per service, and the awkward part of each |
| `test_schemas.py` | 58 | Request/response contracts and their validation rules |
| `test_google_books.py` | 37 | Volume mapping, the gap-filling merge, upstream failures |
| `test_notifications.py` | 42 | **The overdue digest.** Selection and the reminder interval, that a private book never reaches the wire, the signature, redirects refused, and that a failure leaves the loan to retry |
| `test_settings_store.py` | 23 | Typed reads and writes over the key/value table |
| `test_auth.py` | 22 | Password hashing, JWT creation and the auth dependencies |
| `test_models.py` | 77 | Constraints, defaults, cascades, relationships, what may be switched into, that a collection is not a privacy boundary, and that the unfiltered-book-query walk sees a query for one column as well as for a row, cannot be laundered by a binding in another function, by any binding form `symtable` knows about (including three an AST walk structurally cannot see), by a shadowing parameter or by a class body it never visited, reads its own exemption count out of its docstring, and that a quote's length ceilings are a CHECK rather than a `String(n)` SQLite ignores |
| `test_authors.py` | 45 | Splitting a credit line, the key that folds without asking against the one that only suggests, the index, the three suggestion rules, and the two bounds that keep them from being a plantable denial of service: a cap per bucket and a budget for the pass |
| `test_auth_backends_bindguard.py` | 20 | **The empty-password guards**, at all three layers |
| `test_ratelimit.py` | 22 | The sliding window, and the login/registration limits |
| `test_uploads.py` | 25 | Content-sniffed image validation and the size cap |
| `test_middleware.py` | 25 | Security headers, CSP contents, HSTS conditions |
| `test_main.py` | 57 | App wiring, tag seeding, the operationId guard, the overdue ticker's lifespan, what the built files say about being reused, the shell that has to answer a client route, and `SERVE_FRONTEND=false` taking both away |
| `test_house_rules.py` | 29 | **Defects a person found four times.** Every caller-supplied row id bounded at both ends, whether it arrives as a query parameter, a path parameter or a body field; that the guards themselves can fail, including on a shared alias that lost its ceiling; that the bounds actually refuse, per route; that a provenance column stays unread, and that the stated model counts are recomputed rather than believed |
| `test_serialisation.py` | 35 | Assembling `BookOut`: the per-request fields, the tag suggestion by caption and by DDC number, that the copy count and the collection name each cost one statement for a page rather than one per book, and that the statement count stated in the docstring is the one measured |
| `test_schema.py` | 40 | Alembic: create, adopt a pre-Alembic database, upgrade, and that two table rewrites left their partial unique indexes partial |
| `test_database.py` | 27 | Engine setup and the session dependency |
| `routers/test_books_bulk.py` | 27 | One verb applied to a selection, and the three-way count |
| `routers/test_collections.py` | 19 | **Shelving, never permission.** Naming a part of the shelf, the case-insensitive uniqueness the database enforces, counts filtered to the caller, and a delete that unfiles rather than destroys |
| `routers/test_books_collections.py` | 33 | Filing a book, the two list parameters and the 422 for both at once, the bulk verb, the merge that absorbs a collection, and the export column |
| `routers/test_books_duplicates.py` | 31 | Duplicate detection and the merge, incl. the ORM cascade trap |
| `routers/test_books_classifications.py` | 28 | **A catalogue heading kept whole.** That the number survives the parse and a year does not become one, that a German caption still suggests a household tag, that the server writes no tag by itself, and that re-running enrichment, merging and purging each leave the right rows, including the per book ceiling that both capped writers of the table obey and the scheme ordering that decides what survives it |
| `routers/test_books_quotes.py` | 50 | **Passages copied out of a book.** The bounds on the excerpt, the remark and the page, reading order with the unpaged last, who may correct one, that a private book's quotes are 404, and that the cross-book listing filters its rows *and* its count |
| `routers/test_books_progress.py` | 29 | **The reading log.** One unit per entry, the promotion to reading, that a member never sees another's, and the merge that would otherwise cascade it away |
| `routers/test_books_reading.py` | 31 | Ratings, and the rules for stamping reading dates |
| `routers/test_books_series.py` | 28 | Series gaps, shelf locations, and partial detail edits |
| `routers/test_books_authors.py` | 47 | The author index and its privacy, the `?author=` filter, merging and reversing one, the household wide mapping against the filtered shelf, the flat map, and undoing a merge |
| `routers/test_books.py` | 107 | Listing, search, sorting, tagging, covers, notes, export, ownership |
| `routers/test_books_google.py` | 24 | Enrichment, the chosen-edition apply and that its body cannot overflow the database, candidates and that a record the schema refuses costs one heading rather than the whole response, the feature gate |
| `routers/test_books_search.py` | 37 | **Free-text search.** That it works with no API key, that all six catalogues answer, how they merge, that one record failing a bound costs one result rather than the response, and that a record carrying more headings than the ceiling loses the ninth rather than its whole row |
| `routers/test_books_trash.py` | 43 | **Undoing a delete.** That a trashed book leaves every view, comes back whole, and frees its ISBN again |
| `routers/test_settings.py` | 58 | Feature flags, the masked API key, the overdue webhook settings, admin-only writes |
| `routers/test_imports.py` | 43 | The import, the private-ISBN branch, the tag caps, the rate limit |
| `routers/test_books_tags.py` | 24 | **Two vocabularies in one table.** Who may create, who may delete, and the counts |
| `routers/test_auth.py` | 74 | Registration, login, `/auth/me`, the registration switch, and switching into a test account in all three modes |
| `routers/test_loans.py` | 57 | Lending, returning, history, and who may run the overdue digest |
| `routers/test_stats.py` | 37 | Every aggregation, and that each respects privacy |
| `routers/test_users.py` | 33 | The member list, test accounts, and appearance: the caller's own only, never on `UserOut` |

## The parts that matter most

**Authorization.** Before this suite existed, every one of these could be called by any
signed-in member against *any* book, including another member's private one:
`delete_book`, `add_book_tag`, `remove_book_tag`, `upload_cover`, `refresh_metadata`,
`update_status`, `get_notes`, `add_note`. `test_dependencies.py` exercises each from three
sides (the owner, another member, and a member acting on someone else's private book) and
asserts the private case reports **404, not 403**, because a 403 confirms the book exists.

**Privacy.** `visible_to()` must be applied by every query that returns or counts books.
Its absence is covered from several angles: listings, search, export, all four statistics
aggregations, and the loans list (which would otherwise disclose the title of a book the
caller cannot see, along with who has it).

**The N+1.** `test_dependencies.py::TestPagination` pins the paging contract. The query
count itself is measured separately, see *Not covered here* below.

**Errors.** That a crash returns a generic 500 and **never** a traceback; that unknown
`/api/*` paths answer JSON rather than falling through to the SPA; that `Retry-After` and
`WWW-Authenticate` survive the JSON error path.

**The empty-password guards** (`test_auth_backends_bindguard.py`). An LDAP bind with a DN
and a blank password is not a failed login. Most directories accept it as an anonymous bind
and return nothing, so the caller believes it is connected. Each of the three layers is
tested on its own, including the whitespace-only case and the startup refusal, because any
one of them could be removed by someone who thinks the other two make it redundant.

**Secrets are never echoed.** `test_books_google.py` asserts the API key does not appear in
the 400 that explains the key is missing, and that the *stored* value is unmasked. Masking
at rest instead of in the response would break every lookup while still looking right in the
settings screen.

**Ownership stays separate from read status.** `routers/test_books.py::TestOwnership` and
`routers/test_imports.py` pin that a scanned book is `owned`, that a Goodreads import
produces `unknown`, and that the bulk endpoint reports `skipped` for books the caller may
not modify rather than claiming success.

**The reading-date rules** (`routers/test_books_reading.py`). Dates are derived from
status transitions rather than typed, so each rule is pinned separately: re-selecting the
current status must not move a date that already records something true, going straight to
"read" stamps both ends, and moving back to unread clears them, or a book stays in "books
finished this year" forever.

**The merge cascade** (`routers/test_books_duplicates.py`). Repointing notes, quotes, loans and
statuses with a bulk `UPDATE` leaves the session's loaded collections stale, and the
`db.delete()` that follows cascades straight through them, deleting exactly what was just
moved. Four tests cover the rows surviving a merge, and one covers the unique-index
ordering that made an absorbed ISBN fail.

**The category separator.** `test_google_books.py` and `routers/test_books_google.py` both
pin that a category containing a comma ("Fiction, general") survives the round trip. It is a
one-character decision that silently shreds data if reversed.

## Deliberate gaps

The uncovered lines are defensive branches that are awkward to provoke and would cost more
in test complexity than they return:

- `main.py` (8): the `static/` mount, which only exists in a built image, and the
  duplicate-operationId guard's raise.
- `errors.py` (2): the fallback wording for a status with no entry in the presentation
  table.
- `routers/books.py` (5): narrow branches in the two metadata parsers, reached only by
  particular malformed upstream payloads.
- `routers/loans.py` (1), `schemas/common.py` (1): an unused convenience property and a
  guard clause.

Two things are **not** covered by choice:

- **Real network calls.** All four metadata sources are stubbed. A change in one of their
  response shapes will not be caught here; it would need a contract test against the live
  service, which would then fail whenever they have an outage. The fixtures are trimmed
  copies of real responses, including the awkward parts (a qualified 020, an ISBN-10 in a
  record found by ISBN-13, a title statement holding another book's title), because those
  are what the parsers exist for.
- **A real directory.** `ldap3`'s connection is stubbed, so the LDAP tests pin our filter
  construction, bind sequence and guards, not any particular server's behaviour. Verifying
  against a real OpenLDAP would be an integration test with a container, and a different
  kind of investment.
- **Concurrency.** Nothing exercises two simultaneous writers. SQLite and a household-sized
  workload make this a poor investment; it would matter if the app ever moved to a
  multi-worker deployment.

## Conventions

- One behaviour per test, named as a sentence about behaviour.
- Comment the non-obvious ones. Where a test encodes a trap (route ordering, SQLite's
  second-resolution timestamps, the bcrypt 72-byte limit) the comment is what stops
  someone "simplifying" the guard away later.
- Document real behaviour, even when it is a wart:
  `test_passwords_differing_past_the_limit_collide` asserts that bcrypt ignores everything
  past 72 bytes. That is true, surprising, and better pinned than pretended away.
- Account fixtures insert rows directly rather than calling `/auth/register`: bcrypt is
  deliberately slow and most tests need an account. The registration and hashing paths are
  still covered end-to-end in `test_auth.py` and `routers/test_auth.py`.
