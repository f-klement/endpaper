# Backend test coverage

<!-- measured: begin -->

**10455 tests, in 148 files**, counted by the run that reads this line.
**The 129 rows below sum to 9273.**
The other 1182 tests are in 21 files this register may not name.
The table also carries 2 files this engine does not run, stated as 0.
<!-- measured: end -->

**Those figures are generated and nothing here is recounted by hand.**
`test_coverage_register.py` renders that block from the collection the suite is executing,
and fails when this document disagrees with it, row by row and file by file. There is no
date beside the numbers, because a figure a run recomputes has nothing to be as of. Three
parties recounted this register by hand in two days and each left a different one wrong;
the last was 102 out on the headline, in a commit saying two instruments agreed on it.

**The files with no row are ones this published register may not name.** The publish gate
strips them, and a published file that points at a stripped path fails the gate. Which
files those are is not a list kept here either: a collected file either carries a row or
declares itself internal, the gate refuses to publish anything carrying that declaration,
and the guard reads the declaration rather than any list of names. So a new test file has
three destinations, a row here, the strip list, or a row of 0 where this engine cannot run
it, and one that takes none of them fails by name.

**Collected is what the rows sum to; passed is what the gate prints.** They differ by the
skips among collected items plus the open recorded defects, both zero, and
`test_nothing_collected_is_skipped_or_left_expected_to_fail` is what keeps them so.
**Among collected items is the load bearing half of that clause.** The gate also prints a
skip for a module that ends its own collection, which is the file this table states as 0;
that module is never collected, so it is in neither the sum nor this equality. Drop those
three words and the sentence reads as a claim about the gate's own skip line, which is 1,
and the next reader corrects a figure that was right. **The
rule is written with both terms even though both are empty**, deliberately: stating it
without the skip once made the check undoable, and rewriting it as `collected == passed`
while the tree happens to have neither is a rule that fails for the wrong reason the day
somebody adds either.

**To count from outside the suite**, `--collect-only -q` through the runner prints one
`path: count` line per file. It prints no node ids, because this project's `addopts`
carries `-q` and the runner adds another; an earlier note here concluded from that that it
answers "nothing to count", which is wrong and cost a recount.

**The per file figures are collected tests**, not `def test_` lines, which come to fewer
because a parametrised case is one line and several tests.

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
`helpers.py`, `strategies.py`) sit at the root of the tree. `strategies.py` holds the
generators more than one property based test draws from, and the witness that proves a
generator still reaches the class its property is about.

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
| `test_isbn.py` | 79 | Parsing, check digits, ISBN-10 to ISBN-13, the equivalent forms, that a catalogue's own qualifier is the MARC reader's problem and not this module's, and the same rules as properties over generated input: that a check digit is the only one that completes its body, that parsing is idempotent and answers None or thirteen ASCII Bookland digits, and that inserting any character `normalise` discards changes nothing |
| `conformance/test_isbn.py` | 34 | **The Python half of the shared fixture set.** Holds no ISBN expectation of its own: `conformance/cases/isbn.json` is the specification, and this is a dispatch table plus the guards that stop the suite passing while testing nothing |
| `conformance/test_subject.py` | 43 | The shared subject cases, run against the server's own per entry rule. Both the absolute arm and the equality arm, plus the guards that stop the file passing while testing nothing: the floor, the outcome partition, the guard dropping table in `conformance/subject.md`, and that every domain in the case directory has a runner on both sides |
| `test_ddc.py` | 29 | **Dewey headings.** That a number splits from its caption and a year does not, that the segmentation prime is stripped rather than rejected, that the projection reads the number |
| `test_backup.py` | 181 | **The whole library out and back.** Round trip, refusing a bad archive, zip path traversal, and that an archive written before a table existed still restores. |
| `test_lending.py` | 42 | **The loan clock.** Overdue, days overdue and days out, each arm of each; that a returned loan stops counting at its return; that `days_out`'s clamp is the reachable one |
| `test_opds.py` | 106 | **The OPDS reader.** Which addresses this server will open, what one Atom entry becomes, the identifier the census says is not there, the doctype refusal, the decoder-on-a-file property, and the origin pin over paging. `TestNoResponseMovesTheOrigin` is the one to read first |
| `routers/test_opds.py` | 44 | **The OPDS routes.** The admin gate on configuration against a member's right to sync, the credential lifecycle, and that deleting a server or moving it to another origin takes its login with it |
| `test_bibliographic.py` | 103 | **What a bibliographic value means, with no record and no transport.** Every rule on its own, that the two language tables are one table inverted, and that only the four carrier aware doors reach the prose refusal, and that the catalogue order flip counts commas after the noise strip and takes a terminal full stop only on the branch that reorders a name, and that a role word standing as the surname is the name rather than the designation a catalogue appends, with the two shapes that stay outside that rule named, and, over generated input, that every rule here answers for any string at all, that a title is quoted from the record rather than rewritten, and that the disc half and the not a book half are still one refusal |
| `test_marc.py` | 83 | **The MARCXML reader and writer.** That MARC is read through `metadata.py`'s parser rather than a second one, what the importer refuses that a lookup does not, that an ISBN qualified inside its own subfield still reaches the importer's primary match key, and that every column it writes out of a record is a fact about the work, so a name that is not one cannot be written on a create and skipped on a match, and that a heading says what the citing record was asserting with it, so a carrier leaves in the genre or form field rather than as a subject |
| `test_marc_fields.py` | 86 | **What a MARC21 datafield and subfield spell.** The subfield reader and its repeats, the vocabulary a heading declares and the kind it asserts, the authority identifier, which added entry wrote the book, the component part refusal, and the carrier codes that decide a book from a recording. The two `020` readers, which state a number and count a parenthesis as qualification, and what that rule deliberately does not reach. Seven classes moved out of `test_metadata.py` with the module, plus the namespace having one definition, `Fields` carrying the record it parsed, the 245 field picked in one place, and an absent tag reading as no fields |
| `test_metadata.py` | 438 | **The catalogue chain.** Source ranking, the merge, the cross-reference guards, denoising, the relevance ranking, the search deadline, outcomes, the cache, that a stored login reaches the request it was stored for and no other, that every door needing one declares it, and which transport actually carries one |
| `test_catalogue_access.py` | 43 | **The bounds of the catalogue access door.** That one module reaches `metadata`'s outbound doors and one module constructs an `Access`, that `GoogleVolumes` stays one method and two fields wide, that no refusal is built from a value, that no public type prints a secret, that the module reaches no query builder, that each constructor charges its own limiter, that a locally refused request spends no budget, and that no route answers a refusal to a caller with no session |
| `test_errors.py` | 54 | Content-negotiated errors, the 500 handler, API-vs-SPA routing, and that no hand raised refusal uses a status the schema declares with an array detail, and that a crash is logged once, by the app, a validation or database error's without the value, measured on the server the image runs |
| `test_auth_backends.py` | 100 | Local, LDAP and proxy identity sources, and that a directory identity never adopts a test account |
| `test_csv_import.py` | 170 | **Reading anybody's export.** One real shape per service, and the awkward part of each |
| `test_schemas.py` | 69 | Request/response contracts and their validation rules |
| `test_google_books.py` | 111 | Volume mapping, the gap-filling merge, upstream failures, and that `merge_into` takes a `BookMatch` rather than a dictionary, pinned on the signature itself so a third call site inherits the bound. Also the join onto `books.categories`: a subject carrying the separator the column is joined on is dropped there rather than refused, driven by a list holding two such subjects among four and by a volume whose only category holds one, and the count is capped at the join with the two offending subjects at the front, so truncating before dropping answers short. And that the parenthesised series is read in one pass, held to the expression it replaced over generated titles, and that a series number in another script's digits is not read |
| `test_notifications.py` | 163 | **The overdue digest.** Selection and the reminder interval, that a private book never reaches the wire, the signature, redirects refused, that a failure leaves the loan to retry, that one sender failing in any way neither stops the others nor skips the stamp, is broken at once, and logs its type and frames but never its message, that an address the URL parser would raise on is refused at the send, and that a path the parse reads as a host is logged as unknown |
| `test_sources.py` | 100 | **The provider roster.** That off means not asked rather than deprioritised, that the stored order is the order sources are asked and not which is believed, and the catalogue remit: a remit may only be declared for a source the committed sample measures, the Argentine frame cannot give that catalogue one, and the derived table holds the rows' own objects, plus that every seeded target answers something, which is what makes the refusal when nothing is asked derivable rather than true by coincidence of the seed data |
| `test_tags.py` | 88 | **The one place a tag is decided from a name.** That nothing outside the mint and the seed constructs one, read by two instruments that go blind on different shapes, with a twenty nine row battery naming what each sees; which of a case differing pair wins; the normaliser the route and the import now share; and the ceiling on one Book, held against the single route and the bulk verb |
| `test_targets.py` | 94 | **A catalogue as a row.** The seeded roster field by field, what a row may carry, and the two query builders |
| `test_decoders.py` | 69 | **What a decoder is, and what it is never told.** The contract, a catalogue decoder reading a record off a file with no `Target`, and the two family refusal and that the catalogue family's published table covers every reader a search can name |
| `test_sru.py` | 228 | **The SRU server: the protocol, driven as a function over a query string.** That no index reaches a private or a trashed book, that parsing any string at all answers with a tree or a diagnostic and never a third thing, and that an escaped term matches its own characters and nothing else, judged by SQLite itself |
| `test_settings_store.py` | 123 | Typed reads and writes over the key/value table, and that a setting the environment pins is read where it is pinned: every reader the corpus spells, including one reached as an attribute on a module that imported it, and that the plan and the logins agree on which sources need one, so a source cannot sit in the plan with no login resolved for it, and that a stored row nested past the parser's stack degrades |
| `test_credentials.py` | 275 | **Somebody else's login, sealed.** The envelope and its key generation, the three key sources, the recovery phrase and its checksum, the origin a credential is bound to, and the upgrade path: which sources may still open the superseded scheme, and the three instruments that end that acceptance |
| `test_auth.py` | 22 | Password hashing, JWT creation and the auth dependencies |
| `test_accounts.py` | 68 | **Recovery and confirmation, where the rules live rather than where they are served.** That one function builds a reset request so an admin can approve but never start one, that redeeming ends every session on the account, that a code is single use and expires, and that both branches of a resend cost the same. |
| `test_recover.py` | 7 | The command line reset, which is the path for a library whose only admin has nobody to approve their request. |
| `test_enums.py` | 18 | **The read end of an unconstrained enum column**, as a table of `(enum, stored) -> member | default` with no session and no HTTP, and that a stray value is logged with what it was |
| `test_logvalues.py` | 12 | **The bound on what an untrusted value logs.** That the clip is on the repr rather than the value, that a newline cannot forge a second line, and that a poisoned column read through a page logs one bounded record rather than its own length |
| `test_models.py` | 179 | Constraints, defaults, cascades, relationships, what may be switched into, that a collection is not a privacy boundary |
| `test_downloads.py` | 5 | **The two facts both download routes share.** That the saved filename's day is UTC rather than whichever zone the host happens to be set to, driven nine hours east of Greenwich at an instant just past local midnight, with two further arms that refuse the run when the zone did not take, because an offset comparison is armed on a developer's machine and inert in the container where the suite runs; and the attachment header both routes send. |
| `test_dialect_portability.py` | 58 | That the month bucket renders per dialect and refuses a third, that both statistics buckets reach Postgres as `to_char` with no `strftime` left, and that both dialects render the same predicate for every index in the schema |
| `test_importing.py` | 141 | **Applying a parsed export to a library.** The private-book oracle: a row whose ISBN belongs to a book the member cannot see is counted, never named, writes nothing; that the second bound `stored_record` applies returns the documented value on each side of every bound, with the case generator asserting its own coverage so a lost branch is red rather than quietly narrower; that the two ceiling tables agree per name, which is what keeps the rebuild a truncation rather than a drop; and that no importer reaches a column off the tuple both its writers walk, with the record's own type minted in one place; and that a bound stating how many entries a list may hold is not read as a character width, driven by a 200 character value on the container field with the second reading agreeing about it and about a title still cut to its own width |
| `test_import_readers.py` | 16 | **What a reader IS, and that the set of them is closed.** That a reader is handed decoded text and nothing about how the file arrived, that every registered one honours a column correction, and that a service fitting the candidate names is names alone and no code. |
| `test_authority.py` | 121 | **The network half of author identity.** That the four cross references a GND record carries are read off it, that the record's own scheme is never among them |
| `test_authorship.py` | 107 | **The database half of author identity.** That one read costs two statements and that a read after a write is not stale |
| `test_identity.py` | 97 | **What makes two books the same book.** One fold over a title and one over a credit, and the three predicates built on them: the work, the printing, and the reading history title that takes the half of the fold which cannot merge two books and refuses the half that can |
| `test_folding.py` | 34 | **Folding two Books.** That every child of `books` declares what a fold does with its rows and an eleventh fails at import naming the table, the four policies and their ceilings, that no read here looks past the Books in hand with the bound traced to the carry rather than to the column alone, and the read count that makes a person look at a read that appeared |
| `test_book_columns.py` | 23 | **The partition of `books`' columns.** That every column is classified exactly once, with a column in no cell, a cell naming a column that is gone and a column in two cells each reported and each raising at import rather than at a write; that each writer asks for its set by identity rather than re-listing it; what five of the six cells should hold asked of `CopyCreate`, `BookMatch`, the visibility predicate, the foreign key graph and what the copy route cannot carry in its constructor rather than of the cell; and that no module outside the tests reads a name other than the three the writers take |
| `test_shelf.py` | 242 | The seam every many-book query goes through, and the only enforcement of the privacy rule since the AST guard was deleted. |
| `test_shelving.py` | 4 | **The one place it is decided who may be told a collection exists.** That nothing else decides it, over every module and with the reader's own state out of reach, planted against the exemption that shipped the tag version green |
| `test_fields.py` | 60 | **The one place it is decided who may be told a custom field exists.** The three cross module rules behind those routes, each derived from the tree rather than listed: that every read of `custom_fields` is classified and a new one fails by name, that the whole table read has the callers it claims, so a route that calls it and publishes the rows is named where the read itself has not changed, and that nothing but a book id and a field id leaves the value table, which is what keeps a value, a count or a book out of the one read that is unscoped on purpose |
| `test_nothing_private_leaves.py` | 34 | **The export boundary, and what still crosses it.** That only the shelf builds an outbound payload, a route sweep derived from the live route table, and the shapes the guards admit they cannot see |
| `test_no_custody.py` | 7 | **Nowhere to send a book file to.** Which routes accept an upload, as an equality in both directions with what each file is for, and that no mapped column carries bytes: the structural half of the promise that a book file is read in the browser and never uploaded |
| `test_authors.py` | 63 | Splitting a credit line, the key that folds without asking against the one that only suggests, the index, the four suggestion rules |
| `test_auth_backends_bindguard.py` | 20 | **The empty-password guards**, at all three layers |
| `test_ratelimit.py` | 49 | The sliding window, and the login/registration limits |
| `test_uploads.py` | 33 | Content-sniffed image validation and the size cap |
| `test_middleware.py` | 27 | Security headers, CSP contents, HSTS conditions |
| `test_main.py` | 64 | App wiring, tag seeding, the operationId guard, the overdue ticker's lifespan, what the built files say about being reused, the shell that has to answer a client route. The operationId guard is held on its extent as well as its refusal: its population against the operations the document publishes, its call position against every `include_router` in the module, and the acceptance of a name two unpublished routes share, which is what a published pair being refused cannot say |
| `test_house_rules.py`                      |   466 | **Defects a person found four times.** Every caller-supplied row id bounded at both ends, whether it arrives as a query parameter. Also the one decision of what vendored code is: each walk in the test tree that reaches that decision, driven against a constructed tree with each kind of vendored path planted in front of it, and no other test module allowed to define a walk of its own; and that the route handler population is derived twice, once from the decorators and once from the routes the app registers, with the decorator tuple itself held against the names the corpus carries; and that no docstring anywhere under `backend/` holds the control character its own sentence names, over the one walk that sees the generated revisions as well. The ignore file rule has one home now, so each form that home refuses is asserted on its own arm, the parse is held against an expected value rather than fed back into the matcher, and both parameters of that seam are keyword only, and each marker character is refused by the position or the equality git defines it at rather than by containment, with an arm on each side of that: the forms refused, and the literals a containment test used to refuse by accident |
| `test_scratch_report.py` | 4 | **The scratch report names the filesystem the databases landed on.** `conftest._fastest_scratch()` falls back from `/dev/shm` to disk silently |
| `test_property_budget.py`                  |     6 | **What the generated tests are allowed to spend, measured rather than declared.** The examples that actually execute are counted against a floor, every registered profile is checked against it, and a generated test that neither carries the `property` marker nor keeps to the profile's budget is refused |
| `test_roster_counts.py` | 83 | **A number spelled in prose, recomputed.** Every number written beside a roster noun is found by a census and must carry a verdict naming a cardinality computed from `sources.py`. The census walks the tree minus what a tool owns, so a new file is covered without anybody remembering, and it reads this register. The claims it makes about its own corpus are recomputed rather than restated, and the size of its own walk is not written down anywhere, for the reason the register gives under a corpus being stated as an exclusion. |
| `test_coverage_register.py` | 70 | **This register, against the run that reads it.** Every row's count and the generated block recomputed from the collection in hand, the partition that makes a file with no row one the publish gate strips rather than one nobody described, and the parser's own silent failures |
| `test_a_hung_test_is_named.py` | 27 | **A hung test fails as a named test, and a run that lost tests fails too.** The diagonal runs a real pytest over a throwaway project it writes itself, with its own short ceiling, holding termination in its own hands and partitioning the outcome three ways so an unbounded inner run is invalid rather than green; beside it, that a slow test which finishes is not reddened, that the red survives deleting the rest of the inner project, and that an ini planted directly above the project does not reach it. Each of the three flags making the mechanism has an arm, because each is a way the fix silently becomes what it replaced. The global ceiling is asserted as strictly above the largest ceiling the test tree declares, derived from what a call binds through the shared walk and stated as the floor it is. And the session's own reconciliation: that a short session is refused by name and that four shapes of deliberate stop are not, each driven at the values the hook was measured receiving; that a collect only run and a worker are not; that the exit status partition is pinned on both sides, so a future status cannot join the exempt side by being added; that an empty population is a refusal rather than a vacuous pass; and that the hooks filling it were armed in the run reading the line |
| `test_openapi_drift.py` | 8 | **The committed schema is the document this code produces.** That `frontend/openapi.json` is byte identical to what the generator writes, and that the two verdicts under it can fail: a changed value, a key only one side carries, a lost final newline, and a generation refused rather than reported as a drift |
| `test_declared_media_types.py` | 53 | **A route that sends bytes declares what those bytes are, at every answer it files.** Four operations sent a file or an image under `application/json` with an empty schema, so the committed document, the generated client and any third party reading it were wrong about all four. The population is every documented route annotated with a `Response` **subclass**, which is the mirror of the no body rule in the auth tests. The rules are per declared key under four cells that are disjoint and total by construction, driven over keys none of which is live; what no live route reaches is driven on a throwaway application in both directions, including the two success keys the singular rule refused and the content under a redirect it never looked at; the export, the archive and the covers are held against the types their own module says they serve; and each is driven over the wire, a cover twice, because one range and two ranges arrive under different media types |
| `schemas/test_common.py` | 17 | **One line a member typed, and the one place the API layer spells it.** The three normalisations, the partition over the control characters that keeps the middle one from becoming the strictest, the ordering a URL bought, and the walk that refuses a whitespace split. The control character rule this layer found is now tree wide in `test_house_rules.py`, because two of its sites were generated revisions no walk here can see |
| `schemas/test_book.py` | 104 | **Two request bodies writing one column must agree about it.** `BookMatch` bounded four of its seventeen fields while `merge_into` wrote them all. Also the doors over `books.categories`, by the input that drives each: a separator bearing candidate among clean ones for the refusal, the count and the entry width read off their own named factors, a payload of exactly the stated width carrying bare separators for the rejoin, one subject as wide as the whole bound for the diagonal, and a field partition driven by synthetic sides including this tree's own annotated spelling and an abstract sequence; and the field partition is read against both write bodies, since the update route assigns onto a row rather than calling a constructor and needs its own refusal, its own derived pop list and its own reader over the route's source |
| `schemas/test_settings.py` | 2 | **A row the router builds must carry every field the source describes.** The settings row is built by splatting the description into the response model |
| `test_serialisation.py` | 47 | Assembling `BookOut`: the per-request fields, the tag suggestion by caption and by DDC number, that a tag name inside a longer word is not a caption match |
| `test_schema.py`                           |   283 | Alembic: create, adopt a pre-Alembic database, upgrade, that two table rewrites left their partial unique indexes partial, and the bounds three text columns and one address column gained |
| `schemas/test_wire_datetimes.py` | 7 | **Every dated field this API publishes carries an offset**, asked of what each field emits rather than of which policy object it names, so a second correct spelling passes and a field that lost one is reported by name. With the arms that keep it from passing vacuously: a population floor, a planted bare field, a planted container, and the published components reconciled against the walk |
| `schemas/test_digital.py` | 31 | What a client may say about a file it holds, bounded at the schema: the root, the path beneath it and the fingerprint, each refused at its ceiling rather than trusted for its width |
| `test_env_example.py` | 4 | **Operator documentation that goes stale silently.** That every environment name `config.py` reads appears in `.env.example` and nothing appears there that the code ignores |
| `test_database.py` | 90 | Engine setup, the session dependency, and the TLS posture every `DATABASE_SSL_MODE` resolves to, read off the context before any socket exists, and that the application's own engine is built from the setting, that a statement error names no bound value, and that every engine says so |
| `scripts/test_postgres_database.py` | 11 | The database name rule, the only thing between a name and DDL that takes no bind parameter. The server half runs against Postgres only and is not reached here |
| `test_database_tls_on_a_real_server.py` | 0 | That the modes refusing a downgrade refuse a server with no TLS, that the tolerant two reach it, and that the cleartext probe can still see the driver's socket. Skipped off Postgres, so this run collects none of it |
| `test_errors_on_a_real_server.py` | 0 | That a unique violation on a live server, reaching the 500 handler through a route, is logged with the constraint and without the value the server quotes, beside a witness that the server did quote it. Skipped off Postgres, so this run collects none of it |
| `test_fetch.py` | 137 | **The only door outwards.** That the body cap counts raw wire bytes and compression is never requested, and that neither the text seam nor the JSON seam hands a caller a lone surrogate |
| `test_xml_parse.py` | 10 | **What parsing a stranger's XML may cost.** The depth bound at the builder, a refused nest costing one chunk at ten times the size, and the chunked feed raising what one feed raises |
| `test_deadline.py` | 38 | How much of a deadline is left, and which clock answers: that the two names are the whole door, that neither grows a parameter, and that the module imports nothing but the standard library |
| `test_dialect.py` | 104 | One rule, two engines: that each dialect's arm renders where the rule is rendered and a third is refused there, that the SQLite arm of every ported constraint is the text it always was, and that no SQLite arm lost a clause the Postgres arm is allowed to omit, and that each revision's Postgres arm is the next one's starting point |
| `test_catalogue.py` | 241 | Folding what one source repeats, filling one row from another, merging two catalogues of one printing, how complete a record is, the two draft shapes, and what a source may not assert about this deployment's own files, and that rewriting a scalar after the fold refuses every collection, leaves each one the same object, and re-enters every dropper, so the locality rule needs no second belt on the import path |
| `test_classifications.py` | 38 | **What a heading asserts, beside which file its number is in.** The kind a field carries, that a legacy row keeps its pair, and the derivation that counts the readers |
| `test_filing.py` | 238 | **How each classification scheme's call numbers sort.** One rule per scheme answering three things: whether it recognises a number, the key that files it |
| `test_z3950.py` | 78 | The Z39.50 door: the byte and time bounds enforced by construction, the taxonomy keeping **refused**, **unreachable** and **answered nothing** apart, and PQF escaping. |
| `test_z3950_provisional.py` | 38 | The provisional ctypes client behind that door: every ZOOM call declared against the signatures it really has, NULL checks, the single worker and its lock |
| `routers/test_public.py` | 51 | The first routes reachable without a session: the gate as a router dependency rather than per handler, that nothing under the prefix accepts a write, 404 never 403 |
| `schemas/test_public.py` | 25 | That the public payload is a total partition of `BookOut`, 18 published and 27 withheld with a reason each, and that no public model carries an alias |
| `test_cover_store.py` | 55 | **The one module that knows where a cover lives.** The house rule in three `ast` passes, the two writers told apart in both directions, the containment check driven directly because no public function reaches that arm, and the on disk lookups' stability under a reordered allowlist |
| `test_covers.py` | 150 | Fetching, sniffing, storing and serving a cover, the per-hop host allowlist, the shape every entry on it needs for the CSP and the fetch to mean the same thing, the same wire-byte reading the catalogue path uses, and the two house rules keeping `covers.py` the only module that knows an image host or decides a cover is local |
| `test_reading.py` | 66 | **The seam every reading record goes through.** That a record is private to its member separately from the book being visible, and that rating a book or offering to discuss it stamps no dates. |
| `test_custom_fields.py` | 108 | **Household defined fields on a book.** That every reader and writer takes `Book` objects rather than ids |
| `routers/test_books_identifier_backfill.py` | 37 | The bulk lookup by stored identifier: the batch and its cursor, that a miss clears the cursor and a timeout leaves the book a candidate, that a rate limited book is provably still one afterwards, and that no key is a 409 naming the switch rather than a clean run |
| `routers/test_concurrency_bounds.py` | 4 | That no route handler builds a concurrency bound of its own, with the handlers and the primitives both derived rather than named, so a primitive nobody has thought of fails by name; that the identifier backfill holds its bound at module level and is sized off what its own module builds it to rather than off the constant beside it; that the handler population this reads is the route layer's share of the population `test_house_rules.py` derives twice, held as an equality rather than as a floor; and that the image runs one worker, without which every bound here is per worker rather than per pod |
| `routers/test_books_cover_backfill.py` | 14 | The bulk cover fetch: that the pool outlives the request rather than being built per call, that every book is given the run's own budget and not only every hop, that a wave whose slots run out examines only what started, that the cursor never passes a book no fetch began, that the pool holds exactly one wave's slots, and that re-resolving a stored cover the browser cannot render keeps the one it has |
| `routers/test_books_custom_fields.py` | 71 | The six routes: defining, renaming, filling in, and that a field on a book the caller cannot see is 404 rather than 403. Also the doors that take a field id: a rename or a value write naming a definition the caller may not be told about answers 404 and leaves the row alone, that refusal is the one an absent id already gives, the rename logs the account and both names, and retyping a hidden field's name hands back the definition and nothing else, so the write after it is still a 404 |
| `test_mailer.py` | 59 | **SMTP as a transport and its refusals.** That TLS cannot be switched off by any setting or environment variable, that a stripped STARTTLS raises rather than sending in the clear, that a credential the mail library cannot encode is refused as a setting |
| `routers/test_covers.py` | 41 | The cover routes: upload, fetch, serve, and the placeholder |
| `routers/test_books_copies.py` | 40 | Copy groups: creating, listing and the shared-edition rules |
| `routers/test_books_covers.py` | 27 | Cover routes hung off a book |
| `routers/test_books_lending.py` | 25 | Loans: lending, returning, the reminder interval and who may see a loan |
| `routers/test_books_bulk.py` | 76 | One verb applied to a selection, the three-way count, that a row id past the largest a row can carry is a 404 rather than an `OverflowError` out of the driver, that the dispatch table and `BulkAction` agree with `_dispatch_table` driven by a synthetic enum in both directions, and that no member of `BulkAction` turns a hostile argument into a 500 |
| `routers/test_collections.py` | 34 | **Shelving, never permission.** Naming a part of the shelf, the case-insensitive uniqueness the database enforces, in ASCII and outside it, counts filtered to the caller, and which collections a caller is told about at all |
| `routers/test_books_collections.py` | 40 | Filing a book, the two list parameters and the 400 for both at once, the bulk verb, the merge that absorbs a collection, the export column, and that each write door still takes a shelf only the caller's own private books are on |
| `routers/test_books_duplicates.py` | 48 | Duplicate detection and the merge, incl. the ORM cascade trap |
| `routers/test_books_notes.py` | 13 | A note's own visibility over the four note routes: a private note absent from another member's listing and from an admin's, 404 rather than 403 on edit and delete for anybody but its author, and an edit that does not mention the flag leaving it alone |
| `routers/test_books_digital_references.py` | 44 | The four routes a client uses to say where a book's file is: only the member's own references, a sighting that refreshes the fingerprint, a miss that flags the row rather than deleting it, and a book the caller cannot see answering 404 |
| `routers/test_imports_marc.py` | 61 | **Both directions of the exchange.** Library mode enforced at 403, the file size ceiling, the preview counts and what each one discloses, that a matched Book never gains an ISBN, and that the gap filter drops an ISBN the create path grew, asked of the filter rather than of today's tuple. On the export side, that the shelf is walked a page at a time rather than resolved whole and that the walk handed to the response has not run, that a book is written exactly once whatever the shelf does behind it, that a writer giving out, part way through or on the walk's first query, leaves a document no parser accepts, what a page of the widest records a write through the API can produce weighs, which a restore beats by 13.75 MiB a page, and the two questions that decide it, the fill character and how many times a field repeats, and that no production module calls the whole document writer at all |
| `routers/test_books_classification_filter.py` | 29 | **Filtering by classification, and the order it comes back in.** Chiefly a privacy test: `classifications` carries no member column, so the filter is only as private as the shelf in front of it. |
| `routers/test_books_classifications.py` | 36 | **A catalogue heading kept whole.** That the number survives the parse and a year does not become one, that a German caption still suggests a curated tag |
| `routers/test_books_categories.py` | 22 | **Subjects posted with a book.** Stored whole and interpreted by nothing: a spelling that matches a curated tag still mints one nowhere, a subject carrying the separator the column is joined on is refused rather than split, the count and the entry width are refused off their constants, spacing and control characters are normalised instead of refused, a book posted without any stores a null rather than an empty string, and the route's own source is read for a field it pops and never writes; and the second door onto that column, where an empty list clears, an absent field leaves alone, a null is refused rather than taken as a second spelling of the clear, and the cleared column is read off the database as a null rather than an empty string |
| `routers/test_books_quotes.py` | 50 | **Passages copied out of a book.** The bounds on the excerpt, the remark and the page, reading order with the unpaged last, who may correct one |
| `routers/test_books_progress.py` | 29 | **The reading log.** One unit per entry, the promotion to reading, that a member never sees another's, and the merge that would otherwise cascade it away |
| `routers/test_books_reading.py` | 31 | Ratings, and the rules for stamping reading dates |
| `routers/test_books_series.py` | 30 | Series gaps, shelf locations, partial detail edits, and that the gap range is truncated at `MAX_SERIES_INDEX`, pinned from both edges so neither a smaller ceiling nor a missing one passes |
| `routers/test_books_authors.py` | 112 | The author index and its privacy, the `?author=` filter, merging and reversing one, the library wide mapping against the filtered shelf, the flat map, and undoing a merge. |
| `routers/test_books.py`                    |   183 | Listing, search, sorting, tagging, covers, notes, export, ownership, that every cell the export writes goes through the formula escape with no exemption, and that a login this deployment holds leaves with the request that needs it |
| `routers/test_books_identifiers.py`        |    28 | The identifier a store knows a book by, over the API: written with the book, read back on it, refused where the scheme is not one this app names, bounded so a payload cannot carry an unbounded list, and removed by any member who may write the book, where an invisible book and one belonging to somebody else are both 404 |
| `schemas/test_identifier.py`               |    24 | What a store identifier may contain, at the door: the character classes refused, which are whitespace and both invisible Unicode categories, checked as the same set the client filter refuses rather than against examples, and as one rule over every string: the padding comes off and what is left is stored unless it is empty or holds any whitespace or anything invisible |
| `schemas/test_classification.py`           |    10 | **What a classification number may hold, as a rule over every string.** The whitespace a catalogue's own formatting leaves is collapsed, both invisible Unicode categories are refused, and storing a stored number changes nothing |
| `test_identifiers.py`                      |    10 | Writing identifiers onto a book: duplicates within one payload dropped rather than refused, because a client reading two of its own files may find one book in both, and the repoint a merge performs |
| `routers/test_books_google.py` | 44 | Enrichment, the chosen-edition apply and that its body cannot overflow the database |
| `routers/test_books_search.py` | 56 | **Free-text search.** That it works with no API key, that the six catalogues a reader would doubt answer do, how they merge, that a record describing itself with more subjects than a book may hold still comes back as a row where the cap now trims them |
| `routers/test_books_trash.py` | 43 | **Undoing a delete.** That a trashed book leaves every view, comes back whole, and frees its ISBN again |
| `routers/test_settings.py` | 174 | Feature flags, the masked API key, the overdue webhook settings, admin-only writes |
| `routers/test_imports.py` | 61 | The import, the private-ISBN branch, the tag caps, the rate limit, and the round trip: that every column of the live export is read back or named as unread, that each one lands in the field named for it, and that every importer field is filled or named as absent |
| `routers/test_books_tags.py` | 67 | **Two vocabularies in one table.** Who may create, who may delete, and the counts |
| `routers/test_auth.py` | 101 | Registration, login, `/auth/me`, the registration switch, switching into a test account in all three modes, and that an address given at registration is stored, normalised, and that a failed confirmation mail logs its type and never its message |
| `routers/test_loans.py` | 101 | Lending, returning, history, who may run the overdue digest, and the overdue list a member reads: whose loans it holds, the in app switch that empties it |
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