"""The `origin` and `harvest` filters on `GET /api/books`, in backend/routers/books.py.

A harvested Book is one `books.harvest_id` names a run for, and it is always public
and ownerless (`docs/decisions.md`, *Harvesting an OAI-PMH repository*). The rows
are written straight into the database here, as a harvest writes them; what the
harvest itself does is `tests/routers/test_imports_harvest.py`.
"""

from datetime import UTC, datetime

import pytest

import settings_store
from enums import SettingKey
from models import Book, Harvest


@pytest.fixture
def library_mode(db) -> None:
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")


def harvested(db, *titles: str, trashed: bool = False) -> int:
    """Write one run creating a Book per title, and answer the run's id."""
    run = Harvest(base_url="http://10.0.0.1/oai", metadata_prefix="marcxml")
    db.add(run)
    db.flush()
    deleted_at = datetime.now(UTC).replace(tzinfo=None) if trashed else None
    db.add_all(
        Book(title=title, harvest_id=run.id, harvested_identifier=f"oai:{title}", deleted_at=deleted_at)
        for title in titles
    )
    db.commit()
    return run.id


def listed(client, headers: dict[str, str], **params: object) -> tuple[list[str], int]:
    res = client.get("/api/books", params=params, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    return [book["title"] for book in body["items"]], body["total"]


@pytest.mark.usefixtures("library_mode")
class TestInLibraryMode:
    def test_harvested_lists_only_the_books_a_harvest_created(self, client, db, member, make_book):
        make_book(member["headers"], title="Typed in")
        harvested(db, "Harvested A", "Harvested B")

        assert listed(client, member["headers"], origin="harvested") == (["Harvested A", "Harvested B"], 2)

    def test_added_lists_every_book_no_harvest_created(self, client, db, member, make_book):
        make_book(member["headers"], title="Typed in")
        harvested(db, "Harvested")

        assert listed(client, member["headers"], origin="added") == (["Typed in"], 1)

    def test_another_members_private_book_is_neither_listed_nor_counted(
        self, client, db, member, other_user, make_book
    ):
        """Only the `added` arm reaches the Shelf's privacy rule: a harvested row
        cannot be private (`ck_books_harvested_is_nobodys_and_public`), so the
        `harvested` arm guards a filter on an unscoped query and nothing more."""
        make_book(other_user["headers"], title="Diary", is_private=True)
        make_book(member["headers"], title="Typed in")
        harvested(db, "Harvested")

        assert listed(client, member["headers"], origin="added") == (["Typed in"], 1)
        assert listed(client, member["headers"], origin="harvested") == (["Harvested"], 1)

    def test_it_composes_with_the_search_and_counts_past_the_page(self, client, db, member, make_book):
        make_book(member["headers"], title="Dune typed in")
        harvested(db, "Dune one", "Dune two", "Emma")

        page = listed(client, member["headers"], origin="harvested", q="dune", page_size=1)

        assert page == (["Dune one"], 2)

    def test_a_value_outside_the_two_is_refused(self, client, member):
        res = client.get("/api/books", params={"origin": "imported"}, headers=member["headers"])

        assert res.status_code == 422


@pytest.mark.usefixtures("library_mode")
class TestOneRun:
    def test_harvest_lists_only_the_books_that_run_created(self, client, db, member, make_book):
        make_book(member["headers"], title="Typed in")
        harvested(db, "First run")
        run = harvested(db, "Second run A", "Second run B")

        assert listed(client, member["headers"], harvest=run) == (["Second run A", "Second run B"], 2)

    def test_a_run_that_created_no_book_lists_nothing(self, client, db, member, make_book):
        make_book(member["headers"], title="Typed in")
        harvested(db, "Harvested")
        empty = harvested(db)

        assert listed(client, member["headers"], harvest=empty) == ([], 0)

    def test_a_trashed_book_of_the_run_is_neither_listed_nor_counted(self, client, db, member):
        """The privacy arm. A harvested row is always public, so the Shelf's
        exclusion this filter can reach is the trash: a `harvest_id` clause on
        an unscoped query would list the trashed Book and count it."""
        run = harvested(db, "Kept")
        harvested(db, "Trashed", trashed=True)
        trashed_run = harvested(db, "Also trashed", trashed=True)

        assert listed(client, member["headers"], harvest=run) == (["Kept"], 1)
        assert listed(client, member["headers"], harvest=trashed_run) == ([], 0)

    def test_it_composes_with_the_origin(self, client, db, member):
        run = harvested(db, "Harvested")

        assert listed(client, member["headers"], harvest=run, origin="harvested") == (["Harvested"], 1)
        assert listed(client, member["headers"], harvest=run, origin="added") == ([], 0)


class TestOutsideLibraryMode:
    @pytest.mark.parametrize("params", [{"origin": "harvested"}, {"harvest": 1}], ids=["origin", "harvest"])
    def test_the_filter_is_refused(self, client, db, member, params):
        harvested(db, "Harvested")

        res = client.get("/api/books", params=params, headers=member["headers"])

        assert res.status_code == 403

    def test_the_listing_without_it_is_unchanged(self, client, db, member, make_book):
        """Passes before either filter existed, by design: it holds the refusal
        to a request that names one, so a check on library mode alone fails it."""
        make_book(member["headers"], title="Typed in")
        harvested(db, "Harvested")

        assert listed(client, member["headers"]) == (["Harvested", "Typed in"], 2)
