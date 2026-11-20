"""Tests for backend/oai.py: the OAI-PMH protocol, driven through `oai.respond`.

`tests/routers/test_oai.py` owns the gate in front of it. `tests/test_harvest.py`
owns how a datestamp moves and when a tombstone is written; here a tombstone is
only read.
"""

import base64
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from sqlalchemy import CheckConstraint, String, Table, update

import oai
import settings_store
from enums import SettingKey
from models import Book, OaiTombstone
from schemas.common import MAX_ROW_ID
from schemas.public import PublicBookOut

NS = f"{{{oai.NAMESPACE}}}"
DC = "{http://purl.org/dc/elements/1.1/}"

#: A reserved name from RFC 2606, so no identifier here names a deployment.
REPOSITORY = oai.Repository(host="catalogue.example", base_url="https://catalogue.example/oai")


def respond(db: Any, query: list[tuple[str, str]] | None = None, **arguments: str) -> ElementTree.Element:
    """One request, parsed. `query` carries a repeated argument, which a mapping cannot."""
    return ElementTree.fromstring(oai.respond(urlencode(query or list(arguments.items())), db, REPOSITORY))


def error_of(root: ElementTree.Element) -> str | None:
    error = root.find(f"{NS}error")
    return None if error is None else error.get("code")


def identifiers(root: ElementTree.Element) -> list[str]:
    return [element.text or "" for element in root.iter(f"{NS}identifier")]


def deleted(root: ElementTree.Element) -> list[str]:
    return [
        header.findtext(f"{NS}identifier") or ""
        for header in root.iter(f"{NS}header")
        if header.get("status") == "deleted"
    ]


def token_of(root: ElementTree.Element) -> str | None:
    token = root.find(f".//{NS}resumptionToken")
    return None if token is None else (token.text or "")


def stamp(db: Any, book_id: int, moment: datetime) -> None:
    """Put a datestamp where a test wants it, by a write `harvest.py` does not move."""
    db.execute(update(Book).where(Book.id == book_id).values(oai_datestamp=moment))
    db.commit()


@pytest.fixture(autouse=True)
def serving(db):
    """As a deployment answering requests is: an address stored, and the first
    request recorded, so a Book leaving from here on is tombstoned."""
    settings_store.set_value(db, SettingKey.OAI_ADMIN_EMAIL, "catalogue@library.example")
    settings_store.record_oai_service(db)


@pytest.fixture
def shelf(db, admin, member):
    """One public book, one private one and one created in the trash."""
    owner = admin["user"]["id"]
    public = Book(
        title="Chartreuse Windmill", isbn="9780306406157", author="Ada Lovelace", added_by_user_id=owner
    )
    private = Book(title="Chartreuse Windmill", is_private=True, added_by_user_id=member["user"]["id"])
    trashed = Book(
        title="Chartreuse Windmill",
        added_by_user_id=owner,
        deleted_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([public, private, trashed])
    db.commit()
    return {"public": public.id, "private": private.id, "trashed": trashed.id}


class TestNoBookOutsideThePublicShelfIsServed:
    """`Shelf.seen_by_the_public` is the only row filter, on every verb."""

    @pytest.mark.parametrize("verb", ["ListIdentifiers", "ListRecords"])
    def test_a_listing_names_only_the_public_book(self, db, shelf, verb):
        root = respond(db, verb=verb, metadataPrefix="oai_dc")
        assert identifiers(root) == [REPOSITORY.identifier(shelf["public"])]

    @pytest.mark.parametrize("which", ["private", "trashed"])
    def test_a_book_never_public_answers_as_an_id_that_never_existed(self, db, shelf, which):
        """The same error as for a free id, so `GetRecord` cannot tell a stranger
        that a private Book exists."""
        hidden = respond(
            db, verb="GetRecord", metadataPrefix="oai_dc", identifier=REPOSITORY.identifier(shelf[which])
        )
        absent = respond(
            db, verb="GetRecord", metadataPrefix="oai_dc", identifier=REPOSITORY.identifier(MAX_ROW_ID)
        )
        assert error_of(hidden) == error_of(absent) == "idDoesNotExist"

    def test_a_marc_listing_names_only_the_public_book(self, db, shelf):
        root = respond(db, verb="ListRecords", metadataPrefix="marc21")
        assert identifiers(root) == [REPOSITORY.identifier(shelf["public"])]


class TestARecordThatLeavesIsADeletedHeader:
    """Owner's decision: deletedRecord is persistent, and the tombstone holds
    the identifier and the datestamp and nothing else."""

    def test_a_book_made_private_is_listed_as_deleted(self, db, shelf):
        db.get(Book, shelf["public"]).is_private = True
        db.commit()
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc")
        assert deleted(root) == [REPOSITORY.identifier(shelf["public"])]

    def test_a_deleted_record_carries_no_metadata(self, db, shelf):
        db.get(Book, shelf["public"]).is_private = True
        db.commit()
        root = respond(
            db, verb="GetRecord", metadataPrefix="oai_dc", identifier=REPOSITORY.identifier(shelf["public"])
        )
        assert deleted(root) == [REPOSITORY.identifier(shelf["public"])]
        assert root.find(f".//{NS}metadata") is None
        assert "Chartreuse" not in ElementTree.tostring(root, encoding="unicode")

    def test_identify_advertises_persistent_deletion(self, db):
        assert respond(db, verb="Identify").findtext(f".//{NS}deletedRecord") == "persistent"


class TestTheRecordCarriesNoColumnThePublicPayloadWithholds:
    """`oai_dc` is built from `PublicBookOut`. Asserted by rendering a stored Book
    with a distinctive value in every withheld text column, the instrument
    `tests/test_sru.py` uses for `marc21`, which covers that format here too."""

    @staticmethod
    def _sentinels(db: Any) -> dict[str, str]:
        # A column a CHECK holds to a list of values cannot take a sentinel.
        listed = {
            column.key
            for constraint in cast(Table, Book.__table__).constraints
            if isinstance(constraint, CheckConstraint) and " IN (" in str(constraint.sqltext).upper()
            for column in Book.__table__.columns
            if column.key in str(constraint.sqltext)
        }
        textual = {
            column.key
            for column in Book.__table__.columns
            if column.key not in set(PublicBookOut.model_fields) | listed
            and isinstance(column.type, String)
            and not getattr(column.type, "enums", None)
        }
        # Three characters: the narrowest withheld column, `purchase_currency`, holds no more.
        return {key: f"Zq{n}" for n, key in enumerate(sorted(textual))}

    def test_no_withheld_value_appears_in_a_rendered_record(self, db, admin):
        sentinels = self._sentinels(db)
        assert len(sentinels) >= 3, "the population this test reads has gone"
        book = Book(title="Chartreuse Windmill", added_by_user_id=admin["user"]["id"], **sentinels)
        db.add(book)
        db.commit()
        rendered = oai.respond(urlencode({"verb": "ListRecords", "metadataPrefix": "oai_dc"}), db, REPOSITORY)
        assert "Chartreuse Windmill" in rendered
        assert [key for key, value in sentinels.items() if value in rendered] == []


#: One request per row that reaches the error it names.
ERROR_CASES: list[tuple[list[tuple[str, str]], str]] = [
    ([], "badVerb"),
    ([("verb", "Harvest")], "badVerb"),
    ([("verb", "Identify"), ("verb", "Identify")], "badVerb"),
    ([("verb", "Identify"), ("extra", "1")], "badArgument"),
    ([("verb", "ListRecords")], "badArgument"),
    ([("verb", "ListRecords"), ("metadataPrefix", "oai_dc"), ("metadataPrefix", "oai_dc")], "badArgument"),
    ([("verb", "ListRecords"), ("metadataPrefix", "oai_dc"), ("resumptionToken", "x")], "badArgument"),
    ([("verb", "ListRecords"), ("metadataPrefix", "oai dc")], "badArgument"),
    ([("verb", "ListRecords"), ("metadataPrefix", "x" * (oai.MAX_ARGUMENT_CHARS + 1))], "badArgument"),
    (
        [("verb", "ListRecords"), ("metadataPrefix", "oai_dc"), ("from", "2026-01-01T00:00:00+01:00")],
        "badArgument",
    ),
    ([("verb", "ListRecords"), ("metadataPrefix", "oai_dc"), ("from", "2026-02-30")], "badArgument"),
    # Finer than the day the repository serves, which the specification makes an error.
    (
        [("verb", "ListRecords"), ("metadataPrefix", "oai_dc"), ("from", "2026-01-01T00:00:00Z")],
        "badArgument",
    ),
    ([("verb", "ListRecords"), ("resumptionToken", "!!!!")], "badResumptionToken"),
    ([("verb", "ListSets"), ("resumptionToken", "x")], "badResumptionToken"),
    ([("verb", "ListRecords"), ("metadataPrefix", "dc")], "cannotDisseminateFormat"),
    (
        [("verb", "GetRecord"), ("metadataPrefix", "oai_dc"), ("identifier", "oai:elsewhere.example:1")],
        "idDoesNotExist",
    ),
    ([("verb", "ListRecords"), ("metadataPrefix", "oai_dc")], "noRecordsMatch"),
    ([("verb", "ListSets")], "noSetHierarchy"),
    ([("verb", "ListRecords"), ("metadataPrefix", "oai_dc"), ("set", "a")], "noSetHierarchy"),
]


class TestEveryNamedErrorIsReachable:
    @pytest.mark.parametrize(("query", "code"), ERROR_CASES)
    def test_each_error_has_a_request_that_reaches_it(self, db, query, code):
        assert error_of(respond(db, query)) == code

    def test_every_error_code_is_among_those_reached(self):
        reached = {code for _, code in ERROR_CASES}
        assert reached == {code.value for code in oai.ErrorCode}

    def test_too_many_fields_is_an_error_rather_than_a_traceback(self, db):
        assert (
            error_of(respond(db, [("verb", "Identify")] + [(f"k{n}", "v") for n in range(oai.MAX_FIELDS)]))
            == "badArgument"
        )

    @pytest.mark.parametrize(
        "query", [[("verb", "Harvest"), ("x", "<y>")], [("verb", "Identify"), ("x", "y")]]
    )
    def test_bad_verb_and_bad_argument_echo_no_argument(self, db, query):
        request = respond(db, query).find(f"{NS}request")
        assert request is not None
        assert request.attrib == {}


class TestPagingVisitsEveryRecordOnce:
    @pytest.fixture
    def many(self, db, admin, monkeypatch):
        monkeypatch.setattr(oai, "PAGE_SIZE", 2)
        books = [Book(title=f"Book {n}", added_by_user_id=admin["user"]["id"]) for n in range(5)]
        db.add_all(books)
        db.commit()
        return [book.id for book in books]

    def test_following_the_tokens_lists_each_record_once(self, db, many):
        seen: list[str] = []
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc")
        while True:
            seen += identifiers(root)
            token = token_of(root)
            if not token:
                break
            root = respond(db, verb="ListIdentifiers", resumptionToken=token)
        assert seen == [REPOSITORY.identifier(book_id) for book_id in many]

    def test_a_resumed_list_ends_on_an_empty_token(self, db, many):
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc")
        while token_of(root):
            root = respond(db, verb="ListIdentifiers", resumptionToken=token_of(root) or "")
        assert token_of(root) == ""

    def test_a_window_from_before_1970_resumes(self, db, many):
        """A window starting before 1970 travels in its token like any other."""
        root = respond(
            db, [("verb", "ListIdentifiers"), ("metadataPrefix", "oai_dc"), ("from", "1960-01-01")]
        )
        seen = identifiers(root)
        while token_of(root):
            root = respond(db, verb="ListIdentifiers", resumptionToken=token_of(root) or "")
            assert error_of(root) is None
            seen += identifiers(root)
        assert seen == [REPOSITORY.identifier(book_id) for book_id in many]

    def test_a_tombstone_is_paged_in_id_order_with_the_live_records(self, db, many):
        db.get(Book, many[1]).is_private = True
        db.commit()
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc")
        assert identifiers(root) == [REPOSITORY.identifier(many[0]), REPOSITORY.identifier(many[1])]
        assert deleted(root) == [REPOSITORY.identifier(many[1])]


class TestAForgedTokenReachesNoMoreThanAFreshRequest:
    """Every field of a token is one a caller may ask for anyway; the row filter
    and the page size are the server's."""

    @staticmethod
    def _forge(raw: str) -> str:
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    def test_a_forged_token_from_the_start_answers_as_the_fresh_request(self, db, shelf):
        forged = respond(db, verb="ListRecords", resumptionToken=self._forge("oai_dc!!!0"))
        fresh = respond(db, verb="ListRecords", metadataPrefix="oai_dc")
        assert identifiers(forged) == identifiers(fresh) == [REPOSITORY.identifier(shelf["public"])]

    @pytest.mark.parametrize(
        "raw",
        [
            "oai_dc!!!0!500",
            "secret!!!0",
            f"oai_dc!!!{MAX_ROW_ID + 1}",
            "oai_dc!!!-1",
            "oai_dc!x!!0",
            "oai_dc!0!!0",
            # A bound to the second, which would bisect a day: the shape tokens had
            # when the window travelled as epoch seconds.
            f"oai_dc!{int(datetime(2026, 3, 4, 12, tzinfo=UTC).timestamp())}!!0",
        ],
    )
    def test_a_token_of_any_other_shape_is_refused(self, db, raw):
        assert (
            error_of(respond(db, verb="ListRecords", resumptionToken=self._forge(raw)))
            == "badResumptionToken"
        )

    def test_an_overlong_token_is_refused_before_decoding(self, db):
        token = self._forge("oai_dc!!!0") + "A" * oai.MAX_TOKEN_CHARS
        assert error_of(respond(db, verb="ListRecords", resumptionToken=token)) == "badResumptionToken"


class TestTheWindowSelectsByDatestamp:
    @pytest.fixture
    def dated(self, db, shelf):
        stamp(db, shelf["public"], datetime(2026, 3, 4, 12, 0, 0))
        return shelf["public"]

    @pytest.mark.parametrize(
        ("window", "found"),
        [
            ({"from": "2026-03-04", "until": "2026-03-04"}, True),
            ({"from": "2026-03-05"}, False),
            ({"until": "2026-03-03"}, False),
        ],
    )
    def test_from_and_until_are_inclusive(self, db, dated, window, found):
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc", **window)
        assert (identifiers(root) == [REPOSITORY.identifier(dated)]) is found
        assert found or error_of(root) == "noRecordsMatch"

    @pytest.mark.parametrize(
        "window",
        [
            {"from": "2026-03-04", "until": "2026-03-05T00:00:00Z"},
            {"from": "2026-03-05", "until": "2026-03-04"},
        ],
    )
    def test_a_window_given_to_the_second_or_reversed_is_refused(self, db, window):
        assert (
            error_of(respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc", **window)) == "badArgument"
        )

    def test_a_bound_finer_than_a_day_compares_as_its_day(self, db, dated):
        """Whatever builds a `Harvest`, no page compares a stored datestamp to the
        second: a start one second past the stamp still selects it."""
        harvest = oai.Harvest(oai.FORMATS["oai_dc"], datetime(2026, 3, 4, 12, 0, 1), None, 0)
        assert [entry.book_id for entry in oai._page(db, harvest, with_metadata=False)] == [dated]

    def test_a_forged_token_reaches_the_window_of_whole_days_a_fresh_request_does(self, db, dated):
        day = date(2026, 3, 4).toordinal()
        raw = f"oai_dc!{day}!{day + 1}!0"
        forged = respond(
            db,
            verb="ListIdentifiers",
            resumptionToken=TestAForgedTokenReachesNoMoreThanAFreshRequest._forge(raw),
        )
        fresh = respond(
            db,
            [
                ("verb", "ListIdentifiers"),
                ("metadataPrefix", "oai_dc"),
                ("from", "2026-03-04"),
                ("until", "2026-03-04"),
            ],
        )
        assert identifiers(forged) == identifiers(fresh) == [REPOSITORY.identifier(dated)]

    def test_until_at_the_last_representable_day_is_open(self, db, dated):
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc", until="9999-12-31")
        assert identifiers(root) == [REPOSITORY.identifier(dated)]

    def test_a_resumed_page_keeps_the_window(self, db, admin, dated, monkeypatch):
        monkeypatch.setattr(oai, "PAGE_SIZE", 1)
        later = [Book(title=f"Later {n}", added_by_user_id=admin["user"]["id"]) for n in range(2)]
        db.add_all(later)
        db.commit()
        stamp(db, later[0].id, datetime(2026, 3, 4, 13, 0, 0))
        first = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc", until="2026-03-04")
        second = respond(db, verb="ListIdentifiers", resumptionToken=token_of(first) or "")
        assert identifiers(first) + identifiers(second) == [
            REPOSITORY.identifier(dated),
            REPOSITORY.identifier(later[0].id),
        ]


class TestTheVerbsAnswer:
    def test_identify_reports_the_oldest_datestamp_served(self, db, shelf):
        stamp(db, shelf["public"], datetime(2001, 2, 3, 4, 5, 6))
        stamp(db, shelf["private"], datetime(1990, 1, 1))
        assert respond(db, verb="Identify").findtext(f".//{NS}earliestDatestamp") == "2001-02-03"

    def test_identify_counts_a_tombstone_among_the_datestamps(self, db):
        db.add(OaiTombstone(book_id=7, datestamp=datetime(1999, 1, 1)))
        db.commit()
        assert respond(db, verb="Identify").findtext(f".//{NS}earliestDatestamp") == "1999-01-01"

    def test_identify_advertises_the_day_granularity(self, db):
        """Owner's decision: a datestamp says the day a Book was added, never the second."""
        assert respond(db, verb="Identify").findtext(f".//{NS}granularity") == "YYYY-MM-DD"

    def test_identify_names_the_stored_contact_address(self, db):
        assert respond(db, verb="Identify").findtext(f".//{NS}adminEmail") == "catalogue@library.example"

    def test_list_metadata_formats_names_both(self, db):
        root = respond(db, verb="ListMetadataFormats")
        assert [e.text for e in root.iter(f"{NS}metadataPrefix")] == ["oai_dc", "marc21"]

    def test_list_metadata_formats_for_a_private_book_is_id_does_not_exist(self, db, shelf):
        root = respond(db, verb="ListMetadataFormats", identifier=REPOSITORY.identifier(shelf["private"]))
        assert error_of(root) == "idDoesNotExist"

    def test_get_record_carries_dublin_core_from_the_public_record(self, db, shelf):
        root = respond(
            db, verb="GetRecord", metadataPrefix="oai_dc", identifier=REPOSITORY.identifier(shelf["public"])
        )
        assert root.findtext(f".//{DC}title") == "Chartreuse Windmill"
        assert root.findtext(f".//{DC}creator") == "Ada Lovelace"
        assert root.findtext(f".//{DC}identifier") == "urn:isbn:9780306406157"

    def test_the_request_element_echoes_what_was_accepted(self, db, shelf):
        request = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc").find(f"{NS}request")
        assert request is not None
        assert request.attrib == {"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"}
        assert request.text == REPOSITORY.base_url

    def test_a_record_datestamp_is_the_day_of_the_books(self, db, shelf):
        stamp(db, shelf["public"], datetime(2026, 1, 2, 3, 4, 5))
        root = respond(db, verb="ListIdentifiers", metadataPrefix="oai_dc")
        assert root.findtext(f".//{NS}datestamp") == "2026-01-02"

    def test_control_characters_in_a_title_do_not_break_the_document(self, db, admin):
        db.add(Book(title="Before\x0cafter", added_by_user_id=admin["user"]["id"]))
        db.commit()
        root = respond(db, verb="ListRecords", metadataPrefix="oai_dc")
        assert root.findtext(f".//{DC}title") == "Beforeafter"

    def test_response_date_is_now(self, db):
        text = respond(db, verb="Identify").findtext(f"{NS}responseDate") or ""
        moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        assert abs(moment - datetime.now(UTC).replace(tzinfo=None)) < timedelta(minutes=1)
