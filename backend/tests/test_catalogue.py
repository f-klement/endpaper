"""The typed draft every source adapter normalises into.

What is pinned here is the seam itself: the folding rules, the completeness
score, and the two wire shapes. What each catalogue's parser makes of its own
XML is pinned in `test_metadata.py`, which is where the parsers are.
"""

import ast
import asyncio
import dataclasses
import logging
import pathlib
from typing import Any, Final, cast

import annotated_types
import pytest
from pydantic import ValidationError

import catalogue
import google_books
import isbn as isbn_utils
import metadata
from catalogue import AuthorityAssertion, Heading, Record, Subject, uncontrolled
from enums import AuthorityScheme, ClassificationScheme
from models import DESCRIPTION_MAX, ISBN_MAX, Book
from schemas.book import BookCreate, BookLookup, BookMatch
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK
from tests.test_house_rules import _is_vendored

#: What a text field has to start with to satisfy a validator other than its
#: length. Only `cover_url` can be helped this way: `BookCreate` refuses
#: anything that is neither https nor an uploaded cover, and these fixtures are
#: asserted against that model, so padding alone would fail for a reason this
#: file is not about. `isbn` has such a validator too and no prefix satisfies
#: it, which is what `VALID_ISBN` is for.
_PREFIXES = {"cover_url": "https://example.com/"}


def _widest(name: str) -> str:
    """The longest value of `name` its column can hold, still a legal one."""
    prefix = _PREFIXES.get(name, "")
    return prefix + "x" * (catalogue._TEXT_CEILINGS[name] - len(prefix))


def _at_every_ceiling() -> dict[str, Any]:
    """A record filled to every ceiling at once, rebuilt from the tables rather
    than written out, so a ceiling that moves moves the fixture with it."""
    filled: dict[str, Any] = {name: _widest(name) for name in catalogue._TEXT_CEILINGS}
    filled.update({name: high for name, (_, high) in catalogue._NUMBER_RANGES.items()})
    return filled


def _one_past(name: str) -> Any:
    """The smallest value of `name` that its column cannot hold."""
    if name in catalogue._TEXT_CEILINGS:
        return _widest(name) + "x"
    return catalogue._NUMBER_RANGES[name][1] + 1


#: A real ISBN, for the two assertions made against `BookCreate`.
#:
#: `isbn` is in the ceilings table, so `_at_every_ceiling` fills it to the
#: column with padding. That is the right fixture for a `Record`, which checks
#: only the width, and the wrong one for `BookCreate`, which refuses this field
#: on its checksum: a padded value would be refused for a reason these two
#: assertions are not about. Hence the override, and it cannot be folded into
#: `_PREFIXES`, since no prefix makes a padded string a valid ISBN.
VALID_ISBN: Final[dict[str, Any]] = {"isbn": "9780743273565"}


BOUNDED = sorted(set(catalogue._TEXT_CEILINGS) | set(catalogue._NUMBER_RANGES))


def _checked(body: str, characters: str, accepts: Any) -> str:
    """`body` plus the one check character its own scheme accepts.

    Found by asking `isbn.py` rather than by recomputing either checksum here,
    which would be the algorithm stored twice and would agree with a broken copy
    of itself.
    """
    return next(body + character for character in characters if accepts(body + character))


def _every_shape_of_a_real_isbn() -> list[str]:
    """Real ISBNs in every written form `isbn.normalise` accepts.

    Both of `isbn.parse`'s returning branches: the ISBN-13 it validates, under
    each Bookland prefix, and the ISBN-10 it converts, including the `X` check
    digit, which is the one character `normalise` upper cases rather than
    strips. Each written plain, hyphenated, spaced, padded and lower cased,
    because a separator a caller left in is how a value wider than the canonical
    form would reach a column.
    """
    thirteens = [
        _checked(prefix + f"{number:09d}", "0123456789", isbn_utils.is_valid_isbn13)
        for prefix in isbn_utils.BOOKLAND_PREFIXES
        for number in (0, 1, 42, 441013593, 743273565, 999999999)
    ]
    tens = [
        _checked(f"{number:09d}", "0123456789X", isbn_utils.is_valid_isbn10)
        for number in (0, 1, 42, 306406152, 441013593, 999999999)
    ]
    return [
        written
        for value in thirteens + tens
        for written in (
            value,
            "-".join(value),
            " ".join(value),
            f"  {value}  ",
            value.lower(),
        )
    ]


def _match_keys(table: dict[str, int] | None = None) -> dict[str, str]:
    """Which `BookMatch` key each of `table`'s fields lands under, **derived**.

    `as_match` does not use the record's own names for everything: `isbn`
    becomes `isbn13` there, because a search row is one printing among several
    rather than the one asked for. Writing that down would be a second statement
    of that method's own mapping, and the first version of the guards below
    simply assumed the names matched and died on a `KeyError` the day `isbn` was
    briefly bounded.

    **Takes the table rather than reading `_TEXT_CEILINGS` directly**, so the
    diagonal can hand it a field that *is* renamed. Reading the live table, the
    answer today is nine names and no renames, and a version of this function
    that had quietly become the identity would look identical.

    Two character probes, so every value is under every ceiling including
    `language` at 10, and unique, so the inversion cannot collide.
    """
    fields = catalogue._TEXT_CEILINGS if table is None else table
    probe: dict[str, Any] = {
        name: f"p{index}" for index, name in enumerate(sorted(fields))
    }
    wire = Record(source="dnb", **probe).as_match()
    landed = {value: key for key, value in wire.items() if isinstance(value, str)}
    return {name: landed[value] for name, value in probe.items() if value in landed}


def _opens_the_upload_door(source: str) -> bool:
    """Whether this module actually calls `Record.from_upload`.

    A **call**, not the spelling. `importing.py` names the method in prose to
    say where truncation now happens, and a guard matching a substring would
    make writing that explanation fail the suite.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_upload"
        for node in ast.walk(ast.parse(source))
    )

DDC_004 = Heading(ClassificationScheme.DDC, "004")
DDC_004_CAPTIONED = Heading(ClassificationScheme.DDC, "004", "Informatik")
GND = Heading(ClassificationScheme.GND, "4026894-9", "Informatik")
LCSH = Heading(ClassificationScheme.LCSH, "France -- History")
KANE = AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "1042243212")
MATTHIAS = AuthorityAssertion("Karl Matthias", AuthorityScheme.GND, "1042243213")


class TestARecordFoldsWhatOneSourceRepeats:
    """A catalogue restates itself, and no parser should have to remember that."""

    def test_a_heading_repeated_in_one_record_is_kept_once(self):
        """One live K10plus record's 082 `$a` values read `100`, `610`, `610`."""
        record = Record(headings=(DDC_004, DDC_004))

        assert record.headings == (DDC_004,)

    def test_a_caption_is_taken_from_whichever_entry_carries_one(self):
        record = Record(headings=(DDC_004, DDC_004_CAPTIONED))

        assert record.headings == (DDC_004_CAPTIONED,)

    def test_a_later_caption_never_replaces_one_already_found(self):
        """The first source to name a heading is the one that captions it."""
        other = Heading(ClassificationScheme.DDC, "004", "Computing")
        record = Record(headings=(DDC_004_CAPTIONED, other))

        assert record.headings == (DDC_004_CAPTIONED,)

    def test_two_numbers_under_one_scheme_are_two_headings(self):
        """`005.133` and `004` are two catalogues' answers, not a duplicate."""
        precise = Heading(ClassificationScheme.DDC, "005.133")
        record = Record(headings=(DDC_004, precise))

        assert record.headings == (DDC_004, precise)

    def test_a_subject_repeated_in_one_record_is_kept_once(self):
        """The DNB's 689 restates the 600, 650 and 651 it was built from."""
        record = Record(subjects=uncontrolled(("Informatik", "Roman", "Informatik")))

        assert record.subjects == (Subject("Informatik"), Subject("Roman"))

    def test_an_undeclared_repeat_of_a_declared_subject_folds_away(self):
        """The 689 restatement carries no `$2`, on 199 of 199 live DNB fields.

        Both orders, because a catalogue may declare on either field: the DNB
        declares on `650` and restates on `689`, K10plus is the exact mirror.
        """
        declared = Subject("Informatik", "gnd", "(DE-588)4026894-9")
        restated = Subject("Informatik")

        assert Record(subjects=(declared, restated)).subjects == (declared,)
        assert Record(subjects=(restated, declared)).subjects == (declared,)

    def test_one_label_under_two_vocabularies_stays_two_subjects(self):
        """15 of 765 live (record, label) pairs, and merging them is the
        crosswalk #134 refuses: `Woerterbuch` is a `gnd` subject and a
        `gnd-content` form type on one DNB record."""
        subject = Subject("Woerterbuch", "gnd", "(DE-588)4066724-8")
        form = Subject("Woerterbuch", "gnd-content", "(DE-588)4066724-8")

        assert Record(subjects=(subject, form)).subjects == (subject, form)

    def test_an_identifier_is_filled_in_from_whichever_entry_carries_one(self):
        """`_union`'s caption rule, applied to the half a record omits more."""
        bare = Subject("Europe", "nlgaf")
        identified = Subject("Europe", "nlgaf", "urn:nbn:gr:nlg:01-A273635")

        assert Record(subjects=(bare, identified)).subjects == (identified,)

    def test_a_later_identifier_never_replaces_one_already_found(self):
        first = Subject("Europe", "nlgaf", "urn:nbn:gr:nlg:01-A273635")
        second = Subject("Europe", "nlgaf", "urn:nbn:gr:nlg:99-B000000")

        assert Record(subjects=(first, second)).subjects == (first,)

    def test_an_undeclared_subject_no_field_declared_is_kept(self):
        """The fold drops an undeclared copy of a **declared** label only. A
        record whose every subject is undeclared keeps every one of them, which
        is what every Dublin Core source produces."""
        record = Record(subjects=uncontrolled(("Fantasy", "Roman")))

        assert record.subjects == (Subject("Fantasy"), Subject("Roman"))

    def test_an_undeclared_repeat_carrying_its_own_identifier_is_kept(self):
        """A restatement adds nothing; this adds an identifier nobody else
        named, so it is a second assertion.

        Measured live, twice in 169 pairs, and both are the OENB: it writes
        `650 $a Oesterreich $2 VLK $0 (AT-VLB)LA01044691` and, on the same
        record, `689 $a Oesterreich $0 (DE-588)4043271-3`. Folding the second
        away throws out the GND number, which is the better identifier of the
        two.
        """
        local = Subject("Oesterreich", "vlk", "(AT-VLB)LA01044691")
        gnd_number = Subject("Oesterreich", None, "(DE-588)4043271-3")

        assert Record(subjects=(local, gnd_number)).subjects == (local, gnd_number)

    def test_the_kept_identifier_is_never_moved_onto_the_other_vocabulary(self):
        """The obvious repair for the case above, refused.

        Writing `(DE-588)4043271-3` onto the `VLK` entry says the GND number
        identifies a heading in the Vorarlberg list. That is a crosswalk between
        two vocabularies, which is what #134 refuses, so the fix is to keep both
        rather than to fill one from the other.
        """
        local = Subject("Psychology", "gnd", None)
        fast = Subject("Psychology", None, "(OCoLC)fst01081447")
        folded = Record(subjects=(fast, local)).subjects

        assert [subject.identifier for subject in folded] == [
            "(OCoLC)fst01081447",
            None,
        ]

    def test_an_undeclared_repeat_of_the_same_identifier_still_folds(self):
        """147 of the 169 live pairs, and the commonest shape of all: the DNB's
        `689` restates the `650` heading **with its `(DE-588)` number** and no
        `$2`. A rule that kept every undeclared entry carrying an identifier
        would put that word on the wire twice."""
        declared = Subject("Informatik", "gnd", "(DE-588)4026894-9")
        restated = Subject("Informatik", None, "(DE-588)4026894-9")

        assert Record(subjects=(declared, restated)).subjects == (declared,)

    def test_a_label_keeps_the_place_of_its_first_occurrence(self):
        """`categories` is joined from these labels **and stored on the Book**,
        so a person reads the order.

        The fold used to emit surviving entries in key order, so dropping an
        undeclared entry that came first moved its label to wherever the
        declared one sat: this record answered `Informatik; Roman` where the
        plain string deduplication it replaced answered `Roman; Informatik`.
        """
        record = Record(
            subjects=(
                Subject("Roman"),
                Subject("Informatik", "gnd"),
                Subject("Roman", "gnd"),
            )
        )

        assert record.subject_labels == ["Roman", "Informatik"]
        assert record.as_match()["categories"] == "Roman; Informatik"

    def test_an_undeclared_subject_survives_beside_a_declared_one(self):
        """The label matters and not merely whether anything was declared.

        Written after attacking the rule: a fold asking "did **any** field
        declare" rather than "did any field declare *this label*" passes every
        other test in this class, and drops `Roman` off any record that also
        carries one GND heading. That is a live shape, not a hypothetical: a DNB
        record declaring `gnd` on its `650` and a K10plus record declaring
        nothing on its own reach one `Record` through `merged_with`.
        """
        declared = Subject("Informatik", "gnd", "(DE-588)4026894-9")
        other = Subject("Roman")

        assert Record(subjects=(declared, other)).subjects == (declared, other)

    def test_one_author_named_by_both_100_and_700_is_asserted_once(self):
        record = Record(author_identifiers=(KANE, KANE))

        assert record.author_identifiers == (KANE,)

    def test_two_records_disagreeing_about_one_name_keep_both_assertions(self):
        """The opposite call from `_union`, and the reason `_distinct` is not it.

        A heading's caption is folded towards a single answer because there is
        one to fold towards. Two catalogues giving one spelling two GND numbers
        is a disagreement, and hiding it behind whichever answered first is what
        the store refuses to do at its own layer: see
        `authorship.Authorship.record_catalogue_assertions`.
        """
        other = AuthorityAssertion("Sean P. Kane", AuthorityScheme.GND, "9999")
        record = Record(author_identifiers=(KANE, other))

        assert record.author_identifiers == (KANE, other)


class TestAuthorityAssertionsFollowTheCollectionRules:
    """Filed with `subjects` and `headings`, not with the scalars.

    `_FILLED` tests a scalar with `is None`, which an empty tuple is not, so a
    collection listed there would never fill a gap and nothing would say so.
    """

    def test_a_row_with_no_assertions_takes_the_other_row_s(self):
        empty = Record(source="google", title="X")
        dnb = Record(source="dnb", title="X", author_identifiers=(KANE,))

        assert empty.filled_from(dnb).author_identifiers == (KANE,)

    def test_a_row_that_has_assertions_keeps_its_own_on_the_search_path(self):
        """The leading catalogue describes the book. Two rows meet on the search
        path because they share a title, an author and a year, which is a guess.
        """
        leading = Record(source="dnb", title="X", author_identifiers=(KANE,))
        other = Record(source="loc", title="X", author_identifiers=(MATTHIAS,))

        assert leading.filled_from(other).author_identifiers == (KANE,)

    def test_the_lookup_path_carries_both_catalogues_assertions(self):
        """Every record `merged_with` folds was found by the same verified ISBN,
        so both are describing the people who wrote this printing."""
        dnb = Record(source="dnb", title="X", author_identifiers=(KANE,))
        onb = Record(source="onb", title="X", author_identifiers=(MATTHIAS,))

        assert dnb.merged_with(onb).author_identifiers == (KANE, MATTHIAS)

    def test_neither_draft_shape_carries_an_assertion(self):
        """The same omission ADR 0006 gets for Classifications, for the same
        reason: `refresh` and automatic `enrich` write from these dictionaries,
        and an assertion reaches the store from the `Record` itself instead. A
        key here would put a third party value into a request body a client
        posts back."""
        record = Record(source="dnb", isbn="1", title="X", author_identifiers=(KANE,))

        assert "author_identifiers" not in record.as_lookup()
        assert "author_identifiers" not in record.as_match()


class TestFillingOneRowFromAnother:
    """`filled_from`, which is the search path: only gaps are filled."""

    def test_an_absent_scalar_is_filled(self):
        leading = Record(source="open_library", title="Dune")
        following = Record(source="k10plus", title="Dune", page_count=412)

        assert leading.filled_from(following).page_count == 412

    def test_a_present_scalar_is_not_overwritten(self):
        """The leading catalogue stays the one describing the book."""
        leading = Record(source="open_library", title="Dune", publisher="Ace")
        following = Record(source="k10plus", title="Dune", publisher="Heyne")

        assert leading.filled_from(following).publisher == "Ace"

    def test_a_zero_is_a_value_and_not_an_absence(self):
        """Falsiness would let the next source overwrite a real series index.

        This used to be asserted on a `page_count` of 0, which
        `_NUMBER_RANGES` now clears at construction. `series_index` is bounded
        at 0 inclusive, so it is the scalar that still reaches this rule falsy,
        and the rule is unchanged.
        """
        leading = Record(source="bnf", title="A pamphlet", series_index=0.0)
        following = Record(source="loc", title="A pamphlet", series_index=4.0)

        assert leading.filled_from(following).series_index == 0.0

    def test_an_empty_string_is_a_value_and_not_an_absence(self):
        leading = Record(source="bnf", title="Untitled", subtitle="")
        following = Record(source="loc", title="Untitled", subtitle="a novel")

        assert leading.filled_from(following).subtitle == ""

    def test_an_empty_heading_list_is_an_absence(self):
        """The live defect this rule was written for: `[]` is not `None`, so an
        empty list used to beat a populated one from the next source. Over 30
        live title searches, 6 of the 10 merged rows whose Library of Congress
        half carried LCSH lost every heading."""
        leading = Record(source="bnf", title="Les Miserables")
        following = Record(source="loc", title="Les Miserables", headings=(LCSH,))

        assert leading.filled_from(following).headings == (LCSH,)

    def test_a_populated_heading_list_is_not_unioned(self):
        """Two rows meet here on a title and a year, which is a guess. Unioning
        them would also break the ceiling: a row is bounded at
        `MAX_CLASSIFICATIONS_PER_BOOK` and `BookMatch` refuses a ninth."""
        leading = Record(source="open_library", title="X", headings=(DDC_004,))
        following = Record(source="loc", title="X", headings=(LCSH,))

        assert leading.filled_from(following).headings == (DDC_004,)

    def test_every_catalogue_that_answered_is_named(self):
        leading = Record(source="bnf", title="X")
        following = Record(source="loc", title="X")

        assert leading.filled_from(following).source == "bnf+loc"

    def test_the_catalogues_behind_a_merged_row_are_readable_without_the_separator(self):
        row = Record(source="bnf", title="X").filled_from(Record(source="loc", title="X"))

        assert row.sources == {"bnf", "loc"}

    def test_a_record_naming_no_catalogue_names_none(self):
        """`sources` on an empty string is empty, not a set holding `""`."""
        assert Record().sources == frozenset()


class TestMergingTwoCataloguesOfOnePrinting:
    """`merged_with`, which is the lookup path: every record is the same ISBN."""

    def test_both_catalogues_headings_are_kept(self):
        dnb = Record(source="dnb", title="X", headings=(GND,))
        k10plus = Record(source="k10plus", title="X", headings=(DDC_004,))

        assert dnb.merged_with(k10plus).headings == (GND, DDC_004)

    def test_both_catalogues_subjects_are_kept_in_order(self):
        dnb = Record(source="dnb", title="X", subjects=uncontrolled(("Informatik",)))
        k10plus = Record(source="k10plus", title="X", subjects=uncontrolled(("Roman",)))

        assert dnb.merged_with(k10plus).subjects == (
            Subject("Informatik"),
            Subject("Roman"),
        )

    def test_one_subject_both_catalogues_carry_is_kept_once(self):
        dnb = Record(source="dnb", title="X", subjects=uncontrolled(("Informatik",)))
        k10plus = Record(
            source="k10plus", title="X", subjects=uncontrolled(("Informatik",))
        )

        assert dnb.merged_with(k10plus).subjects == (Subject("Informatik"),)

    def test_one_catalogues_stamp_reaches_the_others_bare_subject(self):
        """Two catalogues describing one printing, one of which said which
        vocabulary the heading is from. The fold is across the merge, so the
        merged record carries the stamp once rather than the word twice."""
        dnb = Record(
            source="dnb",
            title="X",
            subjects=(Subject("Informatik", "gnd", "(DE-588)4026894-9"),),
        )
        k10plus = Record(
            source="k10plus", title="X", subjects=uncontrolled(("Informatik",))
        )

        assert dnb.merged_with(k10plus).subjects == (
            Subject("Informatik", "gnd", "(DE-588)4026894-9"),
        )

    def test_one_number_from_two_sources_keeps_the_caption(self):
        """Taking the leading source whole would throw a caption away.

        **No live source pair exercises this for DDC any more**, and that is the
        reason it is pinned here rather than through a lookup. Until 2026-08-24
        the DNB captioned its Dewey number and K10plus did not; both now answer
        with the number alone, so the case a merge can still meet is a stored
        heading being re-enriched, which `_write_classifications` resolves with
        this same rule.
        """
        bare = Record(source="k10plus", title="X", headings=(DDC_004,))
        captioned = Record(source="dnb", title="X", headings=(DDC_004_CAPTIONED,))

        assert bare.merged_with(captioned).headings == (DDC_004_CAPTIONED,)

    def test_a_scalar_still_only_fills_a_gap(self):
        """The collections are unioned here and the scalars are not."""
        dnb = Record(source="dnb", title="X", publisher="Hanser")
        k10plus = Record(source="k10plus", title="X", publisher="Heyne")

        assert dnb.merged_with(k10plus).publisher == "Hanser"


class TestHowCompleteARecordIs:
    """The score that decides which printing and which catalogue leads."""

    def test_an_empty_record_scores_nothing(self):
        assert Record().completeness == 0

    def test_each_field_a_reader_recognises_a_copy_from_counts_once(self):
        record = Record(author="Frank Herbert", year=1965, publisher="Ace")

        assert record.completeness == 3

    def test_subjects_count_once_however_many_there_are(self):
        assert Record(subjects=uncontrolled(("a", "b", "c"))).completeness == 1

    def test_a_title_does_not_count(self):
        """Every record has one, so it separates nothing."""
        assert Record(title="Dune").completeness == 0

    def test_headings_do_not_count(self):
        """A record is not more recognisable for carrying a call number."""
        assert Record(headings=(DDC_004,)).completeness == 0


class TestTheTwoDraftShapes:
    """`as_lookup` and `as_match` fill two schemas, and must not drift from them."""

    #: What each schema holds that a Record deliberately does not supply.
    #: `classifications` is ADR 0006: a draft dictionary carrying none is what
    #: stops an unattended writer adding one. `suggested_tag_ids` is the
    #: library's own reading of the record rather than the catalogue's.
    NOT_FROM_THE_RECORD = {"classifications", "suggested_tag_ids"}

    def test_the_lookup_draft_fills_every_key_its_schema_names(self):
        assert set(Record().as_lookup()) == (
            set(BookLookup.model_fields) - self.NOT_FROM_THE_RECORD
        )

    def test_the_match_draft_fills_every_key_its_schema_names(self):
        assert set(Record().as_match()) == (
            set(BookMatch.model_fields) - self.NOT_FROM_THE_RECORD
        )

    def test_neither_draft_carries_a_classification(self):
        """ADR 0006 held by the type. Automatic enrichment and Refresh Metadata
        write from these dictionaries, so a heading they cannot carry is a
        heading an unattended write cannot store."""
        record = Record(source="dnb", title="X", headings=(GND, DDC_004))

        assert "classifications" not in record.as_lookup()
        assert "classifications" not in record.as_match()

    def test_a_match_calls_the_isbn_isbn13(self):
        """A search row is one printing among several rather than the one asked
        for, which is the only reason the two schemas spell it differently."""
        record = Record(source="loc", title="X", isbn="9780262046305")

        assert record.as_match()["isbn13"] == "9780262046305"
        assert record.as_lookup()["isbn"] == "9780262046305"

    def test_a_category_containing_a_comma_survives_the_round_trip(self):
        """Google's own category names contain commas, which is why the joined
        column uses a semicolon. A record holding one must come back whole."""
        record = Record(subjects=uncontrolled(("Fiction, general", "Computers")))

        assert record.as_match()["categories"] == "Fiction, general; Computers"

    def test_one_word_under_two_vocabularies_reaches_the_wire_once(self):
        """`_folded_subjects` keeps both on purpose. `categories` is one string
        a person reads, where the same word twice reads as a defect."""
        record = Record(
            subjects=(
                Subject("Roemisches Recht", "gnd", "(DE-588)4076560-1"),
                Subject("Roemisches Recht", "local"),
            )
        )

        assert record.as_match()["categories"] == "Roemisches Recht"

    def test_a_record_with_no_subjects_carries_no_categories(self):
        """`null` rather than `""`, so a client tests for one absence."""
        assert Record(title="X").as_match()["categories"] is None

    def test_an_untitled_record_fills_the_lookup_schema_with_an_empty_title(self):
        """`BookLookup.title` is required and a thin catalogue answer is not."""
        assert Record().as_lookup()["title"] == ""

    def test_an_untitled_record_leaves_a_match_title_absent(self):
        """`BookMatch.title` is optional, and the row is dropped upstream."""
        assert Record().as_match()["title"] is None


class TestTheHeadingsAPickedRowConfirms:
    def test_a_row_carries_no_more_headings_than_a_book_may_hold(self):
        """`BookMatch` refuses a ninth entry and `main.py` catches no
        `ValidationError`, so an unbounded row is a 500 waiting for the next
        endpoint that builds one. Measured over four live DNB `WOE=` searches on
        2026-08-24: 8 of 189 records carry more than eight headings."""
        record = Record(
            source="dnb",
            title="X",
            headings=tuple(
                Heading(ClassificationScheme.GND, f"{index}") for index in range(12)
            ),
        )

        assert len(record.match_headings()) == MAX_CLASSIFICATIONS_PER_BOOK

    def test_the_record_keeps_every_heading_it_was_given(self):
        """The bound belongs to the row, not to the record: the lookup path
        orders by scheme before it cuts, and cutting first would drop a Dewey
        number an ordering would have saved."""
        headings = tuple(
            Heading(ClassificationScheme.GND, f"{index}") for index in range(12)
        )

        assert len(Record(headings=headings).headings) == 12


class TestTheFoldRunsOncePerSetOfCollections:
    """The difference between a flat cost and a product, on a hostile response.

    `_merge_matches` folds every row sharing a title, an author and a year onto
    one slot, and every fold builds a new `Record`. Before `_folded`, each of
    those re-inspected the whole subject and heading lists of whichever row was
    fat, so the cost is the **product** of the row count and that record's
    width. Measured on a four core worker, one process, CPython 3.14.7: 8,176
    rows against a record carrying 22,784 subjects and 11,392 headings, which
    is the worst shape fitting inside `fetch.MAX_RESPONSE_BYTES` at
    `_loc_record`'s measured per element costs, took **125.970s** without this
    field and 0.227s with it. `_merge_matches` is synchronous inside
    `async def search`, so that is the event loop stopped for every Member at
    once. `catalogue.Record._folded` carries the budget arithmetic, the second
    measured shape, and the two times this figure has been recorded wrong.

    Pinned by counting entries inspected rather than by a clock, so the test
    fails on the defect rather than on a busy machine.
    """

    @staticmethod
    def _counting(monkeypatch) -> list[int]:
        """Every entry the three folds look at, one entry per element."""
        inspected: list[int] = []
        real_unique = catalogue._folded_subjects
        real_union = catalogue._union
        # The third collection is counted too, and deliberately: a fold that
        # escaped `_folded` here would be invisible to a counter watching only
        # the two that existed when this test was written.
        real_distinct = catalogue._distinct

        def unique(values):
            values = tuple(values)
            inspected.append(len(values))
            return real_unique(values)

        def union(headings):
            headings = tuple(headings)
            inspected.append(len(headings))
            return real_union(headings)

        def distinct(assertions):
            assertions = tuple(assertions)
            inspected.append(len(assertions))
            return real_distinct(assertions)

        monkeypatch.setattr(catalogue, "_folded_subjects", unique)
        monkeypatch.setattr(catalogue, "_union", union)
        monkeypatch.setattr(catalogue, "_distinct", distinct)
        return inspected

    @staticmethod
    def _fat() -> Record:
        return Record(
            source="loc",
            title="X",
            subjects=uncontrolled(f"subject {index}" for index in range(200)),
            headings=tuple(
                Heading(ClassificationScheme.LCSH, f"heading {index}")
                for index in range(200)
            ),
            author_identifiers=tuple(
                AuthorityAssertion(f"Author {index}", AuthorityScheme.GND, str(index))
                for index in range(200)
            ),
        )

    def test_filling_a_row_again_and_again_never_folds_it_again(self, monkeypatch):
        row = self._fat()
        inspected = self._counting(monkeypatch)

        for _ in range(50):
            row = row.filled_from(Record(source="bnf", title="X"))

        assert sum(inspected) == 0

    def test_merging_folds_again_because_it_is_the_one_that_concatenates(
        self, monkeypatch
    ):
        """The other half of the rule. `merged_with` passes `_folded=False`, and
        a record that stopped folding there would keep both catalogues' repeats.
        """
        row = self._fat()
        inspected = self._counting(monkeypatch)

        row.merged_with(
            Record(source="dnb", title="X", subjects=uncontrolled(("subject 0",)))
        )

        assert sum(inspected) > 0

    def test_a_repeat_the_second_catalogue_brings_is_still_folded(self):
        """What the count above is protecting, asserted on the values."""
        first = Record(source="dnb", title="X", subjects=uncontrolled(("Informatik",)))
        second = Record(
            source="k10plus", title="X", subjects=uncontrolled(("Informatik",))
        )

        assert first.merged_with(second).subjects == (Subject("Informatik"),)


class TestWhatARecordFillsIsEveryScalarItHolds:
    def test_every_scalar_fact_is_one_a_record_fills(self):
        """`_FILLED` is exhaustive by assertion rather than by inspection.

        A new scalar left out of it silently never fills a gap, and a new
        collection put into it is tested with `is None`, which `()` is not, so
        it never fills either. Neither shows up as an error anywhere.
        """
        names = {field.name for field in dataclasses.fields(Record)}

        assert set(catalogue._FILLED) == names - {
            "source",
            "subjects",
            "headings",
            "author_identifiers",
            "_folded",
        }


class TestARecordFitsTheColumnsItFeeds:
    """A scalar the Book's column cannot hold is cleared at construction.

    The ticket this closes: `PUT /api/books/{id}/refresh` writes nine columns
    straight off a record, and eight of them had no ceiling in the schema, in
    the model or in SQLite, which does not enforce a `VARCHAR` length. Bounding
    the refresh handler alone would have been a fourth door beside `as_lookup`,
    `_match_rows` and `_bounded_match`; bounding the record is the one place all
    four agree.

    The rule is the one the enrichment route settled: the value too wide loses
    **that field**, never the record and never a Member's own request.
    """

    @pytest.mark.parametrize("name", BOUNDED)
    def test_a_value_the_column_can_hold_is_kept(self, name):
        widest: dict[str, Any] = {name: _at_every_ceiling()[name]}

        assert getattr(Record(source="dnb", **widest), name) == widest[name]

    @pytest.mark.parametrize("name", BOUNDED)
    def test_a_value_the_column_cannot_hold_is_dropped(self, name):
        past: dict[str, Any] = {name: _one_past(name)}

        assert getattr(Record(source="dnb", **past), name) is None

    @pytest.mark.parametrize("name", sorted(catalogue._NUMBER_RANGES))
    def test_a_number_below_its_floor_is_dropped(self, name):
        low, _ = catalogue._NUMBER_RANGES[name]
        below: dict[str, Any] = {name: low - 1}

        assert getattr(Record(source="dnb", **below), name) is None

    @pytest.mark.parametrize("name", sorted(catalogue._NUMBER_RANGES))
    def test_a_number_at_its_floor_is_kept(self, name):
        low, _ = catalogue._NUMBER_RANGES[name]
        floor: dict[str, Any] = {name: low}

        assert getattr(Record(source="dnb", **floor), name) == low

    @pytest.mark.parametrize("name", BOUNDED)
    def test_the_record_keeps_every_other_field_it_was_given(self, name):
        """The field, not the record. Asserted per field rather than on one of
        them, because a guard proved on one field is then trusted for the ones
        beside it."""
        fields: dict[str, Any] = _at_every_ceiling() | {name: _one_past(name)}

        record = Record(source="dnb", **fields)

        kept = {other: getattr(record, other) for other in BOUNDED if other != name}
        assert kept == {other: fields[other] for other in BOUNDED if other != name}

    def test_a_record_at_every_ceiling_is_a_body_the_create_schema_accepts(self):
        """The two ends of the same rule meet: nothing a record keeps is a value
        this app's own request body would refuse.

        `isbn` is overridden with a real one because `_at_every_ceiling` pads
        it to the column and `BookCreate` refuses this field on its checksum:
        see `VALID_ISBN`.
        """
        record = Record(source="dnb", **(_at_every_ceiling() | VALID_ISBN))

        assert BookCreate(**record.as_lookup()).title == _widest("title")

    @pytest.mark.parametrize("name", [name for name in BOUNDED if name != "title"])
    def test_a_record_over_one_ceiling_is_still_a_body_the_create_schema_accepts(self, name):
        """What the refresh route used to store: a value its own edit form
        answers 422 for. Driven per field, because `BookCreate` is what a Member
        posts back after a scan and what `BookDetailsUpdate` mirrors."""
        record = Record(
            source="dnb",
            **(_at_every_ceiling() | VALID_ISBN | {name: _one_past(name)}),
        )

        assert BookCreate(**record.as_lookup()) is not None

    def test_an_oversized_title_reaches_the_draft_empty_for_the_member_to_fill(self):
        """`title` is the one field where dropping cannot be transparent, and
        the column is why: it is the Book's only `NOT NULL` text column, so
        `BookCreate` requires at least one character and `as_lookup` coerces an
        absent title to `""` rather than omitting it.

        That is still the better of the two answers. A Member posting this back
        unchanged gets "at least 1 character" against an empty box they can see,
        where before they got "at most 500 characters" against a title they
        would have had to trim by hand.
        """
        record = Record(source="dnb", isbn="9780743273565", title=_one_past("title"))

        assert record.as_lookup()["title"] == ""
        with pytest.raises(ValidationError):
            BookCreate(**record.as_lookup())

    def test_an_oversized_description_no_longer_makes_the_lookup_draft_raise(self):
        """`BookLookup.description` carries `max_length=DESCRIPTION_MAX` and is
        built inside the scan handler, where a `ValidationError` reaches
        `errors.unhandled_exception_handler` and answers a Member's scan with a
        500. The bound one layer down is what makes that unreachable."""
        record = Record(
            source="dnb",
            isbn="9780743273565",
            title="X",
            description="x" * (DESCRIPTION_MAX + 1),
        )

        assert BookLookup(**record.as_lookup()).description is None

    def test_a_cover_chosen_after_the_fold_is_bounded_too(self):
        """`with_cover` replaces a scalar on a record whose `_folded` flag is
        already set, so a bound below that guard would let this one field
        through. It is the only `replace` in this module that introduces a value
        from outside."""
        record = Record(source="dnb", title="X").with_cover(
            "https://example.com/" + "x" * catalogue._TEXT_CEILINGS["cover_url"]
        )

        assert record.cover_url is None

    def test_a_cover_url_is_measured_as_the_column_will_store_it(self):
        """`Book`'s `@validates("cover_url")` runs `covers.https_url` on every
        write, which turns `http://` into `https://` and lengthens the value by
        one character. Measuring the parsed form stored 501 characters in a
        `String(500)`: one over on SQLite, a failed flush on an engine that
        enforces it. http is the ordinary case rather than an edge, since
        Google Books serves `imageLinks.thumbnail` over it.
        """
        ceiling = catalogue._TEXT_CEILINGS["cover_url"]
        at_the_ceiling_once_stored = "http://" + "x" * (ceiling - len("https://"))

        assert len(at_the_ceiling_once_stored) == ceiling - 1
        assert (
            Record(source="dnb", cover_url=at_the_ceiling_once_stored).cover_url
            == at_the_ceiling_once_stored
        )
        assert Record(source="dnb", cover_url=at_the_ceiling_once_stored + "x").cover_url is None

    def test_an_https_url_is_measured_as_it_stands(self):
        """The other half of that diagonal: the rewrite only lengthens a URL it
        changes, so a value already https is bounded at the ceiling itself and
        not one below it."""
        ceiling = catalogue._TEXT_CEILINGS["cover_url"]
        widest = "https://" + "x" * (ceiling - len("https://"))

        assert len(widest) == ceiling
        assert Record(source="dnb", cover_url=widest).cover_url == widest

    def test_a_dropped_field_is_named_in_the_log_with_the_catalogue_that_sent_it(
        self, caplog
    ):
        with caplog.at_level(logging.INFO, logger="endpaper.catalogue"):
            Record(source="dnb", title="x" * (catalogue._TEXT_CEILINGS["title"] + 1))

        assert "title" in caplog.text
        assert "dnb" in caplog.text

    def test_a_record_that_fits_says_nothing(self, caplog):
        with caplog.at_level(logging.INFO, logger="endpaper.catalogue"):
            Record(source="dnb", title="Dune")

        assert caplog.text == ""


class TestWhichScalarsAreBoundedAndWhichAreNamedInstead:
    def test_every_scalar_is_bounded_or_deliberately_not(self):
        """A field added to `Record` and left out of both tables would be
        written to a column with no ceiling, which is the whole of the defect
        this closes, and nothing else would notice. So it has to be classified
        before the suite passes."""
        names = {field.name for field in dataclasses.fields(Record)}

        assert set(BOUNDED) | catalogue._UNBOUNDED == names - {
            "subjects",
            "headings",
            "author_identifiers",
            "_folded",
        }

    def test_which_scalars_are_left_unbounded(self):
        """The composition, not the coverage, and they are two assertions.

        The union above is unchanged by moving a name out of a ceilings table
        and into `_UNBOUNDED` in one gesture, which is precisely the change that
        would need arguing. Measured by a design critic seat over every field in
        turn, against the twelve bounded fields as the tables stood then: with
        the coverage assertion alone, eleven of them could be moved here with
        the whole suite still green.

        **The denominator is named because it has already moved.** It is
        `BOUNDED`, and bounding `isbn` grew it without touching the finding, so
        an unscoped fraction was stale in the very commit that bounded the
        field. The measurement is what it was measured against; the
        finding is what survives it.

        **The literal below has to move with the subject**, and it has been left
        behind before: it named one scalar while the set held two, after a
        revert, and the seat that asked for this assertion found that too. That
        is the cost of a guard naming its subject in a literal, and it is worth
        paying, because it is the only thing here that notices a name moving
        between the two tables.
        """
        assert frozenset({"source"}) == catalogue._UNBOUNDED

    def test_no_scalar_is_in_both_tables(self):
        assert not set(catalogue._TEXT_CEILINGS) & set(catalogue._NUMBER_RANGES)

    def test_nothing_bounded_is_also_named_as_unbounded(self):
        assert not set(BOUNDED) & catalogue._UNBOUNDED

    def test_an_isbn_wider_than_its_column_is_dropped(self):
        """The most expensive line in this file to have got right, and it says
        the opposite of what it said until the exclusion was decided again.

        What it bought is a whole search row: `BookMatch.isbn13` is bounded at
        20 and `_match_rows` drops the record, so a malformed identifier used to
        cost the row rather than the field. What it costs is stated by the test
        below, and why that cost is unreachable is stated at `_UNBOUNDED`.
        """
        wide = "9" * (ISBN_MAX + 1)

        assert Record(source="dnb", isbn=wide, title="X").isbn is None

    def test_an_absent_isbn_makes_the_lookup_draft_raise(self):
        """What bounding it would cost if a producer could reach here with a
        wide value. `BookLookup.isbn` is required, so an absent ISBN raises
        where the scan handler builds the draft, and nothing catches a
        `ValidationError` there.

        Kept as the statement of the risk rather than deleted with the
        exclusion: the bound is safe because no lookup producer can supply a
        value the ceiling clears, not because this stopped being a 500."""
        with pytest.raises(ValidationError):
            BookLookup(**Record(source="dnb", title="X").as_lookup())

    def test_the_ceiling_admits_every_isbn_the_parser_can_produce(self):
        """Why the bound cannot clear the field on the lookup path, recomputed
        here rather than stated at `_UNBOUNDED`.

        Every producer reaching `BookLookup` sets `isbn` from the canonicalised
        argument `metadata.lookup` was given or from `isbn.parse`'s own output,
        and the argument is that same function's output, so one width decides
        it. Driven over both of `parse`'s returning branches, the ISBN-13 it
        validates and the ISBN-10 it converts, and over the separator forms
        `normalise` strips, since a form that survived normalisation would be
        the way a wider value got through.

        A sweep rather than a reading of `_ISBN13_LENGTH`, which would be the
        constant agreeing with itself.
        """
        widths = {
            len(parsed)
            for raw in _every_shape_of_a_real_isbn()
            for parsed in [isbn_utils.parse(raw)]
            if parsed is not None
        }

        assert widths, "the sweep produced no ISBNs, so it asserts nothing"
        assert max(widths) <= ISBN_MAX

    def test_the_sweep_reaches_both_of_the_parsers_returning_branches(self):
        """The diagonal for the test above, which its own width assertion cannot
        make: both branches return thirteen characters, so dropping either one
        leaves that assertion green. Measured, and it is why this exists.

        The branches are told apart by what `parse` does with the value rather
        than by how the fixture built it: an ISBN-13 comes back as its own
        normalised form, and an ISBN-10 comes back as something else.
        """
        outcomes = {
            isbn_utils.parse(raw) == isbn_utils.normalise(raw)
            for raw in _every_shape_of_a_real_isbn()
        }

        assert outcomes == {True, False}

    def test_the_google_adapter_parses_its_own_identifier(self):
        """**This test was inverted at the wave merge of 2026-09-03, and the
        inversion is the point.**

        It read `..._would_reach_that_raise_if_the_field_were_bounded` and
        asserted the defect: `metadata._google_record` preferred the volume's
        own unparsed `industryIdentifiers` entry over the canonicalised
        argument, so an over-wide one became the record's ISBN, and a bound
        would have cleared it into the raise above. That was the stated reason
        this field stays out of the ceilings.

        Another trio closed it in the same wave, in a file this one did not own,
        and the two tripwires here went red on the merged tree, which is what
        they were for. The exclusion was then decided again and the field is
        bounded, so **this pair is now the precondition rather than the record
        of a defect**: the ceiling is safe only while every producer parses its
        own identifier, and these two are what say it does. See
        `catalogue._UNBOUNDED`, where the decision lives.
        """
        argument = "9780743273565"
        wider_than_the_column = "9" * (ISBN_MAX * 2)
        record = metadata._google_record(
            {"isbn13": wider_than_the_column, "title": "Dune"}, argument
        )

        # Both halves, inverted together: the over-wide identifier is refused,
        # and what survives is the canonicalised argument rather than nothing,
        # because clearing the field is itself the 500 this whole exclusion is
        # about. The width is derived from the column rather than typed, so it
        # cannot fall under the ceiling if that ever moves.
        assert len(record.isbn or "") <= ISBN_MAX
        assert record.isbn == argument

    def test_the_lookup_path_gets_the_parsed_value(self, monkeypatch):
        """The same tripwire one layer out, on the value rather than on the call,
        and inverted with its sibling at the 2026-09-03 merge.

        The test above drives `_google_record` directly, so a canonicalisation
        added at the **call site** would leave it green while the exclusion went
        on costing a search row for nothing.

        **Pinned on the value, after a source read was measured and found
        weak.** That version asserted `"_google_record(" in` the caller's source,
        and a security seat mutated the real source four ways: it caught the call
        being replaced, and missed the call being wrapped, the identifier being
        parsed before the call, and the name surviving only in a docstring. 1 of
        4. This one is false under all four, because it reads what the record
        ends up holding.

        Stubbing `lookup_by_isbn` is what **removes** the network rather than
        what adds a fixture: it is the function that would make the request.
        """
        wider_than_the_column = "9" * (ISBN_MAX * 2)

        async def one_volume(isbn: str, api_key: str) -> dict[str, Any]:
            return {"isbn13": wider_than_the_column, "title": "Dune"}

        # The module object, not `metadata.google_books`, which mypy refuses as
        # an implicit re-export. It is the same object either way: `metadata`
        # resolves `google_books.lookup_by_isbn` at call time.
        monkeypatch.setattr(google_books, "lookup_by_isbn", one_volume)
        result = asyncio.run(metadata._google_books("9780743273565", "key"))

        assert result.record is not None
        assert len(result.record.isbn or "") <= ISBN_MAX
        assert result.record.isbn == "9780743273565"


class TestARecordAgreesWithTheColumnsItFeeds:
    """The ceilings are recomputed from the table rather than restated here.

    **What that buys is a tripwire, not independence, and the difference is
    worth stating.** `models.py` supplies both sides of the width comparison:
    the column is declared `String(TITLE_MAX)` and the ceiling is `TITLE_MAX`.
    So the comparison cannot detect drift, because there is nothing left to
    drift; it detects a literal being written back into either side, which is
    the arrangement it exists to prevent. The class docstring said the first
    thing until a critic seat pointed out that the same diff had removed the
    second place.

    The assertions that are not tautologies are the ones against `BookMatch`
    below: those constants are declared separately and a record wider than the
    model it feeds would be stored, because SQLite does not enforce a `VARCHAR`
    length and would only fail on a database that does.
    """

    @staticmethod
    def _declared() -> dict[str, Any]:
        """What each bounded column says its own width is. `Text` says nothing,
        so the value is `None` there rather than absent."""
        return {
            name: getattr(Book.__table__.c[name].type, "length", None)
            for name in catalogue._TEXT_CEILINGS
        }

    def test_only_the_description_column_declares_no_width_of_its_own(self):
        declared = self._declared()

        assert {name for name, width in declared.items() if width is None} == {
            "description"
        }

    def test_every_ceiling_with_a_column_width_is_that_width(self):
        """**A tautology today and kept as a tripwire.** `models.py` supplies
        both sides: the column is declared `String(TITLE_MAX)` and the ceiling
        is `TITLE_MAX`, so this compares a constant with itself and goes red
        only once a literal written into one of them stops tracking the other.

        **It does not catch the literal, and it used to claim it did.** A
        ceiling written `20` beside a column declared `String(ISBN_MAX)` passes
        here, because 20 is what `ISBN_MAX` is: measured, the whole file stayed
        green. The test below is what catches it, and this one is what catches
        the constant moving afterwards."""
        declared = {
            name: width for name, width in self._declared().items() if width is not None
        }

        assert declared == {
            name: ceiling
            for name, ceiling in catalogue._TEXT_CEILINGS.items()
            if name != "description"
        }

    def test_every_ceiling_comes_from_the_module_that_declares_the_columns(self):
        """What keeps the comparison above a tripwire instead of a coincidence.

        A ceiling that is not the constant `models.py` declares agrees with its
        column on the day it is written and stops moving with it, and nothing
        comparing the two **values** can tell the difference: the mutation
        writing `20` for `ISBN_MAX` passed every test in this file.

        **The import list, not merely a name, and that is the correction rather
        than the rule.** A first version asked only that the value be an
        `ast.Name`, which a local `_ISBN_CEILING = 20` satisfies while stopping
        dead exactly as the literal would. A critic seat measured it: the whole
        file stayed green. The literal was the example and this is the family.

        **What it still cannot see**, stated rather than left to be found, and
        the two cases are refused by different things. A ceiling naming the
        **wrong** constant from that module, `TITLE_MAX` on `isbn`, is imported
        and passes here; `test_every_ceiling_with_a_column_width_is_that_width`
        refuses it, because the two values then differ, so neither arm is the
        rule on its own. An imported name **rebound in the module body**,
        `ISBN_MAX = 20` under the import, passes both: the source arm finds the
        name in the import list and the value arm finds the column's own width.
        Nothing in this file catches that one. **ruff F811** does, measured
        through this project's own config, which is why no third arm is written
        for it: a rule the linter already holds is not one to restate here.

        Read off the source rather than the imported table, because by the time
        the module is loaded a literal and a constant are the same integer.
        Structural on both sides, so a ceiling added later and a constant
        imported later are both covered without a further arm.
        """
        module = ast.parse(pathlib.Path(catalogue.__file__).read_text())
        from_models = {
            alias.asname or alias.name
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom) and node.module == "models"
            for alias in node.names
        }
        assert from_models, "nothing is imported from models, so this asserts nothing"

        table = next(
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_TEXT_CEILINGS"
        )
        assert isinstance(table, ast.Dict)

        elsewhere = {
            cast(ast.Constant, key).value: ast.unparse(value)
            for key, value in zip(table.keys, table.values, strict=True)
            if ast.unparse(value) not in from_models
        }

        assert elsewhere == {}, (
            "These ceilings are not the constant `models.py` declares for the "
            "column, so they agree with it today and stop moving with it: "
            + repr(elsewhere)
        )

    def test_the_text_column_takes_the_ceiling_its_schemas_already_carry(self):
        """`description` is `Text`, so the column declares nothing and the
        number has to come from somewhere. It comes from the one every request
        body already holds it to."""
        assert catalogue._TEXT_CEILINGS["description"] == DESCRIPTION_MAX

    def test_every_bounded_field_is_a_column_on_the_book(self):
        """A ceiling on a field no column stores would be bounding nothing."""
        assert set(BOUNDED) <= set(Book.__table__.c.keys())

    def test_no_ceiling_is_wider_than_the_model_the_record_feeds(self):
        """The property the whole ticket is: a record never carries a value one
        of its own wire shapes would refuse.

        Against `BookMatch` rather than `BookCreate`, because it is the model
        every bounded field appears on. `BookCreate` has no `google_books_id`,
        so a guard driven off it alone would leave that one field checked by
        nothing, which is this repository's standing shape for a bound proved on
        the fields beside the one that matters.
        """
        wider = {
            name: (ceiling, limit.max_length)
            for name, ceiling in catalogue._TEXT_CEILINGS.items()
            for limit in BookMatch.model_fields[_match_keys()[name]].metadata
            if isinstance(limit, annotated_types.MaxLen) and ceiling > limit.max_length
        }

        assert wider == {}

    def test_every_bounded_string_reaches_that_model_under_some_name(self):
        """The other half, since the check above is vacuous for a name the model
        does not carry, and a field `as_match` silently stopped filling would be
        exactly that."""
        assert set(_match_keys()) == set(catalogue._TEXT_CEILINGS)
        assert set(_match_keys().values()) <= set(BookMatch.model_fields)

    def test_exactly_one_bounded_field_is_renamed_on_the_wire(self):
        """Derived rather than assumed, and the rename is live since `isbn`
        joined the ceilings: `as_match` calls a record's `isbn` `isbn13`,
        because a search row is one printing among several rather than the one
        asked for.

        Assuming the names matched is what broke these guards the first time
        that field was bounded, and this is now also the diagonal for
        `_match_keys`: with it replaced by the identity this assertion fails,
        where before no live rename existed for it to miss."""
        assert {name: key for name, key in _match_keys().items() if name != key} == {
            "isbn": "isbn13"
        }

    def test_the_derivation_reads_the_table_it_is_handed(self):
        """The other half of the diagonal, which the assertion above cannot
        make: it drives the live table, so a `_match_keys` ignoring its argument
        and reading `_TEXT_CEILINGS` would satisfy it.

        Measured by the seat that found the first version of this test: with
        `_match_keys` replaced by the identity, all four of its consumers
        passed, this one included, which is why it is written on a table with a
        single entry rather than on the live one.
        """
        assert _match_keys({"isbn": ISBN_MAX}) == {"isbn": "isbn13"}

    def test_no_number_a_record_carries_is_renamed_on_the_wire(self):
        """So the numeric comparison below may use the record's own names."""
        assert set(catalogue._NUMBER_RANGES) <= set(Record(source="dnb").as_match())

    def test_no_number_range_is_wider_than_that_model_either(self):
        """Numbers are bounded by range rather than by width, so they need
        their own comparison and are not covered by the two above."""
        wider: dict[str, tuple[str, float, float]] = {}
        for name, (low, high) in catalogue._NUMBER_RANGES.items():
            for limit in BookMatch.model_fields[name].metadata:
                # `annotated_types` types these as `SupportsGe` and `SupportsLe`
                # rather than as numbers, so mypy refuses the comparison until
                # they are named for what every bound in this tree actually is.
                if isinstance(limit, annotated_types.Ge):
                    floor = cast(float, limit.ge)
                    if low < floor:
                        wider[name] = ("floor", low, floor)
                if isinstance(limit, annotated_types.Le):
                    ceiling = cast(float, limit.le)
                    if high > ceiling:
                        wider[name] = ("ceiling", high, ceiling)

        assert wider == {}


class TestARecordFromAnUploadedFile:
    """`Record.from_upload`, the one producer that truncates rather than drops.

    A catalogue answering over the network is asserting something about a book
    this Library holds, so half an assertion is worse than none. An uploaded
    MARC file is the Member's own shelf arriving at once, and `books.title` is
    `NOT NULL`, so a dropped title costs the row rather than the field.
    """

    @pytest.mark.parametrize("name", sorted(catalogue._CUT_ON_UPLOAD))
    def test_a_string_too_wide_is_cut_to_the_column(self, name):
        record = Record.from_upload(source="marc_upload", **{name: _one_past(name)})

        assert len(getattr(record, name)) == catalogue._TEXT_CEILINGS[name]

    @pytest.mark.parametrize("name", sorted(catalogue._KEPT_WHOLE_ON_UPLOAD))
    def test_a_string_a_cut_would_rename_is_dropped_here_too(self, name):
        """A cut title is the same book. A cut URL is a different address, a cut
        volume id names a different volume, and a cut language code names a
        different language. See `_CUT_ON_UPLOAD`."""
        record = Record.from_upload(source="marc_upload", **{name: _one_past(name)})

        assert getattr(record, name) is None

    @pytest.mark.parametrize("name", sorted(catalogue._TEXT_CEILINGS))
    def test_the_same_value_is_dropped_on_the_network_path(self, name):
        """The diagonal. A test that only drove `from_upload` would pass with
        the two policies collapsed into one."""
        past: dict[str, Any] = {name: _one_past(name)}

        assert getattr(Record(source="dnb", **past), name) is None

    @pytest.mark.parametrize("name", sorted(catalogue._NUMBER_RANGES))
    def test_a_number_out_of_range_is_dropped_on_both_paths(self, name):
        """Numbers are the half both policies already agreed on, so
        `from_upload` states nothing about them and cannot disagree."""
        past: dict[str, Any] = {name: _one_past(name)}

        assert getattr(Record.from_upload(source="marc_upload", **past), name) is None

    def test_a_value_the_column_holds_is_untouched(self):
        record = Record.from_upload(source="marc_upload", title=_widest("title"))

        assert record.title == _widest("title")

    def test_the_collections_are_still_folded(self):
        """`from_upload` builds through the ordinary constructor, so a parser
        that repeats itself costs nothing here either."""
        record = Record.from_upload(
            source="marc_upload", title="X", headings=(DDC_004, DDC_004)
        )

        assert record.headings == (DDC_004,)

    def test_every_bounded_string_is_cut_or_kept_whole_and_not_both(self):
        """Exhaustive by assertion. A text field added to the ceilings and to
        neither set would fall out of `from_upload` silently and be truncated by
        nothing and dropped by nothing on the upload path."""
        assert (
            set(catalogue._TEXT_CEILINGS)
            == catalogue._CUT_ON_UPLOAD | catalogue._KEPT_WHOLE_ON_UPLOAD
        )
        assert not catalogue._CUT_ON_UPLOAD & catalogue._KEPT_WHOLE_ON_UPLOAD

    def test_no_module_but_the_marc_reader_opens_this_door(self):
        """The containment, not the behaviour. A second producer truncating a
        catalogue's assertion would undo the split above without any test
        failing, so the call site is counted rather than trusted.

        **A call, not the spelling.** The first version of this searched for the
        substring and would have been tripped by `importing.py`, which names
        `from_upload` in prose to say where the truncation now happens. A
        docstring mentioning a door is not a caller, and a guard that cannot
        tell them apart makes writing the explanation fail the suite.

        **And application files, not everything under `backend/`.** The second
        version walked and parsed **2,977** files, **2,879** of them inside
        `backend/.venv`, taking 12.9 seconds against 98 application files. It
        passed only because no dependency happens to call anything named
        `from_upload`. `test_house_rules._is_vendored` is the rule this tree
        already keeps for that, written after CI's `UV_CACHE_DIR` put a cache
        under `backend/` and turned a green local walk red on every push.
        """
        backend = pathlib.Path(catalogue.__file__).parent
        callers = [
            relative
            for path in sorted(backend.rglob("*.py"))
            if not _is_vendored(path)
            for relative in [path.relative_to(backend).as_posix()]
            if not relative.startswith("tests/")
            and relative != "catalogue.py"
            and _opens_the_upload_door(path.read_text())
        ]

        assert callers == ["marc.py"]

    def test_that_guard_can_tell_a_call_from_a_mention(self):
        """The diagonal for the guard above, driving the same predicate rather
        than a copy of it: a fixture that reimplements what it checks proves
        nothing about the check."""
        assert _opens_the_upload_door("Record.from_upload(title='X')")
        assert not _opens_the_upload_door('"""names Record.from_upload in prose"""')
