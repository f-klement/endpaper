"""Tests for backend/goodreads.py: reading a library export.

The export format has one trap that silently imports nothing, and it is pinned
first: Goodreads writes identifier columns as spreadsheet formulas.
"""

from datetime import date

import pytest

from enums import ReadStatus
from goodreads import (
    SHELF_TO_STATUS,
    parse_date_read,
    parse_export,
    search_url,
    unwrap_excel_formula,
)

HEADER = (
    "Book Id,Title,Author,ISBN,ISBN13,My Rating,Publisher,"
    "Number of Pages,Year Published,Date Read,Bookshelves,Exclusive Shelf\n"
)


def export(*rows: str) -> bytes:
    return (HEADER + "".join(row if row.endswith("\n") else row + "\n" for row in rows)).encode()


def row(
    title: str = "Dune",
    author: str = "Frank Herbert",
    isbn: str = '="0441013597"',
    isbn13: str = '="9780441013593"',
    rating: str = "5",
    shelf: str = "read",
    date_read: str = "",
) -> str:
    return (
        f'1,"{title}","{author}",{isbn},{isbn13},{rating},Chilton,412,1965,'
        f'{date_read},favourites,{shelf}'
    )


class TestUnwrapExcelFormula:
    def test_unwraps_the_formula_goodreads_writes(self):
        # They wrap these so spreadsheets do not strip leading zeros or render
        # long numbers in scientific notation.
        assert unwrap_excel_formula('="9780441013593"') == "9780441013593"

    def test_handles_the_empty_form(self):
        assert unwrap_excel_formula('=""') == ""

    def test_leaves_a_plain_value_alone(self):
        assert unwrap_excel_formula("9780441013593") == "9780441013593"

    def test_trims_surrounding_space(self):
        assert unwrap_excel_formula('  ="9780441013593"  ') == "9780441013593"


class TestParseExport:
    def test_reads_a_row(self):
        result = parse_export(export(row()))

        assert len(result.rows) == 1
        assert result.rows[0].title == "Dune"
        assert result.rows[0].author == "Frank Herbert"

    def test_the_isbn_survives_the_formula_wrapper(self):
        """The whole reason an import can silently match nothing."""
        result = parse_export(export(row()))
        assert result.rows[0].isbn == "9780441013593"

    def test_falls_back_to_isbn10_when_isbn13_is_absent(self):
        result = parse_export(export(row(isbn13='=""')))
        # Canonicalised on the way in, so it matches what the catalogue stores.
        assert result.rows[0].isbn == "9780441013593"

    def test_a_row_with_no_usable_isbn_still_imports(self):
        # Matched by title instead. Plenty of older entries have no ISBN.
        result = parse_export(export(row(isbn='=""', isbn13='=""')))
        assert result.rows[0].isbn is None
        assert result.rows[0].title == "Dune"

    @pytest.mark.parametrize(
        "shelf,expected",
        [
            ("read", ReadStatus.READ),
            ("currently-reading", ReadStatus.READING),
            ("to-read", ReadStatus.WANT_TO_READ),
        ],
    )
    def test_maps_each_shelf_to_a_status(self, shelf, expected):
        result = parse_export(export(row(shelf=shelf)))
        assert result.rows[0].status == expected

    def test_want_to_read_is_not_collapsed_into_unread(self):
        # "on my shelf, not started" and "I mean to read this" are different
        # claims, and the export carries the difference. Asserted against the
        # mapping table rather than one parsed row: after the first assertion
        # the type is already narrowed, so re-checking it proves nothing.
        assert parse_export(export(row(shelf="to-read"))).rows[0].status is (
            ReadStatus.WANT_TO_READ
        )
        assert ReadStatus.UNREAD not in SHELF_TO_STATUS.values()

    def test_a_custom_shelf_is_skipped_and_counted(self):
        result = parse_export(export(row(shelf="borrowed-from-mum")))
        assert result.rows == []
        assert result.skipped == 1

    def test_an_empty_shelf_is_skipped(self):
        result = parse_export(export(row(shelf="")))
        assert result.skipped == 1

    def test_a_row_with_no_title_is_skipped(self):
        result = parse_export(export(row(title="")))
        assert result.skipped == 1

    def test_reads_several_rows(self):
        result = parse_export(export(row(title="Dune"), row(title="Neuromancer")))
        assert [entry.title for entry in result.rows] == ["Dune", "Neuromancer"]

    def test_ratings_are_read_and_zero_means_unrated(self):
        assert parse_export(export(row(rating="4"))).rows[0].rating == 4
        # Goodreads writes 0 for "no rating", which is not a one-star review.
        assert parse_export(export(row(rating="0"))).rows[0].rating is None

    def test_a_utf8_bom_does_not_break_the_first_column(self):
        # Exports opened and resaved in Excel commonly gain one, and it would
        # otherwise corrupt the first header name.
        content = b"\xef\xbb\xbf" + export(row())
        assert len(parse_export(content).rows) == 1

    def test_a_non_utf8_file_still_parses(self):
        content = export(row(author="Frank Herbert")).replace(b"Herbert", b"Herb\xe9rt")
        assert len(parse_export(content).rows) == 1


class TestRejectingTheWrongFile:
    def test_a_file_without_the_shelf_column_is_refused(self):
        # "0 books imported" is not a useful thing to tell someone who picked
        # the wrong file.
        with pytest.raises(ValueError, match="Goodreads export"):
            parse_export(b"Title,Author\nDune,Frank Herbert\n")

    def test_the_message_says_where_to_get_the_right_one(self):
        with pytest.raises(ValueError, match="Import/Export"):
            parse_export(b"Title,Author\nDune,Frank Herbert\n")

    def test_an_unrelated_csv_is_refused(self):
        with pytest.raises(ValueError):
            parse_export(b"a,b,c\n1,2,3\n")


class TestShelfMapping:
    def test_covers_every_exclusive_shelf_goodreads_has(self):
        assert set(SHELF_TO_STATUS) == {"read", "currently-reading", "to-read"}


class TestSearchUrl:
    def test_prefers_the_isbn(self):
        url = search_url("Dune", "9780441013593")
        assert "9780441013593" in url

    def test_falls_back_to_the_title(self):
        assert "Dune" in search_url("Dune", None)

    def test_escapes_a_title_with_spaces_and_punctuation(self):
        url = search_url("Eats, Shoots & Leaves")
        assert " " not in url
        assert "&" not in url.split("q=")[1]

    def test_points_at_goodreads_search(self):
        assert search_url("Dune").startswith("https://www.goodreads.com/search?q=")


class TestDateRead:
    """The export's "Date Read" column, which used to be parsed and discarded."""

    def test_reads_the_goodreads_format(self):
        result = parse_export(export(row(date_read="2021/03/14")))
        assert result.rows[0].date_read == date(2021, 3, 14)

    def test_reads_an_iso_date(self):
        # An export edited in a spreadsheet comes back in that locale's format.
        result = parse_export(export(row(date_read="2021-03-14")))
        assert result.rows[0].date_read == date(2021, 3, 14)

    def test_reads_a_day_first_date(self):
        result = parse_export(export(row(date_read="14/03/2021")))
        assert result.rows[0].date_read == date(2021, 3, 14)

    def test_an_empty_cell_is_absent(self):
        assert parse_export(export(row(date_read=""))).rows[0].date_read is None

    def test_an_unparseable_date_is_absent_rather_than_wrong(self):
        # A wrong date lands in "books finished in 2021" and nobody notices.
        assert parse_export(export(row(date_read="last Tuesday"))).rows[0].date_read is None


class TestParseDateRead:
    def test_handles_the_three_shapes_directly(self):
        assert parse_date_read("2021/03/14") == date(2021, 3, 14)
        assert parse_date_read("2021-03-14") == date(2021, 3, 14)
        assert parse_date_read("14/03/2021") == date(2021, 3, 14)

    def test_trims_surrounding_space(self):
        assert parse_date_read("  2021/03/14  ") == date(2021, 3, 14)

    def test_a_year_alone_is_not_a_date(self):
        assert parse_date_read("2021") is None
