from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from enums import CatalogueSource, Locale, OverdueNotifyReason, OverdueSender

#: How far apart two reminders for the same loan may be, in days. The floor is
#: 1 rather than 0: a zero would mean "resend on every tick", which is an hourly
#: repeat of the same list into the library's channel.
MIN_REMINDER_DAYS = 1
MAX_REMINDER_DAYS = 365

#: Long enough for a signed webhook URL with a token in its query string.
MAX_WEBHOOK_URL = 500
MAX_WEBHOOK_SECRET = 200

#: Bounds on the mail and Telegram fields.
#:
#: Every one of these is a settings row an admin types and a restore can write
#: through Core, so the bound is what stops a settings table row becoming a
#: multi-megabyte string the hourly ticker reads on every tick.
#:
#: `MAX_MAIL_RECIPIENT_LIST` bounds the **length of the field**, not how many
#: addresses are in it. `mailer.MAX_RECIPIENTS` is what caps the count, and the
#: two are separate because a 1000 character field of one very long address is a
#: different mistake from ten thousand short ones.
MAX_MAIL_HOST = 255
MAX_MAIL_ADDRESS = 320
MAX_MAIL_RECIPIENT_LIST = 1000
MAX_MAIL_PASSWORD = 200
MAX_MAIL_USERNAME = 320
#: A bot token is `<digits>:<35 characters>` today. 300 is room for Telegram
#: changing its mind without being room for anything else.
MAX_TELEGRAM_TOKEN = 300
MAX_TELEGRAM_CHAT = 64


#: The provider list can never be longer than the roster, because every entry
#: names one member of a closed enum. Stated as a bound on the request body all
#: the same: without it a payload repeating one source a million times is a
#: million objects validated before `sources.parse` gets to drop all but one.
MAX_CATALOGUE_SOURCES = len(CatalogueSource)


class CatalogueSourcePreference(BaseModel):
    """One row of the provider list, as a client sends it back.

    **Two fields, because they are the only two a household sets.** Everything
    else on `CatalogueSourceOut` is derived, and accepting a derived field back
    would be accepting a client's opinion about a rule the server owns.
    """

    source: CatalogueSource
    enabled: bool


class CatalogueSourceOut(BaseModel):
    """One catalogue, as the settings screen needs to draw it.

    **Only `source` and `enabled` are stored; every other field is derived**,
    and they are served rather than recomputed in the browser for the reason
    `public_catalogue_published` is: two places deciding one rule is how a
    screen comes to promise something the server does not do.

    `sources.describe` is the one place that decides them, and each field below
    says what it means rather than being enumerated here. This paragraph used to
    list them and was stale on two within a round, which is what a summary of
    five fields six lines above the five fields is for.
    """

    source: CatalogueSource
    #: Off means **not asked**, on every path in `metadata.py` that reaches this
    #: catalogue for a record. It is not a claim about every request the
    #: application makes: `covers.py` still asks Open Library and the DNB for a
    #: cover image, and `authority.py` asks three more hosts about an author.
    #: `backend/sources.py` states that boundary in full, and this sentence used
    #: to contradict it.
    enabled: bool
    #: Whether this source can answer an ISBN at all. False for the BnF and the
    #: Library of Congress, which answer title search only, so the screen can
    #: say that reordering them changes nothing about scanning a barcode.
    answers_lookup: bool
    answers_search: bool
    #: Whether it is one of the leading enabled sources asked together on every
    #: lookup. This is what "what does enabling cost" resolves to on the ISBN
    #: path: everything below the leading run is asked only after a miss.
    asked_first: bool
    #: Whether it needs a credential the household supplies. Google Books alone
    #: today.
    needs_a_key: bool
    #: Whether that credential is in force, from the environment or the table.
    #:
    #: **Sent beside `ready` rather than folded into it**, because they are two
    #: causes and a screen showing only the conjunction cannot tell them apart.
    #: A library with a key whose Google Books card is switched off was told to
    #: add a key it already had, which is the exact symptom this feature exists
    #: to stop somebody hunting for.
    has_key: bool
    #: Whether it **could** answer if asked, which is false only for a source
    #: needing a key that this deployment has not got: Google Books with none
    #: stored and none in the environment. **The most likely single cause of
    #: "why is this not working"**, so it is a field rather than something a
    #: reader is left to infer from two other screens.
    #:
    #: Deliberately independent of `enabled`. A household switching Google Books
    #: on wants to be told there is no key at the moment it switches it on, and
    #: a field that went false only once the source was already enabled could
    #: not say so first. See `sources.describe`.
    ready: bool


class LoginImageOut(BaseModel):
    """Where the login background lives, as a path under the /covers mount."""

    url: str


class FeatureFlagsOut(BaseModel):
    """What the frontend needs in order to decide what to render.

    Readable by anyone, deliberately: the login page is localised, so the
    default language has to be known before a token exists. It carries no
    secrets and nothing about the catalogue.
    """

    google_books_enabled: bool
    # Whether the lookup will actually work: the toggle is on AND a key is
    # stored. `google_books_enabled` alone is not enough to decide what to
    # render, because a toggle with no key behind it produces a button that
    # can only ever 400. Not a secret: any member could learn the same thing
    # by pressing that button once.
    google_books_ready: bool = False
    goodreads_lookup_enabled: bool
    default_locale: Locale

    # ── Library mode ─────────────────────────────────────────────────────
    #: Whether this Library is running as a small archive rather than a
    #: household.
    #:
    #: **It was deliberately absent for a round**, because it had no reader, and
    #: an unread field on the one endpoint a stranger can call is disclosure
    #: with nothing on the other end of it. The note left here said it cost one
    #: line to add back beside its first consumer. MARC import and export is
    #: that consumer: the export menu offers MARCXML only in library mode, and
    #: the MARC import section appears only there, so a client with no session
    #: to read `GET /api/settings` from still has to be told.
    #:
    #: **The raw switch, not a conjunction**, unlike the field below it. There
    #: is nothing to conjoin: the server gates both MARC routes on this row
    #: alone, so a client reading it gets exactly the answer the routes give.
    #:
    #: What it discloses to a caller with no token is one boolean of deployment
    #: posture: this instance is run as a library. It says nothing about the
    #: catalogue, and **it is not the same disclosure as the field below it**,
    #: which was the first justification written here and is measurably wrong:
    #: with library mode on and nothing published the response reads
    #: `library_mode: true, public_catalogue_published: false`, so this is
    #: strictly the wider of the two in that state. It is published because a
    #: client with no admin session cannot otherwise tell whether to offer a
    #: MARC control the server will answer 403 to.
    library_mode: bool = False

    # ── The public catalogue ─────────────────────────────────────────────
    #:
    #: Whether a reader with no account may search and read item records.
    #:
    #: **The conjunction, not the raw switch.** It is false whenever library
    #: mode is off, however the publish row reads, which is the same answer
    #: `settings_store.public_catalogue_is_published` gives the routes. Two
    #: places reading one row and disagreeing about what it means is how a UI
    #: comes to promise something the server refuses.
    #:
    #: Readable without a session, like everything else on this model, and it
    #: has to be: it is what tells a browser holding no token whether there is
    #: a public catalogue to show. It discloses nothing a request to
    #: `/api/public/books` would not.
    public_catalogue_published: bool = False


class SettingsOut(BaseModel):
    """The admin view. The API key is masked, never returned in full."""

    google_books_enabled: bool
    # Masked: enough to see a key is present and tell one from another, and
    # nothing a browser could use. `has_google_books_api_key` is what the UI
    # keys off, because a masked string is not a truth value.
    google_books_api_key_preview: str
    has_google_books_api_key: bool
    # True when the deployment supplied the key through the environment. It then
    # wins over anything stored and cannot be changed here, so the UI disables
    # the field rather than offering an edit that would be refused. Reporting
    # *where* a secret comes from is not reporting the secret.
    google_books_api_key_from_env: bool = False
    goodreads_lookup_enabled: bool
    default_locale: Locale

    # ── Catalogue sources ────────────────────────────────────
    #: The whole roster, always, in the order this library asks them, whether or
    #: not each is on. **Never only the enabled ones**: the screen has to draw a
    #: switched off source in order to offer switching it back on, and a list
    #: that omitted them would make "off" and "not in this build" the same
    #: thing on screen.
    #:
    #: Empty only if `sources.DEFAULT_ORDER` is, which it is not. It is a list
    #: rather than a map because the order is the point.
    catalogue_sources: list[CatalogueSourceOut] = Field(default_factory=list)

    # ── Overdue reminders ────────────────────────────────────────────────
    overdue_webhook_enabled: bool = False
    #: Returned in full, unlike the secret beside it. It is a destination the
    #: admin typed and has to be able to check; a masked URL cannot be
    #: proofread, and the whole point of the field is spotting a wrong one.
    #: An admin who can read this is an admin who can change it.
    overdue_webhook_url: str = ""
    #: Masked, like the Google key, for the same reason: the browser has no use
    #: for the signing secret and every reason not to hold it.
    overdue_webhook_secret_preview: str = ""
    has_overdue_webhook_secret: bool = False
    overdue_reminder_days: int = Field(
        default=7, ge=MIN_REMINDER_DAYS, le=MAX_REMINDER_DAYS
    )

    # ── Mail ─────────────────────────────────────────────────────────────
    #: Every one of these reports the value **in force**, the environment's
    #: where it supplied one, for the reason the Google key's preview does: a
    #: screen showing a value the next send will not use is worse than one
    #: showing nothing. `mail_from_env` names which fields that applies to, so
    #: the UI disables them rather than offering an edit the server would 409.
    #: Reporting *where* a value comes from is not reporting the value, which is
    #: why that list is safe to serve beside a masked secret.
    overdue_mail_enabled: bool = False
    overdue_mail_to: str = ""
    mail_server: str = ""
    mail_port: str = ""
    mail_username: str = ""
    #: Masked, like every other secret here. `has_mail_password` is what the UI
    #: keys off, because a masked string is not a truth value.
    mail_password_preview: str = ""
    has_mail_password: bool = False
    mail_use_tls: bool = False
    mail_use_ssl: bool = False
    mail_default_sender: str = ""
    #: Which of the seven mail settings this deployment pinned. A list rather
    #: than one flag per field: the fields are uniform, and seven booleans is
    #: seven chances for one to be forgotten when an eighth arrives.
    mail_from_env: list[str] = Field(default_factory=list)

    # ── Telegram ─────────────────────────────────────────────────────────
    #: No host field, and its absence is the control rather than an omission.
    #: See `notifications.TELEGRAM_API`.
    overdue_telegram_enabled: bool = False
    telegram_bot_token_preview: str = ""
    has_telegram_bot_token: bool = False
    telegram_bot_token_from_env: bool = False
    #: In full: it is a destination an admin typed and has to be able to
    #: proofread, the same asymmetry the webhook URL has against its secret.
    telegram_chat_id: str = ""
    telegram_chat_id_from_env: bool = False

    # ── In app ───────────────────────────────────────────────────────────
    #: One field, because the channel is the app: no destination, no
    #: credential, nothing to pin from the environment. **Defaults to true**,
    #: unlike the three above it, which start silent because they send
    #: catalogue content somewhere outside this app.
    overdue_in_app_enabled: bool = True

    # ── Library mode and the public catalogue ────────────────────────────
    #: The two switches **as stored**, not as they take effect. This model is
    #: the admin's view of the settings table, and a screen that showed
    #: `public_catalogue_enabled` as false because library mode happens to be
    #: off would be a screen an admin cannot use: they would turn it on twice
    #: and see it come back off. `public_catalogue_published` beside them is
    #: the conjunction, which is what actually decides whether anything is
    #: served, and is the value the confirmation and the banner read.
    library_mode: bool = False
    public_catalogue_enabled: bool = False
    public_catalogue_indexing_enabled: bool = False
    #: `library_mode and public_catalogue_enabled`, computed on the server so
    #: the browser cannot get the rule wrong. See `FeatureFlagsOut`.
    public_catalogue_published: bool = False


class SettingsUpdate(BaseModel):
    """A partial update. Every field is optional; absent means "leave alone".

    That matters for the API key: a form that always submitted every field
    would blank the key whenever an admin toggled something else, since the
    browser never received the real value to send back.
    """

    google_books_enabled: bool | None = None
    # An empty string clears the key deliberately. `None` leaves it untouched.
    google_books_api_key: str | None = Field(default=None, max_length=200)
    goodreads_lookup_enabled: bool | None = None
    default_locale: Locale | None = None

    #: The provider list, sent whole rather than patched.
    #:
    #: **A partial list is accepted and completed rather than refused**, by the
    #: same `sources.parse` a stored row goes through: anything it does not name
    #: is appended in the default order and enabled. One door for both, so a
    #: payload and a restore cannot disagree about what an unmentioned source
    #: means. A repeat is dropped, and a name this build does not know is
    #: dropped rather than 422ing, because a client one release ahead is not a
    #: bad request.
    #:
    #: Bounded because a request body is bounded, not because the roster is:
    #: see `MAX_CATALOGUE_SOURCES`.
    catalogue_sources: list[CatalogueSourcePreference] | None = Field(
        default=None, max_length=MAX_CATALOGUE_SOURCES
    )

    overdue_webhook_enabled: bool | None = None
    #: An empty string clears the destination. `None` leaves it untouched.
    overdue_webhook_url: str | None = Field(default=None, max_length=MAX_WEBHOOK_URL)
    #: Write only, like the Google key: the browser never received the stored
    #: value, so an absent field has to mean "leave alone" or every unrelated
    #: toggle would blank the secret.
    overdue_webhook_secret: str | None = Field(
        default=None, max_length=MAX_WEBHOOK_SECRET
    )
    overdue_reminder_days: int | None = Field(
        default=None, ge=MIN_REMINDER_DAYS, le=MAX_REMINDER_DAYS
    )

    overdue_mail_enabled: bool | None = None
    overdue_mail_to: str | None = Field(default=None, max_length=MAX_MAIL_RECIPIENT_LIST)
    mail_server: str | None = Field(default=None, max_length=MAX_MAIL_HOST)
    #: A string, not an `int`, so an empty field clears it back to the default
    #: the way every other text setting here does. `mailer.checked_config`
    #: refuses anything that is not a port before a socket is opened.
    mail_port: str | None = Field(default=None, max_length=5)
    mail_username: str | None = Field(default=None, max_length=MAX_MAIL_USERNAME)
    #: Write only, like the webhook secret: the browser never received the
    #: stored value, so an absent field has to mean "leave alone" or every
    #: unrelated toggle would blank it.
    mail_password: str | None = Field(default=None, max_length=MAX_MAIL_PASSWORD)
    mail_use_tls: bool | None = None
    mail_use_ssl: bool | None = None
    mail_default_sender: str | None = Field(default=None, max_length=MAX_MAIL_ADDRESS)

    overdue_telegram_enabled: bool | None = None
    #: Write only. It is a credential, and Telegram puts it in the URL path.
    telegram_bot_token: str | None = Field(default=None, max_length=MAX_TELEGRAM_TOKEN)
    telegram_chat_id: str | None = Field(default=None, max_length=MAX_TELEGRAM_CHAT)

    overdue_in_app_enabled: bool | None = None

    #: Library mode, the publish switch and whether a crawler is invited.
    #:
    #: Three separate fields, and none of them refuses the other: an admin may
    #: store `public_catalogue_enabled` while library mode is off, and the
    #: catalogue stays unpublished because
    #: `settings_store.public_catalogue_is_published` reads both. Refusing the
    #: write instead would make the order the two toggles are saved in matter,
    #: and would lose an admin's stated intent the moment they turned library
    #: mode off to look at something.
    library_mode: bool | None = None
    public_catalogue_enabled: bool | None = None
    public_catalogue_indexing_enabled: bool | None = None

    @field_validator("overdue_webhook_url")
    @classmethod
    def http_or_https(cls, value: str | None) -> str | None:
        """Refuse a destination that is not an http(s) URL.

        Checked here **and** again in `notifications.py` before the request is
        made. Two checks rather than one because they answer different
        questions: this one refuses the save with a 422 naming the field, and
        the other one refuses to send at all, which covers a row written by a
        restore or edited by hand. A `file:` or `gopher:` destination is not a
        typo worth guessing at.

        This does **not** try to keep an admin off the cluster's own network.
        See `docs/security.md`: the URL is admin-set, and a blocklist of
        private ranges is a thing that looks like a control and is not one.
        """
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return ""
        parsed = urlparse(trimmed)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("The webhook URL must start with http:// or https://")
        return trimmed


class SenderOutcome(BaseModel):
    """What one channel did with the digest.

    **The withheld count is here rather than only at the top, and the case it
    was written for has now arrived.** The three senders that push outward
    withhold the same private books, because each goes to a channel rather than
    to a person, so their three numbers agree. The in app channel reports **0**,
    because its audience is a member and nothing is withheld from it. A single
    figure at the top would now be wrong on one row of four.
    """

    sender: OverdueSender
    sent: bool = False
    loans: int = Field(default=0, ge=0)
    skipped_private: int = Field(default=0, ge=0)
    #: Null exactly when `sent` is true, as at the top level.
    reason: OverdueNotifyReason | None = None
    detail: str | None = None


class OverdueNotifyResult(BaseModel):
    """What one run of the overdue digest did.

    Reported rather than logged, because "send now" exists so a person can see
    the thing work. `skipped_private` is here for the same reason the exclusion
    exists: a library that expects five entries and gets four should be able
    to see why without reading the source.
    """

    #: True when a request was actually made and the receiver accepted it.
    #:
    #: A sender that **pushes**, which is what `notifications.pushes_outward`
    #: decides. The in app channel reports `sent` in its own row and never sets
    #: this one: it hands the digest to nothing, so a run carrying only that
    #: channel sent nothing and answers `IN_APP_ONLY`.
    sent: bool = False
    #: Loans in the digest that was sent, or that would have been.
    loans: int = Field(default=0, ge=0)
    #: Overdue loans left out because the book is private. See decisions.md.
    skipped_private: int = Field(default=0, ge=0)
    #: Which of the four ways nothing was sent. **Null exactly when `sent` is
    #: true**, and set in every other case: `_outcome` in `notifications.py` is
    #: the only thing that builds a not-sent result, so a new exit cannot omit
    #: it.
    #:
    #: A closed set rather than only the sentence below, because the client has
    #: to render the difference and cannot branch on prose. Without it a refused
    #: webhook and a quiet week were the same line on the screen.
    reason: OverdueNotifyReason | None = None
    #: The same outcome as a sentence, for a log or for an API caller with no
    #: message catalogue. Null on a successful send.
    detail: str | None = None
    #: One entry per sender this run had something to report, in sender order.
    #:
    #: **Empty in two cases, not one.** Every channel off, which is `DISABLED`;
    #: and a run with nothing overdue while the in app notice is off, which is
    #: `NOTHING_DUE` with no pushing sender attempted. A pushing sender is
    #: reported when it was tried, and a run with nothing to send tries none.
    #:
    #: **`sent` at the top level is true when any sender that pushes
    #: delivered**, because that is the condition `notified_at` is stamped on:
    #: a reminder went out. A sender that failed is reported here rather than
    #: compensated for, so a broken receiver is visible on the screen that
    #: configures it instead of turning the working channels into an hourly
    #: repeat.
    #:
    #: The in app row is here on a run that pushed nothing, including one where
    #: nothing was overdue, because it is the channel a household can read
    #: without configuring anything and "is it on" is what they are asking.
    senders: list[SenderOutcome] = Field(default_factory=list)


class SenderHealth(BaseModel):
    """What one switched-on channel last did, as a standing record.

    #82. The per run report above says what happened on the run you are looking
    at; this says what has been happening. Without it a household running mail
    and Telegram whose bot token expires gets mail delivered, the loan stamped,
    everything apparently normal, and Telegram failing hourly with nothing
    anywhere but the container log.

    Only channels that are switched on are reported: a line about a webhook
    somebody turned off a month ago is a line about nothing.
    """

    sender: OverdueSender
    #: Null until this channel has run at all, which is what a household sees
    #: on the day they configure one. "Not yet" and "fine" are the two answers
    #: they most need to tell apart, so they are not the same value here.
    last_run_at: datetime | None = None
    #: Null for the same reason as `last_run_at`.
    sent: bool | None = None
    #: The failure, if the last run was one. Null on a success.
    reason: OverdueNotifyReason | None = None
    detail: str | None = None
    #: The first failure of the current unbroken run of them, so a channel that
    #: failed once at 3am reads differently from one failing every hour since
    #: Tuesday. Null whenever the last run succeeded.
    failing_since: datetime | None = None
    #: How many consecutive failures. Zero on a success and on a channel that
    #: has never run.
    failures: int = Field(default=0, ge=0)
    #: Whether this is worth interrupting somebody about, which is a decision
    #: rather than a fact and is made by `notifications._is_broken`: a refusal
    #: at once, a transport failure only after it has persisted. **One failed
    #: send is a network, every send failing for a day is a configuration.**
    broken: bool = False


class RestoreResult(BaseModel):
    """What a restore actually put back.

    Counted per table rather than reported as "done", so a backup that was
    missing its covers or its loans says so instead of looking successful.

    The list is the tables whose absence a library would notice: their books,
    their accounts, what they wrote, who has what, and what they have read. It
    is not every table, and the two it leaves out are the two nobody counts:
    `tags` and `book_tags` come back with the books, and `settings` is one row
    per toggle. A table added to `backup._TABLES` belongs here if losing it
    silently would look like a successful restore.
    """

    books: int = Field(ge=0)
    users: int = Field(ge=0)
    notes: int = Field(ge=0)
    loans: int = Field(ge=0)
    covers: int = Field(ge=0)
    #: Every member's reading status, rating and reading dates. Absent from
    #: this report until reading progress was added, so a restore that dropped
    #: the library's entire reading history read as a clean one.
    user_books: int = Field(default=0, ge=0)
    reading_progress: int = Field(default=0, ge=0)
    #: The library's shelf labels. Here for the reason above: losing them
    #: silently restores every book unfiled, which reads as a clean restore
    #: until somebody opens the library and finds their shelves gone.
    collections: int = Field(default=0, ge=0)
    #: Passages members typed out by hand. They exist nowhere else: a book can
    #: be rescanned and a cover refetched, and a quote cannot, so a restore
    #: that silently dropped them is the worst case this field guards against.
    quotes: int = Field(default=0, ge=0)
    #: The author merge decisions. The clearest case this field exists for: a
    #: merge writes nothing to `books`, so an archive without these rows
    #: restored a library where every merged author had split back into its
    #: spellings while every book looked perfectly intact. The table was
    #: missing from `backup._TABLES` entirely until 2026-08-26 and no count
    #: reported its absence.
    author_aliases: int = Field(default=0, ge=0)
