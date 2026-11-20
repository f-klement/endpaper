"""Tests for narrowing one lookup or search, the `only` parameter on backend/routers/books.py.

A cataloguer in library mode may ask fewer catalogues for one request. The standing
provider list is the institution's policy, so a narrowing can only take sources away:
these pin that a left out source is not contacted, on the transport rather than on the
merged answer, and that a name outside the policy is refused rather than dropped.

Every outbound call is intercepted with respx.
"""

import httpx
import pytest
import respx

import ratelimit
import settings_store
import sources
import z3950
from enums import CatalogueSource, SettingKey
from tests.helpers import (
    AT_DNB_COVERS,
    AT_OPEN_LIBRARY_COVERS,
    BNF,
    K10PLUS,
    silence_catalogues,
)

GERMAN_ISBN = "9783960092353"


def library_mode(db) -> None:
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")


def switched_off(client, admin, off: CatalogueSource) -> None:
    client.put(
        "/api/settings",
        json={
            "catalogue_sources": [
                {"source": source.value, "enabled": source is not off} for source in sources.DEFAULT_ORDER
            ]
        },
        headers=admin["headers"],
    )


class _RecordingZ3950Client:
    """Records every association asked for and refuses it, as the suite's own refusal does."""

    def __init__(self) -> None:
        self.hosts: list[str] = []

    def open(self, target: z3950.Target, *, timeout: float) -> z3950.Session:
        self.hosts.append(target.host)
        raise z3950.Unreachable("recorded, not opened")


@pytest.fixture
def z3950_opens(monkeypatch) -> list[str]:
    """The hosts every Z39.50 association was asked of, which respx cannot see."""
    recorder = _RecordingZ3950Client()
    monkeypatch.setattr(z3950, "_default_client", lambda: recorder)
    return recorder.hosts


def contacted_besides(mock: respx.MockRouter, named: str) -> list[str]:
    """Every catalogue URL asked over HTTP that is not under `named`.

    **Read inside the `with` block.** Leaving it rolls the router back and clears
    its call list, so read after, this answers empty whatever was asked.

    The image hosts are left out: a cover is fetched whatever the plan, so they
    are not a catalogue a narrowing could leave out. **The router needs
    `assert_all_mocked=False`**: otherwise a request no route matches raises
    inside the catalogue's own error handling and never reaches `mock.calls`.
    """
    urls = [str(call.request.url) for call in mock.calls]
    allowed = (named, AT_OPEN_LIBRARY_COVERS, AT_DNB_COVERS)
    return [url for url in urls if not url.startswith(allowed)]


class TestALeftOutSourceIsNotContacted:
    """Every source but the named one goes unasked, over HTTP and over Z39.50.

    The named source answers 500, so the lookup's in turn tail runs too: a tail
    reading the full chain rather than the narrowed one would reach the rest.
    """

    def test_a_narrowed_lookup_asks_no_source_but_the_named_one(self, client, admin, db, z3950_opens):
        library_mode(db)
        with respx.mock(assert_all_called=False, assert_all_mocked=False) as mock:
            k10plus = mock.get(url__startswith=K10PLUS).mock(return_value=httpx.Response(500))
            silence_catalogues(mock)
            client.get(
                "/api/books/lookup",
                params={"isbn": GERMAN_ISBN, "only": ["k10plus"]},
                headers=admin["headers"],
            )
            others = contacted_besides(mock, K10PLUS)

        assert k10plus.called
        assert others == []
        assert z3950_opens == []

    def test_a_narrowed_search_asks_no_source_but_the_named_one(self, client, admin, db, z3950_opens):
        library_mode(db)
        with respx.mock(assert_all_called=False, assert_all_mocked=False) as mock:
            bnf = mock.get(url__startswith=BNF).mock(return_value=httpx.Response(500))
            silence_catalogues(mock)
            response = client.get(
                "/api/books/search",
                params={"q": "dune", "only": ["bnf"]},
                headers=admin["headers"],
            )
            others = contacted_besides(mock, BNF)

        assert bnf.called
        assert others == []
        assert z3950_opens == []
        assert response.json()["asked"] == ["bnf"]


class TestANarrowingCannotWiden:
    def test_naming_a_switched_off_source_is_refused_and_asks_nothing(self, client, admin, db):
        library_mode(db)
        switched_off(client, admin, CatalogueSource.DNB)
        with respx.mock(assert_all_called=False) as mock:
            anything = mock.get(url__regex=r".*").mock(return_value=httpx.Response(500))
            response = client.get(
                "/api/books/lookup",
                params={"isbn": GERMAN_ISBN, "only": ["dnb", "k10plus"]},
                headers=admin["headers"],
            )

        assert response.status_code == 409
        assert not anything.called

    def test_naming_a_source_that_cannot_answer_this_path_is_refused(self, client, admin, db):
        """The BnF answers a title search and no ISBN, so a lookup naming it asks nothing."""
        library_mode(db)
        response = client.get(
            "/api/books/lookup",
            params={"isbn": GERMAN_ISBN, "only": ["bnf"]},
            headers=admin["headers"],
        )

        assert response.status_code == 409

    def test_an_unknown_source_is_refused(self, client, admin, db):
        library_mode(db)
        response = client.get(
            "/api/books/search",
            params={"q": "dune", "only": ["worldcat"]},
            headers=admin["headers"],
        )

        assert response.status_code == 422

    def test_a_refused_narrowing_spends_no_budget(self, client, member, db):
        library_mode(db)
        client.get(
            "/api/books/lookup",
            params={"isbn": GERMAN_ISBN, "only": ["bnf"]},
            headers=member["headers"],
        )

        assert not ratelimit.metadata_limiter._hits.get(member["user"]["username"])


class TestAHouseholdIsNeverOfferedIt:
    def test_a_narrowed_search_outside_library_mode_is_refused(self, client, admin):
        response = client.get(
            "/api/books/search",
            params={"q": "dune", "only": ["bnf"]},
            headers=admin["headers"],
        )

        assert response.status_code == 403

    def test_a_narrowed_lookup_outside_library_mode_is_refused_and_asks_nothing(self, client, admin):
        with respx.mock(assert_all_called=False) as mock:
            anything = mock.get(url__regex=r".*").mock(return_value=httpx.Response(500))
            response = client.get(
                "/api/books/lookup",
                params={"isbn": GERMAN_ISBN, "only": ["k10plus"]},
                headers=admin["headers"],
            )

        assert response.status_code == 403
        assert not anything.called

    def test_the_roster_outside_library_mode_is_refused(self, client, admin):
        assert client.get("/api/books/lookup/catalogues", headers=admin["headers"]).status_code == 403


class TestTheRoster:
    def test_it_lists_what_this_library_asks_with_what_each_answers(self, client, admin, member, db):
        library_mode(db)
        switched_off(client, admin, CatalogueSource.DNB)

        rows = client.get("/api/books/lookup/catalogues", headers=member["headers"]).json()
        by_source = {row["source"]: row for row in rows}

        assert "dnb" not in by_source
        assert by_source["bnf"] == {"source": "bnf", "answers_lookup": False, "answers_search": True}
        assert by_source["k10plus"]["answers_lookup"] is True
