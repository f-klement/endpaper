"""Tests for backend/csv_import.py.

The parser exists because somebody arriving here is arriving **from** something,
and it is as likely to be LibraryThing, StoryGraph or Libib as Goodreads. So
the cases that matter are one real export shape per service, and the awkward
parts of each: Goodreads wraps its identifiers in a spreadsheet formula,
LibraryThing exports tab separated with every value in brackets and a few bytes
that are not UTF-8, and Openreads separates its header words with underscores.

The column-guessing approach is taken from BookWyrm's `importers/importer.py`.
Both of its properties are load bearing and losing either is silent, so both
are tested against the whole candidate table rather than against examples:
`TestTheCandidateListSetsPriority` for the order, `TestAColumnIsClaimedOnce`
for the pool, and `TestTheCandidateTableIsWellFormed` for the two properties
of the table that decide whether either can work at all.
"""

import pytest

import csv_import
from csv_import import (
    COLUMN_GUESSES,
    ImportError_,
    build_mapping,
    decode,
    flip_catalogue_name,
    match_format,
    match_status,
    parse,
    parse_date,
    sniff_delimiter,
    unwrap_excel_formula,
)
from enums import BookFormat, ReadStatus

GOODREADS = b'''Book Id,Title,Author,Author l-f,ISBN,ISBN13,My Rating,Publisher,Binding,\
Number of Pages,Year Published,Date Read,Bookshelves,Exclusive Shelf,My Review
1,Dune,Frank Herbert,"Herbert, Frank",="0441013597",="9780441013593",5,Ace,Paperback,\
604,2005,2021/03/14,"sci-fi, favourites",read,A desert planet.
'''

LIBRARYTHING = (
    "Book Id\tTitle\tPrimary Author\tISBN\tRating\tDate Read\tCollections\tTags\n"
    "1\t[Der Zauberberg]\t[Mann, Thomas]\t[9783596294336]\t4\t[2019-04-02]\t"
    "[Your library]\t[Übersetzung, klassiker]\n"
).encode("latin-1")

STORYGRAPH = b'''Title,Authors,ISBN/UID,Format,Read Status,Last Date Read,Star Rating,Tags
The Hobbit,J.R.R. Tolkien,9780261102217,audiobook,currently-reading,,4.0,fantasy
'''

LIBIB = b'''title,creator,isbn,ean,publisher,publish_date,status,tags,notes,rating
Stoner,John Williams,9783423280150,,dtv,2014,Not Begun,"novel; sad",,3
'''

OPENREADS = b'''title,author,status,rating,pages,publication_year,isbn,tags
Piranesi,Susanna Clarke,in_progress,5,272,2020,9781526622426,fantasy
'''


class TestGoodreads:
    def test_reads_a_row(self):
        [row] = parse(GOODREADS).rows
        assert row.title == "Dune"
        assert row.author == "Frank Herbert"
        assert row.status is ReadStatus.READ
        assert row.rating == 5

    def test_unwraps_the_spreadsheet_formula_around_the_isbn(self):
        """`="9780441013593"` matches no book at all if left alone.

        They wrap identifier columns so a spreadsheet does not strip leading
        zeros. It is the single most common reason an import matches nothing.
        """
        [row] = parse(GOODREADS).rows
        assert row.isbn == "9780441013593"

    def test_takes_the_status_from_the_shelf_not_the_tag_column(self):
        """Goodreads has both, and `Bookshelves` is the free-form one.

        Claiming that as the status imports an entire library as unread.
        """
        parsed = parse(GOODREADS)
        assert parsed.mapping["status"] == "Exclusive Shelf"
        assert parsed.mapping["tags"] == "Bookshelves"

    def test_reads_the_rest_of_the_record(self):
        [row] = parse(GOODREADS).rows
        assert row.publisher == "Ace"
        assert row.year == 2005
        assert row.pages == 604
        assert row.format is BookFormat.PAPERBACK
        assert row.tags == ["sci-fi", "favourites"]
        assert row.date_read is not None


class TestLibraryThing:
    def test_reads_a_tab_separated_file(self):
        """Read as CSV it becomes one column named after the whole header line."""
        parsed = parse(LIBRARYTHING)
        assert parsed.delimiter == "\t"
        assert len(parsed.rows) == 1

    def test_reads_a_cell_whose_bytes_are_not_utf_8(self):
        """Named for the byte, because that is what decides here.

        The rest of this fixture is ASCII, so the umlaut is the only thing in
        it that could have been mangled.
        """
        assert parse(LIBRARYTHING).rows[0].tags == ["Übersetzung", "klassiker"]

    def test_strips_the_brackets_around_every_value(self):
        [row] = parse(LIBRARYTHING).rows
        assert row.title == "Der Zauberberg"
        assert row.isbn == "9783596294336"

    def test_turns_the_catalogue_order_author_around(self):
        [row] = parse(LIBRARYTHING).rows
        assert row.author == "Thomas Mann"

    def test_a_read_date_is_a_status_when_the_column_is_a_collection(self):
        """`Collections` holds "Your library", which is not a status.

        BookWyrm's importer for this service recovers the shelf from the dates
        for the same reason. Without it a whole LibraryThing library imports
        with no reading history at all.
        """
        [row] = parse(LIBRARYTHING).rows
        assert row.status is ReadStatus.READ


class TestOtherServices:
    def test_storygraph(self):
        [row] = parse(STORYGRAPH).rows
        assert row.title == "The Hobbit"
        assert row.status is ReadStatus.READING
        assert row.format is BookFormat.AUDIOBOOK
        assert row.rating == 4

    def test_libib(self):
        [row] = parse(LIBIB).rows
        assert row.title == "Stoner"
        assert row.status is ReadStatus.WANT_TO_READ
        assert row.year == 2014
        assert row.tags == ["novel", "sad"]

    def test_openreads_underscored_headers(self):
        """`publication_year` and `Year Published` are the same column.

        Headers are normalised the same way values are, so the guess tables do
        not need an entry per spelling.
        """
        [row] = parse(OPENREADS).rows
        assert row.year == 2020
        assert row.pages == 272
        assert row.status is ReadStatus.READING

    def test_a_plain_title_and_author_list(self):
        """The whole requirement is a title column."""
        [row] = parse(b"Name,By\nMoby Dick,Herman Melville\n").rows
        assert row.title == "Moby Dick"
        assert row.author == "Herman Melville"


class TestColumnGuessing:
    def test_the_two_isbn_columns_go_to_the_two_isbn_fields(self):
        """Goodreads carries both, and each is one field's name and no other's.

        Not the pool: matching is exact after normalising, so `ISBN` cannot
        reach the 13's candidates whether or not anything is removed.
        `TestAColumnIsClaimedOnce` is what covers the pool.
        """
        mapping = build_mapping(["Title", "ISBN", "ISBN13"])
        assert mapping["isbn13"] == "ISBN13"
        assert mapping["isbn"] == "ISBN"

    def test_a_column_nothing_wants_is_left_alone(self):
        mapping = build_mapping(["Title", "Owned Copies"])
        assert "Owned Copies" not in mapping.values()

    def test_a_field_with_no_column_is_none(self):
        assert build_mapping(["Title"])["rating"] is None

    def test_matching_ignores_case_and_separators(self):
        assert build_mapping(["TITLE", "date_read"])["date_read"] == "date_read"

    def test_completed_is_a_header_in_one_table_and_a_cell_value_in_the_other(self):
        """`COLUMN_GUESSES` is matched against headers, `STATUS_GUESSES` against cells.

        The word is in both. Conflating the two namespaces would read a header
        row as a status, or leave a `Completed` column unmapped because the
        word was spoken for.
        """
        mapping = build_mapping(["Title", "Completed"])

        assert mapping["date_read"] == "Completed"
        assert mapping["status"] is None
        assert match_status("Completed") is ReadStatus.READ


class TestTheCandidateTableIsWellFormed:
    """Two properties of `COLUMN_GUESSES` that nothing else can observe.

    Both fail silently in the same way: the name is written, the file has the
    column, and the field comes back empty with no error anywhere.
    """

    def test_no_two_fields_name_the_same_column(self):
        """Which is also why the pool is inert today. See `TestAColumnIsClaimedOnce`."""
        names = [guess for _, guesses in COLUMN_GUESSES for guess in guesses]
        assert sorted(names) == sorted(set(names))

    def test_every_candidate_is_written_in_the_form_a_header_is_reduced_to(self):
        """A candidate spelled `publish_date` can never match anything.

        The table says so at its head and nothing enforced it.
        """
        names = [guess for _, guesses in COLUMN_GUESSES for guess in guesses]
        assert [csv_import._normalise_term(name) for name in names] == names


class TestAColumnIsClaimedOnce:
    """A matched header leaves the pool, so two fields cannot claim it.

    Inert against today's table, which names no column twice, and kept anyway.
    Both tests here run against a table that does share a name, because a guard
    nothing exercises is a comment.
    """

    def test_a_name_shared_by_two_fields_goes_to_the_earlier_one(self, monkeypatch):
        """The second field gets nothing, rather than reading the same column."""
        monkeypatch.setattr(
            csv_import,
            "COLUMN_GUESSES",
            (("isbn13", ("ean", "isbn")), ("isbn", ("isbn",))),
        )

        assert build_mapping(["ISBN"]) == {"isbn13": "ISBN", "isbn": None}
        assert build_mapping(["EAN", "ISBN"]) == {"isbn13": "EAN", "isbn": "ISBN"}

    def test_a_file_naming_one_column_twice_fills_one_field_from_each(self, monkeypatch):
        """Two headers spelled the same way are two entries in the pool."""
        monkeypatch.setattr(
            csv_import,
            "COLUMN_GUESSES",
            (("isbn13", ("isbn",)), ("isbn", ("isbn",))),
        )

        assert build_mapping(["ISBN", "isbn"]) == {"isbn13": "ISBN", "isbn": "isbn"}


class TestOverrides:
    def test_a_named_header_replaces_the_guess(self):
        parsed = parse(
            b"Name,Real Title\nWrong,Right\n", {"title": "Real Title"}
        )
        assert parsed.rows[0].title == "Right"

    def test_an_override_naming_a_missing_header_is_ignored(self):
        """It describes a different file, and refusing this one helps nobody."""
        parsed = parse(b"Title\nDune\n", {"title": "Nonexistent"})
        assert parsed.rows[0].title == "Dune"


class TestRefusing:
    def test_an_empty_file(self):
        with pytest.raises(ImportError_):
            parse(b"")

    def test_a_file_with_no_title_column(self):
        with pytest.raises(ImportError_) as error:
            parse(b"Colour,Weight\nred,3\n")
        # The real headers are named, so a column can be picked by hand.
        assert "Colour" in str(error.value)

    def test_a_row_with_no_title_is_counted_not_dropped_silently(self):
        parsed = parse(b"Title,Author\n,Nobody\nDune,Frank Herbert\n")
        assert len(parsed.rows) == 1
        assert parsed.skipped == 1


class TestFieldParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("read", ReadStatus.READ),
            ("Already Read", ReadStatus.READ),
            ("to-read", ReadStatus.WANT_TO_READ),
            ("Want to Read", ReadStatus.WANT_TO_READ),
            ("currently-reading", ReadStatus.READING),
            ("in_progress", ReadStatus.READING),
            ("Not Begun", ReadStatus.WANT_TO_READ),
            # Goodreads users file this as a custom shelf and StoryGraph as a
            # status, and both spellings turn up in the same export folder.
            ("did-not-finish", ReadStatus.DID_NOT_FINISH),
            ("DNF", ReadStatus.DID_NOT_FINISH),
            ("Abandoned", ReadStatus.DID_NOT_FINISH),
            ("abgebrochen", ReadStatus.DID_NOT_FINISH),
            ("stopped reading", ReadStatus.DID_NOT_FINISH),
            # "finished" is READ and "unfinished" is not a negation of it that
            # any prefix rule would get right, which is why these match exactly.
            ("finished", ReadStatus.READ),
            ("unfinished", ReadStatus.DID_NOT_FINISH),
            ("borrowed", None),
            ("", None),
        ],
    )
    def test_status_vocabularies(self, raw, expected):
        assert match_status(raw) is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Paperback", BookFormat.PAPERBACK),
            ("mass market paperback", BookFormat.PAPERBACK),
            ("Hardcover", BookFormat.HARDCOVER),
            ("Kindle Edition", BookFormat.EBOOK),
            ("audiobook", BookFormat.AUDIOBOOK),
            ("Unknown Binding", None),
        ],
    )
    def test_format_vocabularies(self, raw, expected):
        assert match_format(raw) is expected

    @pytest.mark.parametrize(
        "raw", ["2021/03/14", "2021-03-14", "14/03/2021", "14.03.2021"]
    )
    def test_date_shapes(self, raw):
        parsed = parse_date(raw)
        assert parsed is not None and parsed.year == 2021

    def test_a_date_it_cannot_read_is_absent_rather_than_wrong(self):
        # A wrong date lands in "books finished in 2021" and nobody notices.
        assert parse_date("sometime last spring") is None

    def test_a_rating_outside_the_scale_is_dropped(self):
        [row] = parse(b"Title,Rating\nDune,9\n").rows
        assert row.rating is None

    def test_an_unrated_row_is_not_rated_zero(self):
        [row] = parse(b"Title,My Rating\nDune,0\n").rows
        assert row.rating is None

    def test_a_year_a_spreadsheet_mangled_is_dropped(self):
        [row] = parse(b"Title,Year Published\nDune,12345\n").rows
        assert row.year is None

    def test_a_corporate_author_keeps_its_commas(self):
        assert (
            flip_catalogue_name("Springer, Berlin, Heidelberg")
            == "Springer, Berlin, Heidelberg"
        )

    def test_a_name_with_no_comma_is_left_alone(self):
        assert flip_catalogue_name("Frank Herbert") == "Frank Herbert"

    def test_unwrapping_leaves_an_ordinary_value_alone(self):
        assert unwrap_excel_formula("9780441013593") == "9780441013593"

    def test_an_empty_formula_becomes_empty(self):
        assert unwrap_excel_formula('=""') == ""


class TestDecoding:
    def test_a_byte_order_mark_does_not_glue_itself_to_the_first_header(self):
        """A spreadsheet writes one, and a plain UTF-8 decode keeps it.

        `Title` then arrives as `﻿Title` and matches nothing.
        """
        parsed = parse("﻿Title,Author\nDune,Frank Herbert\n".encode())
        assert parsed.mapping["title"] is not None

    def test_no_byte_sequence_at_all_can_refuse_to_decode(self):
        """Every one of the 256 byte values, so nothing is left to raise.

        Ascending order puts no valid multi-byte sequence in the input: every
        lead byte is followed by one too high to continue it. So 256 in is 256
        out, and the length is what makes this stronger than `is not None`,
        which a decode that swallowed a byte would also satisfy.
        """
        assert len(decode(bytes(range(256)))) == 256


class TestDelimiterSniffing:
    def test_a_comma_in_a_quoted_title_does_not_outvote_the_tabs(self):
        """Counted on the header line only, for exactly this reason."""
        sample = "Title\tAuthor\n\"Dune, or the Desert\"\tFrank Herbert\n"
        assert sniff_delimiter(sample) == "\t"

    def test_an_ordinary_csv(self):
        assert sniff_delimiter("Title,Author\nDune,Frank Herbert\n") == ","


# ── The 2026 audit ────────────────────────────────────────────────────────────
#
# Every header row below is quoted from a named artefact with the date it was
# taken, because a header row is the fact that goes stale. **Every book row is
# invented**: `backend/tests/` is published, and a real export is somebody's
# reading history.
#
# `xfail(strict=True)` marks what the module does not do today. Strict, so the
# marker fails the moment the behaviour is fixed and cannot be left behind.

#: Open Library's reading log, `ReadingLogExport.fieldnames` in
#: `openlibrary/plugins/upstream/account.py` at `acfa38d17f`, committed
#: 2026-09-01. Taken from the generator rather than a sample.
OPEN_LIBRARY = b'''Work ID,Title,Authors,First Publish Year,Edition ID,Edition Count,\
Bookshelf,My Ratings,Ratings Average,Ratings Count,Has Ebook,Subjects,Subject People,\
Subject Places,Subject Times
OL1W,The Left Hand of Darkness,Ursula K. Le Guin,1969,OL2M,12,Already Read,5,4.2,900,\
true,Science fiction,,,
'''

#: The same export before 2022, from `bookwyrm/tests/data/openlibrary.csv`,
#: committed 2021-12-14. Work keys only, so there is nothing to import.
OPEN_LIBRARY_2021 = b"Work Id,Edition Id,Bookshelf\nOL1W,OL2M,Already Read\n"

#: BookWyrm's own account export, from `bookwyrm/tests/data/bookwyrm.csv`,
#: committed 2024-08-10.
BOOKWYRM = b'''title,author_text,remote_id,openlibrary_key,inventaire_id,librarything_key,\
goodreads_key,bnf_id,viaf,wikidata,asin,aasin,isfdb,isbn_10,isbn_13,oclc_number,start_date,\
finish_date,stopped_date,rating,review_name,review_cw,review_content,review_published,\
shelf,shelf_name,shelf_date
Solaris,Stanislaw Lem,https://example.test/book/1,,,,,,,,,,,0156027607,9780156027601,,\
2024-01-02,2024-02-03,,4,On Solaris,,An ocean that thinks.,2024-02-04,read,Read,2024-02-03
'''

#: Libib's bulk import template, from `support.libib.com/libib/website/add-items.html`,
#: read 2026-09-05. UNVERIFIED that Libib's export uses these same names: the
#: vendor's exports page names `creators` and `copies` in prose, which is this
#: vocabulary, but no real export file was obtained.
LIBIB_TEMPLATE = b'''added,creators,began_date,completed_date,copies,description,group,\
upc_isbn10,ean_isbn13,ddc,lcc,lccn,oclc,lexile,length_of,notes,price,publish_date,\
publisher,rating,review,review_date,status,tags,title
2026-01-05,Ursula K. Le Guin,,2026-02-06,1,,,0441478123,9780441478125,,,,,,304,,,1974,\
Harper,4,,,Completed,sci-fi,The Dispossessed
'''

#: This app's own CSV export. The header is written by the `/export` route in
#: `backend/routers/books.py` and pinned by
#: `tests/routers/test_books.py::TestExport`, so a drift fails there, not here.
ENDPAPER_OWN = b'''Title,Author,ISBN,Publisher,Year,Description,Tags,My Status,Date Added,\
Added By,Format,Condition,Location,Collection,Purchase Price,Purchase Currency,\
Purchased On,Purchased From
Solaris,Stanislaw Lem,9780156027601,Harcourt,1970,An ocean that thinks.,sci-fi,read,\
2026-01-05,ada,paperback,good,Shelf 2,,12.00,EUR,2026-01-05,a shop
'''

#: LibraryThing's column order, from `bookwyrm/tests/data/librarything.tsv`,
#: committed 2021-12-28, and confirmed unchanged by the column indices in
#: `vandinem/tsv-to-csv`, pushed 2024-01-24. `Length` is a physical dimension
#: and stands before `Page Count`, which is the point of this fixture.
LIBRARYTHING_DIMENSIONS = (
    b"Title\tLength\tPage Count\n" b"A Winter in Kaliningrad\t5.12 inches\t471\n"
)

#: A file that is UTF-8 apart from one MARC-8 byte in a column nothing maps.
#: This is the real shape of a LibraryThing export: measured on the 2021 file,
#: one line of five failed UTF-8, at `Cort\xe2azar` in `Subjects`.
MIXED_ENCODING = (
    b"Title\tSubjects\n"
    + "Ein Winter in Königsberg\t".encode()
    + b"Bl\xe2umer, Ines"
    + b"\n"
)


class TestTheCandidateListSetsPriority:
    """The candidates decide which column wins, and the file's order decides
    nothing.

    The whole table is the first test rather than three examples, because the
    defect this replaces was a rule stated in four places and held by none: it
    survived three readers and a test that happened to list its two headers in
    candidate order.
    """

    def test_no_field_answers_differently_when_the_file_reverses_its_columns(self):
        """Every candidate of every field, in the file, both ways round.

        The forwards pass is the control: it agrees under either rule, which is
        exactly how the defect stayed invisible.
        """
        headers = [guess for _, guesses in COLUMN_GUESSES for guess in guesses]
        first_written = {field: guesses[0] for field, guesses in COLUMN_GUESSES}

        assert build_mapping(headers) == first_written
        assert build_mapping(list(reversed(headers))) == first_written

    def test_a_named_status_column_beats_a_bare_shelf_listed_before_it(self):
        assert build_mapping(["Title", "Shelf", "Exclusive Shelf"])["status"] == (
            "Exclusive Shelf"
        )

    def test_a_page_count_beats_a_column_that_holds_a_shelf_dimension(self):
        assert build_mapping(["Title", "Length", "Page Count"])["pages"] == "Page Count"

    def test_a_length_of_column_beats_a_bare_length_column(self):
        """The position `length of` was added in, asserted rather than described.

        Appending it after `length` passes every Libib test, because no Libib
        file carries both. This is the file that tells the two apart, and it is
        what stops the next reader tidying the name to the end of the list.
        """
        assert build_mapping(["Title", "Length", "length_of"])["pages"] == "length_of"

    def test_the_members_own_ratings_column_beats_a_bare_rating_column(self):
        """The other position, and the same diagonal.

        `My Ratings` after `rating` in the candidate list would hand this field
        the `Rating` column, which is where a site that publishes an average
        puts everyone else's number.
        """
        assert build_mapping(["Title", "Rating", "My Ratings"])["rating"] == "My Ratings"

    def test_a_librarything_row_keeps_its_page_count(self):
        """What the defect cost on a real file: 471 pages read as 5."""
        [row] = parse(LIBRARYTHING_DIMENSIONS).rows
        assert row.pages == 471


class TestOneStrayByteDoesNotDecideTheEncodingOfTheWholeFile:
    """Decoding is per byte, so a file is not voted into another encoding.

    The second test is what the old rule did right and this one has to keep
    doing: a file that really is cp1252 must still come back with its accents,
    even though every one of them is a byte that is not UTF-8.

    The last is the other side of `_STRAY_RUN_BUDGET`, asserted on what the
    file comes back as rather than on how long it took, so it says which branch
    ran without being a timing test.
    """

    def test_an_accent_survives_a_bad_byte_in_a_column_nothing_reads(self):
        [row] = parse(MIXED_ENCODING).rows
        assert row.title == "Ein Winter in Königsberg"

    def test_a_file_that_really_is_cp1252_keeps_its_accents(self):
        content = "Title,Publisher\nDer Zauberberg,S. Fischer Müller\n".encode("cp1252")
        [row] = parse(content).rows
        assert row.publisher == "S. Fischer Müller"

    def test_a_byte_no_encoding_defines_costs_its_own_character_and_no_more(self):
        """cp1252 leaves 0x81 undefined, and the row either side of it stands."""
        content = b"Title,Publisher\nDune,Ace\x81Books\n"
        [row] = parse(content).rows
        assert row.title == "Dune"
        assert row.publisher == "Ace�Books"

    def test_a_cp1252_pair_that_is_also_valid_utf_8_is_read_as_the_sequence(self):
        """The cost of deciding per byte, asserted rather than described.

        `Â£` in cp1252 is 0xC2 0xA3, which is also the UTF-8 for `£`, so the
        pair is read as one character. It is mojibake in cp1252 before this
        ever sees it, which is why the trade goes this way.

        The 0x81 is what puts the file on that path at all: without a byte that
        fails, this pair decodes strictly and the branch under test never runs.
        """
        assert decode(b"a\x81b," + "Â£".encode("cp1252")) == "a�b,£"

    def test_a_file_carrying_replacement_characters_is_not_voted_out_by_them(self):
        """U+FFFD in the file is not a byte that failed, and is not counted.

        This importer writes that character itself, so a file can come back to
        it carrying thousands, and counting them would send a valid UTF-8 file
        to cp1252 over nothing: the same defect this class is named for,
        arriving through a second door.
        """
        content = (
            b"Title\n"
            + "�".encode() * (csv_import._STRAY_RUN_BUDGET + 1)
            + b"\x81"
            + "…".encode()
            + b"\n"
        )

        text = decode(content)

        assert text.endswith("…\n")
        assert text.count("�") == csv_import._STRAY_RUN_BUDGET + 2

    def test_a_file_that_mostly_fails_utf_8_is_read_whole_as_another_encoding(self):
        """Past the budget the premise is false and the whole file is the question.

        Sized from the budget itself, so raising it cannot leave this passing
        against the other branch. What it gives up is asserted rather than
        described: the one valid UTF-8 run in this file is read as cp1252 too.
        """
        content = (
            b"Title\n" + b"caf\xe9 " * (csv_import._STRAY_RUN_BUDGET + 1) + "…".encode()
        )

        text = decode(content)

        assert text.count("café") == csv_import._STRAY_RUN_BUDGET + 1
        assert text.endswith("â€¦")

    def test_a_file_just_under_the_budget_keeps_its_valid_utf_8(self):
        """The same file one run shorter, which is the diagonal of the one above."""
        content = (
            b"Title\n" + b"caf\xe9 " * csv_import._STRAY_RUN_BUDGET + "…".encode()
        )

        text = decode(content)

        assert text.count("café") == csv_import._STRAY_RUN_BUDGET
        assert text.endswith("…")


class TestEndpapersOwnExportRoundTrips:
    """The parser's half. The join with the live export route, which is what
    keeps this fixture honest, is
    `tests/routers/test_imports.py::TestEndpapersOwnExportSurvivesItsOwnImporter`.
    """

    def test_the_columns_that_do_come_back(self):
        [row] = parse(ENDPAPER_OWN).rows
        assert row.title == "Solaris"
        assert row.author == "Stanislaw Lem"
        assert row.isbn == "9780156027601"
        assert row.year == 1970
        assert row.format is BookFormat.PAPERBACK

    def test_a_reading_status_survives_an_export_and_an_import(self):
        [row] = parse(ENDPAPER_OWN).rows
        assert row.status is ReadStatus.READ

    def test_the_collection_column_is_not_read_as_the_status(self):
        """`Collection` is one letter from `collections`, a status candidate.

        Asserted against a file with no status column, because in the export
        itself the question never arises: `My Status` is matched first and no
        later candidate is consulted, so a fixture based version of this passes
        whatever `Collection` would have done.
        """
        assert build_mapping(["Title", "Collection"])["status"] is None


class TestOpenLibraryReadingLog:
    def test_the_columns_that_match(self):
        [row] = parse(OPEN_LIBRARY).rows
        assert row.title == "The Left Hand of Darkness"
        assert row.author == "Ursula K. Le Guin"
        assert row.status is ReadStatus.READ

    def test_every_shelf_the_reading_log_can_write_is_recognised(self):
        """Completeness for this service, not the vocabulary itself.

        `bookshelf_map` in the generator has exactly these four values, so an
        unrecognised one here is a shelf that imports with no status at all.
        What each word means is `test_status_vocabularies`' job.
        """
        shelves = ["Want to Read", "Currently Reading", "Already Read", "Stopped Reading"]
        assert all(match_status(shelf) is not None for shelf in shelves)

    def test_the_export_carries_no_isbn_to_match_on(self):
        """A property of the export, recorded so nobody looks for the bug.

        Open Library exports work and edition keys, so a reading log import
        matches by title and author or not at all.
        """
        assert parse(OPEN_LIBRARY).mapping["isbn"] is None
        assert parse(OPEN_LIBRARY).mapping["isbn13"] is None

    def test_the_2021_export_is_refused_rather_than_imported_empty(self):
        with pytest.raises(ImportError_) as error:
            parse(OPEN_LIBRARY_2021)
        assert "Work Id" in str(error.value)

    def test_the_members_own_rating_is_read(self):
        [row] = parse(OPEN_LIBRARY).rows
        assert row.rating == 5

    def test_a_crowd_rating_never_wins_over_the_members_own(self):
        """The hazard is finding 1 again, not a candidate name.

        Matching is exact after normalising, so no `ratings` candidate could
        ever claim `Ratings Average`. What can put somebody else's number in
        this field is a file that lists a bare `Rating` column before the
        member's own, which is what this asserts against.
        """
        assert build_mapping(["Title", "Rating", "My Rating"])["rating"] == "My Rating"

    def test_the_publication_year_is_read(self):
        [row] = parse(OPEN_LIBRARY).rows
        assert row.year == 1969


class TestBookWyrmExport:
    def test_the_columns_that_match(self):
        [row] = parse(BOOKWYRM).rows
        assert row.title == "Solaris"
        assert row.author == "Stanislaw Lem"
        assert row.isbn == "9780156027601"
        assert row.status is ReadStatus.READ
        assert row.rating == 4
        assert row.date_read is not None and row.date_read.month == 2

    def test_every_bookwyrm_shelf_is_recognised(self):
        """Completeness for this service. The vocabulary itself is tested once."""
        shelves = ["to-read", "currently-reading", "read", "stopped-reading"]
        assert all(match_status(shelf) is not None for shelf in shelves)

    def test_the_review_becomes_the_note(self):
        [row] = parse(BOOKWYRM).rows
        assert row.notes == "An ocean that thinks."


class TestLibibsCurrentVocabulary:
    """Libib's own template, and the three columns of it that matter most.

    The `LIBIB` fixture above uses `creator`, `isbn` and `ean`. No Libib
    artefact found uses those spellings: the vendor's current template and a
    2024 third party template both say `creators`, `upc_isbn10` and
    `ean_isbn13`, and a real 2016 export said `authors`, `isbn10`, `isbn13`.
    """

    def test_the_columns_that_match(self):
        [row] = parse(LIBIB_TEMPLATE).rows
        assert row.title == "The Dispossessed"
        assert row.status is ReadStatus.READ
        assert row.rating == 4
        assert row.publisher == "Harper"
        assert row.year == 1974

    def test_the_author_is_read(self):
        [row] = parse(LIBIB_TEMPLATE).rows
        assert row.author == "Ursula K. Le Guin"

    def test_the_isbn_is_read(self):
        """Without this and the author, a Libib row is a bare title.

        **The mapping is asserted beside the value, because the value cannot
        say which column produced it.** `parse` builds `isbn` from
        `parse_isbn(cell("isbn13")) or parse_isbn(cell("isbn"))`, so dropping
        `ean isbn13` leaves the file's own 13 ignored and this same string
        rebuilt from the 10, silently.

        **`status` is the other field fed by two columns**, and by control flow
        rather than by an expression: `parse` derives READ from a parsed
        `date_read` when the status column matched nothing. A test asserting a
        derived status has the same blind spot, which is what
        `test_the_status_word_is_recognised_rather_than_inferred_from_the_date`
        answers, by taking the date away. Every other field reads one column.

        Deleting either assertion below stops this test seeing the candidate it
        is named for.
        """
        parsed = parse(LIBIB_TEMPLATE)
        assert parsed.mapping["isbn13"] == "ean_isbn13"
        assert parsed.mapping["isbn"] == "upc_isbn10"
        [row] = parsed.rows
        assert row.isbn == "9780441478125"

    def test_the_status_word_is_recognised_rather_than_inferred_from_the_date(self):
        """`Completed` read from the status column, on a row with no date.

        The template carries a status and a completed date, and `parse` derives
        READ from a parsed date whenever the status column matched nothing, so
        `test_the_columns_that_match` cannot tell the two routes apart. This
        row empties the date, which is the only shape that can: the status has
        to carry itself.

        Asking `match_status` directly instead would test the vocabulary rather
        than this file, and the vocabulary is already asked in
        `TestColumnGuessing`.
        """
        no_date = LIBIB_TEMPLATE.replace(b",2026-02-06,", b",,")

        [row] = parse(no_date).rows
        assert row.date_read is None
        assert row.status is ReadStatus.READ

    def test_the_completed_date_is_the_date_read(self):
        [row] = parse(LIBIB_TEMPLATE).rows
        assert row.date_read is not None and row.date_read.year == 2026

    def test_the_page_count_is_read(self):
        [row] = parse(LIBIB_TEMPLATE).rows
        assert row.pages == 304


class TestOpenreads:
    """From `bookwyrm/tests/data/openreads-csv-example.csv`, committed 2025-03-31."""

    def test_planned_is_a_book_somebody_wants_to_read(self):
        assert match_status("planned") is ReadStatus.WANT_TO_READ

    def test_the_book_format_column_is_found(self):
        assert build_mapping(["title", "book_format"])["format"] == "book_format"


#: Amazon's Kindle document listing, from
#: `Kindle.KindleDocs/datasets/Kindle.KindleDocs.DocumentMetadata/`. Header taken
#: from a real 2022 export a member published; **no 2026 export was obtained**,
#: so treat the column names as of that date and not as current.
KINDLE_DOCUMENTS = b'''DocumentId,Title,DocumentProvider,Filename,DocumentOriginalType,\
DocumentSizeInBytes,DocumentTypeAndConvertionCompletionStatus,HasBeenDeleted,\
EntryCreationDate
AAAA,Solaris,Stanislaw Lem,solaris.azw3,application/x-mobipocket-ebook,100,\
documentType = document,true,2019-01-01
BBBB,Roadside Picnic,Arkady Strugatsky,picnic.azw3,application/x-mobipocket-ebook,100,\
documentType = document,false,2019-01-02
'''


class TestTheCloudExports:
    """What #197's two candidates actually look like when handed to `parse`."""

    def test_the_kindle_listing_gives_a_title_and_nothing_else(self):
        parsed = parse(KINDLE_DOCUMENTS)
        assert parsed.mapping["title"] == "Title"
        assert [field for field, header in parsed.mapping.items() if header] == ["title"]

    def test_the_kindle_listing_carries_no_identifier_to_match_on(self):
        """No ASIN and no ISBN. The ASIN is in the reading session log instead."""
        assert all(row.isbn is None for row in parse(KINDLE_DOCUMENTS).rows)

    def test_a_document_amazon_marks_deleted_arrives_beside_the_rest(self):
        """The finding, and it is not a name that fixes it.

        The fixture holds one row with `HasBeenDeleted` true and one with it
        false, and both come back. The module has one row filter, "no title, so
        skip", and a row level exclusion cannot be expressed as a candidate
        header name. Asserted on the titles, not on a count, so the flag is
        load bearing in the test that is named for it.

        Where those rows land matters as much as that they arrive: an import
        never sets `is_private`, which defaults to false, so a title the member
        deleted at the source comes back visible to the whole instance.
        """
        titles = [row.title for row in parse(KINDLE_DOCUMENTS).rows]
        assert titles == ["Solaris", "Roadside Picnic"]

    def test_a_json_library_file_is_refused_rather_than_read_as_a_table(self):
        """Google Play's book list is `Library.json`, so somebody will upload it."""
        with pytest.raises(ImportError_):
            parse(b'[{"libraryDoc": {"doc": {"documentType": "Book"}}}]\n')


class TestARefusalDoesNotEchoTheFileBack:
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="`headers[:12]` bounds the count, nothing bounds each header's length.",
    )
    def test_a_file_that_is_not_a_table_gets_a_short_refusal(self):
        """A file with no delimiters has one enormous first line, and it is a header.

        Measured: a 100,000 character line produces a 100,108 character message,
        and `routers/imports.py` makes it the `detail` of a 400.
        """
        with pytest.raises(ImportError_) as error:
            parse(("x" * 100_000 + "\ny\n").encode())
        assert len(str(error.value)) < 2_000
