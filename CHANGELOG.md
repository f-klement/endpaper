# Changelog

## Unreleased

### Added

- Authors that share a confirmed ISNI are offered as one person on the merge suggestions
  panel, which is the first rule there that reaches a pen name or a transliteration. It is a
  suggestion like the other three: nothing is folded until somebody says so, and deleting
  the alias row puts the shelf back.
- **In library mode every member chases every loan.** The overdue page used to
  narrow to the loans a member lent or borrowed unless they were an admin, so a
  volunteer could see a book was out and not that it was late. With library mode
  on that arm lifts for everyone. Private books are as far out of reach as they
  were: the relaxation is about who is party to a loan, not about which books
  exist, and the shelf filter in front of it did not move.
- **A loan says how long the book has been away.** Every open loan on the loans
  page and the overdue page carries the number of whole days it has been out,
  and an overdue one carries how far past its date it is. Both are computed on
  the server, in the same place the overdue reminders read, so a row and a
  reminder cannot disagree about the same loan.
- **An SRU server, on the published catalogue's own two switches.** A published
  catalogue can be searched by a person; being searched by another institution's
  software needs a protocol, and the one this domain uses is SRU. `/sru` takes a CQL
  query and answers MARCXML, and `operation=explain` tells a client which indexes exist
  without anybody having to ask a human. It exposes exactly what the public catalogue
  exposes and not one row more: the same gate, the same rows, the same rate limit
  counter, and records from the same MARC writer the export uses. A hostile query is
  bounded five ways on the parse and once more on what it costs to run, and refused as
  an SRU diagnostic in a 200, which is what an SRU client can read, rather than as a
  status code it cannot. With library mode off the endpoint does not exist.
- A **filing rule** per classification scheme, which is how that scheme's call numbers
  sort. Dewey files a notation as its own text, Library of Congress files by class letters
  then class number so `BF75` stands before `BF575` as it does on a shelf, and a scheme
  with no rule of its own files as text and offers no shelf order. The library can be
  ordered by Library of Congress call number as well as by Dewey.

- **Search harder.** A catalogue can be slow enough that the shared 4.0s deadline cancels
  it before it answers, which makes switching it on a burned connection and never a
  record. Such a catalogue is now left out of the ordinary title search and reached by
  asking for it, under a longer deadline of its own. The search panel offers it after a
  search comes back, names the catalogues it would add, and says so instead of "no
  matches" when every catalogue this library has switched on is a slow one. Nothing
  changes on the ISBN path, which already reached a slow catalogue only after every
  faster one had missed.
- The catalogue settings section says on the row when a catalogue is left out for being
  slow, so off because it is slow does not read as off because it is broken.


### Changed

- The shelf order reads a stored key instead of building one. A classification row now
  carries the key its scheme's filing rule returns for its number, written whenever the row
  is written and backfilled for existing rows. The order used to compile a twelve arm `CASE`
  per classification row on every listing: the worst case a member could construct cost
  2.3 s of database time per request on one box and 3.2 s on another.
- A catalogue record whose ISBN is wider than the column now loses that field rather than
  carrying it. A malformed identifier used to cost a whole search row, since the search row
  schema refused it; it now costs the identifier only.

- Library mode now opens on the dense list rather than on whatever view was
  last chosen, and remembers changes made to it separately. Turning library
  mode on no longer overwrites a household's view, and turning it off again
  returns it unmodified. Nothing already stored is reset: the household keeps
  the key it has always had, and library mode gets one of its own.

- A catalogue's address, transport, query indexes, record format and page sizes are data
  on one typed row per source, and its parser stays code: eleven near identical adapters,
  five ISBN lookups and six title searches, are one request builder and a reader chosen
  per row. Adding a national catalogue is a row, plus a reader only when its record format
  is genuinely new. Nothing a household sees changes: the same sources, asked in the same
  order, returning the same records. The database table those rows will live in is created
  and seeded here and deliberately not read yet, because reading an address off a row is
  the decision that lets somebody supply one, and that has its own ticket.
- The German interface no longer addresses the reader informally, and does not address
  them formally either. 82 strings were rephrased to carry no address at all, so one
  catalogue reads correctly in a household and in a library without either being told
  which it is. German has the machinery for it: the infinitive for an instruction,
  `eigen-` for a possessive that carries weight, a plain article for one that does not,
  the passive, and `wer …` for a conditional about the reader.
- The published catalogue was the one section written formally, addressing a visitor
  formally while the rest of the app was informal. It reads the same as everything else
  now.

- A national catalogue is asked only about the ISBNs it could hold. An ISBN names its own
  registration group, and a catalogue whose collecting remit is one group is skipped for a
  book from another: the National Library of Greece for `978-960` and `978-618`, the
  Austrian National Library for `978-3`. Measured over the committed 500 ISBN sample,
  1.396s per lookup becomes 1.279s and the second phase makes 518 requests instead of 753,
  for the same 377 books. The rule applies to the sources asked one at a time and never to
  the leading pair, which is gathered and so costs its slowest member rather than their
  sum. A catalogue may carry a remit only where there is no book it alone answers outside
  it, which is why the Czech National Library carries none.
- The provider list on the settings screen says which registration groups a catalogue
  collects, which is the third thing a row can be beside on and off.
- **A subject heading now carries the vocabulary the record declared and the
  identifier it gave.** A Greek record saying `Ευρώπη` also says that the heading
  comes from `nlgaf`, the National Library of Greece's own authority file, and
  that its number there is `urn:nbn:gr:nlg:01-A273635`. Both were discarded: the
  identifier reader accepted a German `(DE-588)` prefix and nothing else, which
  dropped **11 of 11** of that catalogue's identifiers and 27 of 718 across four
  catalogues measured on 2026-08-31. Nothing is mapped between vocabularies and
  nothing is guessed: a heading whose record declared no vocabulary stays
  unlabelled.
- **Nothing on screen changes.** No column holds either value yet and nothing
  reads them: the tag suggestion and the `categories` string both take the words
  alone, and showing one word twice because two vocabularies claim it would be a
  worse page. This is the half a later change needs in hand, and it is worth a
  line only because the identifier stopped being thrown away.

- **A house rule that compiles every Python file under `backend/` and fails on any compile
  time warning.** An invalid escape sequence in a non raw string is a `SyntaxWarning`
  today and a `SyntaxError` on CPython's schedule, at which point the file stops importing
  and every house rule in `test_house_rules.py` goes with it. Nothing here read that
  warning. The walk covers the tests and the migrations as well as the application
  modules, because the failure is at import and does not care which a file is. ruff's
  `W605` is selected in the same change as the fast path: it reports the same escape with
  a column and an autofix, before the suite runs.
- **The catalogue roster's size is recomputed wherever the tree spells it.**
  `backend/tests/test_roster_counts.py` takes a census of every number written beside a
  roster noun across the backend, the docs that ship, the root Markdown and the frontend,
  and requires a verdict for each: it names a cardinality computed from `sources.py` and
  is compared with it, or it records what the number counts instead. A candidate with no
  verdict fails and a verdict judging nothing fails, so neither half can rot, and no count
  is written in the guard. Adding one source had previously made twenty two prose
  statements stale, found in three passes each believing it was the last; six were still
  stale when this landed and five are fixed here. Four more in `docs/decisions.md` were
  corrected at the merge, and that register is read by the census since 2026-09-03.
- The wrapper that serialises `api:generate` refuses when a generation did not rewrite
  the schema. Two runs that
  die the same way produce two identical trees and a diff of nothing, and that clean diff
  had been read as verification.

**The first draft of this entry claimed "two identical strings from two vocabularies stop
being merged" as a user visible change and that was wrong.** `Record.subject_labels`
deduplicates by label before either consumer sees the subjects, and that property's own
docstring says both consumers would be wrong to show the distinction. The fold does keep
them apart inside the record; nothing downstream can tell.

**"The wire is byte identical" was also wrong, and was fixed in the code rather than in the
prose.** `categories` is a joined string of these labels and is stored on the Book, and the
first fold emitted surviving entries in key order, so a record carrying `Roman` undeclared
before `Informatik` declared answered `Informatik; Roman` where the rule it replaced
answered `Roman; Informatik`. The fold now groups by label, so a label keeps the place of
its first occurrence and the string is unchanged. `frontend/openapi.json` is separately
byte identical, which is about the schema and was never about this.
- `GET /api/books/search` answers with an object rather than a bare list: `matches`, plus
  `asked` and `unasked` naming the catalogues the fan out did and did not reach. It takes
  a `harder` parameter.
- The roster count census now reads `docs/decisions.md`. That register was excluded on the
  reasoning that a count in it is dated by the file's structure, which is true of
  `CHANGELOG.md` and false here: it carries no version headings and records decisions that
  still bind. Every one of the 15 candidates it holds now carries a verdict, 3 of them live
  claims the guard checks against `sources.py` and 12 of them records of what a figure
  counted when it was taken.

### Fixed

- A cover URL a member posts is now bounded against what the database stores rather than
  against what arrives. The ORM upgrades `http://` to `https://` on every write, which
  lengthens the value by one, so a 500 character URL was accepted and stored as 501 against
  a 500 character column. Both adding a book and applying enrichment were affected.

- A column change made in the first moment of a cold load was saved under the
  household's columns even in library mode, because the flag that names the
  mode had not arrived yet. The controls that write a per-mode preference are
  now disabled until it has.

- The cataloguer's call number column drew Dewey **and** Library of Congress notations and
  offered one order, a Dewey one, over both. A library shelving by Library of Congress got
  an order written for another scheme, silently. The column now offers each scheme's own
  order and names the one it is reading.
- A Dewey number carrying MARC's segmentation prime (`005.13/3`) filed apart from the same
  heading written `005.133`. The validator accepted the prime without writing its answer
  back, so it reached the column; the filing rule removes it before sorting. Measured, 53
  of 463 live K10plus values carry one, so those rows change key and their neighbours
  change position.
- A classification number carrying a control character was accepted. A NUL is the one that
  mattered: it is not whitespace, so the collapse let it through, and SQLite's string
  functions stop at one where Python's do not, so a single stored value produced two
  different filing keys.
- Five strings on the public catalogue settings page addressed the reader formally while
  the rest of the German interface was informal. They arrived with the wave that built the
  published catalogue and nothing noticed the mix.
- Three German strings opened a sentence with `Sie` about the books, the records and the
  covers. In an interface that also addresses its reader that way, they read as statements
  about the reader: that they are created unconfirmed, arrive unconfirmed, and keep a
  link. Each names its subject now.
- A German string said `ueber` where it meant `über`.

- **Every field a request body carries is bounded.** `BookMatch`, the body of
  `POST /api/books/{id}/enrich/apply`, bounded four of its seventeen fields and left the
  rest open, so a member chose how large a stored value was and how much parsing the
  server did. The sharpest was `series_index`, which had no ceiling at all while
  `GET /api/series` computes a range over it: a stored `1e9` is roughly 70 GB and ten
  minutes of work, on every request, for every member. `suggested_tag_ids` bounded each
  entry's value and not the number of entries. The guard is not a per field assertion:
  every field naming a column two request bodies both write must carry the same bound in
  both, which is how this one arrived.
- `BookCreate.language` accepted 16 characters into a `String(10)` column. Narrowed to 10,
  which is what the column has always said and what `importing.py` already truncated to.
  **This narrows what `POST /api/books` accepts**: an 11 to 16 character language now gets
  a 422 where it used to get a 201, and no such value was ever a valid tag or storable on
  an engine that enforces a width.
- `BodySizeLimitMiddleware`'s docstring said a chunked JSON body was bounded by the
  route's own parsing. Neither of its two rules sees such a request and a schema runs only
  after the body is in memory, so nothing bounded it. The docstring now says so.
- The `CATEGORIES_MAX` comment justified itself with a lookup path worst case of nine
  catalogues storing three times the bound. The fold is two records, not nine, because it
  reduces over a tier sliced to `sources.ALWAYS_ASKED`, and both per record figures came
  from the Library of Congress, which is title search only and can never be on that path.
  Driven with every source answering, the real figure is 0.67x the bound. The risk it was
  describing is real for a better reason: five of the six catalogues that can be folded
  cap their subject list not at all, and the fold order is the household's, so two
  uncapped records are reachable from the settings screen.

- An ISBN of Unicode digits that are not ASCII is refused rather than accepted or crashing.
  `str.isdigit()` is true of far more than `0` to `9`, and the two halves failed in
  opposite directions: a superscript two made `GET /api/books/lookup` raise, and an
  Arabic-Indic zero passed the checksum, so `POST /api/books` stored a string the unique
  ISBN constraint could not see as the same book. The tag filter had the first shape on a
  query string. Every digit predicate in the backend is now narrowed to ASCII, and a house
  rule requires it.

- **A catalogue can no longer write a value the columns refuse.** Automatic enrichment
  (`POST /api/books/{id}/enrich`) handed the merge whatever the catalogues answered, while
  its neighbour `POST /api/books/{id}/enrich/apply` refused the identical value with a 422:
  same book, same column, one route apart. The sharp one is a series number, which is a
  stored denial of service rather than an untidy row, because the series view computes a
  range over that column on every request for every member and a stored `1e9` is roughly
  70 GB and ten minutes of it. A value the column cannot hold now costs that one field on
  that one enrichment, logged, and the rest of the record still lands: refusing the whole
  record would report "nothing found" about a book a catalogue did find. Every catalogue
  that answers that route is somebody else's, so this needs a broken or compromised
  upstream rather than a hostile member.

- **A bulk tag action with an absurd id answered 500.** `{"action": "add_tag", "value":
  2**63}` passed the parse, reached the row lookup and raised out of the database driver.
  It is a 404 now, which is what an id no row can carry already got when it merely did not
  exist.

- **A single corrupt series number no longer costs every member the series page.** That
  view lists the gaps in a series, and it worked them out by counting up from one to the
  highest number held, so one row holding a number no member could have typed made it
  build a list millions of entries long on every request. Measured at 14,888,944 bytes
  from a library of one book. Such a row cannot be created through the API and can still
  arrive: a restore writes what the file says, and an instance upgraded from an earlier
  release keeps what its enrichment stored. The gaps below the ceiling are still reported,
  so a library with one bad row still gets the answer it can act on.

- **The refusal that keeps a digitised copy, an audiobook or a disc off a shelf was written
  in German and English**, so it silently did nothing for a catalogue that describes one in
  any other language. It now reads the carrier codes the record itself carries: MARC's
  leader/06, `007` and `008/23` for the four MARC sources, the MODS
  `physicalDescription/form` for the Library of Congress, and the `dc:type` for the BnF.
  Measured over 2,605 live MARC records, 65 that are not physical books passed the old rule
  and 43 of those state no extent at all, so no wording in any language could have reached
  them. The two Dublin Core sources keep a phrase of their own because they carry no code
  to read.

- A K10plus, OeNB or NLG lookup ranked the records for one ISBN on completeness alone and
  applied no not-a-book test, where the DNB lookup always had one. A digitisation is
  usually the fuller record, so it won: measured over 210 live K10plus ISBN lookups, 9
  answered with both kinds and 8 of the 9 returned the digitisation.

- The BnF's printed-only gate accepted any record whose `dc:type` contained `text`, which
  is the Dublin Core type an ebook carries too.

- **The enrichment endpoint's API documentation said a new install "searches all seven"
  catalogues** where the search fan out asks eight, and enumerated a source order that had
  been wrong since the Austrian National Library moved down the default list. FastAPI
  publishes a route docstring as the OpenAPI description, so the wrong number shipped in
  the published schema and in the generated client. The sentence now counts the roster,
  says separately that Google Books answers only once its section is on and a key is in
  force, and no longer enumerates the order. Two comments in the settings store said the
  stored provider row holds "seven entries" where it spells nine.

- **Two published registers rendered as one code block from partway down.** A previous
  wave folded a working draft into `CHANGELOG.md` and `docs/decisions.md` along with
  its own scaffolding, leaving an unclosed fence in each and 42 lines of instructions
  addressed to a main session in the second. Everything below the fence was code on
  GitHub and nothing failed, because no test read a Markdown file for its shape. A house
  rule now counts the fences in every published Markdown file.
- A book catalogue can no longer write a value the database column cannot hold. Refreshing
  a book's metadata wrote nine fields straight from the catalogue's answer with no ceiling
  on eight of them; a value too wide now loses that one field and the refresh keeps
  everything else.
- Scanning an ISBN whose catalogue record carries a very long description no longer fails
  with a server error.
- Importing a MARC file with a very long title still cuts the title to fit rather than
  dropping the book, which is the right answer for a file you uploaded yourself and the
  wrong one for a catalogue's guess about a book you already own.
- The 409 raised when no catalogue can answer named the ISBN path from both title search
  routes. A library running only the Czech National Library, which answers an ISBN and
  answers no title search, was refused a title search by being told nothing could look up
  an ISBN.
- `docs/decisions.md` said "Six of the eight sources publish a carrier vocabulary" where
  the backend reaches its not-a-book test from seven sources and five of those state a
  carrier in codes. Five of seven, and the sentence's own list already named five.
- The same register justified rejecting a blanket scan with a figure that had already
  moved twice. It no longer restates a number the guard's own docstring recomputes.

## v0.12.0

_2026-08-31_

### Added

- **The Czech National Library** is asked about a book by ISBN. Of 50 Czech
  ISBNs the rest of the chain answers 10 between them and this one answers 49.
  It is on by default and can be moved or switched off in Settings, Catalogue
  sources.
- **It is asked about an ISBN and never about a title**, which is the server's
  doing rather than a choice: it returns one filled in record per reply whatever
  is asked for, so offering ten search results would mean ten separate requests
  to a catalogue somebody else pays to run. A scan wants one record and gets one.
- **The National Library of Greece** is asked about a book, on an ISBN lookup and
  on a title search. It is the Greek legal deposit catalogue, so it holds the
  domestic edition under the domestic ISBN, which is the case the rest of the
  chain missed: of 50 Greek ISBNs, the other free sources answer 8 between them
  and this one answers 37. It is on by default and can be moved or switched off
  in Settings, Catalogue sources.
- **An email address can be given while an account is being created**, and every
  account can now reach the place to set one. The registration form asks for it,
  optionally, and so does the **test accounts** form in Settings, Data, which is
  the only place an admin creates an account here. An address left empty is still
  empty: nothing about an account without one has changed, and nothing is sent to
  it yet.
- **A member is told when they have no address**, rather than shown an empty box
  that reads the same as a field which failed to load. An admin scanning the
  member list for the row whose reminders go nowhere reads "None set." instead of
  looking for the box that happens to be blank.
- **A member whose account came from a directory is told the directory did not
  supply an address, and that this one is theirs to fill in.** Those accounts
  appear at a first sign in with nobody filling in a form, so nobody had ever
  asked them for one, and the field looked identical to a local account that had
  chosen not to give one.
- **MARC21 import and export**, in library mode. A MARCXML file another library
  exported can be read at Settings, Your library, Take a catalogue across, and
  the whole shelf can be written back out from the export menu. Records are
  matched on ISBN, then on author and title together, so importing the same file
  twice fills gaps rather than doubling the catalogue. The preview says how many
  records the file holds, how many this app can store and how many are already
  on the shelf, before anything is written.
- The export carries the **classifications**, which is the half another
  institution shelves by: `082` for Dewey, `050` for a Library of Congress call
  number, `650` with `$0` and `$2` for a GND or LCSH heading.
- `GET /api/settings/features` now reports `library_mode`, so a client with no
  admin session can tell whether to offer any of this.
- **The cataloguer's column set.** In library mode the table view offers two
  columns a household has no use for: a call number, and the published subject
  headings. The household's columns about the object and the reader are turned
  off by default and can be turned back on. Which columns are drawn is now
  chosen from a picker above the table and remembered separately for each mode,
  so switching library mode on and off does not rearrange anybody's catalogue.
  The call number sorts by the Dewey number rather than by the text in the cell.
- A bound on `description`, `models.DESCRIPTION_MAX`. It had none anywhere:
  `POST /api/books` accepted a 200,000 character description with a 201, and
  `description` is on the listing payload, so one oversized value was paid for
  on every page of every list.

### Fixed

- **A book whose catalogue record qualifies its ISBN was reported as not found.**
  MARC lets a record note the binding, the volume, the price or the format beside
  an ISBN, and this app read every such note as a cross reference to a different
  edition and refused the record. That was right for the one German catalogue it
  was written against and wrong beside it: measured over the same 500 ISBNs the
  source order is derived from, it was refusing 51 records that K10plus and the
  Austrian National Library already held. **Most of them are German language
  publishing**, 21 Austrian and 14 German of the 51, with 7 Spanish, 5 Italian,
  2 Brazilian, 1 Greek and 1 Uruguayan: the rule was written for those
  catalogues and was costing them most. A record now keeps the old rule where it
  names its own ISBN plainly as well, and drops it where a qualified entry is the
  only identifier the record has. The MARC importer read the same rule, so a
  catalogue file imported by hand lost those ISBNs too.

### Changed

- The default catalogue order asks Open Library before the Austrian National
  Library. The fallback list is asked one source at a time and stops at the
  first hit, so it is ordered by how often a source answers a book the leading
  pair missed. **Re-measured for this release**, with the Greek catalogue in the
  list and the qualified ISBN fix in place: of the 279 such ISBNs in 500, Open
  Library answers 83, the National Library of Greece 34 and the ÖNB 1, and the
  order is those three. The figures this entry carried a week ago, 297, 96 and
  2, were the same measurement before either change. Nothing changes for a
  library that has set its own order.
- The duplicate finder and the importers now compute one identity key
  (`importing.identity_key`) rather than two. The CSV importer's title only
  fallback is unchanged; MARC never matches on a title alone.
- `GET /api/books` now has its statement count pinned exactly, at 11, over two
  page lengths. It was a measurement in a docstring that nothing checked.

---

### Added

- **A provider list in Settings, Catalogue sources.** Every catalogue this build
  can ask is listed, with a switch and a position. Off means not asked, on every
  path that reaches it. The order is the order they are asked in: on an ISBN
  lookup the top two are asked together and the rest one at a time, and on a
  title search every enabled source goes out at once. A new install asks exactly
  what it asked before, so nothing changes until somebody moves something.

### Fixed

- **Every book listing loaded its tags twice.** `Loading.SERIALISED` fetched
  `Book.tags` and `books_to_out` fetched them again a moment later, so one
  statement per request bought nothing on the app's busiest read path. The
  shelf side is gone: `GET /api/books` costs 11 SELECTs where it cost 12, at 5
  books and at 25, and the routes that read the shelf twice in one request
  (`/api/books/{id}/copies`, `POST /api/books/{id}/restore`) drop two each.

---

- **Google Books was asked with the feature switched off.** Two of the six call
  sites that reach a catalogue passed the API key without consulting
  `google_books_enabled`, so scanning a barcode and refreshing a record both
  sent the ISBN to Google with the feature off, and with no key stored they sent
  it anonymously rather than not at all. Both switches are now conjoined in one
  place and every call site inherits it.
- **A request with every catalogue switched off said the book did not exist.**
  All four routes that reach a catalogue now answer 409 naming the setting,
  rather than a 404 that was a claim about the book made by an app that had
  asked nobody, or an empty result page that reads the same way.
- **Turning Google Books off left the records it had already supplied in the
  lookup cache for another day.** Every write that changes which catalogues are
  asked now drops it: the provider list, the Google Books switch and the Google
  Books key.

**Classifications are shown, filtered and sorted.** The catalogues have been
supplying Dewey numbers, Library of Congress call numbers and subject headings
for a while, and the app stored every one of them and displayed none. A book now
shows the headings it carries, each with the scheme named, because `004` is
computing in Dewey and is not a Library of Congress call number at all. Every one
is a link that narrows the library to the books sharing it.

The library gains a classification filter beside the tag filter, with counts: the
subject headings and numbers in the collection, and the Dewey shelf as its 100
divisions. It is deliberately a separate control rather than more chips in the tag
panel, because a tag is this library's own word and a heading is a published
scheme's, and flattening the two is what the store was built to avoid.

Books can also be ordered by Dewey number, with the unclassified last. Only Dewey,
because only Dewey sorts: a Library of Congress call number puts `BF75` before
`BF575` on a real shelf and text order reverses them.


**The Back and Upload Cover buttons on a book were unreadable in dark mode.** Both
painted their pill with the top surface token and their label with a dark mode
ink. That token is the one surface no palette and no mode redefines, so the label
moved and the pill did not: light text on a white pill, measured at 1.26:1 against
the 4.5:1 needed. They are the shared button now, which states the fill and the
foreground together, at 14.25:1 in light and 15.79:1 in dark. They also gained the
press state, the standard height and an icon in place of an arrow glyph, which
takes the spoken label from "arrow Back" to "Back".

## v0.11.0

_2026-08-29_

**Internal: the privacy rule now covers the tables that hang off a book.** A book
can be private, and one function decides who may see which books. That rule is
enforced by a test which reads the source of every backend file, and it only
noticed queries naming a book directly. A query over a book's classifications,
custom field values or tags names no book at all, so a page listing every Dewey
number in the library with a count would have included numbers from other
people's private books, and nothing would have failed.

The test now covers those tables. It reports every read of them and judges none:
which statements are safe is written down by hand, ten of them, each with a
reason. Which tables belong to a book is read from the schema rather than listed,
so a new one is covered the day it is added.

**Confirming an author's GND number now stores the other identifiers that come
with it.** The same authority record already carried an ISNI, an LCNAF number, a
VIAF cluster and a Wikidata item on every lookup; all four were shown once and
dropped. They are now kept, so an author has a stable identity outside the German
catalogue as well as inside it. Confirming an identifier answers with everything
it wrote, rather than with the one row.

**An identifier the two authority files disagree about is shown and never
stored.** A disagreement means they point at different records, and storing
either side would be resolution by precedence, which this feature refuses to do
anywhere. The conflict is reported beside the identifier instead. The two files
are now compared on ISNI as well as on the Wikidata item and the VIAF cluster.

**Internal: no test can reach the internet.** Existing tests began making real
requests to lobid the moment the confirmation endpoint made one, and nothing in
the suite would have said so.

**Internal: Settings is a route tree.** Six sections, each a heading and a line
saying what it routes to, with a page of its own behind it. A section only an
admin can use is not offered to a member, and still refuses them if they follow a
link to it directly.

**Author identifiers for six national libraries.** Confirming a GND number now
also stores the author's number in the national libraries of Brazil, Argentina,
Spain, Portugal, Italy and Chile. A GND record's own cross references carry ISNI,
the Library of Congress number, the VIAF cluster and Wikidata, and no national
file at all; the VIAF cluster that record names carries all six. `AuthorityScheme`
grows from five members to eleven, in one migration.

**VIAF is read as an enrichment and never as an entry point.** A lookup is
unchanged and costs nothing extra: it still asks lobid and Wikidata only. A
confirmation asks VIAF for the national identifiers, and only then. The cluster is
verified against the identifier that was confirmed rather than trusted, so a
cluster that does not name the same GND record back is discarded.

**Internal: a refusal test that had gone vacuous twice.** The check that the
scheme constraint rejects an unknown scheme used `viaf` until `viaf` became a
member, then `blbnb` until `blbnb` became one on the same day. It now uses a
classification scheme, which cannot become a person's scheme, and a new test pins
the two enums' overlap so the next widening cannot quietly disarm it.

**Overdue reminders in the app.** A fourth reminder channel beside the webhook,
mail and Telegram, and the only one that needs nothing obtained first: no receiver
to run, no SMTP account, no bot token. A banner on the library page says how many
of your loans are overdue and links to the list. It is on to begin with, unlike
the three that send catalogue content outward, because a household that has
configured nothing being told nothing is the problem the reminder feature was
filed to solve.

It is the one channel with a reader, so it is the one that can carry a member's
own private books: each person sees the overdue loans they lent or borrowed, an
admin sees every overdue loan on their shelf, and neither can reach a private book
somebody else added.

**It switches itself on for an existing install**, not only for a fresh one: the
default applies to a settings row nobody has written, and no household has written
this one. A library that upgrades will find the banner there without having asked
for it. That is intended rather than an oversight, since the channel sends nothing
outward and discloses nothing a member could not already see, but it is a change
to a running installation and it is said here rather than discovered.

**A reminder channel that has stopped working now says so.** Each run records what
every channel did, so a failure survives the run that produced it. The lending
settings screen shows the standing record under each switch: never run, working,
failed once, or not working since a date with the number of attempts. A channel
failing for a day is also called out on the library page.

The bar for that banner is deliberately high, because a notice that cannot tell a
network blip from a broken configuration is one people switch off. A refusal the
app made itself, a missing address or a setting it will not use, is reported at
once, since nothing was dialled and nothing will work until somebody changes it. A
destination that could not be reached is reported only after 24 hours and at least
two consecutive failures. Any write to a channel's own settings clears its record,
so repairing a bot token is what makes the notice go, and nothing else clears one.

**Internal: the image now carries YAZ, and the compile does not run on every
build.** National library catalogues speak Z39.50, and reaching them needs a client
library that Alpine does not package. It is compiled from source in a build stage
and the shipped image takes the library and one diagnostic binary, about 11 MB in
all. The compile takes a minute, and it runs when the YAZ version, the tarball it
was built from, the base image or the build recipe changes, rather than on every
push. The tree carries a stamp naming all four, and both the build stage and the
runtime stage check it, so a prebuilt tree that does not match is recompiled or
refused rather than shipped. Nothing in the application calls it yet.

**An email address per member.** A reminder can be addressed to the borrower rather
than only to the household mailbox. A member sets their own under Settings, Your
account; an admin sets anybody's on the same screen. **Nothing sends to it yet**:
overdue mail still goes to the household mailbox, and a member with no address is what
every row is on upgrade, so the column changes no behaviour until somebody fills a
field in.

**`LDAP_EMAIL_ATTRIBUTE` and `PROXY_EMAIL_HEADER`, both empty by default.** Set either
and the directory owns each member's address: it is re-applied at every sign in, exactly
as admin status already is, and the field becomes read only in the app. Left empty, the
directory is not asked and a member's own address is never overwritten. With the shipped
defaults an LDAP deployment's search asks for exactly what it asked for before.
**Turning either on clears the stored address of any member the directory has none for**,
and the field is read only from then on, so populate the directory first.

**A public catalogue, off by default and behind two switches.** Library mode changes
what a cataloguer sees and publishes nothing; publishing is a second, separate decision.
A publish switch left on while library mode is off is treated as off by the server, so
turning library mode back off cannot leave a catalogue public. Both are runtime settings
rather than environment variables, because an environment variable takes a redeploy to
correct.

**`GET /api/public/books` and `GET /api/public/books/{id}`** are the first routes in this
application reachable without a session: search and one item record, and nothing else.
Rate limited at 120 requests a minute, and `noindex` until indexing is separately
allowed. **`/robots.txt`** is generated from the same switches: disallow everything until
a catalogue is both published and allowed to be indexed, then allow the catalogue paths
and nothing else.

**`docs/featurelist.md` no longer says "No public catalogue. Nothing is readable without
a session."** That sentence was rewritten in the same commit as the code that made it
false, and `README.md` with it.

**A Wikipedia button on an author card, where the shelf knows who the author is.** An
author you have identified against an authority file now carries a second button beside
"Show these books": the Wikipedia W, linking out to the article about them. It opens in
the language you are reading the app in; where no article exists in that language it
falls back to the other one, then to any language at all, on the grounds that a page you
cannot read is still about the right person and beats no page. Where Wikipedia has
nothing, or cannot be reached, it links to the Wikidata entry instead, so the button
never leads nowhere.

**It appears only for an author whose identity has been confirmed**, which is what makes
it safe rather than merely available: two different writers share the name Robert Louis
Stevenson in the German authority file, and a biography of the wrong one is worse than
none. Nothing is stored, nothing is fetched but the list of which language editions
exist, and no biography or portrait is read.

**A second route to the six national library numbers, for when VIAF is down.** Those six
reach this library through a VIAF cluster, and until now that was the only route: an
outage there cost every one of them. Wikidata carries the same six and is now asked for
them when VIAF produces no cluster. One source answers per confirmation, never both, so
the two can never disagree and nothing changes on the ordinary path.

**Internal: a national number Wikidata states twice is dropped rather than picked from.**
The same rule already applied to a VIAF cluster naming one file twice. It is not a corner
case: 4,955 people on Wikidata carry more than one Spanish national number, and Cervantes
carries eight Argentine ones. A statement Wikidata has marked deprecated, which means it
knows the value is wrong, is not read at all.

**Internal: a Z39.50 transport**, a second door outward beside the HTTP one, bounded in
bytes and in time by construction. **Nothing asks a Z39.50 target during a lookup yet**
and the source chain is unchanged. It exists so that adding a national library catalogue
is a mapping rather than a protocol.

**Internal: `mailer.looks_like_address` accepted a trailing newline**, because it was
anchored with `$` under `match` and `$` matches before a final newline; it also accepted
NUL, ESC and every other C0 control, because its character class excluded only whitespace
and five punctuation characters. It is the rule the household recipient list, the sender
address and now the member address all check against, and four docstrings called it the
header injection control. Nothing was exploitable, because four independent `.strip()`
calls stood in front of it. It is `fullmatch` plus a Unicode category test now, and it is
tested with none of those callers in front of it.

**Six more wallpapers, and each family goes from five to eight.** Three more William
Morris repeats, Trellis (1862), Marigold (1875) and Jasmine (1872), and three more
decorated papers: Shippo, the Japanese linked circles; Meander, the Greek fret; and
Curl, the marbler's snail, which is Nonpareil worked a second time with a stylus. None
of them is an image: a wallpaper here is a rule that generates a tile, so a new one
costs a few kilobytes and takes its colours from whichever palette is in force.

What each reproduces, and on what basis it is free to reproduce, is tabulated in
`docs/theming.md`. The short version is that Morris died in 1896 and his firm's chief
designer in 1932, the eight paper traditions are geometric constructions with no author
at all, and nothing here is traced from anybody's photograph of anything.

**Three more palettes, taking the picker from seven to ten.** Kanagawa, Tokyo Night and
Ayu, each a port of a published scheme rather than an invention, each MIT licensed and
credited on the screen that offers it. Kanagawa is the fourth palette whose upstream names
both of its members, after Catppuccin, Rose Pine and Everforest, so the picker says Lotus
in light and Wave in dark; Tokyo Night and Ayu each publish a third theme with a name of its own, Storm
and Mirage, and neither of those is what is ported, so neither prints a member name rather
than printing one for a theme this app does not ship.

Every one of the six new blocks was generated to the same contrast contract the
seven existing palettes hold, and measured against it rather than eyeballed: body text at
7:1 on the card, the muted rungs at 4.5, the focus ring at 3.0, and the dark body ink
inside the anti glare band. `text-green-800`, the one raw Tailwind hue this app holds to a
floor at a call site, still clears on all ten; the darkest card of the ten is now Tokyo
Night's rather than Nord's and it holds there by 1.28.

**Overdue loans have their own page.** The library page keeps the reminder, which is a
count and a link, and the list of what is actually late has moved to a page of its own at
`/loans/overdue`, with the reminder channels' standing state beside it. A household
wanting to know whether a borrower was told had to look under a switch in Lending
settings; it is now on the screen the books are on.

**The overdue list and the count beside it now agree.** The banner counts the loans this
member is party to, and the loans page it used to link to shows every loan over a book
they can see, so the link handed some readers a screen with more rows on it than the
sentence they had just read. The new page asks an endpoint that applies the banner's own
rule.

**An overdue loan is visibly overdue on the loans page.** It stays in the list, and it
carries an edge bar as well as the badge that names the date the book was due.

**The loans page nudge counts the same loans the page it opens will list.** It counted a
wider set, so for most people it named a number the next screen disagreed with, and with
the reminder switched off it offered a page that had nothing on it.

**The channel panel no longer says where the loans appear.** It reports on channels that
send outward and knows nothing about the in app reminder's switch, so with that switch off
it promised the loans appeared on a page that was saying the opposite three lines below.

**Internal: the delivery status says what it can support and no more.** The health record
is written once per channel per run and holds no loan id, so no screen can say a
particular borrower was or was not told. The overdue page's note says that in as many
words, and a test pins the note to the lines it qualifies in both languages.

**The overdue page says so when it is showing you part of the list.** It asks for fifty
loans and the count beside the title counts all of them, so a household with more than
fifty overdue books saw a number the list disagreed with and no way to reach the rest.
It now names how many of how many are on screen.

**The overdue banners no longer call somebody else's loan yours.** An admin sees every
overdue loan in the household, so "{count} of your loans are overdue" was false for the
one reader who sees the most. Both banners now say the loans need chasing without saying
whose they are.

**Internal: two loan routes each made one database query per request that fetched
something already fetched.** Both listed a book's tags eagerly, and the serialiser loads
those tags for every book on the page regardless, so the work was thrown away. Removed
from both, measured at one statement fewer whether the page holds three loans or ten.

## v0.10.1

_2026-08-27_

**v0.10.0 was tagged and never published**, so this is that release plus the one
change that lets it ship. `verify:image` refused the image over a fixed openssl
advisory and skipped all three publish jobs, which is the gate working: nothing
went to Docker Hub. The cause was that the image build cached the layer which
upgrades the base system's packages, so the upgrade had not actually run against
the current package index for some time. The cache is now bounded and the
upgrade runs again. No application code differs between the two.

Everything below shipped as part of this release.

## v0.10.0

_2026-08-27_

**Added: the Austrian National Library is now one of the catalogues a lookup asks.**
An ISBN that the German National Library and K10plus both miss is put to the
ÖNB before the slower fallbacks, and a title search asks it alongside the other
six. Its records carry the same Dewey numbers and GND subject headings a DNB
record does, so confirming one enriches a book the same way. Metadata from it is
published under CC0.

It is a fallback rather than a first choice because that is what the measurement
supported: over 50 ISBNs from ten Austrian presses, the ÖNB held all 50, the DNB
47 and K10plus 39, and 3 were held by the ÖNB and by neither of the German pair.
Six percent is worth a request that costs nothing when the German pair answer.

**Fixed: titles from the ÖNB no longer arrive with the cataloguer's sorting brackets.**
MARC brackets a leading article so a catalogue can file `Die Klavierspielerin`
under K. Most catalogues use two invisible control characters for it and the ÖNB
uses `<<` and `>>`, so one title in seven would have reached the shelf reading
`<<Die>> Klavierspielerin`. It is also used inside personal names, so
`Einem, Gottfried <<von>>` was affected too.

**Fixed: a journal article is no longer offered as a book.** Over half of what an ÖNB
title search returns is articles and book chapters rather than whole
publications, and they have a title, an author and a year like anything else.
They are now recognised and dropped.

**Fixed: a catalogue record with an absurd page count no longer breaks the
whole search.** One record whose page count ran to more than 4,300 digits turned both
an ISBN lookup and a title search into a server error, for every catalogue at
once, rather than costing that one record. Found while adding the new
catalogue; it affected all of them and had been there for some time. A page
count outside the range a book can have is now ignored, and the record is kept
with everything else it carries.

**Internal: author authority identifiers, as an API change.** Nothing renders any
of this yet, so these are the endpoints rather than a screen.

- Author authority identifiers. The German National Library sends each author's
  GND number in its catalogue records and Endpaper was discarding it; it is
  stored now, on a refresh or an enrichment matched by the book's own ISBN.
- A new read, `GET /api/books/authors/authority`, answers with what the GND and
  Wikidata hold for an author: the authority's own spelling, dates, a one line
  description, and cross references. Where an identifier is already held it
  resolves that number; otherwise it searches by name and returns candidates.
  `q` retypes the name to search for.
- `POST` and `DELETE` on `/api/books/authors/identifiers` confirm a candidate
  and remove a wrong identifier. There is no verb that changes one: correcting
  it is a delete, and a re-import may write it again.
- Every identifier records whether a catalogue asserted it or a person chose it.
- Disagreements are reported rather than resolved: between two spellings merged
  into one author, between the two authority files, and between a catalogue and
  a value already held, which now comes back on the refresh that caused it
  instead of going to the log.

**Added: the predefined tags are shown in your own language.** The tags a new library
starts with are now translated, and German is the first language they exist in. A tag you
have renamed is left exactly as you typed it and stays that way: renaming a tag is how you
tell the app you want your own word for it, and there is no way to end up with a name you
did not choose showing over one you did. Tags you invented were never translated and still
are not.

**Fixed: a catalogue answering with an enormous record could stall every search at once.**
A response crafted to repeat one book thousands of times, with a single entry carrying
thousands of subjects, made the merge re-read that entry once per repeat. Measured at the
worst shape that fits inside the response size limit, that was over thirty seconds during
which nobody else's search would run. Repeats are now folded once, when the record is
built, and the time no longer depends on how much the record carries.

**Fixed: a book only Google Books knew about was refreshed without its page count, its
language or its Google id.** The fallback lookup dropped them on the way out of the source.
The same omission was found and fixed for Open Library on 2026-08-24.

**Internal: one type now carries every catalogue's answer.** Six source adapters used to
hand their answer across the seam as a dictionary, in two different shapes, with two
functions existing only to convert between them and one of those living in a route handler.
`backend/catalogue.py` replaces both with a `Record`. Folding a repeated heading, filling a
caption from whichever source has one, and treating an empty list as an absence rather than
as an answer were three rules spread across three sites; each is now one rule applied where
the record is built. Adding a catalogue is a mapping rather than a new dialect of keys for
every consumer to guess at. No behaviour change on the shelf.

**Added: a library can define its own fields on a book.** Name a field once, say
whether it holds text or a web link, and every book can carry a value for it. A link
field renders as a link out to another system, which is what this was built for: a
book's page in a calibre-web instance. Renaming a field keeps every value under it.
Deleting one takes them all and is admin only.

A link is only ever offered when the address stored is the address a browser will
visit. Some characters look like a full stop to a reader and are read as one by a
browser without being one: an address using them is rewritten so the words and the
destination match, and one that cannot be reconciled is shown as plain text rather
than as something clickable that goes somewhere else.

**Added: overdue reminders can now be sent by email and to a Telegram chat.** Until now
they went to a webhook only, which meant somebody in the household had to build a receiver
before the feature did anything, and most had none. Email works for anybody with a mailbox,
and Telegram needs a bot and a chat rather than a service of your own. The webhook is
unchanged and keeps working. Switch on as many of the three as you like: they all carry the
same list, and any one of them getting through counts as the loan having been chased.
Private books are left out of all three, exactly as they always were on the webhook, and
the count of what was held back is now reported for each channel rather than once for the
run. "Send now" reports one line per channel, so a run that reached the chat and not the
webhook no longer reads as a clean send.

Mail and Telegram are configured in Settings, under Mail and chat reminders. The
credentials can instead come from the deployment, through the seven standard `MAIL_*`
variables plus `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`; where one is set it wins, the
field is fixed in Settings, and the app refuses to store a value beside it that nothing
would read. Neither secret is ever sent back to a browser in full. Certificates are always
checked and there is no setting that relaxes that; a mail password configured with no
encryption is refused rather than sent in the clear. `MAIL_DEBUG` is deliberately not
honoured, because Python writes the password exchange to the log under it.

**Fixed: a catalogue could stop a search working, or use this server to reach somewhere
else.** Records are fetched from six third party catalogues. A reply that was much larger
than any real record could exhaust the server's memory, one that redirected could send it to
an address of the sender's choosing, and one that redirected to a malformed address took the
whole search down instead of dropping that one source. Replies are now capped, redirects are
followed only back to the same catalogue, and a bad one costs that catalogue its own results
and nothing else. The reminder webhook no longer reads the reply it is sent.

**Fixed: a spreadsheet holding two rows for the same book could abandon the whole
import.** One row carrying a rating and another carrying a reading status, for a book
the library already had, ended the import with nothing written and no explanation. It
now applies both rows.

**Fixed: some changes did not reach the library grid until you left the page and came
back.** Merging two authors, returning a loan, and several edits made from a book's own
page updated everything except the grid itself, because the instruction to refresh it
named the wrong thing. The grid caught up on its own within thirty seconds of leaving
and returning, which is why this looked like slowness rather than a fault.

**Changed: editing a book no longer reloads everything else on screen.** A write used
to throw away the whole cache, so a page showing ten things fetched all ten again. It
now refreshes what the change actually affected: ten requests down to five for a tag
change, and to two for an ordinary edit. Confirming a book you found by searching no
longer repeats the search, which on the metadata sources is a billed request.

**Internal: one module now owns the reading record.** `backend/reading.py` is the only
place that reads or writes what you have read, what you are reading, your rating and
your dates. Those rules were spelled out at eight call sites, each carrying the same
rule that a reading record is yours and not the library's. Nothing about what anybody
sees has changed.

**Changed: two shelves whose names differ only in case are now one shelf, and an
upgrade merges any pair a library already has.** A library that had both "Ästhetik"
and "ästhetik" had two shelves nothing downstream could tell apart, because the rule
that keeps one name per collection compared only the twenty six plain English letters
and left every accented one alone. It now compares every letter, so the pair cannot be
made again. Where one already exists, the upgrade keeps the older of the two shelves,
moves every book from the newer one onto it, and writes both spellings into the log.
No book is deleted and none is left unfiled. Merging two shelves cannot be undone.

Restoring a backup does the opposite and says so. An old backup holding such a pair
is refused, naming both spellings, rather than merged quietly: an upgrade cannot ask
anybody anything, but somebody restoring a file can be told what is wrong with it and
where to fix it.

**Fixed: a name starting with an accented letter sorted after every other name.**
A collection called "Ästhetik" or an author called "Émile Zola" was filed below
"Zebra" rather than beside "A" and "E", because the database compares letters by
their number and an accented letter's number is above every plain one. Collections,
tags, series and the author index are now ordered by the browser, in the language
the app is set to.

**Internal: one module now owns every book query.** `backend/shelf.py` is the only
place that applies the privacy rule, so a listing, a count, an index or an export
is scoped to what a member may see by how it is built rather than by remembering a
filter. Nothing about what anybody sees has changed; the rule it enforces is the
same one, enforced in one place instead of twenty four.

**Fixed: a backup did not include the author merges, so restoring one split
every merged author back into its spellings.** The books themselves were always
intact, which is why nothing looked wrong: a merge records a decision and never
rewrites a book. Backups taken from now on carry the decisions. An older archive
restores with none, which is the state it was written in.

**Fixed: some pages could leave the server holding on to memory it never freed.**
Every "not found" answer from the cover, book and author routes kept a little
state alive for the lifetime of the process. Nothing was exposed and nothing was
lost; a busy library would have seen memory climb slowly.

**Internal: the library's filters have one owner, and the two sides are now checked
against each other.** Reading them out of a link and turning them into a request were
written in different places, and nothing said they described the same set of filters.
They do, and a test proves it against the API's own schema from now on. Nothing about
what the filters do has changed.

**Fixed: importing a library export could fail completely if one of its shelf
names was not plain English.** A shelf called "Ästhetik" that already existed as
a tag made the whole import stop and write nothing, every time, with no useful
message. Nothing was lost, but nothing arrived either.

**Fixed: the import preview had no rate limit**, although the documentation said
it did. Reading a large file is the expensive half, so it is now limited
together with the import itself.

**Internal: applying an import has one owner too.** The code that reads a parsed
export and writes it into the library moved out of the request handler. Nothing
about importing behaves differently.

**Internal: author identity has one owner too.** The rules for deciding that two
spellings are one person were already in their own module and were already pure;
everything the database knew about it was in a route handler. Both halves now sit
together. Nothing about merging, undoing a merge or filtering by an author has
changed.

## v0.9.0

_2026-08-26_

**Classification review.** Metadata refresh and automatic enrichment now update scalar
facts only. Choosing a catalogue record shows its Classifications first, then adds the
selected evidence to the book.

**Endpaper is for libraries and archives too, and now says so.** It was always
usable by a small library, and every page described it as a household tool, which
told the wrong half of its audience it was not for them. The description is now "a
self-hosted catalogue for the books you share", built for a household's shelves and
for the library or archive that has outgrown a spreadsheet.

Nothing about how it behaves has changed. The features a library needs are still
being built, and the pages say only what has actually shipped.

Two interface labels read better as a result: "Household tags" is now "Your tags",
and the German text no longer assumes the people sharing a catalogue live together.

## v0.8.0

_2026-08-25_

A larger refactor of UI elements, naming conventions, documentation and
presentation style.

The `:latest` image also reports its version again. It read `unknown` between
releases, and `:latest` is what most self-hosters run, so the version was
missing on every day that was not a release day. It now names the release it
descends from. Tagged releases were never affected.

## v0.7.0

_2026-08-24_

**Library of Congress subject headings.** A title search now brings back what a
cataloguer said the book is about, in the Library of Congress's own controlled
vocabulary: `Computer programming`, `Software architecture`,
`Computer software -- Development`. They ride along on the record the search
already fetched, so nothing got slower and no new service is involved. Measured
over 900 live records: 85% carry at least one.

They are kept whole, subdivisions included, because `Computer software` and
`Computer software -- Development` are two different headings with two different
sets of books under them. Nothing displays them yet.

**The About card carries the README's badges.** Version, licence and source, at
the top of the card at the foot of Settings, where the version and a source link
used to sit as a sentence. They are drawn rather than fetched: no shields.io and
no image at all, so they take the colours of whichever palette you chose, they
render with the app installed and offline, and opening Settings tells no outside
service that your server exists.

**Classifications are stored whole.** A catalogue heading is a scheme, a number
and a caption: `GND`, `4203576-4`, `Schatz`. The number used to be stripped off
at parse time so the caption could substring match a tag by name, which threw
away the only half that means the same in two languages.

**Which is why German records now suggest tags at all.** Measured against the
DNB over ten German ISBNs: eight carried a DDC heading, and not one of the eight
captions matched any of the 105 built in tag names, because every caption was
German. Dewey `830` now suggests Fiction and `004` suggests Computing, through
a mapping of the 100 published Dewey divisions that reads the number and never
the words. Which is just as well, because the catalogues send the number
without any words at all.

**It stays a suggestion.** The suggested tags arrive ticked on the add form and
nothing is written until you press the button, so an unwanted one is one click
away rather than something to find and undo later. Tags are a small curated list
the household chooses from, and one nobody chose cannot later be told apart from
one they did.

**German records come back with proper subject headings.** The German National
Library is now read in the full catalogue format rather than the summary one it
was asked for before, and the difference is what the summary left out: the
subject headings a librarian assigned, each with the identifier that names it in
the national authority file. A book about a treasure hunt in Samoa arrives filed
under Schatz and Samoainseln rather than under nothing.

**And it fixed things nobody had noticed.** Records for older books had the
translator credit sitting inside the title. An edited volume had no author at
all. German umlauts arrived in a form that looks identical on screen and counts
as a different word, which was enough to file one author under two spellings.
Titles beginning with an article carried two invisible control characters, and
one carried a stray double space. Page counts now arrive on 71 of 74 records
where they used to arrive on 50.

**A well catalogued book no longer disappears from search.** A search result
carrying more subject headings than a book is allowed to keep was being thrown
away whole rather than trimmed. It now keeps the eight that matter most, and
the classification a tag suggestion reads is the one that survives.

**"Other editions of this book" now means it.** The picker used to search
every catalogue for the title and author, which is a good guess. It now asks
Open Library for the printings it has merged under the same work, with the
book's own ISBN, and puts those first: a donation in an unfamiliar printing is
matched against the actual list of printings rather than against whatever a
search returned. Editions in another language are left out, because a
translation cannot tell you what your copy's page count is.

**Open Library answers with far more than it used to.** It is read as three
records rather than one, and across 35 books that means subjects on 28 of them
rather than 16, a page count on 20 rather than none, a language on 27 rather
than none, and a Dewey or Library of Congress number on 12 rather than none. It
costs a tenth of a second.

**A DVD is no longer offered as a book.** A scanned identifier that names a
disc is refused rather than catalogued; an ebook edition of a book you are
holding is still offered, because it is the same book.

**A third way to look at the library.** Beside the covers and the table there
is now a list: one dense row per book, a tiny cover, and the title, author,
series, year and reading status beside it, with a marker when the book is out on
loan or nobody has confirmed you own it. It is for the case the other two are
bad at, which is finding a book you know you own without reading twenty one
columns or scrolling past forty covers. Your choice is remembered in your
browser, as it already was.

**Suggested tags stop reading a word inside another word.** "Software
engineering" used to suggest **War** and "thoughtcrime" used to suggest
**Crime**, and since suggestions arrive ticked, those got written unless you
noticed. Measured over 22 books, 12 of 32 suggestions were wrong that way, and
on German records every single one was. It costs one real suggestion: a book
filed under "fiction classics" no longer offers **Classic**, because the tag is
singular and the subject is not.

**Headless.** `SERVE_FRONTEND=false` runs the API without mounting the compiled
frontend, for a host that has no reader to serve a page to. One image and one
flag: the built files stay on disk, unused. With it set, a path outside the API
is a plain 404 rather than the app shell, which is correct, because a host
serving no frontend has no client routes for the shell to rescue.

**Settings folds.** Eleven cards, the same disclosure and the same per device
memory the book page uses, against a fixed rule: a card that answers "what is
this set to" arrives open, a card that starts a job (import, cover backfill,
overdue reminders, test accounts, backup) arrives closed. Your own choice wins
after that, and is remembered per card.

**An About card** at the foot of Settings: the version you are running, a link
to the source, and one sentence asking whether you would like to buy the author
a coffee. The Ko-fi button is served from your own deployment, so opening
Settings tells Ko-fi nothing.

**Funding links**, in `README.md`, on the Docker Hub page and in that one
sentence. The money is for running a shared relay. It is not a paid tier and no
feature sits behind it.

**The version on that card is now the tag you released**, derived at build time
rather than typed into a file first. Nothing is bumped before tagging: a release
shows `0.7.0`, a working build shows `0.6.0-14-gbbdf755` and cannot be mistaken
for one.

## v0.6.0

_2026-08-23_

Five features, and a bug that had been hiding under a comment saying it was
fixed.

**More than one copy of a title.** Two paperbacks of one book are two objects,
each with its own condition, location and lending state. This meant breaking the
rule that an ISBN is unique, which every other feature here assumed, so it went
first: uniqueness now applies to single copies only, through a partial index.

**Collections.** Named parts of a shelf, one per book: physical from ebook, kept
from sold, yours from mine. Filing a book changes nothing about who may see it,
which is deliberate. A collection is shelving, not permission.

**Author pages, and merging.** Everybody your shelf credits, with their books
behind one click. When one person arrives spelled three ways you can fold them
together, and the merge writes nothing to any book: it records the decision, so
it is reversible, it survives a re-import that would otherwise split the name
again, and it can express a spelling no book carries.

**Quotes.** A passage worth keeping, with the page it is on and your own line
about it beside it. Kept separate from notes because one is meant to be verbatim
and the other is not.

**The book page folds.** Seventeen panels in one column became six collapsible
groups plus a heading that never folds. What arrives open depends on the book: a
loan section opens on a book that is out, copies on a book with more than one.
Your own choice to open or close a section wins over that, permanently, on that
device.

**The endless spinner is fixed, and it was two faults.** The client did not tell
the server it wanted JSON, so a portal answered an expired session with a
redirect rather than a 401; the service worker then served the cached shell to
the reload, so the reload never reached the portal. Round and round. Both are
closed, and a guard now makes a second reload in one page load impossible: a
loop degrades to a page that says what happened.

**Deep links survived nothing before this.** `/book/12` and every other client
route answered 404 on refresh, with a valid session, and had since v0.2.0. Five
documents said otherwise, one of them published. The shell is now served for an
unmatched path that is not an API route, that accepts HTML, and that is not an
asset, so a bookmark works, a refresh works, and a shared link works. `/login`
was 404ing too, which behind a portal is invisible and in the default local mode
is the sign-in form.

**Cache headers.** The shell revalidates, hashed assets do not. A reader holding
yesterday's page no longer asks for a script that a deploy deleted.

**Five migrations run on start**, in this order: `d1a7f36b9c58` adds lending
willingness, `b1e7c94a2d05` makes a second copy legal, `c2f95a80d417` creates
`collections`, `a9c4e7b21d03` creates `author_aliases`, and `d3f6b81c9a27`
creates `quotes`. All additive, all with a working downgrade, and none touches an
existing row's data. The copies one is the only one that changes a constraint:
it replaces the unique index on `books.isbn` with a partial one, so a downgrade
fails rather than silently dropping the second copy of anything.

**Dropped, so nobody goes looking.** Linking a physical book to an ebook: the
useful half of it already exists, since a copy can be marked as an ebook format
and two copies of one title are now two rows. MARC import and export, and
printable reports.

## v0.5.0

_2026-08-22_

Also in this release, after the section below was written:

**Covers are stored here rather than hotlinked.** A candidate is verified, then fetched
and written beside the book, so a cover no longer depends on a third party being
reachable from every reader's browser. `POST /api/books/covers/backfill` repairs a
library that predates this, a hundred books at a time, and reports what it could not
find. Fetching is restricted to an allowlist of hosts, which closed a server-side
request forgery that predates this release: a member-supplied `cover_url` was fetched
with redirects followed and no host check.

**The service worker no longer pins a broken cover for a month.** It cached
cross-origin covers `CacheFirst` with no restriction on what may be stored, and an
opaque response cannot be told from an error, so one failed fetch blanked a cover for
thirty days. Now `StaleWhileRevalidate`, only 200s are stored, and the cache is renamed
so already-poisoned entries are dropped rather than inherited.

**A fourth reading status, did not finish.** Started, not finished, not going back.
Recording progress on such a book returns it to reading; nothing deletes the log.

**The library can be read as a table**, nineteen columns, sortable on what the API can
actually order by, with the choice remembered. Cards gained a fold out.

**The health probe can fail.** It ran `SELECT 1`, which on an already-open SQLite handle
is served from cache and issues no RPC, so this app stayed ready for 39 hours through a
total storage outage. It now performs a filesystem operation with its own timeout, and
answers 503 when storage cannot be reached. Set `timeoutSeconds` above 2 on any probe
that calls it: the Kubernetes default of 1 makes the check inert.


Where you are in a book, and something that chases the books that are out.

**Two migrations run on start**, in this order: `f7c2a1e50b93` creates the
`reading_progress` table, and `a3e94c0d15f8` adds `loans.notified_at`. Both are
additive, both have a working downgrade, and neither touches an existing row's
data. The second drops and recreates the partial unique index on open loans
around its batch step, because batch mode rebuilds a SQLite table by reflecting
it and that index coming back as a plain unique one would forbid ever lending a
book twice.

### Added

**Reading progress.** Record the page you reached, or a percentage for an
audiobook or anything with no page count, as often as you like. It is an
append-only log rather than one editable number, which is what lets it answer
"how much did I read in March" as well as "where am I". Each entry can carry how
long the sitting was. The first entry on an unstarted book moves it to reading
and stamps the date, because saying where you are is the same claim the status
button makes; nothing ever moves a book to read on a page number, since page
counts come from catalogues and are off by one often enough that the last page
proves nothing.

A member's log is theirs. Two people reading the same copy see their own
positions and never each other's, on a shared shelf as much as a private book.

**Pages read, by month**, on the stats page. Computed from the differences
between consecutive positions, and covering page-tracked books only: an
audiobook records a percentage, and turning that into a page count would produce
a figure that adds up with the others while meaning something else.

**Overdue reminders, by webhook.** Endpaper can POST a digest of every overdue
loan to an address you choose, hourly, signed with HMAC-SHA256 so the receiver
can check it really came from here. How many days pass before the same loan is
chased again is yours to set. A generic webhook rather than email or one chat
service, because a self-hosted app should not carry an integration with
something only one household runs.

**Private books are never in it.** A webhook has no account behind it and lands
in a channel everyone reads, so a private title there would be readable by all
of them. The digest says how many it left out without naming one, and the owner
is still chased in the app, where the overdue view is per member. The settings
screen says this in words rather than leaving it to the documentation.

There is a **Send now** button beside the settings, which runs the digest
immediately and says what happened: sent, and to how many loans; or which of the
four reasons it sent nothing, because a switched-off toggle, a missing address, a
quiet week and a webhook that refused the request are four different problems and
only one of them is not a problem. That is what makes the feature checkable by a
person, and it is the endpoint to point an external cron at:
`ENABLE_OVERDUE_TICKER=false` turns the in-process timer off.

### Fixed

**A backup taken before this release still restores.** Adding a table to the
archive would have made every older backup fail with "the backup is missing:
reading_progress", because the restore required every table it knew about to be
present. A table added after format version 1 is now optional and restores as
empty, while a truncated archive missing `books` is refused as before.

**A restore now reports the reading statuses it put back.** `user_books` was
absent from the report, so a restore that dropped every member's entire reading
history read as a clean one. It is counted now, along with the progress log.

**Covers are downloaded and served from here, not linked to somebody else's
server.** A hotlinked cover needed five things to keep working: the image
service being up, the URL not rotting, this app being able to reach it, your
browser being able to reach it, and the content policy permitting it. Four of
those five are outside this application, so a shelf could go blank for a reason
nothing here could see or fix. Measured on the running deployment, the covers
directory held **zero** files, so that described every cover in the library. It
also stops your browser telling `covers.openlibrary.org` which books the
household owns, once per book, every time the grid draws.

Every way a book gets added now resolves a cover, including **the CSV import,
which never did**: a library that arrived that way showed the placeholder on
every single book and nothing in any log said why. The import itself does not
fetch, because a fetch per row over thousands of rows would hold the request
open until a proxy gave up on it. **Settings has a Covers section** that fetches
the ones that are missing, a hundred at a time, six at a time within that, and
tells you how many it stored, how many had a cover that could not be downloaded
from here, how many no service has one for, and how many are left. Each press
carries on from where the last one stopped, so a book that cannot be fixed does
not block the ones behind it, and reaching the end starts over. It is safe to
press twice. If a download fails the remote link is kept, so
the worst case is what the app did before.

**A cover URL nobody could parse used to break the repair button for everybody.** A URL
with an impossible port, like `:99999`, was accepted onto a book and then crashed every
attempt to fetch it, for every member, permanently, because one bad row is enough. It is
refused up front now, and a cover failure of any kind can no longer fail the request that
provoked it: adding a book always saves the book.

**Covers must come from one of the four image services this app knows about.**
`cover_url` can be typed by anybody with an account, and adding a book makes the
server fetch it, so without a host check that was an account holder choosing
which address this server connects to. Redirects are followed by hand, two hops
at most, and every hop is checked. The blind version of that predates covers
being stored at all.

**A fourth reading status: Did not finish.** Started, not going to be finished.
The date you started is kept, because that happened; the finish date is cleared,
so a book you gave up on is never counted in "books finished this year", and the
record of how far you got is left exactly where it is. Recording a new position
puts the book back to reading, because that is what picking it up again is.
Goodreads and StoryGraph shelves called `abandoned`, `dnf` or `did-not-finish`
all import onto it.

**Library cards fold out.** Title, author and up to three tags with the genre
first; press Details for the series, year, publisher, shelf, format, condition,
page count, the remaining tags and what the copy cost, without leaving the grid.

**A table view for the library**, toggled beside the sort control and remembered
in your browser. Nineteen columns of metadata, sortable on the ones the server
can order by, scrolling inside its own box so the page never slides sideways.

### Fixed, in the app

**Covers that had gone are back, and the cause was in your browser.** This is the fault
that was reported, and nothing on the server was wrong: the library had a cover URL on
every book, three of the four answered with a real image when fetched from the server, the
content policy allowed the host and DNS resolved it. The offline cache was storing cover
images with `CacheFirst` and no check on the response. A cross-origin image request cannot
tell a 404 from a picture, so a failed cover was cached as though it were one, and
`CacheFirst` then served it for **thirty days** without ever asking again. Covers are now
revalidated in the background, an error is never stored, and the cache has been renamed and
the poisoned one deleted, so the fix reaches browsers that already have the bad entries. It
also now covers all four image services rather than Open Library alone.

**The Goodreads lookup can be found.** It was a 14 pixel chain-link icon at 60%
opacity beside the title, with no label. It has moved down to the actions, with
its own words, at a contrast the rest of the app holds to.

**The health probe now detects the failure it was written to detect.** During a
total storage outage on 2026-08-22, `/api/healthz` answered 200 continuously and
the pod stayed ready for **39 hours**. `SELECT 1` on an already-open SQLite
handle is served from memory and never reaches the disk, so it could not fail in
the mode that mattered. It now also stats the data directory, which has to cross
the wire, under a timeout of its own so a hung mount is a failed check rather
than a handler that never answers.


## v0.4.0

Seven palettes, ten wallpapers, and a screen to choose them on.

**v0.3.0 was never released.** Its section below is a true record of what landed,
but no tag and no image were ever published for it, so there is nothing to
upgrade from. This release contains both, and upgrading from v0.2.1 goes
straight here.

**Two migrations run on start**, in this order: `c4d8e91a2f60` adds the three
appearance columns to `users`, and `e6f1a94b2d73` adds the flag that marks an
admin-created test account. Both are additive, both have a working downgrade,
and neither touches an existing row's data.

### Added

**Appearance is something you pick, at `/settings/appearance`.** A palette, light
or dark, and a wallpaper, applied the moment you choose and saved to your
account, so the look follows you from your laptop to your phone. Its own screen
rather than a row in the settings list, because the only honest preview of a
wallpaper is the page: the pattern is painted behind everything, so the picker is
the app with the controls laid over it. The preview on top of it is your own
first two books, not invented sample content.

**Seven palettes.** Endpaper, Catppuccin, Rose Pine, Gruvbox, Solarized,
Everforest and Nord, each in light and dark. The colours belong to their
projects; the lightness of each rung belongs to this app, so every palette clears
the same contrast floors rather than shipping whatever the upstream editor theme
happened to publish. Every correction, with the contrast that forced it, is
tabulated in `docs/theming.md`. Nord publishes no light theme, so its light
member is built here from Snow Storm and Polar Night, and the picker says so on
the tile rather than greying out a control every other palette leaves alone.

**Ten wallpapers, in two families.** Five after William Morris (Willow Bough,
Acanthus, Pimpernel, Strawberry Thief, Golden Lily) and five decorated papers
(Nonpareil, Seigaiha, Asanoha, Plait, Khatam). They are drawn rather than
shipped: every tile is generated in the browser from the palette's own ink, so a
pattern costs no download and follows whatever colours you chose. **None** and
**Surprise me** are tiles beside them, and a new account starts on Surprise me.

**Licences on the screen that offers them.** Six MIT notices and the note that
this project is not affiliated with Morris & Co.

**Test accounts an admin can switch into.** Sign in as any member from the
settings page to see the library as they see it, and come back the same way. The
query cache is dropped on every change of account, so nobody's private books
survive the switch.

**A top bar instead of a left rail**, and **lending to somebody who has no
account**: both landed before this release was tagged, and are described under
v0.3.0 below.

### Fixed

**The wallpaper no longer arrives a frame late.** The palette, the mode and the
pattern are applied together before React mounts, rather than the first two
synchronously and the third from an effect. Nobody noticed while the pattern was
faint and never changed; a picker makes it the first thing you watch for.

**Muted text on a light card was below AA.** `paper-400` and `paper-500` measure
2.35:1 and 3.83:1 against the card where WCAG wants 4.5, and were text in
fourteen places. A test now fails the build if either is used as light-mode text
again.

**One rose did both "want to read" and "delete".** They are separate colours now,
because a colour that means both a pleasure and a danger means neither.

**The green success message failed AA on every palette.** `text-green-600`
measured 2.79 to 3.22 against 4.5; it is `text-green-800` now, measured 6.19 to
7.13.

**Twenty-one controls drew their own focus ring**, at 2.24:1 against a page where
WCAG 1.4.11 wants 3:1, and sixteen of them killed the browser's own first. There
is one ring now, and a test that keeps it that way.

**More contrast was honoured on the default palette only.** The
`prefers-contrast: more` block was outranked by every palette block, so six of
the seven silently ignored it. It also turns the wallpaper off, and the picker
says why rather than showing an off state nobody chose.

### Changed

**Tag pills are no longer colour coded by category.** The category is written on
the pill, and the three hues cost fifteen tokens per mode to say the same thing
twice. A tag the household invented keeps the accent, which is the one
distinction with a reason.

## v0.3.0

Four bug reports, and what fixing them turned up underneath.

### Fixed

**No cover appeared on a German shelf.** Every stored cover was blocked by the
browser, with a 200 on the record and nothing in any log. `covers.py` resolves a
978-3 ISBN through the DNB's cover service, and that host was never added to the
Content-Security-Policy, which was a hand-written list beside it. The policy is
now derived from the one list of hosts, and a test walks the AST of every backend
module to keep cover URLs from being written anywhere else: `metadata.py` held six
of them, which is the door the same bug would have come back through.

**Google Books thumbnails could not render either.** Google serves them over plain
http, which is mixed content on an https page and blocked whatever the policy
says. They are upgraded on the way in, on every path that stores a cover, and a
one-shot migration upgrades the rows already stored.

**A cover that failed to load took the layout with it.** The old handler removed
the image from the flow, which collapsed the book page's header to nothing and
dropped the back button on top of the title. Every cover in the app now falls back
to the same placeholder, at the same size.

**The back button did nothing on a deep link.** It was `navigate(-1)`, and a
shared link, a reload or a PWA cold start has no prior entry to go back to. It now
goes back where there is somewhere to go, and to the library where there is not.

**Registration refused the attempt and charged you for it.** Under `ldap` and
`proxy` auth the rate limiter ran before the refusal, so an anonymous caller could
exhaust a real budget on a route that can never succeed. The refusal also told
proxy deployments their accounts were "managed by the directory", where there need
not be one.

**A backup restored covers the browser blocks.** A restore inserts through Core,
so the column validator never fired. It calls the upgrade itself now.

### Added

**Lend to somebody who has no account.** A neighbour, a colleague, a book club.
The borrower is either a member or a typed name, exactly one of the two, enforced
by a CHECK constraint rather than by the schema alone, because a restore and an
import do not go through the schema.

**A top bar instead of a left rail.** Library, scan and loans stay on the bar as
icons; everything else moved into a menu behind the account trigger, which still
names the person signed in. The rail spent 56px of a phone's width on every screen
and had nowhere to open a menu into. Under proxy auth the menu no longer offers
sign out or switch account: the upstream owns the session and both were inert.

**A network failure says so.** A rejected request used to print the browser's own
"Failed to fetch", untranslated, to whoever was standing in a tunnel.

### Security

A cover URL is now required to be `https://` or one of our own uploads. Nothing
was exploitable through the values this rejects, and all of them become
exploitable the day `img-src` gains a wildcard or a cover is rendered outside an
image tag.

### Tested

The login and registration flow through the HTTP routes and the UI in all three
auth modes, which had thorough unit tests for the backends and nothing for the
routes.

## v0.2.1

Documentation only. No code change, and the image is a rebuild of the same
source.

The README's feature list had fallen behind what v0.2.0 actually shipped. It
omitted **per-book privacy**, **series gap detection** and **duplicate merge**,
which are three of the things this project does that most alternatives do not,
and said nothing about rapid scanning, ratings and notes, due dates and overdue
loans, bulk edits, saved views, statistics or the health endpoint. It also still
said the first account to *register* becomes admin, which stopped being the
whole story once proxy and LDAP deployments got an admin bootstrap.

Rewritten and grouped, and it now links the changelog.

## v0.2.0

The first release that publishes both source and an image. v0.1.0 got half way:
GitHub received the source, Docker Hub received nothing.

### Added

**Metadata, four sources instead of two.** The DNB and K10plus are asked
concurrently and their answers merged, then Open Library, then Google Books.
Which is asked first is decided by the ISBN prefix, so a 978-3 goes to the DNB.
No key is required for any of the first three, and Google is optional.

**Covers are verified before they are stored.** A candidate URL is fetched and
answered three ways: present, definitely absent, or unknown. Unknown keeps the
URL, so a momentary 5xx at the image host does not throw away a cover that
exists.

**Import from anything, not just Goodreads.** Columns are guessed rather than
required, with a preview before anything is written. Measured against real
exports from Goodreads, StoryGraph, LibraryThing and Calibre, and a list
somebody typed by hand.

**Backup and restore.** The whole library plus every cover as one zip.

**Tags a household can invent for itself**, beside a curated vocabulary grown
from 32 to 105 and grouped by category in the picker.

**Trash.** Deleting a book is reversible, with a window to change your mind.

Also: saved searches, a wishlist view, overdue loans that say so, and format,
condition, price, purchase date and purchase source on a book.

### Fixed

**Proxy and LDAP deployments had no admin bootstrap.** Registration is 403 in
both modes and admin came only from a configured group, so deploying with
`AUTH_MODE=proxy` and no groups header produced a library nobody could
administer, and switching an existing local deployment to a directory demoted
the existing admin on their first page load.

**The cover cookie was a copy of the access token.** It is now scoped and
refused everywhere but the cover route, so a copy that escapes cannot be
replayed against the API. `POST /auth/logout` clears it; nothing did before, so
it outlived the session.

**A restore could hand a live session to the wrong person.** It replaces the
users table, so the id in an existing token may afterwards belong to somebody
else. Tokens now carry an epoch that a restore rerolls.

**Foreign keys were not enforced**, which made every `ON DELETE CASCADE` in the
schema decorative. Turned on, along with WAL and a busy timeout, and every
foreign key column is now indexed.

**One open loan per book is a database constraint.** Merging two records used to
leave both open, so a book could be out with two people at once.

**Uploads are refused before they reach the disk.** A 200 MB request aimed at
the 5 MB cover endpoint was spooled to a temporary file in full and only then
answered with a 413.

**A failed cover upload no longer destroys the cover that was there.**

**Rate limits** on library import and on the metadata fan-out, which reaches as
many as four public catalogues per call.

**Re-scanning a book you already own** offers to open it, rather than answering
with a sentence and no way forward.

**The account menu was unreadable on a phone**, folded into a 56px rail.

### Changed

- `POST /api/books/bulk/ownership` is removed. `POST /api/books/bulk` with
  `set_ownership` has the same body, the same permission rules and the same
  result.
- `GET /api/healthz` is the health endpoint. Container probes should point at
  it rather than `/`, which is answered from disk and stays healthy when the
  database is not.

## v0.1.0

Source published to GitHub. The image did not publish.
