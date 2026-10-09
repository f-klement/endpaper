# Index of the decisions register

Every entry of [`decisions.md`](decisions.md), in the order it appears there, with the
section it sits under and how long it is.

**This is a grep target, not a page to read.** Read whole it is longer than the register's
own heading lines, so it earns its place on one thing that grepping those headings cannot
give you: **how long an entry is before you open it**. It also gives every entry a working
anchor, and it is the one place the register's titles exist as a list something can
enumerate.

**Generated from that file's own headings.** An entry is added by writing it in
`decisions.md`, never by editing a row here, and a row edited by hand is overwritten the next
time the list is regenerated.

**What the columns are.** `Section` is the top level heading the entry sits under, and it is
**empty where the entry is itself that heading**, rather than printing the same title twice.
`Entry` is the heading, copied character for character and linked to its anchor. `Words` is
the entry's body down to the next heading at its own level or above, so a section counts the
entries under it as well.

**It does not say which module a decision is about.** The register's own entry, "An index of
this file is generated, not written", is where that refusal is argued; this file does not
repeat the argument.

<!-- index: begin -->
| Section | Entry | Words |
|---|---|---|
|  | [Backend](decisions.md#backend) | 33,353 |
| Backend | [`bcrypt` directly, not `passlib`](decisions.md#bcrypt-directly-not-passlib) | 98 |
| Backend | [Settings are functions, not module constants](decisions.md#settings-are-functions-not-module-constants) | 59 |
| Backend | [`DATA_DIR` exists at all](decisions.md#data_dir-exists-at-all) | 22 |
| Backend | [`visible_to()` is a function](decisions.md#visible_to-is-a-function) | 62 |
| Backend | [The Shelf owns the privacy rule, and the AST guard is gone](decisions.md#the-shelf-owns-the-privacy-rule-and-the-ast-guard-is-gone) | 468 |
| Backend | [Book access lives in dependencies, not in handlers](decisions.md#book-access-lives-in-dependencies-not-in-handlers) | 36 |
| Backend | [Login has its own schema](decisions.md#login-has-its-own-schema) | 33 |
| Backend | [`covers.py` is the only module that knows an image host](decisions.md#coverspy-is-the-only-module-that-knows-an-image-host) | 145 |
| Backend | [A stored cover must be https, or one of ours](decisions.md#a-stored-cover-must-be-https-or-one-of-ours) | 302 |
| Backend | [The fourth reading status is "Did not finish", not "Abandoned"](decisions.md#the-fourth-reading-status-is-did-not-finish-not-abandoned) | 892 |
| Backend | [The built files state a cache lifetime, and only hashed names get a long one](decisions.md#the-built-files-state-a-cache-lifetime-and-only-hashed-names-get-a-long-one) | 385 |
| Backend | [The mount serves the shell for a client route, because `html=True` does not](decisions.md#the-mount-serves-the-shell-for-a-client-route-because-htmltrue-does-not) | 649 |
| Backend | [`SERVE_FRONTEND=false` is a flag on one image, not a second image](decisions.md#serve_frontendfalse-is-a-flag-on-one-image-not-a-second-image) | 239 |
| Backend | [The health probe touches the database, and that was not enough](decisions.md#the-health-probe-touches-the-database-and-that-was-not-enough) | 590 |
| Backend | [The covers that "stopped appearing" were a service worker cache, not the server](decisions.md#the-covers-that-stopped-appearing-were-a-service-worker-cache-not-the-server) | 548 |
| Backend | [A cover is stored here, not hotlinked](decisions.md#a-cover-is-stored-here-not-hotlinked) | 317 |
| Backend | [The cover bytes are files on the volume, not a column](decisions.md#the-cover-bytes-are-files-on-the-volume-not-a-column) | 401 |
| Backend | [The cover backfill is every member's own, not the admin's](decisions.md#the-cover-backfill-is-every-members-own-not-the-admins) | 682 |
| Backend | [The CSV import does not fetch covers inline](decisions.md#the-csv-import-does-not-fetch-covers-inline) | 75 |
| Backend | [The server checks which host it may fetch a cover from](decisions.md#the-server-checks-which-host-it-may-fetch-a-cover-from) | 218 |
| Backend | [Five cover outcomes are counted, because they used to be indistinguishable](decisions.md#five-cover-outcomes-are-counted-because-they-used-to-be-indistinguishable) | 148 |
| Backend | [A test account is a column, not "auth_source is local"](decisions.md#a-test-account-is-a-column-not-auth_source-is-local) | 425 |
| Backend | [The rate limiter is hand-rolled](decisions.md#the-rate-limiter-is-hand-rolled) | 30 |
| Backend | [Lending *to* an external is a loan; lending *from* one is not](decisions.md#lending-to-an-external-is-a-loan-lending-from-one-is-not) | 238 |
| Backend | [Loans are ordered by `(loaned_at DESC, id DESC)`](decisions.md#loans-are-ordered-by-loaned_at-desc-id-desc) | 40 |
| Backend | [`/export` is declared before `/{book_id}`](decisions.md#export-is-declared-before-book_id) | 31 |
| Backend | [A unique *index*, not a unique constraint, on `user_books`](decisions.md#a-unique-index-not-a-unique-constraint-on-user_books) | 35 |
| Backend | [`generate_unique_id_function`](decisions.md#generate_unique_id_function) | 80 |
| Backend | [Alembic, adopted rather than more hand-written ALTERs](decisions.md#alembic-adopted-rather-than-more-hand-written-alters) | 46 |
| Backend | [Ownership is a separate axis from read status](decisions.md#ownership-is-a-separate-axis-from-read-status) | 66 |
| Backend | [Lending willingness is a third axis, and it is on the book](decisions.md#lending-willingness-is-a-third-axis-and-it-is-on-the-book) | 178 |
| Backend | [A book marked never lent is refused once, not forbidden](decisions.md#a-book-marked-never-lent-is-refused-once-not-forbidden) | 249 |
| Backend | ["Ask me about this book" is on the member, and everybody can see it](decisions.md#ask-me-about-this-book-is-on-the-member-and-everybody-can-see-it) | 212 |
| Backend | [`categories` is joined with a semicolon, not a comma](decisions.md#categories-is-joined-with-a-semicolon-not-a-comma) | 210 |
| Backend | [A classification is stored whole, and its number is what gets matched](decisions.md#a-classification-is-stored-whole-and-its-number-is-what-gets-matched) | 329 |
| Backend | [The DDC projection is a suggestion, and "suggestion" means pre-selected](decisions.md#the-ddc-projection-is-a-suggestion-and-suggestion-means-pre-selected) | 284 |
| Backend | [Division level, not the full Dewey schedule](decisions.md#division-level-not-the-full-dewey-schedule) | 125 |
| Backend | [The Library of Congress is fetched over plaintext HTTP, knowingly](decisions.md#the-library-of-congress-is-fetched-over-plaintext-http-knowingly) | 398 |
| Backend | [Catalogue XML refuses a doctype, and the response body is capped at 2 MiB](decisions.md#catalogue-xml-refuses-a-doctype-and-the-response-body-is-capped-at-2-mib) | 198 |
| Backend | [Classifications are in the backup and not in the CSV](decisions.md#classifications-are-in-the-backup-and-not-in-the-csv) | 85 |
| Backend | [Only DDC is projected, though LCC, GND and LCSH are stored](decisions.md#only-ddc-is-projected-though-lcc-gnd-and-lcsh-are-stored) | 153 |
| Backend | [LCSH is a parser extension, and the Library of Congress stays off the lookup path](decisions.md#lcsh-is-a-parser-extension-and-the-library-of-congress-stays-off-the-lookup-path) | 293 |
| Backend | [`classifications.number` is 120 characters, and LCSH is why](decisions.md#classificationsnumber-is-120-characters-and-lcsh-is-why) | 156 |
| Backend | [A subject heading never reaches the Dewey parser, on this source either](decisions.md#a-subject-heading-never-reaches-the-dewey-parser-on-this-source-either) | 86 |
| Backend | [LCSH sorts last at the ceiling, and the tie against GND is decided on the column](decisions.md#lcsh-sorts-last-at-the-ceiling-and-the-tie-against-gnd-is-decided-on-the-column) | 286 |
| Backend | [An empty list is absent, and `[]` used to beat a populated list](decisions.md#an-empty-list-is-absent-and--used-to-beat-a-populated-list) | 448 |
| Backend | [The DNB is read as MARC21, and Dublin Core cost a caption to leave](decisions.md#the-dnb-is-read-as-marc21-and-dublin-core-cost-a-caption-to-leave) | 198 |
| Backend | [Open Library's subjects are not classifications, and its two classification fields are](decisions.md#open-librarys-subjects-are-not-classifications-and-its-two-classification-fields-are) | 295 |
| Backend | [Open Library subjects are bounded at twelve, and the bound is what makes them usable](decisions.md#open-library-subjects-are-bounded-at-twelve-and-the-bound-is-what-makes-them-usable) | 257 |
| Backend | [Tag names are matched on word boundaries, not as bare substrings](decisions.md#tag-names-are-matched-on-word-boundaries-not-as-bare-substrings) | 206 |
| Backend | [An Open Library key is validated before it goes into a URL](decisions.md#an-open-library-key-is-validated-before-it-goes-into-a-url) | 95 |
| Backend | [The edition cluster drops a declared translation, and ranks a declared match first](decisions.md#the-edition-cluster-drops-a-declared-translation-and-ranks-a-declared-match-first) | 412 |
| Backend | [The candidates page deduplicates on the ISBN and on nothing else](decisions.md#the-candidates-page-deduplicates-on-the-isbn-and-on-nothing-else) | 86 |
| Backend | [The DNB's 653 keywords are not read](decisions.md#the-dnbs-653-keywords-are-not-read) | 108 |
| Backend | [The Goodreads integration is a CSV import and a link](decisions.md#the-goodreads-integration-is-a-csv-import-and-a-link) | 54 |
| Backend | [Reading progress is a log, not a `current_page` column](decisions.md#reading-progress-is-a-log-not-a-current_page-column) | 132 |
| Backend | [Two units on `reading_progress`, exactly one per row](decisions.md#two-units-on-reading_progress-exactly-one-per-row) | 102 |
| Backend | [The displayed percentage is derived, never stored](decisions.md#the-displayed-percentage-is-derived-never-stored) | 82 |
| Backend | [Recording progress promotes to `reading` and never to `read`](decisions.md#recording-progress-promotes-to-reading-and-never-to-read) | 92 |
| Backend | [A status change never deletes progress rows](decisions.md#a-status-change-never-deletes-progress-rows) | 80 |
| Backend | [The progress endpoints sit beside `/{book_id}/status`, not before `/{book_id}`](decisions.md#the-progress-endpoints-sit-beside-book_idstatus-not-before-book_id) | 92 |
| Backend | [`pages_by_month` is computed in Python, and covers page-tracked books only](decisions.md#pages_by_month-is-computed-in-python-and-covers-page-tracked-books-only) | 236 |
| Backend | [Overdue reminders go out on three channels: a webhook, email, and Telegram](decisions.md#overdue-reminders-go-out-on-three-channels-a-webhook-email-and-telegram) | 575 |
| Backend | [The overdue digest excludes private books, on every channel](decisions.md#the-overdue-digest-excludes-private-books-on-every-channel) | 396 |
| Backend | [`notified_at` is a timestamp on the loan, stamped when at least one channel that pushes delivered](decisions.md#notified_at-is-a-timestamp-on-the-loan-stamped-when-at-least-one-channel-that-pushes-delivered) | 333 |
| Backend | [The digest result carries a `reason`, and it is null exactly when it sent](decisions.md#the-digest-result-carries-a-reason-and-it-is-null-exactly-when-it-sent) | 258 |
| Backend | [`count_private_overdue` takes no reminder interval](decisions.md#count_private_overdue-takes-no-reminder-interval) | 143 |
| Backend | [A measured number lives in one place, and the other places point at it](decisions.md#a-measured-number-lives-in-one-place-and-the-other-places-point-at-it) | 133 |
| Backend | [`SECRET_KEYS` is enforced by a test that walks it, not by being read](decisions.md#secret_keys-is-enforced-by-a-test-that-walks-it-not-by-being-read) | 136 |
| Backend | [The webhook URL is returned in full; the signing secret is masked](decisions.md#the-webhook-url-is-returned-in-full-the-signing-secret-is-masked) | 114 |
| Backend | [The ticker is one asyncio task, and assumes one process](decisions.md#the-ticker-is-one-asyncio-task-and-assumes-one-process) | 89 |
| Backend | [Reading dates are derived, not entered](decisions.md#reading-dates-are-derived-not-entered) | 53 |
| Backend | [Series is two columns, not a table](decisions.md#series-is-two-columns-not-a-table) | 46 |
| Backend | [Location is free text](decisions.md#location-is-free-text) | 53 |
| Backend | [Every row id a caller supplies is bounded at both ends](decisions.md#every-row-id-a-caller-supplies-is-bounded-at-both-ends) | 462 |
| Backend | [A book belongs to one collection, not many](decisions.md#a-book-belongs-to-one-collection-not-many) | 323 |
| Backend | [Every book that existed before collections is unfiled, and no default was invented](decisions.md#every-book-that-existed-before-collections-is-unfiled-and-no-default-was-invented) | 151 |
| Backend | [A collection is never a privacy boundary, and its label is not per library](decisions.md#a-collection-is-never-a-privacy-boundary-and-its-label-is-not-per-library) | 689 |
| Backend | [Deleting a collection unfiles its books, and the database is what says so](decisions.md#deleting-a-collection-unfiles-its-books-and-the-database-is-what-says-so) | 107 |
| Backend | [A copy carries its own collection, and the group spans them](decisions.md#a-copy-carries-its-own-collection-and-the-group-spans-them) | 387 |
| Backend | [A collection is not an import option, and not a grant scope](decisions.md#a-collection-is-not-an-import-option-and-not-a-grant-scope) | 162 |
| Backend | [A copy is a row, not a count column](decisions.md#a-copy-is-a-row-not-a-count-column) | 418 |
| Backend | [Deliberate copies and accidental duplicates are told apart by a token](decisions.md#deliberate-copies-and-accidental-duplicates-are-told-apart-by-a-token) | 172 |
| Backend | [The copy group is a shared label, not a self-referencing foreign key](decisions.md#the-copy-group-is-a-shared-label-not-a-self-referencing-foreign-key) | 223 |
| Backend | [The copy's cover file is copied, not shared](decisions.md#the-copys-cover-file-is-copied-not-shared) | 71 |
| Backend | [`_create_book` frees every holder of the ISBN, not the first one](decisions.md#_create_book-frees-every-holder-of-the-isbn-not-the-first-one) | 260 |
| Backend | [A cover file is unlinked after the commit, never before it](decisions.md#a-cover-file-is-unlinked-after-the-commit-never-before-it) | 176 |
| Backend | [Duplicate detection matches on title and author, not ISBN](decisions.md#duplicate-detection-matches-on-title-and-author-not-isbn) | 59 |
| Backend | [An author is a name on a book, not a row](decisions.md#an-author-is-a-name-on-a-book-not-a-row) | 381 |
| Backend | [Two spellings are one person because somebody said so, not because the strings changed](decisions.md#two-spellings-are-one-person-because-somebody-said-so-not-because-the-strings-changed) | 295 |
| Backend | [Three keys, and only the conservative one folds without asking](decisions.md#three-keys-and-only-the-conservative-one-folds-without-asking) | 110 |
| Backend | [The credit line is split on commas, and the importers' flip rule is not reused](decisions.md#the-credit-line-is-split-on-commas-and-the-importers-flip-rule-is-not-reused) | 175 |
| Backend | [The author page is the library, filtered](decisions.md#the-author-page-is-the-library-filtered) | 110 |
| Backend | [Deduplication has two entry points, and the suggestions are the smaller one](decisions.md#deduplication-has-two-entry-points-and-the-suggestions-are-the-smaller-one) | 211 |
| Backend | [Merging is any member's, and so is undoing it](decisions.md#merging-is-any-members-and-so-is-undoing-it) | 54 |
| Backend | [`importing.py` owns applying an export, `csv_import.py` stays pure underneath](decisions.md#importingpy-owns-applying-an-export-csv_importpy-stays-pure-underneath) | 305 |
| Backend | [SQLite folds case in ASCII and Python does not](decisions.md#sqlite-folds-case-in-ascii-and-python-does-not) | 382 |
| Backend | [A collection's name folds in Python, and the migration that did it merges](decisions.md#a-collections-name-folds-in-python-and-the-migration-that-did-it-merges) | 393 |
| Backend | [The migration merges, and four SQLite traps decided its shape](decisions.md#the-migration-merges-and-four-sqlite-traps-decided-its-shape) | 134 |
| Backend | [A route docstring is API documentation, not an internal comment](decisions.md#a-route-docstring-is-api-documentation-not-an-internal-comment) | 292 |
| Backend | [`authorship.py` owns author identity, and `authors.py` stays pure underneath](decisions.md#authorshippy-owns-author-identity-and-authorspy-stays-pure-underneath) | 308 |
| Backend | [Book duplicates are not author identity](decisions.md#book-duplicates-are-not-author-identity) | 99 |
| Backend | [The alias mapping is library wide; the shelf is what `visible_to` filters](decisions.md#the-alias-mapping-is-library-wide-the-shelf-is-what-visible_to-filters) | 453 |
| Backend | [Author aliases never cross to a peer](decisions.md#author-aliases-never-cross-to-a-peer) | 90 |
| Backend | [Merging repoints through the ORM, not a bulk UPDATE](decisions.md#merging-repoints-through-the-orm-not-a-bulk-update) | 85 |
| Backend | [A quote is its own table, not a page number on a note](decisions.md#a-quote-is-its-own-table-not-a-page-number-on-a-note) | 214 |
| Backend | [What was left off a quote, and why](decisions.md#what-was-left-off-a-quote-and-why) | 184 |
| Backend | [The page is an integer, so a preface has no page](decisions.md#the-page-is-an-integer-so-a-preface-has-no-page) | 321 |
| Backend | [A quote is visible to whoever can see the book](decisions.md#a-quote-is-visible-to-whoever-can-see-the-book) | 260 |
| Backend | [A quote belongs to a copy, not to a work](decisions.md#a-quote-belongs-to-a-copy-not-to-a-work) | 317 |
| Backend | [There is a cross-book quotes page, and it is a book listing](decisions.md#there-is-a-cross-book-quotes-page-and-it-is-a-book-listing) | 462 |
| Backend | [One bulk endpoint, not six](decisions.md#one-bulk-endpoint-not-six) | 39 |
| Backend | [`unrated` names its correlation explicitly](decisions.md#unrated-names-its-correlation-explicitly) | 43 |
| Backend | [Python 3.14 is a hard requirement, and PEP 649 is why](decisions.md#python-314-is-a-hard-requirement-and-pep-649-is-why) | 34 |
| Backend | [The test suites were slow for reasons nobody had measured](decisions.md#the-test-suites-were-slow-for-reasons-nobody-had-measured) | 451 |
| Backend | [The per-test reset deletes rows, and two faster designs were refused](decisions.md#the-per-test-reset-deletes-rows-and-two-faster-designs-were-refused) | 450 |
| Backend | [The per test ceiling is derived from the tree, not chosen from a distribution](decisions.md#the-per-test-ceiling-is-derived-from-the-tree-not-chosen-from-a-distribution) | 274 |
| Backend | [A verdict is a claim about a denominator, and the layer everyone reads had none](decisions.md#a-verdict-is-a-claim-about-a-denominator-and-the-layer-everyone-reads-had-none) | 502 |
| Backend | [The remote test runner was reporting on a tree nobody had](decisions.md#the-remote-test-runner-was-reporting-on-a-tree-nobody-had) | 167 |
| Backend | [A seeded tag is identified by a key, not by its name](decisions.md#a-seeded-tag-is-identified-by-a-key-not-by-its-name) | 366 |
| Backend | [Who may be told a tag exists is a question about books, answered in one module](decisions.md#who-may-be-told-a-tag-exists-is-a-question-about-books-answered-in-one-module) | 285 |
| Backend | [The tag name index has no viewer, and the viewer sits on the hand off instead](decisions.md#the-tag-name-index-has-no-viewer-and-the-viewer-sits-on-the-hand-off-instead) | 448 |
| Backend | [The Catalogue record is a type, and the two dialects are gone](decisions.md#the-catalogue-record-is-a-type-and-the-two-dialects-are-gone) | 859 |
| Backend | [The Austrian National Library is a third MARCXML source, and the probe is why it works](decisions.md#the-austrian-national-library-is-a-third-marcxml-source-and-the-probe-is-why-it-works) | 645 |
| Backend | [Where it sits](decisions.md#where-it-sits) | 126 |
| Backend | [Two defects the mapping would have shipped, neither visible by reading](decisions.md#two-defects-the-mapping-would-have-shipped-neither-visible-by-reading) | 72 |
| Backend | [A `ValueError` no SRU handler caught, and a bound that could not have helped](decisions.md#a-valueerror-no-sru-handler-caught-and-a-bound-that-could-not-have-helped) | 139 |
| Backend | [What was deliberately not done](decisions.md#what-was-deliberately-not-done) | 38 |
| Backend | [What adding a catalogue cost, which is the seam's own report card](decisions.md#what-adding-a-catalogue-cost-which-is-the-seams-own-report-card) | 31 |
| Backend | [The privacy rule covers the tables that belong only to a Book, and does not try to be clever about it](decisions.md#the-privacy-rule-covers-the-tables-that-belong-only-to-a-book-and-does-not-try-to-be-clever-about-it) | 502 |
| Backend | [The shared bibliographic vocabulary is a module, and MARC reading is not](decisions.md#the-shared-bibliographic-vocabulary-is-a-module-and-marc-reading-is-not) | 248 |
| Backend | [The catalogue family publishes its decoders, and three readers are not decoders](decisions.md#the-catalogue-family-publishes-its-decoders-and-three-readers-are-not-decoders) | 281 |
| Backend | [A list filter's toggle is a patch, not a helper over an array](decisions.md#a-list-filters-toggle-is-a-patch-not-a-helper-over-an-array) | 92 |
| Backend | [`useLibrary`'s width is guarded structurally rather than by a number](decisions.md#uselibrarys-width-is-guarded-structurally-rather-than-by-a-number) | 84 |
| Backend | [One module owns the covers directory, and the sweep is chosen by the argument](decisions.md#one-module-owns-the-covers-directory-and-the-sweep-is-chosen-by-the-argument) | 256 |
| Backend | [A payload's per viewer half is a type, and it carries no defaults](decisions.md#a-payloads-per-viewer-half-is-a-type-and-it-carries-no-defaults) | 275 |
| Backend | [`LoanOut.book` is `BookColumns`, and it stops there rather than at four fields](decisions.md#loanoutbook-is-bookcolumns-and-it-stops-there-rather-than-at-four-fields) | 245 |
| Backend | [A measured number lives where the column is declared](decisions.md#a-measured-number-lives-where-the-column-is-declared) | 231 |
|  | [Frontend](decisions.md#frontend) | 14,679 |
| Frontend | [Page-centric colocation](decisions.md#page-centric-colocation) | 18 |
| Frontend | [`useLibrary` has one door for filters, not a setter per field](decisions.md#uselibrary-has-one-door-for-filters-not-a-setter-per-field) | 559 |
| Frontend | [A stored preference has one owner, and the subscription is what retired the counter](decisions.md#a-stored-preference-has-one-owner-and-the-subscription-is-what-retired-the-counter) | 1,169 |
| Frontend | [The filter set is checked against the API's own schema](decisions.md#the-filter-set-is-checked-against-the-apis-own-schema) | 370 |
| Frontend | [Types are generated, not hand-written](decisions.md#types-are-generated-not-hand-written) | 48 |
| Frontend | [No top-level `query` block in `orval.config.ts`](decisions.md#no-top-level-query-block-in-orvalconfigts) | 49 |
| Frontend | [`includeHttpResponseReturnType: false`](decisions.md#includehttpresponsereturntype-false) | 36 |
| Frontend | [`api/mutator.ts` throws on 401, except on the credential endpoints](decisions.md#apimutatorts-throws-on-401-except-on-the-credential-endpoints) | 103 |
| Frontend | [The multipart path does not set `Content-Type`](decisions.md#the-multipart-path-does-not-set-content-type) | 22 |
| Frontend | [Every request declares `Accept`, and a download declares something else](decisions.md#every-request-declares-accept-and-a-download-declares-something-else) | 300 |
| Frontend | [The endless spinner was two faults, and neither was wrong on its own](decisions.md#the-endless-spinner-was-two-faults-and-neither-was-wrong-on-its-own) | 395 |
| Frontend | [`isRedirect()` is `opaqueredirect` only](decisions.md#isredirect-is-opaqueredirect-only) | 110 |
| Frontend | [The reload is counted, and an uncountable one is not taken](decisions.md#the-reload-is-counted-and-an-uncountable-one-is-not-taken) | 331 |
| Frontend | [The dead-end branch is the one place that must empty the query cache](decisions.md#the-dead-end-branch-is-the-one-place-that-must-empty-the-query-cache) | 73 |
| Frontend | [`clearSession()` leaves the saved searches and the last location behind, and that is accepted](decisions.md#clearsession-leaves-the-saved-searches-and-the-last-location-behind-and-that-is-accepted) | 178 |
| Frontend | [`--color-paper-0` exists, and its value is `#ffffff`](decisions.md#--color-paper-0-exists-and-its-value-is-ffffff) | 90 |
| Frontend | [`bloom` and `danger` hold the same five hexes](decisions.md#bloom-and-danger-hold-the-same-five-hexes) | 135 |
| Frontend | [`TAG_PILL_CLASSES` is a four-key table with two values in it](decisions.md#tag_pill_classes-is-a-four-key-table-with-two-values-in-it) | 124 |
| Frontend | [The list row holds the grid card's face, plus two facts from its fold out](decisions.md#the-list-row-holds-the-grid-cards-face-plus-two-facts-from-its-fold-out) | 504 |
| Frontend | [Every cover in the list loads lazily, and carries no accessible name](decisions.md#every-cover-in-the-list-loads-lazily-and-carries-no-accessible-name) | 220 |
| Frontend | [A selection forces the grid, and that is tested before the view is read](decisions.md#a-selection-forces-the-grid-and-that-is-tested-before-the-view-is-read) | 61 |
| Frontend | [The palettes are CSS, and the catalogue is TypeScript](decisions.md#the-palettes-are-css-and-the-catalogue-is-typescript) | 152 |
| Frontend | [Every palette block repeats tokens that look identical to the block above it](decisions.md#every-palette-block-repeats-tokens-that-look-identical-to-the-block-above-it) | 70 |
| Frontend | [The wallpaper's opacity is solved from a weight, not written down](decisions.md#the-wallpapers-opacity-is-solved-from-a-weight-not-written-down) | 531 |
| Frontend | [A pattern is admitted by measurement, not by looking at it](decisions.md#a-pattern-is-admitted-by-measurement-not-by-looking-at-it) | 267 |
| Frontend | [The plait was verified by rendering, and not on a real screen](decisions.md#the-plait-was-verified-by-rendering-and-not-on-a-real-screen) | 209 |
| Frontend | [No veins on the leaves](decisions.md#no-veins-on-the-leaves) | 197 |
| Frontend | [The ink budget is measured analytically, and that is not free](decisions.md#the-ink-budget-is-measured-analytically-and-that-is-not-free) | 140 |
| Frontend | [The underfoliage plane is on two patterns, not five](decisions.md#the-underfoliage-plane-is-on-two-patterns-not-five) | 116 |
| Frontend | [A dark hover state is stated at every call site, and the rule has no exemptions](decisions.md#a-dark-hover-state-is-stated-at-every-call-site-and-the-rule-has-no-exemptions) | 199 |
| Frontend | [The theming series is one changelog entry, under v0.4.0](decisions.md#the-theming-series-is-one-changelog-entry-under-v040) | 106 |
| Frontend | [`warn`, `ok` and `loan` stay raw Tailwind, for now, minus one repair](decisions.md#warn-ok-and-loan-stay-raw-tailwind-for-now-minus-one-repair) | 176 |
| Frontend | [`:root:root` in the `prefers-contrast` block](decisions.md#rootroot-in-the-prefers-contrast-block) | 44 |
| Frontend | [Appearance is three columns on `users`, and is not on `UserOut`](decisions.md#appearance-is-three-columns-on-users-and-is-not-on-userout) | 87 |
| Frontend | [The wallpaper picker is a route, and the wallpaper is not a switch](decisions.md#the-wallpaper-picker-is-a-route-and-the-wallpaper-is-not-a-switch) | 305 |
| Frontend | [The swatches read the stylesheet rather than restating it](decisions.md#the-swatches-read-the-stylesheet-rather-than-restating-it) | 327 |
| Frontend | [The front door does not shuffle](decisions.md#the-front-door-does-not-shuffle) | 114 |
| Frontend | [The appearance cache is keyed by account, and the login screen shows the last one](decisions.md#the-appearance-cache-is-keyed-by-account-and-the-login-screen-shows-the-last-one) | 107 |
| Frontend | [`useSession` clears the query cache on a change of account id, not per call site](decisions.md#usesession-clears-the-query-cache-on-a-change-of-account-id-not-per-call-site) | 280 |
| Frontend | [Under proxy auth a token beats the header, but only a switch token](decisions.md#under-proxy-auth-a-token-beats-the-header-but-only-a-switch-token) | 179 |
| Frontend | [Tailwind 4 has no config file](decisions.md#tailwind-4-has-no-config-file) | 15 |
| Frontend | [`/login` is routable while signed in](decisions.md#login-is-routable-while-signed-in) | 13 |
| Frontend | [The scanner filters barcodes before reporting](decisions.md#the-scanner-filters-barcodes-before-reporting) | 14 |
| Frontend | [No i18n library](decisions.md#no-i18n-library) | 57 |
| Frontend | [No dashes as punctuation, anywhere](decisions.md#no-dashes-as-punctuation-anywhere) | 92 |
| Frontend | [The Google Books search is submitted, not debounced](decisions.md#the-google-books-search-is-submitted-not-debounced) | 37 |
| Frontend | [`mutate`, not `mutateAsync`, for fire-and-forget writes](decisions.md#mutate-not-mutateasync-for-fire-and-forget-writes) | 44 |
| Frontend | [A selected card is a checkbox, not a disabled link](decisions.md#a-selected-card-is-a-checkbox-not-a-disabled-link) | 43 |
| Frontend | [The login tabs have `aria-label`s that differ from their text](decisions.md#the-login-tabs-have-aria-labels-that-differ-from-their-text) | 44 |
| Frontend | [Debounce tests use `fireEvent`, not `user-event`](decisions.md#debounce-tests-use-fireevent-not-user-event) | 7 |
| Frontend | [The book detail page is six collapsible groups under an identity block](decisions.md#the-book-detail-page-is-six-collapsible-groups-under-an-identity-block) | 783 |
| Frontend | [A section's stored state is three values, and absence is one of them](decisions.md#a-sections-stored-state-is-three-values-and-absence-is-one-of-them) | 159 |
| Frontend | [Section state is per device and per section](decisions.md#section-state-is-per-device-and-per-section) | 262 |
| Frontend | [`writing` is fixed closed because the data to decide it is not on the page](decisions.md#writing-is-fixed-closed-because-the-data-to-decide-it-is-not-on-the-page) | 153 |
| Frontend | [A collapsed section is hidden, not unmounted](decisions.md#a-collapsed-section-is-hidden-not-unmounted) | 74 |
| Frontend | [The settings page folds against a fixed table, not a condition](decisions.md#the-settings-page-folds-against-a-fixed-table-not-a-condition) | 407 |
| Frontend | [The section store is a parameter, because two pages have an `about`](decisions.md#the-section-store-is-a-parameter-because-two-pages-have-an-about) | 59 |
| Frontend | [Folding settings kept the card, and removing the fold removed the variant](decisions.md#folding-settings-kept-the-card-and-removing-the-fold-removed-the-variant) | 125 |
| Frontend | [Funding is one link, in the README and in an About card](decisions.md#funding-is-one-link-in-the-readme-and-in-an-about-card) | 217 |
| Frontend | [The version is derived, not declared](decisions.md#the-version-is-derived-not-declared) | 361 |
| Frontend | [The About card's badges are drawn, never fetched](decisions.md#the-about-cards-badges-are-drawn-never-fetched) | 468 |
| Frontend | [Name lists are ordered in the browser, not by the database](decisions.md#name-lists-are-ordered-in-the-browser-not-by-the-database) | 478 |
| Frontend | [`theme/patterns.ts` exports eleven names only its test imports](decisions.md#themepatternsts-exports-eleven-names-only-its-test-imports) | 411 |
| Frontend | [A store identifier's value rule lives beside the scheme, and the Takeout reader asks it](decisions.md#a-store-identifiers-value-rule-lives-beside-the-scheme-and-the-takeout-reader-asks-it) | 1,173 |
|  | [The reading record has one owner, and it is a second privacy rule](decisions.md#the-reading-record-has-one-owner-and-it-is-a-second-privacy-rule) | 448 |
|  | [A write names what it made stale](decisions.md#a-write-names-what-it-made-stale) | 1,557 |
| A write names what it made stale | [A custom field renders as a link because the Library said so, and only if the value still is one](decisions.md#a-custom-field-renders-as-a-link-because-the-library-said-so-and-only-if-the-value-still-is-one) | 291 |
| A write names what it made stale | [Deleting a custom field is admin only, defining one is not](decisions.md#deleting-a-custom-field-is-admin-only-defining-one-is-not) | 341 |
| A write names what it made stale | [`MAX_CUSTOM_FIELDS` is the only ceiling the feature needs](decisions.md#max_custom_fields-is-the-only-ceiling-the-feature-needs) | 134 |
| A write names what it made stale | [Settings is an index of six routes, and the descriptions are the page](decisions.md#settings-is-an-index-of-six-routes-and-the-descriptions-are-the-page) | 433 |
|  | [Tooling](decisions.md#tooling) | 5,225 |
| Tooling | [Bun, not npm](decisions.md#bun-not-npm) | 27 |
| Tooling | [`bunfig.toml` configures a security scanner](decisions.md#bunfigtoml-configures-a-security-scanner) | 66 |
| Tooling | [`--import-mode=importlib` for pytest](decisions.md#--import-modeimportlib-for-pytest) | 10 |
| Tooling | [Alpine, and the musl bar for new dependencies](decisions.md#alpine-and-the-musl-bar-for-new-dependencies) | 86 |
| Tooling | [TypeScript's strictest options are on](decisions.md#typescripts-strictest-options-are-on) | 23 |
| Tooling | [Each test runs in a transaction, and pysqlite is not allowed to open it](decisions.md#each-test-runs-in-a-transaction-and-pysqlite-is-not-allowed-to-open-it) | 270 |
| Tooling | [Mutation testing is a tool a seat reaches for, and never a gate](decisions.md#mutation-testing-is-a-tool-a-seat-reaches-for-and-never-a-gate) | 220 |
| Tooling | [The baseline is an arm of the sweep, not a thing remembered from an earlier run](decisions.md#the-baseline-is-an-arm-of-the-sweep-not-a-thing-remembered-from-an-earlier-run) | 120 |
| Tooling | [The mutant generator is a library, and the sweep engine is not](decisions.md#the-mutant-generator-is-a-library-and-the-sweep-engine-is-not) | 148 |
| Tooling | [A verdict is read off the suite's own report, never off the words it printed](decisions.md#a-verdict-is-read-off-the-suites-own-report-never-off-the-words-it-printed) | 206 |
| Tooling | [A test asking which refusal fired reads the message off a channel the fixture owns, never a stream a runner formatted](decisions.md#a-test-asking-which-refusal-fired-reads-the-message-off-a-channel-the-fixture-owns-never-a-stream-a-runner-formatted) | 310 |
| Tooling | [A backticked test name is an assertion about a location, and a name that is gone loses its backticks](decisions.md#a-backticked-test-name-is-an-assertion-about-a-location-and-a-name-that-is-gone-loses-its-backticks) | 315 |
| Tooling | [The frontend has no sweep, and the route to one is recorded rather than built](decisions.md#the-frontend-has-no-sweep-and-the-route-to-one-is-recorded-rather-than-built) | 223 |
| Tooling | [A schema driven run over every operation, and what it is allowed to claim](decisions.md#a-schema-driven-run-over-every-operation-and-what-it-is-allowed-to-claim) | 639 |
| Tooling | [Three ways a response contradicted the schema that declares it, and one 500](decisions.md#three-ways-a-response-contradicted-the-schema-that-declares-it-and-one-500) | 649 |
| Tooling | [Every hand raised refusal is a sentence, so none of them may use 422](decisions.md#every-hand-raised-refusal-is-a-sentence-so-none-of-them-may-use-422) | 429 |
| Tooling | [A route that answers with no body documents none](decisions.md#a-route-that-answers-with-no-body-documents-none) | 311 |
| Tooling | [A route declares every answer it files, and no rule chooses between them](decisions.md#a-route-declares-every-answer-it-files-and-no-rule-chooses-between-them) | 277 |
| Tooling | [The truth about a partial answer is a second media type, not a second copy of the first](decisions.md#the-truth-about-a-partial-answer-is-a-second-media-type-not-a-second-copy-of-the-first) | 186 |
| Tooling | [Findings answered rather than fixed](decisions.md#findings-answered-rather-than-fixed) | 455 |
|  | [Reference implementations: what may be read, and what may not be copied](decisions.md#reference-implementations-what-may-be-read-and-what-may-not-be-copied) | 239 |
|  | [Product](decisions.md#product) | 2,230 |
| Product | [A count in a docstring is pinned by a test or it is not stated](decisions.md#a-count-in-a-docstring-is-pinned-by-a-test-or-it-is-not-stated) | 280 |
| Product | [A guard that enumerates its own universe goes quiet without failing](decisions.md#a-guard-that-enumerates-its-own-universe-goes-quiet-without-failing) | 167 |
| Product | [Small libraries and archives are a direction, not a second audience](decisions.md#small-libraries-and-archives-are-a-direction-not-a-second-audience) | 345 |
| Product | [Multi workstation is expected, and the shape is deliberately unchosen](decisions.md#multi-workstation-is-expected-and-the-shape-is-deliberately-unchosen) | 367 |
| Product | [The outward language names both audiences, and the claims stay staged](decisions.md#the-outward-language-names-both-audiences-and-the-claims-stay-staged) | 298 |
| Product | [The glossary names the operator only where it has to](decisions.md#the-glossary-names-the-operator-only-where-it-has-to) | 254 |
| Product | [German addresses the reader in neither register](decisions.md#german-addresses-the-reader-in-neither-register) | 176 |
| Product | [No bookshop or retailer is a catalogue source](decisions.md#no-bookshop-or-retailer-is-a-catalogue-source) | 252 |
|  | [Multi workstation is joined terminals, and the container stays the documented alternative](decisions.md#multi-workstation-is-joined-terminals-and-the-container-stays-the-documented-alternative) | 496 |
|  | [VIAF is the wrong supplier for resolution and the right one for discovery](decisions.md#viaf-is-the-wrong-supplier-for-resolution-and-the-right-one-for-discovery) | 447 |
|  | [An identifier two files disagree about is shown and never stored](decisions.md#an-identifier-two-files-disagree-about-is-shown-and-never-stored) | 16,793 |
| An identifier two files disagree about is shown and never stored | [VIAF was refused as a supplier and is used as an enrichment, and both are right](decisions.md#viaf-was-refused-as-a-supplier-and-is-used-as-an-enrichment-and-both-are-right) | 251 |
| An identifier two files disagree about is shown and never stored | [A VIAF cluster is verified against the confirmed record, never trusted](decisions.md#a-viaf-cluster-is-verified-against-the-confirmed-record-never-trusted) | 300 |
| An identifier two files disagree about is shown and never stored | [Storing an identifier and resolving one are different acts](decisions.md#storing-an-identifier-and-resolving-one-are-different-acts) | 173 |
| An identifier two files disagree about is shown and never stored | [The national identifiers have one route, and Wikidata is the fallback for it](decisions.md#the-national-identifiers-have-one-route-and-wikidata-is-the-fallback-for-it) | 142 |
| An identifier two files disagree about is shown and never stored | [A refusal test whose subject is a plausible future member is a countdown](decisions.md#a-refusal-test-whose-subject-is-a-plausible-future-member-is-a-countdown) | 178 |
| An identifier two files disagree about is shown and never stored | [The in app reminder is a sender, and it is the one that does not stamp `notified_at`](decisions.md#the-in-app-reminder-is-a-sender-and-it-is-the-one-that-does-not-stamp-notified_at) | 165 |
| An identifier two files disagree about is shown and never stored | [A sender includes exactly what its audience may see](decisions.md#a-sender-includes-exactly-what-its-audience-may-see) | 198 |
| An identifier two files disagree about is shown and never stored | [A new endpoint is classified for cache invalidation, or the inventory guard fails](decisions.md#a-new-endpoint-is-classified-for-cache-invalidation-or-the-inventory-guard-fails) | 96 |
| An identifier two files disagree about is shown and never stored | [One failed send is a network. Every send failing for a day is a configuration](decisions.md#one-failed-send-is-a-network-every-send-failing-for-a-day-is-a-configuration) | 593 |
| An identifier two files disagree about is shown and never stored | [YAZ is compiled, not packaged, and the image stays Alpine](decisions.md#yaz-is-compiled-not-packaged-and-the-image-stays-alpine) | 511 |
| An identifier two files disagree about is shown and never stored | [The YAZ builder image is named after what it is built from](decisions.md#the-yaz-builder-image-is-named-after-what-it-is-built-from) | 284 |
| An identifier two files disagree about is shown and never stored | [The runtime `COPY` shipped with the builder image, not with the transport](decisions.md#the-runtime-copy-shipped-with-the-builder-image-not-with-the-transport) | 188 |
| An identifier two files disagree about is shown and never stored | [The YAZ build id names what is built, never what it is built against](decisions.md#the-yaz-build-id-names-what-is-built-never-what-it-is-built-against) | 343 |
| An identifier two files disagree about is shown and never stored | [The YAZ pin is trust on first use, and nothing else watches it](decisions.md#the-yaz-pin-is-trust-on-first-use-and-nothing-else-watches-it) | 175 |
| An identifier two files disagree about is shown and never stored | [YAZ encrypts a TLS connection and does not authenticate it](decisions.md#yaz-encrypts-a-tls-connection-and-does-not-authenticate-it) | 141 |
| An identifier two files disagree about is shown and never stored | [A suite pod must not outlive the run that made it](decisions.md#a-suite-pod-must-not-outlive-the-run-that-made-it) | 219 |
| An identifier two files disagree about is shown and never stored | [The suite pod registry is untrusted, and what that bought is a bound rather than safety](decisions.md#the-suite-pod-registry-is-untrusted-and-what-that-bought-is-a-bound-rather-than-safety) | 310 |
| An identifier two files disagree about is shown and never stored | [A member's address is served only where it is named, and never on `UserOut`](decisions.md#a-members-address-is-served-only-where-it-is-named-and-never-on-userout) | 328 |
| An identifier two files disagree about is shown and never stored | [Who owns a member's address is a configuration lookup, not a column](decisions.md#who-owns-a-members-address-is-a-configuration-lookup-not-a-column) | 446 |
| An identifier two files disagree about is shown and never stored | [A guard is one mechanism, because two mechanisms have a seam](decisions.md#a-guard-is-one-mechanism-because-two-mechanisms-have-a-seam) | 242 |
| An identifier two files disagree about is shown and never stored | [One definition of what an address is, and it has to hold without its callers](decisions.md#one-definition-of-what-an-address-is-and-it-has-to-hold-without-its-callers) | 286 |
| An identifier two files disagree about is shown and never stored | [The public shelf has no ownership arm, rather than a sentinel viewer](decisions.md#the-public-shelf-has-no-ownership-arm-rather-than-a-sentinel-viewer) | 249 |
| An identifier two files disagree about is shown and never stored | [Publishing takes two switches, and the conjunction is on the server](decisions.md#publishing-takes-two-switches-and-the-conjunction-is-on-the-server) | 133 |
| An identifier two files disagree about is shown and never stored | [The public payload is a separate model, not `BookOut` with an exclusion list](decisions.md#the-public-payload-is-a-separate-model-not-bookout-with-an-exclusion-list) | 313 |
| An identifier two files disagree about is shown and never stored | [The `X-Robots-Tag` belongs in the middleware, not on the routes](decisions.md#the-x-robots-tag-belongs-in-the-middleware-not-on-the-routes) | 162 |
| An identifier two files disagree about is shown and never stored | [The public listing takes a subset of the filters, and a subset of the sorts](decisions.md#the-public-listing-takes-a-subset-of-the-filters-and-a-subset-of-the-sorts) | 173 |
| An identifier two files disagree about is shown and never stored | [The published `id` is the insert order, and that disclosure is accepted](decisions.md#the-published-id-is-the-insert-order-and-that-disclosure-is-accepted) | 210 |
| An identifier two files disagree about is shown and never stored | [`noindex` by default, because publishing and being crawled are two decisions](decisions.md#noindex-by-default-because-publishing-and-being-crawled-are-two-decisions) | 46 |
| An identifier two files disagree about is shown and never stored | [What "unreachable" was implemented as, and the two cases it deliberately excludes](decisions.md#what-unreachable-was-implemented-as-and-the-two-cases-it-deliberately-excludes) | 303 |
| An identifier two files disagree about is shown and never stored | [What the fallback refuses to store, and why it is not `_claim`](decisions.md#what-the-fallback-refuses-to-store-and-why-it-is-not-_claim) | 183 |
| An identifier two files disagree about is shown and never stored | [The budget moved and the statement moved with it](decisions.md#the-budget-moved-and-the-statement-moved-with-it) | 111 |
| An identifier two files disagree about is shown and never stored | [The author card links out to Wikipedia, and the language is resolved rather than guessed](decisions.md#the-author-card-links-out-to-wikipedia-and-the-language-is-resolved-rather-than-guessed) | 466 |
| An identifier two files disagree about is shown and never stored | [The Z39.50 transport is a seam, and the client behind it is not chosen yet](decisions.md#the-z3950-transport-is-a-seam-and-the-client-behind-it-is-not-chosen-yet) | 295 |
| An identifier two files disagree about is shown and never stored | [The blur calibration is a test now, because the eleventh pattern arrived as six](decisions.md#the-blur-calibration-is-a-test-now-because-the-eleventh-pattern-arrived-as-six) | 304 |
| An identifier two files disagree about is shown and never stored | [A displacement field repeats with the tile when its supports are disjoint](decisions.md#a-displacement-field-repeats-with-the-tile-when-its-supports-are-disjoint) | 229 |
| An identifier two files disagree about is shown and never stored | [Curl is Nonpareil worked a second time, and that is the point rather than a shortcut](decisions.md#curl-is-nonpareil-worked-a-second-time-and-that-is-the-point-rather-than-a-shortcut) | 168 |
| An identifier two files disagree about is shown and never stored | [Golden Lily is John Henry Dearle's, not William Morris's](decisions.md#golden-lily-is-john-henry-dearles-not-william-morriss) | 52 |
| An identifier two files disagree about is shown and never stored | [A claim survives review when the evidence that would test it is not on the line](decisions.md#a-claim-survives-review-when-the-evidence-that-would-test-it-is-not-on-the-line) | 153 |
| An identifier two files disagree about is shown and never stored | [A Z39.50 target is three separate questions, and the third one fails silently](decisions.md#a-z3950-target-is-three-separate-questions-and-the-third-one-fails-silently) | 229 |
| An identifier two files disagree about is shown and never stored | [A red line in the survey is a moment, not a verdict](decisions.md#a-red-line-in-the-survey-is-a-moment-not-a-verdict) | 159 |
| An identifier two files disagree about is shown and never stored | [Published catalogue lists rot, and a `gaierror` is a claim about a string](decisions.md#published-catalogue-lists-rot-and-a-gaierror-is-a-claim-about-a-string) | 182 |
| An identifier two files disagree about is shown and never stored | [A load bearing operational fact may not live only in a file that gets deleted](decisions.md#a-load-bearing-operational-fact-may-not-live-only-in-a-file-that-gets-deleted) | 121 |
| An identifier two files disagree about is shown and never stored | [Where a credential is published by the library itself, that is a decision and not a measurement](decisions.md#where-a-credential-is-published-by-the-library-itself-that-is-a-decision-and-not-a-measurement) | 189 |
| An identifier two files disagree about is shown and never stored | [The Alma gateway cannot be enumerated](decisions.md#the-alma-gateway-cannot-be-enumerated) | 74 |
| An identifier two files disagree about is shown and never stored | [A generator may not read its own output](decisions.md#a-generator-may-not-read-its-own-output) | 228 |
| An identifier two files disagree about is shown and never stored | [Three palettes chosen by licence and by measured distance, not by taste](decisions.md#three-palettes-chosen-by-licence-and-by-measured-distance-not-by-taste) | 484 |
| An identifier two files disagree about is shown and never stored | [The channel record lives in two places, and they answer two questions](decisions.md#the-channel-record-lives-in-two-places-and-they-answer-two-questions) | 341 |
| An identifier two files disagree about is shown and never stored | [The overdue page reads `overdue_for_viewer`, not the loans list with a filter](decisions.md#the-overdue-page-reads-overdue_for_viewer-not-the-loans-list-with-a-filter) | 354 |
| An identifier two files disagree about is shown and never stored | [The channel panel may not claim anything about this page](decisions.md#the-channel-panel-may-not-claim-anything-about-this-page) | 109 |
| An identifier two files disagree about is shown and never stored | [The channel record has three states, and a nullable list is two](decisions.md#the-channel-record-has-three-states-and-a-nullable-list-is-two) | 62 |
| An identifier two files disagree about is shown and never stored | [A count and a capped list may not appear on one screen without saying so](decisions.md#a-count-and-a-capped-list-may-not-appear-on-one-screen-without-saying-so) | 180 |
| An identifier two files disagree about is shown and never stored | [A banner may not say "your" where the viewer is an admin](decisions.md#a-banner-may-not-say-your-where-the-viewer-is-an-admin) | 77 |
| An identifier two files disagree about is shown and never stored | [`LoanRowSkeleton` exists because the placeholder drifts from the row](decisions.md#loanrowskeleton-exists-because-the-placeholder-drifts-from-the-row) | 99 |
| An identifier two files disagree about is shown and never stored | [The health line's docstring said the thing the page exists to deny](decisions.md#the-health-lines-docstring-said-the-thing-the-page-exists-to-deny) | 73 |
| An identifier two files disagree about is shown and never stored | [`en.ts` is the source of truth, so a hint fixed in German only is a hint not fixed](decisions.md#ents-is-the-source-of-truth-so-a-hint-fixed-in-german-only-is-a-hint-not-fixed) | 52 |
| An identifier two files disagree about is shown and never stored | [A check that cannot find its input has not passed](decisions.md#a-check-that-cannot-find-its-input-has-not-passed) | 178 |
| An identifier two files disagree about is shown and never stored | [Prose inside an unquoted heredoc is code](decisions.md#prose-inside-an-unquoted-heredoc-is-code) | 118 |
| An identifier two files disagree about is shown and never stored | [An eager load is kept because a measurement asks for it, not because the route beside it has one](decisions.md#an-eager-load-is-kept-because-a-measurement-asks-for-it-not-because-the-route-beside-it-has-one) | 740 |
| An identifier two files disagree about is shown and never stored | [A ceiling cannot see a statement removed](decisions.md#a-ceiling-cannot-see-a-statement-removed) | 78 |
| An identifier two files disagree about is shown and never stored | [Headings are ANDed and Dewey divisions are ORed, in one filter](decisions.md#headings-are-anded-and-dewey-divisions-are-ored-in-one-filter) | 131 |
| An identifier two files disagree about is shown and never stored | [Only Dewey gets a sort, because only Dewey sorts](decisions.md#only-dewey-gets-a-sort-because-only-dewey-sorts) | 150 |
| An identifier two files disagree about is shown and never stored | [A projection that trusts a comment is a fail open filter](decisions.md#a-projection-that-trusts-a-comment-is-a-fail-open-filter) | 214 |
| An identifier two files disagree about is shown and never stored | [A bound stated in a docstring is not a bound](decisions.md#a-bound-stated-in-a-docstring-is-not-a-bound) | 141 |
| An identifier two files disagree about is shown and never stored | [Settled by the owner, and not a seat's to reopen](decisions.md#settled-by-the-owner-and-not-a-seats-to-reopen) | 195 |
| An identifier two files disagree about is shown and never stored | [An apk finding is acted on, because the rebuild is the fix and a digest bump is not](decisions.md#an-apk-finding-is-acted-on-because-the-rebuild-is-the-fix-and-a-digest-bump-is-not) | 385 |
| An identifier two files disagree about is shown and never stored | [One CVE against two ecosystems is two findings](decisions.md#one-cve-against-two-ecosystems-is-two-findings) | 161 |
| An identifier two files disagree about is shown and never stored | [The ledger reads one line, not the whole tag message](decisions.md#the-ledger-reads-one-line-not-the-whole-tag-message) | 135 |
| An identifier two files disagree about is shown and never stored | [A `$` anchored pattern is not a `fullmatch`](decisions.md#a--anchored-pattern-is-not-a-fullmatch) | 43 |
| An identifier two files disagree about is shown and never stored | [A rebuild finding is not ledgered, so a failed rebuild is retried](decisions.md#a-rebuild-finding-is-not-ledgered-so-a-failed-rebuild-is-retried) | 150 |
| An identifier two files disagree about is shown and never stored | [The ledger key names the ecosystem](decisions.md#the-ledger-key-names-the-ecosystem) | 120 |
| An identifier two files disagree about is shown and never stored | [An advisory id is one whitespace free token](decisions.md#an-advisory-id-is-one-whitespace-free-token) | 73 |
| An identifier two files disagree about is shown and never stored | [A rebuild release builds with the kaniko cache off](decisions.md#a-rebuild-release-builds-with-the-kaniko-cache-off) | 176 |
| An identifier two files disagree about is shown and never stored | [A finding with no advisory id is refused](decisions.md#a-finding-with-no-advisory-id-is-refused) | 65 |
| An identifier two files disagree about is shown and never stored | [A guard proved on one validated field, then trusted for the fields beside it](decisions.md#a-guard-proved-on-one-validated-field-then-trusted-for-the-fields-beside-it) | 333 |
|  | [Open, and not resolved in this ticket](decisions.md#open-and-not-resolved-in-this-ticket) | 1,234 |
| Open, and not resolved in this ticket | [The provider order is the order sources are asked, and nothing else](decisions.md#the-provider-order-is-the-order-sources-are-asked-and-nothing-else) | 217 |
| Open, and not resolved in this ticket | [The tier a source is asked in is a position, not a property of the source](decisions.md#the-tier-a-source-is-asked-in-is-a-position-not-a-property-of-the-source) | 162 |
| Open, and not resolved in this ticket | [Google Books has two switches and they are conjoined in one place](decisions.md#google-books-has-two-switches-and-they-are-conjoined-in-one-place) | 118 |
| Open, and not resolved in this ticket | [The provider list does not reach the cover and authority hosts](decisions.md#the-provider-list-does-not-reach-the-cover-and-authority-hosts) | 76 |
| Open, and not resolved in this ticket | [A source that cannot answer says which of two things is wrong](decisions.md#a-source-that-cannot-answer-says-which-of-two-things-is-wrong) | 63 |
| Open, and not resolved in this ticket | [An evasion attempt is bounded by the shapes its author imagines](decisions.md#an-evasion-attempt-is-bounded-by-the-shapes-its-author-imagines) | 180 |
| Open, and not resolved in this ticket | [A paragraph describing behaviour is not re-read when the behaviour changes](decisions.md#a-paragraph-describing-behaviour-is-not-re-read-when-the-behaviour-changes) | 181 |
|  | [MARC21 import and export](decisions.md#marc21-import-and-export) | 10,303 |
| MARC21 import and export | [MARC is read through `metadata.py`'s parser, not a second one](decisions.md#marc-is-read-through-metadatapys-parser-not-a-second-one) | 209 |
| MARC21 import and export | [What `marc.py` refuses is deliberately narrower than what a lookup refuses](decisions.md#what-marcpy-refuses-is-deliberately-narrower-than-what-a-lookup-refuses) | 110 |
| MARC21 import and export | [An oversized MARC file is refused, where an oversized CSV is truncated](decisions.md#an-oversized-marc-file-is-refused-where-an-oversized-csv-is-truncated) | 62 |
| MARC21 import and export | [The MARCXML export is paged rather than capped](decisions.md#the-marcxml-export-is-paged-rather-than-capped) | 1,035 |
| MARC21 import and export | [Every export arm walks the same pages](decisions.md#every-export-arm-walks-the-same-pages) | 723 |
| MARC21 import and export | [Library mode is enforced on the server for MARC, at 403](decisions.md#library-mode-is-enforced-on-the-server-for-marc-at-403) | 83 |
| MARC21 import and export | [One line a member typed: three rules, and which field takes which](decisions.md#one-line-a-member-typed-three-rules-and-which-field-takes-which) | 844 |
| MARC21 import and export | [`classifications.py` exists because a ceiling with two implementations is not one](decisions.md#classificationspy-exists-because-a-ceiling-with-two-implementations-is-not-one) | 48 |
| MARC21 import and export | [A stored `classifications.scheme` is a `str`, and comparing it with `is` fails silently](decisions.md#a-stored-classificationsscheme-is-a-str-and-comparing-it-with-is-fails-silently) | 99 |
| MARC21 import and export | [No `008` in an exported record](decisions.md#no-008-in-an-exported-record) | 84 |
| MARC21 import and export | [The MARC importer applies the API's own bounds, read off the declarations](decisions.md#the-marc-importer-applies-the-apis-own-bounds-read-off-the-declarations) | 1,166 |
| MARC21 import and export | [A guard's fixture has to reference the thing the guard stops](decisions.md#a-guards-fixture-has-to-reference-the-thing-the-guard-stops) | 115 |
| MARC21 import and export | [No module reads another module's private names](decisions.md#no-module-reads-another-modules-private-names) | 458 |
| MARC21 import and export | [`isbn` is never gap-filled onto a matched Book, and that is what stops a 500](decisions.md#isbn-is-never-gap-filled-onto-a-matched-book-and-that-is-what-stops-a-500) | 408 |
| MARC21 import and export | [The MARC preview publishes an ISBN existence oracle, and it is accepted](decisions.md#the-marc-preview-publishes-an-isbn-existence-oracle-and-it-is-accepted) | 254 |
| MARC21 import and export | [The shelf loads what the row needs, not what the serialiser will load anyway](decisions.md#the-shelf-loads-what-the-row-needs-not-what-the-serialiser-will-load-anyway) | 393 |
| MARC21 import and export | [Three national catalogues speak SRU over HTTP, so they need no Z39.50 client](decisions.md#three-national-catalogues-speak-sru-over-http-so-they-need-no-z3950-client) | 444 |
| MARC21 import and export | [Greece serves MARC21, not UNIMARC, and it is a different host](decisions.md#greece-serves-marc21-not-unimarc-and-it-is-a-different-host) | 311 |
| MARC21 import and export | [A miss rate is not a gain: the candidate has to hold the book too](decisions.md#a-miss-rate-is-not-a-gain-the-candidate-has-to-hold-the-book-too) | 256 |
| MARC21 import and export | [The DNB and the OENB answer almost nothing outside German publishing, and both are in the default first tier](decisions.md#the-dnb-and-the-oenb-answer-almost-nothing-outside-german-publishing-and-both-are-in-the-default-first-tier) | 301 |
| MARC21 import and export | [Most of the coverage the tree credits to the chain is Google Books, and most installations have no key](decisions.md#most-of-the-coverage-the-tree-credits-to-the-chain-is-google-books-and-most-installations-have-no-key) | 155 |
| MARC21 import and export | [A national library does not hold every ISBN in its own registration group](decisions.md#a-national-library-does-not-hold-every-isbn-in-its-own-registration-group) | 77 |
| MARC21 import and export | [The Library of Congress is credited with the wrong countries](decisions.md#the-library-of-congress-is-credited-with-the-wrong-countries) | 291 |
| MARC21 import and export | [Argentina and Uruguay will be covered, using the credentials their libraries publish](decisions.md#argentina-and-uruguay-will-be-covered-using-the-credentials-their-libraries-publish) | 449 |
| MARC21 import and export | [A number, once written down, stops being re-derived and starts being copied](decisions.md#a-number-once-written-down-stops-being-re-derived-and-starts-being-copied) | 362 |
| MARC21 import and export | [A finding that rests on a mechanism should say what guards that mechanism](decisions.md#a-finding-that-rests-on-a-mechanism-should-say-what-guards-that-mechanism) | 316 |
| MARC21 import and export | [An SRU source built on PQF may not build its own query string](decisions.md#an-sru-source-built-on-pqf-may-not-build-its-own-query-string) | 417 |
| MARC21 import and export | [A source that is not UTF-8 corrupts a shelf rather than failing a search](decisions.md#a-source-that-is-not-utf-8-corrupts-a-shelf-rather-than-failing-a-search) | 418 |
|  | [The cataloguer's column set](decisions.md#the-cataloguers-column-set) | 1,687 |
| The cataloguer's column set | [The call number is Dewey and Library of Congress, the subjects are GND and LCSH](decisions.md#the-call-number-is-dewey-and-library-of-congress-the-subjects-are-gnd-and-lcsh) | 198 |
| The cataloguer's column set | [Sorting the call number sorts the classification, never the cell](decisions.md#sorting-the-call-number-sorts-the-classification-never-the-cell) | 106 |
| The cataloguer's column set | [There is no record status column, and the promise of one is withdrawn](decisions.md#there-is-no-record-status-column-and-the-promise-of-one-is-withdrawn) | 268 |
| The cataloguer's column set | [One spec table per column, not a label map beside two lists of keys](decisions.md#one-spec-table-per-column-not-a-label-map-beside-two-lists-of-keys) | 223 |
| The cataloguer's column set | [The column set is per mode, in two localStorage keys](decisions.md#the-column-set-is-per-mode-in-two-localstorage-keys) | 393 |
| The cataloguer's column set | [One table of scheme labels, because there were about to be three](decisions.md#one-table-of-scheme-labels-because-there-were-about-to-be-three) | 53 |
| The cataloguer's column set | [A count is not a fact about a file until it says which tree it describes](decisions.md#a-count-is-not-a-fact-about-a-file-until-it-says-which-tree-it-describes) | 126 |
| The cataloguer's column set | [A refusal belongs where somebody would go to propose it again](decisions.md#a-refusal-belongs-where-somebody-would-go-to-propose-it-again) | 75 |
| The cataloguer's column set | [Check the shape of a scripted edit's result, not its exit code](decisions.md#check-the-shape-of-a-scripted-edits-result-not-its-exit-code) | 83 |
|  | [The default source order, and what an order can and cannot buy](decisions.md#the-default-source-order-and-what-an-order-can-and-cannot-buy) | 2,547 |
| The default source order, and what an order can and cannot buy | [The first tier is a latency budget, and no order of the roster covers more](decisions.md#the-first-tier-is-a-latency-budget-and-no-order-of-the-roster-covers-more) | 226 |
| The default source order, and what an order can and cannot buy | [The ticket's own premise did not survive re-derivation, and three of its four claims were wrong](decisions.md#the-tickets-own-premise-did-not-survive-re-derivation-and-three-of-its-four-claims-were-wrong) | 220 |
| The default source order, and what an order can and cannot buy | [The ÖNB's justifying measurement measured a different population](decisions.md#the-önbs-justifying-measurement-measured-a-different-population) | 320 |
| The default source order, and what an order can and cannot buy | [Three slots asked together was measured and refused, on 0.061s](decisions.md#three-slots-asked-together-was-measured-and-refused-on-0061s) | 191 |
| The default source order, and what an order can and cannot buy | [Most of the chain's coverage is Google Books, and most installs have no key](decisions.md#most-of-the-chains-coverage-is-google-books-and-most-installs-have-no-key) | 195 |
| The default source order, and what an order can and cannot buy | [The evidence behind a stated bound has to live where the bound does](decisions.md#the-evidence-behind-a-stated-bound-has-to-live-where-the-bound-does) | 255 |
| The default source order, and what an order can and cannot buy | [A guard proved on one property, then trusted for the property beside it, for the third time in one file](decisions.md#a-guard-proved-on-one-property-then-trusted-for-the-property-beside-it-for-the-third-time-in-one-file) | 209 |
| The default source order, and what an order can and cannot buy | [A fix a critic hands you is itself a first draft](decisions.md#a-fix-a-critic-hands-you-is-itself-a-first-draft) | 92 |
| The default source order, and what an order can and cannot buy | [A docstring in a published test may not cite a session path](decisions.md#a-docstring-in-a-published-test-may-not-cite-a-session-path) | 217 |
| The default source order, and what an order can and cannot buy | [The source order guard's dict arm: a structural rewrite, tried and reverted](decisions.md#the-source-order-guards-dict-arm-a-structural-rewrite-tried-and-reverted) | 302 |
| The default source order, and what an order can and cannot buy | [Two seats made the same mistake in opposite directions](decisions.md#two-seats-made-the-same-mistake-in-opposite-directions) | 128 |
|  | [A test that loops holds one log record per iteration](decisions.md#a-test-that-loops-holds-one-log-record-per-iteration) | 128 |
|  | [The National Library of Greece, and the rule that was refusing its records](decisions.md#the-national-library-of-greece-and-the-rule-that-was-refusing-its-records) | 2,147 |
| The National Library of Greece, and the rule that was refusing its records | [`020 $q` is a qualifier about this record's item, and refusing it lost the book](decisions.md#020-q-is-a-qualifier-about-this-records-item-and-refusing-it-lost-the-book) | 352 |
| The National Library of Greece, and the rule that was refusing its records | [Matching an ISBN and choosing one are two questions, and only the first is safe to answer](decisions.md#matching-an-isbn-and-choosing-one-are-two-questions-and-only-the-first-is-safe-to-answer) | 200 |
| The National Library of Greece, and the rule that was refusing its records | [An inline qualifier is the same qualifier, and reading it needs both halves](decisions.md#an-inline-qualifier-is-the-same-qualifier-and-reading-it-needs-both-halves) | 789 |
| The National Library of Greece, and the rule that was refusing its records | [A pooled union over a country stratified sample is the wrong instrument for the first tier](decisions.md#a-pooled-union-over-a-country-stratified-sample-is-the-wrong-instrument-for-the-first-tier) | 261 |
| The National Library of Greece, and the rule that was refusing its records | [The tail's two candidate rules came apart, exactly where the guard said they would](decisions.md#the-tails-two-candidate-rules-came-apart-exactly-where-the-guard-said-they-would) | 137 |
| The National Library of Greece, and the rule that was refusing its records | [The National Library of Greece is plaintext too, and the identity check is what that costs](decisions.md#the-national-library-of-greece-is-plaintext-too-and-the-identity-check-is-what-that-costs) | 258 |
|  | [An address at account creation](decisions.md#an-address-at-account-creation) | 511 |
| An address at account creation | [An email address belongs to creating an account, and a directory account has no creation moment to attach one to](decisions.md#an-email-address-belongs-to-creating-an-account-and-a-directory-account-has-no-creation-moment-to-attach-one-to) | 490 |
|  | [What the three seats caught, this wave](decisions.md#what-the-three-seats-caught-this-wave) | 397 |
| What the three seats caught, this wave | [A fix round wrote an unmeasured reason into the paragraph about unmeasured reasons](decisions.md#a-fix-round-wrote-an-unmeasured-reason-into-the-paragraph-about-unmeasured-reasons) | 211 |
| What the three seats caught, this wave | [Both critic seats found the same two things, from opposite ends](decisions.md#both-critic-seats-found-the-same-two-things-from-opposite-ends) | 160 |
|  | [The Czech National Library, and a server that renders one record a page](decisions.md#the-czech-national-library-and-a-server-that-renders-one-record-a-page) | 1,698 |
| The Czech National Library, and a server that renders one record a page | [The search path is refused because the server renders one record per response](decisions.md#the-search-path-is-refused-because-the-server-renders-one-record-per-response) | 273 |
| The Czech National Library, and a server that renders one record a page | [The ticket named the shape correctly, and the first fix dismissed it](decisions.md#the-ticket-named-the-shape-correctly-and-the-first-fix-dismissed-it) | 372 |
| The Czech National Library, and a server that renders one record a page | [The tier rule counts concentration, not frames](decisions.md#the-tier-rule-counts-concentration-not-frames) | 358 |
| The Czech National Library, and a server that renders one record a page | [An internal document declares itself, and the publish gate checks both directions](decisions.md#an-internal-document-declares-itself-and-the-publish-gate-checks-both-directions) | 251 |
| The Czech National Library, and a server that renders one record a page | [The Czech catalogue is plaintext, and it is on the scan path](decisions.md#the-czech-catalogue-is-plaintext-and-it-is-on-the-scan-path) | 211 |
| The Czech National Library, and a server that renders one record a page | [A refusal written in two languages was refusing in two languages](decisions.md#a-refusal-written-in-two-languages-was-refusing-in-two-languages) | 160 |
|  | [The committed client is generated only by the pinned toolchain, and the script enforces it](decisions.md#the-committed-client-is-generated-only-by-the-pinned-toolchain-and-the-script-enforces-it) | 663 |
|  | [A national catalogue is asked only about the registration groups it collects](decisions.md#a-national-catalogue-is-asked-only-about-the-registration-groups-it-collects) | 852 |
|  | [An `isdigit()` guard does not make an `int()` safe](decisions.md#an-isdigit-guard-does-not-make-an-int-safe) | 140 |
|  | [A subject carries the vocabulary a record declared, and the store is a separate question](decisions.md#a-subject-carries-the-vocabulary-a-record-declared-and-the-store-is-a-separate-question) | 346 |
|  | [`$2` is read on a subject field only, and the signature is what says so](decisions.md#2-is-read-on-a-subject-field-only-and-the-signature-is-what-says-so) | 269 |
|  | [The vocabulary code is lower cased for `marc._extra_headings`, not for the catalogues](decisions.md#the-vocabulary-code-is-lower-cased-for-marc_extra_headings-not-for-the-catalogues) | 107 |
|  | [An undeclared repeat folds away only when it adds nothing](decisions.md#an-undeclared-repeat-folds-away-only-when-it-adds-nothing) | 158 |
|  | [A subject label keeps the place of its first occurrence](decisions.md#a-subject-label-keeps-the-place-of-its-first-occurrence) | 105 |
|  | [The first `$0` is the authority file's number, and `Subfields.gnd_identifier` asks a different question](decisions.md#the-first-0-is-the-authority-files-number-and-subfieldsgnd_identifier-asks-a-different-question) | 316 |
|  | [A label under two vocabularies is two subjects; a label restated undeclared is one](decisions.md#a-label-under-two-vocabularies-is-two-subjects-a-label-restated-undeclared-is-one) | 154 |
|  | [`$2` means a vocabulary on a subject field and a Dewey edition on `082`](decisions.md#2-means-a-vocabulary-on-a-subject-field-and-a-dewey-edition-on-082) | 2,117 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [Every Python file is compiled, and the warning is recorded rather than raised](decisions.md#every-python-file-is-compiled-and-the-warning-is-recorded-rather-than-raised) | 448 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [Every field a request body carries is bounded, and the value comes from one place each](decisions.md#every-field-a-request-body-carries-is-bounded-and-the-value-comes-from-one-place-each) | 815 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [The guard is three questions asked of every request body, not a table of fields](decisions.md#the-guard-is-three-questions-asked-of-every-request-body-not-a-table-of-fields) | 50 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [`BodySizeLimitMiddleware` promises a bound it does not apply, and the gap is stated](decisions.md#bodysizelimitmiddleware-promises-a-bound-it-does-not-apply-and-the-gap-is-stated) | 89 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [Two bounds this entry does not close](decisions.md#two-bounds-this-entry-does-not-close) | 154 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [The roster count is guarded by a census with a verdict, not by a scan and not by a list](decisions.md#the-roster-count-is-guarded-by-a-census-with-a-verdict-not-by-a-scan-and-not-by-a-list) | 709 |
| `$2` means a vocabulary on a subject field and a Dewey edition on `082` | [The hole a reviewer should know about](decisions.md#the-hole-a-reviewer-should-know-about) | 52 |
|  | [A stale count outside the census grammar is fixed by rewriting the sentence, not by widening the census](decisions.md#a-stale-count-outside-the-census-grammar-is-fixed-by-rewriting-the-sentence-not-by-widening-the-census) | 278 |
|  | [Four figures in the roster census are snapshots rather than recomputed, deliberately](decisions.md#four-figures-in-the-roster-census-are-snapshots-rather-than-recomputed-deliberately) | 172 |
|  | [`merge_into` takes a `BookMatch`, not a dictionary](decisions.md#merge_into-takes-a-bookmatch-not-a-dictionary) | 183 |
|  | [The enrichment door drops the field; the search door drops the row](decisions.md#the-enrichment-door-drops-the-field-the-search-door-drops-the-row) | 360 |
|  | [The three doors over `books.categories`, and why they differ](decisions.md#the-three-doors-over-bookscategories-and-why-they-differ) | 2,290 |
| The three doors over `books.categories`, and why they differ | [The 422 is unreachable from an honest producer today, and that is a precondition rather than a note](decisions.md#the-422-is-unreachable-from-an-honest-producer-today-and-that-is-a-precondition-rather-than-a-note) | 141 |
| The three doors over `books.categories`, and why they differ | [The frequency measurement was withdrawn, and where a split would live if it is ever run](decisions.md#the-frequency-measurement-was-withdrawn-and-where-a-split-would-live-if-it-is-ever-run) | 113 |
| The three doors over `books.categories`, and why they differ | [The bound is two named factors, and both are literals](decisions.md#the-bound-is-two-named-factors-and-both-are-literals) | 263 |
| The three doors over `books.categories`, and why they differ | [The write has an unwrite, and it is an empty list](decisions.md#the-write-has-an-unwrite-and-it-is-an-empty-list) | 344 |
| The three doors over `books.categories`, and why they differ | [The second writer of a reshaped column arrives at a door with no refusal on it](decisions.md#the-second-writer-of-a-reshaped-column-arrives-at-a-door-with-no-refusal-on-it) | 184 |
| The three doors over `books.categories`, and why they differ | [One demand declined, with the reason, because its only other home is deleted](decisions.md#one-demand-declined-with-the-reason-because-its-only-other-home-is-deleted) | 76 |
| The three doors over `books.categories`, and why they differ | [`categories` is deliberately absent from the MARC importer's field list](decisions.md#categories-is-deliberately-absent-from-the-marc-importers-field-list) | 91 |
|  | [A guard that names two enforcers and has one](decisions.md#a-guard-that-names-two-enforcers-and-has-one) | 160 |
|  | [The series ceiling is applied at the reader as well as at the writers](decisions.md#the-series-ceiling-is-applied-at-the-reader-as-well-as-at-the-writers) | 234 |
|  | [The record's own carrier code decides, and prose is the fallback](decisions.md#the-records-own-carrier-code-decides-and-prose-is-the-fallback) | 257 |
|  | [A catalogue record is bounded at construction, not at each door](decisions.md#a-catalogue-record-is-bounded-at-construction-not-at-each-door) | 485 |
|  | [Two producers of one record, and they differ about one thing](decisions.md#two-producers-of-one-record-and-they-differ-about-one-thing) | 225 |
|  | [A slow catalogue is kept and made opt-in, behind an explicit second search](decisions.md#a-slow-catalogue-is-kept-and-made-opt-in-behind-an-explicit-second-search) | 258 |
|  | [The slow marking ships empty, and that is a measurement](decisions.md#the-slow-marking-ships-empty-and-that-is-a-measurement) | 214 |
|  | [The longer deadline is separate, bounded, and its margin is chosen rather than measured](decisions.md#the-longer-deadline-is-separate-bounded-and-its-margin-is-chosen-rather-than-measured) | 128 |
|  | [The answer says what was asked, rather than the request implying it](decisions.md#the-answer-says-what-was-asked-rather-than-the-request-implying-it) | 151 |
|  | [The longer fan out is bounded by concurrency, and the bound never waits](decisions.md#the-longer-fan-out-is-bounded-by-concurrency-and-the-bound-never-waits) | 902 |
| The longer fan out is bounded by concurrency, and the bound never waits | [The backfill waits where the search refuses, and a deadline is what buys the wait](decisions.md#the-backfill-waits-where-the-search-refuses-and-a-deadline-is-what-buys-the-wait) | 701 |
|  | [Asking nothing has two causes, and the answer has to tell them apart](decisions.md#asking-nothing-has-two-causes-and-the-answer-has-to-tell-them-apart) | 253 |
|  | [The refused long search names our own limit, not the catalogues'](decisions.md#the-refused-long-search-names-our-own-limit-not-the-catalogues) | 3,975 |
| The refused long search names our own limit, not the catalogues' | [A scheme says how its own call numbers sort, and a scheme with no rule sorts as text](decisions.md#a-scheme-says-how-its-own-call-numbers-sort-and-a-scheme-with-no-rule-sorts-as-text) | 846 |
| The refused long search names our own limit, not the catalogues' | [A catalogue source is a row, and its parser is not](decisions.md#a-catalogue-source-is-a-row-and-its-parser-is-not) | 201 |
| The refused long search names our own limit, not the catalogues' | [The runtime asks the constant, and the table waits for the ticket that edits it](decisions.md#the-runtime-asks-the-constant-and-the-table-waits-for-the-ticket-that-edits-it) | 157 |
| The refused long search names our own limit, not the catalogues' | [An invariant a restore can reach is a CHECK constraint or it is nothing](decisions.md#an-invariant-a-restore-can-reach-is-a-check-constraint-or-it-is-nothing) | 129 |
| The refused long search names our own limit, not the catalogues' | [The roster guard changed shape because the question did](decisions.md#the-roster-guard-changed-shape-because-the-question-did) | 120 |
| The refused long search names our own limit, not the catalogues' | [What the guard learned from being attacked](decisions.md#what-the-guard-learned-from-being-attacked) | 189 |
| The refused long search names our own limit, not the catalogues' | [The frontend suite shares one environment, and `tests/doubles/` is what pays for it](decisions.md#the-frontend-suite-shares-one-environment-and-testsdoubles-is-what-pays-for-it) | 448 |
| The refused long search names our own limit, not the catalogues' | [The backend suite is twice as slow in CI as in an identical pod, and three obvious reasons are not it](decisions.md#the-backend-suite-is-twice-as-slow-in-ci-as-in-an-identical-pod-and-three-obvious-reasons-are-not-it) | 424 |
| The refused long search names our own limit, not the catalogues' | [The runner checks its image against the pipeline for both toolchains, not one](decisions.md#the-runner-checks-its-image-against-the-pipeline-for-both-toolchains-not-one) | 451 |
| The refused long search names our own limit, not the catalogues' | [What the pipeline now reports about its own CPU](decisions.md#what-the-pipeline-now-reports-about-its-own-cpu) | 622 |
|  | [The library view is remembered per mode, and the household's key kept its name](decisions.md#the-library-view-is-remembered-per-mode-and-the-households-key-kept-its-name) | 395 |
|  | [The SRU server borrows the public catalogue's gate rather than growing one](decisions.md#the-sru-server-borrows-the-public-catalogues-gate-rather-than-growing-one) | 149 |
|  | [The column boundary for a MARC record is `marc.py`'s field mapping, and it is now pinned](decisions.md#the-column-boundary-for-a-marc-record-is-marcpys-field-mapping-and-it-is-now-pinned) | 173 |
|  | [Masking is supported because SQLite's LIKE does not backtrack](decisions.md#masking-is-supported-because-sqlites-like-does-not-backtrack) | 304 |
|  | [The query bound is a cost budget, because a count of predicates is not a cost](decisions.md#the-query-bound-is-a-cost-budget-because-a-count-of-predicates-is-not-a-cost) | 238 |
|  | [The SRU response bound is charged in bytes, and the row count is not that bound](decisions.md#the-sru-response-bound-is-charged-in-bytes-and-the-row-count-is-not-that-bound) | 1,006 |
|  | [An integer the storage engine cannot hold was three unauthenticated 500s](decisions.md#an-integer-the-storage-engine-cannot-hold-was-three-unauthenticated-500s) | 216 |
|  | [A filter is a read of its column, and only the record writer was guarded](decisions.md#a-filter-is-a-read-of-its-column-and-only-the-record-writer-was-guarded) | 93 |
|  | [`explain` reads the `Host` header directly, and not `request.url`](decisions.md#explain-reads-the-host-header-directly-and-not-requesturl) | 170 |
|  | [The diagnostic numbers were checked against a second implementation, and four changed](decisions.md#the-diagnostic-numbers-were-checked-against-a-second-implementation-and-four-changed) | 259 |
|  | [`dc.subject` searches tags, and classification headings are not indexed](decisions.md#dcsubject-searches-tags-and-classification-headings-are-not-indexed) | 101 |
|  | [The one catalogue record scalar that is deliberately unbounded](decisions.md#the-one-catalogue-record-scalar-that-is-deliberately-unbounded) | 176 |
|  | [A catalogue record's ISBN is bounded, and what makes that safe](decisions.md#a-catalogue-records-isbn-is-bounded-and-what-makes-that-safe) | 403 |
|  | [A request body bounds the cover URL it stores, not the one it receives](decisions.md#a-request-body-bounds-the-cover-url-it-stores-not-the-one-it-receives) | 289 |
|  | [Which columns an import may fill, column by column](decisions.md#which-columns-an-import-may-fill-column-by-column) | 652 |
|  | [Which authority schemes exist, and why the list is code rather than rows](decisions.md#which-authority-schemes-exist-and-why-the-list-is-code-rather-than-rows) | 401 |
|  | [Storing an identifier and resolving one are different acts](decisions.md#storing-an-identifier-and-resolving-one-are-different-acts-1) | 246 |
|  | [The Z39.50 door's bounds, and which of fetch.py's four have no counterpart](decisions.md#the-z3950-doors-bounds-and-which-of-fetchpys-four-have-no-counterpart) | 658 |
|  | [UNIMARC is read from the Library of Congress crosswalk, and not until a source sends one](decisions.md#unimarc-is-read-from-the-library-of-congress-crosswalk-and-not-until-a-source-sends-one) | 1,441 |
|  | [ISNI is the identity spine, and VIAF is a discovery route](decisions.md#isni-is-the-identity-spine-and-viaf-is-a-discovery-route) | 455 |
|  | [A new catalogue gets a lookup slot and no search slot until somebody measures the search](decisions.md#a-new-catalogue-gets-a-lookup-slot-and-no-search-slot-until-somebody-measures-the-search) | 292 |
|  | [OPDS is a discovery route, and the Atom line is not a metadata import route](decisions.md#opds-is-a-discovery-route-and-the-atom-line-is-not-a-metadata-import-route) | 407 |
|  | [Two source families, one contract](decisions.md#two-source-families-one-contract) | 100 |
|  | [A decoder is never told how the bytes arrived](decisions.md#a-decoder-is-never-told-how-the-bytes-arrived) | 189 |
|  | [The capability vocabulary is what a source can be asked for, not which fields it supplies](decisions.md#the-capability-vocabulary-is-what-a-source-can-be-asked-for-not-which-fields-it-supplies) | 127 |
|  | [Two families, the argument, and where it lives](decisions.md#two-families-the-argument-and-where-it-lives) | 64 |
|  | [The capability vocabulary is a projection, not the stored field](decisions.md#the-capability-vocabulary-is-a-projection-not-the-stored-field) | 82 |
|  | [No migration, and why](decisions.md#no-migration-and-why) | 56 |
|  | [A guard that duplicates what it checks cannot be attacked](decisions.md#a-guard-that-duplicates-what-it-checks-cannot-be-attacked) | 209 |
|  | [Splitting an exemption list is not the same as pinning it](decisions.md#splitting-an-exemption-list-is-not-the-same-as-pinning-it) | 87 |
|  | [The matcher is named, and naming it could only take rules away](decisions.md#the-matcher-is-named-and-naming-it-could-only-take-rules-away) | 247 |
|  | [A batch relink is one transaction, and a decision is never repointed](decisions.md#a-batch-relink-is-one-transaction-and-a-decision-is-never-repointed) | 571 |
|  | [A catalogue credential's source is constrained, and that is not the foreign key by another name](decisions.md#a-catalogue-credentials-source-is-constrained-and-that-is-not-the-foreign-key-by-another-name) | 417 |
|  | [`conformance/` is published, and the fixtures are the specification](decisions.md#conformance-is-published-and-the-fixtures-are-the-specification) | 107 |
|  | [A conformance case pins the intermediate when the rule spans two functions](decisions.md#a-conformance-case-pins-the-intermediate-when-the-rule-spans-two-functions) | 309 |
|  | [One conformance document per domain, because the guard anchors on a header](decisions.md#one-conformance-document-per-domain-because-the-guard-anchors-on-a-header) | 160 |
|  | [The ASCII guard in `isbn.normalise` widens the backend rather than narrowing it](decisions.md#the-ascii-guard-in-isbnnormalise-widens-the-backend-rather-than-narrowing-it) | 73 |
|  | [The candidate list sets column priority, and the pool is kept though it is inert](decisions.md#the-candidate-list-sets-column-priority-and-the-pool-is-kept-though-it-is-inert) | 219 |
|  | [Encoding is decided per byte where the file is UTF-8, and per file where it is not](decisions.md#encoding-is-decided-per-byte-where-the-file-is-utf-8-and-per-file-where-it-is-not) | 594 |
|  | [The duplicate 409 withholds the id, and does not hide which case it was](decisions.md#the-duplicate-409-withholds-the-id-and-does-not-hide-which-case-it-was) | 134 |
|  | [A guard's file set is derived from the publish gate, never listed beside it](decisions.md#a-guards-file-set-is-derived-from-the-publish-gate-never-listed-beside-it) | 686 |
|  | [The ignore file rule had three homes with three refusal shapes, and one module replaced them](decisions.md#the-ignore-file-rule-had-three-homes-with-three-refusal-shapes-and-one-module-replaced-them) | 1,621 |
|  | [The ASCII narrowing rule is about alphanumeric predicates, not digits](decisions.md#the-ascii-narrowing-rule-is-about-alphanumeric-predicates-not-digits) | 222 |
|  | [A MARC `700` that states no role is not an author](decisions.md#a-marc-700-that-states-no-role-is-not-an-author) | 371 |
|  | [The heading count was already derived, and the sentence around it was wrong](decisions.md#the-heading-count-was-already-derived-and-the-sentence-around-it-was-wrong) | 64 |
|  | [A candidate name added at the end of a list is a different change from one added in it](decisions.md#a-candidate-name-added-at-the-end-of-a-list-is-a-different-change-from-one-added-in-it) | 268 |
|  | [A value assertion names its input only where one column feeds it](decisions.md#a-value-assertion-names-its-input-only-where-one-column-feeds-it) | 291 |
|  | [A catalogue login is resolved by the route, never read by the module that sends it](decisions.md#a-catalogue-login-is-resolved-by-the-route-never-read-by-the-module-that-sends-it) | 524 |
|  | [A test count is not a roster count, and the census refuses one by grammar](decisions.md#a-test-count-is-not-a-roster-count-and-the-census-refuses-one-by-grammar) | 1,523 |
|  | [The suite runner ships the repository it belongs to, not the caller's directory](decisions.md#the-suite-runner-ships-the-repository-it-belongs-to-not-the-callers-directory) | 210 |
|  | [The census's declaration window is bracketed where the number may be read](decisions.md#the-censuss-declaration-window-is-bracketed-where-the-number-may-be-read) | 150 |
|  | [An unverified account may do nothing, and the admin override is what makes that safe](decisions.md#an-unverified-account-may-do-nothing-and-the-admin-override-is-what-makes-that-safe) | 212 |
|  | [A catalogue credential is per source row, and the envelope already says so](decisions.md#a-catalogue-credential-is-per-source-row-and-the-envelope-already-says-so) | 126 |
|  | [The importer gets a reader per service, rather than a pre-pass in front of one path](decisions.md#the-importer-gets-a-reader-per-service-rather-than-a-pre-pass-in-front-of-one-path) | 179 |
|  | [The key is resolved once for a loop, and the arm that costs is stated with the one that saves](decisions.md#the-key-is-resolved-once-for-a-loop-and-the-arm-that-costs-is-stated-with-the-one-that-saves) | 421 |
|  | [The lever on a hosted deployment is one variable, and unwritable is not the condition](decisions.md#the-lever-on-a-hosted-deployment-is-one-variable-and-unwritable-is-not-the-condition) | 202 |
|  | [A `KeyState` carries the recovery phrase, so it is not rendered either](decisions.md#a-keystate-carries-the-recovery-phrase-so-it-is-not-rendered-either) | 74 |
|  | [The asymmetry, not a rule, is what makes an admin confirmed reset a recovery flow](decisions.md#the-asymmetry-not-a-rule-is-what-makes-an-admin-confirmed-reset-a-recovery-flow) | 137 |
|  | [A code, never a mailed link, and the reason is the `Host` header](decisions.md#a-code-never-a-mailed-link-and-the-reason-is-the-host-header) | 119 |
|  | [Confirmation is stamped when an account is made, not evaluated against the current policy](decisions.md#confirmation-is-stamped-when-an-account-is-made-not-evaluated-against-the-current-policy) | 117 |
|  | [`users` carries the settled fact and a table carries the workflow](decisions.md#users-carries-the-settled-fact-and-a-table-carries-the-workflow) | 65 |
|  | [No check constraint pairs the confirmation provenance with the admin who asserted it](decisions.md#no-check-constraint-pairs-the-confirmation-provenance-with-the-admin-who-asserted-it) | 46 |
|  | [One recovery budget across both flows, charged on two keys](decisions.md#one-recovery-budget-across-both-flows-charged-on-two-keys) | 117 |
|  | [An archive says what it knows by carrying the key, not by carrying a value](decisions.md#an-archive-says-what-it-knows-by-carrying-the-key-not-by-carrying-a-value) | 67 |
|  | [A token's `iat` carries sub second precision, and both roundings were wrong](decisions.md#a-tokens-iat-carries-sub-second-precision-and-both-roundings-were-wrong) | 216 |
|  | [The export door has a guest list, not only a doorman](decisions.md#the-export-door-has-a-guest-list-not-only-a-doorman) | 159 |
|  | [One instance issues a loan, and today that is two checkable claims](decisions.md#one-instance-issues-a-loan-and-today-that-is-two-checkable-claims) | 170 |
|  | [The borrower rule is one predicate, and the constraint is stricter than it by one shape](decisions.md#the-borrower-rule-is-one-predicate-and-the-constraint-is-stricter-than-it-by-one-shape) | 195 |
|  | [A corpus somebody chose cannot exhibit a disagreement nobody thought of](decisions.md#a-corpus-somebody-chose-cannot-exhibit-a-disagreement-nobody-thought-of) | 187 |
|  | [`trim()` strips a space, and a corpus of spaces cannot say so](decisions.md#trim-strips-a-space-and-a-corpus-of-spaces-cannot-say-so) | 201 |
|  | [A historical revision is compared by what it built, not by its source](decisions.md#a-historical-revision-is-compared-by-what-it-built-not-by-its-source) | 122 |
|  | [The test suite's schema is the migrated one, not the declared one](decisions.md#the-test-suites-schema-is-the-migrated-one-not-the-declared-one) | 105 |
|  | [A corpus is stated as an exclusion, never as a total](decisions.md#a-corpus-is-stated-as-an-exclusion-never-as-a-total) | 141 |
|  | [Four test modules keep their own copy of the walk over the backend's source](decisions.md#four-test-modules-keep-their-own-copy-of-the-walk-over-the-backends-source) | 97 |
|  | [An SRU diagnostic is a refusal to answer, not an answer of nothing](decisions.md#an-sru-diagnostic-is-a-refusal-to-answer-not-an-answer-of-nothing) | 430 |
|  | [A third party's diagnostic text is not logged, only its URI](decisions.md#a-third-partys-diagnostic-text-is-not-logged-only-its-uri) | 71 |
|  | [Free and credentialled is a real combination, and two guards rested on its not being one](decisions.md#free-and-credentialled-is-a-real-combination-and-two-guards-rested-on-its-not-being-one) | 282 |
|  | [A login on a plaintext connection, accepted with the residual stated in three places](decisions.md#a-login-on-a-plaintext-connection-accepted-with-the-residual-stated-in-three-places) | 192 |
|  | [A row exclusion belongs to the generic mapping, not to a service's reader](decisions.md#a-row-exclusion-belongs-to-the-generic-mapping-not-to-a-services-reader) | 274 |
|  | [A preview names the reader it used, including when it used the generic one](decisions.md#a-preview-names-the-reader-it-used-including-when-it-used-the-generic-one) | 112 |
|  | [The catalogue that publishes its own login ships with it](decisions.md#the-catalogue-that-publishes-its-own-login-ships-with-it) | 241 |
|  | [The Z39.50 client is the one already built, promoted rather than chosen](decisions.md#the-z3950-client-is-the-one-already-built-promoted-rather-than-chosen) | 189 |
|  | [A shipped login is the bottom of one ladder, and the ladder is walked once](decisions.md#a-shipped-login-is-the-bottom-of-one-ladder-and-the-ladder-is-walked-once) | 160 |
|  | [The pair lives on the target row, so the origin it is bound to is not stored twice](decisions.md#the-pair-lives-on-the-target-row-so-the-origin-it-is-bound-to-is-not-stored-twice) | 84 |
|  | [The provenance is one field, because the levels are ordered and booleans are not](decisions.md#the-provenance-is-one-field-because-the-levels-are-ordered-and-booleans-are-not) | 77 |
|  | [A stock install and a set that needs no credential are two different names](decisions.md#a-stock-install-and-a-set-that-needs-no-credential-are-two-different-names) | 130 |
|  | [The import seam is a reader per service, and selection is shown rather than trusted](decisions.md#the-import-seam-is-a-reader-per-service-and-selection-is-shown-rather-than-trusted) | 204 |
|  | [A claim is a predicate over the front of the file, not a set of header names](decisions.md#a-claim-is-a-predicate-over-the-front-of-the-file-not-a-set-of-header-names) | 144 |
|  | [A row exclusion is honoured wherever the column appears, and a repeated one is refused](decisions.md#a-row-exclusion-is-honoured-wherever-the-column-appears-and-a-repeated-one-is-refused) | 328 |
|  | [A figure two instruments disagree about is cut, not caveated](decisions.md#a-figure-two-instruments-disagree-about-is-cut-not-caveated) | 177 |
|  | [Amazon's `DocumentProvider` is not read as the author](decisions.md#amazons-documentprovider-is-not-read-as-the-author) | 78 |
|  | [An excluded row is counted in the open, where a blocked row is not](decisions.md#an-excluded-row-is-counted-in-the-open-where-a-blocked-row-is-not) | 68 |
|  | [A source carries a remit, so a catalogue is asked about books it might hold](decisions.md#a-source-carries-a-remit-so-a-catalogue-is-asked-about-books-it-might-hold) | 185 |
|  | [Provenance is published, because a catalogue that hides its sources is not a catalogue](decisions.md#provenance-is-published-because-a-catalogue-that-hides-its-sources-is-not-a-catalogue) | 127 |
|  | [A harvested Book is owned by the harvest, not by the admin who ran it](decisions.md#a-harvested-book-is-owned-by-the-harvest-not-by-the-admin-who-ran-it) | 180 |
|  | [The competitor register's reference counts get a stated command and no guard](decisions.md#the-competitor-registers-reference-counts-get-a-stated-command-and-no-guard) | 248 |
|  | [A household's own OPDS server is its own table, not a row in `catalogue_targets`](decisions.md#a-households-own-opds-server-is-its-own-table-not-a-row-in-catalogue_targets) | 170 |
|  | [An OPDS server is refused link local after resolution, and admitted everywhere else private](decisions.md#an-opds-server-is-refused-link-local-after-resolution-and-admitted-everywhere-else-private) | 276 |
|  | [An entitlement is not a holding](decisions.md#an-entitlement-is-not-a-holding) | 142 |
|  | [A born digital title depends on two of the title search sources](decisions.md#a-born-digital-title-depends-on-two-of-the-title-search-sources) | 321 |
|  | [An envelope is bound to the origin it may be sent to, and a restore drops household logins as the belt](decisions.md#an-envelope-is-bound-to-the-origin-it-may-be-sent-to-and-a-restore-drops-household-logins-as-the-belt) | 1,209 |
|  | [Reading a Calibre library through SQLite in the browser, not on the server](decisions.md#reading-a-calibre-library-through-sqlite-in-the-browser-not-on-the-server) | 222 |
|  | [The content security policy grants `'wasm-unsafe-eval'` and nothing else](decisions.md#the-content-security-policy-grants-wasm-unsafe-eval-and-nothing-else) | 148 |
|  | [The Calibre index wins and the OPF fills its gaps, with two exceptions](decisions.md#the-calibre-index-wins-and-the-opf-fills-its-gaps-with-two-exceptions) | 97 |
|  | [What the reference library actually contains, measured rather than quoted](decisions.md#what-the-reference-library-actually-contains-measured-rather-than-quoted) | 254 |
|  | [Identifiers other than the ISBN had nowhere to go, and the count is what justified the table](decisions.md#identifiers-other-than-the-isbn-had-nowhere-to-go-and-the-count-is-what-justified-the-table) | 156 |
|  | [Which sibling audio files are one book](decisions.md#which-sibling-audio-files-are-one-book) | 219 |
|  | [What real audiobook files say that the ticket did not](decisions.md#what-real-audiobook-files-say-that-the-ticket-did-not) | 214 |
|  | [What MOBI cannot supply, and where its ISBN comes from](decisions.md#what-mobi-cannot-supply-and-where-its-isbn-comes-from) | 222 |
|  | [A measurement in published prose names its corpus and its instrument in the same clause](decisions.md#a-measurement-in-published-prose-names-its-corpus-and-its-instrument-in-the-same-clause) | 161 |
|  | [`BookFormat.COMIC` earned a value where a magazine did not](decisions.md#bookformatcomic-earned-a-value-where-a-magazine-did-not) | 252 |
|  | [A CBZ carrying no metadata is not a failure](decisions.md#a-cbz-carrying-no-metadata-is-not-a-failure) | 134 |
|  | [A comic's title is the file's own, and the series is not repeated into it](decisions.md#a-comics-title-is-the-files-own-and-the-series-is-not-repeated-into-it) | 153 |
|  | [A PDF that opens and names no title still says so](decisions.md#a-pdf-that-opens-and-names-no-title-still-says-so) | 81 |
|  | [A PDF's `/CreationDate` is not read as a publication year](decisions.md#a-pdfs-creationdate-is-not-read-as-a-publication-year) | 67 |
|  | [Encryption is decided by `/Encrypt` resolving to a dictionary, not by the key being present](decisions.md#encryption-is-decided-by-encrypt-resolving-to-a-dictionary-not-by-the-key-being-present) | 40 |
|  | [Two readers' corpora were re-derived, and both named the wrong population](decisions.md#two-readers-corpora-were-re-derived-and-both-named-the-wrong-population) | 131 |
|  | [A plausible year and a storable year are two questions, and the plausible one is a function](decisions.md#a-plausible-year-and-a-storable-year-are-two-questions-and-the-plausible-one-is-a-function) | 964 |
| A plausible year and a storable year are two questions, and the plausible one is a function | [Seven modules read a publication year, and they apply three different rules](decisions.md#seven-modules-read-a-publication-year-and-they-apply-three-different-rules) | 267 |
| A plausible year and a storable year are two questions, and the plausible one is a function | [One defect, two seats, two instruments, and it was already fixed](decisions.md#one-defect-two-seats-two-instruments-and-it-was-already-fixed) | 83 |
|  | [A file's subject is a category, not a tag, and the library says so by 1.058](decisions.md#a-files-subject-is-a-category-not-a-tag-and-the-library-says-so-by-1058) | 328 |
|  | [A file's subject is shown where it is still reversible, not where the design round put it](decisions.md#a-files-subject-is-shown-where-it-is-still-reversible-not-where-the-design-round-put-it) | 167 |
|  | [What the browser rebuilds of the server's normaliser, and what keeps it one directional](decisions.md#what-the-browser-rebuilds-of-the-servers-normaliser-and-what-keeps-it-one-directional) | 355 |
|  | [Excluding Calibre's tags is a scope decision, and the request figure was wrong](decisions.md#excluding-calibres-tags-is-a-scope-decision-and-the-request-figure-was-wrong) | 358 |
|  | [A Calibre library's `metadata.opf` is a stale copy of the index, not a second source](decisions.md#a-calibre-librarys-metadataopf-is-a-stale-copy-of-the-index-not-a-second-source) | 156 |
|  | [The 57 books are the undefined date, and the correction runs the other way](decisions.md#the-57-books-are-the-undefined-date-and-the-correction-runs-the-other-way) | 444 |
|  | [Neither source wins the 70 that are left, and each is right about a different field](decisions.md#neither-source-wins-the-70-that-are-left-and-each-is-right-about-a-different-field) | 413 |
|  | [How it was measured, and what is excluded](decisions.md#how-it-was-measured-and-what-is-excluded) | 281 |
|  | [The 42 language disagreements are an accepted cost, with the reason](decisions.md#the-42-language-disagreements-are-an-accepted-cost-with-the-reason) | 221 |
|  | [The count that corroborates the split, and the base rate that looked wrong](decisions.md#the-count-that-corroborates-the-split-and-the-base-rate-that-looked-wrong) | 202 |
|  | [A prefix read is a third question, not a smaller ceiling](decisions.md#a-prefix-read-is-a-third-question-not-a-smaller-ceiling) | 352 |
|  | [Five guards, one shape: the description was written from what it was meant to cover](decisions.md#five-guards-one-shape-the-description-was-written-from-what-it-was-meant-to-cover) | 375 |
|  | [The plausibility window belongs to reading a year, not to bounding one](decisions.md#the-plausibility-window-belongs-to-reading-a-year-not-to-bounding-one) | 536 |
|  | [The window sits in `fb2.yearIn`, not at the end of `fb2.readYear`](decisions.md#the-window-sits-in-fb2yearin-not-at-the-end-of-fb2readyear) | 111 |
|  | [`opf.readYear` windows the chosen date, which is the opposite choice](decisions.md#opfreadyear-windows-the-chosen-date-which-is-the-opposite-choice) | 125 |
|  | [Why no complement guard was built for the caller list](decisions.md#why-no-complement-guard-was-built-for-the-caller-list) | 175 |
|  | [A boundary arm asserts the point just outside the end, not a number far outside](decisions.md#a-boundary-arm-asserts-the-point-just-outside-the-end-not-a-number-far-outside) | 337 |
|  | [A PDF's inflated bytes and its object stream parses are charged to the same total as its reads](decisions.md#a-pdfs-inflated-bytes-and-its-object-stream-parses-are-charged-to-the-same-total-as-its-reads) | 698 |
|  | [The no-custody claim rests on the absent route, not on the network scan](decisions.md#the-no-custody-claim-rests-on-the-absent-route-not-on-the-network-scan) | 181 |
|  | [Why the published sentence says "no route accepts a book file" and the guard does not enforce that](decisions.md#why-the-published-sentence-says-no-route-accepts-a-book-file-and-the-guard-does-not-enforce-that) | 80 |
|  | [The column half is asserted, and it is the weaker half](decisions.md#the-column-half-is-asserted-and-it-is-the-weaker-half) | 66 |
|  | [A decoder a runtime may not carry is never built at module scope](decisions.md#a-decoder-a-runtime-may-not-carry-is-never-built-at-module-scope) | 483 |
|  | [A zipped reader is handed a zip's refusal, not a table of them](decisions.md#a-zipped-reader-is-handed-a-zips-refusal-not-a-table-of-them) | 466 |
|  | [MIT, and the four places that have to agree about it](decisions.md#mit-and-the-four-places-that-have-to-agree-about-it) | 590 |
|  | [The shared record moved to the seam and kept its name](decisions.md#the-shared-record-moved-to-the-seam-and-kept-its-name) | 553 |
|  | [A count in prose is deleted before it is guarded](decisions.md#a-count-in-prose-is-deleted-before-it-is-guarded) | 390 |
|  | [A note carries its own visibility, and it is the second access control on content](decisions.md#a-note-carries-its-own-visibility-and-it-is-the-second-access-control-on-content) | 544 |
|  | [A restored cover is written only when its bytes are an image this app serves](decisions.md#a-restored-cover-is-written-only-when-its-bytes-are-an-image-this-app-serves) | 364 |
|  | [A bulk keep and a keep one row at a time are two different answers](decisions.md#a-bulk-keep-and-a-keep-one-row-at-a-time-are-two-different-answers) | 236 |
|  | [A draft builder is found by two derivations, and the file set is not one of them](decisions.md#a-draft-builder-is-found-by-two-derivations-and-the-file-set-is-not-one-of-them) | 279 |
|  | [A catalogue is asked only where it collects, and the bar for saying so is zero](decisions.md#a-catalogue-is-asked-only-where-it-collects-and-the-bar-for-saying-so-is-zero) | 389 |
|  | [A `CheckConstraint` in `models.py` is a description, not a second enforcement](decisions.md#a-checkconstraint-in-modelspy-is-a-description-not-a-second-enforcement) | 203 |
|  | [SQLite in the browser was already paid for, so a device store costs its reader](decisions.md#sqlite-in-the-browser-was-already-paid-for-so-a-device-store-costs-its-reader) | 266 |
|  | [A number in prose is deleted rather than corrected, again](decisions.md#a-number-in-prose-is-deleted-rather-than-corrected-again) | 137 |
|  | [A guard's clearance is a prefix test standing in for a semantic one](decisions.md#a-guards-clearance-is-a-prefix-test-standing-in-for-a-semantic-one) | 440 |
|  | [The `File` half of the no-custody predicate is inverted, and that is deliberate](decisions.md#the-file-half-of-the-no-custody-predicate-is-inverted-and-that-is-deliberate) | 173 |
|  | [`codeOnly` is gone, and what the parser gave up](decisions.md#codeonly-is-gone-and-what-the-parser-gave-up) | 105 |
|  | [The dark hover band was never measured on the pair it named](decisions.md#the-dark-hover-band-was-never-measured-on-the-pair-it-named) | 82 |
|  | [The reader seam is what a reader is, and a parsing rule is not](decisions.md#the-reader-seam-is-what-a-reader-is-and-a-parsing-rule-is-not) | 158 |
|  | [The untrusted row vocabulary is a module, and its rule is written down](decisions.md#the-untrusted-row-vocabulary-is-a-module-and-its-rule-is-written-down) | 151 |
|  | [A global stubbed to `undefined` does not test a `typeof` guard](decisions.md#a-global-stubbed-to-undefined-does-not-test-a-typeof-guard) | 150 |
|  | [An export that contains the books is read in the browser, not in the import seam](decisions.md#an-export-that-contains-the-books-is-read-in-the-browser-not-in-the-import-seam) | 96 |
|  | [A container of books is a library source, not a file reader](decisions.md#a-container-of-books-is-a-library-source-not-a-file-reader) | 229 |
|  | [Two store reader fields nothing read, and why the one word they shared could not be given a sentence](decisions.md#two-store-reader-fields-nothing-read-and-why-the-one-word-they-shared-could-not-be-given-a-sentence) | 427 |
|  | [A store's own identifier is read and not kept, and the ASIN is where that first bit](decisions.md#a-stores-own-identifier-is-read-and-not-kept-and-the-asin-is-where-that-first-bit) | 262 |
|  | [A store's identifier is a table of its own, not a second guess at `isbn`](decisions.md#a-stores-identifier-is-a-table-of-its-own-not-a-second-guess-at-isbn) | 925 |
|  | [A store that cannot say who owns a book says so, and the default meant it never could](decisions.md#a-store-that-cannot-say-who-owns-a-book-says-so-and-the-default-meant-it-never-could) | 500 |
|  | [Prevalence is a rate, and a lifetime count is a measure of age](decisions.md#prevalence-is-a-rate-and-a-lifetime-count-is-a-measure-of-age) | 170 |
|  | [A Calibre type string is a name and a marketplace, and the value is what decides](decisions.md#a-calibre-type-string-is-a-name-and-a-marketplace-and-the-value-is-what-decides) | 765 |
|  | [An identifier is shown as text, and the link that was not built](decisions.md#an-identifier-is-shown-as-text-and-the-link-that-was-not-built) | 379 |
|  | [A new rule in the house rules calls the helpers already there rather than re-spelling them](decisions.md#a-new-rule-in-the-house-rules-calls-the-helpers-already-there-rather-than-re-spelling-them) | 513 |
|  | [Commit before asking for a sign off, and never ask while the tree is dirty](decisions.md#commit-before-asking-for-a-sign-off-and-never-ask-while-the-tree-is-dirty) | 158 |
|  | [A file's identifier label is mapped now, and the value is what keeps a row](decisions.md#a-files-identifier-label-is-mapped-now-and-the-value-is-what-keeps-a-row) | 999 |
| A file's identifier label is mapped now, and the value is what keeps a row | [`MOBI-ASIN` is admitted, and calibre's refusal of it is still right](decisions.md#mobi-asin-is-admitted-and-calibres-refusal-of-it-is-still-right) | 509 |
| A file's identifier label is mapped now, and the value is what keeps a row | [The guard the refusal rested on is narrower and is not gone](decisions.md#the-guard-the-refusal-rested-on-is-narrower-and-is-not-gone) | 240 |
|  | [A response body is parsed in one place, so the hazard is handled in one place](decisions.md#a-response-body-is-parsed-in-one-place-so-the-hazard-is-handled-in-one-place) | 253 |
|  | [The ISBN label a file puts in front of the number has one home](decisions.md#the-isbn-label-a-file-puts-in-front-of-the-number-has-one-home) | 144 |
|  | [The suite's database is the migrations', and it is asserted rather than stated](decisions.md#the-suites-database-is-the-migrations-and-it-is-asserted-rather-than-stated) | 295 |
|  | [A guard that strips prose with a regex edits the code it was reading](decisions.md#a-guard-that-strips-prose-with-a-regex-edits-the-code-it-was-reading) | 271 |
|  | [A second instrument is a defect before it is wrong](decisions.md#a-second-instrument-is-a-defect-before-it-is-wrong) | 688 |
|  | [An instrument that cannot composite measures the one pairing it may not assume about](decisions.md#an-instrument-that-cannot-composite-measures-the-one-pairing-it-may-not-assume-about) | 178 |
|  | [Three GLOB rules, three different situations, one arm](decisions.md#three-glob-rules-three-different-situations-one-arm) | 445 |
| Three GLOB rules, three different situations, one arm | [A character ceiling bounds no bytes](decisions.md#a-character-ceiling-bounds-no-bytes) | 102 |
| Three GLOB rules, three different situations, one arm | [A literal anti vacuity floor is a stated bound wearing a measurement's clothes](decisions.md#a-literal-anti-vacuity-floor-is-a-stated-bound-wearing-a-measurements-clothes) | 121 |
|  | [The local cover precedence is `covers.is_local` and nothing else](decisions.md#the-local-cover-precedence-is-coversis_local-and-nothing-else) | 200 |
|  | [Outside evidence cannot claim to be this deployment's own file](decisions.md#outside-evidence-cannot-claim-to-be-this-deployments-own-file) | 120 |
|  | [`COVER_HOSTS` entries are bare hosts, and two readers need them to be](decisions.md#cover_hosts-entries-are-bare-hosts-and-two-readers-need-them-to-be) | 73 |
|  | [Escaping a CSV export cell is the default, and the exemption is the claim](decisions.md#escaping-a-csv-export-cell-is-the-default-and-the-exemption-is-the-claim) | 200 |
|  | [The flip counts commas after the noise strip and returns the value from before it](decisions.md#the-flip-counts-commas-after-the-noise-strip-and-returns-the-value-from-before-it) | 131 |
|  | [`csv_import` has four public names, and the tables are not among them](decisions.md#csv_import-has-four-public-names-and-the-tables-are-not-among-them) | 126 |
|  | [What the export refuses, and why each refusal is not a gap](decisions.md#what-the-export-refuses-and-why-each-refusal-is-not-a-gap) | 186 |
|  | [`exchange.py` was refused and the round trip test it was filed for existed already](decisions.md#exchangepy-was-refused-and-the-round-trip-test-it-was-filed-for-existed-already) | 128 |
|  | [Only the branch that flips a cell may take its full stop](decisions.md#only-the-branch-that-flips-a-cell-may-take-its-full-stop) | 269 |
|  | [`_PERSON_NOISE` on the import path is quadratic over a whitespace run](decisions.md#_person_noise-on-the-import-path-is-quadratic-over-a-whitespace-run) | 124 |
|  | [The count that guards a guard must not be read off the thing it guards](decisions.md#the-count-that-guards-a-guard-must-not-be-read-off-the-thing-it-guards) | 87 |
|  | [Not carried over: the export's column order](decisions.md#not-carried-over-the-exports-column-order) | 81 |
|  | [No export cell is exempt from the escape, and there is no list of exemptions](decisions.md#no-export-cell-is-exempt-from-the-escape-and-there-is-no-list-of-exemptions) | 277 |
|  | [Left open: `csv_import` can still re-export a second rule with a home](decisions.md#left-open-csv_import-can-still-re-export-a-second-rule-with-a-home) | 78 |
|  | [What the escape guard structurally cannot carry](decisions.md#what-the-escape-guard-structurally-cannot-carry) | 147 |
|  | [The thing retiring the exemption list cost, which is not the exemption](decisions.md#the-thing-retiring-the-exemption-list-cost-which-is-not-the-exemption) | 166 |
|  | [SQLite is the engine, and a dialect keyword in `models.py` is a description](decisions.md#sqlite-is-the-engine-and-a-dialect-keyword-in-modelspy-is-a-description) | 285 |
|  | [A deadline is a bare float, and the type behind it stayed deferred](decisions.md#a-deadline-is-a-bare-float-and-the-type-behind-it-stayed-deferred) | 340 |
|  | [`errors.API_PREFIXES` and `covers.LOCAL_COVER_PREFIX` are two concepts sharing a spelling](decisions.md#errorsapi_prefixes-and-coverslocal_cover_prefix-are-two-concepts-sharing-a-spelling) | 215 |
|  | [The key, the plan and the logins reach a catalogue as one value](decisions.md#the-key-the-plan-and-the-logins-reach-a-catalogue-as-one-value) | 1,102 |
|  | [A locally refused catalogue request spends no rate limit budget](decisions.md#a-locally-refused-catalogue-request-spends-no-rate-limit-budget) | 138 |
|  | [Two predicates decide whether a credentialled catalogue is asked, and they ask different questions](decisions.md#two-predicates-decide-whether-a-credentialled-catalogue-is-asked-and-they-ask-different-questions) | 215 |
|  | [One matcher serves both catalogue door rules, with a receiver exemption](decisions.md#one-matcher-serves-both-catalogue-door-rules-with-a-receiver-exemption) | 272 |
|  | [`sources.parse` returns the whole roster, so naming one source narrows nothing](decisions.md#sourcesparse-returns-the-whole-roster-so-naming-one-source-narrows-nothing) | 164 |
|  | [The bound before a write that a review asked for was already there](decisions.md#the-bound-before-a-write-that-a-review-asked-for-was-already-there) | 95 |
|  | [Enrichment's cascade is not the access door's](decisions.md#enrichments-cascade-is-not-the-access-doors) | 226 |
|  | [Editing applied migrations was allowed, on one condition](decisions.md#editing-applied-migrations-was-allowed-on-one-condition) | 205 |
|  | [A grep cannot find what it does not spell](decisions.md#a-grep-cannot-find-what-it-does-not-spell) | 99 |
|  | [The naive regex translation of a GLOB fails two different ways](decisions.md#the-naive-regex-translation-of-a-glob-fails-two-different-ways) | 141 |
|  | [A NUL arm is subsumed by a column type, not by an engine](decisions.md#a-nul-arm-is-subsumed-by-a-column-type-not-by-an-engine) | 129 |
|  | [Creation is not preservation](decisions.md#creation-is-not-preservation) | 347 |
|  | [The Postgres driver is a runtime dependency, and the image is the reason](decisions.md#the-postgres-driver-is-a-runtime-dependency-and-the-image-is-the-reason) | 792 |
|  | [The channel's loans are the public shelf's, not a second spelling of it](decisions.md#the-channels-loans-are-the-public-shelfs-not-a-second-spelling-of-it) | 106 |
|  | [The loan door has three constructors, not two](decisions.md#the-loan-door-has-three-constructors-not-two) | 138 |
|  | [What stayed outside that door, and why](decisions.md#what-stayed-outside-that-door-and-why) | 137 |
|  | [No migration: `close` is above the index, never instead of it](decisions.md#no-migration-close-is-above-the-index-never-instead-of-it) | 73 |
|  | [The attribute rule is wider than the ticket asked for, and costs one line](decisions.md#the-attribute-rule-is-wider-than-the-ticket-asked-for-and-costs-one-line) | 134 |
|  | [The txt export flattens every value, with no exempt set](decisions.md#the-txt-export-flattens-every-value-with-no-exempt-set) | 141 |
|  | [A door is not shut by the absence of a caller](decisions.md#a-door-is-not-shut-by-the-absence-of-a-caller) | 94 |
|  | [An address policy can take the teeth out of the control it sits behind](decisions.md#an-address-policy-can-take-the-teeth-out-of-the-control-it-sits-behind) | 225 |
|  | [Making the cover download door async would cost one `asyncio.run`, not three](decisions.md#making-the-cover-download-door-async-would-cost-one-asynciorun-not-three) | 104 |
|  | [A closed vocabulary is a module, and the objection against this one was measured away](decisions.md#a-closed-vocabulary-is-a-module-and-the-objection-against-this-one-was-measured-away) | 189 |
|  | [Folding two Books is one door, and the guard replacing an allowlist took three rounds](decisions.md#folding-two-books-is-one-door-and-the-guard-replacing-an-allowlist-took-three-rounds) | 407 |
|  | [A guard that names no module is still exempting one, if its walk stops early](decisions.md#a-guard-that-names-no-module-is-still-exempting-one-if-its-walk-stops-early) | 1,363 |
| A guard that names no module is still exempting one, if its walk stops early | [The bulk verb table is built through its check, not checked beside it](decisions.md#the-bulk-verb-table-is-built-through-its-check-not-checked-beside-it) | 549 |
| A guard that names no module is still exempting one, if its walk stops early | [A stored reason is a name, guarded by a type for what a type can hold and by a test for the rest](decisions.md#a-stored-reason-is-a-name-guarded-by-a-type-for-what-a-type-can-hold-and-by-a-test-for-the-rest) | 516 |
|  | [The column partition covers all thirty columns, not the twenty five that are nullable](decisions.md#the-column-partition-covers-all-thirty-columns-not-the-twenty-five-that-are-nullable) | 494 |
|  | [The pinned key guard resolves an attribute call's subject across modules](decisions.md#the-pinned-key-guard-resolves-an-attribute-calls-subject-across-modules) | 657 |
|  | [A guard's prose is written so that one member can be dropped alone](decisions.md#a-guards-prose-is-written-so-that-one-member-can-be-dropped-alone) | 290 |
|  | [The bulk write is a loop over items, and the follow up stays in the caller's `post`](decisions.md#the-bulk-write-is-a-loop-over-items-and-the-follow-up-stays-in-the-callers-post) | 156 |
|  | [`stopped` is a stop that ended the run early, and both halves are asserted](decisions.md#stopped-is-a-stop-that-ended-the-run-early-and-both-halves-are-asserted) | 97 |
|  | [A stopped bulk write prunes what it walked, never what it offered](decisions.md#a-stopped-bulk-write-prunes-what-it-walked-never-what-it-offered) | 69 |
|  | [A run stopped after one book still remembers the shelf](decisions.md#a-run-stopped-after-one-book-still-remembers-the-shelf) | 59 |
|  | [The stop is its own button, and the discard keeps its place](decisions.md#the-stop-is-its-own-button-and-the-discard-keeps-its-place) | 128 |
|  | [The commit that ends a run may not move the discard toward the finger](decisions.md#the-commit-that-ends-a-run-may-not-move-the-discard-toward-the-finger) | 359 |
|  | [The result banner is never drawn over a run](decisions.md#the-result-banner-is-never-drawn-over-a-run) | 99 |
|  | [The rapid add's progress is not a live region](decisions.md#the-rapid-adds-progress-is-not-a-live-region) | 74 |
|  | [The rule that one module writes a shelf in bulk is two assertions, not one](decisions.md#the-rule-that-one-module-writes-a-shelf-in-bulk-is-two-assertions-not-one) | 334 |
|  | [oxlint is adopted as a ratchet, and the suppression list is two lists](decisions.md#oxlint-is-adopted-as-a-ratchet-and-the-suppression-list-is-two-lists) | 565 |
|  | [Three more ruff families, and what each suppression is standing on](decisions.md#three-more-ruff-families-and-what-each-suppression-is-standing-on) | 1,939 |
|  | [The tooling tree's disciplines run in the backend suite, not in a job step](decisions.md#the-tooling-trees-disciplines-run-in-the-backend-suite-not-in-a-job-step) | 250 |
|  | [Turning a linter on is not the same as fixing what it finds](decisions.md#turning-a-linter-on-is-not-the-same-as-fixing-what-it-finds) | 282 |
|  | [A floor that nothing drives is not a floor](decisions.md#a-floor-that-nothing-drives-is-not-a-floor) | 164 |
|  | [The working notes are split by how often a rule fires, not by how important it is](decisions.md#the-working-notes-are-split-by-how-often-a-rule-fires-not-by-how-important-it-is) | 540 |
|  | [A claim about a file is verified by reading the file back, in the call that makes it](decisions.md#a-claim-about-a-file-is-verified-by-reading-the-file-back-in-the-call-that-makes-it) | 231 |
|  | [The container rule took five review rounds, and four of them were one defect](decisions.md#the-container-rule-took-five-review-rounds-and-four-of-them-were-one-defect) | 466 |
| The container rule took five review rounds, and four of them were one defect | [Two findings answered rather than fixed, with the reason](decisions.md#two-findings-answered-rather-than-fixed-with-the-reason) | 234 |
|  | [A comment beginning `# noqa` is a blanket suppression, whatever it goes on to say](decisions.md#a-comment-beginning--noqa-is-a-blanket-suppression-whatever-it-goes-on-to-say) | 121 |
|  | [Property based tests run in the ordinary suite, and the budget is a test rather than a number](decisions.md#property-based-tests-run-in-the-ordinary-suite-and-the-budget-is-a-test-rather-than-a-number) | 565 |
|  | [A generator is derived from the rule, and a witness beside it proves it still reaches the class](decisions.md#a-generator-is-derived-from-the-rule-and-a-witness-beside-it-proves-it-still-reaches-the-class) | 346 |
|  | [The LIKE escaping has a property at one of its two sites, and the reason is the door in front of each](decisions.md#the-like-escaping-has-a-property-at-one-of-its-two-sites-and-the-reason-is-the-door-in-front-of-each) | 315 |
|  | [`flip_catalogue_name` is stable on a name and not on a cell that is not one](decisions.md#flip_catalogue_name-is-stable-on-a-name-and-not-on-a-cell-that-is-not-one) | 186 |
|  | [The structural house rules stay in the test tree, and both contract tools are refused](decisions.md#the-structural-house-rules-stay-in-the-test-tree-and-both-contract-tools-are-refused) | 1,279 |
| The structural house rules stay in the test tree, and both contract tools are refused | [It cuts three of the four rules in half](decisions.md#it-cuts-three-of-the-four-rules-in-half) | 125 |
| The structural house rules stay in the test tree, and both contract tools are refused | [A graph of this backend is very nearly edgeless](decisions.md#a-graph-of-this-backend-is-very-nearly-edgeless) | 286 |
| The structural house rules stay in the test tree, and both contract tools are refused | [What does work needs the tree changed to suit the tool, and two of its three shapes are silently blind](decisions.md#what-does-work-needs-the-tree-changed-to-suit-the-tool-and-two-of-its-three-shapes-are-silently-blind) | 327 |
| The structural house rules stay in the test tree, and both contract tools are refused | [The frontend half is refused because the contract is weaker, not because the tool will not run](decisions.md#the-frontend-half-is-refused-because-the-contract-is-weaker-not-because-the-tool-will-not-run) | 197 |
| The structural house rules stay in the test tree, and both contract tools are refused | [The evasion everybody suspects is not the reason](decisions.md#the-evasion-everybody-suspects-is-not-the-reason) | 33 |
| The structural house rules stay in the test tree, and both contract tools are refused | [What would change the answer](decisions.md#what-would-change-the-answer) | 92 |
|  | [An absence is not a verdict, and the ratchet now proves its report arrived](decisions.md#an-absence-is-not-a-verdict-and-the-ratchet-now-proves-its-report-arrived) | 1,686 |
|  | [The publish gate's forbidden list cannot hold every node name](decisions.md#the-publish-gates-forbidden-list-cannot-hold-every-node-name) | 100 |
|  | [A documented command is validated, not generated](decisions.md#a-documented-command-is-validated-not-generated) | 1,128 |
|  | [The house rule learned what the revision beside it already knew](decisions.md#the-house-rule-learned-what-the-revision-beside-it-already-knew) | 568 |
|  | [A `GLOB` rule claims only what a NUL lets it read](decisions.md#a-glob-rule-claims-only-what-a-nul-lets-it-read) | 452 |
|  | [A bound on a confined column is written in bytes, once, not in both units](decisions.md#a-bound-on-a-confined-column-is-written-in-bytes-once-not-in-both-units) | 528 |
|  | [The envelope's ceiling is derived from the two routes that can fill it](decisions.md#the-envelopes-ceiling-is-derived-from-the-two-routes-that-can-fill-it) | 269 |
|  | [The envelope still carries no NUL clause, and the reason changed under it](decisions.md#the-envelope-still-carries-no-nul-clause-and-the-reason-changed-under-it) | 115 |
|  | [Every constraint naming a NUL is probed, and which rule probes it depends on the arm](decisions.md#every-constraint-naming-a-nul-is-probed-and-which-rule-probes-it-depends-on-the-arm) | 483 |
|  | [`STILL_OPEN` is empty, and the file keeps two anti vacuity guards without it](decisions.md#still_open-is-empty-and-the-file-keeps-two-anti-vacuity-guards-without-it) | 132 |
|  | [`AddedRule` moved to `dialect.py`, and the move was measured rather than asserted](decisions.md#addedrule-moved-to-dialectpy-and-the-move-was-measured-rather-than-asserted) | 302 |
|  | [What the envelope ceiling's derivation still cannot see](decisions.md#what-the-envelope-ceilings-derivation-still-cannot-see) | 453 |
|  | [A guard over another tree's source names no file in it](decisions.md#a-guard-over-another-trees-source-names-no-file-in-it) | 254 |
|  | [An allowlist entry is keyed on the statement, because a fragment names a token](decisions.md#an-allowlist-entry-is-keyed-on-the-statement-because-a-fragment-names-a-token) | 290 |
|  | [Every CHECK is compared as text, and a fourth premise arm asks a boot what it built](decisions.md#every-check-is-compared-as-text-and-a-fourth-premise-arm-asks-a-boot-what-it-built) | 810 |
|  | [An enum list in a CHECK is derived from its enum, so growing the enum names the missing revision](decisions.md#an-enum-list-in-a-check-is-derived-from-its-enum-so-growing-the-enum-names-the-missing-revision) | 1,220 |
|  | [The diagonal that drives a walk reads the test tree, not one file](decisions.md#the-diagonal-that-drives-a-walk-reads-the-test-tree-not-one-file) | 732 |
|  | [The mutation sweep takes its own interrupt back](decisions.md#the-mutation-sweep-takes-its-own-interrupt-back) | 611 |
|  | [The fold is one thing and the predicate is another](decisions.md#the-fold-is-one-thing-and-the-predicate-is-another) | 433 |
|  | [Whitespace is stripped after punctuation is removed, never before](decisions.md#whitespace-is-stripped-after-punctuation-is-removed-never-before) | 234 |
|  | [The reading history title takes half the fold and refuses the other half](decisions.md#the-reading-history-title-takes-half-the-fold-and-refuses-the-other-half) | 1,814 |
| The reading history title takes half the fold and refuses the other half | [A provenance claim is the most quotable sentence in a module and the least checked](decisions.md#a-provenance-claim-is-the-most-quotable-sentence-in-a-module-and-the-least-checked) | 1,368 |
|  | [A leading article is a title's, never a credit's](decisions.md#a-leading-article-is-a-titles-never-a-credits) | 84 |
|  | [`identity.py` is kept although the depth instrument argues against it](decisions.md#identitypy-is-kept-although-the-depth-instrument-argues-against-it) | 361 |
|  | [The two completeness scores are two questions, not one list](decisions.md#the-two-completeness-scores-are-two-questions-not-one-list) | 671 |
|  | [An arm compared against itself survives every mutant, and the sweep cannot see it](decisions.md#an-arm-compared-against-itself-survives-every-mutant-and-the-sweep-cannot-see-it) | 257 |
|  | [An arm that pins the wrong thing, and the seat that withdrew its own finding](decisions.md#an-arm-that-pins-the-wrong-thing-and-the-seat-that-withdrew-its-own-finding) | 314 |
|  | [A guard for the general components folder names no domain word](decisions.md#a-guard-for-the-general-components-folder-names-no-domain-word) | 125 |
|  | [The generality half of the components bar is left to review, deliberately](decisions.md#the-generality-half-of-the-components-bar-is-left-to-review-deliberately) | 218 |
|  | [A guard over a platform API derives the API rather than naming it](decisions.md#a-guard-over-a-platform-api-derives-the-api-rather-than-naming-it) | 1,115 |
|  | [An arm that cannot fail the claim it was written for, and it is a family now](decisions.md#an-arm-that-cannot-fail-the-claim-it-was-written-for-and-it-is-a-family-now) | 629 |
|  | [Four date formats are kept although two of them are drift](decisions.md#four-date-formats-are-kept-although-two-of-them-are-drift) | 171 |
|  | [A supported language is an own property of the catalogue, not anything `in` it](decisions.md#a-supported-language-is-an-own-property-of-the-catalogue-not-anything-in-it) | 193 |
|  | [The settings import hooks are folded at the contract, not at the runtime](decisions.md#the-settings-import-hooks-are-folded-at-the-contract-not-at-the-runtime) | 430 |
|  | [A generated `TError` is not the type of any error this app throws](decisions.md#a-generated-terror-is-not-the-type-of-any-error-this-app-throws) | 209 |
|  | [A contract derived from a measured pair survives review; one reasoned out from scratch did not](decisions.md#a-contract-derived-from-a-measured-pair-survives-review-one-reasoned-out-from-scratch-did-not) | 266 |
|  | [The words beside a guard are read as its extent, and they were wrong in both directions](decisions.md#the-words-beside-a-guard-are-read-as-its-extent-and-they-were-wrong-in-both-directions) | 306 |
|  | [Every population derived by matching source text in this wave was wrong at least once](decisions.md#every-population-derived-by-matching-source-text-in-this-wave-was-wrong-at-least-once) | 252 |
|  | [A refactor moved the data out of the set the privacy guard watched](decisions.md#a-refactor-moved-the-data-out-of-the-set-the-privacy-guard-watched) | 300 |
|  | [A fix round is better where it was aimed and weaker where nobody looked again](decisions.md#a-fix-round-is-better-where-it-was-aimed-and-weaker-where-nobody-looked-again) | 215 |
|  | [A shared helper takes the wider type, and a caller that has narrowed one keeps its own](decisions.md#a-shared-helper-takes-the-wider-type-and-a-caller-that-has-narrowed-one-keeps-its-own) | 211 |
|  | [A `*_ORDER` list is exhaustive by type, and the tests keep only what the type cannot hold](decisions.md#a-_order-list-is-exhaustive-by-type-and-the-tests-keep-only-what-the-type-cannot-hold) | 258 |
|  | [A decision record's own figures are deleted rather than corrected](decisions.md#a-decision-records-own-figures-are-deleted-rather-than-corrected) | 333 |
|  | [The scan queue keeps no module, and the reason is a measurement](decisions.md#the-scan-queue-keeps-no-module-and-the-reason-is-a-measurement) | 191 |
|  | [A row names whose secret its door takes, not whether it is metered](decisions.md#a-row-names-whose-secret-its-door-takes-not-whether-it-is-metered) | 499 |
|  | [A weakened population and a decorative tuple member are different failures, and only one is a cross check](decisions.md#a-weakened-population-and-a-decorative-tuple-member-are-different-failures-and-only-one-is-a-cross-check) | 385 |
|  | [An index of this file is generated, not written](decisions.md#an-index-of-this-file-is-generated-not-written) | 280 |
|  | [A second derivation is only a second instrument until you delete the first and watch it fail](decisions.md#a-second-derivation-is-only-a-second-instrument-until-you-delete-the-first-and-watch-it-fail) | 321 |
|  | [A literal beside a derivation may be carrying a floor, so ask what it refuses before deleting what it repeats](decisions.md#a-literal-beside-a-derivation-may-be-carrying-a-floor-so-ask-what-it-refuses-before-deleting-what-it-repeats) | 248 |
|  | [A refusal is narrowed and its escape hatch is closed in the same change](decisions.md#a-refusal-is-narrowed-and-its-escape-hatch-is-closed-in-the-same-change) | 216 |
|  | [A refusal can be worth having for the shape of the failure alone](decisions.md#a-refusal-can-be-worth-having-for-the-shape-of-the-failure-alone) | 370 |
|  | [A refusal that shares one message across five terms sends the reader to the wrong fix](decisions.md#a-refusal-that-shares-one-message-across-five-terms-sends-the-reader-to-the-wrong-fix) | 118 |
|  | [A corpus figure is stated as an exclusion or recomputed, and the census had to learn this about itself](decisions.md#a-corpus-figure-is-stated-as-an-exclusion-or-recomputed-and-the-census-had-to-learn-this-about-itself) | 290 |
|  | [A duration is attributed to a machine and a worker count or it is not evidence](decisions.md#a-duration-is-attributed-to-a-machine-and-a-worker-count-or-it-is-not-evidence) | 180 |
|  | [One fact, several homes, and the sweep for the others is part of the change](decisions.md#one-fact-several-homes-and-the-sweep-for-the-others-is-part-of-the-change) | 169 |
|  | [The field a heading goes in and the code naming its vocabulary are one decision](decisions.md#the-field-a-heading-goes-in-and-the-code-naming-its-vocabulary-are-one-decision) | 351 |
|  | [A generated export of the lockfile is not committed, because the scanner already reads the lock](decisions.md#a-generated-export-of-the-lockfile-is-not-committed-because-the-scanner-already-reads-the-lock) | 597 |
|  | [`UserCreate.username` is the only username field in the application carrying a pattern](decisions.md#usercreateusername-is-the-only-username-field-in-the-application-carrying-a-pattern) | 479 |
|  | [A recovery phrase is told from prose by its glue, not by its checksum](decisions.md#a-recovery-phrase-is-told-from-prose-by-its-glue-not-by-its-checksum) | 372 |
|  | [A fixture that must be a valid phrase is derived, never written down](decisions.md#a-fixture-that-must-be-a-valid-phrase-is-derived-never-written-down) | 125 |
|  | [An exclusion arm pins the predicate's shape and says nothing about its argument](decisions.md#an-exclusion-arm-pins-the-predicates-shape-and-says-nothing-about-its-argument) | 121 |
|  | [An unreachable fixture pins a state the server cannot produce](decisions.md#an-unreachable-fixture-pins-a-state-the-server-cannot-produce) | 171 |
|  | [The death signal an arm carries is the uncatchable one](decisions.md#the-death-signal-an-arm-carries-is-the-uncatchable-one) | 486 |
|  | [What a killed suite run leaves is three things, and the third had no owner](decisions.md#what-a-killed-suite-run-leaves-is-three-things-and-the-third-had-no-owner) | 556 |
|  | [A gate whose hostile input is rejected by an earlier gate has no test](decisions.md#a-gate-whose-hostile-input-is-rejected-by-an-earlier-gate-has-no-test) | 211 |
|  | [A deadline test turns on a fact, because every clock available to it is wider than the thing it measures](decisions.md#a-deadline-test-turns-on-a-fact-because-every-clock-available-to-it-is-wider-than-the-thing-it-measures) | 545 |
|  | [A row count is a second instrument, and the two numbers are read together](decisions.md#a-row-count-is-a-second-instrument-and-the-two-numbers-are-read-together) | 595 |
|  | [A liveness guard on an instrument reads the magnitude, never the key](decisions.md#a-liveness-guard-on-an-instrument-reads-the-magnitude-never-the-key) | 125 |
|  | [An instrument's reach is bounded by the container types its walker knows](decisions.md#an-instruments-reach-is-bounded-by-the-container-types-its-walker-knows) | 353 |
|  | [The directory username is bounded where the row is written, not by a column constraint](decisions.md#the-directory-username-is-bounded-where-the-row-is-written-not-by-a-column-constraint) | 777 |
|  | [A refused name is logged in full, and a dict of directory results is not clipped](decisions.md#a-refused-name-is-logged-in-full-and-a-dict-of-directory-results-is-not-clipped) | 191 |
|  | [The one username log line an unauthenticated caller reaches composes both bounds](decisions.md#the-one-username-log-line-an-unauthenticated-caller-reaches-composes-both-bounds) | 247 |
|  | [A receiver of the public tree blocks the publish, or says at its own site why it does not](decisions.md#a-receiver-of-the-public-tree-blocks-the-publish-or-says-at-its-own-site-why-it-does-not) | 797 |
|  | [One function scans the commit and sends it, because two of them cannot be kept in step](decisions.md#one-function-scans-the-commit-and-sends-it-because-two-of-them-cannot-be-kept-in-step) | 482 |
|  | [The commit subject is a publication channel, and the publish fails rather than rewriting it](decisions.md#the-commit-subject-is-a-publication-channel-and-the-publish-fails-rather-than-rewriting-it) | 265 |
|  | [The outbound commit message is an artefact, so there is one evaluation and nothing to compare](decisions.md#the-outbound-commit-message-is-an-artefact-so-there-is-one-evaluation-and-nothing-to-compare) | 366 |
|  | [A secret scanner that asks a library inherits the library's blind spots](decisions.md#a-secret-scanner-that-asks-a-library-inherits-the-librarys-blind-spots) | 279 |
|  | [The sentence wider than its measurement is written by the careful seat, not the careless one](decisions.md#the-sentence-wider-than-its-measurement-is-written-by-the-careful-seat-not-the-careless-one) | 1,117 |
|  | [A guard's verdict can be a property of the tree rather than of the guard](decisions.md#a-guards-verdict-can-be-a-property-of-the-tree-rather-than-of-the-guard) | 567 |
|  | [A role word can be the surname, and a flip manufactures the stop that hides it](decisions.md#a-role-word-can-be-the-surname-and-a-flip-manufactures-the-stop-that-hides-it) | 850 |
|  | [An instrument's output is a sample until somebody derives the population](decisions.md#an-instruments-output-is-a-sample-until-somebody-derives-the-population) | 1,033 |
|  | [A bound widened inside an extraction is recorded, and the arm pinning it has an expiry](decisions.md#a-bound-widened-inside-an-extraction-is-recorded-and-the-arm-pinning-it-has-an-expiry) | 362 |
|  | [A stale name in prose is checkable only where the sentence spells the module](decisions.md#a-stale-name-in-prose-is-checkable-only-where-the-sentence-spells-the-module) | 383 |
|  | [The API promises RFC 3339, so the serialiser adds the offset the column does not hold](decisions.md#the-api-promises-rfc-3339-so-the-serialiser-adds-the-offset-the-column-does-not-hold) | 719 |
|  | [A deadline is an instant, so the browser sends the offset](decisions.md#a-deadline-is-an-instant-so-the-browser-sends-the-offset) | 269 |
|  | [A calendar date is not an instant, so the renderer reads the shape rather than the caller](decisions.md#a-calendar-date-is-not-an-instant-so-the-renderer-reads-the-shape-rather-than-the-caller) | 675 |
|  | [A branded date type was refused, and the reason is that the branding is free and the slot is impossible](decisions.md#a-branded-date-type-was-refused-and-the-reason-is-that-the-branding-is-free-and-the-slot-is-impossible) | 480 |
|  | [A database side default on a naive column is the one ambiguous stored value, and the wire did not make it one](decisions.md#a-database-side-default-on-a-naive-column-is-the-one-ambiguous-stored-value-and-the-wire-did-not-make-it-one) | 150 |
|  | [The database connection's default is weaker than the mail path's, deliberately](decisions.md#the-database-connections-default-is-weaker-than-the-mail-paths-deliberately) | 348 |
|  | [A shared corpus owes a single file caller a refusal, and the module that holds it cannot see itself](decisions.md#a-shared-corpus-owes-a-single-file-caller-a-refusal-and-the-module-that-holds-it-cannot-see-itself) | 1,233 |
|  | [An author column on the custom field row, rather than the cheaper alternative](decisions.md#an-author-column-on-the-custom-field-row-rather-than-the-cheaper-alternative) | 240 |
|  | [The provenance arm was widened to the declaration rather than given an exemption](decisions.md#the-provenance-arm-was-widened-to-the-declaration-rather-than-given-an-exemption) | 142 |
|  | [A schema declaration counts as a read of a guarded column](decisions.md#a-schema-declaration-counts-as-a-read-of-a-guarded-column) | 234 |
|  | [The declaration reader is keyed on Pydantic's compiled schema, not on `FieldInfo`](decisions.md#the-declaration-reader-is-keyed-on-pydantics-compiled-schema-not-on-fieldinfo) | 128 |
|  | [What the two instruments hold is reading, with the archive as a stated exception](decisions.md#what-the-two-instruments-hold-is-reading-with-the-archive-as-a-stated-exception) | 169 |
|  | [An unattended release is started by a HIGH and carries every fixable advisory](decisions.md#an-unattended-release-is-started-by-a-high-and-carries-every-fixable-advisory) | 209 |
|  | [An unfixable Python advisory is recorded against its release and package, or it blocks](decisions.md#an-unfixable-python-advisory-is-recorded-against-its-release-and-package-or-it-blocks) | 338 |
|  | [The carve out asks OSV again, and reads it more strictly than the trigger does](decisions.md#the-carve-out-asks-osv-again-and-reads-it-more-strictly-than-the-trigger-does) | 420 |
|  | [A blocked night is exit 3, armed it pages its own summary, and unarmed it is a report](decisions.md#a-blocked-night-is-exit-3-armed-it-pages-its-own-summary-and-unarmed-it-is-a-report) | 144 |
|  | [The release acts only on what its own run made](decisions.md#the-release-acts-only-on-what-its-own-run-made) | 257 |
|  | [Every call carrying a release credential leaves through one pinned opener](decisions.md#every-call-carrying-a-release-credential-leaves-through-one-pinned-opener) | 346 |
|  | [The HTTP library's request lines are switched off by level, not redacted](decisions.md#the-http-librarys-request-lines-are-switched-off-by-level-not-redacted) | 173 |
|  | [A refusal over a whole lint population is `lint.ignore`, read by selecting it again](decisions.md#a-refusal-over-a-whole-lint-population-is-lintignore-read-by-selecting-it-again) | 506 |
|  | [The application's `lint.ignore` refuses two exception rules, and B008 is on](decisions.md#the-applications-lintignore-refuses-two-exception-rules-and-b008-is-on) | 745 |
|  | [The application's per file table is read](decisions.md#the-applications-per-file-table-is-read) | 83 |
|  | [A backlog count is held by equality, and a security entry by file](decisions.md#a-backlog-count-is-held-by-equality-and-a-security-entry-by-file) | 93 |
|  | [The keys of both ruff configurations are pinned](decisions.md#the-keys-of-both-ruff-configurations-are-pinned) | 131 |
|  | [The frontend backlog counts are read over a copy with every disable directive blanked](decisions.md#the-frontend-backlog-counts-are-read-over-a-copy-with-every-disable-directive-blanked) | 387 |
|  | [The frontend's property runs draw a fresh seed, and say where they are](decisions.md#the-frontends-property-runs-draw-a-fresh-seed-and-say-where-they-are) | 384 |
|  | [One module runs every property, and the door is closed by derivation where one exists](decisions.md#one-module-runs-every-property-and-the-door-is-closed-by-derivation-where-one-exists) | 295 |
|  | [The oracle for a reader is counted work, not "did it throw"](decisions.md#the-oracle-for-a-reader-is-counted-work-not-did-it-throw) | 441 |
|  | [Every bound a door declares is held by a control, and a ledger refuses one without](decisions.md#every-bound-a-door-declares-is-held-by-a-control-and-a-ledger-refuses-one-without) | 458 |
|  | [The build refuses a bundle that loads or emits the property generator](decisions.md#the-build-refuses-a-bundle-that-loads-or-emits-the-property-generator) | 211 |
|  | [A coverage gap is answered where the instrument is configured or the code is tested, never by a figure](decisions.md#a-coverage-gap-is-answered-where-the-instrument-is-configured-or-the-code-is-tested-never-by-a-figure) | 280 |
|  | [A webhook address is refused where the URL parser would raise, at save and at send](decisions.md#a-webhook-address-is-refused-where-the-url-parser-would-raise-at-save-and-at-send) | 198 |
|  | [An error whose message can quote a value is logged by its type, place and frames](decisions.md#an-error-whose-message-can-quote-a-value-is-logged-by-its-type-place-and-frames) | 260 |
|  | [A route's crash is answered inside the app, so the server logs it once](decisions.md#a-routes-crash-is-answered-inside-the-app-so-the-server-logs-it-once) | 256 |
|  | [A security waiver in the application stays at its line, and is held by value](decisions.md#a-security-waiver-in-the-application-stays-at-its-line-and-is-held-by-value) | 449 |
|  | [A suppression comment is read the way ruff reads it, and may not name a policing rule](decisions.md#a-suppression-comment-is-read-the-way-ruff-reads-it-and-may-not-name-a-policing-rule) | 321 |
|  | [A parsed XML document is bounded by depth while it parses, and fed to its parser in chunks](decisions.md#a-parsed-xml-document-is-bounded-by-depth-while-it-parses-and-fed-to-its-parser-in-chunks) | 329 |
|  | [The coverage register's write is printed in a loop until every byte is out](decisions.md#the-coverage-registers-write-is-printed-in-a-loop-until-every-byte-is-out) | 209 |
<!-- index: end -->
