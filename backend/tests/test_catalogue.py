"""The typed draft every source adapter normalises into.

What is pinned here is the seam itself: the folding rules, the completeness
score, and the two wire shapes. What each catalogue's parser makes of its own
XML is pinned in `test_metadata.py`, which is where the parsers are.
"""

import dataclasses

import catalogue
from catalogue import AuthorityAssertion, Heading, Record, Subject, uncontrolled
from enums import AuthorityScheme, ClassificationScheme
from schemas.book import BookLookup, BookMatch
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK

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
        """Falsiness would let the next source overwrite a real page count."""
        leading = Record(source="bnf", title="A pamphlet", page_count=0)
        following = Record(source="loc", title="A pamphlet", page_count=480)

        assert leading.filled_from(following).page_count == 0

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
