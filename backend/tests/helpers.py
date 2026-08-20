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
# Six sources answer a lookup or a search, and respx fails a test that makes an
# unmocked request rather than letting it reach the real service. So a test
# touching either path has to silence all six, and stating them one by one in
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
    for base in (DNB, K10PLUS, BNF, LOC):
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
    def __init__(self, dn: str, username: str, groups: list[str], attribute: str = "uid"):
        self.entry_dn = dn
        self._username = username
        self._attribute = attribute
        self.memberOf = SimpleNamespace(values=groups)
        self._has_groups = bool(groups)

    def __contains__(self, item: str) -> bool:
        return item == "memberOf" and self._has_groups

    def __getitem__(self, item: str) -> SimpleNamespace:
        if item == self._attribute:
            return SimpleNamespace(value=self._username)
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

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def bind(self) -> bool:
        return self._bind_results.pop(0) if self._bind_results else False

    def search(self, search_base: str, search_filter: str, attributes: list[str]) -> None:
        self.searched_filter = search_filter
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


def directory_with(monkeypatch, *, groups: list[str] | None = None, user_bind: bool = True):
    entry = FakeEntry("uid=kim,ou=people,dc=example,dc=org", "kim", groups or [])
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
