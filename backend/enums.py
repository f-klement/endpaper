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


class BookFormat(StrEnum):
    """What kind of object the copy is.

    Separate from everything else because "do we own this" has a different
    answer per format: a library can hold the audiobook and not the paperback,
    and a reader looking for something to take on a train cares which. Reviews
    of every competitor in this space ask for it by name, usually as "where is
    audiobook".

    OTHER exists so the list can stay short. A boxed set, a magazine or a
    pamphlet is a real thing on a real shelf and does not need its own value.
    """

    HARDCOVER = "hardcover"
    PAPERBACK = "paperback"
    EBOOK = "ebook"
    AUDIOBOOK = "audiobook"
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
    number does not, which costs nothing because nothing here sorts on it.

    **LCSH is the one member with no identifier at all, and that is measured
    rather than assumed.** MODS from `lx2.loc.gov` carries no `valueURI` on a
    single `<subject>` element across 900 live records (2026-08-24), so the
    only access point the record supplies is the authorised heading string.
    `number` holds that string and `label` is absent, because storing the same
    words in both columns would state one fact twice. The consequence is
    honest and worth knowing: a heading the Library of Congress later revises
    (`Afro-Americans` became `African Americans`) changes this scheme's
    identifier, where a GND number or a Dewey notation survives its own
    recaptioning. That is why LCSH sorts last in `_SCHEME_ORDER`.

    **A person's identifier is not one of these**, though the DNB writes it in
    the same `$0`: `100 $0` says who wrote the book, and every scheme here says
    what the book is about. See `docs/decisions.md`, "The author's GND is read
    by nothing".

    Only DDC is projected onto a tag: see `ddc.DIVISION_TAGS`. The other three
    are stored because a catalogue heading is worth keeping whole, not because
    anything reads them yet.
    """

    DDC = "ddc"
    LCC = "lcc"
    GND = "gnd"
    LCSH = "lcsh"


class ExportFormat(StrEnum):
    CSV = "csv"
    TXT = "txt"


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


class OverdueSender(StrEnum):
    """Which channel a reminder went out on.

    A closed set because the result reports one outcome per sender and the
    client renders each: a string would let a new sender arrive on screen with
    no label and no test noticing.
    """

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
