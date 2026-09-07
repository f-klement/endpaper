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

from datetime import date, datetime

import pytest

import csv_import
from csv_import import (
    CLAIMS,
    COLUMN_GUESSES,
    HeaderNames,
    ImportError_,
    build_mapping,
    decode,
    detect,
    flip_catalogue_name,
    match_format,
    match_status,
    parse,
    parse_date,
    sniff_delimiter,
    unwrap_excel_formula,
)
from enums import BookFormat, ReadStatus
from import_readers import ImportReader

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
            ("Graphic Novel", BookFormat.COMIC),
            ("manga", BookFormat.COMIC),
            ("CBZ", BookFormat.COMIC),
            # The container this app refuses to parse still names the shelf it
            # sits on. `frontend/src/lib/cbz.ts` carries the refusal.
            ("cbr", BookFormat.COMIC),
            # A collected comic and an ordinary novel are both sold in this
            # binding, and this table sees only the word, so it stays where it
            # was rather than following the comic vocabulary.
            ("Trade Paperback", BookFormat.PAPERBACK),
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

#: A Goodreads export with a row exclusion column bolted onto it, and one row
#: marked deleted. **Derived rather than quoted**: no service is attested as
#: writing both this header row and that column, and a file no service writes is
#: exactly what the rule now has to answer for.
GOODREADS_WITH_AN_EXCLUSION = GOODREADS.replace(b"My Review", b"HasBeenDeleted").replace(
    b"A desert planet.", b"true"
) + (
    b'2,Solaris,Stanislaw Lem,"Lem, Stanislaw",="0156027607",="9780156027601",4,'
    b"Harvest,Paperback,204,2002,2021/04/15,sci-fi,read,false\n"
)


class TestTheCloudExports:
    """What #197's two candidates actually look like when handed to `parse`."""

    def test_the_kindle_listing_gives_a_title_and_nothing_else(self):
        parsed = parse(KINDLE_DOCUMENTS)
        assert parsed.mapping["title"] == "Title"
        assert [field for field, header in parsed.mapping.items() if header] == ["title"]

    def test_the_kindle_listing_carries_no_identifier_to_match_on(self):
        """No ASIN and no ISBN. The ASIN is in the reading session log instead."""
        assert all(row.isbn is None for row in parse(KINDLE_DOCUMENTS).rows)

    def test_a_json_library_file_is_refused_rather_than_read_as_a_table(self):
        """Google Play's book list is `Library.json`, so somebody will upload it."""
        with pytest.raises(ImportError_):
            parse(b'[{"libraryDoc": {"doc": {"documentType": "Book"}}}]\n')


class TestOneCellCannotBuyUnboundedWork:
    """The parts of a compound cell are bounded by the upload and by nothing
    about a publication or a reading session.

    Measured with `time.process_time()` on files of `MAX_UPLOAD_BYTES`,
    20,000 rows, the bound switched off and on in the same process on the same
    bytes: `readings` **21.472 s** of CPU against **0.776 s**, `publication`
    **4.174 s** against **0.710 s**. The same file read generically costs
    0.393 s, which is the floor either number is heading for. On a route any
    member may reach three times a minute, and the preview writes nothing at
    all.

    **The machine is not named here**, because this file is published and its
    name is not: the figures are a ratio measured twice in one process rather
    than a comparison with any number taken elsewhere.

    **Asserted below as a count of calls rather than as a duration**, because a
    duration measured in a throttled pod says nothing, and because the count is
    what the bound is: `parse_date` costs 16.56 microseconds on a miss and the
    shape gate in front of it costs 0.21.

    A single enormous cell is not the shape of this: `csv.field_size_limit`
    refuses one over 131,072 characters, and the file above spends its budget
    across the rows instead.
    """

    def test_a_cell_of_rubbish_reaches_the_date_parser_and_not_the_date_format(
        self, monkeypatch
    ):
        """The gate is in `parse_date` rather than in the unpacker, so it covers
        every caller that loops over parts, including one written later."""
        calls = 0

        class Counting:
            """`datetime.strptime` cannot be patched on the class itself, which
            is immutable, so the module's name for it is what is replaced."""

            @staticmethod
            def strptime(text, pattern):
                nonlocal calls
                calls += 1
                return datetime.strptime(text, pattern)

        monkeypatch.setattr(csv_import, "datetime", Counting)

        content = (
            b"title,book_format,readings\nPiranesi,paperback,"
            + b"a|" * 20_000
            + b"\n"
        )
        [row] = parse(content).rows

        assert row.date_read is None
        assert calls == 0

    def test_finding_the_exclusion_columns_never_scans_the_header_row_twice(self):
        """The same shape one level up: a file's columns, not a cell's parts.

        Scanning the header row per header it is asked about is quadratic in a
        column count nothing bounds but the upload, and the refusal for a
        repeated exclusion column was written that way. The figures, and the
        caveat that decides what they mean, are at the site in `csv_import.py`
        and are not copied here: a number copied is a number that stops being
        re-derived, and the copy is the one without the caveat.

        **Counted as element comparisons, not as calls of one named method**,
        which is the difference between a guard and a guard for one spelling.
        Measured per header at 500 columns: what ships compares 4, and
        `headers.count`, `found.count` and a hand written loop compare 500, 499
        and 501. `found.count` is the one that matters, since it is one word
        from what ships, reads as a tidy up, is the same quadratic, and reaches
        a list this test never handed anybody.

        **What this sees is a quadratic that compares the header objects it was
        handed, and nothing else.** Two shapes are outside it, stated rather
        than answered with another arm, because the fix for both is an
        instrument that watches the row instead of its elements and that cannot
        be a `list`. A pair of `list.index` calls compares 4 per header, being
        quadratic in copying rather than in comparing. A scan over the
        normalised forms compares **1** per header, which is below what ships,
        because `_normalise_term` returns a plain `str` and the counting type
        never reaches the comparison. It is the same quadratic the comment at
        that site measures, so the instrument reads the expensive shape as the
        cheaper one.

        **Comparisons rather than a duration**, for the reason this class
        already gives: a duration in a throttled pod says nothing.
        """
        compared = 0

        class Counting(str):
            """A header that says when anything compared it.

            `__hash__` is delegated because defining `__eq__` drops it, and the
            tally this guards is built by hashing the row.
            """

            def __eq__(self, other):
                nonlocal compared
                compared += 1
                return str.__eq__(self, other)

            def __hash__(self):
                return str.__hash__(self)

        # Distinct objects, because `list.count` and `in` shortcut on identity
        # and a row of one repeated object would compare nothing at all.
        headers: list[str] = [
            Counting("Title"),
            *(Counting("HasBeenDeleted") for _ in range(500)),
        ]

        with pytest.raises(ImportError_, match="more than one column"):
            csv_import._exclusion_columns(headers)

        assert compared < 10 * len(headers)

    def test_a_real_date_still_reaches_it(self):
        """The other half of the diagonal: a gate that rejected everything would
        pass the row above and lose every date in every file."""
        [row] = parse(OPENREADS_READINGS).rows
        assert row.date_read == date(2024, 3, 4)

    def test_a_publication_cell_of_commas_is_tried_a_bounded_number_of_times(
        self, monkeypatch
    ):
        calls = 0
        real = csv_import.match_format

        def counted(raw):
            nonlocal calls
            calls += 1
            return real(raw)

        monkeypatch.setattr(csv_import, "match_format", counted)

        content = (
            "Title\tPrimary Author\tPublication\n"
            "Le Grand Meaulnes\tFournier, Alain\t(1979)" + "," * 20_000 + "\n"
        ).encode()
        [row] = parse(content).rows

        assert row.format is None
        # One call over and above the bound: every row asks the mapped `format`
        # column, which this file does not have, before the cell is unpacked.
        assert calls <= csv_import._FORMAT_PARTS_SCANNED + 1

    def test_a_format_after_a_comma_or_two_is_still_found(self):
        """The diagonal for the bound: scanning nothing would pass the row above
        and lose the field the reader exists for."""
        content = (
            b"Title\tPrimary Author\tPublication\n"
            b"Le Grand Meaulnes\tFournier, Alain\tGallimard (1979), Poche, Paperback\n"
        )
        [row] = parse(content).rows
        assert row.format is BookFormat.PAPERBACK


class TestARefusalDoesNotEchoTheFileBack:
    def test_a_file_broken_on_its_first_line_is_refused_rather_than_a_500(self):
        """Reading the header row is what parses it, so a file whose FIRST line
        is the malformed one used to raise past the handler that turns a
        `csv.Error` into a refusal, and `routers/imports.py` catches only the
        refusal. A file is not more readable for being broken on line one.
        """
        with pytest.raises(ImportError_, match="could not be read as a table"):
            parse(b"Title,HasBeenDeleted\rSolaris,true\r")
        with pytest.raises(ImportError_, match="could not be read as a table"):
            parse(b'"' + b"A" * 200_000 + b'",Title\nx,y\n')

    def test_a_file_that_is_not_a_table_gets_a_short_refusal(self):
        """A file with no delimiters has one enormous first line, and it is a header.

        Measured before each header was bounded: a 100,000 character line
        produced a 100,108 character message, and `routers/imports.py` makes it
        the `detail` of a 400, so a file that is not a table was quoted back to
        its sender in full.
        """
        with pytest.raises(ImportError_) as error:
            parse(("x" * 100_000 + "\ny\n").encode())
        assert len(str(error.value)) < 2_000

    def test_the_headers_it_does_quote_are_still_useful(self):
        """The other half: bounding a quote to nothing would pass the row above.

        Twelve headers of forty characters is the ceiling, and a real header row
        is well inside it, so the message that helps somebody pick the right
        column is unchanged.
        """
        with pytest.raises(ImportError_) as error:
            parse(b"Work Id,Edition Id,Bookshelf\nOL1W,OL2M,Already Read\n")
        assert "Work Id, Edition Id, Bookshelf" in str(error.value)


# ── The readers ───────────────────────────────────────────────────────────────
#
# Two export shapes cannot be a candidate header name, so two services have a
# reader of their own. A row exclusion is a third shape no name can carry and
# needs no reader: `_ROW_EXCLUSIONS` is honoured by every one of them, which is
# `TestARowTheFileMarksAsDeletedDoesNotComeBack` below. `import_readers.py` is
# the contract and `tests/test_import_readers.py` guards it; what is here is
# what each reader reads, and how a file is recognised as one service's.

#: LibraryThing's compound cell. **`Publication` and the shape of its value are
#: quoted from the importer audit of 2026-09-05**, which read a real export;
#: `Primary Author` is the same file's author column and is already quoted in
#: `LIBRARYTHING` above, off `bookwyrm/tests/data/librarything.tsv`. As
#: everywhere here the header row is quoted and the book row is invented.
LIBRARYTHING_PUBLICATION = (
    b"Title\tPrimary Author\tPublication\tPage Count\n"
    b"Le Grand Meaulnes\tFournier, Alain\tGallimard (1979), Paperback\t250\n"
)

#: Openreads' compound cell. **`readings` is quoted from the same audit and the
#: separator between two sessions is not**: what was quoted is one session,
#: `start|finish|`. The `;` below is therefore invented, which is exactly why
#: `test_the_session_separator_does_not_decide_the_answer` exists and why the
#: reader is written not to depend on it. `book_format` is quoted off
#: `bookwyrm/tests/data/openreads-csv-example.csv`, committed 2025-03-31.
OPENREADS_READINGS = (
    b"title,author,status,book_format,readings\n"
    b"Piranesi,Susanna Clarke,finished,paperback,"
    b"2021-01-02|2021-02-03|;2024-01-01|2024-03-04|\n"
)


class TestEachServicesOwnReaderIsTheOneThatRunsOnItsOwnFile:
    """The diagonal: every fixture in this file, against every reader.

    A fixture named for a service is not evidence that the service's reader ran
    on it, so the check is each file against its own answer **and** each
    claim taken apart one name at a time. A claim that fired on something else
    in the file would survive the first half and not the second.
    """

    def test_each_file_gets_the_reader_it_is_for(self):
        expected = {
            ImportReader.GENERIC: (
                GOODREADS,
                LIBRARYTHING,
                STORYGRAPH,
                LIBIB,
                LIBIB_TEMPLATE,
                OPENREADS,
                OPEN_LIBRARY,
                BOOKWYRM,
                ENDPAPER_OWN,
                LIBRARYTHING_DIMENSIONS,
                KINDLE_DOCUMENTS,
            ),
            ImportReader.LIBRARYTHING: (LIBRARYTHING_PUBLICATION,),
            ImportReader.OPENREADS: (OPENREADS_READINGS,),
        }
        for reader, files in expected.items():
            for content in files:
                assert parse(content).reader is reader, content[:40]

    @pytest.mark.parametrize(
        ("content", "reader"),
        [
            (LIBRARYTHING_PUBLICATION, ImportReader.LIBRARYTHING),
            (OPENREADS_READINGS, ImportReader.OPENREADS),
        ],
    )
    def test_every_name_of_a_claim_is_load_bearing(self, content, reader):
        """Each name dropped in turn, and the file must fall back to generic.

        This is what tells a claim apart from a fixture that happens to be
        recognised by one distinctive word: a name that could be removed with
        the answer unchanged is a name doing nothing.
        """
        claim = dict(CLAIMS)[reader]
        assert isinstance(claim, HeaderNames)
        headers = parse(content).headers

        for name in claim.names:
            [header] = [h for h in headers if csv_import._normalise_term(h) == name]
            without = content.replace(header.encode(), b"Something Else")
            assert parse(without).reader is ImportReader.GENERIC, name

    def test_a_column_one_service_shares_no_longer_routes_a_file_anywhere(self):
        """What the exclusion moving out of a reader took off this table.

        A Goodreads export carrying a column of that one name used to be the
        shape a claim could wrongly fire on, and the reader it would have gone
        to read the title alone, so such a file lost eleven of the twelve fields
        `ImportRow` carries. No claim mentions that name now, so the file is read
        generically and reads whole. What the
        column does to its rows is
        `TestARowTheFileMarksAsDeletedDoesNotComeBack`, and it is not detection.
        """
        content = GOODREADS.replace(b"My Review", b"HasBeenDeleted")

        parsed = parse(content)

        assert parsed.reader is ImportReader.GENERIC
        assert parsed.rows[0].author == "Frank Herbert"
        claimed = {
            name
            for _, claim in CLAIMS
            if isinstance(claim, HeaderNames)
            for name in claim.names
        }
        assert "hasbeendeleted" not in claimed

    def test_a_compound_readers_column_is_one_of_the_names_that_found_the_file(self):
        """The column a reader unpacks is also half of what recognises the file,
        so the two are one constant and this is what holds them together.

        Written twice they drift into a file that is detected as a service's and
        then unpacks nothing at all, silently.
        """
        for reader, column in (
            (ImportReader.LIBRARYTHING, csv_import._PUBLICATION),
            (ImportReader.OPENREADS, csv_import._READINGS),
        ):
            claim = dict(CLAIMS)[reader]
            assert isinstance(claim, HeaderNames)
            assert column in claim.names

    def test_a_claim_may_be_about_something_other_than_a_header_row(
        self, monkeypatch
    ):
        """The property the next reader needs, run rather than asserted.

        Google Play Books' library export is nested JSON, so no set of header
        names could ever claim it and its first line may be a single `{`. This
        registers the claim that reader would carry, over text past line one and
        not a `HeaderNames` at all, and asks `detect` to route to it.

        Asserting that every claim is callable would pass on the table this
        replaces, since `HeaderNames` is callable too. The routing is the claim.
        """
        library_json = '{\n  "libraryDoc": {\n    "documentType": "Book"\n  }\n}\n'

        monkeypatch.setattr(
            csv_import,
            "CLAIMS",
            ((ImportReader.OPENREADS, lambda text: '"documentType": "Book"' in text),),
        )

        assert detect(library_json) is ImportReader.OPENREADS

    def test_a_claim_is_handed_the_window_and_never_the_file(self, monkeypatch):
        """What the type accepts that a set of header names refused.

        A set of names could only ask about one line, so the work was bounded by
        what a claim was. A predicate is free to walk a 5 MB upload once per
        claim, on a route reachable three times a minute, and `detect` is where
        that is stopped rather than in a sentence each claim keeps to itself.
        """
        seen: list[int] = []

        def record(text: str) -> bool:
            seen.append(len(text))
            return False

        monkeypatch.setattr(csv_import, "CLAIMS", ((ImportReader.OPENREADS, record),))

        detect("x" * (csv_import._CLAIM_WINDOW * 3))

        assert seen == [csv_import._CLAIM_WINDOW]

    def test_a_file_with_no_newline_in_it_does_not_cost_the_whole_file(self):
        """The one input that reaches `_headers_of`'s fallback.

        A file with no delimiter at all is one enormous header, which is this
        module's own pathological input, and a slice ending at `find + 1` ends
        at zero for it. Read as the whole file, three claims over 5 MB cost 108
        ms and 25.5 MB of peak allocation against 20 ms and 1.3 MB. **Both
        halves are one instrument's run**, so the pair is a comparison; three
        instruments read the unwindowed side and the other two put it at 132 ms
        and at 437.8 ms, so the figure written is the lowest of the three and a
        floor. An ordinary export with a newline in it is 0.06 ms either way.
        `_headers_of` is what this asserts, because `detect` windows the text
        before any claim sees it and would hide the fallback.
        """
        # Asserted on the whole answer, not on `[0]`'s length. Indexing it made
        # the old spelling go red by `IndexError` instead: a 500,000 character
        # field is over `csv.field_size_limit`, so `_headers_of` caught the
        # `csv.Error` and answered `[]` before any length was compared. The name,
        # the docstring and the assertion were three claims and the assertion was
        # the one that never ran.
        assert csv_import._headers_of("x" * 500_000) == ["x" * csv_import._CLAIM_WINDOW]

    def test_a_file_nothing_claims_is_read_generically(self):
        """The fallback is what bounds a detection miss: a file no claim fires
        on is read by the reader that reads it today, never by nothing."""
        assert detect("Title,Author\nDune,Frank Herbert\n") is ImportReader.GENERIC

    def test_the_member_may_name_a_reader_over_the_detector(self):
        parsed = parse(LIBRARYTHING_PUBLICATION, None, ImportReader.GENERIC)
        assert parsed.reader is ImportReader.GENERIC
        assert parsed.rows[0].publisher is None

    def test_a_file_the_detector_cannot_read_falls_back_rather_than_raising(self):
        """Detection runs before the file is known to be a table at all."""
        assert detect("") is ImportReader.GENERIC


class TestARowTheFileMarksAsDeletedDoesNotComeBack:
    """The half of this that changes what a member sees.

    A row exclusion names no field, so it cannot be a candidate header name
    under any spelling. Left unread, a title the member deleted at the source
    came back, and came back visible to everyone on the instance: nothing on the
    import path sets `is_private` and `Book.is_private` defaults to false.

    **It is the generic mapping's, not one service's reader's.** The column is
    honoured wherever it appears, so nothing has to be right about which service
    wrote the file. Owner's decision, 2026-09-07.

    The attested fixture carries one row with the flag true and one with it
    false, so every assertion below is on the flag rather than on a count.
    """

    def test_the_row_the_member_deleted_does_not_come_back(self):
        assert [row.title for row in parse(KINDLE_DOCUMENTS).rows] == ["Roadside Picnic"]

    def test_it_is_counted_rather_than_dropped_silently(self):
        """A member who exported 400 titles and imported 380 is owed the other
        twenty, so the numbers still add up to the lines in the file."""
        parsed = parse(KINDLE_DOCUMENTS)
        assert (parsed.excluded, parsed.skipped, len(parsed.rows)) == (1, 0, 1)

    def test_a_value_outside_the_vocabulary_keeps_the_row(self):
        """The direction that does not destroy data.

        The attested column is written `true` and `false`, so a word outside
        that is a file this module has not seen, and inventing an exclusion out
        of it would drop books nobody deleted.
        """
        odd = KINDLE_DOCUMENTS.replace(b",true,", b",unknown,")
        parsed = parse(odd)
        assert [row.title for row in parsed.rows] == ["Solaris", "Roadside Picnic"]
        assert parsed.excluded == 0

    def test_a_row_with_no_title_is_still_the_other_count(self):
        """Two refusals, and they stay apart: the exclusion is what the file
        says, and the skip is what the row lacks."""
        untitled = KINDLE_DOCUMENTS.replace(b"BBBB,Roadside Picnic,", b"BBBB,,")
        parsed = parse(untitled)
        assert (parsed.excluded, parsed.skipped, parsed.rows) == (1, 1, [])

    def test_a_row_that_is_deleted_and_untitled_counts_as_deleted(self):
        """The one row that says which of the two is asked first, and without
        it the order is a comment.

        A row lacking a title is dropped either way, so the mutation that reads
        the title first is invisible on every other row in the file: the counts
        are the only place it shows, and a member reading them is owed the
        file's own answer rather than this module's.
        """
        both = KINDLE_DOCUMENTS.replace(b"AAAA,Solaris,", b"AAAA,,")
        parsed = parse(both)
        assert (parsed.excluded, parsed.skipped) == (1, 0)
        assert [row.title for row in parsed.rows] == ["Roadside Picnic"]

    @pytest.mark.parametrize("yes", ["true", "TRUE", " true ", "1", "yes", "y"])
    def test_every_spelling_of_yes_drops_the_row(self, yes):
        """The vocabulary decides what a file destroys, and it decides that for
        every file now rather than for one service's, so it is pinned rather
        than stated. Case and surrounding space belong to the file.
        """
        content = KINDLE_DOCUMENTS.replace(b",true,", f",{yes},".encode())
        assert [row.title for row in parse(content).rows] == ["Roadside Picnic"]

    @pytest.mark.parametrize("no", ["false", "0", "no", "", "deleted"])
    def test_everything_else_keeps_the_row(self, no):
        """The other half of the diagonal, and the direction that does not
        destroy data. `deleted` is in it deliberately: a word that reads like
        the answer is still not the answer the column is written with.
        """
        content = KINDLE_DOCUMENTS.replace(b",true,", f",{no},".encode())
        parsed = parse(content)
        assert [row.title for row in parsed.rows] == ["Solaris", "Roadside Picnic"]
        assert parsed.excluded == 0

    def test_naming_a_reader_does_not_bring_them_back(self):
        """What the old rule allowed and this one does not, pinned as such.

        The exclusion used to belong to one reader, so asking for the generic
        one read the same file as a plain table and every deleted title
        returned. It belongs to the mapping every reader shares now, so naming a
        reader decides how the cells are read and never whether the row exists.
        The way to import a row the file marks as deleted is to change the file,
        which is the member's own upload.
        """
        parsed = parse(KINDLE_DOCUMENTS, None, ImportReader.GENERIC)
        assert [row.title for row in parsed.rows] == ["Roadside Picnic"]
        assert parsed.excluded == 1

    def test_a_service_reader_honours_it_and_still_reads_its_own_cell(self):
        """Not one reader's rule and not bought with another reader's job.

        Openreads' file, read by Openreads' reader, with the column present: the
        deleted row goes and the compound cell of the row that stays is still
        unpacked.
        """
        content = (
            b"title,author,status,book_format,readings,HasBeenDeleted\n"
            b"Piranesi,Susanna Clarke,finished,paperback,2021-01-02|2021-02-03|,true\n"
            b"Solaris,Stanislaw Lem,finished,paperback,2024-01-01|2024-03-04|,false\n"
        )

        parsed = parse(content)

        assert parsed.reader is ImportReader.OPENREADS
        assert (parsed.excluded, [row.title for row in parsed.rows]) == (1, ["Solaris"])
        assert parsed.rows[0].date_read == date(2024, 3, 4)

    def test_any_service_writing_the_column_is_honoured_and_reads_whole(self):
        """**What the old rule refused and this one accepts**, stated as a test.

        The exclusion used to need a claim naming two of Amazon's headers, so a
        file from anywhere else carrying that column kept every row. It is
        honoured wherever the column appears now, which is wider by exactly this
        shape, and the widening is bounded by the name being one no field can
        be: the rest of such a file is still read as the plain table it is.
        """
        parsed = parse(GOODREADS_WITH_AN_EXCLUSION)

        assert parsed.reader is ImportReader.GENERIC
        assert (parsed.excluded, [row.title for row in parsed.rows]) == (1, ["Solaris"])
        assert parsed.rows[0].author == "Stanislaw Lem"
        assert parsed.rows[0].publisher == "Harvest"

    def test_a_file_naming_the_column_twice_is_refused_rather_than_read(self):
        """The one place in this module where refusing beats reading.

        `csv.DictReader` keys a row on the header string, so two columns of the
        same name collapse into one value, the last one's. Read that way the row
        below, which the file marks deleted in its first such column, was
        imported with the count reading zero and the column named beside it,
        which is the silent miss this rule exists to remove. Refusing destroys
        nothing.
        """
        twice = b"Title,HasBeenDeleted,HasBeenDeleted\nSolaris,true,false\n"
        with pytest.raises(ImportError_, match="more than one column"):
            parse(twice)

    def test_that_refusal_names_the_column_rather_than_a_run_of_spaces(self):
        """Padding is stripped before a name is reduced, so a file has as many
        spellings of this column as it has lengths of padding.

        Unbounded in what it stripped, the message named forty spaces and told
        a member to remove a column it had not identified. These all reduce to
        one name, so this is the half about stripping; the count is below.
        """
        padded = [" " * length + "HasBeenDeleted" for length in range(200)]
        header = ",".join(["Title", *padded, *padded])
        row = ",".join(["Solaris", *["true"] * (2 * len(padded))])

        with pytest.raises(ImportError_) as error:
            parse(f"{header}\n{row}\n".encode())

        assert "HasBeenDeleted" in str(error.value)
        assert len(str(error.value)) < 2_000

    def test_that_refusal_names_a_bounded_number_of_them(self):
        """The other half, and it needs names that do not reduce to one.

        Case is not a separator, so fifteen case spellings are fifteen distinct
        columns of one name, and quoting every one of them is how a refusal
        quotes a file back to its sender. The count is asserted rather than the
        message's length, because a length passes on a file that never reaches
        the cap.
        """
        name = "hasbeendeleted"
        spellings = [name[:index].upper() + name[index:] for index in range(15)]
        assert len(set(spellings)) == 15
        # Tied to the constant, not to 15: raise the cap above the fixture and
        # the assertion below becomes an identity that observes nothing.
        assert len(spellings) > csv_import._MAX_HEADERS_QUOTED
        header = ",".join(["Title", *spellings, *spellings])
        row = ",".join(["Solaris", *["true"] * (2 * len(spellings))])

        with pytest.raises(ImportError_) as error:
            parse(f"{header}\n{row}\n".encode())

        named = str(error.value).split("called ")[1].split(", so which")[0]
        assert len(named.split(", ")) == csv_import._MAX_HEADERS_QUOTED

    def test_a_name_longer_than_a_header_may_be_quoted_at_is_cut(
        self, monkeypatch
    ):
        """The length bound, which today's one name cannot reach.

        A header that reduces to `hasbeendeleted` carries no separator, so it is
        fourteen characters stripped and the cut cannot show. A longer name can
        be added at any time and the cut is what stops a `csv.field_size_limit`
        long header reaching a member, so it is asserted against a name of that
        shape rather than left to the day one arrives.
        """
        long_name = "has been deleted at the source by the member themselves"
        assert len(long_name) > csv_import._MAX_HEADER_QUOTED
        monkeypatch.setattr(
            csv_import,
            "_ROW_EXCLUSIONS",
            tuple(csv_import._normalise_term(name) for name in (long_name,)),
        )

        parsed = parse(f"Title,{long_name}\nSolaris,true\nDune,false\n".encode())

        assert parsed.excluded == 1
        assert parsed.exclusion_column == long_name[: csv_import._MAX_HEADER_QUOTED]

    def test_every_column_that_marks_deletion_is_read_and_not_only_the_first(self):
        """Two spellings of the name are two columns, and they disagree in one
        direction only: a column saying the member deleted this row is what the
        file says, and a second column silent about it takes nothing back."""
        both = (
            b"Title,HasBeenDeleted,hasbeendeleted\n"
            b"Solaris,false,true\n"
            b"Roadside Picnic,false,false\n"
        )
        parsed = parse(both)
        assert (parsed.excluded, [row.title for row in parsed.rows]) == (
            1,
            ["Roadside Picnic"],
        )

    def test_a_name_written_with_separators_is_the_same_name(self, monkeypatch):
        """The reduction every header goes through is applied to the candidate
        at import rather than asked of whoever adds one.

        The candidate is written as the header the export carries, so the
        reduction is already load bearing: without it `HasBeenDeleted` matches
        no normalised header and every other test in this class goes red. This
        is the half that has no subject until a second name arrives, run against
        the module's own expression rather than left as a sentence.
        """
        monkeypatch.setattr(
            csv_import,
            "_ROW_EXCLUSIONS",
            tuple(csv_import._normalise_term(name) for name in ("has_been_deleted",)),
        )

        parsed = parse(b"Title,Has Been Deleted\nSolaris,true\nRoadside Picnic,false\n")

        assert [row.title for row in parsed.rows] == ["Roadside Picnic"]

    def test_the_reported_column_still_names_the_column_and_stays_bounded(self):
        """A header is as long as the file makes it, and a 100,108 character
        400 is a refusal this module has already paid for once. Padding is what
        makes an arbitrarily long header still normalise to this name.

        **Asserted on what a member can read, not only on the length.** A bound
        that slices from the left of a padded header holds at exactly the right
        number of characters and reports forty spaces, which is the count beside
        a blank this whole change was taken against.
        """
        padded = ("Title," + " " * 200 + "HasBeenDeleted\nSolaris,true\n").encode()

        parsed = parse(padded)

        assert parsed.excluded == 1
        assert parsed.exclusion_column == "HasBeenDeleted"
        assert len(parsed.exclusion_column or "") <= csv_import._MAX_HEADER_QUOTED

    def test_the_column_it_was_read_from_is_reported(self):
        """A count a member cannot trace to a column of their own file is a
        number they cannot check, and the column is not one service's now."""
        assert parse(KINDLE_DOCUMENTS).exclusion_column == "HasBeenDeleted"

    def test_a_file_with_no_such_column_says_so_rather_than_saying_nothing(self):
        """Which is a different answer from "that column, and no row said yes",
        and the count alone cannot tell them apart."""
        parsed = parse(GOODREADS)
        assert (parsed.exclusion_column, parsed.excluded) == (None, 0)

    def test_a_column_correction_reaches_such_a_file(self):
        """The refusal that used to meet this call had one subject and it has
        gone.

        `DocumentProvider` means a document's provider, which is a sideloader on
        a sideloaded file, so no guess maps it. A member who wants it as the
        author says so, and the reader that guesses columns is the only kind
        there is.
        """
        parsed = parse(KINDLE_DOCUMENTS, {"author": "DocumentProvider"})
        assert [row.author for row in parsed.rows] == ["Arkady Strugatsky"]

    def test_the_columns_nothing_guesses_are_reported_as_unread(self):
        """`DocumentProvider` held the author on the rows the audit saw and
        means a document's provider, so no candidate name matches it. The
        preview says so rather than leaving somebody looking for the bug."""
        parsed = parse(KINDLE_DOCUMENTS)
        assert parsed.mapping["title"] == "Title"
        assert parsed.mapping["author"] is None


class TestLibraryThingsPublicationCellIsThreeFields:
    def test_the_publisher_the_year_and_the_format_all_come_out(self):
        [row] = parse(LIBRARYTHING_PUBLICATION).rows
        assert (row.publisher, row.year, row.format) == (
            "Gallimard",
            1979,
            BookFormat.PAPERBACK,
        )

    def test_the_rest_of_the_file_is_read_the_way_it_always_was(self):
        """A reader of its own is not a second parser: the candidate names, the
        catalogue order author and the tab delimiter all still apply."""
        [row] = parse(LIBRARYTHING_PUBLICATION).rows
        assert (row.title, row.author, row.pages) == ("Le Grand Meaulnes", "Alain Fournier", 250)

    def test_a_publisher_whose_name_holds_a_comma_survives(self):
        """The bracketed year is the anchor for exactly this reason: splitting
        this cell on its punctuation reads half a name as a binding."""
        content = LIBRARYTHING_PUBLICATION.replace(
            b"Gallimard (1979), Paperback", b"Farrar, Straus and Giroux (1979)"
        )
        [row] = parse(content).rows
        assert (row.publisher, row.year) == ("Farrar, Straus and Giroux", 1979)

    def test_the_last_bracketed_year_is_the_year_of_publication(self):
        """The position of the anchor, asserted rather than described.

        A publisher whose own name carries a bracketed year takes the anchor if
        the first is read instead, and then the year is the wrong one and the
        publisher is half a name. A mutation harness found this untested: both
        `found[0]` and `found[-1]` passed every other row in this class, because
        no other cell here has two.
        """
        content = LIBRARYTHING_PUBLICATION.replace(
            b"Gallimard (1979), Paperback", b"Editions (1901) Ltd (1979), Paperback"
        )
        [row] = parse(content).rows
        assert (row.publisher, row.year) == ("Editions (1901) Ltd", 1979)

    def test_a_cell_with_no_bracketed_year_invents_none(self):
        """The conservative half. Read the other way round, `Gallimard, Poche`
        would produce a year out of nothing, and a wrong value here is worse
        than an absent one."""
        content = LIBRARYTHING_PUBLICATION.replace(
            b"Gallimard (1979), Paperback", b"Gallimard, Poche"
        )
        [row] = parse(content).rows
        assert (row.publisher, row.year, row.format) == ("Gallimard, Poche", None, None)

    def test_a_column_of_its_own_beats_the_compound_cell(self):
        """Gaps are filled and nothing is overwritten, which is the rule
        `importing._fill_gaps` applies for the same reason."""
        content = (
            "Title\tPrimary Author\tPublication\tPublisher\n"
            "Le Grand Meaulnes\tFournier, Alain\tGallimard (1979)\tEmecé\n"
        ).encode()
        [row] = parse(content).rows
        assert (row.publisher, row.year) == ("Emecé", 1979)

    def test_an_empty_publication_cell_leaves_the_row_alone(self):
        content = LIBRARYTHING_PUBLICATION.replace(b"Gallimard (1979), Paperback", b"")
        [row] = parse(content).rows
        assert (row.publisher, row.year, row.format) == (None, None, None)


class TestOpenreadsReadingsCellIsAFinishDate:
    def test_the_latest_finish_is_the_date_read(self):
        """A book read twice has two, and the later one is when this member
        last finished it."""
        [row] = parse(OPENREADS_READINGS).rows
        assert row.date_read == date(2024, 3, 4)

    def test_the_session_separator_does_not_decide_the_answer(self):
        """The separator between two sessions was not attested, so the reading
        is written not to depend on it: the finishes are the odd numbered parts
        whatever glues two sessions together.

        Four separators, one answer, and the fourth is a newline, which arrives
        quoted because an unquoted one ends the row. Reading structure that was
        not attested is how a start becomes a finish.
        """
        answers = set()
        for separator in (b";", b"/", b" "):
            content = OPENREADS_READINGS.replace(b"|;2024", b"|" + separator + b"2024")
            [row] = parse(content).rows
            answers.add(row.date_read)

        quoted = OPENREADS_READINGS.replace(
            b"2021-01-02|2021-02-03|;2024-01-01|2024-03-04|",
            b'"2021-01-02|2021-02-03|\n2024-01-01|2024-03-04|"',
        )
        [row] = parse(quoted).rows
        answers.add(row.date_read)

        assert answers == {date(2024, 3, 4)}

    def test_an_open_session_never_becomes_a_finish(self):
        """A session somebody is part way through carries a start and no finish,
        and the day they began is not the day they finished."""
        content = OPENREADS_READINGS.replace(b";2024-01-01|2024-03-04|", b";2024-01-01|")
        [row] = parse(content).rows
        assert row.date_read == date(2021, 2, 3)

    def test_a_row_with_only_an_open_session_gets_no_date_at_all(self):
        content = OPENREADS_READINGS.replace(
            b"2021-01-02|2021-02-03|;2024-01-01|2024-03-04|", b"2024-01-01|"
        )
        [row] = parse(content).rows
        assert row.date_read is None

    def test_a_date_column_of_its_own_beats_the_compound_cell(self):
        content = (
            b"title,status,book_format,readings,date_read\n"
            b"Piranesi,finished,paperback,2024-01-01|2024-03-04|,2020-05-06\n"
        )
        [row] = parse(content).rows
        assert row.date_read == date(2020, 5, 6)

    def test_a_finish_out_of_the_cell_can_still_say_the_book_was_read(self):
        """The status rule runs after the cell is unpacked, which is the reason
        it is a function rather than a line inside the row builder: this date
        does not exist yet while the row is being built."""
        content = (
            b"title,book_format,readings\n"
            b"Piranesi,paperback,2024-01-01|2024-03-04|\n"
        )
        [row] = parse(content).rows
        assert (row.status, row.date_read) == (ReadStatus.READ, date(2024, 3, 4))
