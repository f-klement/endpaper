"""The privacy rule at the wire: a private Book is never **sent**.

`tests/test_shelf.py` holds two rules about how a Book is fetched and one about
the type it is carried in. This file asks the only question a reader outside
this process can ask, which is what actually came back, and it asks it of every
route the application answers without a member.

**Why "never sent" rather than "never shown".** A client that hides a private
Book is one copy of the privacy rule per client, including clients written
against this API by people this project has never met and cannot correct. A
payload that does not contain the Book needs no client to cooperate. That is
the answer #119 settled, and it is worth something only because it is checkable
at a boundary, which is what this file is.

**The route set is derived, not listed.** A route is swept unless FastAPI
resolves a member somewhere in its dependency tree, so a route that becomes
reachable without a session is swept the day it becomes so, whether or not
anybody remembered this file existed. `UNAUTHENTICATED` pins that set with a
reason per route, so a route joining or leaving it is a decision rather than an
edit.

**What this cannot see**, stated because a sweep that looks thorough is read as
one that is:

* **Anything leaving by something other than a route.** The digest mailer sends
  titles to members, a backup file carries every row deliberately, and a
  catalogue lookup sends an ISBN to a third party. None is an HTTP response and
  none is swept here.
* **Anything that is not an `APIRoute`.** `iter_api_routes` yields those alone,
  so a raw Starlette route and the SPA's `StaticFiles` mount are invisible both
  to the sweep and to `test_the_route_set_is_the_pinned_one`. The mount is not
  present in this process at all, which is why nothing here would notice if it
  began serving something.
* **A route the driver cannot exercise.** A POST needing a body answers 422 and
  proves nothing about what it would have sent. `CARRIES_BOOKS` is the record
  of which calls were shown to reach Book data at all, asserted by equality, so
  a call that stops reaching it has to be explained rather than silently joining
  the vacuous half.
* **A shape no probe has.** `PROBES` is a handful of query strings, so a route
  wanting a shape none of them has is driven but not searched. That is the one
  enumeration in this file and it is the reason `CARRIES_BOOKS` is asserted
  rather than assumed. The count is deliberately not written here: it was wrong
  within an hour of being written, because the probes were still being cut.
* **Disclosure that is not a string.** How many records an SRU response reports,
  a gap in the published ids, how long a request took. `schemas/public.py`
  records the id gap as known and accepted.
* **A row this file does not mark.** What carries a marker is every free text
  column on `books`, derived from the table, plus one row each in `tags`,
  `classifications`, `notes`, `quotes` and `custom_field_values`. **Everything
  else does not**: no `loans` row, no `user_books` row, no `reading_progress`
  row, and no integer, date or boolean anywhere. A route serving one of those
  for a private Book passes this sweep, and the fixture marking five related
  tables is what would otherwise read as covering all of them.
"""

import re
from typing import cast, get_args, get_type_hints

import pytest
from sqlalchemy import CheckConstraint, String, Table, Text

import settings_store
from auth import get_current_user, get_current_user_for_cover
from enums import (
    ClassificationScheme,
    CustomFieldKind,
    SettingKey,
    TagCategory,
)
from main import app, iter_api_routes
from models import (
    Book,
    Classification,
    CustomField,
    CustomFieldValue,
    Note,
    Quote,
    Tag,
)
from tests.conftest import auth_header

#: A string that occurs in no fixture, no seeded tag and no real library.
#:
#: **Ten characters, and the length is load bearing.** At eleven it did not fit
#: `books.language`, which is `String(10)`, so that column was silently dropped
#: from the marked set while this file claimed to mark every free text column.
#: `test_the_only_column_too_short_for_the_marker_is_the_currency` is what says
#: so now, derived from the table rather than from this comment. No substring of
#: it is a word, so a match is this marker rather than a collision.
MARKER = "ZQPRIVATEQ"

#: The same, for the Book a reader with no account is entitled to see.
#:
#: The sweep's own control: a driver that finds neither marker anywhere is a
#: driver inspecting nothing, and this is the one it must find.
PUBLIC_MARKER = "ZQPUBLICQZ"

#: A word both Books carry, and the whole point of the probes below.
#:
#: A search for it is a question whose correct answer is the public Book and not
#: the private one, asked of every route that searches anything. A term unique to
#: the private Book would be a weaker question: any route returning it for the
#: shared term returns it for a private one too, and the shared term also catches
#: a route that filters the query and forgets the shelf.
SHARED_TERM = "catalogued"

#: Query strings applied to every call, rather than one per route.
#:
#: **Breadth is derived and depth is enumerated, and the split is deliberate.**
#: Which routes exist comes from the app; what to ask them cannot, because a
#: protocol like SRU has a shape no generic driver would guess. Applying every
#: probe to every call keeps this from becoming a table of per route knowledge,
#: which is what goes stale.
#:
#: The SRU probe is here because the bare route answers `explain`, which carries
#: no records at all: without it `/sru` is a 200 that proves nothing, which is
#: what the first measurement of this sweep showed.
#:
#: **No probe carries either marker**, deliberately. A server that echoed the
#: request back, which SRU diagnostics come close to doing, would put the string
#: in the response without ever having read a Book, and this file would report a
#: leak that was the caller's own input coming home.
PROBES: tuple[str, ...] = (
    "",
    f"q={SHARED_TERM}",
    f"operation=searchRetrieve&query={SHARED_TERM}",
)

#: Every call this application answers with no member resolved, and why.
#:
#: **Asserted by equality, never as a subset.** A subset check forgives a route
#: that has just stopped requiring a session, which is the only change this
#: table exists to catch.
UNAUTHENTICATED: dict[str, str] = {
    "GET /api/healthz": "liveness, and it reads no table",
    "GET /api/public/books": "the published catalogue, gated by the publish switch",
    "GET /api/public/books/{book_id}": "one published record, 404 for every other reason",
    "GET /api/settings/features": "which features the sign in page may offer",
    "GET /api/settings/login-image": "the sign in background, chosen by an admin",
    "GET /auth/config": "which auth mode this deployment runs, before a session exists",
    "POST /auth/login": "the route that creates a session",
    "POST /auth/logout": "discards a token, and a caller with none has nothing to prove",
    "POST /auth/register": "the route that creates an account",
    # The four recovery routes. Each is reachable without a session because a
    # member who could sign in would not need it, and each answers the same
    # whatever it found, so none is a roster. See `backend/accounts.py`.
    "POST /auth/reset/request": (
        "a member with no session asking an admin to approve a reset"
    ),
    "POST /auth/reset/redeem": (
        "spending an approved code on a new password, which issues no session"
    ),
    "POST /auth/verify/request": "sending a confirmation code to an address again",
    "POST /auth/verify": (
        "returning the confirmation code, which settles the account and issues "
        "no session"
    ),
    "GET /covers/login_bg.{extension}": "the sign in background's bytes",
    "GET /robots.txt": "what a crawler is told, which must answer either way",
    "GET /sru": "the SRU base URL, gated by the same publish switch",
    "DELETE /api/{rest:path}": "the API's own 404, so an unknown path is not the SPA",
    "GET /api/{rest:path}": "the same",
    "PATCH /api/{rest:path}": "the same",
    "POST /api/{rest:path}": "the same",
    "PUT /api/{rest:path}": "the same",
    "DELETE /auth/{rest:path}": "the same, under the auth prefix",
    "GET /auth/{rest:path}": "the same",
    "PATCH /auth/{rest:path}": "the same",
    "POST /auth/{rest:path}": "the same",
    "PUT /auth/{rest:path}": "the same",
}

#: The calls the sweep was shown to reach Book data through.
#:
#: **This is the anti vacuity half and it is the reason the sweep means
#: anything.** Every assertion below is an absence, and an absence is what a
#: broken driver, an unpublished catalogue and a route that 404s all produce.
#: These are the calls where the public Book's marker came back, so they are the
#: calls where the private Book's absence is a refusal rather than an empty
#: response.
CARRIES_BOOKS: frozenset[str] = frozenset(
    {
        "GET /api/public/books",
        "GET /api/public/books/{book_id}",
        "GET /sru",
    }
)


def _free_text_columns() -> list[str]:
    """Every column on `books` a marker can be written to, derived from the table.

    **Stated as the exclusion**, because an inclusion list goes stale the day
    the model grows a column, and the column somebody adds next is exactly the
    one a payload will carry.

    Excluded, each for a reason read off the table rather than remembered:

    * anything that is not a string, since a marker is one;
    * a column named in a CHECK constraint, where a marker is refused by the
      database. **One column, `ownership`**, and writing the other three enum
      backed columns into this bullet is the mistake this sentence exists to
      stop repeating: they have no constraint and this rule never saw them;
    * a column whose **mapped Python type** is not `str`, which is what actually
      excludes `format`, `lending` and `condition`. All three are a `String` in
      the database and an enum in Python, so a marker is stored happily and then
      fails `BookOut` validation on the owner's own read, turning the control in
      `TestTheSweepWouldNotice` into a 500 rather than a finding;
    * a column shorter than the marker, which today is `purchase_currency`
      alone, asserted below rather than stated here;
    * a key, whose value is an identity rather than content.
    """
    table = cast(Table, Book.__table__)
    constrained = {
        column.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        for column in table.columns
        if re.search(rf"\b{re.escape(column.name)}\b", str(constraint.sqltext))
    }
    hints = get_type_hints(Book)
    names = []
    for column in table.columns:
        if not isinstance(column.type, String | Text):
            continue
        if column.primary_key or column.foreign_keys or column.name in constrained:
            continue
        length = getattr(column.type, "length", None)
        if length is not None and length < len(MARKER):
            continue
        # `Mapped[str | None]` and not `Mapped[BookFormat | None]`. See above.
        mapped = get_args(hints.get(column.name))
        inner = mapped[0] if mapped else None
        if str not in (set(get_args(inner)) or {inner}):
            continue
        names.append(column.name)
    return names


def _publish(db) -> None:
    """Both switches on, so the catalogue answers rather than 404ing.

    The sweep is worth nothing against a deployment publishing nothing: every
    catalogue route would answer 404 and the marker would be absent for a reason
    that has nothing to do with privacy.
    """
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
    settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")
    settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED, "true")


@pytest.fixture
def marked(db, admin, member):
    """One private Book marked in every free text column, and one public Book.

    The private Book belongs to a **different** member from the admin, so an
    ownership arm reintroduced by accident would have somebody to match.

    **Five related rows carry the marker as well as the columns**, because the
    Book is not the only thing a route can serve: a Tag and a Classification,
    since a name or a call number existing only on a private Book is the
    disclosure `list_tags` once made without ever returning the Book, and a
    Note, a Quote and a custom field value, which are the three tables whose
    whole content is a member's own words about a Book. Which rows are **not**
    marked is on the module docstring, because that is the part a reader would
    otherwise assume.
    """
    columns = cast(Table, Book.__table__).columns
    private = Book(added_by_user_id=member["user"]["id"], is_private=True)
    for name in _free_text_columns():
        limit = getattr(columns[name].type, "length", None) or 200
        setattr(private, name, f"{MARKER} {SHARED_TERM} {name}"[:limit])
    private.tags = [Tag(name=f"{MARKER} tag", category=TagCategory.CUSTOM)]
    private.classifications = [
        Classification(
            scheme=ClassificationScheme.DDC, number="823", label=f"{MARKER} label"
        )
    ]
    private.notes = [Note(user_id=member["user"]["id"], content=f"{MARKER} note")]
    private.quotes = [
        Quote(user_id=member["user"]["id"], text=f"{MARKER} quote", page=7)
    ]
    field = CustomField(name=f"{MARKER} field", kind=CustomFieldKind.TEXT)
    db.add(field)
    db.flush()
    private.custom_field_values = [
        CustomFieldValue(field_id=field.id, value=f"{MARKER} value")
    ]

    public = Book(
        title=f"{PUBLIC_MARKER} {SHARED_TERM} title",
        author=f"{PUBLIC_MARKER} author",
        added_by_user_id=admin["user"]["id"],
    )
    db.add_all([private, public])
    db.commit()
    db.refresh(private)
    db.refresh(public)
    _publish(db)
    return {"private": private.id, "public": public.id}


def _resolves_a_member(dependant) -> bool:
    """Whether FastAPI will have a `User` in hand before this route's handler runs.

    Asked of the **resolved dependency tree** rather than of the source, because
    what protects a route is what FastAPI resolved and not the decorator
    somebody meant to write. `tests/routers/test_public.py` records the same
    choice for the publish gate.
    """
    if dependant.call in {get_current_user, get_current_user_for_cover}:
        return True
    return any(_resolves_a_member(sub) for sub in dependant.dependencies)


def _calls() -> list[str]:
    """Every `METHOD path` this application answers with no member resolved.

    `HEAD` and `OPTIONS` are folded away: FastAPI answers both from the `GET`
    that is already swept, and neither carries a body of its own.
    """
    return sorted(
        {
            f"{method} {route.path}"
            for route in iter_api_routes(app.routes)
            if not _resolves_a_member(route.dependant)
            for method in route.methods or ()
            if method not in {"HEAD", "OPTIONS"}
        }
    )


def _drive(client, call: str, probe: str, book_id: int):
    """One request, with every path parameter filled by the same book id.

    Uniform substitution rather than a table of parameter names: a table is a
    list of what somebody has seen, and the next parameter is the one it does
    not have. A path that comes out meaningless answers 404 or 422, which is
    what `CARRIES_BOOKS` exists to make visible rather than to hide.
    """
    method, path = call.split(" ", 1)
    url = re.sub(r"\{[^}]+\}", str(book_id), path)
    if probe:
        url = f"{url}?{probe}"
    return client.request(method, url)


def _seen(client, call: str, marked: dict, marker: str) -> bool:
    """Whether a marker came back from any probe of one call, for either Book id.

    Headers as well as the body: a marker reaching a `Location`, an `ETag` or a
    filename is as sent as one in the payload.
    """
    for probe in PROBES:
        for book_id in (marked["private"], marked["public"]):
            response = _drive(client, call, probe, book_id)
            headers = " ".join(f"{k}: {v}" for k, v in response.headers.items())
            if marker in response.text or marker in headers:
                return True
    return False


class TestNothingPrivateLeavesByARoute:
    """The sweep itself, one case per call, over the derived route set."""

    @pytest.mark.parametrize("call", _calls())
    def test_no_probe_returns_a_private_book(self, client, marked, call):
        assert not _seen(client, call, marked, MARKER), (
            f"{call} returned a private Book's data to a caller with no "
            "session. A private Book never leaves this instance: it is absent "
            "from the payload rather than redacted in it, because a stripped "
            "row still says the Book is there and lets a stranger count them. "
            "Rows for a reader this instance cannot name come from "
            "`Shelf.seen_by_the_public(db).outbound_page(...)`."
        )

    def test_there_are_calls_to_sweep(self):
        """A guard that inspects nothing reads as coverage. This fails if
        `iter_api_routes` or the dependency walk stops understanding the route
        layout, which is how the first version of the operation id check in
        `main.py` passed while testing nothing."""
        assert len(_calls()) >= 10

    def test_the_route_set_is_the_pinned_one(self):
        """The value the sweep reads, pinned where the sweep cannot see it move.

        The sweep covers whatever this set contains, so it cannot notice the set
        itself changing: a route that stops requiring a session is swept and
        passes, and nothing says a stranger can now reach it. This is what says
        so.
        """
        assert set(_calls()) == set(UNAUTHENTICATED), (
            "The set of calls answered with no member has changed. Added: "
            f"{sorted(set(_calls()) - set(UNAUTHENTICATED))}. Gone: "
            f"{sorted(set(UNAUTHENTICATED) - set(_calls()))}. Each one is a "
            "surface a stranger reaches, so each needs a line here saying why "
            "it needs no session."
        )


class TestTheSweepWouldNotice:
    """The controls. Every assertion above is an absence, and an absence is
    also what a broken driver produces."""

    def test_the_calls_that_reach_a_book_are_the_pinned_ones(self, client, marked):
        """The public Book's marker, through the same driver and the same probes.

        Asserted by equality in both directions: a call dropping out of this set
        has gone quietly vacuous, and one joining it is a new surface carrying
        Book data.
        """
        reaching = {call for call in _calls() if _seen(client, call, marked, PUBLIC_MARKER)}
        assert reaching == set(CARRIES_BOOKS), (
            f"Calls now reaching Book data: {sorted(reaching)}, pinned as "
            f"{sorted(CARRIES_BOOKS)}. A call that has left the set is one "
            "whose absence of a private Book now proves nothing."
        )

    def test_the_private_book_is_there_to_be_leaked(self, client, marked, member):
        """The other control, and the one that decides whether the sweep is
        about privacy at all.

        The marker has to be discoverable somewhere, or its absence above says
        only that the fixture wrote nothing. Its owner sees it, which is what
        `is_private` means: visible to the account that added it, and to nobody
        else.
        """
        response = client.get(
            f"/api/books/{marked['private']}", headers=auth_header(member["access_token"])
        )
        assert response.status_code == 200
        assert MARKER in response.text

    def test_another_member_is_refused_the_same_book(self, client, marked, admin):
        """The diagonal. Without it the control above would pass on a
        deployment where every Book is visible to everybody."""
        response = client.get(
            f"/api/books/{marked['private']}", headers=auth_header(admin["access_token"])
        )
        assert response.status_code == 404
        assert MARKER not in response.text


class TestTheMarkedColumns:
    """What the fixture writes, and why the rest is left alone."""

    def test_the_marked_columns_are_derived_from_the_table(self):
        """Not a list. A text column added to `books` tomorrow is marked without
        anybody editing this file, which is the whole reason the derivation is
        worth its lines."""
        marked = set(_free_text_columns())
        assert {"title", "author", "description", "isbn", "location"} <= marked
        assert len(marked) >= 10

    def test_the_closed_vocabularies_are_excluded_and_stay_excluded(self):
        """The four enum backed columns.

        **Only one of the four has a CHECK constraint**, so a rule reading the
        database alone lets three through, and a marker in `format` is stored
        without complaint and then fails `BookOut` validation on the owner's own
        read: the control below turns into a 500 rather than a finding.
        Measured, and it is why the mapped Python type is read as well as the
        table.
        """
        marked = set(_free_text_columns())
        assert marked.isdisjoint({"format", "lending", "condition", "ownership"})

    def test_the_only_column_too_short_for_the_marker_is_the_currency(self):
        """**The complement, derived, rather than one membership.**

        A column too short holds a truncated marker that no assertion can ever
        match, so it is vacuous rather than failing, and nothing says it left.
        That is not hypothetical: at eleven characters the marker did not fit
        `language`, `String(10)`, and this file went on claiming to mark every
        free text column. Asserting one name would not have caught it; asserting
        the whole short set does.
        """
        table = cast(Table, Book.__table__)
        too_short = {
            column.name
            for column in table.columns
            if isinstance(column.type, String | Text)
            and not column.primary_key
            and not column.foreign_keys
            and (getattr(column.type, "length", None) or 10**6) < len(MARKER)
        }
        assert too_short == {"purchase_currency"}, (
            f"{sorted(too_short)} are too short to hold the marker, so the "
            "sweep cannot see a leak through them. Shorten MARKER, or say here "
            "which column is being given up and why."
        )
