"""Tests for the harvest half of backend/routers/imports.py, and `MarcImport.for_harvest`.

The repository is `respx` at an address literal behind `fetch.pinned_client`, as in
`tests/test_harvester.py`, which holds the client's own paging and bounds. What is
here needs a database: the gates, the matching, what a created Book is, and the run.
"""

import re

import pytest
import respx
from sqlalchemy import select

import harvester
import settings_store
from enums import OwnershipStatus, RecordOrigin, SettingKey
from models import Book, Classification, Harvest, PendingHeading
from routers.imports import HARVEST_RUNNING, REPOSITORY_CHANGED
from tests.corpus import REPO
from tests.test_harvester import BASE, MARC, list_records, oai_record, response

PREVIEW = "/api/imports/harvest/preview"
#: The apply names the repository its preview read, as the card sends it.
APPLY = f"/api/imports/harvest?repository={BASE}"

#: The two client modules that read the harvester's 409 codes: the card words
#: both, and the hook drops its read on `REPOSITORY_CHANGED`.
SETTINGS = REPO / "frontend/src/pages/SettingsPage/LibrarySettingsPage"
CARD = SETTINGS / "components/HarvestImport.tsx"
HOOKS = SETTINGS / "hooks.ts"


def switched_on(db, *, library: bool = True, harvester: bool = True) -> None:
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true" if library else "false")
    settings_store.set_value(db, SettingKey.OAI_HARVEST_BASE_URL, BASE)
    settings_store.set_value(db, SettingKey.OAI_HARVEST_ENABLED, "true" if harvester else "false")


def a_repository(*records: str) -> None:
    """The three requests a run makes, the last answering `records` on one page."""
    respx.get(BASE, params={"verb": "Identify"}).respond(
        text=response("<Identify><repositoryName>Old Catalogue</repositoryName></Identify>")
    )
    respx.get(BASE, params={"verb": "ListMetadataFormats"}).respond(
        text=response(
            "<ListMetadataFormats><metadataFormat><metadataPrefix>marcxml</metadataPrefix>"
            f"<metadataNamespace>{MARC}</metadataNamespace></metadataFormat></ListMetadataFormats>"
        )
    )
    respx.get(BASE, params={"verb": "ListRecords", "metadataPrefix": "marcxml"}).respond(
        text=list_records(*records)
    )


def with_a_heading(title: str, *numbers: str, isbn: str | None = None) -> str:
    """A record carrying Dewey headings, `004` alone by default, which a file import would confirm."""
    dewey = "".join(
        f'<datafield tag="082" ind1="0" ind2="4"><subfield code="a">{number}</subfield></datafield>'
        for number in numbers or ("004",)
    )
    return oai_record(title, isbn=isbn).replace("</record></metadata>", f"{dewey}</record></metadata>")


def pending(db, book_id: int) -> list[tuple[str, bool]]:
    """A Book's raised headings by number, and whether each is settled, re-read."""
    db.expire_all()
    rows = db.scalars(
        select(PendingHeading).where(PendingHeading.book_id == book_id).order_by(PendingHeading.id)
    )
    return [(row.number, row.settled_at is not None) for row in rows]


@pytest.fixture
def harvesting(db):
    switched_on(db)


class TestTheGates:
    @pytest.mark.parametrize("path", [PREVIEW, APPLY])
    def test_a_member_is_refused(self, client, member, harvesting, path):
        assert client.post(path, headers=member["headers"]).status_code == 403

    @pytest.mark.parametrize("path", [PREVIEW, APPLY])
    def test_the_route_is_404_with_the_switch_off(self, client, admin, db, path):
        switched_on(db, harvester=False)
        assert client.post(path, headers=admin["headers"]).status_code == 404

    @pytest.mark.parametrize("path", [PREVIEW, APPLY])
    def test_the_route_is_404_outside_library_mode(self, client, admin, db, path):
        switched_on(db, library=False)
        assert client.post(path, headers=admin["headers"]).status_code == 404

    @respx.mock
    def test_the_route_answers_with_both_on(self, client, admin, harvesting):
        """Anti vacuity for the 404s."""
        a_repository(oai_record("One"))
        assert client.post(PREVIEW, headers=admin["headers"]).status_code == 200

    @respx.mock
    def test_a_repository_failure_is_a_502_that_names_no_address(self, client, admin, harvesting):
        respx.get(BASE, params={"verb": "Identify"}).respond(status_code=500)

        res = client.post(PREVIEW, headers=admin["headers"])

        assert res.status_code == 502
        assert "10.0.9.9" not in res.text

    @pytest.mark.parametrize("path", [PREVIEW, APPLY])
    @respx.mock
    def test_a_harvest_while_another_runs_is_a_409_that_fetches_nothing(
        self, client, admin, harvesting, db, path
    ):
        """A retry behind a proxy that timed the first out would otherwise
        import every record with no ISBN twice."""
        with harvester.one_run():
            res = client.post(path, headers=admin["headers"])

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == HARVEST_RUNNING
        assert respx.calls.call_count == 0
        assert db.scalars(select(Harvest)).all() == []

    @respx.mock
    def test_an_apply_naming_another_repository_is_a_409_that_fetches_nothing(
        self, client, admin, harvesting, db
    ):
        """A tab that read the address before another tab saved a new one
        previewed a repository this would not harvest."""
        res = client.post(
            "/api/imports/harvest",
            params={"repository": "http://10.0.9.10/oai"},
            headers=admin["headers"],
        )

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == REPOSITORY_CHANGED
        assert "10.0.9" not in res.json()["detail"]["message"]
        assert respx.calls.call_count == 0
        assert db.scalars(select(Harvest)).all() == []

    @respx.mock
    def test_an_apply_naming_the_stored_repository_with_spaces_around_it_runs(
        self, client, admin, harvesting
    ):
        """Anti vacuity for the refusal above, and the settings read does not trim."""
        a_repository(oai_record("One"))

        res = client.post(
            "/api/imports/harvest", params={"repository": f" {BASE} "}, headers=admin["headers"]
        )

        assert res.status_code == 200

    @respx.mock
    def test_a_refused_apply_spends_none_of_the_import_limit(self, client, admin, harvesting):
        """The refusal reads before `import_limiter`, so a tab refused for a stale
        address may read again and harvest at once."""
        a_repository(oai_record("One"))
        stale = {"repository": "http://10.0.9.10/oai"}

        refused = [
            client.post("/api/imports/harvest", params=stale, headers=admin["headers"]).status_code
            for _ in range(4)
        ]

        assert refused == [409] * 4
        assert client.post(APPLY, headers=admin["headers"]).status_code == 200

    def test_the_card_words_both_codes_as_the_route_spells_them(self):
        """Each side's tests spell the codes with their own literal, so a code
        respelt on one side stays green on both while the card reads a running
        harvest as a lost race. This holds the keys of `REFUSAL_BY_CODE`."""
        body = re.search(r"\bconst REFUSAL_BY_CODE\b[^{]*\{([^}]*)\}", CARD.read_text(encoding="utf-8"))

        assert body is not None
        assert sorted(re.findall(r"^\s*(\w+):", body.group(1), re.MULTILINE)) == sorted(
            [HARVEST_RUNNING, REPOSITORY_CHANGED]
        )

    def test_the_hook_drops_its_read_on_the_code_the_route_spells(self):
        declared = re.findall(r'error\.code === "([^"]*)"', HOOKS.read_text(encoding="utf-8"))

        assert declared == [REPOSITORY_CHANGED]


class TestThePreview:
    @respx.mock
    def test_it_counts_what_is_held_and_writes_nothing(self, client, admin, harvesting, make_book, db):
        make_book(admin["headers"], title="Held", author="An Author")
        a_repository(
            oai_record("Held").replace("</datafield>", "</datafield>" + _author("An Author"), 1),
            oai_record("New"),
            oai_record("Gone", deleted=True),
        )

        body = client.post(PREVIEW, headers=admin["headers"]).json()

        assert (body["readable"], body["already_held"], body["deleted"], body["records_seen"]) == (2, 1, 1, 3)
        assert body["repository_name"] == "Old Catalogue"
        assert db.scalar(select(Harvest.id)) is None
        assert db.scalars(select(Book.title)).all() == ["Held"]


def _author(name: str) -> str:
    return f'<datafield tag="100" ind1="1" ind2=" "><subfield code="a">{name}</subfield></datafield>'


class TestTheApply:
    @respx.mock
    def test_a_created_book_is_nobodys_public_and_points_at_its_run(self, client, admin, harvesting, db):
        a_repository(oai_record("New"))

        body = client.post(APPLY, headers=admin["headers"]).json()

        book = db.scalars(select(Book)).one()
        assert (book.added_by_user_id, book.is_private, book.harvest_id) == (None, False, body["harvest_id"])
        assert (book.record_origin, book.ownership) == (RecordOrigin.OAI_HARVEST, OwnershipStatus.UNKNOWN)

    @respx.mock
    def test_the_run_records_its_counts_and_who_ran_it(self, client, admin, harvesting, db):
        a_repository(oai_record("One"), oai_record("Two"), oai_record("Gone", deleted=True))

        body = client.post(APPLY, headers=admin["headers"]).json()

        run = db.get_one(Harvest, body["harvest_id"])
        assert (run.base_url, run.metadata_prefix, run.run_by_user_id) == (
            BASE,
            "marcxml",
            admin["user"]["id"],
        )
        assert (run.records_seen, run.records_added, run.finished_at is not None) == (3, 2, True)
        assert (body["created"], body["deleted"]) == (2, 1)

    @respx.mock
    def test_a_book_matched_by_isbn_is_filled_and_not_overwritten(
        self, client, admin, harvesting, make_book, db
    ):
        held = make_book(admin["headers"], title="Dune", author="Frank Herbert", isbn="9780441172719")
        record = oai_record("Dune, retitled", isbn="9780441172719").replace(
            "</record></metadata>",
            '<datafield tag="260" ind1=" " ind2=" "><subfield code="b">Ace</subfield></datafield>'
            "</record></metadata>",
        )
        a_repository(record)

        body = client.post(APPLY, headers=admin["headers"]).json()

        book = db.get_one(Book, held["id"])
        assert (body["matched"], body["created"]) == (1, 0)
        assert (book.title, book.publisher, book.harvest_id) == ("Dune", "Ace", None)

    @respx.mock
    def test_a_record_crediting_nobody_never_matches_a_credited_book(
        self, client, admin, harvesting, make_book, db
    ):
        make_book(admin["headers"], title="Collected Poems", author="Somebody Else")
        a_repository(oai_record("Collected Poems"))

        body = client.post(APPLY, headers=admin["headers"]).json()

        assert (body["matched"], body["created"]) == (0, 1)

    @respx.mock
    def test_a_created_books_headings_wait_as_suggestions(self, client, admin, harvesting, db):
        a_repository(with_a_heading("Computing"))

        body = client.post(APPLY, headers=admin["headers"]).json()

        book = db.scalars(select(Book)).one()
        assert db.scalar(select(Classification.id)) is None
        assert pending(db, book.id) == [("004", False)]
        assert body["headings_pending"] == 1

    @respx.mock
    def test_a_book_matched_by_isbn_gets_no_heading_and_no_suggestion(
        self, client, admin, harvesting, make_book, db
    ):
        """The record is some other Book's, whose headings it has no say over."""
        held = make_book(admin["headers"], title="Dune", author="Frank Herbert", isbn="9780441172719")
        a_repository(with_a_heading("Dune", isbn="9780441172719"))

        body = client.post(APPLY, headers=admin["headers"]).json()

        assert (body["matched"], body["headings_pending"]) == (1, 0)
        assert db.scalar(select(Classification.id)) is None
        assert pending(db, held["id"]) == []

    @respx.mock
    def test_a_book_matched_by_author_and_title_gets_no_heading_and_no_suggestion(
        self, client, admin, harvesting, make_book, db
    ):
        """The ladder's second rung is another record's Book as much as the first."""
        held = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        credited = "</datafield>" + _author("Frank Herbert")
        a_repository(with_a_heading("Dune").replace("</datafield>", credited, 1))

        body = client.post(APPLY, headers=admin["headers"]).json()

        assert (body["matched"], body["created"], body["headings_pending"]) == (1, 0, 0)
        assert db.scalar(select(Classification.id)) is None
        assert pending(db, held["id"]) == []

    @respx.mock
    def test_a_member_private_book_is_neither_matched_nor_named(self, client, admin, member, harvesting, db):
        res = client.post(
            "/api/books",
            json={
                "title": "Private Diary",
                "author": "A Member",
                "isbn": "9780441172719",
                "is_private": True,
            },
            headers=member["headers"],
        )
        assert res.status_code == 201, res.text
        a_repository(oai_record("Public Record", isbn="9780441172719"))

        res = client.post(APPLY, headers=admin["headers"])

        assert (res.json()["matched"], res.json()["created"], res.json()["skipped"]) == (0, 0, 1)
        assert "Private Diary" not in res.text
        private = db.scalars(select(Book).where(Book.title == "Private Diary")).one()
        assert (private.harvest_id, private.added_by_user_id) == (None, member["user"]["id"])


class TestARerunMatchesByRecordIdentifier:
    """A record with no ISBN matches only on its title and author, so a Book a
    cataloguer corrected after the first run matched nothing on the ladder and
    a re-run, the natural answer to `truncated`, created it again. The
    identifier it was created from is what holds it now."""

    @staticmethod
    def _corrected(db, harvest_id: int) -> Book:
        """The harvested Book, its title corrected here after the run."""
        book = db.scalars(select(Book).where(Book.harvest_id == harvest_id)).one()
        book.title = "One, corrected"
        db.commit()
        return book

    @respx.mock
    def test_a_second_run_matches_a_corrected_book_and_creates_nothing(self, client, admin, harvesting, db):
        a_repository(oai_record("One"))
        first = client.post(APPLY, headers=admin["headers"]).json()
        book = self._corrected(db, first["harvest_id"])

        again = client.post(APPLY, headers=admin["headers"]).json()

        assert (again["matched"], again["created"]) == (1, 0)
        assert db.scalars(select(Book.id)).all() == [book.id]
        assert (book.harvested_identifier, book.title) == ("oai:x:One", "One, corrected")

    @respx.mock
    def test_a_second_run_raises_only_the_headings_the_record_newly_carries(
        self, client, admin, harvesting, db
    ):
        a_repository(with_a_heading("One", "004"))
        book = self._corrected(db, client.post(APPLY, headers=admin["headers"]).json()["harvest_id"])
        a_repository(with_a_heading("One", "004", "510"))

        again = client.post(APPLY, headers=admin["headers"]).json()

        assert again["headings_pending"] == 1
        assert pending(db, book.id) == [("004", False), ("510", False)]

    @respx.mock
    def test_a_discarded_set_is_not_raised_again(self, client, admin, harvesting, db):
        a_repository(with_a_heading("One", "004"))
        book = self._corrected(db, client.post(APPLY, headers=admin["headers"]).json()["harvest_id"])
        discarded = client.post(f"/api/books/{book.id}/pending-headings/discard", headers=admin["headers"])
        assert discarded.status_code == 204
        a_repository(with_a_heading("One", "004", "510"))

        again = client.post(APPLY, headers=admin["headers"]).json()

        assert again["headings_pending"] == 1
        assert pending(db, book.id) == [("004", True), ("510", False)]

    @respx.mock
    def test_a_confirmed_heading_is_not_raised_again(self, client, admin, harvesting, db):
        a_repository(with_a_heading("One", "004"))
        book = self._corrected(db, client.post(APPLY, headers=admin["headers"]).json()["harvest_id"])
        confirmed = client.post(f"/api/books/{book.id}/pending-headings/confirm", headers=admin["headers"])
        assert confirmed.status_code == 200, confirmed.text

        again = client.post(APPLY, headers=admin["headers"]).json()

        assert again["headings_pending"] == 0
        assert pending(db, book.id) == [("004", True)]

    @respx.mock
    def test_the_preview_of_a_second_run_counts_it_held(self, client, admin, harvesting, db):
        a_repository(oai_record("One"))
        self._corrected(db, client.post(APPLY, headers=admin["headers"]).json()["harvest_id"])

        body = client.post(PREVIEW, headers=admin["headers"]).json()

        assert (body["readable"], body["already_held"]) == (1, 1)

    @respx.mock
    def test_the_same_identifier_from_another_repository_is_not_matched(self, client, admin, harvesting, db):
        """An OAI identifier is unique within its repository only."""
        elsewhere = Harvest(base_url="http://10.0.0.1/oai", metadata_prefix="marc21")
        db.add(elsewhere)
        db.flush()
        db.add(Book(title="Another book", harvest_id=elsewhere.id, harvested_identifier="oai:x:One"))
        db.commit()
        a_repository(oai_record("One"))

        body = client.post(APPLY, headers=admin["headers"]).json()

        assert (body["matched"], body["created"]) == (0, 1)

    @respx.mock
    def test_a_record_whose_book_is_in_the_trash_is_left_there(self, client, admin, harvesting, db):
        a_repository(oai_record("One"))
        book = self._corrected(db, client.post(APPLY, headers=admin["headers"]).json()["harvest_id"])
        assert client.delete(f"/api/books/{book.id}", headers=admin["headers"]).status_code == 204

        again = client.post(APPLY, headers=admin["headers"]).json()

        assert (again["created"], again["in_trash"]) == (0, 1)
