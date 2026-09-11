# Backend test coverage

**6752 tests**, in 102 files, recounted with `--collect-only` on 2026-09-11.

**The headline equals the passed count today, and that is a fact about the tree rather than
a simplification.** The gate reports `6752 passed`, with no skip and no `xfail`: the strict
`xfail` that recorded a defect in the CSV importer is gone, because the work that closed the
defect closed it.

**Collected is the number this table sums to; passed is the number the gate prints.** They
differ by the count of open recorded defects **plus the skips**, **zero** here, so if they
ever differ by anything else, one of the two is wrong. **The rule is written with both terms
even though both are currently empty**, and that is deliberate twice over: stating it without
the skip once made the check undoable, and a rule rewritten as `collected == passed` while
the tree happens to have neither is one that fails for the wrong reason the day somebody adds
either.

**The rows below sum to 6703, forty nine short, and the shortfall is deliberate.** Those
tests live in six files on the publish gate's DENY list, which this published register may not
name: a published file pointing at a stripped path fails the gate. **The number moves whenever
one of those files gains a test and is not derivable from anything below.**

**The per file figures are collected tests, so they sum to the headline less that stated
shortfall**, and that is the check. They are not `def test_` lines, which come to fewer, because a parametrised case is
one line and several tests.

**Recount with the command; never adjust a row by arithmetic and never copy a figure from a
report.** Three counts in this register were wrong in one wave, each written correctly and then
left behind by the work it described.

Line coverage was last measured at **96%** when the suite held 1571 tests, and has not been
re-measured since: the gate runs `pytest` without `--cov`, so that percentage is a number which
looks measured and is not.

```bash
uv run pytest                                    # the suite
uv run pytest --cov --cov-report=term-missing    # coverage, with unhit lines
uv run pytest tests/test_dependencies.py -k private   # one area
```

The tree mirrors `backend/`: the tests for `routers/books.py` are at
`tests/routers/test_books.py`. Support files that mirror nothing (`conftest.py`,
`helpers.py`) sit at the root of the tree.

Nothing here touches the network or a real database. Every catalogue is intercepted with
`respx` through `tests.helpers.silence_catalogues`, and each test gets a throwaway SQLite file.

**`conftest.refuse_unmocked_network` is autouse, so no test can reach the internet.** It is
hermetic rather than loud on purpose: `authority._lobid` catches bare `Exception`, so a
forgotten mock degrades to an empty answer rather than a red test. Seven tests began making
real requests to lobid the moment one route grew one, and nothing in the suite said so.

**`silence_catalogues` is called last, and that is load bearing.** respx resolves routes in
registration order, first match wins, and a route whose pattern **equals** an existing one
replaces it rather than being appended, which silently discarded a test's own response. That is
why the helper uses regexes.

---

## What each file covers

| File | Tests | Covers |
|---|---:|---|
| `test_dependencies.py` | 44 | **Authorization and pagination.** The regression suite for the access-control holes described below |
| `test_config.py` | 52 | Settings resolution, the startup secret guard, upload limits, the frontend switch |
| `test_isbn.py` | 60 | Parsing, check digits, ISBN-10 to ISBN-13, the equivalent forms |
| `conformance/test_isbn.py` | 33 | **The Python half of the shared fixture set.** Holds no ISBN expectation of its own: `conformance/cases/isbn.json` is the specification, and this is a dispatch table plus the guards that stop the suite passing while testing nothing |
| `test_ddc.py` | 29 | **Dewey headings.** That a number splits from its caption and a year does not, that the segmentation prime is stripped rather than rejected, that the projection reads the number |
| `test_backup.py` | 119 | **The whole library out and back.** Round trip, refusing a bad archive, zip path traversal, and that an archive written before a table existed still restores. |
| `test_lending.py` | 17 | **The loan clock.** Overdue, days overdue and days out, each arm of each; that a returned loan stops counting at its return; that `days_out`'s clamp is the reachable one |
| `test_opds.py` | 94 | **The OPDS reader.** Which addresses this server will open, what one Atom entry becomes, the identifier the census says is not there, the doctype refusal, the decoder-on-a-file property, and the origin pin over paging. `TestNoResponseMovesTheOrigin` is the one to read first |
| `routers/test_opds.py` | 44 | **The OPDS routes.** The admin gate on configuration against a member's right to sync, the credential lifecycle, and that deleting a server or moving it to another origin takes its login with it |
| `test_marc.py` | 61 | **The MARCXML reader and writer.** That MARC is read through `metadata.py`'s parser rather than a second one, what the importer refuses that a lookup does not |
| `test_metadata.py` | 466 | **The catalogue chain.** Source ranking, the merge, the cross-reference guards, denoising, the relevance ranking, the search deadline, outcomes, the cache, that a stored login reaches the request it was stored for and no other, that every door needing one declares it, and which transport actually carries one |
| `test_errors.py` | 38 | Content-negotiated errors, the 500 handler, API-vs-SPA routing |
| `test_auth_backends.py` | 87 | Local, LDAP and proxy identity sources, and that a directory identity never adopts a test account |
| `test_csv_import.py` | 169 | **Reading anybody's export.** One real shape per service, and the awkward part of each |
| `test_schemas.py` | 66 | Request/response contracts and their validation rules |
| `test_google_books.py` | 41 | Volume mapping, the gap-filling merge, upstream failures, and that `merge_into` takes a `BookMatch` rather than a dictionary, pinned on the signature itself so a third call site inherits the bound |
| `test_notifications.py` | 129 | **The overdue digest.** Selection and the reminder interval, that a private book never reaches the wire, the signature, redirects refused, that a failure leaves the loan to retry |
| `test_sources.py` | 98 | **The provider roster.** That off means not asked rather than deprioritised, that the stored order is the order sources are asked and not which is believed, and the catalogue remit: a remit may only be declared for a source the committed sample measures, the Argentine frame cannot give that catalogue one, and the derived table holds the rows' own objects |
| `test_targets.py` | 71 | **A catalogue as a row.** The seeded roster field by field, what a row may carry, and the two query builders |
| `test_decoders.py` | 26 | **What a decoder is, and what it is never told.** The contract, a catalogue decoder reading a record off a file with no `Target`, and the two family refusal |
| `test_sru.py` | 205 | **The SRU server: the protocol, driven as a function over a query string.** That no index reaches a private or a trashed book |
| `test_settings_store.py` | 43 | Typed reads and writes over the key/value table |
| `test_credentials.py` | 262 | **Somebody else's login, sealed.** The envelope and its key generation, the three key sources, the recovery phrase and its checksum, the origin a credential is bound to, and the upgrade path: which sources may still open the superseded scheme, and the three instruments that end that acceptance |
| `test_auth.py` | 22 | Password hashing, JWT creation and the auth dependencies |
| `test_accounts.py` | 66 | **Recovery and confirmation, where the rules live rather than where they are served.** That one function builds a reset request so an admin can approve but never start one, that redeeming ends every session on the account, that a code is single use and expires, and that both branches of a resend cost the same. |
| `test_recover.py` | 7 | The command line reset, which is the path for a library whose only admin has nobody to approve their request. |
| `test_models.py` | 163 | Constraints, defaults, cascades, relationships, what may be switched into, that a collection is not a privacy boundary |
| `test_importing.py` | 39 | **Applying a parsed export to a library.** The private-book oracle: a row whose ISBN belongs to a book the member cannot see is counted, never named, writes nothing |
| `test_import_readers.py` | 16 | **What a reader IS, and that the set of them is closed.** That a reader is handed decoded text and nothing about how the file arrived, that every registered one honours a column correction, and that a service fitting the candidate names is names alone and no code. |
| `test_authority.py` | 120 | **The network half of author identity.** That the four cross references a GND record carries are read off it, that the record's own scheme is never among them |
| `test_authorship.py` | 107 | **The database half of author identity.** That one read costs two statements and that a read after a write is not stale |
| `test_shelf.py` | 224 | The seam every many-book query goes through, and the only enforcement of the privacy rule since the AST guard was deleted. |
| `test_nothing_private_leaves.py` | 34 | **The export boundary, and what still crosses it.** That only the shelf builds an outbound payload, a route sweep derived from the live route table, and the shapes the guards admit they cannot see |
| `test_no_custody.py` | 7 | **Nowhere to send a book file to.** Which routes accept an upload, as an equality in both directions with what each file is for, and that no mapped column carries bytes: the structural half of the promise that a book file is read in the browser and never uploaded |
| `test_authors.py` | 63 | Splitting a credit line, the key that folds without asking against the one that only suggests, the index, the four suggestion rules |
| `test_auth_backends_bindguard.py` | 20 | **The empty-password guards**, at all three layers |
| `test_ratelimit.py` | 37 | The sliding window, and the login/registration limits |
| `test_uploads.py` | 33 | Content-sniffed image validation and the size cap |
| `test_middleware.py` | 27 | Security headers, CSP contents, HSTS conditions |
| `test_main.py` | 59 | App wiring, tag seeding, the operationId guard, the overdue ticker's lifespan, what the built files say about being reused, the shell that has to answer a client route |
| `test_house_rules.py`                      |   279 | **Defects a person found four times.** Every caller-supplied row id bounded at both ends, whether it arrives as a query parameter. Also the one decision of what vendored code is: each of the five walks over this tree driven against a constructed tree with each kind of vendored path planted in front of it, and no other test module allowed to define a walk of its own |
| `test_scratch_report.py` | 4 | **The scratch report names the filesystem the databases landed on.** `conftest._fastest_scratch()` falls back from `/dev/shm` to disk silently |
| `test_roster_counts.py` | 78 | **A number spelled in prose, recomputed.** Every number written beside a roster noun is found by a census and must carry a verdict naming a cardinality computed from `sources.py`. The census walks the tree minus what a tool owns, so a new file is covered without anybody remembering, and it reads this register. |
| `schemas/test_book.py` | 39 | **Two request bodies writing one column must agree about it.** `BookMatch` bounded four of its seventeen fields while `merge_into` wrote them all |
| `schemas/test_settings.py` | 2 | **A row the router builds must carry every field the source describes.** The settings row is built by splatting the description into the response model |
| `test_serialisation.py` | 47 | Assembling `BookOut`: the per-request fields, the tag suggestion by caption and by DDC number, that a tag name inside a longer word is not a caption match |
| `test_schema.py`                           |   184 | Alembic: create, adopt a pre-Alembic database, upgrade, that two table rewrites left their partial unique indexes partial |
| `schemas/test_digital.py` | 31 | What a client may say about a file it holds, bounded at the schema: the root, the path beneath it and the fingerprint, each refused at its ceiling rather than trusted for its width |
| `test_env_example.py` | 4 | **Operator documentation that goes stale silently.** That every environment name `config.py` reads appears in `.env.example` and nothing appears there that the code ignores |
| `test_database.py` | 27 | Engine setup and the session dependency |
| `test_fetch.py` | 121 | **The only door outwards.** That the body cap counts raw wire bytes and compression is never requested |
| `test_catalogue.py` | 173 | Folding what one source repeats, filling one row from another, merging two catalogues of one printing, how complete a record is, the two draft shapes |
| `test_classifications.py` | 38 | **What a heading asserts, beside which file its number is in.** The kind a field carries, that a legacy row keeps its pair, and the derivation that counts the readers |
| `test_filing.py` | 238 | **How each classification scheme's call numbers sort.** One rule per scheme answering three things: whether it recognises a number, the key that files it |
| `test_z3950.py` | 78 | The Z39.50 door: the byte and time bounds enforced by construction, the taxonomy keeping **refused**, **unreachable** and **answered nothing** apart, and PQF escaping. |
| `test_z3950_provisional.py` | 38 | The provisional ctypes client behind that door: every ZOOM call declared against the signatures it really has, NULL checks, the single worker and its lock |
| `routers/test_public.py` | 51 | The first routes reachable without a session: the gate as a router dependency rather than per handler, that nothing under the prefix accepts a write, 404 never 403 |
| `schemas/test_public.py` | 25 | That the public payload is a total partition of `BookOut`, 18 published and 27 withheld with a reason each, and that no public model carries an alias |
| `test_covers.py` | 113 | Fetching, sniffing, storing and serving a cover, the per-hop host allowlist, and the same wire-byte reading the catalogue path uses |
| `test_reading.py` | 56 | **The seam every reading record goes through.** That a record is private to its member separately from the book being visible, and that rating a book or offering to discuss it stamps no dates. |
| `test_custom_fields.py` | 106 | **Household defined fields on a book.** That every reader and writer takes `Book` objects rather than ids |
| `routers/test_books_custom_fields.py` | 44 | The six routes: defining, renaming, filling in, and that a field on a book the caller cannot see is 404 rather than 403 |
| `test_mailer.py` | 56 | **SMTP as a transport and its refusals.** That TLS cannot be switched off by any setting or environment variable, that a stripped STARTTLS raises rather than sending in the clear |
| `routers/test_covers.py` | 40 | The cover routes: upload, fetch, serve, and the placeholder |
| `routers/test_books_copies.py` | 37 | Copy groups: creating, listing and the shared-edition rules |
| `routers/test_books_covers.py` | 27 | Cover routes hung off a book |
| `routers/test_books_lending.py` | 25 | Loans: lending, returning, the reminder interval and who may see a loan |
| `routers/test_books_bulk.py` | 32 | One verb applied to a selection, the three-way count, and that a row id past the largest a row can carry is a 404 rather than an `OverflowError` out of the driver |
| `routers/test_collections.py` | 21 | **Shelving, never permission.** Naming a part of the shelf, the case-insensitive uniqueness the database enforces, in ASCII and outside it, counts filtered to the caller |
| `routers/test_books_collections.py` | 33 | Filing a book, the two list parameters and the 422 for both at once, the bulk verb, the merge that absorbs a collection, and the export column |
| `routers/test_books_duplicates.py` | 32 | Duplicate detection and the merge, incl. the ORM cascade trap |
| `routers/test_books_notes.py` | 13 | A note's own visibility over the four note routes: a private note absent from another member's listing and from an admin's, 404 rather than 403 on edit and delete for anybody but its author, and an edit that does not mention the flag leaving it alone |
| `routers/test_books_digital_references.py` | 44 | The four routes a client uses to say where a book's file is: only the member's own references, a sighting that refreshes the fingerprint, a miss that flags the row rather than deleting it, and a book the caller cannot see answering 404 |
| `routers/test_imports_marc.py` | 43 | **The import route.** Library mode enforced at 403, the file size ceiling, the preview counts and what each one discloses, that a matched Book never gains an ISBN |
| `routers/test_books_classification_filter.py` | 29 | **Filtering by classification, and the order it comes back in.** Chiefly a privacy test: `classifications` carries no member column, so the filter is only as private as the shelf in front of it. |
| `routers/test_books_classifications.py` | 36 | **A catalogue heading kept whole.** That the number survives the parse and a year does not become one, that a German caption still suggests a curated tag |
| `routers/test_books_quotes.py` | 50 | **Passages copied out of a book.** The bounds on the excerpt, the remark and the page, reading order with the unpaged last, who may correct one |
| `routers/test_books_progress.py` | 29 | **The reading log.** One unit per entry, the promotion to reading, that a member never sees another's, and the merge that would otherwise cascade it away |
| `routers/test_books_reading.py` | 31 | Ratings, and the rules for stamping reading dates |
| `routers/test_books_series.py` | 30 | Series gaps, shelf locations, partial detail edits, and that the gap range is truncated at `MAX_SERIES_INDEX`, pinned from both edges so neither a smaller ceiling nor a missing one passes |
| `routers/test_books_authors.py` | 110 | The author index and its privacy, the `?author=` filter, merging and reversing one, the library wide mapping against the filtered shelf, the flat map, and undoing a merge. |
| `routers/test_books.py`                    |   127 | Listing, search, sorting, tagging, covers, notes, export, ownership, and that a login this deployment holds leaves with the request that needs it |
| `routers/test_books_identifiers.py`        |    28 | The identifier a store knows a book by, over the API: written with the book, read back on it, refused where the scheme is not one this app names, bounded so a payload cannot carry an unbounded list, and removed by any member who may write the book, where an invisible book and one belonging to somebody else are both 404 |
| `schemas/test_identifier.py`               |    17 | What a store identifier may contain, at the door: the character classes refused, which are whitespace and both invisible Unicode categories, checked as the same set the client filter refuses rather than against examples |
| `test_identifiers.py`                      |    10 | Writing identifiers onto a book: duplicates within one payload dropped rather than refused, because a client reading two of its own files may find one book in both, and the repoint a merge performs |
| `routers/test_books_google.py` | 44 | Enrichment, the chosen-edition apply and that its body cannot overflow the database |
| `routers/test_books_search.py` | 55 | **Free-text search.** That it works with no API key, that the six catalogues a reader would doubt answer do, how they merge |
| `routers/test_books_trash.py` | 43 | **Undoing a delete.** That a trashed book leaves every view, comes back whole, and frees its ISBN again |
| `routers/test_settings.py` | 173 | Feature flags, the masked API key, the overdue webhook settings, admin-only writes |
| `routers/test_imports.py` | 61 | The import, the private-ISBN branch, the tag caps, the rate limit, and the round trip: that every column of the live export is read back or named as unread, that each one lands in the field named for it, and that every importer field is filled or named as absent |
| `routers/test_books_tags.py` | 31 | **Two vocabularies in one table.** Who may create, who may delete, and the counts |
| `routers/test_auth.py` | 81 | Registration, login, `/auth/me`, the registration switch, switching into a test account in all three modes, and that an address given at registration is stored, normalised |
| `routers/test_loans.py` | 95 | Lending, returning, history, who may run the overdue digest, and the overdue list a member reads: whose loans it holds, the in app switch that empties it |
| `routers/test_sru.py` | 35 | **The gate in front of the protocol.** That the endpoint does not exist until both switches are on, that turning library mode back off closes it |
| `routers/test_stats.py` | 39 | Every aggregation, and that each respects privacy |
| `routers/test_users.py` | 72 | The member list, test accounts and the address an admin may set while creating one, appearance (the caller's own only, never on `UserOut`) |

## The parts that matter most

**Authorization.** Eight book routes were once callable by any signed in member against any
book, including another member's private one. `test_dependencies.py` exercises each from three
sides, owner, other member, and a member acting on somebody else's private book, and asserts
the private case reports **404, not 403**.

**Privacy.** Every query returning or counting books is built through `shelf.py`. Its absence
is covered from listings, search, export, all four statistics aggregations, and the loans list,
which would otherwise disclose the title of a book the caller cannot see.

**The N+1.** `test_dependencies.py::TestPagination` pins the paging contract, and the listing
statement counts are asserted rather than described.

**Errors.** A crash returns a generic 500 and **never** a traceback.

**Secrets are never echoed**, asserted on the response body and on the logs.

**Ownership stays separate from read status**, and the reading date rules are derived rather
than stored by the client.

## Deliberate gaps

- `main.py`: the `static/` mount, which only exists in a built image.
- `errors.py`: the fallback wording for a status with no presentation entry.
- `routers/books.py`: narrow branches in the two metadata parsers, reached only by a shape no
  live catalogue has produced.
- **Real network calls.** Every catalogue is stubbed, so a change in one of their responses is
  invisible here and shows up in production.
- **A real directory.** `ldap3`'s connection is stubbed, so the LDAP tests pin our filter and
  our handling, not a server's behaviour.
- **Concurrency.** Nothing exercises two simultaneous writers.

## Conventions

- One behaviour per test, named as a sentence about behaviour.
- Where a test encodes a trap, the comment says what breaks without it.
- Document real behaviour even when it is a wart: bcrypt ignoring everything past 72 bytes is
  pinned rather than pretended away.
- Account fixtures insert rows directly rather than calling `/auth/register`, because bcrypt is
  deliberately slow and most tests need an account. The registration path is still covered end
  to end in the auth tests.