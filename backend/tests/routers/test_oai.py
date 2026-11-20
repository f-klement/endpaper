"""Tests for backend/routers/oai.py: the gate in front of the OAI-PMH provider.

`tests/test_oai.py` drives `oai.respond` and owns the protocol. What is left here
is what a route decides: whether the endpoint exists at all, how fast a stranger
may ask, what the response is labelled as, and where it says it is. Every test
sends **no `Authorization` header**.
"""

from xml.etree import ElementTree

import pytest
from fastapi.routing import APIRoute
from starlette.requests import Request

import oai
import settings_store
from enums import SettingKey
from main import app, iter_api_routes
from ratelimit import PUBLIC_CATALOGUE_LIMIT
from routers.oai import OAI_PREFIX, oai_switch, repository_for
from routers.public import public_reader
from routers.sru import SRU_PREFIX

IDENTIFY = f"{OAI_PREFIX}?verb=Identify"


def _publish(db, *, published: bool = True, oai_on: bool = True, sru_on: bool = False, indexed: bool = False):
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
    settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true" if published else "false")
    settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_INDEXING_ENABLED, "true" if indexed else "false")
    settings_store.set_value(db, SettingKey.OAI_PROVIDER_ENABLED, "true" if oai_on else "false")
    settings_store.set_value(db, SettingKey.OAI_ADMIN_EMAIL, "catalogue@library.example")
    settings_store.set_value(db, SettingKey.SRU_SERVER_ENABLED, "true" if sru_on else "false")


class TestTheProviderHasASwitchOfItsOwn:
    def test_a_published_catalogue_serves_no_oai_until_the_switch_is_set(self, client, db):
        """The default read through the route: no OAI row written at all."""
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")
        assert client.get(IDENTIFY).status_code == 404

    def test_the_switch_on_serves_nothing_while_the_catalogue_is_unpublished(self, client, db):
        _publish(db, published=False)
        assert client.get(IDENTIFY).status_code == 404

    def test_the_switch_off_answers_exactly_what_an_unpublished_catalogue_does(self, client, db):
        _publish(db, published=False)
        unpublished = client.get(IDENTIFY)
        _publish(db, oai_on=False)
        switched_off = client.get(IDENTIFY)
        assert (switched_off.status_code, switched_off.content) == (
            unpublished.status_code,
            unpublished.content,
        )

    def test_sru_on_does_not_serve_oai(self, client, db):
        _publish(db, oai_on=False, sru_on=True)
        assert client.get(SRU_PREFIX).status_code == 200
        assert client.get(IDENTIFY).status_code == 404

    def test_oai_on_does_not_serve_sru(self, client, db):
        _publish(db, oai_on=True, sru_on=False)
        assert client.get(IDENTIFY).status_code == 200
        assert client.get(SRU_PREFIX).status_code == 404

    def test_probing_the_switch_is_rate_limited(self, client, db):
        _publish(db, oai_on=False)
        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            assert client.get(IDENTIFY).status_code == 404
        assert client.get(IDENTIFY).status_code == 429


class TestTheFirstRequestServedIsRecorded:
    """`harvest.py` writes no tombstone before it (owner's decision on issue #176)."""

    def test_a_refused_request_records_nothing(self, client, db):
        _publish(db, oai_on=False)
        client.get(IDENTIFY)
        assert settings_store.oai_has_served(db) is False

    def test_an_answered_request_records_the_moment(self, client, db):
        _publish(db)
        client.get(IDENTIFY)
        db.expire_all()
        assert settings_store.oai_has_served(db) is True


class TestEveryOaiRouteIsGated:
    """Asserted against the live route table, scoped by module as `routers/sru.py`'s is."""

    @staticmethod
    def _module_routes() -> list[APIRoute]:
        return [
            route
            for route in iter_api_routes(app.routes)
            if getattr(route.endpoint, "__module__", "") == "routers.oai"
        ]

    def test_every_route_runs_the_public_gate_then_the_switch(self):
        routes = self._module_routes()
        assert routes, "a guard that inspects nothing reads as coverage"
        assert all(
            [d.call for d in route.dependant.dependencies][:2] == [public_reader, oai_switch]
            for route in routes
        )

    def test_nothing_in_the_module_writes_or_is_in_the_schema(self):
        assert all((route.methods or set()) <= {"GET", "HEAD"} for route in self._module_routes())
        assert all(not route.include_in_schema for route in self._module_routes())


class TestTheSharedGateGivesTheSharedLimit:
    def test_the_limit_is_spent_by_the_json_catalogue_too(self, client, db):
        _publish(db)
        for _ in range(PUBLIC_CATALOGUE_LIMIT.max_attempts):
            client.get("/api/public/books")
        assert client.get(IDENTIFY).status_code == 429


class TestWhatTheResponseSays:
    def test_the_media_type_is_xml(self, client, db):
        _publish(db)
        assert client.get(IDENTIFY).headers["content-type"].startswith("text/xml")

    def test_a_crawler_is_not_invited_even_when_the_catalogue_is_indexable(self, client, db):
        _publish(db, indexed=True)
        assert "noindex" in client.get(IDENTIFY).headers["X-Robots-Tag"]

    def test_robots_txt_does_not_allow_the_oai_path(self, client, db):
        _publish(db, indexed=True)
        assert OAI_PREFIX not in client.get("/robots.txt").text

    def test_identify_names_the_stored_contact_address(self, client, db):
        _publish(db)
        root = ElementTree.fromstring(client.get(IDENTIFY).content)
        assert root.findtext(f"{{{oai.NAMESPACE}}}Identify/{{{oai.NAMESPACE}}}adminEmail") == (
            "catalogue@library.example"
        )

    def test_identify_names_the_base_url_the_request_reached(self, client, db):
        _publish(db)
        root = ElementTree.fromstring(client.get(IDENTIFY, headers={"Host": "books.example:8443"}).content)
        assert root.findtext(f"{{{oai.NAMESPACE}}}Identify/{{{oai.NAMESPACE}}}baseURL") == (
            "http://books.example:8443/oai"
        )


def _request(scheme: str, host: str) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": ("10.0.0.1", 80),
            "path": OAI_PREFIX,
            "query_string": b"",
            "headers": [(b"host", host.encode())],
        }
    )


class TestTheRepositoryIsWhereTheRequestSaysItIs:
    @pytest.mark.parametrize(
        ("scheme", "host", "base_url"),
        [
            ("https", "books.example", "https://books.example/oai"),
            ("https", "books.example:8443", "https://books.example:8443/oai"),
            ("http", "books.example:80", "http://books.example/oai"),
        ],
    )
    def test_the_base_url_leaves_out_only_the_scheme_default_port(self, scheme, host, base_url):
        assert repository_for(_request(scheme, host)).base_url == base_url

    def test_a_host_that_is_not_a_hostname_falls_back(self):
        repository = repository_for(_request("https", "<script>"))
        assert repository.host == "localhost"
        assert repository.identifier(3) == "oai:localhost:3"
