"""Tests for the subject vocabulary routes in routers/settings.py."""

import gzip
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
import respx

import vocabulary_copy

URL = "/api/settings/vocabularies"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "vocabularies"
LCSH_RELEASE = gzip.compress((FIXTURES / "lcsh_subjects_skos_2026_11_20.jsonl").read_bytes())
LCSH_ORIGIN = vocabulary_copy.scheme("lcsh").origin or ""


@pytest.fixture(autouse=True)
def no_load_from_another_test(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with no load under way and waits for the ones it
    started before the database is emptied."""
    threads: dict[str, threading.Thread] = {}
    monkeypatch.setattr(vocabulary_copy, "_PROGRESS", {})
    monkeypatch.setattr(vocabulary_copy, "_THREADS", threads)
    yield
    for thread in list(threads.values()):
        thread.join(timeout=30)


def _after(held: threading.Event) -> Callable[[httpx.Request], httpx.Response]:
    """A release that answers, with a failure, only once `held` is set."""

    def answer(_request: httpx.Request) -> httpx.Response:
        held.wait(30)
        return httpx.Response(503)

    return answer


def test_a_member_may_neither_list_nor_download_them(client, member):
    assert client.get(URL, headers=member["headers"]).status_code == 403
    assert client.post(f"{URL}/lcsh/download", headers=member["headers"]).status_code == 403


def test_an_admin_lists_every_declared_vocabulary_with_nothing_loaded(client, admin):
    res = client.get(URL, headers=admin["headers"])

    assert res.status_code == 200
    assert [(row["scheme"], row["copyable"], row["entries"]) for row in res.json()] == [
        ("gnd", True, None),
        ("lcsh", True, None),
    ]


def test_downloading_an_undeclared_vocabulary_is_a_404(client, admin):
    assert client.post(f"{URL}/mesh/download", headers=admin["headers"]).status_code == 404


def test_a_download_is_accepted_and_its_copy_is_listed_once_loaded(client, admin):
    with respx.mock:
        respx.get(LCSH_ORIGIN).mock(return_value=httpx.Response(200, content=LCSH_RELEASE))
        res = client.post(f"{URL}/lcsh/download", headers=admin["headers"])
        loading = vocabulary_copy.running("lcsh")
        if loading is not None:
            loading.join(timeout=30)

    assert res.status_code == 202
    assert res.json()["scheme"] == "lcsh"
    assert client.get(URL, headers=admin["headers"]).json()[1]["entries"] == 5


def test_a_second_download_while_one_runs_is_a_409(client, admin):
    held = threading.Event()
    with respx.mock:
        respx.get(LCSH_ORIGIN).mock(side_effect=_after(held))
        client.post(f"{URL}/lcsh/download", headers=admin["headers"])
        try:
            assert client.post(f"{URL}/lcsh/download", headers=admin["headers"]).status_code == 409
        finally:
            held.set()
            loading = vocabulary_copy.running("lcsh")
            if loading is not None:
                loading.join(timeout=30)
