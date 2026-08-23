# Backend test coverage

**1694 tests.** Line coverage was last measured at **96%** (4303 statements, 186
missed) when the suite held 1571, which is 123 tests ago, and has not been re-measured since: the gate runs
`pytest` without `--cov`, and a percentage carried forward across 63 new tests is a
number that looks measured and is not.

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
| `test_config.py` | 41 | Settings resolution, the startup secret guard, upload limits |
| `test_isbn.py` | 37 | Parsing, check digits, ISBN-10 to ISBN-13, the equivalent forms |
| `test_backup.py` | 56 | **The whole library out and back.** Round trip, refusing a bad archive, zip path traversal, and that an archive written before a table existed still restores |
| `test_metadata.py` | 82 | **The catalogue chain.** Source ranking, the merge, the cross-reference guards, denoising, the relevance ranking, the search deadline, outcomes, the cache |
| `test_errors.py` | 38 | Content-negotiated errors, the 500 handler, API-vs-SPA routing |
| `test_auth_backends.py` | 60 | Local, LDAP and proxy identity sources, and that a directory identity never adopts a test account |
| `test_csv_import.py` | 60 | **Reading anybody's export.** One real shape per service, and the awkward part of each |
| `test_schemas.py` | 46 | Request/response contracts and their validation rules |
| `test_google_books.py` | 37 | Volume mapping, the gap-filling merge, upstream failures |
| `test_notifications.py` | 39 | **The overdue digest.** Selection and the reminder interval, that a private book never reaches the wire, the signature, redirects refused, and that a failure leaves the loan to retry |
| `test_settings_store.py` | 23 | Typed reads and writes over the key/value table |
| `test_auth.py` | 22 | Password hashing, JWT creation and the auth dependencies |
| `test_models.py` | 44 | Constraints, defaults, cascades, relationships, and what may be switched into |
| `test_auth_backends_bindguard.py` | 20 | **The empty-password guards**, at all three layers |
| `test_ratelimit.py` | 22 | The sliding window, and the login/registration limits |
| `test_uploads.py` | 24 | Content-sniffed image validation and the size cap |
| `test_middleware.py` | 25 | Security headers, CSP contents, HSTS conditions |
| `test_main.py` | 28 | App wiring, tag seeding, the operationId guard, the overdue ticker's lifespan |
| `test_schema.py` | 34 | Alembic: create, adopt a pre-Alembic database, upgrade |
| `test_database.py` | 16 | Engine setup and the session dependency |
| `routers/test_books_bulk.py` | 27 | One verb applied to a selection, and the three-way count |
| `routers/test_books_duplicates.py` | 31 | Duplicate detection and the merge, incl. the ORM cascade trap |
| `routers/test_books_progress.py` | 29 | **The reading log.** One unit per entry, the promotion to reading, that a member never sees another's, and the merge that would otherwise cascade it away |
| `routers/test_books_reading.py` | 29 | Ratings, and the rules for stamping reading dates |
| `routers/test_books_series.py` | 28 | Series gaps, shelf locations, and partial detail edits |
| `routers/test_books.py` | 107 | Listing, search, sorting, tagging, covers, notes, export, ownership |
| `routers/test_books_google.py` | 20 | Enrichment, the chosen-edition apply, candidates, the feature gate |
| `routers/test_books_search.py` | 31 | **Free-text search.** That it works with no API key, that all six catalogues answer, and how they merge |
| `routers/test_books_trash.py` | 43 | **Undoing a delete.** That a trashed book leaves every view, comes back whole, and frees its ISBN again |
| `routers/test_settings.py` | 55 | Feature flags, the masked API key, the overdue webhook settings, admin-only writes |
| `routers/test_imports.py` | 43 | The import, the private-ISBN branch, the tag caps, the rate limit |
| `routers/test_books_tags.py` | 24 | **Two vocabularies in one table.** Who may create, who may delete, and the counts |
| `routers/test_auth.py` | 74 | Registration, login, `/auth/me`, the registration switch, and switching into a test account in all three modes |
| `routers/test_loans.py` | 48 | Lending, returning, history, and who may run the overdue digest |
| `routers/test_stats.py` | 33 | Every aggregation, and that each respects privacy |
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

**The merge cascade** (`routers/test_books_duplicates.py`). Repointing notes, loans and
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
