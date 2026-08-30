"""Tests for the MARC half of backend/routers/imports.py, and the MARC export.

Both directions of one exchange, in one file, because the assertion that matters
most spans them: a record this app writes is a record this app reads back, and
splitting the two would let the writer and the reader drift with each half green.

The parser itself is `tests/test_marc.py`. What is here is everything that needs
a database or a session: the library mode gate, the matching, what a second
import of the same file does, and what a member may see in an export.
"""

import settings_store
from enums import SettingKey
from models import Book

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
