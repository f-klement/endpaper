"""Tests for backend/csv_import.py.

The parser exists because somebody arriving here is arriving **from** something,
and it is as likely to be LibraryThing, StoryGraph or Libib as Goodreads. So
the cases that matter are one real export shape per service, and the awkward
parts of each: Goodreads wraps its identifiers in a spreadsheet formula,
LibraryThing exports tab separated in Latin-1 with every value in brackets, and
Openreads separates its header words with underscores.

The column-guessing approach is taken from BookWyrm's `importers/importer.py`.
Two of its properties are load bearing and are tested here directly, because
losing either is silent: a matched header is removed from the pool, and the
first matching candidate wins.
"""

import pytest

from csv_import import (
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
    "[Your library]\t[german, classics]\n"
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

    def test_reads_latin_1(self):
        assert parse(LIBRARYTHING).rows[0].title == "Der Zauberberg"

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
    def test_a_matched_header_cannot_be_claimed_twice(self):
        """Goodreads has ISBN and ISBN13; without removal one field takes both."""
        mapping = build_mapping(["Title", "ISBN", "ISBN13"])
        assert mapping["isbn13"] == "ISBN13"
        assert mapping["isbn"] == "ISBN"

    def test_the_first_candidate_wins(self):
        mapping = build_mapping(["Title", "Exclusive Shelf", "Shelf"])
        assert mapping["status"] == "Exclusive Shelf"

    def test_a_column_nothing_wants_is_left_alone(self):
        mapping = build_mapping(["Title", "Owned Copies"])
        assert "Owned Copies" not in mapping.values()

    def test_a_field_with_no_column_is_none(self):
        assert build_mapping(["Title"])["rating"] is None

    def test_matching_ignores_case_and_separators(self):
        assert build_mapping(["TITLE", "date_read"])["date_read"] == "date_read"


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

    def test_latin_1_never_fails(self):
        assert decode(bytes(range(256))) is not None


class TestDelimiterSniffing:
    def test_a_comma_in_a_quoted_title_does_not_outvote_the_tabs(self):
        """Counted on the header line only, for exactly this reason."""
        sample = "Title\tAuthor\n\"Dune, or the Desert\"\tFrank Herbert\n"
        assert sniff_delimiter(sample) == "\t"

    def test_an_ordinary_csv(self):
        assert sniff_delimiter("Title,Author\nDune,Frank Herbert\n") == ","
