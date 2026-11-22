"""Closed value sets shared by the ORM, the schemas and the query parameters.

These are `StrEnum`, so they compare equal to their string value and store as
plain text in SQLite, so existing rows keep working untouched. The point of
declaring them is what happens downstream: FastAPI emits them into the OpenAPI
schema as enumerations, which is what lets the generated TypeScript client have
union types like `"unread" | "reading" | "read"` instead of `string`.
"""

import logging
from enum import StrEnum
from typing import Final, overload

from logvalues import clipped

logger = logging.getLogger("endpaper.enums")


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


class AccessStatus(StrEnum):
    """Where one request for access to a digital copy stands.

    Never stored: `models.AccessRequest` keeps who decided and when, and this
    is read off those columns, so the two cannot disagree.
    """

    PENDING = "pending"
    GRANTED = "granted"
    DECLINED = "declined"


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


class FilingRuleName(StrEnum):
    """Which filing rule a classification scheme's numbers sort under.

    **Closed, and constrained by `ck_classification_schemes_filing`, where the
    scheme beside it is open.** A rule is arithmetic in `filing.py`, so a row
    naming a rule nothing implements would be a row that lies, which is the
    argument `AuthorityScheme` makes about a reader. The names are Koha's.
    """

    #: No rule of its own: the number files as its own text and no shelf is
    #: ordered by it. The column's default.
    GENERIC = "generic"
    DEWEY = "dewey"
    LCC = "lcc"


class ClassificationScheme(StrEnum):
    """The schemes this application's own code reads or writes.

    **A `classifications` row may quote any scheme in the
    `classification_schemes` table, and these four are the rows that table is
    seeded with.** A library on UDC adds a row rather than asking for a code
    change: whether UDC exists is not this project's business. What makes
    these four different is that code names them. A catalogue reader produces
    them (`sources.CLASSIFIES`, held to the decoders by its test), `BookSort`
    orders a shelf by two of them, and the MARC export writes a field for each.
    So `classification_schemes.BUILT_IN` seeds them, and their rows can be
    neither renamed nor deleted nor refiled: a row this code reads changing
    under it would be the failure a closed enum used to make impossible.

    The scheme is still what makes the number mean anything: `004` is
    computing in Dewey and nothing at all in Library of Congress notation. A
    row is the place a library states that reading for a scheme of its own.

    **GND is an authority file rather than a shelf order, and it still belongs
    here.** What the column called `number` holds is the scheme's own identifier
    for a heading, which is the half that does not change while the caption
    does. For Dewey that was measured: `004` is Informatik in a German record
    and Computing in an English one. For GND it is a property of the identifier
    rather than something this app will see, German being its only caption:
    `4203576-4` names one heading whatever a record calls it. What differs is
    that a Dewey number also sorts, and a GND number does not. That is now a
    visible difference rather than a latent one:
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
    recaptioning. That is why LCSH sorts last of these four in
    `classifications.SCHEME_ORDER`.

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
    longer one of the things it has alone**: every scheme row names a filing
    rule, and LCC's orders a shelf too.
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


class HeadingUse(StrEnum):
    """What an authority heading may be used as: MARC 21 authority `008/14` to `16`.

    The suggest field asks with the use of the field it fills, so a field adding
    a subject is never offered a name heading: one would resolve and carry an
    identifier, and still be filed under the wrong kind of thing, which nothing
    downstream can detect. `vocabulary_copy.suggest` applies it.
    """

    #: `008/14`: valid as a main or added entry, a name.
    NAME = "name"
    #: `008/15`: valid as a subject added entry.
    SUBJECT = "subject"
    #: `008/16`: valid as a series added entry.
    SERIES = "series"


class LinkRelationship(StrEnum):
    """What an online link is to the Book that carries it: MARC 856's second indicator.

    **Only the three values the indicator states.** A blank and `8` ("no
    display constant generated") say nothing about the relationship, so they
    are stored as null rather than as a fourth member that would read as a
    fact. Declaration order is compared by `_enum_check`'s guard, so a new
    member is a revision.
    """

    #: `0`: the link is the resource itself, a born digital title.
    RESOURCE = "resource"
    #: `1`: a version of the resource, such as the EPUB of a print edition
    #: catalogued from the print record.
    VERSION = "version"
    #: `2`: a related resource, such as a table of contents or a review.
    RELATED = "related"


class BookIdentifierScheme(StrEnum):
    """Who is naming a Book, where that name is not an ISBN.

    **Not `books.isbn`, and this enum is what keeps them apart.** That column is
    the importer's match key and the lookup key, and every path into it check
    digits its input. Most ASINs are ten characters beginning `B` and pass no
    such test, so a row carrying one in that column matches nothing and takes
    the dedupe surface down with it for the rows that do.

    **The exception is why a token goes here even when it would pass.** For a
    printed edition Amazon reuses the ISBN-10 as the ASIN, and that does check
    digit: measured on the scan path, 4 of 8 `ASIN`/`AMAZON` values are one.
    Such a value is two facts, the number the book carries and the name Amazon
    files it under, so `books.isbn` takes the canonical ISBN-13 and the row here
    keeps the token as issued. An earlier version of this paragraph said an ASIN
    passes no check digit test at all, which was the weaker claim read as the
    stronger one. See `docs/decisions.md`.

    **A member here has to be a value some reader can produce**, which is
    `AuthorityScheme`'s rule and its reason: a scheme nothing reads an
    identifier out of is a row that lies. All three below are produced today,
    in the browser: the first two by the two store readers that measured an
    identifier and no ISBN, which a Calibre library's own `identifiers` table
    also reaches through `frontend/src/lib/calibre.identifiersWithScheme`, and
    the third by the Calibre reader alone.

    **`goodreads` is the member that rule has refused**, and a Calibre library
    carries the type: nothing here produces the value. `csv_import.py` reads a
    Goodreads export and names no `Book Id` column, and `lib/goodreads.ts` is a
    search link built from a title and an author. `doi`, `issn`, `oclc` and
    `arxiv` are refused for the same reason and would have a second one, being
    a record in a bibliographic file rather than what a store calls an edition.

    **Not `books.google_books_id`, though `GOOGLE_BOOKS` names the same
    catalogue.** That column records which Google volume this row's *metadata*
    was taken from, and `evidence` is the only module that writes one from a
    catalogue: `Policy.OVERWRITE` there retypes it. (Two others carry a
    value the library already holds, `_absorb_fields` on a merge and the copy
    route through `_WORK_FIELDS`, and `backup.restore` reinstates one. None of
    them is a fresh assertion, which is why the claim is about the catalogue
    rather than about the count.) A row here records which volume a member's own
    export said they **own**, which is a fact rather than a preference, and
    `models.AuthorIdentifier` already states that asymmetry for a person's
    name. Writing the store's assertion into the enrichment column would also
    pre-empt enrichment, because `evidence` fills only a field that is not already
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
    #: Calibre's own permanent key for one record, `books.uuid` in a library's
    #: `metadata.db`, read by `frontend/src/lib/calibre.ts`. **Not a store's
    #: name for an edition but the one key a Calibre record keeps for life**,
    #: so it is what recognises a record with no file and no ISBN when the
    #: library is imported again: an add carrying one is refused where a
    #: visible Book carries it (`recognition.Source.CALIBRE`). An internal
    #: key, so no export carries it.
    #:
    #: **Named for the value and not `calibre`**, because the file readers say
    #: Calibre in their own code, `opf.ts` reading `calibre:series`, and
    #: `frontend/tests/lib/fileReaders.test.ts` refuses any module a reader
    #: reaches that spells a stored scheme.
    CALIBRE_UUID = "calibre_uuid"


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
    #: Open Researcher and Contributor ID: a researcher's own registration
    #: rather than a national file.
    ORCID = "orcid"


# **The inference the docstring sets aside is not available anyway**, and this
# is a comment for the reason `BookFormat`'s own comment gives: a docstring here
# is copied into `frontend/openapi.json`, so a maintenance note in one moves a
# committed document for no reader's benefit. `created_by_user_id` is provenance
# on both tables named below: no query may consult it and no schema may declare
# a field named for it, which `models.py` states at each column and
# `tests/test_house_rules.py::TestProvenanceColumnsAreNeverRead` enforces with
# one instrument per half. So this value is the only route to the question
# rather than the cheaper of two.
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


# **Beside `AuthorityProvenance`, not instead of it**, and the two answer
# different questions about one row. Provenance says who tied the number to
# this author: a record fetched for this book, or a person. This says which
# file the number itself came from and which other file named it too. A cross
# reference is `member` by provenance, because a person confirmed the record,
# and `lobid` or `viaf` by supplier, because that file carried the number.
# `ck_author_identifiers_supplier` couples them where they overlap: a
# `catalogue` row is supplied by the catalogue and by nothing else.
class AuthoritySupplier(StrEnum):
    """Which file supplied an author identifier, or checked it.

    `asserted_by` names the file the value came from and `checked_by` a
    second file that tied the same value to the same person, or null where
    none did: for a cross reference, a file whose own record carries the
    value; for a member's GND number, lobid, where its record for that number
    names the author. A reader can tell a number two files agree on from one
    that a single file carried, which looked identical before either was
    recorded.

    `unrecorded` is a row stored before the supplier was recorded. It is never
    a guess: the same scheme under the same provenance arrived by more than
    one route, so the row cannot say which.
    """

    #: The catalogue record fetched for this book's own ISBN.
    CATALOGUE = "catalogue"
    #: A member's request named the value.
    MEMBER = "member"
    #: The GND, read through lobid.
    LOBID = "lobid"
    WIKIDATA = "wikidata"
    VIAF = "viaf"
    #: The Library of Congress name authority file.
    LOC = "loc"
    ORCID = "orcid"
    #: The Biblioteca Nacional de Portugal.
    BNP = "bnp"
    #: Stored before the supplier was recorded.
    UNRECORDED = "unrecorded"


class ExportFormat(StrEnum):
    """What `GET /api/books/export` may write.

    Three of these are for a person and one is for another institution, and the
    difference decides who may ask for it. CSV carries a household's own
    columns (what a book cost, which room it is in, who added it) and goes to a
    spreadsheet; plain text carries fewer and goes to an editor. HTML is a page
    a person opens offline or hands to somebody, with the narrower set of
    columns `routers/books._html_chunks` names. MARCXML carries the catalogue record and goes
    to another library's system, so it is offered only in library mode: see
    `routers/books.export_books`.
    """

    CSV = "csv"
    TXT = "txt"
    #: One self contained page: inline CSS, no script, nothing fetched. Every
    #: value is escaped, because titles arrive from outside catalogues.
    HTML = "html"
    #: MARC21 in XML, and deliberately not ISO 2709. The binary serialisation
    #: needs a directory of byte offsets that has to agree with the field data
    #: after every change, and every system that reads it reads this too.
    MARCXML = "marcxml"


#: What each export format is sent as, and the **only** home for these strings.
#:
#: Read twice and that is the whole reason it exists: `routers/books.export_books`
#: puts one of them on the `StreamingResponse`, and the same route's `responses`
#: declares all of them so the published schema says what the route sends rather
#: than `application/json`. A literal at each site is one promise and one delivery
#: that can disagree, which is the defect the declaration was added to close.
#:
#: The charset rides along, because it is part of what the route actually sends
#: and a declaration that dropped it would be a second, smaller version of the
#: same disagreement.
#:
#: `application/marcxml+xml` is the registered type for MARC21 in XML, per the
#: Library of Congress: a cataloguer's tools dispatch on it.
EXPORT_MEDIA_TYPES: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv; charset=utf-8",
    ExportFormat.TXT: "text/plain; charset=utf-8",
    ExportFormat.HTML: "text/html; charset=utf-8",
    ExportFormat.MARCXML: "application/marcxml+xml; charset=utf-8",
}

#: Refused at import rather than covered by a test, for `book_columns._MISFILED`'s
#: reason and one of its own: the route reads this map with `[]`, so a format added
#: without an entry is a `KeyError` on somebody's export, and the declaration would
#: quietly be short by one media type with nothing raising at all.
_FORMATS_WITHOUT_A_MEDIA_TYPE = set(ExportFormat) - set(EXPORT_MEDIA_TYPES)
if _FORMATS_WITHOUT_A_MEDIA_TYPE:
    raise RuntimeError(
        "Every member of ExportFormat is sent under a media type and these have "
        f"none: {sorted(_FORMATS_WITHOUT_A_MEDIA_TYPE)}. The export route reads "
        "this map to set the response's type and the same route declares its "
        "values in the published schema, so a missing entry is both a failed "
        "export and a document that is short a promise."
    )


class BookOrigin(StrEnum):
    """Accepted values for `GET /api/books?origin=`: who brought a Book in.

    **Two values rather than a boolean**, so the parameter names what it asks
    and the filter panel offers it as one select beside format and lending.
    Absent is every Book.

    HARVESTED is a Book an OAI-PMH harvest created, `books.harvest_id` set.
    ADDED is every other: a member's, a file import's, or a row with no
    recorded adder that no harvest wrote.
    """

    HARVESTED = "harvested"
    ADDED = "added"


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
    TOKEN_EPOCH = "token_epoch"  # noqa: S105  a settings key name, not a secret

    # Where overdue reminders go, and how often. Settings rather than
    # environment variables because the library changes them: which channel
    # gets chased, and how much nagging it tolerates, are decisions made after
    # the container is running.
    OVERDUE_WEBHOOK_ENABLED = "overdue_webhook_enabled"
    OVERDUE_WEBHOOK_URL = "overdue_webhook_url"
    OVERDUE_WEBHOOK_SECRET = "overdue_webhook_secret"  # noqa: S105  a settings key name, not a secret
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
    MAIL_PASSWORD = "mail_password"  # noqa: S105  a settings key name, not a secret
    MAIL_USE_TLS = "mail_use_tls"
    MAIL_USE_SSL = "mail_use_ssl"
    MAIL_DEFAULT_SENDER = "mail_default_sender"

    # Telegram. No host key, and that absence is the control: see
    # `notifications.TELEGRAM_API` for why making it configurable would give
    # away the one property this sender has that the webhook does not.
    OVERDUE_TELEGRAM_ENABLED = "overdue_telegram_enabled"
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"  # noqa: S105  a settings key name, not a secret
    TELEGRAM_CHAT_ID = "telegram_chat_id"

    # The in app notice. One toggle and nothing else: the channel is the app,
    # so there is no destination to store and no credential to hold, which is
    # the entire argument for its existence.
    OVERDUE_IN_APP_ENABLED = "overdue_in_app_enabled"

    # The patron's own overdue notice: one mail per patron, about the loans
    # that patron holds and nothing else, to the address on their record.
    OVERDUE_PATRON_MAIL_ENABLED = "overdue_patron_mail_enabled"
    # Whether switching library mode on has already turned on the patron
    # notice and the service digest. Not a preference: written once, by the
    # settings router, so a later switch on finds it set and changes nothing.
    LIBRARY_MODE_NOTICES_DEFAULTED = "library_mode_notices_defaulted"

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
    # Whether the SRU server answers, as a third switch under the two above.
    # Publishing a catalogue to people and serving it to another library's
    # software are separate decisions: an archive may want the first without
    # the second. `settings_store.sru_is_served` reads it together with the
    # publish state, so it can never publish a catalogue on its own. Each
    # export protocol gets a row of its own beside this one rather than a
    # shared one, because a shared row is where two switches become one.
    SRU_SERVER_ENABLED = "sru_server_enabled"
    # Whether the OAI-PMH provider answers, the second export protocol's own
    # switch beside SRU's and for the same reasons. `settings_store.oai_is_served`
    # reads it with the publish state. No migration writes it on: nothing was
    # ever harvested over OAI-PMH, so off is the default for a fresh deployment
    # and an upgraded one alike.
    OAI_PROVIDER_ENABLED = "oai_provider_enabled"
    # The repository contact address `Identify` serves as `adminEmail`. Its own
    # setting rather than a member's address, so nobody's personal address is
    # published by accident; the switch above cannot be turned on while it is
    # empty (owner's decision on issue #176).
    OAI_ADMIN_EMAIL = "oai_admin_email"
    # When the OAI-PMH provider first answered a request, in ISO form, or empty
    # for never. Not a preference: `harvest.py` writes no tombstone before it,
    # since no harvester could have seen a record that left earlier.
    OAI_FIRST_SERVED = "oai_first_served"
    # The OAI-PMH harvester's switch and the repository it reads, the import
    # half of issue #178. One setting in two rows: the switch cannot be stored
    # on while the address is empty, which `routers/settings.py` refuses and
    # `settings_store.harvest_repository` reads again. No migration: nothing
    # was ever harvested, so off is the default everywhere.
    OAI_HARVEST_ENABLED = "oai_harvest_enabled"
    OAI_HARVEST_BASE_URL = "oai_harvest_base_url"
    # Whether a public record says if the book is on the shelf or on loan.
    # Its own row, off by default: a loan is a member's activity, and showing
    # a stranger that one is open is a decision of its own rather than part of
    # publishing. `settings_store.availability_is_shown` reads it with the
    # publish state, so it can never publish anything on its own. No migration:
    # nothing showed availability before, so off is the default for a fresh
    # deployment and an upgraded one alike.
    PUBLIC_AVAILABILITY_ENABLED = "public_availability_enabled"

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

    # Which entries of the curated registry this library has picked, as
    # `RegisteredCatalogue` names and nothing else. **Names, never addresses**:
    # an entry's address is always `registry.ENTRIES`, so no row holds one and
    # nothing reads one back. See `registry.picked`.
    PICKED_CATALOGUES = "picked_catalogues"

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

    # Whether an admin has put away the library page's offer of a local
    # vocabulary copy. Per installation rather than per browser, by the owner's
    # decision of 2026-11-20 on issue #139: one admin dismissing it answers for
    # the library, and a browser preference would bring it back on every
    # other device. Loading a copy ends the offer anyway; this row only ends
    # it sooner.
    VOCABULARY_OFFER_DISMISSED = "vocabulary_offer_dismissed"

    # Whether a book's heading field offers headings from the local vocabulary
    # copies as a cataloguer types (#135). On by default and read with library
    # mode, so a household never meets it: `settings_store.headings_from_vocabulary`.
    HEADINGS_FROM_VOCABULARY = "headings_from_vocabulary"


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
    #: One mail per patron, about that patron's own overdue loans, to the
    #: address on their record. The one pushing sender whose audience is a
    #: person rather than a channel, so the one that names a private Book: the
    #: borrower holding it (owner, 2026-11-22). Its loans are its own selection,
    #: `notifications.due_for_patrons`, not the digest the other three share.
    PATRON_MAIL = "patron_mail"


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
    #: A sender raised something that is neither a refusal nor a transport
    #: failure: a case the code does not anticipate. Distinct from
    #: `UNREACHABLE`, because nothing says a request was made, and from
    #: `MISCONFIGURED`, because nothing says a setting is wrong. It is that
    #: channel's failure, so the others still run, and it is broken at once,
    #: because nothing says it is transient either. The server log names the
    #: exception's type and where it was raised; the loans are left to retry.
    UNEXPECTED = "unexpected"
    #: A patron with an overdue loan has no usable email address, so the
    #: patron notice for that loan was not sent. Reported rather than skipped,
    #: so a notice nobody could address is never a notice nobody hears about.
    #: Decided before any socket is opened, like `MISCONFIGURED`, and cleared by
    #: a person: an address on the record, or the switch off.
    NO_ADDRESS = "no_address"


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

    One endpoint per verb would be a near-identical handler per member below,
    each repeating the same permission walk and the same three-way result. The
    verb is a field instead.
    """

    # No count in the docstring above, deliberately: a number beside the list it
    # counts goes stale in silence, and this one did.
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    SET_STATUS = "set_status"
    SET_OWNERSHIP = "set_ownership"
    SET_LOCATION = "set_location"
    # File a selection into a collection, or out of one: an empty value clears
    # it, the same way SET_LOCATION's empty string unpacks a box.
    SET_COLLECTION = "set_collection"
    DELETE = "delete"
    # Give each owned copy in the selection an accession number, minted from
    # its row. Idempotent: a copy that has one keeps it.
    ASSIGN_ACCESSION = "assign_accession"


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
    worth an ISBN request. NKP, BNE, BNA, BNU, BN_PL, LIBRIS, KB_DK, BIBSYS,
    MELINDA, SBN, PORBASE, OSZK and SNK are the other way round, **lookup only**, and
    for two different reasons. The NKP's,
    the BNA's and the BNU's is the server's: each renders one populated record
    per response whatever page size is asked for, so a search for ten
    candidates would be ten requests. The rest is ours: nobody has measured
    what a search at any of them would find, so each holds the conservative
    default. See `sources.LOOKUP_SOURCES` and
    `SEARCH_SOURCES`, which is why those are two sets and not one.

    **Two members need a credential and are free**: the BNA and the BNU. What
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
    #: The Biblioteca Nacional de Uruguay. The BNA's profile exactly: another
    #: Aleph behind the same YAZ front end, the same bare Dublin Core, and a
    #: login its library publishes. #117.
    BNU = "bnu"
    #: The Biblioteka Narodowa, Poland's national library. Alma SRU and MARC21,
    #: the BNE's profile exactly. `BN_PL` rather than `BNP`, which is the
    #: Portuguese national library's own abbreviation and a candidate here.
    BN_PL = "bn_pl"
    #: LIBRIS, the Swedish union catalogue the National Library of Sweden runs.
    #: SRU and MARC21 on its own server rather than on Alma, and a union
    #: catalogue like K10plus rather than a legal deposit one.
    LIBRIS = "libris"
    #: Det Kgl. Bibliotek, the Royal Danish Library. Alma SRU and MARC21, the
    #: BNE's profile at a third Alma tenant. `KB_DK` rather than `KB`, which is
    #: also the National Library of Sweden's and the Dutch one's own name.
    KB_DK = "kb_dk"
    #: The BIBSYS network, the Norwegian union catalogue of research and public
    #: libraries, which the National Library of Norway's records join. Alma's
    #: network zone over SRU and MARC21, so the BNE's profile once more.
    BIBSYS = "bibsys"
    #: Melinda, the Finnish union catalogue the National Library of Finland
    #: runs. SRU and MARC21 on its own server rather than on Alma, LIBRIS's
    #: shape.
    MELINDA = "melinda"
    #: The Servizio Bibliotecario Nazionale, Italy's union catalogue, which the
    #: ICCU runs. Z39.50, asked for its MARC21 view of records it keeps in
    #: UNIMARC.
    SBN = "sbn"
    #: PORBASE, the Portuguese union catalogue the Biblioteca Nacional de
    #: Portugal runs. Z39.50 and UNIMARC, the only syntax it answers in.
    PORBASE = "porbase"
    #: The Országos Széchényi Könyvtár, Hungary's national library. Z39.50 and
    #: MARC21.
    OSZK = "oszk"
    #: The Slovenská národná knižnica, Slovakia's national library. Z39.50 and
    #: MARC21.
    SNK = "snk"


class RegisteredCatalogue(StrEnum):
    """A catalogue in the curated registry this build ships: `registry.ENTRIES`.

    **Closed, and a second enum rather than more `CatalogueSource` members.** A
    `CatalogueSource` is asked by default and has a measured place in
    `sources.DEFAULT_ORDER`; one of these is asked by nobody until an admin
    picks it, and has no measurement to place it by, so a pick is asked only
    after the whole chain missed: `sources.Plan.picked`. Folding them would put
    an unmeasured catalogue into every household's roster on upgrade.

    **Closed because the registry is vendored**: a member is a reachable host
    this build ships, so adding one is a diff somebody reads, which is the
    property ticket 148 exists for. `registry` refuses at import a member with
    no entry and an entry with no member, and a value one `CatalogueSource`
    already spells: the test route tries `CatalogueSource` first, so the entry
    could not be named, and logins and `sources.Plan` key on the same string.
    """

    #: The National Library of Scotland. Alma SRU, MARC21.
    NLS = "nls"
    #: The National Library of Israel. Alma SRU, MARC21.
    NLI = "nli"
    #: The CSIC library network, the union catalogue of Spain's National
    #: Research Council. Alma SRU, MARC21.
    CSIC = "csic"


class Disposition(StrEnum):
    """How one catalogue answered one question, and nothing about what it said.

    **The vocabulary `z3950.py` names**, refused, unreachable and answered
    nothing, plus the case those three are the failures of. A registry entry's
    evidence and an admin's test of a source both report one, so a curation
    record and a probe result are one shape (owner, 2026-09-05).
    """

    #: It returned a record for the ISBN asked that the reader believed.
    ANSWERED = "answered"
    #: It replied and returned nothing this build believes: no record, or one
    #: whose identity check failed.
    ANSWERED_NOTHING = "answered_nothing"
    #: It replied, and the reply was a no: a diagnostic, an error status, a
    #: rate limit, or bytes no reader could take.
    REFUSED = "refused"
    #: Nothing replied inside the bound: no connection, or no answer in time.
    UNREACHABLE = "unreachable"


# A member per `CatalogueSource` is checked below the class rather than
# generated: a `StrEnum` cannot extend another, and a functional `StrEnum(...)`
# call is a type mypy cannot read members off. No migration for a new member:
# the column is a plain `String(20)` behind `models.DegradingEnum`.
class RecordOrigin(StrEnum):
    """Where a Book's record came from: a catalogue, a file, an import, or a person.

    **A closed set rather than a free string**, so every surface can label each
    value and a stored value nobody can name degrades to unknown rather than
    arriving on screen untranslated. Every `CatalogueSource` is a member under
    its own value, and so is every `RegisteredCatalogue`; the rest are the
    origins that are not a catalogue.

    **Closed across a registry refresh because a refresh is a commit.** A new
    `RegisteredCatalogue` member without an origin is refused at import below,
    and the frontend's catalogue name test then refuses a frontend with no
    label for it. An entry a later snapshot drops may keep its member here,
    so the books it supplied keep their label; removing it is safe too, since
    a stored value nobody names reads as unknown.

    **Where the record came from, never whether it was changed since.** That is
    `books.record_modified_here`, and why the two are two columns is on
    `models.Book`.
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
    BNE = "bne"
    BNA = "bna"
    BNU = "bnu"
    BN_PL = "bn_pl"
    LIBRIS = "libris"
    KB_DK = "kb_dk"
    BIBSYS = "bibsys"
    MELINDA = "melinda"
    SBN = "sbn"
    PORBASE = "porbase"
    OSZK = "oszk"
    SNK = "snk"
    #: The registry's entries, `RegisteredCatalogue`, asked on a scan once picked.
    NLS = "nls"
    NLI = "nli"
    CSIC = "csic"
    #: Typed by a member, or sent by a client that named no other origin.
    MANUAL = "manual"
    #: Read off the book's own file, or its name, on the scan page.
    FILE = "file"
    #: A reading history export, `importing.Import`.
    CSV_IMPORT = "csv_import"
    #: Another institution's MARCXML file, `importing.MarcImport`.
    MARC_IMPORT = "marc_import"
    #: A member's own library server, `importing.OpdsImport`.
    OPDS_IMPORT = "opds_import"
    #: A Calibre library read in the browser.
    CALIBRE_IMPORT = "calibre_import"
    #: A store's export or a reading device's database, read in the browser.
    STORE_IMPORT = "store_import"
    #: Another repository's records, harvested over OAI-PMH: `harvester.py`.
    OAI_HARVEST = "oai_harvest"

    @classmethod
    def of_catalogue(cls, name: str) -> RecordOrigin | None:
        """The origin a catalogue's record carries, or None for a name no catalogue has.

        A name rather than a `CatalogueSource`, because `catalogue.Record.leading`
        is a string: a record a test or a file reader labels `marc` is no
        catalogue's, and answers None rather than raising. A picked registry
        entry is a catalogue: without it, a book a pick supplied would read as
        having no origin, and a refresh from one would flag the book as changed
        here rather than say where the record came from.
        """
        return cls(name) if name in _CATALOGUES else None


#: Every name a catalogue's record can lead with: the roster and the registry.
_CATALOGUES: Final[frozenset[str]] = frozenset(map(str, CatalogueSource)) | frozenset(
    map(str, RegisteredCatalogue)
)

#: Refused at import, for `book_columns._MISFILED`'s reason: a catalogue added to
#: the roster or the registry without an origin of its own would answer a lookup
#: whose record then reads as coming from nowhere.
_SOURCES_WITHOUT_AN_ORIGIN = _CATALOGUES - set(map(str, RecordOrigin))
if _SOURCES_WITHOUT_AN_ORIGIN:
    raise RuntimeError(
        "Every CatalogueSource and RegisteredCatalogue is a RecordOrigin under the same value, and these "
        f"are not: {sorted(_SOURCES_WITHOUT_AN_ORIGIN)}. Add each to RecordOrigin."
    )


class HarvestFormat(StrEnum):
    """The serialisation a harvest read a repository in: `harvester.py` chooses it.

    MARCXML wherever a repository offers it, and Dublin Core only where it does
    not, since that is the protocol's mandatory format and carries less: no
    heading, no series, no role on a name. The preview and the result name it so
    an admin knows a Dublin Core run brings thinner Books.
    """

    MARCXML = "marcxml"
    DUBLIN_CORE = "dublin_core"


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


class Transport(StrEnum):
    """Which door a catalogue target's request goes out of.

    **A field of the row, read by one dispatcher**: `metadata._DOORS` holds one
    door per member and refuses at import to hold fewer, so nothing above it
    asks which protocol answered. What a row on each transport must carry is
    `targets.Target`'s to refuse.

    **Here rather than in `targets.py`** because `models.py` derives
    `ck_catalogue_targets_transport` from it, and a foundation importing the
    catalogue layer would point up the stack. `targets.Transport` is this
    class, re-exported.
    """

    SRU = "sru"
    #: Z39.50 through `z3950.py`'s seam: no HTTP, no redirect, no content
    #: encoding, and its own byte and time bounds.
    Z3950 = "z3950"
    #: Not SRU and not Z39.50: a JSON API of the target's own design, with its
    #: own adapter. Open Library and Google Books, and nothing else. A row here
    #: carries an address and its capabilities and no query fields at all,
    #: because there is no query grammar to name.
    BESPOKE = "bespoke"


class RecordCharset(StrEnum):
    """The character set a Z39.50 target's records arrive in, which the client converts from.

    **Data on the row, because the record cannot be trusted to say.** A MARC21
    record declares its set in leader/09 and a UNIMARC one in `100 $a/26-29`,
    but the client renders text before any reader sees a leader, and a set read
    wrongly is every accented letter wrong with nothing raised. So each row
    names what its target was measured sending, and the client converts from
    that to UTF-8.

    **The seam's spelling, not the client's**, for the reason `z3950.Syntax`
    gives: the client maps these to whatever its library calls them.
    """

    #: ISO 10646 as UTF-8, which needs no conversion.
    UTF8 = "utf8"
    #: MARC-8, the MARC21 default where leader/09 is blank.
    MARC8 = "marc8"
    #: ISO 5426, which a UNIMARC record declares as `0103` in `100 $a/26-29`.
    ISO5426 = "iso5426"


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


class CredentialKind(StrEnum):
    """What a catalogue wants before it answers, as a compliance reader names it.

    **Two kinds and not one flag**, because a policy is written about them
    separately: an API key is this deployment's own account at a commercial
    service, sent in a query string; a login is the institution's account at
    another library's server. `targets.Target.credential_kind` derives it from
    the row's `needs_key` and `secret`.
    """

    #: Answers anybody.
    NONE = "none"
    #: The deployment's own key at a metered commercial API. Google Books.
    API_KEY = "api_key"
    #: A username and password at the catalogue's own server.
    LOGIN = "login"


class HighlightSource(StrEnum):
    """Where a highlight came from, which is half of what names it there.

    `highlights.source_key` is only unique within one source, so the pair is
    the identity an import re-finds a row by: `models.Highlight` says what each
    source's key is.
    """

    #: A KOReader sidecar, `metadata.<ext>.lua`, read in the member's browser.
    KOREADER = "koreader"
    #: Readwise's own highlight id, written by the pull in `readwise.py`.
    READWISE = "readwise"


class ImageExtension(StrEnum):
    """An image format a cover, a further image or the login background is
    stored in. `config.ALLOWED_IMAGE_EXTENSIONS` is these values.

    **SVG is deliberately absent**: these files are served back from the
    app's own origin, and an SVG can carry script, which would make it a
    stored XSS vector. A member here is also a value
    `ck_cover_images_extension` admits, so adding one needs a revision.
    """

    JPEG = "jpeg"
    JPG = "jpg"
    PNG = "png"
    WEBP = "webp"


class MemberLoginService(StrEnum):
    """A service where a member holds a login of their own, sealed in
    `member_logins`.

    `models.MemberLogin` says why this kind of secret has a table to itself.
    """

    #: An access token from `readwise.io/access_token`, read by `readwise.py`.
    READWISE = "readwise"


class ReadwiseOutcome(StrEnum):
    """How the last pull of one member's Readwise highlights ended.

    Stored on the member's login so the account page can say it, and so the
    daily job can tell a member who needs to act from one who does not.
    """

    #: Every page was read and applied, so the cursor moved.
    SYNCED = "synced"
    #: A bound ended the walk early. What was read is kept; the cursor stays,
    #: so the next run reads those pages again.
    INCOMPLETE = "incomplete"
    #: Readwise answered 401: the token was revoked or mistyped.
    REFUSED = "token_refused"
    #: Readwise answered 429. The next run tries again.
    RATE_LIMITED = "rate_limited"
    #: Readwise could not be reached or answered something unreadable.
    UNAVAILABLE = "unavailable"
    #: The sealed token cannot be opened here: no key, or a different one.
    UNREADABLE = "unreadable"


@overload
def member_or[E: StrEnum](enum: type[E], stored: object, default: E, *, context: str | None = None) -> E: ...


@overload
def member_or[E: StrEnum](
    enum: type[E], stored: object, default: None, *, context: str | None = None
) -> E | None: ...


def member_or[E: StrEnum](
    enum: type[E], stored: object, default: E | None, *, context: str | None = None
) -> E | None:
    """The member this stored value names, or the default, never an exception.

    **The read end of the bargain every unconstrained enum column strikes.** A
    column holding one of these is a plain VARCHAR, so the set is enforced by a
    `CheckConstraint` or by nothing: `backup.restore` inserts through Core,
    where no Pydantic model and no `@validates` hook fires, so an archive older
    than a constraint decides the value. `enum(stored)` on a value outside the
    set raises `ValueError`, and it raises where the row is read rather than
    where it was written, which for a listing is a 500 on the whole page
    instead of one wrong card.

    SQLite cannot ALTER a CHECK, so a constraint costs a table rebuild in a
    migration every time the enum grows. That is a fair price for a closed enum
    and a recurring tax on one that is not, and this is what the second kind
    pays instead.

    **It logs, because the degrade is still data loss nobody can see.** The
    value that arrived is in the message: the whole point of a restore going
    quiet is that nothing afterwards says which rows it changed the reading of.

    Pure, and takes the stored value rather than a row, so the rule is a table
    of `(enum, stored) -> member | default` with no session and no HTTP behind
    it. `models.DegradingEnum` is what puts a column behind it.
    """
    if isinstance(stored, enum):
        return stored
    if stored is None:
        return default
    try:
        # **`str(stored)` and not `stored`**, because the parameter is `object`
        # on purpose: a column can hand back an integer or a blob, and
        # `StrEnum` takes a `str`. A member's value is a string, so this can
        # only ever succeed on something that was already one, and everything
        # else falls to the `ValueError` below with its value in the log.
        return enum(str(stored))
    except ValueError:
        logger.warning(
            "%s holds %s, which is not a %s; reading it as %r",
            # The enum's name when the caller has nothing more specific. A
            # column cannot say which row it was reading, and the one caller
            # that can say so passes it.
            context or enum.__name__,
            # **Clipped, and that is not tidiness.** This fires once per row per
            # column on every read, the column's declared length bounds nothing
            # in SQLite, and the reader can be the unauthenticated public
            # catalogue. `logvalues` holds the measurement.
            clipped(stored),
            enum.__name__,
            default,
        )
        return default


class VocabularyLoadPhase(StrEnum):
    """Where a background load of a vocabulary's local copy stands.

    Held in memory by `vocabulary_copy` and never stored: a load that finished
    is a `vocabulary_copies` row, and one under way when the process stopped is
    simply not running any more.
    """

    #: Waiting for another vocabulary's load to finish.
    QUEUED = "queued"
    #: Downloading the release from its source.
    FETCHING = "fetching"
    #: Turning the release into entries.
    CONVERTING = "converting"
    #: Writing the entries beside the copy in use.
    LOADING = "loading"
    #: Stopped. The copy in use, or none, still answers.
    FAILED = "failed"
