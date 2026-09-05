"""The facts a Library keeps about its Books that this schema does not know.

## The privacy rule, which is the whole review

**Every reader and writer below takes `Book` objects, never book ids.** A caller
that forgets gets a type error at the call site, before anything is read, which is
what makes the rule structural rather than remembered: a `Book` in hand has
already been through the Shelf.

**No `Shelf` here, and that is the second half of the same decision.** A Shelf
narrows to a viewer; this module is handed rows that were already narrowed, so
taking one would put the privacy rule in two places.

## Rendering a value as a link is an injection surface

**The kind is declared, never detected**, so a value cannot become a link by
looking like one.

**The declaration is not the permission**: `link_target` re-reads the stored
value on every read rather than trusting what a write accepted, so a row that
arrived through a restore is held to the same rule.

**The stored value for a URL field is rebuilt from the parse**, not kept as typed,
so what is stored is what the parser resolved.

## Two named ways past a Book

Both are named rather than commented, for the same reason `shelf.py` names its
two: a table wide question cannot be scoped to a viewer without leaving rows
nobody can reach.
"""

import logging
from collections.abc import Collection
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from enums import CustomFieldKind
from models import (
    MAX_CUSTOM_FIELDS,
    Book,
    CustomField,
    CustomFieldValue,
)

#: The two schemes a value may be linked at.
#:
#: Everything else is text, including the ones that are the reason this tuple
#: exists: `javascript`, `data` and `vbscript`. A scheme relative `//host`
#: carries no scheme at all and is refused by the same test.
logger = logging.getLogger("endpaper.custom_fields")

_LINKABLE_SCHEMES = ("http", "https")

#: The three code points a browser reads as a label separator in a host, and
#: `urlsplit` does not.
#:
#: **This is not a tidying rule, it is the one that stops a phishing link.**
#: WHATWG's host parser maps U+3002 IDEOGRAPHIC FULL STOP, U+FF0E FULLWIDTH
#: FULL STOP and U+FF61 HALFWIDTH IDEOGRAPHIC FULL STOP onto `.` before it
#: splits the labels; Python's does not, and neither does IDNA on its own.
#: Measured 2026-08-27, on the same string:
#:
#:     urlsplit('https://good.example\u3002evil.example/x').hostname
#:         -> 'good.example\u3002evil.example'      one label
#:     new URL(same).host
#:         -> 'good.example.evil.example'            registrable: evil.example
#:
#: So a Member could store a link that reads as a host this Household trusts,
#: pass every refusal below, and send another Member to somebody else's site.
#: In a shared Library that is a phishing vector rather than a curiosity, and
#: it is why the host is **rebuilt** rather than merely inspected.
#:
#: **Three literals are only the whole rule because the percent escape is
#: refused.** WHATWG decodes the host before it maps it, so `%2e` is this same
#: divergence arriving one step earlier and this table would never see it; a
#: mapping that handled the literals alone would look complete and close
#: nothing. `link_target` refuses `%` in a host for that reason, and the two
#: halves have to be read together.
_HOST_SEPARATORS = {"\u3002": ".", "\uff0e": ".", "\uff61": "."}


class Refused(Exception):
    """What this Library will not do, carrying the sentence a person reads.

    An exception rather than a returned `None`, because every refusal here has
    a different reason and a caller that collapses them to "it did not work"
    cannot say which. The routers map it to a 409.
    """


class Filled(NamedTuple):
    """One field a Book has something in, ready to render.

    `href` is `None` for anything that is not a link, which is every TEXT field
    and any URL field whose stored value does not survive `link_target`. The
    caller renders `value` either way, so a refused link degrades to the text
    it already was rather than to nothing.

    `kind` is carried rather than left for the caller to read off `field.kind`
    and coerce, so the tolerance in `_kind_of` is applied once, here, instead of
    at each call site.
    """

    field: CustomField
    kind: CustomFieldKind
    value: str
    href: str | None


def _kind_of(field: CustomField) -> CustomFieldKind:
    """What this definition holds, degrading to TEXT rather than raising.

    The column is a plain VARCHAR, and `CustomFieldKind(...)` on a value that
    is not one of the two **raises `ValueError`**. That is the poisoned row
    shape `link_target` is written against, and it would be a worse one: a
    single bad `kind` would 500 every read of every Book with a value in that
    field, not one Book.

    `ck_custom_fields_kind` in the schema is what stops such a row arriving,
    including through `backup.restore`, which inserts through Core and sees no
    Pydantic model. This is the second half, for a database restored from an
    archive older than that constraint, and it degrades in the safe direction:
    an unrecognised kind is TEXT, and a TEXT field never links whatever it
    holds.

    **The definitions route is guarded by the constraint alone**, not by this:
    `CustomFieldOut.kind` is typed, so Pydantic would refuse a bad row there
    with a 500. Stated rather than left to be discovered.
    """
    try:
        return CustomFieldKind(field.kind)
    except ValueError:
        logger.warning(
            "Custom field %s has an unrecognised kind %r; reading it as text",
            field.id,
            field.kind,
        )
        return CustomFieldKind.TEXT


def link_target(kind: CustomFieldKind, value: str) -> str | None:
    """Where this value points, or None if it is not somewhere to point.

    Pure, and called on every read rather than only on every write: see the
    module docstring, "the declaration is not the permission".

    A TEXT field never links whatever it holds, so the kind gate comes first
    and is not one of the refusals counted below.

    **Seven refusals**, counted as conditions rather than as branches, and
    every one of them is a value a person can type into a text box. The same
    seven, in the same order, are the numbered list in `docs/security.md`:

    * whitespace or a backslash anywhere in the value: both make Python and a
      browser read a **different host**, so neither can be reconciled
    * a value `urlsplit` cannot parse at all, which **raises** rather than
      returning: stored once, that is a row which 500s every read of its Book
      for good, which is the shape `covers.is_renderable` was fixed for
    * a scheme that is not `http` or `https`, which is `javascript:`, `data:`
      and a scheme relative `//host` (that one parses to no scheme at all)
    * a username or password, because `https://calibre.example@evil.example/`
      reads as the first host and navigates to the second
    * port zero, which is a link no browser will follow
    * a **percent escape in the host**, which is the separator mapping below
      arriving one step earlier: WHATWG decodes before it runs IDNA, so `%2e`
      lands where `\u3002` does. Refused rather than decoded, because decoding
      is recursive and encodes more than separators. The path and the query are
      untouched: `/book/12%20a` is a link
    * no host, or one with an empty label, so `https:///x` is text

    Returns the URL **rebuilt from the parse**, with the host separators in
    `_HOST_SEPARATORS` mapped onto `.` first. `parsed.geturl()` hands back the
    string that came in, which for `https://good.example\u3002evil.example/x`
    is a link this app calls one host and a browser sends somewhere else.
    Rebuilding makes the stored value name the host that will actually be
    reached, so it reads honestly as well as resolving honestly.

    **What "both ends agree" is worth, stated rather than assumed.** It is
    measured against the divergences named here, not proved in general: Python
    and a browser are two URL parsers and only one of them implements WHATWG.
    The half that does not depend on that agreement is the scheme test, which
    is what actually stops code from running.

    **One divergence is named and deliberately not closed**, because it is a
    mismatch rather than a spoof. UTS-46 **deletes** ignored code points, so a
    host carrying a soft hyphen, a zero width space or a byte order mark stores
    as typed and resolves without them: `calibre.exa\xadmple` is
    `calibre.example` to a browser. Deletion can only ever shorten a host, so
    it cannot reach a domain the text does not already name, and the characters
    are invisible in the link text as well as absent from the destination, so
    there is nothing for a reader to misread. That is the whole difference from
    `%2e` and `\u3002`, both of which **lengthen** the host and put a different
    registrable domain behind the same text.
    """
    if kind is not CustomFieldKind.URL:
        return None
    # Before anything is parsed. Both characters make Python and a browser read
    # a **different host** out of the same string, so a value carrying one can
    # never be reconciled and is refused rather than repaired. A backslash ends
    # the authority for a browser and does not for `urlsplit`
    # (`http://good.example\.evil.example/x` is one host here and
    # `good.example` with a path of `/.evil.example/x` there); whitespace makes
    # `new URL()` throw outright, so an href built from it is a link nothing
    # can follow. Neither appears unencoded in a URL anybody meant to write.
    if any(character.isspace() for character in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        # Read inside the try: this is the attribute that raises.
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in _LINKABLE_SCHEMES:
        return None
    if parsed.username or parsed.password:
        return None
    # `urlsplit` itself refuses a port above 65535 or below zero, by raising
    # from the attribute read above, which is why that read is inside the try
    # rather than here. What is left for this line is **port zero**, which it
    # returns as `0`: no browser connects to it, so a link to it is a link that
    # cannot be followed. Measured, not assumed: `:0` yields `0`, `:65536`
    # raises "Port out of range", `:-1` raises "could not be cast".
    if port == 0:
        return None

    host = parsed.hostname or ""
    for separator, plain in _HOST_SEPARATORS.items():
        host = host.replace(separator, plain)
    if not host or "%" in host or ".." in host or host.startswith(".") or host.endswith("."):
        # An empty host is `https:///x`. The rest are what the separator
        # mapping can produce out of a host that was already malformed, and a
        # label that is empty on one side of the wire and not the other is the
        # divergence this whole function exists to close.
        #
        # **`%` is the separator mapping one step earlier, and refusing it is
        # what closes the mapping at all.** WHATWG percent-decodes the host
        # *before* it runs IDNA, so `%2e` reaches the same place `\u3002` does
        # and `_HOST_SEPARATORS` never sees it. Measured 2026-08-27 against
        # `new URL(...).host`, every one of these was stored as a link and
        # resolved to `evil.example`:
        #
        #     calibre.example%2eevil.example      -> calibre.example.evil.example
        #     calibre.example%2Eevil.example      -> calibre.example.evil.example
        #     calibre.example%ef%bc%8eevil.example -> calibre.example.evil.example
        #
        # It cannot be repaired the way a literal separator can, because
        # decoding is recursive (`%252e`) and encodes more than separators
        # (`%00`, `%2f`, both of which stored as links a browser then throws
        # on). So it joins whitespace and the backslash: not something anybody
        # typed on purpose, and not reconcilable between the two parsers.
        #
        # **The path and the query are untouched by this.** A percent escape
        # there is ordinary and both parsers agree about it;
        # `https://calibre.example/book/12%20a` is a link.
        return None

    # **Rebuilt, not returned as it arrived.** Returning `parsed.geturl()` gives
    # back the string that was passed in, separators and all, which is exactly
    # the value a browser would resolve elsewhere. Brackets go back on an IPv6
    # host because `hostname` strips them and a bare `::1` in a netloc is not a
    # URL. `urlsplit` has already lowercased the scheme and the host.
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _stored_form(kind: CustomFieldKind, value: str) -> str | None:
    """What goes in the column for this value, or None if it may not be stored.

    A URL field stores the parsed form, so the value and the link are one
    string and no reader has to wonder which of the two a browser would follow.
    A TEXT field stores what was typed.

    None means refuse, and only a URL field can produce it. It is a **422 at
    the write**, which is the half `link_target` cannot do: silently degrading
    a mistyped URL to text would leave somebody looking at a field they
    declared a link and cannot click, with nothing saying why.
    """
    if kind is not CustomFieldKind.URL:
        return value
    return link_target(kind, value)


# ── Definitions, which are Library wide ───────────────────────────────────────


def definitions(db: Session) -> list[CustomField]:
    """Every field this Library has defined, in the order it defined them.

    By `id`, which is insertion order, so a Book lists its fields the same way
    twice and two Books list them in the same order as each other. There is no
    `position` column and no reordering: `MAX_CUSTOM_FIELDS` keeps the list
    short enough that the question does not arise.
    """
    return db.query(CustomField).order_by(CustomField.id).all()


def define(db: Session, name: str, kind: CustomFieldKind) -> CustomField:
    """Define a field, or hand back the one that already has the name.

    **A collision returns the existing row rather than a 409**, which is what
    `create_tag` does and for the same reason: somebody typing a name that is
    already there wants that field, and an error sends them to find it by hand.
    The kind of the existing row is left alone, because changing it would
    reinterpret every value already under it.

    **Folded in Python, never with `func.lower`.** SQLite's `lower()` is ASCII
    only, so `lower('Ähnliches')` is `'Ähnliches'` there and `'ähnliches'`
    here; a stored name with a non ASCII capital would never match and the
    insert would then hit the binary `unique=True` on the column as a 500.
    Measured on `create_tag` before it was fixed, and recorded in
    `docs/decisions.md`. `MAX_CUSTOM_FIELDS` is what makes reading the whole
    table to fold it cheap.

    Refuses past the ceiling. A Book holds at most one value per definition, so
    this is the one number that bounds the feature: see `MAX_CUSTOM_FIELDS`.

    **What this does not close**, named rather than half-done, and both are the
    same shape `Records.open` names for `user_books`. Two concurrent requests
    can both read a Library at 24 fields and both insert, leaving 26; and two
    naming the same field can both find nothing and the second then hits the
    unique index as a 500. Closing either means a savepoint and a re-read on
    conflict, which changes behaviour under a load nobody has reported.
    `create_tag` has carried the identical second exposure since it was
    written.
    """
    rows = definitions(db)
    folded = name.lower()
    existing = next((row for row in rows if row.name.lower() == folded), None)
    if existing is not None:
        return existing
    if len(rows) >= MAX_CUSTOM_FIELDS:
        raise Refused(
            f"This library already has {MAX_CUSTOM_FIELDS} custom fields, "
            "which is the most it can have. Delete one to add another."
        )
    field = CustomField(name=name, kind=kind)
    db.add(field)
    return field


def rename(db: Session, field: CustomField, name: str) -> CustomField:
    """Rename a field. **No value moves**, which is user story 5.

    That is a property of the schema rather than of this function: the values
    reference the definition by id, so the name they are filed under is read
    through the join and never copied into them. A JSON column on `books` is
    the design where this function would have had to rewrite every row.

    **A collision is refused rather than absorbed**, unlike `define`. Renaming
    onto an existing name means merging two definitions, and the two hold
    different values on the same Books: one of them would have to be destroyed,
    silently, by an operation whose whole purpose is not losing any. Its own
    name in a different case is not a collision, so fixing the capitalisation
    of a field is a rename like any other.
    """
    folded = name.lower()
    clash = next(
        (
            row
            for row in definitions(db)
            if row.id != field.id and row.name.lower() == folded
        ),
        None,
    )
    if clash is not None:
        raise Refused(f"This library already has a field called {clash.name}.")
    field.name = name
    return field


def remove(db: Session, field: CustomField) -> int:
    """Delete a field and every value under it. Returns how many values went.

    User story 6. The count goes to the route's **log line** and no further:
    `TagOut.book_count` exists so a confirmation can say "take this off 214
    books", and the equivalent number here cannot be published, for the reason
    in the second paragraph below. The confirmation says "every book" instead,
    which is true and needs no query.

    **The values are deleted here rather than left to the cascade.** SQLite
    enforces a foreign key only while `PRAGMA foreign_keys` is on, which
    `database.py` sets per connection and a migration's connection does not
    have; `delete_tag` clears its association rows by hand for exactly this
    reason. The count is also wanted, and a cascade returns nothing.

    **The count is not scoped to a viewer, and it is not published.** It
    reaches an admin who has just deleted the field, describing rows that no
    longer exist, so it discloses nothing about which Books held them. A count
    of Books that *do* hold a field would be a disclosure, which is why this
    feature does not offer one: see `docs/security.md`.
    """
    removed = (
        db.query(CustomFieldValue).filter(CustomFieldValue.field_id == field.id).delete()
    )
    db.delete(field)
    return int(removed)


# ── Values, which belong to Books somebody already resolved ───────────────────


def values_on(db: Session, book: Book) -> list[Filled]:
    """What this Book holds in the Library's fields, ready to render.

    Takes a `Book`, never an id, and that is the privacy rule: see the module
    docstring.

    Only the fields it has something in. That is user story 4, and the schema
    is what makes it true rather than a filter here: clearing a value deletes
    the row, so a Book with nothing to say about a field has nothing to skip.

    Ordered by `field_id`, so every Book lists its fields in the order the
    Library defined them.

    **One statement**, with the definitions joined on. The obvious
    implementation reads the values and then the name of each field, which is
    one query plus one per row.

    **A function rather than the batching class this started as.** The class
    took a `Sequence[Book]` and loaded a whole page in one statement, and there
    is no caller for that and never will be: these are served by their own
    route rather than on `BookOut`, and `routers/books.py` records why in three
    places. A batch reader with a batch caller refused by design is three
    public names and a test measuring a path nothing runs. If a listing ever
    needs them, the batch belongs back here, still taking Books.
    """
    rows = (
        db.query(CustomFieldValue, CustomField)
        .join(CustomField, CustomField.id == CustomFieldValue.field_id)
        .filter(CustomFieldValue.book_id == book.id)
        .order_by(CustomFieldValue.field_id)
        .all()
    )
    filled: list[Filled] = []
    for row, field in rows:
        kind = _kind_of(field)
        target = link_target(kind, row.value)
        filled.append(
            Filled(
                field=field,
                kind=kind,
                value=row.value,
                # **Only when the target is the value**, which is what makes
                # "value and target are the same string" true of what is
                # served rather than only of what this app writes.
                #
                # The caller renders `value` as the link text and `href` as the
                # destination. A row this app never wrote can carry a value
                # `link_target` **rewrites**, and then the anchor reads as one
                # registrable domain and goes to another:
                # `https://calibre.example\u3002evil.example/x` is stored as
                # typed by `backup.restore`, which inserts through Core with no
                # validator, and rewrites to `calibre.example.evil.example`.
                # That is the sharpest form of the phishing case, produced by
                # the rewrite that fixes it at the write end.
                #
                # **Free, because `link_target` is idempotent**: measured over
                # twelve accepted inputs including a case folded scheme, a
                # dropped empty query and a dropped empty fragment,
                # `link_target(link_target(x)) == link_target(x)` every time.
                # So a row this app wrote always passes this test and keeps its
                # link; only a row it did not write can fail it.
                href=target if target == row.value else None,
            )
        )
    return filled


def write(
    db: Session, book: Book, field: CustomField, value: str
) -> CustomFieldValue | None:
    """Set this Book's value for one field, or clear it with an empty string.

    Returns the row, or None when the value was cleared and there is no row.

    **An empty value is a delete, not an empty row**, which is what keeps user
    story 4 a property of the schema: `ck_custom_field_values_bounds` refuses a
    zero length value, so there is no way to store a field that renders as
    nothing. Clearing a field nobody had filled in is not an error: it is the
    state the caller asked for.

    **Refuses a URL that is not one**, with the reason in the exception. See
    `_stored_form`.

    Takes a `Book`, so the caller has already resolved one. The route that
    calls this asks for `BookForWrite`, which is the app's ordinary write rule:
    a Public Book is a shared shelf any member may curate, and a Private one
    never reaches the dependency unless it is the caller's own.
    """
    kind = _kind_of(field)
    row = (
        db.query(CustomFieldValue)
        .filter(
            CustomFieldValue.book_id == book.id,
            CustomFieldValue.field_id == field.id,
        )
        .one_or_none()
    )

    if not value:
        if row is not None:
            db.delete(row)
        return None

    stored = _stored_form(kind, value)
    if stored is None:
        raise Refused(
            f"{field.name} holds a link, so it needs a web address: http:// or "
            "https://, with a host and no username or password in it."
        )

    if row is None:
        row = CustomFieldValue(book_id=book.id, field_id=field.id, value=stored)
        db.add(row)
    else:
        row.value = stored
    return row


def resolve_merge(db: Session, keeper_id: int, loser_ids: Collection[int]) -> None:
    """Fold the losing Books' values into the keeper when two Books turn out to
    be one.

    **Not scoped to a Book anybody is holding**, and it cannot be: the merge
    deletes the losing rows, the cascade takes their values with them, and the
    Library silently loses what it typed on the Book that lost. Classifications,
    notes, quotes and reading records are all moved across in
    `routers/books.py::_repoint_relations` for the same reason, and every one of
    them is there because leaving it out destroyed something quietly.

    The values cannot simply move: `(book_id, field_id)` is unique, so a field
    filled in on two of the merged Books would violate it. **The keeper's own
    value wins and the duplicate is dropped**, because that is the value
    attached to the Book that continues to exist. Among losers, the lowest id
    wins, which is the same tie break `_repoint_relations` uses for
    classifications.

    Built to be called before the flush, so it reads what is in the database
    rather than what the caller has already repointed.
    """
    ids = frozenset(loser_ids)
    if not ids:
        return
    taken = {
        row.field_id
        for row in db.query(CustomFieldValue).filter(
            CustomFieldValue.book_id == keeper_id
        )
    }
    for row in (
        db.query(CustomFieldValue)
        .filter(CustomFieldValue.book_id.in_(ids))
        .order_by(CustomFieldValue.id)
        .all()
    ):
        if row.field_id in taken:
            db.delete(row)
        else:
            row.book_id = keeper_id
            taken.add(row.field_id)
