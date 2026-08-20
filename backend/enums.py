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
    """

    UNREAD = "unread"
    WANT_TO_READ = "want_to_read"
    READING = "reading"
    READ = "read"


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
    answer per format: a household can own the audiobook and not the paperback,
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
    good plus) and nobody else can apply them consistently, so a household
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


class TagCategory(StrEnum):
    """The groups tags are presented in throughout the UI.

    The first three are the curated vocabulary, seeded at boot and the same in
    every deployment. CUSTOM is everything a household invents for itself.

    Keeping them apart, rather than making every tag free-form as Jelu and
    Openreads do, is deliberate: the curated list is what makes the tag picker
    useful on the first day, before anybody has typed anything. What was wrong
    was having no way past it.
    """

    TYPE = "type"
    GENRE = "genre"
    AGE = "age"
    CUSTOM = "custom"


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
    DELETE = "delete"
