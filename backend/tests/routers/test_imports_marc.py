"""Tests for the MARC half of backend/routers/imports.py, and the MARC export.

Both directions of one exchange, in one file, because the assertion that matters
most spans them: a record this app writes is a record this app reads back, and
splitting the two would let the writer and the reader drift with each half green.

The parser itself is `tests/test_marc.py`. What is here is everything that needs
a database or a session: the library mode gate, the matching, what a second
import of the same file does, and what a member may see in an export.
"""

import ast
import inspect
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import main
import marc
import settings_store
from enums import SettingKey
from models import (
    AUTHOR_LINE_MAX,
    CLASSIFICATION_LABEL_MAX,
    CLASSIFICATION_NUMBER_MAX,
    DESCRIPTION_MAX,
    ISBN_MAX,
    PUBLISHER_MAX,
    SERIES_NAME_MAX,
    SUBTITLE_MAX,
    TITLE_MAX,
    Book,
    Classification,
)
from routers import books as books_router
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK
from tests.test_house_rules import _python_sources

MARCXML = "http://www.loc.gov/MARC21/slim"


def library_mode(db, on: bool = True) -> None:
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true" if on else "false")


def record(*fields: str) -> str:
    return f"<record><leader>00000nam a22000003  4500</leader>{''.join(fields)}</record>"


def field(tag: str, *subfields: tuple[str, str]) -> str:
    inner = "".join(f'<subfield code="{c}">{v}</subfield>' for c, v in subfields)
    return f'<datafield tag="{tag}" ind1=" " ind2=" ">{inner}</datafield>'


def collection(*records: str) -> bytes:
    return f'<collection xmlns="{MARCXML}">{"".join(records)}</collection>'.encode()


def a_marc_book(title: str, author: str = "An Author", isbn: str | None = None) -> str:
    fields = [field("245", ("a", title)), field("100", ("a", author))]
    if isbn:
        fields.append(field("020", ("a", isbn)))
    return record(*fields)


def upload(client, headers, content: bytes, path: str = "/api/imports/marc", **params):
    return client.post(
        path,
        files={"file": ("catalogue.xml", content, "application/marcxml+xml")},
        headers=headers,
        params=params,
    )


class TestLibraryModeGatesEverySurface:
    """**Enforced on the server, not by hiding a control.** `routers/public.py`
    states the rule: disabling a button in the browser is advice to one
    client."""

    def test_the_export_refuses_marcxml_with_library_mode_off(self, client, admin, db):
        library_mode(db, False)
        res = client.get("/api/books/export", params={"format": "marcxml"}, headers=admin["headers"])
        assert res.status_code == 403

    def test_the_export_still_serves_csv_with_library_mode_off(self, client, admin, db):
        """The gate is on the format, not on the route. A household exporting a
        spreadsheet is not doing library work."""
        library_mode(db, False)
        res = client.get("/api/books/export", headers=admin["headers"])
        assert res.status_code == 200

    def test_the_import_refuses_with_library_mode_off(self, client, admin, db):
        library_mode(db, False)
        assert upload(client, admin["headers"], collection(a_marc_book("T"))).status_code == 403

    def test_the_preview_refuses_with_library_mode_off(self, client, admin, db):
        library_mode(db, False)
        res = upload(
            client, admin["headers"], collection(a_marc_book("T")),
            path="/api/imports/marc/preview",
        )
        assert res.status_code == 403

    def test_the_gate_is_checked_before_the_file_is_parsed(self, client, admin, db):
        """A refused caller must not be able to spend the server's CPU on a
        parse. The evidence is that a file which would be a 400 is a 403."""
        library_mode(db, False)
        res = upload(client, admin["headers"], b"not xml at all")
        assert res.status_code == 403

    def test_every_member_may_export_marc_not_only_an_admin(self, client, member, db):
        """Library mode is a property of the deployment. A cataloguer is not
        necessarily the account that installed it."""
        library_mode(db)
        res = client.get(
            "/api/books/export", params={"format": "marcxml"}, headers=member["headers"]
        )
        assert res.status_code == 200


class TestTheExport:
    def test_it_answers_marcxml_with_a_filename_a_cataloguer_can_open(self, client, admin, db, make_book):
        library_mode(db)
        make_book(admin["headers"], title="Stoner")

        res = client.get("/api/books/export", params={"format": "marcxml"}, headers=admin["headers"])

        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/marcxml+xml")
        # `.xml`, not `.marcxml`: nothing is registered for the latter.
        assert res.headers["content-disposition"].endswith('.xml"')
        assert MARCXML in res.text

    def test_it_carries_the_classifications_a_marc_record_exists_for(self, client, admin, db, make_book):
        """The ticket's own argument: the call number is the classifications
        table rather than a string, and it is the half another institution
        shelves by.

        **Through a real stored row, which `tests/test_marc.py` cannot do.**
        That file drives the writer with a stand-in carrying real enum members,
        and `classifications.scheme` is a plain `String(20)` column, so a stored
        row hands back a `str`. This test is what caught `is` against the enum
        being False for every row: the export answered 200 and carried no call
        number.
        """
        library_mode(db)
        make_book(
            admin["headers"],
            title="Stoner",
            classifications=[{"scheme": "ddc", "number": "813.54"}],
        )

        res = client.get("/api/books/export", params={"format": "marcxml"}, headers=admin["headers"])

        assert '<subfield code="a">813.54</subfield>' in res.text
        assert 'tag="082"' in res.text

    def test_another_members_private_book_is_not_in_the_export(self, client, admin, member, db, make_book):
        """The rule no child of the epic may relax. Asserted here rather than
        argued from `Shelf.seen_by` being called, because an export is the
        shape that publishes a whole shelf at once."""
        library_mode(db)
        make_book(admin["headers"], title="Secret", is_private=True)
        make_book(member["headers"], title="Shared")

        res = client.get(
            "/api/books/export", params={"format": "marcxml"}, headers=member["headers"]
        )

        assert "Shared" in res.text
        assert "Secret" not in res.text

    def test_an_empty_shelf_is_an_empty_collection_and_not_an_error(self, client, member, db):
        library_mode(db)
        res = client.get(
            "/api/books/export", params={"format": "marcxml"}, headers=member["headers"]
        )
        assert res.status_code == 200
        assert "<collection" in res.text


class TestTheExportIsPagedRatherThanWhole:
    """The shelf is never in memory whole, and the file is complete anyway.

    The route used to ask a `Shelf` for every visible Book at once and hand the
    list to a writer that built one `Element` tree over all of it. Nothing
    bounded either, and the library in library mode is the instance with the
    most books: this arm materialised every one of them for an ordinary
    account, and the CSV arm beside it still does. What replaced it walks the
    shelf a page at a time, so
    what these tests are about is the two things paging can get wrong: a book
    that falls between two pages while the shelf moves under the walk, and a
    page that quietly holds the whole shelf again.
    """

    #: A page a test can build a shelf around. Every test here that uses it
    #: patches the constant rather than building a production sized shelf,
    #: because what is under test is that there is a page boundary and where
    #: it is, not the number. `TestThePageSizeThatBoundsTheExport` is what
    #: holds the number itself.
    PAGE = 3

    @pytest.fixture
    def small_pages(self, monkeypatch):
        monkeypatch.setattr(marc, "EXPORT_PAGE_RECORDS", self.PAGE)
        return self.PAGE

    def a_shelf(self, db, owner, count: int, title=None) -> list[str]:
        """`count` public books, and the ISBNs that name them in the file.

        The ISBN rather than the title, because the titles are deliberately
        allowed to collide unless a test asks otherwise: the walk resumes on
        the primary key and a shelf whose titles are all one string is what
        shows it does not read the title at all.
        """
        isbns = [f"978000000{n:04d}" for n in range(count)]
        db.add_all(
            Book(
                title=title(n) if title else "Ambiguous Title",
                author="Ada Example",
                isbn=isbns[n],
                added_by_user_id=owner["user"]["id"],
            )
            for n in range(count)
        )
        db.commit()
        return isbns

    def export(self, client, headers):
        return client.get(
            "/api/books/export", params={"format": "marcxml"}, headers=headers
        )

    def test_every_book_is_written_exactly_once_when_the_shelf_outruns_a_page(
        self, client, admin, db, small_pages
    ):
        """Seven books over pages of three, all sharing one title.

        Exactly once is the assertion and not merely present: a walk that
        resumes in the wrong place repeats a book as readily as it drops one,
        and a MARCXML collection with a record twice is a catalogue exchange
        that silently double counts.
        """
        library_mode(db)
        isbns = self.a_shelf(db, admin, small_pages * 2 + 1)

        text = self.export(client, admin["headers"]).text

        for isbn in isbns:
            assert text.count(f">{isbn}<") == 1, isbn
        assert text.count("<record>") == len(isbns)

    def test_the_writer_is_never_handed_more_than_one_page_of_books(
        self, client, admin, db, monkeypatch, small_pages
    ):
        """The bound itself, watched at the seam it is applied on.

        Counting the pages the route feeds the writer is what fails if the
        route ever goes back to resolving the whole shelf and passing it as one
        page: that reads identically from the outside, answers 200, and is the
        defect this change exists for.
        """
        library_mode(db)
        isbns = self.a_shelf(db, admin, small_pages * 2 + 1)
        sizes: list[int] = []
        chunks: list[str] = []
        whole = marc.stream

        def recording(pages):
            def counted():
                for page in pages:
                    page = list(page)
                    sizes.append(len(page))
                    yield page

            for chunk in whole(counted()):
                chunks.append(chunk)
                yield chunk

        monkeypatch.setattr(marc, "stream", recording)

        assert self.export(client, admin["headers"]).status_code == 200
        assert sum(sizes) == len(isbns)
        assert max(sizes) <= marc.EXPORT_PAGE_RECORDS
        # One chunk per page, plus the two halves of the wrapper. That is a
        # property of `marc.stream` and it is the dispatch cost this pins: one
        # threadpool hop and one ASGI send a page rather than a record.
        assert len(chunks) == len(sizes) + 2

    def test_the_response_is_handed_a_walk_that_has_not_run(
        self, client, admin, db, monkeypatch, small_pages
    ):
        """What reaches the transport, which is the half the counting misses.

        A route that paged the query and then joined the pages into one string
        satisfies every assertion above: the writer still saw pages, and the
        chunks were still pulled one a page. The defect is what is handed over,
        so that is what this reads.

        **The walk is watched and not only the serialiser**, because the
        serialiser's own state does not answer the question:
        `marc.stream(list(_marcxml_pages(...)))` runs the whole walk, holds
        every Book, and still hands over an unstarted generator. So the state
        of the page generator is what is asserted, at the moment the response
        is built. `GEN_CREATED` on it means not one page had been fetched.
        """
        library_mode(db)
        self.a_shelf(db, admin, small_pages * 2 + 1)
        walks: list[object] = []
        states: list[tuple[str | None, str | None]] = []
        pages = books_router._marcxml_pages

        def watched(*args, **kwargs):
            walk = pages(*args, **kwargs)
            walks.append(walk)
            return walk

        def state(value: object) -> str | None:
            # `None` is what a list or a string reports, which is the shape a
            # route that materialised the walk would hand over.
            return inspect.getgeneratorstate(value) if inspect.isgenerator(value) else None

        def recording(content, *args, **kwargs):
            # Read at the moment it is handed over, not afterwards: by the end
            # of the request both generators are closed and say nothing about
            # when they ran.
            states.append((state(content), state(walks[-1]) if walks else None))
            return StreamingResponse(content, *args, **kwargs)

        # By name: both are module level names in that module rather than part
        # of its declared surface, which mypy refuses to reach through.
        monkeypatch.setattr("routers.books._marcxml_pages", watched)
        monkeypatch.setattr("routers.books.StreamingResponse", recording)

        assert self.export(client, admin["headers"]).status_code == 200
        assert states == [(inspect.GEN_CREATED, inspect.GEN_CREATED)]

    def test_a_book_deleted_behind_the_walk_does_not_take_a_later_one_with_it(
        self, db, admin, small_pages
    ):
        """What an offset would have lost, and the reason the walk uses a key.

        Pages of one export are separate reads: pysqlite leaves a `SELECT`
        outside any transaction, so nothing holds a snapshot across them. Delete
        a book that has already been written and every later row shifts one
        place towards the start, so an offset of three lands one row past where
        it left off and the book in between is in no page at all. Driving the
        generator directly rather than through the route is what lets the
        deletion happen between two pages.
        """
        expected = [f"Book {n:02d}" for n in range(small_pages * 2)]
        self.a_shelf(db, admin, len(expected), title=lambda n: f"Book {n:02d}")

        pages = books_router._marcxml_pages(db, admin["user"]["id"])
        first = next(pages)
        written = [book.title for book in first]
        db.delete(db.get(Book, first[0].id))
        db.commit()
        written += [book.title for page in pages for book in page]

        assert written == expected

    def test_an_empty_shelf_yields_no_pages_at_all(self, db, admin, small_pages):
        """The `if not books` arm, which the route level test cannot separate
        from the wrapper being written for an empty collection. It says nothing
        about how many times the walk asked."""
        assert list(books_router._marcxml_pages(db, admin["user"]["id"])) == []

    def test_a_shelf_of_exactly_one_page_yields_no_empty_page_after_it(
        self, db, admin, small_pages
    ):
        """A last page that is exactly full is indistinguishable from a full
        page with more behind it, so the walk asks again and the answer is
        empty. What this pins is that the empty answer is not handed on as a
        page: `marc.stream` would write an empty chunk for it, and a caller
        counting chunks would see one page too many.
        """
        self.a_shelf(db, admin, small_pages)

        pages = list(books_router._marcxml_pages(db, admin["user"]["id"]))

        assert [len(page) for page in pages] == [small_pages]

    def test_a_book_retitled_behind_the_walk_is_still_written(
        self, db, admin, small_pages
    ):
        """What a walk resuming on the title would have lost.

        `PATCH /api/books/{book_id}` can retitle a book, so a title is a key
        that moves. Retitle a book that has not been written yet so that it
        sorts before everything already written, and a walk asking for the
        rows after that title skips it for good, silently and with a 200. The
        primary key cannot move, so this is a book in the file.
        """
        expected = [f"Book {n:02d}" for n in range(small_pages * 2)]
        self.a_shelf(db, admin, len(expected), title=lambda n: f"Book {n:02d}")

        pages = books_router._marcxml_pages(db, admin["user"]["id"])
        written = [book.title for book in next(pages)]
        later = db.query(Book).filter(Book.title == expected[-1]).one()
        later.title = "Aardvark"
        db.commit()
        written += [book.title for page in pages for book in page]

        assert sorted(written) == sorted([*expected[:-1], "Aardvark"])

    def test_a_failure_part_way_through_leaves_a_document_no_parser_accepts(
        self, admin, db, monkeypatch, small_pages
    ):
        """The one thing streaming gives up, and what is left in its place.

        The status line goes out before the first record, so a writer that
        raises on page two cannot answer 500 any more. What it leaves instead
        is a `<collection>` that is never closed, and no XML parser accepts
        that, so a half written catalogue exchange is an error on the
        cataloguer's side rather than a short file that reads as complete. That
        is the silence `docs/decisions.md` refuses for an oversized upload,
        answered on the export side.

        Its own client, because the shared one re-raises a server exception
        instead of handing back the bytes that reached the wire.
        """
        library_mode(db)
        self.a_shelf(db, admin, small_pages * 2)
        written = marc._record_element
        calls = {"n": 0}

        def failing(book):
            calls["n"] += 1
            if calls["n"] > small_pages:
                raise RuntimeError("the writer gave out")
            return written(book)

        monkeypatch.setattr(marc, "_record_element", failing)

        with TestClient(main.app, raise_server_exceptions=False) as client:
            res = self.export(client, admin["headers"])

        # The records that did reach the wire, and no closing tag: an empty
        # body would fail to parse too and would say nothing about truncation.
        assert res.text.count("<record>") == small_pages
        assert "</collection>" not in res.text
        with pytest.raises(ElementTree.ParseError):
            ElementTree.fromstring(res.content)

    def test_a_failure_before_the_first_page_is_also_a_200(
        self, admin, db, monkeypatch, small_pages
    ):
        """The half of that property a failure on page two does not reach.

        The opening tag is yielded before the walk is touched, so the status
        line is already sent when the first query runs. There is no page to be
        part of the way through: a database error on the very first one
        answers 200 with a `<collection>` and nothing else, where before this
        change it was a clean 500. Pinned rather than reasoned, because it is
        the part of the trade that is easiest to assume away.
        """
        library_mode(db)
        self.a_shelf(db, admin, small_pages)

        def refusing(*_args, **_kwargs):
            raise RuntimeError("the shelf could not be read")
            # Unreachable, and it is what makes this a generator function
            # rather than one that raises when it is called. The route has to
            # get its walk and fail on the first `next`, which is where a
            # failing query lands: a call that raised would be a 500 and would
            # prove the opposite of what this test is for. Not a
            # `# pragma: no cover`, which this tree treats as giving up on
            # covering a line rather than as saying why one cannot run.
            yield

        monkeypatch.setattr("routers.books._marcxml_pages", refusing)

        with TestClient(main.app, raise_server_exceptions=False) as client:
            res = self.export(client, admin["headers"])

        assert res.status_code == 200
        # The opening tag **present**, first: without it every assertion below
        # passes on an empty body, and an empty body is what a `stream` that
        # pulled the first page before yielding the wrapper would produce,
        # which is the arrangement this test exists to say is not the one.
        assert "<collection" in res.text
        assert "<record>" not in res.text
        assert "</collection>" not in res.text
        with pytest.raises(ElementTree.ParseError):
            ElementTree.fromstring(res.content)

    def test_a_shelf_smaller_than_a_page_is_still_one_document(
        self, client, admin, db, make_book, small_pages
    ):
        """The wrapper is no longer serialised from a `<collection>` element,
        so what it produces is re-derived from `ElementTree` here rather than
        described in a comment."""
        library_mode(db)
        make_book(admin["headers"], title="Stoner")

        res = self.export(client, admin["headers"])

        probe = ElementTree.tostring(
            ElementTree.Element("probe"), encoding="unicode", xml_declaration=True
        )
        assert res.text.startswith(probe[: probe.index("<probe")])
        # Parsed from bytes: `ElementTree` refuses a `str` carrying an encoding
        # declaration, which is the declaration asserted one line above.
        assert ElementTree.fromstring(res.content).tag == f"{{{MARCXML}}}collection"


class TestThePageSizeThatBoundsTheExport:
    """What one page weighs at the widest a write through the API can produce.

    This is what says whether `EXPORT_PAGE_RECORDS` is a page or the whole
    shelf arriving under another name. `tests/test_sru.py` measures
    `sru.MAX_RECORDS` the same way, against a 2,000 character description
    rather than a declaration.

    **Widest is two questions and this class exists because the second one was
    missed twice.** The first is how wide a field may be, which is a
    `max_length`, read here off its declaration rather than retyped, the way
    `importing.within_bounds` reads every column it checks. The fill character
    is the other half of that question: a `max_length` counts characters and a
    page counts bytes, and `ElementTree` writes `&` as five of them.

    **The second is how many fields a record has, and no length answers it.**
    `700` repeats once per credited name, `marc._credited_names` splits
    `author` on commas, and nothing bounds the count inside
    `AUTHOR_LINE_MAX`, so the same 500 characters is one name or 250 of them
    and each extra one costs its scaffolding rather than its bytes. A fixture
    with one long name produces the fewest `700` fields there can be, which is
    none, and is 36% under the real worst case.

    **The line this fixture draws is what a write through the API can produce,
    and it is drawn once.** `language`, `year`, `page_count` and
    `series_index` are validated for shape as well as length, so filling them
    would measure a record the API refuses; they carry a real value.
    Everything bounded only by length is filled.

    **What a restore can produce is wider, and it is outside that line on
    purpose.** `backup.py` inserts through Core, so `@validates` never fires
    and no schema bound applies: a restored archive can hold a description
    past `DESCRIPTION_MAX`, an `isbn` of any 20 characters, and more than
    `MAX_CLASSIFICATIONS_PER_BOOK` rows on one book. Measured, 32
    classification rows on the otherwise widest record is 144,155 bytes, a
    page of 13.75 MiB, past the ceiling below. None of it is built in here,
    because a restore beats any number this class could name and the ceiling
    is a claim about the writer's shape rather than a platform limit.
    `models.py` records a 3,000,256 byte description that arrived that way.

    **`isbn` is the one filled field that crosses the line**, and it is
    deliberate: it costs 87 bytes of the widest record, it is the cheapest
    demonstration that the two rules differ, and leaving it short would make
    the ceiling read as if the restore path had been forgotten.

    Driven against the writer, and the Books are never saved: bytes per record
    is the writer's property alone, and a page of rows through the API would
    be measuring the fixtures.
    """

    #: What a full page of the widest records may weigh.
    #:
    #: Twelve mebibytes against a measured 9.74, which is 102,107 bytes for one
    #: such record. **A tripwire on the record's shape and not a platform
    #: limit**: nothing enforces it at runtime and no deployment was measured
    #: against it. What it does is fail when a field is added to the writer, or
    #: made repeatable, or given a wider bound, so that the table at
    #: `marc.EXPORT_PAGE_RECORDS` stops being quietly wrong.
    CEILING_BYTES = 12_582_912

    #: The fills, and what each is here to show. `w` is the number a careless
    #: version of this class would have taken; `&` is what escaping does to the
    #: same declared maximum.
    FILLS = ("w", "ä", "&")

    #: The most credited names `AUTHOR_LINE_MAX` characters can hold, as
    #: `x,x,x,...`: one character a name and one separator.
    MOST_CREDITS = AUTHOR_LINE_MAX // 2

    def widest_book(self, n: int, fill: str, credits: int = 1) -> Book:
        """Every length bounded field at its maximum, and `credits` names.

        `credits` is separate from the fill because the two answer the two
        questions this class is about, and a fixture that could not vary them
        apart is the one that missed the second.

        **Two values, and a third is refused rather than clamped.** The author
        column is at its declared maximum at either end, 500 characters as one
        name or as 250 of them, and nothing in between is: `x,` repeated three
        times is six characters, so a fixture asked for three credits would
        quietly measure a narrow record while reading as a wide one.
        """
        if credits not in (1, self.MOST_CREDITS):
            raise ValueError(
                f"credits is 1 or {self.MOST_CREDITS}: those are the two that "
                "fill AUTHOR_LINE_MAX, and anything between them measures a "
                "record narrower than this fixture claims to build"
            )
        author = (
            fill * AUTHOR_LINE_MAX if credits == 1 else (fill + ",") * self.MOST_CREDITS
        )
        book = Book(
            title=fill * TITLE_MAX,
            subtitle=fill * SUBTITLE_MAX,
            author=author,
            publisher=fill * PUBLISHER_MAX,
            year=1974,
            language="de",
            page_count=412,
            isbn=fill * ISBN_MAX,
            description=fill * DESCRIPTION_MAX,
            series_name=fill * SERIES_NAME_MAX,
            series_index=1.0,
        )
        book.classifications = [
            Classification(
                scheme="gnd",
                number=fill * CLASSIFICATION_NUMBER_MAX,
                label=fill * CLASSIFICATION_LABEL_MAX,
            )
            for _ in range(MAX_CLASSIFICATIONS_PER_BOOK)
        ]
        return book

    def page_bytes(self, fill: str, credits: int = 1) -> int:
        page = [
            self.widest_book(n, fill, credits)
            for n in range(marc.EXPORT_PAGE_RECORDS)
        ]
        written = "".join(marc.stream([page]))
        assert written.count("<record>") == marc.EXPORT_PAGE_RECORDS
        return len(written.encode())

    def test_a_full_page_of_the_widest_records_stays_under_the_ceiling(self):
        """The assertion is on the finished page, which is not the peak.

        Building it holds every record's string and the joined result at once:
        measured, 24.01 MiB for this 9.74 MiB page, 2.47 times. The route
        level table at `marc.EXPORT_PAGE_RECORDS` is a typical page rather
        than this one, so it is the shelf independence it demonstrates and not
        the worst case. What this number bounds is the record's shape."""
        assert self.page_bytes("&", self.MOST_CREDITS) < self.CEILING_BYTES

    def test_the_fill_character_is_part_of_what_decides_the_page(self):
        """The first of the two questions: a `max_length` is characters."""
        one_byte, two_byte, escaped = (self.page_bytes(fill) for fill in self.FILLS)

        assert one_byte < two_byte < escaped
        assert escaped > 4 * one_byte

    #: What one extra credited name costs a record, **net**.
    #:
    #: The `700` datafield and its two subfields are 114 bytes; the same name
    #: leaving `100` takes that field from the whole 500 character fill down
    #: to one, so the record gains 109. Measured at the widest fill. 100 is
    #: the conservative figure the assertion uses, and neither number moves
    #: when another field's bound does, which is the point of asserting the
    #: difference rather than a ratio.
    SCAFFOLDING_PER_CREDIT = 100

    def test_the_number_of_credited_names_is_the_other_half(self):
        """The second question, and the one a fixture of one long name cannot
        see: same column, same declared length, more fields.

        **Asserted as the difference the names are responsible for, not as a
        ratio.** A ratio has the one name page underneath it, and that page
        grows with every other bound in the record, so the ratio falls as the
        description widens and the test fails with nothing wrong: measured,
        the margin is gone by `DESCRIPTION_MAX` 13,200. The scaffolding a
        `700` field costs does not move when another field does.
        """
        one_name = self.page_bytes("&")
        many_names = self.page_bytes("&", self.MOST_CREDITS)

        extra_names = self.MOST_CREDITS - 1
        assert many_names - one_name > (
            marc.EXPORT_PAGE_RECORDS * extra_names * self.SCAFFOLDING_PER_CREDIT
        )


class TestNoProductionModuleWritesAWholeCollection:
    """`marc.write` materialises a document, so no route may reach for it.

    That is how this ticket's defect was written: the export called it with a
    shelf nothing bounded. The docstring on `write` says so and a docstring
    stops nobody, so the rule is parsed rather than stated. `marc.stream` is
    what a route wants.

    **The corpus is `test_house_rules._python_sources`** and not a walk of this
    module's own. That module records what a private walk costs, twice: one
    spelled `"tests" not in path.parts and ".venv" not in path.parts` missed
    the cache the pipeline builds under `backend/`, and one asked absolutely
    returned nothing at all from a checkout under a directory called `tests`.
    Both are this repository's standing rule about enumerating the spellings of
    something derivable, and importing the walk is how a rule stops writing its
    own.

    **What it catches is a call to `write` and not the property behind it.**
    Both names a module member can have, the attribute on the imported module
    and the bare name an `import from` binds, read off the parse so that a
    mention in prose is not a finding. It does not catch `import marc as m`,
    `getattr`, or a route joining `marc.stream` into one string itself. The
    property, that this route holds no whole document, is pinned behaviourally
    by `TestTheExportIsPagedRatherThanWhole` instead.
    """

    #: The one module the rule cannot apply to, by resolved path rather than by
    #: basename: a later `routers/marc.py` would otherwise be exempt too.
    THE_WRITER = Path(marc.__file__).resolve()

    def production_modules(self, root: Path | None = None) -> list[Path]:
        """Every module the rule applies to: the app, minus the writer itself."""
        sources = _python_sources(root) if root is not None else _python_sources()
        return [path for path in sources if path.resolve() != self.THE_WRITER]

    def calls_to_write(self, root: Path | None = None) -> list[str]:
        offenders: list[str] = []
        for path in self.production_modules(root):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            bound = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "marc"
                for alias in node.names
                if alias.name == "write"
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                called = node.func
                if (
                    isinstance(called, ast.Attribute)
                    and called.attr == "write"
                    and isinstance(called.value, ast.Name)
                    and called.value.id == "marc"
                ) or (isinstance(called, ast.Name) and called.id in bound):
                    offenders.append(f"{path.name}:{node.lineno}")
        return offenders

    def test_it_reads_the_modules_it_is_meant_to(self):
        """A walk that stopped matching would report nothing, forever."""
        names = {path.name for path in self.production_modules()}
        assert {"sru.py", "shelf.py", "books.py"} <= names
        assert "test_imports_marc.py" not in names
        # **The exemption is live rather than dead.** Asserting the writer is
        # absent from the filtered list only restates the filter. What can go
        # wrong is the walk ceasing to return it, and then the exemption
        # quietly guards nothing and this test still passes.
        assert self.THE_WRITER in {path.resolve() for path in _python_sources()}

    def test_a_planted_call_is_reported_in_both_spellings(self, tmp_path):
        """The detector, driven against a tree built for it.

        A rule asserted only against this checkout is a rule nobody has watched
        fail, which `tests/test_marc.py` records paying for: three single anchor
        mutations left every test in its class green while the rule reported
        nothing. So the corpus takes a root and this plants both spellings in
        one.
        """
        (tmp_path / "attribute_form.py").write_text(
            "import marc\n\n\ndef go(books):\n    return marc.write(books)\n"
        )
        (tmp_path / "import_form.py").write_text(
            "from marc import write\n\n\ndef go(books):\n    return write(books)\n"
        )
        (tmp_path / "innocent.py").write_text(
            "import marc\n\n\ndef go(pages):\n    return marc.stream(pages)\n"
        )

        reported = self.calls_to_write(tmp_path)

        assert sorted(reported) == ["attribute_form.py:5", "import_form.py:5"]

    def test_nothing_outside_marc_py_calls_write(self):
        offenders = self.calls_to_write()
        assert not offenders, (
            "marc.write materialises the whole document and no production "
            f"module may call it; use marc.stream: {offenders}"
        )


class TestTheImport:
    def test_it_creates_the_records_the_catalogue_does_not_hold(self, client, admin, db):
        library_mode(db)

        res = upload(
            client, admin["headers"],
            collection(a_marc_book("Stoner", "John Williams", "9780099561545")),
        )

        assert res.status_code == 200, res.text
        assert res.json()["created"] == 1
        book = db.query(Book).filter(Book.title == "Stoner").one()
        assert (book.author, book.isbn) == ("John Williams", "9780099561545")

    def test_a_created_book_arrives_unconfirmed(self, client, admin, db):
        """Another institution's record says that institution holds the book."""
        library_mode(db)
        upload(client, admin["headers"], collection(a_marc_book("Stoner")))

        assert db.query(Book).filter(Book.title == "Stoner").one().ownership == "unknown"

    def test_it_writes_the_classifications_a_cataloguer_would_have_retyped(self, client, admin, db):
        library_mode(db)

        upload(
            client, admin["headers"],
            collection(
                record(
                    field("245", ("a", "Stoner")),
                    field("082", ("a", "813.54")),
                    field("650", ("a", "Schatz"), ("0", "(DE-588)4203576-4")),
                )
            ),
        )

        book = db.query(Book).filter(Book.title == "Stoner").one()
        assert sorted((c.scheme, c.number) for c in book.classifications) == [
            ("ddc", "813.54"),
            ("gnd", "4203576-4"),
        ]

    def test_nothing_personal_is_written(self, client, admin, db):
        """A catalogue record carries no reading history, so `MarcImport` never
        touches a `user_books` row and the count comes back zero for that reason
        rather than because nothing needed changing."""
        library_mode(db)
        res = upload(client, admin["headers"], collection(a_marc_book("Stoner")))
        assert res.json()["statuses_updated"] == 0

    def test_a_record_with_no_title_is_reported_and_the_rest_complete(self, client, admin, db):
        """The ticket's third user story, through the route."""
        library_mode(db)

        res = upload(
            client, admin["headers"],
            collection(
                record(field("020", ("a", "9780099561545"))),
                a_marc_book("Kept"),
            ),
        )

        assert res.json()["created"] == 1
        assert res.json()["skipped"] == 1

    def test_create_missing_off_reports_what_it_did_not_add(self, client, admin, db):
        library_mode(db)

        res = upload(
            client, admin["headers"], collection(a_marc_book("Stoner")),
            create_missing=False,
        )

        assert res.json()["unmatched_titles"] == ["Stoner"]
        assert res.json()["created"] == 0
        assert db.query(Book).filter(Book.title == "Stoner").count() == 0

    def test_a_file_that_is_not_marc_is_a_400_with_a_reason(self, client, admin, db):
        """"0 books imported" tells somebody who picked the wrong file
        nothing."""
        library_mode(db)
        res = upload(client, admin["headers"], b"Title,Author\nStoner,John Williams\n")
        assert res.status_code == 400
        assert "not XML" in res.json()["detail"]

    def test_an_empty_file_is_refused(self, client, admin, db):
        library_mode(db)
        assert upload(client, admin["headers"], b"").status_code == 400


class TestImportingTwiceDoesNotDoubleTheCatalogue:
    """The ticket's fourth user story, and the reason the preview reports
    `already_held`."""

    def test_the_same_file_twice_creates_nothing_the_second_time(self, client, admin, db):
        library_mode(db)
        payload = collection(a_marc_book("Stoner", "John Williams", "9780099561545"))

        first = upload(client, admin["headers"], payload).json()
        second = upload(client, admin["headers"], payload).json()

        assert (first["created"], first["matched"]) == (1, 0)
        assert (second["created"], second["matched"]) == (0, 1)
        assert db.query(Book).filter(Book.title == "Stoner").count() == 1

    def test_one_file_naming_the_same_work_twice_creates_it_once(self, client, admin, db):
        """A freshly created Book has to be findable by later records of the
        same file, or the second one raises on the ISBN index and takes the
        whole transfer with it."""
        library_mode(db)
        one = a_marc_book("Stoner", "John Williams", "9780099561545")

        res = upload(client, admin["headers"], collection(one, one))

        assert res.status_code == 200, res.text
        assert db.query(Book).filter(Book.title == "Stoner").count() == 1

    def test_a_record_matching_on_author_and_title_is_not_created_again(self, client, admin, db, make_book):
        """No ISBN on either side, so the match is the identity key."""
        library_mode(db)
        make_book(admin["headers"], title="The Stoner", author="John Williams")

        res = upload(
            client, admin["headers"], collection(a_marc_book("Stoner", "John Williams"))
        )

        assert res.json()["matched"] == 1
        assert db.query(Book).count() == 1

    def test_the_same_title_by_a_different_author_is_a_different_book(self, client, admin, db, make_book):
        """**The reason matching is not on title alone.** Every library holds
        more than one *Selected poems*, and folding them is discovered months
        later with no record of what was lost."""
        library_mode(db)
        make_book(admin["headers"], title="Selected poems", author="Sylvia Plath")

        res = upload(
            client, admin["headers"],
            collection(a_marc_book("Selected poems", "Ted Hughes")),
        )

        assert res.json()["created"] == 1
        assert db.query(Book).count() == 2

    def test_a_matched_book_gains_the_fields_it_lacked_and_keeps_the_ones_it_had(
        self, client, admin, db, make_book
    ):
        library_mode(db)
        make_book(admin["headers"], title="Stoner", author="John Williams", publisher="Vintage")

        upload(
            client, admin["headers"],
            collection(
                record(
                    field("245", ("a", "Stoner")),
                    field("100", ("a", "John Williams")),
                    field("264", ("b", "NYRB"), ("c", "1965")),
                    field("300", ("a", "288 pages")),
                )
            ),
        )

        book = db.query(Book).filter(Book.title == "Stoner").one()
        assert book.publisher == "Vintage"
        assert (book.year, book.page_count) == (1965, 288)


class TestThePreview:
    def test_it_writes_nothing(self, client, admin, db):
        library_mode(db)

        res = upload(
            client, admin["headers"], collection(a_marc_book("Stoner")),
            path="/api/imports/marc/preview",
        )

        assert res.status_code == 200, res.text
        assert db.query(Book).count() == 0

    def test_it_counts_what_is_already_held_before_anything_is_written(self, client, admin, db, make_book):
        """The question this endpoint exists for: will importing this double my
        catalogue."""
        library_mode(db)
        make_book(admin["headers"], title="Stoner", author="John Williams")

        res = upload(
            client, admin["headers"],
            collection(a_marc_book("Stoner", "John Williams"), a_marc_book("New Book")),
            path="/api/imports/marc/preview",
        )

        body = res.json()
        assert (body["total_records"], body["readable"], body["already_held"]) == (2, 2, 1)

    def test_it_shows_the_classifications_so_a_bad_082_is_visible_first(self, client, admin, db):
        library_mode(db)

        res = upload(
            client, admin["headers"],
            collection(record(field("245", ("a", "Stoner")), field("082", ("a", "813.54")))),
            path="/api/imports/marc/preview",
        )

        assert res.json()["rows"][0]["classifications"] == ["ddc:813.54"]


class TestTheRoundTripThroughTheApi:
    def test_a_book_exported_and_imported_into_an_empty_catalogue_comes_back(
        self, client, admin, member, db, make_book
    ):
        """The ticket's first testing decision, end to end: export a Book,
        import it, compare the Book.

        Imported as a **different member**, which is what makes it a transfer
        rather than a no-op: the same account would match its own book on the
        ISBN and create nothing.
        """
        library_mode(db)
        make_book(
            admin["headers"],
            title="Stoner",
            author="John Williams",
            isbn="9780099561545",
            publisher="Vintage",
            year=1965,
        )
        exported = client.get(
            "/api/books/export", params={"format": "marcxml"}, headers=admin["headers"]
        ).text

        # The original is removed, so what comes back is built from the file
        # rather than found.
        db.query(Book).delete()
        db.commit()

        res = upload(client, member["headers"], exported.encode("utf-8"))

        assert res.json()["created"] == 1
        book = db.query(Book).one()
        assert (book.title, book.author, book.isbn, book.publisher, book.year) == (
            "Stoner",
            "John Williams",
            "9780099561545",
            "Vintage",
            1965,
        )


class TestWhatAnUploadedRecordMayStore:
    """The bounds every other writer of these columns applies, applied here.

    `POST /api/books` refuses an over-long value with a 422 and the CSV importer
    truncates it. This path had neither, and the cost was measured rather than
    imagined: one 3.7 MB upload of a single record stored a 3,000,000 character
    title into a `String(500)` column, and `GET /api/books` then answered with
    3.8 MB. SQLite does not enforce a `VARCHAR` length, so nothing failed.
    """

    def test_an_over_long_title_is_cut_to_the_column(self, client, admin, db):
        library_mode(db)

        upload(client, admin["headers"], collection(a_marc_book("T" * 600)))

        assert len(db.query(Book).one().title) == 500

    def test_an_over_long_author_and_publisher_are_cut_too(self, client, admin, db):
        """Not the title alone. A guard proved on one field and trusted for the
        fields beside it is the shape this repository keeps finding."""
        library_mode(db)

        upload(
            client, admin["headers"],
            collection(
                record(
                    field("245", ("a", "Stoner")),
                    field("100", ("a", "A" * 600)),
                    field("264", ("b", "P" * 400), ("c", "1965")),
                )
            ),
        )

        book = db.query(Book).one()
        assert (len(book.author), len(book.publisher)) == (500, 255)

    def test_an_open_ended_marc_date_is_stored_as_no_date(self, client, admin, db):
        """`9999` is MARC's own date for a continuing resource and
        `POST /api/books` bounds `year` at 2200. Dropped rather than clamped:
        storing 2200 would assert a date nobody supplied."""
        library_mode(db)

        upload(
            client, admin["headers"],
            collection(record(field("245", ("a", "Stoner")), field("264", ("c", "9999")))),
        )

        assert db.query(Book).one().year is None

    def test_a_series_number_past_the_ceiling_is_dropped(self, client, admin, db):
        """**This is the one that takes the container down, not just the row.**
        `series_index` is `le=1000` on every API path. A ten character `245 $n`
        stores `1e9`, and `GET /api/books/series` then computes
        `set(range(1, max(held) + 1))`, which at a measured 70.5 bytes and 0.624
        seconds per million elements is roughly 70 GB and ten minutes, again on
        every request until the row is found."""
        library_mode(db)

        upload(
            client, admin["headers"],
            collection(
                record(
                    field("245", ("a", "Harry Potter"), ("n", "1000000000"), ("p", "The Stone")),
                )
            ),
        )

        book = db.query(Book).one()
        assert book.series_index is None
        # The series view still answers, which is the property the bound exists
        # for rather than the stored value.
        assert client.get("/api/books/series", headers=admin["headers"]).status_code == 200

    def test_a_matched_book_takes_a_bounded_value_too(self, client, admin, db, make_book):
        """The gap filler writes the same columns from the same record."""
        library_mode(db)
        make_book(admin["headers"], title="Stoner", author="John Williams")

        upload(
            client, admin["headers"],
            collection(
                record(
                    field("245", ("a", "Stoner")),
                    field("100", ("a", "John Williams")),
                    field("264", ("b", "P" * 400), ("c", "1965")),
                )
            ),
        )

        assert len(db.query(Book).one().publisher) == 255


class TestTruncationDoesNotBreakMatching:
    """**The bound and the idempotence have to agree, and at first they did
    not.**

    The identity key is built from a title and an author, the column holds the
    truncated value, and the index is keyed on what is stored. Bounding after
    matching meant a record with a 600 character title never matched itself:
    importing the same file twice created the Book twice and the preview
    reported nothing already held, which is the one number that screen exists
    for.
    """

    def test_an_over_long_record_imported_twice_is_one_book(self, client, admin, db):
        library_mode(db)
        payload = collection(a_marc_book("T" * 600, "A" * 600))

        first = upload(client, admin["headers"], payload).json()
        second = upload(client, admin["headers"], payload).json()

        assert (first["created"], first["matched"]) == (1, 0)
        assert (second["created"], second["matched"]) == (0, 1)
        assert db.query(Book).count() == 1

    def test_the_preview_sees_an_over_long_record_it_already_holds(self, client, admin, db):
        """`already_held` was 0 for exactly the records the bound acts on."""
        library_mode(db)
        payload = collection(a_marc_book("T" * 600, "A" * 600))
        upload(client, admin["headers"], payload)

        body = upload(
            client, admin["headers"], payload, path="/api/imports/marc/preview"
        ).json()

        assert body["already_held"] == 1

    def test_two_titles_agreeing_for_500_characters_merge_and_lose_an_isbn(
        self, client, admin, db
    ):
        """The cost of matching on the truncated key, named rather than glossed.

        Two titles agreeing for 500 characters are byte identical in the column,
        so creating both would make two Books the duplicate finder flags as one.
        **What the merge costs is the second record's identifiers**, which is
        the half the first version of this test claimed the catalogue could not
        hold: `isbn`, `year` and `publisher` are columns, the two records differ in
        them, and `_fill_marc_gaps` fills only where the Book has nothing.

        Asserted rather than argued, so nobody has to take the docstring's word
        for what is dropped.
        """
        library_mode(db)

        res = upload(
            client, admin["headers"],
            collection(
                a_marc_book("X" * 500 + "AAA", "One Author", "9780099561545"),
                a_marc_book("X" * 500 + "BBB", "One Author", "9780345339683"),
            ),
        )

        assert (res.json()["created"], res.json()["matched"]) == (1, 1)
        assert db.query(Book).count() == 1
        # The first record's ISBN survives and the second's is nowhere.
        book = db.query(Book).one()
        assert book.isbn == "9780099561545"
        assert db.query(Book).filter(Book.isbn == "9780345339683").count() == 0

    def test_an_over_long_description_is_cut_to_the_bound(self, client, admin, db):
        """`description` had no bound on either path, so the importer honouring
        the API's contract stored it whole: measured, a 3,000,256 byte upload
        made `GET /api/books` answer with 3,203,366 bytes, and it is on the list
        payload so every page pays. `models.DESCRIPTION_MAX` closes it on
        `POST /api/books` too, which is where the absence really was."""
        library_mode(db)

        upload(
            client, admin["headers"],
            collection(
                record(field("245", ("a", "Stoner")), field("520", ("a", "D" * 20_000)))
            ),
        )

        assert len(db.query(Book).one().description) == 10_000


class TestAMatchedBookNeverGainsAnIsbn:
    """The one column the gap filler must not write, and why.

    Found by the security seat while narrowing the `blocked` count: a record
    whose ISBN belongs to a Book this member cannot see, whose title and author
    match one they can, is **matched** rather than blocked. `MarcIndex.find`
    resolves it on the identity key, so `isbn_is_taken` is never consulted.

    If `isbn` were in `_MARC_GAP_FIELDS` the filler would then write the
    invisible Book's ISBN onto the visible one and trip `books.isbn`'s unique
    index at the commit, after the whole file had been walked: a five thousand
    record transfer writing nothing and answering 500. The incoming ISBN is
    dropped instead, which is the cheaper loss.

    Nothing else would notice the tuple gaining one entry, which is the whole
    reason this exists.
    """

    def test_isbn_is_in_neither_tuple_the_writers_walk(self):
        from importing import _MARC_GAP_FIELDS, _MARC_RECORD_FIELDS

        assert "isbn" not in _MARC_GAP_FIELDS
        assert "isbn" not in _MARC_RECORD_FIELDS

    def test_the_gap_filter_drops_an_isbn_the_create_path_grew(self):
        """The arm above reads today's tuples, so it goes red only after the
        create path has already gained the name. This one asks the filter what
        it would do with one: `book_columns.WORK_DETAIL` holds neither `isbn`
        nor `title`, so the gap filler cannot inherit either however the
        importer's own tuple grows. A filter naming `title` alone returns the
        `isbn` here."""
        from importing import _gap_fields

        assert _gap_fields(("isbn", "title", "author", "publisher")) == (
            "author",
            "publisher",
        )

    def test_a_record_matching_on_title_keeps_its_isbn_out_of_the_catalogue(
        self, client, admin, member, db, make_book
    ):
        """The shape in full: the collision is never reached, so the transfer
        completes and the private book is untouched."""
        library_mode(db)
        make_book(admin["headers"], title="Hidden", isbn="9780099561545", is_private=True)
        make_book(member["headers"], title="Stoner", author="John Williams")

        res = upload(
            client, member["headers"],
            collection(a_marc_book("Stoner", "John Williams", "9780099561545")),
        )

        assert res.status_code == 200, res.text
        assert (res.json()["matched"], res.json()["created"]) == (1, 0)
        # The visible Book did not take the private one's ISBN, so nothing
        # collided and nothing was disclosed.
        assert db.query(Book).filter(Book.title == "Stoner").one().isbn is None
        assert db.query(Book).filter(Book.isbn == "9780099561545").count() == 1


class TestTheWholeFileBeingWrong:
    def test_a_declared_multi_byte_encoding_is_a_400_and_not_a_500(self, client, admin, db):
        """`ElementTree.fromstring` raises `ValueError` rather than
        `ParseError` for one of these, and a handler catching only the second
        answered 500 with a traceback on a 92 byte body."""
        library_mode(db)
        body = (
            '<?xml version="1.0" encoding="EUC-JP"?>'
            f'<collection xmlns="{MARCXML}"><record/></collection>'
        ).encode("ascii")

        res = upload(client, admin["headers"], body)

        assert res.status_code == 400
        assert "multi-byte" in res.json()["detail"]

    def test_a_body_declaring_more_than_the_cap_never_reaches_the_parser(self, client, admin, db):
        """The ticket's "an oversized file aborts the read rather than being
        parsed", at the layer that can actually promise it: the body size
        middleware answers on the declared length, before Starlette spools a
        byte of it to disk."""
        library_mode(db)

        res = client.post(
            "/api/imports/marc",
            headers=admin["headers"] | {"content-length": str(50 * 1024 * 1024)},
            content=b"",
        )

        assert res.status_code == 413


class TestThePreviewCountsBothRefusals:
    def test_a_record_the_import_will_refuse_is_counted_as_blocked(
        self, client, admin, member, db, make_book
    ):
        """**`readable - already_held` overstated what an import would add.**
        A record whose ISBN belongs to a Book the member cannot see is neither
        held nor creatable, so the preview promised a record the import then
        refused."""
        library_mode(db)
        make_book(admin["headers"], title="Secret", isbn="9780099561545", is_private=True)

        res = upload(
            client, member["headers"],
            collection(a_marc_book("Something else", "An Author", "9780099561545")),
            path="/api/imports/marc/preview",
        )

        body = res.json()
        assert (body["readable"], body["already_held"], body["blocked"]) == (1, 0, 1)

    def test_the_preview_and_the_import_agree_on_that_record(
        self, client, admin, member, db, make_book
    ):
        """The two numbers are computed by the same index and the same
        predicates, so this is what says they cannot drift."""
        library_mode(db)
        make_book(admin["headers"], title="Secret", isbn="9780099561545", is_private=True)
        payload = collection(a_marc_book("Something else", "An Author", "9780099561545"))

        preview = upload(
            client, member["headers"], payload, path="/api/imports/marc/preview"
        ).json()
        result = upload(client, member["headers"], payload).json()

        assert preview["blocked"] == 1
        assert (result["created"], result["skipped"]) == (0, 1)

    def test_a_blocked_record_never_names_the_book_it_collided_with(
        self, client, admin, member, db, make_book
    ):
        """A count, never a title. Naming it would be an oracle for "does a
        private book with this ISBN exist in this house"."""
        library_mode(db)
        make_book(admin["headers"], title="Secret", isbn="9780099561545", is_private=True)

        res = upload(
            client, member["headers"],
            collection(a_marc_book("Something else", "An Author", "9780099561545")),
        )

        assert "Secret" not in res.text
        assert res.json()["unmatched_titles"] == []
