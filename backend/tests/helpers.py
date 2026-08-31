"""Helpers shared across the suite.

Kept out of conftest.py so test modules can import them directly. conftest is
loaded by pytest for its fixtures, and importing from it is fragile under the
importlib import mode this suite uses.
"""

import re
from types import SimpleNamespace
from typing import Any

import httpx

import auth_backends

# ── Image payloads ────────────────────────────────────────────────────────────
#
# Uploads are identified by their leading bytes, not by the filename, so a test
# payload has to carry a real magic number. These are the shortest byte strings
# each sniffer accepts.

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 8
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8

# Passes any extension check but is not an image. Used to prove the sniffer,
# not the filename, is what decides, and specifically that an SVG (which can
# carry script, and would be served from our own origin) is turned away.
NOT_AN_IMAGE = b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"


def selects_for(client: Any, headers: dict[str, str], url: str) -> tuple[int, int]:
    """The SELECTs one request issues, and the `total` it answered with.

    The total comes back with the count so a cost met by answering with nothing
    cannot pass for a cheap page.

    **One function, two callers**: `tests/routers/test_loans.py` for the two loan
    pages and `tests/routers/test_books.py` for the books listing. It was written
    in the loans file first and copied here for one wave, while the two files
    belonged to different seats; the copy is gone and both import this.

    Every caller asserts an **exact** count at two page lengths rather than a
    ceiling, and that is the reason this returns the total as well: a smaller
    count is a weaker inequality, so a ceiling goes on passing with an eager load
    deleted, and a cost met by answering with nothing looks like a cheap page.
    """
    from sqlalchemy import event

    from database import engine

    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        body = client.get(url, headers=headers).json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    selects = [row for row in statements if row.lstrip().upper().startswith("SELECT")]
    return len(selects), body["total"]


def items(response: httpx.Response) -> list[Any]:
    """Unwrap a paginated response body.

    Listing endpoints return a `Page` envelope rather than a bare array, so
    tests read the rows through this instead of indexing the body.
    """
    return list(response.json()["items"])


def total(response: httpx.Response) -> int:
    """The filtered row count from a paginated response, not the page length."""
    return int(response.json()["total"])


def titles(response: httpx.Response) -> list[str]:
    """Book titles from a paginated listing, in the order returned."""
    return [book["title"] for book in items(response)]


# ── Metadata catalogues ───────────────────────────────────────────────────────
#
# Seven sources answer a lookup or a search, and respx fails a test that makes
# an unmocked request rather than letting it reach the real service. So a test
# touching either path has to silence all seven, and stating them one by one in
# every test was both noise and a trap: adding a source broke thirty tests in
# an unrelated file.

OPEN_LIBRARY = "https://openlibrary.org/"
#: The two image services. Separate hosts from the catalogues, and reached on
#: every successful lookup now that a cover is checked before it is stored.
OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org/"
DNB_COVERS = "https://portal.dnb.de/opac/mvb/cover"
OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"
DNB = "https://services.dnb.de/sru/dnb"
K10PLUS = "https://sru.k10plus.de/opac-de-627"
BNF = "https://catalogue.bnf.fr/api/SRU"
LOC = "http://lx2.loc.gov:210/lcdb"
OENB = "https://obv-at-oenb.alma.exlibrisgroup.com/view/sru/43ACC_ONB"
NLG = "http://catalogue.nlg.gr:210/biblios"

#: An SRU envelope holding no records. Every SRU source answers 200 with an
#: empty set rather than a 404, so mocking a 404 would test a case none of them
#: produces.
SRU_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">
 <zs:numberOfRecords>0</zs:numberOfRecords><zs:records/>
</zs:searchRetrieveResponse>
"""


def sru_response(body: str = SRU_EMPTY) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/xml"})


def silence_covers(mock: Any) -> Any:
    """Answer both image services with "no cover for that ISBN".

    Separate from `silence_catalogues` because a fixture usually wants this and
    not that: `silence_catalogues` registers a catch-all for Google Books, and
    a fixture calling it would shadow a Google response the test registers in
    its own body, since routes resolve in registration order and a fixture runs
    first. That is the same trap its docstring describes, in reverse.

    A cover is checked before it is stored now, so every successful lookup
    reaches these hosts and an unstubbed test fails on the request.
    """
    for base in (OPEN_LIBRARY_COVERS, DNB_COVERS):
        mock.get(url__regex=f"{re.escape(base)}.*").mock(
            return_value=httpx.Response(404)
        )
    return mock


def silence_oenb(mock: Any) -> Any:
    """Answer the ÖNB with "nothing found".

    A helper of its own rather than a line in every test, because it was added
    to a module whose tests each register their sources by hand: the ÖNB joined
    a lookup chain and a search fan-out that 21 existing tests already pinned,
    and every one of them failed on an unmocked request rather than on anything
    about the ÖNB.

    **Not autouse, deliberately.** A fixture registering this for every test
    would also register it for the tests that exist to watch the ÖNB answer,
    and respx resolves routes in registration order with the first match
    winning, so those would have silently tested nothing.
    """
    mock.get(url__regex=f"{re.escape(OENB)}.*").mock(return_value=sru_response())
    return mock


def silence_nlg(mock: Any) -> Any:
    """Answer the National Library of Greece with "nothing found".

    `silence_oenb`'s helper, one source later and for the same reason: the NLG
    joined a lookup chain and a search fan out that existing tests already
    pinned, and each of those would fail on an unmocked request rather than on
    anything about the NLG.

    **Not autouse**, for `silence_oenb`'s reason.
    """
    mock.get(url__regex=f"{re.escape(NLG)}.*").mock(return_value=sru_response())
    return mock


def silence_open_library(mock: Any) -> Any:
    """Answer the whole Open Library host with "nothing found".

    A helper of its own for `silence_oenb`'s reason, one reorder later. #115 put
    Open Library ahead of the OENB in `sources.DEFAULT_ORDER`, so every test that
    watches the OENB answer an **ISBN lookup** now passes through Open Library
    first, and seven of them failed on an unmocked request rather than on
    anything about the OENB.

    **It answers for the whole host, search included, and not only the record
    endpoint.** The pattern is `openlibrary.org/` and anything after it, so it
    covers `/isbn/*.json` and `/search.json` alike. Every caller today is an ISBN
    lookup test, and a test that wants Open Library's **search** to answer must
    register its own route **before** calling this: respx resolves in
    registration order and the first match wins, so a search route added
    afterwards is unreachable and the test silently passes on a 404.

    **Not the cover host**, which `silence_covers` owns. `covers.openlibrary.org`
    does not start with `openlibrary.org`, so those two patterns are disjoint and
    neither shadows the other whichever is registered first. That is a narrower
    claim than it looks and it is the only one made here.

    **Not autouse**, for `silence_oenb`'s reason: a fixture registering this for
    every test would also register it for the tests that exist to watch Open
    Library answer, and respx resolves in registration order.
    """
    mock.get(url__regex=f"{re.escape(OPEN_LIBRARY)}.*").mock(
        return_value=httpx.Response(404)
    )
    return mock


def silence_catalogues(mock: Any) -> Any:
    """Register a "nothing found" answer for every metadata source.

    **Call this last**, after any source the test wants to answer.

    Two respx behaviours make that the rule, and getting either wrong fails
    silently rather than loudly:

    * Routes resolve in registration order and the **first match wins**, so a
      route added after a catch-all is unreachable.
    * A route whose pattern is **equal** to an existing one **replaces** it
      rather than being appended. So these are written as regexes: a test
      registering `url__startswith=GOOGLE_BOOKS` and this registering the same
      pattern left one route, this one, and the test's own Google response was
      silently discarded.
    """
    for base in (DNB, K10PLUS, BNF, LOC, OENB, NLG):
        mock.get(url__regex=f"{re.escape(base)}.*").mock(return_value=sru_response())
    silence_covers(mock)
    mock.get(url__regex=f"{re.escape(OPEN_LIBRARY)}.*").mock(
        return_value=httpx.Response(404)
    )
    mock.get(url__regex=f"{re.escape(GOOGLE_BOOKS)}.*").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    return mock


# ── Fake LDAP directory ───────────────────────────────────────────────────────
#
# Shared by tests/test_auth_backends.py, which drives the backend directly, and
# tests/routers/test_auth.py, which drives the same backend through the HTTP
# routes. One fake rather than two: a second copy would be a second answer to
# "what does this directory do", and the two would disagree eventually.
#
# What is worth pinning here is our own logic (the empty-password guard, filter
# escaping, shadow accounts, admin group mapping), not ldap3's ability to speak
# LDAP.


class FakeEntry:
    """An ldap3 entry, as much of one as `authenticate_ldap` touches.

    `email=None` is an entry with no such attribute at all, and `email=""` is
    the attribute present and empty. ldap3 gives those two different shapes,
    `item in entry` being False for the first and `.value` being None for the
    second, and the app has to reduce both to "the directory named no address".
    """

    def __init__(
        self,
        dn: str,
        username: str,
        groups: list[str],
        attribute: str = "uid",
        email: str | None = None,
        email_attribute: str = "mail",
    ):
        self.entry_dn = dn
        self._username = username
        self._attribute = attribute
        self.memberOf = SimpleNamespace(values=groups)
        self._has_groups = bool(groups)
        self._email = email
        self._email_attribute = email_attribute

    def __contains__(self, item: str) -> bool:
        if item == "memberOf":
            return self._has_groups
        return item == self._email_attribute and self._email is not None

    def __getitem__(self, item: str) -> SimpleNamespace:
        if item == self._attribute:
            return SimpleNamespace(value=self._username)
        if item == self._email_attribute and self._email is not None:
            return SimpleNamespace(value=self._email or None)
        raise KeyError(item)


class FakeConnection:
    """Stands in for an ldap3 Connection.

    `bind_results` is consumed in order: the first bind is the service account
    searching, the second is the member proving their password.
    """

    def __init__(self, *, bind_results: list[bool], entries: list[FakeEntry]):
        self._bind_results = list(bind_results)
        self.entries: list[FakeEntry] = []
        self._available = entries
        self.result = "fake"
        self.searched_filter: str | None = None
        #: What the search asked the directory for. Recorded because the
        #: shipped default must not add an attribute to it: a test asserting
        #: only the stored address would pass while every deployment's search
        #: had quietly grown a field.
        self.searched_attributes: list[str] | None = None

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def bind(self) -> bool:
        return self._bind_results.pop(0) if self._bind_results else False

    def search(self, search_base: str, search_filter: str, attributes: list[str]) -> None:
        self.searched_filter = search_filter
        self.searched_attributes = list(attributes)
        self.entries = self._available


def install_directory(monkeypatch, connections: list[FakeConnection]) -> list[FakeConnection]:
    """Hand out the given connections, in order, to each _connect() call."""
    handed_out: list[FakeConnection] = []
    queue = list(connections)

    def fake_connect(user: str | None = None, password: str | None = None) -> FakeConnection:
        connection = queue.pop(0)
        connection.bound_as = (user, password)  # type: ignore[attr-defined]
        handed_out.append(connection)
        return connection

    monkeypatch.setattr(auth_backends, "_connect", fake_connect)
    return handed_out


def directory_with(
    monkeypatch,
    *,
    groups: list[str] | None = None,
    user_bind: bool = True,
    email: str | None = None,
    email_attribute: str = "mail",
):
    entry = FakeEntry(
        "uid=kim,ou=people,dc=example,dc=org",
        "kim",
        groups or [],
        email=email,
        email_attribute=email_attribute,
    )
    return install_directory(
        monkeypatch,
        [
            FakeConnection(bind_results=[True], entries=[entry]),
            FakeConnection(bind_results=[user_bind], entries=[]),
        ],
    )


def proxy_headers(username: str, groups: str | None = None) -> dict[str, str]:
    """The headers an upstream proxy sets to assert who the caller is.

    Spelled by `config` rather than written out, so a test does not keep
    passing against a header name the app no longer reads.
    """
    from config import proxy_groups_header, proxy_user_header

    headers = {proxy_user_header(): username}
    if groups is not None:
        headers[proxy_groups_header()] = groups
    return headers


def enable_google_books(db: Any, key: str = "a-test-key") -> None:
    """Switch Google Books on and give it a key, so it is actually asked.

    **Both, because either alone leaves it unasked**, and that is the point
    rather than a setup detail. `settings_store.catalogue_sources` conjoins the
    provider list with whether a source can answer, so a test that mocks
    `googleapis.com` and never sets these gets no request at all.

    Four tests needed this when the conjunction arrived, and every one of them
    had been passing on the defect: they asserted that a lookup falls back to
    Google **with the feature switched off and no key stored**, which is exactly
    the request that should never have been made. Two review seats found that
    hole independently. The tests still assert the fallback; they now configure
    the source first, which is what a library that wants the fallback does.
    """
    import settings_store
    from enums import SettingKey

    settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_ENABLED, "true")
    settings_store.set_value(db, SettingKey.GOOGLE_BOOKS_API_KEY, key)
