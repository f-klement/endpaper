# Backend test coverage

**4786 tests**, in 79 files, recounted from a `--collect-only` run on 2026-09-05, and equal to the `4786 passed` the gate reported on the same commit.

**The rows sum to 4759, twenty seven short, and the twenty seven are deliberate.** They belong to **three** files of tests of scripts under a directory the public mirror strips, so both files are on the `DENY` list and this register may not name them: a published file pointing at a stripped path fails the publish gate, which is how the first omission was found rather than chosen, and a critic confirmed the second the same way by planting the name and watching the gate refuse. The gap was eleven while there was one such file, the second arrived on 2026-09-02 with eleven tests of its own, it gained two more the same day when the regeneration wrapper grew a refusal, and a third file arrived on 2026-09-03 with three, taking the gap to twenty seven; **the number in this sentence moves whenever one of them gains a test, and it is not derivable from anything below.** **The gap is stated rather than hidden**, which is the same arrangement the frontend register already uses for a different reason. Recount the headline with the command, and expect the rows to fall short by exactly those three files. **The per file figures below are collected tests, so they sum to the headline exactly**, and that is the check: `pytest --collect-only -q` prints a count per file, and the total must equal the number above. They are not `def test_` lines, which come to 3777, recounted 2026-09-03, because a parametrised case is one line and several tests, which is why the collected figure is the **larger** of the two. **That figure was 2788 and stale by 638 when this register was recounted for the wave that added the National Library of Greece**: the headline and every row were re-derived and the sentence stating what they are *not* was read past. Recount both, or the distinction this paragraph exists to make is drawn against a number from a different suite.

That distinction was not stated before 2026-08-28 and the column had drifted into a mixture of the two. Recounted whole on that day: **17 rows were wrong in both directions**, `test_catalogue.py` had no row at all, and the headline was stale by 124. Recount with the command rather than adjusting a row by arithmetic. **And re-derive a count here, never copy one from a handoff**: three counts in this register were wrong in one wave, each written down correctly and then left behind by the work it described. A number that arrives in a report has already stopped being a measurement. Line coverage was last measured at **96%** (4303 statements,
186 missed) when the suite held 1571, which is 787 tests ago, and has not been re-measured
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

Nothing here touches the network or a real database. Outbound calls to all nine metadata
catalogues (Open Library, K10plus, the DNB, the OENB, the BnF, the Library of Congress,
the NLG, the NKP and Google Books) are intercepted with `respx` through `tests.helpers.silence_catalogues`; the database is a
throwaway SQLite file that is dropped and recreated between tests.

`conftest.refuse_unmocked_network` is autouse and empty, so **no test can reach the
internet**. Seven existing tests began making real requests to lobid the moment
`POST /authors/identifiers` grew one, and nothing in the suite would have said so. A nested
`respx.mock` inside a test still works. It makes the suite hermetic rather than loud:
`authority._lobid` catches bare `Exception`, so a forgotten mock degrades to an empty answer
rather than a red test.

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
| `test_isbn.py` | 57 | Parsing, check digits, ISBN-10 to ISBN-13, the equivalent forms |
| `test_ddc.py` | 29 | **Dewey headings.** That a number splits from its caption and a year does not, that the segmentation prime is stripped rather than rejected, that the projection reads the number, and that every mapped tag name is a tag that exists |
| `test_backup.py` | 76 | **The whole library out and back.** Round trip, refusing a bad archive, zip path traversal, and that an archive written before a table existed still restores. That the manifest carries every table in the metadata, compared by equality against `Base.metadata` rather than a hand-written list, which is why `author_aliases` went missing for as long as the author feature existed: the old assertion was a subset check named "every table". And that an author merge survives a round trip, which is the symptom that bug had, since a merge writes nothing to `books` |
| `test_marc.py` | 61 | **The MARCXML reader and writer.** That MARC is read through `metadata.py`'s parser rather than a second one, what the importer refuses that a lookup does not, the encodings refused at the door, that a record with no advisory identifier cannot be written, and that an ISBN the record qualifies survives an import while a cancelled one beside it does not hide it |
| `test_metadata.py` | 396 | **The catalogue chain.** Source ranking, the merge, the cross-reference guards, denoising, the relevance ranking, the search deadline, outcomes, the cache, that a classification keeps its number, its caption and its scheme, what a MARC record carries that a Dublin Core crosswalk had cleaned up (repeated subfields, non-sorting delimiters, decomposed text), and Open Library's three records: that its subjects never become classifications, that a key out of a response cannot move the host, that the edition cluster drops a translation, and that a Library of Congress subject heading keeps its subdivisions, refuses the other twenty two authorities in the same record and never reaches the Dewey parser. Plus the National Library of Greece: that a record whose only ISBN is qualified resolves, that one naming another ISBN is refused over a plaintext connection, that its Greek authority `$0` is not read as a GND number, and that the index its probe established is the one sent. And that **no order of the roster finds more books**, over all 5,040 permutations, parametrised on which source holds the book, with an anti vacuity assertion that the permutations reached `lookup` as different plans. Plus the not-a-book rule read off the record's own carrier codes rather than off prose: MARC's leader/06, `007` and `008/23`, the MODS form and the BnF `dc:type`, a 21 row table whose every code is pinned by a distinct row, that a record declaring a text carrier is a text so a scan beside a 19th century print is kept, and that the two Dublin Core sources keep a phrase because they carry no code |
| `test_errors.py` | 38 | Content-negotiated errors, the 500 handler, API-vs-SPA routing |
| `test_auth_backends.py` | 87 | Local, LDAP and proxy identity sources, and that a directory identity never adopts a test account |
| `test_csv_import.py` | 60 | **Reading anybody's export.** One real shape per service, and the awkward part of each |
| `test_schemas.py` | 64 | Request/response contracts and their validation rules |
| `test_google_books.py` | 41 | Volume mapping, the gap-filling merge, upstream failures, and that `merge_into` takes a `BookMatch` rather than a dictionary, pinned on the signature itself so a third call site inherits the bound |
| `test_notifications.py` | 126 | **The overdue digest.** Selection and the reminder interval, that a private book never reaches the wire, the signature, redirects refused, and that a failure leaves the loan to retry |
| `test_sources.py` | 94 | **The provider roster.** That off means not asked rather than deprioritised, that the stored order is the order sources are asked and not which is believed, and that a library with every source off refuses rather than answering nothing. The order now follows the measurement rather than the tuple: the tier rule, the tail rule, the budget's slack and the table's completeness, all derived from `sources.MEASURED` and recomputed from a committed 500 ISBN survey fixture, so the constants cannot drift from the evidence they were read off. The concentration rule is pinned by what it decides rather than by the count it holds: the union is computed with it on and off, and only the off arm demands a third concurrent request per lookup. It replaced a frame count, which the Czech catalogue passed by answering in six frames of ten while 49 of its 59 answers sat in one. The sample the pool is built from is derived from `MEASURED` rather than typed, because typing it once left that source out of every guard in the file |
| `test_targets.py` | 63 | **A catalogue as a row.** The seeded roster field by field, what a row may carry, and the two query builders, which are the only functions in the application that concatenate a value into a catalogue query. Holds the four guards the module cites by name, including that only the DNB waives the ISBN identity check and only the DNB is read for author identifiers |
| `test_settings_store.py` | 38 | Typed reads and writes over the key/value table |
| `test_auth.py` | 22 | Password hashing, JWT creation and the auth dependencies |
| `test_models.py` | 77 | Constraints, defaults, cascades, relationships, what may be switched into, that a collection is not a privacy boundary, and that a quote's length ceilings are a CHECK rather than a `String(n)` SQLite ignores. Plus the same CHECK in the other direction against the model built schema, and the refusal test's subject moved to a classification scheme, which cannot become a person's scheme, after `viaf` and then `blbnb` each became members on the same day |
| `test_importing.py` | 20 | **Applying a parsed export to a library.** The private-book oracle: a row whose ISBN belongs to a book the member cannot see is counted, never named, writes nothing, and does not stop the rest of the file, while the same ISBN on a book they *can* see is an ordinary match, because a difference in behaviour would be the oracle again. That reading records are personal and an existing rating is never overwritten; that a plain book list leaves no unread marker; that a file listing one book twice creates it once; the two measured tag caps and the truncate-before-the-cache-key ordering that once took a whole import down; that a tag already in the library is reused rather than re-inserted, including one with a non-ASCII capital, which used to raise and take the whole file down; and that the catalogue costs one SELECT per row rather than four |
| `test_authority.py` | 120 | **The network half of author identity.** That the four cross references a GND record carries are read off it, that the record's own scheme is never among them, and that a scheme the two files disagree about is shown and never offered for storage. That an ISNI disagreement is detected at all, which is the comparison `_disagreements` used to refuse to make. That a Library of Congress **subject** URI is not read as a person, and that a `sameAs` entry on any other host is not read as one of the four |
| `test_authorship.py` | 67 | **The database half of author identity.** That one read costs two statements and that a read after a write is not stale, which is what says there is no cache; that the module raises a domain error rather than an HTTP one; and the three rules the design rests on: a key is derived from the name and never chosen, removing one is allowed while no operation retypes one in place, and a key is per spelling so the kept spelling gets a row too. Plus resolution through a chain of folded names, and the privacy line on the alias table: the rows are library wide, but a spelling surviving only on somebody else's private book is not listed. Plus `record_cross_references`: that each scheme lands as its own row filed under the same key a confirmation uses, that the rows say a person asserted them, that a collision is reported rather than raised so the confirmation that succeeded is not undone, and that running it twice writes nothing the second time |
| `test_shelf.py` | 184 | The seam every many-book query goes through, and the only enforcement of the privacy rule since the AST guard was deleted. The house rule in **four** `ast` passes: no module but `shelf.py` imports a visibility predicate, none but `shelf.py` builds a query naming `Book`, none but `notifications.py` reaches `books` through a join, and nothing but ten counted statements across four modules reads a table that belongs only to a Book. Twenty three evasion shapes against the `Book` rule and thirty nine against the fourth pass, each asserted against the pass that must catch it, so deleting a pass fails a test. That the fourth pass **judges nothing**: it reports every read of `classifications`, `custom_field_values` and `book_tags`, two of the ten allowlisted statements being correct queries reported anyway, and a test keeps them reported so the cost is not quietly removed. That each allowlist entry is bound to its statement by a source fragment, so a reorder fails rather than shifting reasons. That both derivations are pinned: a ninth child of `books` fails until classified, and a floor of thirty eight reading methods is asserted against `dir(Query) | dir(Select)`, because a set that can grow silently can shrink silently. Who sees what; that no narrowing widens past the predicate, `select()` included; every listing filter and that `matching()` reads all thirteen; stable paging and the series null rule; and that the two named ways past a viewer are two rules rather than one hatch. And the route counts the `Loading` docstring states, recomputed rather than restated: each bucket asserted apart, the route universe derived from an HTTP verb decorator rather than a router's name, and the dependency resolved by following `Depends` to whichever link carries `load=Loading.SERIALISED`, after three enumerations in that one helper each went stale with the class green |
| `test_authors.py` | 45 | Splitting a credit line, the key that folds without asking against the one that only suggests, the index, the three suggestion rules, and the two bounds that keep them from being a plantable denial of service: a cap per bucket and a budget for the pass |
| `test_auth_backends_bindguard.py` | 20 | **The empty-password guards**, at all three layers |
| `test_ratelimit.py` | 37 | The sliding window, and the login/registration limits |
| `test_uploads.py` | 25 | Content-sniffed image validation and the size cap |
| `test_middleware.py` | 25 | Security headers, CSP contents, HSTS conditions |
| `test_main.py` | 59 | App wiring, tag seeding, the operationId guard, the overdue ticker's lifespan, what the built files say about being reused, the shell that has to answer a client route, and `SERVE_FRONTEND=false` taking both away |
| `test_house_rules.py` | 193 | **Defects a person found four times.** Every caller-supplied row id bounded at both ends, whether it arrives as a query parameter, a path parameter or a body field; that the guards themselves can fail, including on a shared alias that lost its ceiling; that the bounds actually refuse, per route; that a provenance column stays unread, that no comparison folds case in the database and in Python at once, and that the stated model counts are recomputed rather than believed. Plus the rule that an `HTTPException` is constructed where it is raised, with twelve shapes that share an instance and three that do not, each asserted individually, because a shared one grows its traceback forever and pins a `Session` and a `User` per refusal. And that only one helper turns `PRAGMA foreign_keys` off, because the pragma is set on the `connect` event rather than per checkout, so a pooled connection handed back with it off leaves the next test running with every foreign key unenforced: green file by file, and order dependent under `-n 2`. And that no module hard codes a source order, with `sources.MEASURED` exempted by name: nothing outside the test tree reads it, a plain tuple planted in the same module is still reported, and a mapping of measurements is guarded tree wide, so the exemption is one named hole rather than a licence. And that every published Markdown file has an even number of code fences, because two registers rendered as one code block from partway down after a wave folded a draft in with its own scaffolding, with nothing failing |
| `test_scratch_report.py` | 4 | **The scratch report names the filesystem the databases landed on.** `conftest._fastest_scratch()` falls back from `/dev/shm` to disk silently, so a run that lost tmpfs still passes and differs only in duration. Pins the text on both arms, rejects a directory that merely starts with the right characters, and pins the hook name: `-q` drops `pytest_report_header` and a `write_line` from `pytest_configure` lands too early, so only the summary hook reaches a CI log. |
| `test_roster_counts.py` | 59 | **A number spelled in prose, recomputed.** Every number written beside a roster noun across the backend, the docs that ship, the root Markdown and the frontend is found by a census and must carry a verdict: it names a cardinality computed from `sources.py` and is compared with it, or it records what the number counts instead, or it is a count nobody here could correct and is asserted to be **still** wrong so the entry clears itself when somebody fixes it. An unclassified candidate fails and a verdict judging nothing fails, so neither half can rot into the stale list it exists to prevent, and no count is written in the guard. The bound is derived: a candidate is in scope only if its value is one of the live cardinalities, and a roster set added to `sources.py` must be declared a cardinality or declared not to be a count. Plus the census's own reach, attacked rather than read: a claim wrapping across a line, a claim starting inside another, the digit form, and the paragraph rule that makes an anchor tell two sentences apart rather than merely exist. And two tests that recompute figures in the file's own docstring, because this guard's subject includes itself. And the verdict table audited from its own source, because a dict discards a duplicate key without a word: twenty one constructions driven one per test, eleven of them refused by a binding count that matches no node type at all, sweeping a `Store` on a name plus the fields that carry one as a string, against five controls that must still pass including a parameter and a nested local of that name, which bind in another scope and cannot reach the table. That eleven is itself recomputed by neutering the binding assertion in a copy of the module and re-driving every construction, because the figure had already been wrong twice. And that the known stale arm still reports, driven from a fixture because the live table now holds none of them and an empty table cannot show the rule works. And the register of decisions, read by the census since 2026-09-03 and pinned from both sides: that it is in scope and that a verdict judges something in it, so an inclusion with an empty table cannot pass as a working one, and that the sentence stating how its candidates split recomputes and sums |
| `schemas/test_book.py` | 32 | **Two request bodies writing one column must agree about it.** `BookMatch` bounded four of its seventeen fields while `merge_into` wrote them all, so the model an enrichment apply reaches was the loose one. Not a per field assertion, which is the enumeration this repository keeps paying for: every field naming a column both models write must carry the same bound in both, and every field a request body carries must have a ceiling at all. The container rule probes rather than reads, so a bare `list` and a `set`, `tuple` or `dict` are all judged by whether pydantic actually refuses an oversized value, and a constraint that cannot apply to the probe returns bounded rather than raising. Plus the collector that finds the body models, pinned by an equality against what the app itself walks, because a module test counting routes cannot put a floor under discovery |
| `schemas/test_settings.py` | 1 | **A row the router builds must carry every field the source describes.** The settings row is built by splatting the description into the response model, and pydantic drops an undeclared key in silence, which is how the slow marking reached the screen as nothing for one round while a test asserting on the description itself stayed green. The rule is the field sets, equal |
| `test_serialisation.py` | 46 | Assembling `BookOut`: the per-request fields, the tag suggestion by caption and by DDC number, that a tag name inside a longer word is not a caption match, that the copy count and the collection name each cost one statement for a page rather than one per book, and that the statement count stated in the docstring is the one measured |
| `test_schema.py` | 104 | Alembic: create, adopt a pre-Alembic database, upgrade, that two table rewrites left their partial unique indexes partial, that widening the classification number kept the unique index and the rows, and the revision that merges two collections whose names differ only in case: that the lower id survives, that every book lands on it, that none is left pointing at the row that was deleted, and that a database already holding such a row is refused with nothing changed. Plus that the migrated `ck_author_identifiers_scheme` accepts every member `AuthorityScheme` offers, which is the one model/migration drift `TestTheMigrationsAndTheModelsAgree` cannot see: it compares nullability and type per column and takes no view of a CHECK |
| `test_env_example.py` | 4 | **Operator documentation that goes stale silently.** That every environment name `config.py` reads appears in `.env.example` and nothing appears there that the code ignores, read off `config.py` rather than a hand written list, because a rule written as its instances regenerates the hole the moment the instances change. Plus a tripwire that the reader finds both places names are read, a direct `os.getenv` and the `_ENV_OVERRIDES` table, since finding one of two makes the other tests pass while enforcing half the rule |
| `test_database.py` | 27 | Engine setup and the session dependency |
| `test_fetch.py` | 61 | **The only door outwards.** That the body cap counts raw wire bytes and compression is never requested, because counting decoded bytes lets httpx expand a 65,250 byte gzip to 67,108,864 before the limit is consulted; that a `content-encoding` nobody asked for is refused on the header; that a redirect is walked here and only back to the same scheme, host and port, with a malformed `Location` host refused the same way, since httpx resolves it inside `send()` before the hop check can run; that the timeout bounds a whole request rather than each read; and an `ast` rule that no module outside three named ones builds an HTTP client, with seventeen evasion shapes and six correct spellings of the door pinned clean |
| `test_catalogue.py` | 161 | Folding what one source repeats, filling one row from another, merging two catalogues of one printing, how complete a record is, the two draft shapes, the headings a picked row confirms, that the fold runs once per set of collections, that authority assertions follow the collection rules, and that every scalar a record holds fits the Book column that stores it: the ceilings recomputed from the table rather than restated, the partition of bounded against deliberately unbounded asserted by contents and not only by coverage, and the one producer that truncates where every other drops |
| `test_filing.py` | 175 | **How each classification scheme's call numbers sort.** One rule per scheme answering four things: whether it recognises a number, the key that files it in Python, the same key in SQL, and whether a shelf may be ordered by it at all. That the two renderings of one key agree, evaluated against real SQLite over a generated corpus as well as a hand written one; that a Dewey number loses MARC's segmentation prime before filing so `005.13/3` and `005.133` file together; that a scheme with no rule of its own files as text and orders no shelf; and that a control character is refused at the door, NUL in particular, because SQLite's string functions stop at one where Python's do not and a single stored value would otherwise produce two keys |
| `test_z3950.py` | 78 | The Z39.50 door: the byte and time bounds enforced by construction, the error taxonomy that keeps **refused**, **unreachable** and **answered nothing** three different dispositions, PQF construction and its escaping, and the latch that stops a client reporting a closed port as zero hits |
| `test_z3950_provisional.py` | 38 | The provisional ctypes client behind that door: every ZOOM call declared against the signatures it really has, NULL checks, the single worker and its lock, and that importing the seam loads no shared library |
| `routers/test_public.py` | 51 | The first routes reachable without a session: the gate as a router dependency rather than per handler, that nothing under the prefix accepts a write, 404 never 403, the rate limit, and `X-Robots-Tag` on every response and not only the 200 |
| `schemas/test_public.py` | 25 | That the public payload is a total partition of `BookOut`, 18 published and 27 withheld with a reason each, and that no public model carries an alias, a computed field or a model serializer that would put a withheld column on the wire |
| `test_covers.py` | 110 | Fetching, sniffing, storing and serving a cover, the per-hop host allowlist, and the same wire-byte reading the catalogue path uses |
| `test_reading.py` | 56 | **The seam every reading record goes through.** That a record is private to its member separately from the book being visible; that rating a book and offering to discuss it deliberately stamp no dates; that a row created in the same request reads as unread rather than raising; the two named ways past a member, counted by call site; and an `ast` rule that only four modules import `UserBook`, with the star import from a re-exporter caught because those four modules are exactly the four that can launder the name |
| `test_custom_fields.py` | 106 | **Household defined fields on a book.** That every reader and writer takes `Book` objects rather than ids, enforced by three `ast` passes over the module's own tree rather than by a list, after a literal pair of examples passed while the shape it forbade was added beside it. That a url field's stored value names the host a browser will actually reach: a confusable separator is rewritten so the value and the destination agree, a percent escape in a host is refused because decoding is recursive, and a value the server never rewrote is served as text rather than as an anchor whose words and destination are two different domains. That `link_target` is idempotent, fuzzed over 24,841 inputs, which is what lets the read end compare a value to its target without costing a real link |
| `routers/test_books_custom_fields.py` | 44 | The six routes: defining, renaming, filling in, and that a field on a book the caller cannot see is 404 rather than 403 |
| `test_mailer.py` | 56 | **SMTP as a transport and its refusals.** That TLS cannot be switched off by any setting or environment variable, that a stripped STARTTLS raises rather than sending in the clear, that a header cannot be injected through an address, and that the password is absent from every repr |
| `routers/test_covers.py` | 34 | The cover routes: upload, fetch, serve, and the placeholder |
| `routers/test_books_copies.py` | 37 | Copy groups: creating, listing and the shared-edition rules |
| `routers/test_books_covers.py` | 27 | Cover routes hung off a book |
| `routers/test_books_lending.py` | 25 | Loans: lending, returning, the reminder interval and who may see a loan |
| `routers/test_books_bulk.py` | 32 | One verb applied to a selection, the three-way count, and that a row id past the largest a row can carry is a 404 rather than an `OverflowError` out of the driver, for each of the three verbs that read `value` as an id |
| `routers/test_collections.py` | 21 | **Shelving, never permission.** Naming a part of the shelf, the case-insensitive uniqueness the database enforces, in ASCII and outside it, counts filtered to the caller, and a delete that unfiles rather than destroys |
| `routers/test_books_collections.py` | 33 | Filing a book, the two list parameters and the 422 for both at once, the bulk verb, the merge that absorbs a collection, and the export column |
| `routers/test_books_duplicates.py` | 31 | Duplicate detection and the merge, incl. the ORM cascade trap |
| `routers/test_imports_marc.py` | 43 | **The import route.** Library mode enforced at 403, the file size ceiling, the preview counts and what each one discloses, that a matched Book never gains an ISBN, and the bounds the importer reads off the API's own declarations |
| `routers/test_books_classification_filter.py` | 26 | **Classifications as a facet, a filter and a shelf order.** Chiefly a privacy test: `classifications` carries no member, so a facet list with counts is the shape that discloses what is on other members' private books without returning one. Also the two operators (headings ANDed like tags, divisions ORed), that a heading carrying a comma or a colon survives the wire, and that Dewey orders while the unclassified sort last |
| `routers/test_books_classifications.py` | 36 | **A catalogue heading kept whole.** That the number survives the parse and a year does not become one, that a German caption still suggests a curated tag, that the server writes no tag by itself, that automatic enrichment and refresh leave headings unchanged, and that a selected record, merging and purging each leave the right rows, including the per book ceiling that both capped writers of the table obey and the scheme ordering that decides what survives it |
| `routers/test_books_quotes.py` | 50 | **Passages copied out of a book.** The bounds on the excerpt, the remark and the page, reading order with the unpaged last, who may correct one, that a private book's quotes are 404, and that the cross-book listing filters its rows *and* its count |
| `routers/test_books_progress.py` | 29 | **The reading log.** One unit per entry, the promotion to reading, that a member never sees another's, and the merge that would otherwise cascade it away |
| `routers/test_books_reading.py` | 31 | Ratings, and the rules for stamping reading dates |
| `routers/test_books_series.py` | 30 | Series gaps, shelf locations, partial detail edits, and that the gap range is truncated at `MAX_SERIES_INDEX`, pinned from both edges so neither a smaller ceiling nor a missing one passes |
| `routers/test_books_authors.py` | 95 | The author index and its privacy, the `?author=` filter, merging and reversing one, the library wide mapping against the filtered shelf, the flat map, and undoing a merge. Plus that confirming a GND number stores the four cross references beside it and lists them on the author, that a client cannot supply its own, that the authority file being unreachable does not fail the confirmation, that a scheme this application cannot resolve fetches nothing, and that a contested cross reference does not reach the table |
| `routers/test_books.py` | 113 | Listing, search, sorting, tagging, covers, notes, export, ownership |
| `routers/test_books_google.py` | 44 | Enrichment, the chosen-edition apply and that its body cannot overflow the database, candidates and that a record the schema refuses costs one heading rather than the whole response, that the work cluster is asked with the book's own ISBN, the feature gate . And that the automatic enrichment route bounds what a catalogue may write: a value too wide for its column costs that one field and the rest of the record still lands, where the neighbouring apply route refuses the identical value with a 422 |
| `routers/test_books_search.py` | 55 | **Free-text search.** That it works with no API key, that the six catalogues a reader would doubt answer do, how they merge, that one record failing a bound costs one result rather than the response, that a record carrying more headings than the ceiling loses the ninth rather than its whole row, and that a Library of Congress record's shelf classifications lead a row crowded with subject headings |
| `routers/test_books_trash.py` | 43 | **Undoing a delete.** That a trashed book leaves every view, comes back whole, and frees its ISBN again |
| `routers/test_settings.py` | 121 | Feature flags, the masked API key, the overdue webhook settings, admin-only writes |
| `routers/test_imports.py` | 47 | The import, the private-ISBN branch, the tag caps, the rate limit |
| `routers/test_books_tags.py` | 31 | **Two vocabularies in one table.** Who may create, who may delete, and the counts |
| `routers/test_auth.py` | 81 | Registration, login, `/auth/me`, the registration switch, switching into a test account in all three modes, and that an address given at registration is stored, normalised, bounded, refused when it is not one, and never served back |
| `routers/test_loans.py` | 75 | Lending, returning, history, who may run the overdue digest, and the overdue list a member reads: whose loans it holds, the in app switch that empties it, and that a page of it costs the same at three loans and at ten |
| `routers/test_stats.py` | 39 | Every aggregation, and that each respects privacy |
| `routers/test_users.py` | 72 | The member list, test accounts and the address an admin may set while creating one, appearance (the caller's own only, never on `UserOut`), and the account cases the address screen has to tell apart: local, a directory that supplies an address, a directory that does not, a row spelling `auth_source` as nothing this build knows, and the fourth combination the wire model can express and the server never produces |

## The parts that matter most

**Authorization.** Before this suite existed, every one of these could be called by any
signed-in member against *any* book, including another member's private one:
`delete_book`, `add_book_tag`, `remove_book_tag`, `upload_cover`, `refresh_metadata`,
`update_status`, `get_notes`, `add_note`. `test_dependencies.py` exercises each from three
sides (the owner, another member, and a member acting on someone else's private book) and
asserts the private case reports **404, not 403**, because a 403 confirms the book exists.

**Privacy.** Every query that returns or counts books is built through `shelf.py`, which
applies `visible_to()` by construction. Its absence is covered from several angles:
listings, search, export, all four statistics aggregations, and the loans list (which
would otherwise disclose the title of a book the caller cannot see, along with who has
it). `test_shelf.py` covers the seam itself, including that a narrowing cannot widen past
the predicate and that the two named ways past a viewer are not general escapes.

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
- **Concurrency.** Nothing exercises two simultaneous writers. SQLite and a library-sized
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
