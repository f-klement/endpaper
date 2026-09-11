"""Closed value sets shared by the ORM, the schemas and the query parameters.

These are `StrEnum`, so they compare equal to their string value and store as
plain text in SQLite, so existing rows keep working untouched. The point of
declaring them is what happens downstream: FastAPI emits them into the OpenAPI
schema as enumerations, which is what lets the generated TypeScript client have
union types like `"unread" | "reading" | "read"` instead of `string`.
"""

from enum import StrEnum


class ReadStatus(StrEnum):
    """A member's own progress through a book. Stored in `user_books.status`.

    WANT_TO_READ is deliberately distinct from UNREAD: "on the shelf, not
    started" and "I intend to read this" are different statements, and
    Goodreads exports carry the distinction (its `to-read` shelf), so
    collapsing them would lose information on import.

    DID_NOT_FINISH is started, not finished, and not going to be. Named for
    what the two apps that ship it call it rather than for the act: Openreads'
    fourth list is "books you didn't finish" and BookLogr's is "Did not
    finish". Neither calls it "abandoned", and matching them costs nothing
    while a third spelling of the same shelf costs a reader a moment every
    time. The importers accept `abandoned`, `dnf` and the German for both, so
    nothing turns on the stored spelling.

    **It is not a kind of READ**, and every query that counts finished books
    tests `finished_at`, which `_stamp_reading_dates` clears for it. A book
    somebody gave up on must never appear in "books finished this year".

    No migration: the column is a plain string, so a new member needs no DDL.
    """

    UNREAD = "unread"
    WANT_TO_READ = "want_to_read"
    READING = "reading"
    READ = "read"
    DID_NOT_FINISH = "did_not_finish"


class OwnershipStatus(StrEnum):
    """Whether a book is physically on the shelf.

    Deliberately separate from ReadStatus, which is about a person, not an
    object. "I have read this" and "we own a copy of this" are independent
    claims: a library borrowing is read but not owned, and an unread gift is
    owned but not read. Conflating them is what makes an imported reading
    history look like a catalogue of possessions.

    UNKNOWN exists because a Goodreads export cannot answer the question at
    all. Defaulting those rows to OWNED would assert something nobody checked;
    defaulting them to NOT_OWNED would be an equally unfounded guess. So they
    arrive unverified and wait to be confirmed.
    """

    OWNED = "owned"
    NOT_OWNED = "not_owned"
    UNKNOWN = "unknown"


# **This docstring is the API's own description of the type.** FastAPI copies it
# into `frontend/openapi.json`, which is served at `/openapi.json` and mirrored
# into the generated TypeScript client, so what belongs in it is what a reader
# of the API needs. Where a maintenance note has to live beside the values, it
# goes in a comment like this one, which stops at the file.
#
# No migration is needed for a new value: the column is a plain `String(20)`
# with no check constraint, so the closed set is enforced here and in the schema
# rather than in the database. That is checked against the database a deployment
# has rather than against this comment, by
# `tests/test_schema.py::TestTheBookFormatColumnOnAMigratedDatabase`, which
# migrates to head, reads the constraints off the built table and then stores
# every member. A revision that constrained the column fails there rather than
# at a member's import.
class BookFormat(StrEnum):
    """What kind of object the copy is.

    Separate from everything else because "do we own this" has a different
    answer per format: a library can hold the audiobook and not the paperback,
    and a reader looking for something to take on a train cares which. Reviews
    of every competitor in this space ask for it by name, usually as "where is
    audiobook".

    OTHER exists so the list can stay short. A boxed set, a magazine or a
    pamphlet is a real thing on a real shelf and does not need its own value.

    **What a sixth value has to have is a file container of its own**, and that
    is a harder test than how common the thing is or than what an importer's
    vocabulary can be taught: a table of spellings is one line to extend, and a
    container has to exist in the world. COMIC has `.cbz`, which is written for
    comics and for nothing else, so a comic files itself. A magazine has no such
    container, so a MAGAZINE member could only ever be typed, and a value only a
    person can distinguish is what OTHER already holds.

    **HARDCOVER, PAPERBACK, EBOOK and AUDIOBOOK predate that test**, and they
    are the axis this enum was made for: what a copy physically is. Nothing here
    is arguing they would pass it.

    COMIC is the umbrella over a single issue and a collected volume, and it
    does not separate them, because the metadata a comic carries does not
    either. `frontend/src/lib/cbz.ts` states what a file says about which of the
    two it is, and what it does not.
    """

    HARDCOVER = "hardcover"
    PAPERBACK = "paperback"
    EBOOK = "ebook"
    AUDIOBOOK = "audiobook"
    COMIC = "comic"
    OTHER = "other"


class BookCondition(StrEnum):
    """The state of this particular copy.

    A deliberately coarse scale. Collectors use finer ones (near fine, very
    good plus) and nobody else can apply them consistently, so a library
    would end up with five spellings of "a bit battered".

    EX_LIBRARY is not a point on the scale: it is a fact about provenance that
    changes what a copy is worth and what it looks like, and it is the one
    category people actually recognise.
    """

    NEW = "new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    EX_LIBRARY = "ex_library"


class LendingWillingness(StrEnum):
    """Whether the library is prepared to lend this copy out.

    **Not the same question as a loan, and not the same as `ownership`.** A
    loan is a fact about right now, `ownership` is a fact about the shelf, and
    this is a standing intention that survives both: a book can be marked
    happy to lend while it is out, and a book nobody will ever lend is still
    owned. Storing it on the loan instead would mean the answer only existed
    while the book was somewhere else.

    IN_USE is the one that would otherwise be missing, and it is the reason
    this is three values rather than a boolean. "Ask me later" is a real
    answer, distinct from "no": the copy is spoken for at the moment and the
    person asking should come back, which a yes/no field cannot say.

    NEVER is a rule, not a state. It is what a signed first edition or a copy
    somebody was given gets, and nothing about the shelf can change it.

    Nullable on the column rather than defaulted to HAPPY: an unanswered
    question is not an answer, and a guess written into every imported book at
    once is worse than a blank, because nobody re-checks a field that looks
    filled in. Same reasoning as `BookFormat`.
    """

    #: Wanted by its owner at the moment. Not a refusal.
    IN_USE = "in_use"
    #: Not lent, as a matter of principle.
    NEVER = "never"
    #: Offered freely.
    HAPPY = "happy"


class TagCategory(StrEnum):
    """The groups tags are presented in throughout the UI.

    The first three are the curated vocabulary, seeded at boot and the same in
    every deployment. CUSTOM is everything a library invents for itself.

    Keeping them apart, rather than making every tag free-form as Jelu and
    Openreads do, is deliberate: the curated list is what makes the tag picker
    useful on the first day, before anybody has typed anything. What was wrong
    was having no way past it.
    """

    TYPE = "type"
    GENRE = "genre"
    AGE = "age"
    CUSTOM = "custom"


class TagKey(StrEnum):
    """The stable identity of a seeded tag, independent of what it is called.

    A predefined tag is shown in the member's language, and the row a
    translation belongs to is found through this, never by matching the name.
    Matching the name is the bug migration `95b6a61d6668` exists to fix,
    repeated at display time: it breaks the moment a household renames a tag.

    Only seeded rows carry one. `tags.key` is nullable and a tag the library
    invented has none, so it is shown as typed, and so is a seeded row somebody
    has renamed: the migration sets a key only where the name still matches the
    English seed name exactly, and a row without one has stopped tracking the
    curated vocabulary.

    **A member is exactly the value of the key**, not derived from the name.
    The English name can be corrected without every German library's tags
    silently changing which translation they get.

    Declared as an enum rather than left a plain string for one downstream
    reason: FastAPI emits it into the OpenAPI schema, Orval generates a union
    from it, and `frontend/src/i18n/tagNames.ts` types its German table as
    `Record<TagKey, string>`. A tag added to `PREDEFINED_TAGS` with no German
    name is then a failed frontend build rather than an English word in a
    German picker, which is the property `de.ts` has and the reason it is typed
    against `en.ts`.

    Every member appears in `PREDEFINED_TAGS` exactly once and every entry
    there names one of these:
    `tests/test_main.py::TestTheSeededVocabularyIsKeyed` pins both directions.
    """

    FICTION = "fiction"
    NON_FICTION = "non_fiction"
    REFERENCE = "reference"
    TEXTBOOK = "textbook"
    ANTHOLOGY = "anthology"
    COMICS = "comics"
    MANGA = "manga"
    PLAY = "play"
    ESSAYS = "essays"
    PICTURE_BOOK = "picture_book"
    ADVENTURE = "adventure"
    CLASSIC = "classic"
    CONTEMPORARY_FICTION = "contemporary_fiction"
    CRIME = "crime"
    DETECTIVE = "detective"
    DYSTOPIAN = "dystopian"
    EPIC_FANTASY = "epic_fantasy"
    FAIRY_TALES = "fairy_tales"
    FANTASY = "fantasy"
    FOLKLORE = "folklore"
    GOTHIC = "gothic"
    GRAPHIC_NOVEL = "graphic_novel"
    HISTORICAL_FICTION = "historical_fiction"
    HORROR = "horror"
    HUMOUR = "humour"
    LITERARY_FICTION = "literary_fiction"
    MAGICAL_REALISM = "magical_realism"
    MYSTERY = "mystery"
    MYTHOLOGY = "mythology"
    NOIR = "noir"
    PARANORMAL = "paranormal"
    POETRY = "poetry"
    POST_APOCALYPTIC = "post_apocalyptic"
    ROMANCE = "romance"
    SATIRE = "satire"
    SCIENCE_FICTION = "science_fiction"
    SHORT_STORIES = "short_stories"
    SPACE_OPERA = "space_opera"
    SPECULATIVE_FICTION = "speculative_fiction"
    SPY_FICTION = "spy_fiction"
    STEAMPUNK = "steampunk"
    SUSPENSE = "suspense"
    THRILLER = "thriller"
    URBAN_FANTASY = "urban_fantasy"
    WAR = "war"
    WESTERN = "western"
    ANTHROPOLOGY = "anthropology"
    ARCHAEOLOGY = "archaeology"
    ARCHITECTURE = "architecture"
    ART = "art"
    ASTRONOMY = "astronomy"
    AUTOBIOGRAPHY = "autobiography"
    BIOGRAPHY = "biography"
    BIOLOGY = "biology"
    BUSINESS = "business"
    CHEMISTRY = "chemistry"
    COMPUTING = "computing"
    COOKING = "cooking"
    DESIGN = "design"
    DIARIES_AND_LETTERS = "diaries_and_letters"
    ECONOMICS = "economics"
    EDUCATION = "education"
    ENVIRONMENT = "environment"
    ETHICS = "ethics"
    FEMINISM = "feminism"
    FILM_AND_TV = "film_and_tv"
    FINANCE = "finance"
    GARDENING = "gardening"
    GEOGRAPHY = "geography"
    HEALTH_AND_FITNESS = "health_and_fitness"
    HISTORY = "history"
    JOURNALISM = "journalism"
    LANGUAGE = "language"
    LAW = "law"
    LINGUISTICS = "linguistics"
    MATHEMATICS = "mathematics"
    MEDICINE = "medicine"
    MEMOIR = "memoir"
    MUSIC = "music"
    NATURE = "nature"
    PARENTING = "parenting"
    PHILOSOPHY = "philosophy"
    PHOTOGRAPHY = "photography"
    PHYSICS = "physics"
    POLITICS = "politics"
    POPULAR_SCIENCE = "popular_science"
    PSYCHOLOGY = "psychology"
    RELIGION = "religion"
    SCIENCE = "science"
    SELF_HELP = "self_help"
    SOCIOLOGY = "sociology"
    SPORTS = "sports"
    TECHNOLOGY = "technology"
    THEATRE = "theatre"
    TRAVEL = "travel"
    TRUE_CRIME = "true_crime"
    URBANISM = "urbanism"
    WINE_AND_DRINK = "wine_and_drink"
    BABY_AND_TODDLER = "baby_and_toddler"
    CHILDREN = "children"
    EARLY_READER = "early_reader"
    MIDDLE_GRADE = "middle_grade"
    YOUNG_ADULT = "young_adult"
    NEW_ADULT = "new_adult"
    ADULT = "adult"


class ClassificationScheme(StrEnum):
    """Published schemes a `classifications` row may quote.

    A closed set rather than free text, because the scheme is what makes the
    number mean anything: `004` is computing in Dewey and nothing at all in
    Library of Congress notation. A row whose scheme nobody recognises is a
    number with no reading.

    All four are produced today. DDC comes from the DNB and K10plus (MARC
    082) and from the Library of Congress (`classification authority="ddc"`);
    LCC comes from the Library of Congress alone (`authority="lcc"`); GND comes
    from the DNB's subject fields, 650, 651, 655, 689 and 600; LCSH comes from
    the same Library of Congress record as the other two, `<subject
    authority="lcsh">` beside the `<classification>` elements.

    **GND is an authority file rather than a shelf order, and it still belongs
    here.** What the column called `number` holds is the scheme's own identifier
    for a heading, which is the half that does not change while the caption
    does. For Dewey that was measured: `004` is Informatik in a German record
    and Computing in an English one. For GND it is a property of the identifier
    rather than something this app will see, the DNB being its only supplier
    here and German its only caption: `4203576-4` names one heading whatever a
    record calls it. What differs is that a Dewey number also sorts, and a GND
    number does not. That is now a visible difference rather than a latent one:
    `BookSort.DDC` and `BookSort.LCC` order a shelf by the two schemes that
    place a book on one, each under its own rule in `filing.py`, and there is
    deliberately no counterpart for GND or LCSH because a subject vocabulary
    has no order to offer.

    **LCSH is the one member with no identifier at all, and that is measured
    rather than assumed.** MODS from `lx2.loc.gov` carries no `valueURI` on a
    single `<subject>` element across 900 live records (2026-08-24), so the
    only access point the record supplies is the authorised heading string.
    `number` holds that string and `label` is absent, because storing the same
    words in both columns would state one fact twice. The consequence is
    honest and worth knowing: a heading the Library of Congress later revises
    (`Afro-Americans` became `African Americans`) changes this scheme's
    identifier, where a GND number or a Dewey notation survives its own
    recaptioning. That is why LCSH sorts last in `classifications.SCHEME_ORDER`.

    **A person's identifier is not one of these**, though the DNB writes it in
    the same `$0`: `100 $0` says who wrote the book, and every scheme here says
    what the book is about. Those go to `AuthorityScheme` and the
    `author_identifiers` table, which is a different store keyed on a name
    rather than on a book.

    **`gnd-content` and `gnd-carrier` are not two more members**, though they
    are `$2` codes beside `gnd` and were nearly added here. They fail this
    enum's own test: a scheme is what gives a number a reading, and those codes
    give `(DE-588)4113937-9` the same reading `gnd` does, in the same file, at
    the same address. What they say is what the record was asserting with it,
    which is `HeadingKind` and a separate column. Storing them here would also
    change the key `uq_classifications_book_scheme_number` is on, so the next
    enrichment of a book that already carries one would deposit the concept a
    second time rather than finding the row it has.

    Only DDC is projected onto a tag: see `ddc.DIVISION_TAGS`. All four are read
    now: a book shows the headings it carries, and any of them can be filtered
    on. What DDC has that the others do not is a second reading, the division,
    which is what makes it browsable as well as filterable. **Sortable is no
    longer one of the things it has alone**: every scheme names a filing rule
    in `filing.py`, and LCC's orders a shelf too.
    """

    DDC = "ddc"
    LCC = "lcc"
    GND = "gnd"
    LCSH = "lcsh"


class HeadingKind(StrEnum):
    """What a record was asserting when it cited a heading, where it said.

    **A different question from the scheme, and that is the whole reason this
    exists.** `ClassificationScheme` names the file an identifier is in, which
    is what makes the number resolvable: `004` is computing in Dewey and
    nothing at all in Library of Congress notation. This names what the citing
    record was doing with it. `(DE-588)4139307-7` is one GND record whether a
    catalogue writes it under `$2 gnd` or under `$2 gnd-carrier`, so the code
    cannot be a scheme without making that column carry two questions at once.

    The distinction is not cosmetic. The DNB writes CD-ROM into a subject field
    with a GND number on it, so before this existed a disc was stored as a
    heading about what the book is about, filtered beside Samoainseln and
    counted in the same facet list.

    **Three members, and only two of them are ever a surprise.** A subject is
    the ordinary case and everything without a declaration is one.

    **Null on the row is not a fourth member**, it is the record never having
    said, which is true of every row written before this and of every scheme
    but GND today: MARC 082 declares no vocabulary and neither does a MODS
    `<subject authority="lcsh">`. `classifications.kind_of` is the one place
    that reads a null as a subject, so the fallback is stated once.

    **This is the whole argument for the shape, and the other sites point here
    rather than restating it.** Keeping the null rather than defaulting the
    column is what lets `add_headings` fill one in later from a record that does
    declare, exactly as it fills in a missing caption. A column defaulted to
    `subject` cannot tell a stored guess from a stored assertion, so the
    mis-filed rows this was built for would never heal; and `subject` sorts
    after both other words, so one such row would also win
    `shelf._heading_counts`'s `max` and make a shared heading stop reading as a
    carrier for every book carrying it. Both were reachable through
    `POST /api/books` before `ck_classifications_kind` and the validator on
    `ClassificationIn` closed them.
    """

    #: What the book is about. Every Dewey number, every call number, every
    #: LCSH string, and every GND heading a record does not mark as one of the
    #: two below.
    #:
    #: **Never written to the column, and that is enforced twice rather than
    #: agreed.** `ck_classifications_kind` permits `content`, `carrier` and the
    #: null only, and `ClassificationIn.a_subject_is_the_absence_of_a_kind`
    #: turns a client's `subject` into the null it means before it gets there.
    #: This member is what `classifications.kind_of` **answers** for a null, not
    #: a value the store holds.
    SUBJECT = "subject"
    #: What kind of text it is: `$2 gnd-content`, which is where
    #: `Fiktionale Darstellung`, `Hochschulschrift` and `Kochbuch` arrive.
    CONTENT = "content"
    #: What physical thing it is: `$2 gnd-carrier`, which is CD-ROM.
    CARRIER = "carrier"


class BookIdentifierScheme(StrEnum):
    """Who is naming a Book, where that name is not an ISBN.

    **Not `books.isbn`, and this enum is what keeps them apart.** That column is
    the importer's match key and the lookup key, and every path into it check
    digits its input. An ASIN is ten characters beginning `B` and passes no such
    test, so a row carrying one in that column matches nothing and takes the
    dedupe surface down with it for the rows that do. See `docs/decisions.md`.

    **A member here has to be a value some reader can produce**, which is
    `AuthorityScheme`'s rule and its reason: a scheme nothing reads an
    identifier out of is a row that lies. Both below are produced today, in the
    browser, by the two store readers that measured an identifier and no ISBN.

    **Not `books.google_books_id`, though `GOOGLE_BOOKS` names the same
    catalogue.** That column records which Google volume this row's *metadata*
    was taken from, and `google_books.merge_into` is the only writer that takes
    one from a catalogue: `overwrite=True` there retypes it. (Two others carry a
    value the library already holds, `_absorb_fields` on a merge and the copy
    route through `_WORK_FIELDS`, and `backup.restore` reinstates one. None of
    them is a fresh assertion, which is why the claim is about the catalogue
    rather than about the count.) A row here records which volume a member's own
    export said they **own**, which is a fact rather than a preference, and
    `models.AuthorIdentifier` already states that asymmetry for a person's
    name. Writing the store's assertion into the enrichment column would also
    pre-empt enrichment, because `merge_into` skips a field that is already
    set, so a Play Books import would stop Google recording its own volume.
    """

    #: Amazon's own number for an edition, off the Kindle for PC catalogue.
    #: 1,032 of 1,032 entries carry one and none carries an ISBN, measured over
    #: two published captures by the trio that wrote `frontend/src/lib/kindle.ts`.
    ASIN = "asin"
    #: A Google Books volume id, off a Play Books Takeout sidecar. Twelve
    #: characters of the URL safe alphabet, 24 of 24 measured, and the only
    #: identifier that archive carries: `frontend/src/lib/takeout.ts` says the
    #: EPUB identifiers beside it are UUIDs and Project Gutenberg URLs.
    GOOGLE_BOOKS = "google_books"


class AuthorityScheme(StrEnum):
    """Authority files a person's identifier may come from.

    **A member here has to be a value some writer can produce.** A scheme nothing
    can read an identifier out of is a row that lies, which is why this is an enum
    rather than a table: adding one requires a reader.

    The roster, what each file is for and why the GND is the entry point are in
    `docs/decisions.md`.
    """

    GND = "gnd"
    ISNI = "isni"
    LCNAF = "lcnaf"
    VIAF = "viaf"
    WIKIDATA = "wikidata"
    #: Biblioteca Nacional do Brasil.
    BLBNB = "blbnb"
    #: Biblioteca Nacional de la Republica Argentina.
    ARBABN = "arbabn"
    #: Biblioteca Nacional de Espana.
    BNE = "bne"
    #: Biblioteca Nacional de Portugal.
    PTBNP = "ptbnp"
    #: Istituto Centrale per il Catalogo Unico, Italy.
    ICCU = "iccu"
    #: Biblioteca Nacional de Chile.
    BNCHL = "bnchl"


class AuthorityProvenance(StrEnum):
    """Who said an author's identifier is that author's.

    **Explicit on both sides, because a null would only be implicit.**
    `author_aliases.created_by_user_id` is nullable and a null there could mean
    a catalogue said so or that the member who said so has since been deleted.
    That ambiguity is affordable for a display name and is not affordable here:
    the question this column exists to answer is whether a curated list has
    quietly become a generated one, and it has to be answerable by reading one
    value rather than by inferring from the absence of another.

    A `CATALOGUE` row never names a person, and `ck_author_identifiers_asserter`
    enforces it. **The other direction is deliberately left unconstrained**, so
    that a `MEMBER` row whose author is gone still reads `member` rather than
    becoming indistinguishable from a machine's. That is slack for a change not
    yet made rather than a live case: no path deletes an account today, counted
    2026-08-27 over `backend/routers/` and `backend/*.py`, so the column is
    never nulled and never dangles.
    """

    #: A record the server itself fetched for this book's own ISBN asserted it.
    CATALOGUE = "catalogue"
    #: A member confirmed a candidate that arrived from a search rather than
    #: from this book's record.
    MEMBER = "member"


class ExportFormat(StrEnum):
    """What `GET /api/books/export` may write.

    Two of these are for a person and one is for another institution, and the
    difference decides who may ask for it. CSV and plain text carry a
    household's own columns (what a book cost, which room it is in, who added
    it) and go to a spreadsheet. MARCXML carries the catalogue record and goes
    to another library's system, so it is offered only in library mode: see
    `routers/books.export_books`.
    """

    CSV = "csv"
    TXT = "txt"
    #: MARC21 in XML, and deliberately not ISO 2709. The binary serialisation
    #: needs a directory of byte offsets that has to agree with the field data
    #: after every change, and every system that reads it reads this too.
    MARCXML = "marcxml"


class BookSort(StrEnum):
    """Accepted values for `GET /api/books?sort=`.

    TITLE_ASC is the default and is spelled out rather than left implicit, so
    the client can round-trip the current sort without a special empty case.
    """

    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"
    AUTHOR = "author"
    YEAR_ASC = "year_asc"
    YEAR_DESC = "year_desc"
    NEWEST = "newest"
    # Series order, for reading a shelf in the order it was written. Books with
    # no series sort last: mixing them in by a NULL index would scatter them
    # through the list rather than grouping them at the end.
    SERIES = "series"
    # Shelf order, one value per scheme that files a shelf, with the
    # unclassified last for the reason SERIES puts the un-serialised last.
    #
    # **Named for the scheme rather than for "classification", because a
    # scheme is what decides how its numbers sort.** `filing.py` holds one
    # rule per scheme and `shelf._SHELF_SORTS` pairs each of these with one.
    #
    # A DDC notation always carries exactly three leading digits
    # (`ddc._NOTATION` refuses anything else), so ordering the text orders the
    # numbers: `004` then `155.9042` then `830`. A Library of Congress call
    # number does not have that property. Its class letters are followed by a
    # number that sorts numerically, so `BF75` precedes `BF575` on a real
    # shelf and text order reverses them, measured against the live row
    # `BF575.S75 E64 2022` on 2026-08-29. That is why the two have different
    # filing rules and not why one of them has none: `filing.LccFiling` pads
    # the class number so text order reproduces the shelf.
    #
    # GND and LCSH get no value here. They are subject vocabularies with no
    # order at all, they file under `filing.GENERIC`, and that rule declares
    # `orders_a_shelf = False` so no listing can be ordered by one.
    DDC = "ddc"
    LCC = "lcc"


class AppEnv(StrEnum):
    """Deployment posture. `DEV` relaxes the startup secret check, nothing else."""

    DEV = "dev"
    PROD = "prod"


class AuthMode(StrEnum):
    """How members are authenticated.

    LOCAL   accounts and bcrypt hashes in this database (the default).
    LDAP    credentials are checked against a directory; no local signup.
    PROXY   an upstream (Authelia, oauth2-proxy, ...) has already authenticated
            the request and asserts who it is in a header. No login screen.
    """

    LOCAL = "local"
    LDAP = "ldap"
    PROXY = "proxy"


class SettingKey(StrEnum):
    """Keys in the runtime settings table.

    These are settings an admin changes from the UI and that must survive a
    restart. Anything an operator sets when deploying stays an environment
    variable instead: a container that behaves differently depending on
    database contents is much harder to reason about.
    """

    GOOGLE_BOOKS_API_KEY = "google_books_api_key"
    GOOGLE_BOOKS_ENABLED = "google_books_enabled"
    GOODREADS_LOOKUP_ENABLED = "goodreads_lookup_enabled"
    DEFAULT_LOCALE = "default_locale"
    TOKEN_EPOCH = "token_epoch"

    # Where overdue reminders go, and how often. Settings rather than
    # environment variables because the library changes them: which channel
    # gets chased, and how much nagging it tolerates, are decisions made after
    # the container is running.
    OVERDUE_WEBHOOK_ENABLED = "overdue_webhook_enabled"
    OVERDUE_WEBHOOK_URL = "overdue_webhook_url"
    OVERDUE_WEBHOOK_SECRET = "overdue_webhook_secret"
    OVERDUE_REMINDER_DAYS = "overdue_reminder_days"

    # Mail. The seven names match the standard `MAIL_*` environment variables a
    # deployment already carries, lowercased, so an operator setting
    # `MAIL_SERVER` and an admin filling in the same field are naming one fact.
    # The eighth standard name, `MAIL_DEBUG`, is deliberately absent: smtplib's
    # debug output writes the AUTH exchange to stderr, so a toggle for it is a
    # switch that puts the mail password in the container log.
    OVERDUE_MAIL_ENABLED = "overdue_mail_enabled"
    OVERDUE_MAIL_TO = "overdue_mail_to"
    MAIL_SERVER = "mail_server"
    MAIL_PORT = "mail_port"
    MAIL_USERNAME = "mail_username"
    MAIL_PASSWORD = "mail_password"
    MAIL_USE_TLS = "mail_use_tls"
    MAIL_USE_SSL = "mail_use_ssl"
    MAIL_DEFAULT_SENDER = "mail_default_sender"

    # Telegram. No host key, and that absence is the control: see
    # `notifications.TELEGRAM_API` for why making it configurable would give
    # away the one property this sender has that the webhook does not.
    OVERDUE_TELEGRAM_ENABLED = "overdue_telegram_enabled"
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"
    TELEGRAM_CHAT_ID = "telegram_chat_id"

    # The in app notice. One toggle and nothing else: the channel is the app,
    # so there is no destination to store and no credential to hold, which is
    # the entire argument for its existence.
    OVERDUE_IN_APP_ENABLED = "overdue_in_app_enabled"

    # Library mode and the public catalogue. Two switches, nested, never one:
    # library mode changes what a **cataloguer** sees and publishes nothing,
    # and a library running it internally without publishing is the common
    # case. One switch would force an institution to put its catalogue on the
    # internet to get the cataloguer's column set.
    #
    # Nesting them also gives "hard to trip by accident" a structural meaning
    # rather than a UI one: publishing takes two deliberate acts, and the
    # second says only that. `settings_store.public_catalogue_is_published` is
    # the single answer to whether anything is actually served, and it reads
    # both rows, so flipping library mode off cannot leave a catalogue public.
    #
    # Settings rather than environment variables, deliberately: an environment
    # variable takes a redeploy to correct, which is the wrong property for the
    # switch most likely to be turned on by mistake. None of the three is in
    # `config._ENV_OVERRIDES`, and
    # `TestLibraryModeAndThePublicCatalogue` in `tests/test_settings_store.py`
    # keeps it that way, in its `not_pinnable_from_the_environment` case.
    LIBRARY_MODE = "library_mode"
    PUBLIC_CATALOGUE_ENABLED = "public_catalogue_enabled"
    # Publishing a catalogue and inviting a search engine to crawl it are
    # different decisions, so the second is its own row. Off by default, which
    # is what makes the public routes send `X-Robots-Tag: noindex`.
    PUBLIC_CATALOGUE_INDEXING_ENABLED = "public_catalogue_indexing_enabled"

    # The last outcome of each reminder sender, as one JSON object keyed by
    # sender. A settings row rather than a table because a table would need a
    # migration, a retention rule and a `backup._TABLES` entry, and this holds
    # one record per sender rather than a history. `settings` is already in
    # `backup._TABLES`, so the record survives a restore with everything else.
    #
    # Written by `notifications.record_run`, read by `notifications.health`.
    # Never edited from the settings screen: it is a measurement, not a
    # preference, which is why it has no field in `SettingsUpdate`.
    SENDER_HEALTH = "sender_health"

    # The provider list: which catalogues are asked, and in what order. One
    # JSON object rather than a row per source, for the reason SENDER_HEALTH is
    # one: a table would need a migration, a `backup._TABLES` entry and a
    # restore path to hold seven booleans and an order.
    #
    # **Never read directly.** `sources.parse` turns whatever the row holds
    # into a full roster, so a hand edit or a restore cannot produce a name
    # `targets.SEEDED` has no entry for. See `settings_store.catalogue_sources`.
    CATALOGUE_SOURCES = "catalogue_sources"

    # Whether accounts here are held by people outside the household.
    #
    # **Its own row, deliberately, and derived from nothing.** It draws a line
    # the codebase did not draw: the auth mode says where credentials are
    # checked, library mode says how the catalogue is presented, and the public
    # catalogue switch is about readers rather than accounts. A verification
    # requirement hung on any of those would be found by somebody turning that
    # thing on for its own reason, which is the worst way to discover an account
    # policy. Owner's decision, 2026-09-06, recorded in `docs/decisions.md`.
    #
    # Gating on whether registration is open was refused separately and it is
    # the near miss: closing signups would silently admit every account that
    # registered while it was open and never verified.
    #
    # A setting rather than an environment variable, like the two switches
    # above and for the same reason: an account policy turned on by mistake has
    # to be correctable without a redeploy.
    ACCOUNTS_OPEN_TO_OUTSIDERS = "accounts_open_to_outsiders"


class OverdueSender(StrEnum):
    """Which channel a reminder went out on.

    A closed set because the result reports one outcome per sender and the
    client renders each: a string would let a new sender arrive on screen with
    no label and no test noticing.
    """

    #: The app itself. Listed first because it is the one channel that needs
    #: nothing from the household: no receiver, no mailbox, no bot token.
    #:
    #: **It does not push, and `notifications.pushes_outward` is where that is
    #: decided.** Nothing is handed to anything: the notice is read from
    #: `GET /api/loans/overdue/mine` by the member it concerns. That is why it
    #: is the one sender whose audience has a viewer, and so the one that can
    #: carry a member's own private books without disclosing them.
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    EMAIL = "email"
    TELEGRAM = "telegram"


class OverdueNotifyReason(StrEnum):
    """Why the overdue digest sent nothing.

    A closed set rather than the prose in `detail`, because the client has to
    *render* the difference and a sentence is not something it can branch on.
    Without it a broken webhook and a quiet week were the same string on the
    screen, which is the exact confusion the "send now" button exists to clear
    up.

    `detail` stays beside it, and the two are not the same thing: this is what
    happened, in a form code can test; that is a sentence for a log or an API
    caller with no message catalogue of its own.
    """

    #: The toggle is off.
    DISABLED = "disabled"
    #: No webhook address is stored, or the stored one is not http(s).
    NO_URL = "no_url"
    #: Nothing is overdue, or everything overdue was chased recently enough.
    NOTHING_DUE = "nothing_due"
    #: The request was made and failed. The loans are left to be retried.
    UNREACHABLE = "unreachable"
    #: The sender is switched on and its configuration cannot be used. Distinct
    #: from `NO_URL`, which is the webhook's own empty-destination case: this
    #: one covers a mail server with no host, credentials that would cross the
    #: wire in the clear, and a Telegram chat id that is not a chat id. A
    #: refusal an operator can act on reads differently from a receiver that
    #: was tried and did not answer.
    MISCONFIGURED = "misconfigured"
    #: The in app notice is the only channel switched on, so nothing was sent
    #: anywhere and nothing was meant to be. Distinct from `DISABLED`, which
    #: says reminders are off: here they are on and every member reads them in
    #: the app. It is also the reason `notified_at` is not stamped on such a
    #: run, because no reminder went out to be stamped for.
    IN_APP_ONLY = "in_app_only"


class Locale(StrEnum):
    EN = "en"
    DE = "de"


class ThemeMode(StrEnum):
    """Light, dark, or whatever the reader's operating system is asking for.

    A closed set, so the server owns it: unlike the palette and the wallpaper,
    which are a stylesheet and a drawing routine the frontend can add to
    without redeploying anything here, these three are the only answers there
    will ever be.
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class BulkAction(StrEnum):
    """What a bulk selection does to the books in it.

    One endpoint per verb would be four near-identical handlers sharing the
    same permission walk and the same three-way result. The verb is a field
    instead.
    """

    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    SET_STATUS = "set_status"
    SET_OWNERSHIP = "set_ownership"
    SET_LOCATION = "set_location"
    # File a selection into a collection, or out of one: an empty value clears
    # it, the same way SET_LOCATION's empty string unpacks a box.
    SET_COLLECTION = "set_collection"
    DELETE = "delete"


class CustomFieldKind(StrEnum):
    """What a Library said one of its own fields holds.

    **Declared per field, never detected from the value**, and the difference
    matters at exactly one place: whether the Book page renders the value as a
    link. Detection reads a member typing prose that happens to start with
    `http` as a URL, and it reads a URL somebody meant as text the same way.
    The Library already has to name the field, so it can say what goes in it.

    TEXT is the default and the safe one: nothing is ever linked from a TEXT
    field, whatever the value looks like.

    URL is a link out to another system, which is the requirement this feature
    exists for: a Book's page in a calibre-web instance. **The declaration is
    not the permission.** `custom_fields.link_target` re-reads the value on
    every serialisation and returns a target only for `http` and `https`, so a
    row that reached the table without passing the write check (a restore, a
    hand edit) is served as text rather than as a link.
    """

    TEXT = "text"
    URL = "url"


class CatalogueSource(StrEnum):
    """A catalogue this build can ask about a book.

    **The values are the strings `metadata.py` already used**, because they are
    not only a settings vocabulary: `catalogue.Record.source` and
    `Record.sources` carry them, `targets.SEEDED` is keyed on them, and
    `metadata._MATCH_PRECEDENCE` names them. Declaring the set changes nothing
    downstream and buys two things: a closed union in the generated client, and
    a roster `sources.parse` can validate a stored row against.

    **Not every source answers every question**, and the split is real rather
    than incidental. BNF and LOC are title search only, because neither was
    worth an ISBN request. NKP, BNE and BNA are the other way round, **lookup
    only**, and for two different reasons. The NKP's and the BNA's is the
    server's: each renders one populated record per response whatever page size
    is asked for, so a search for ten candidates would be ten requests. The
    BNE's is ours: its search works and nobody has measured what it would find,
    so it holds the conservative default. See `sources.LOOKUP_SOURCES` and
    `SEARCH_SOURCES`, which is why those are two sets and not one.

    **One member needs a credential and is free**, which is new: the BNA. What
    that costs the roster's rules is on `sources.NEEDS_A_KEY`.
    """

    OPEN_LIBRARY = "open_library"
    GOOGLE_BOOKS = "google_books"
    DNB = "dnb"
    K10PLUS = "k10plus"
    OENB = "oenb"
    NLG = "nlg"
    NKP = "nkp"
    BNF = "bnf"
    LOC = "loc"
    #: The Biblioteca Nacional de España. Alma SRU on the OPAC hostname, MARC21,
    #: and the ÖNB's profile exactly. #91.
    BNE = "bne"
    #: The Biblioteca Nacional Argentina. The NKP's profile exactly, over the
    #: same bare Dublin Core, and the first source here that is free and
    #: credentialled at once: see `sources.NEEDS_A_KEY`. #116.
    BNA = "bna"


class SourceFamily(StrEnum):
    """Which kind of thing a source is, and there are two of them.

    **The consequence, which is what belongs here.** Each family has its own
    registry, and one registry would let a member's imported library be selected
    as a source answering another member's ISBN scan. `CatalogueSource` is the
    catalogue registry's key space and every door onto the lookup path is keyed
    on it, so the refusal is by construction rather than by a check.
    `targets.FAMILY` names which family that registry is, and
    `tests/test_decoders.py::TestTwoFamiliesMeanTwoRegistries` is the guard.

    **What the two families share is a contract rather than a registry**: one
    output type, `catalogue.Record`; one failure rule, that a bad record fails
    alone and never the batch; and one capability vocabulary, `Capability`.

    Why they are two rather than one, on trust, direction, where they run and
    cardinality, is in `docs/decisions.md`.
    """

    CATALOGUE = "catalogue"
    IMPORT = "import"


class Capability(StrEnum):
    """What a source can be asked for, in one vocabulary across both families.

    **One vocabulary and not one per family**, because a catalogue that answers
    no ISBN and an OPDS server that serves no ISBN are the same statement. A
    member only one family could ever have is a sign the split is being papered
    over rather than a reason to add one.

    **Declared as a set rather than grown one boolean at a time**, which is the
    shape taken from Calibre's metadata `Source`: capabilities are a frozenset
    on the provider there, and have been across a large number of providers for
    years. The test of the shape is that a reader of one row can answer "what is
    this source for" without consulting five other constants, and that a fifth
    member does not mean touching every call site. `targets.Target.capabilities`
    is where a catalogue row answers it.

    **Not a declaration of which fields a source can supply**, and that is a
    deliberate split rather than an omission. Calibre keeps `touched_fields`
    separate from `capabilities` for the same reason: they answer different
    questions. Here the field question is already answered by the output type
    both families share, `catalogue.Record`, whose optional fields are exactly
    "what this record carried"; a second set naming the same thing would be a
    fact stored twice and nothing reads it today.
    """

    #: Answers a lookup by ISBN: one identifier in, at most one record out.
    ANSWERS_ISBN = "answers_isbn"
    #: Answers a search by title terms: several candidates out, ranked here.
    ANSWERS_TITLE_SEARCH = "answers_title_search"
    #: Costs money per request, so asking it about a book something else already
    #: answered is a bill for nothing. See `sources.Plan.lookup_together`.
    METERED = "metered"
    #: Needs a credential the household supplies, so an install without one has
    #: a source in the list that can never answer.
    NEEDS_A_CREDENTIAL = "needs_a_credential"


class VerificationProvenance(StrEnum):
    """Who said this account's address is that person's.

    The same shape as `AuthorityProvenance` and for the same reason: an admin
    marking an account verified is an assertion about a person, and a column
    holding only the assertion cannot afterwards say who made it. Owner's
    decision on issue #104.

    A closed set, so the settings screen and the member list can label each
    without a string arriving on screen with no translation.

    `email_verified_by_user_id` is set on `ADMIN` and on nothing else. That
    pairing is not a check constraint, because adding one to `users` forces a
    batch rewrite of a table that now carries a self referential foreign key;
    `accounts.record_verification` is the one writer and
    `tests/test_accounts.py::TestOnlyAnAdminAssertionNamesAnAdmin` is what keeps
    it true.
    """

    #: Nobody was asked. The account existed before the policy, or was created
    #: while it was off. Every row the migration backfilled reads this.
    NOT_REQUIRED = "not_required"
    #: The member returned a code sent to the address on the account.
    EMAIL = "email"
    #: An admin asserted it from the settings screen. The only value that names
    #: a person.
    ADMIN = "admin"
    #: A directory authenticated the account, so this app was never the one
    #: holding the credential and has nothing of its own to verify.
    DIRECTORY = "directory"


class CredentialProvenance(StrEnum):
    """Which of the four levels supplies a catalogue's login, if any.

    **One field rather than a booleans per level, because the levels are ordered
    and a set of booleans is not.** `credential_from_env` and `has_credential`
    were two of the four answers spelled as two flags, which admits combinations
    the ladder cannot produce and leaves a screen deciding which flag to believe.
    `credentials._resolve` walks the ladder once and this is what it answers.

    **Not a claim that the credential works.** `unreadable` beside it is that,
    and the two are separate axes: a level in force can be in force and broken,
    which is what a pinned variable set to nonsense and a stored login under a
    rotated key both are.
    """

    #: Nothing supplies one. The source cannot authenticate.
    NONE = "none"
    #: The deployment pinned it, `CATALOGUE_CREDENTIAL_<SOURCE>`. Wins over
    #: everything and cannot be edited from a screen.
    ENV = "env"
    #: An admin entered it and it is sealed in `catalogue_credentials`.
    STORED = "stored"
    #: The catalogue publishes its own login and this build carries it. The
    #: bottom of the ladder by construction: see `targets.ShippedCredential`.
    SHIPPED = "shipped"
