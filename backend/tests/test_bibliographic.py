"""Tests for backend/bibliographic.py.

Every rule here is read by decoders for several serialisations, so a test that
reaches one of those decoders is testing the decoder. These are the rules on
their own: one value in, one answer out, no record and no transport.

The catalogue shaped cases live where the catalogue does. `tests/test_metadata.py`
pins what the DNB, the NKP, the BnF and the Library of Congress do with these
answers, and `tests/test_marc.py` pins what an uploaded file and an export do.
"""

import ast
from pathlib import Path

import pytest

import bibliographic
from bibliographic import (
    BIBLIOGRAPHIC_CODES,
    LANGUAGES,
    flip_catalogue_name,
    is_placeholder_title,
    pages_from_extent,
    split_title_statement,
)
from tests.test_house_rules import BACKEND, _python_sources


class TestTitleStatement:
    """The BnF still writes a whole statement into `dc:title`, and so does a
    MARC record old enough not to have subfielded itself."""

    def test_drops_the_statement_of_responsibility(self):
        assert split_title_statement("Dune / Frank Herbert") == ("Dune", None)

    def test_splits_the_subtitle_off_the_colon(self):
        assert split_title_statement("Docker : eine Einfuehrung") == (
            "Docker",
            "eine Einfuehrung",
        )

    def test_drops_the_bracketed_original_title_of_a_translation(self):
        """The brackets hold a different book's title, in another language."""
        assert split_title_statement(
            "[Docker: up and running] ; Praxiswissen Docker"
        ) == (
            "Praxiswissen Docker",
            None,
        )

    def test_keeps_a_colon_that_is_part_of_the_title(self):
        """Only " : " separates a subtitle. A bare colon is punctuation."""
        assert split_title_statement("Docker: up and running") == (
            "Docker: up and running",
            None,
        )

    def test_drops_a_second_work_bound_into_the_same_volume(self):
        assert split_title_statement("Erstes Werk ; Zweites Werk") == (
            "Erstes Werk",
            None,
        )


class TestIsbdPunctuation:
    """A catalogue ends a subfield with the separator for the one after it.

    Named for the cataloguing standard and not for MARC, which is what the
    callers say: the Czech National Library writes the same punctuation into
    un-namespaced Dublin Core.
    """

    def test_drops_the_separator_that_introduces_the_next_subfield(self):
        assert bibliographic.strip_isbd_punctuation("Stoner :") == "Stoner"
        assert bibliographic.strip_isbd_punctuation("Trilogy;") == "Trilogy"

    def test_leaves_punctuation_inside_the_value_alone(self):
        assert bibliographic.strip_isbd_punctuation("Docker: up and running") == (
            "Docker: up and running"
        )


class TestPageCount:
    """Shared by the DNB and K10plus parsers, which spell the extent differently."""

    def test_reads_the_german_form(self):
        assert pages_from_extent("390 Seiten") == 390

    def test_reads_the_english_form(self):
        assert pages_from_extent("412 pages") == 412

    def test_returns_nothing_for_an_extent_it_cannot_parse(self):
        assert pages_from_extent("1 Online-Ressource") is None

    def test_reads_the_abbreviated_form_k10plus_uses(self):
        assert pages_from_extent("348 S.") == 348

    def test_ignores_the_dimensions_that_follow_the_extent(self):
        """A bare first number picks up "23 cm" as a page count."""
        assert pages_from_extent("528 p. : ill. ; 23 cm") == 528

    def test_returns_nothing_for_an_absent_field(self):
        assert pages_from_extent(None) is None


class TestAPageCountIsBoundedAtBothEnds:
    """What the reader refuses, which is a separate behaviour from what it reads.

    **The bound is a fix for a 500, not tidiness.** CPython raises `ValueError`
    on an int conversion of more than `sys.get_int_max_str_digits()` digits, and
    that is neither `httpx.HTTPError` nor `ElementTree.ParseError`, so no SRU
    handler caught it: one record carrying 4,301 digits in its `300 $a` turned
    search and lookup into a 500 for every MARC source at once.

    **The half that needs a source is not here.**
    `tests/test_metadata.py::TestAHostileSourceCostsItsOwnRows` drives the same
    extent through a live shaped response and asserts the request is not a 500;
    this is the parser on its own, which is the split this file exists for.
    """

    @pytest.mark.parametrize(
        "extent, expected",
        [
            ("390 Seiten", 390),
            ("348 S.", 348),
            ("528 p.", 528),
            ("III, 272 S.", 272),
            # The bound `_open_library_pages` has always applied, now applied
            # here too: a page count out of range is no page count.
            ("999999 Seiten", None),
            ("0 Seiten", None),
            # The digit run is refused whole rather than having its tail read
            # as a page count, which is what a bare `\d{1,6}` would have done.
            ("9" * 4301 + " Seiten", None),
            ("9" * 12 + " Seiten", None),
            # **This is the case that actually pins the lookbehind**, and the
            # two above are not: with `\d{1,6}` and no lookbehind they match
            # the last six digits, `999999`, which the range check rejects
            # anyway, so both still answer None with the guard removed. Here
            # the tail is a plausible page count, so dropping the lookbehind
            # invents 350 out of the end of an attack. Measured: the mutation
            # survived the whole file until this row existed.
            ("1" * 20 + "000350 Seiten", None),
            # Still not a page count.
            ("23 cm", None),
            (None, None),
        ],
    )
    def test_a_page_count_is_bounded_at_both_ends(self, extent, expected):
        assert pages_from_extent(extent) == expected


class TestPlaceholderTitles:
    """The DNB's identifier index matches a mention, not an identity."""

    def test_a_volume_slot_is_not_a_title(self):
        assert is_placeholder_title("[Hauptbd.].")
        assert is_placeholder_title("Bd. 3")
        assert is_placeholder_title("Volume 2")
        assert is_placeholder_title("")

    def test_a_real_title_is_kept(self):
        assert not is_placeholder_title("Stoner")
        # "Band" is a prefix of this and must not match it.
        assert not is_placeholder_title("Banditen")


class TestDenoising:
    """What the catalogues return that is not a book on a shelf."""

    @pytest.mark.parametrize(
        "extent",
        [
            "1 Online-Ressource (100 Seiten)",
            "1 online resource",
            "1 audio disc",
            "1 sound recording",
        ],
    )
    def test_a_digitised_or_recorded_copy_is_not_a_book(self, extent):
        assert not bibliographic.is_physical_book(extent, "Der Zauberberg")

    def test_a_printed_extent_is_a_book(self):
        assert bibliographic.is_physical_book("992 Seiten", "Der Zauberberg")

    def test_a_record_with_no_extent_is_allowed(self):
        """Plenty of good records omit it, and refusing them loses real books."""
        assert bibliographic.is_physical_book(None, "Der Zauberberg")

    def test_a_volume_slot_is_still_rejected(self):
        assert not bibliographic.is_physical_book("992 Seiten", "[Hauptbd.].")


class TestTheDiscHalfOnItsOwn:
    """`is_a_disc` is the half the DNB lookup refuses outright.

    The online half it only ranks down, because an online resource is this book
    in another form and a disc is a different object. A test that asked
    `is_physical_book` could not tell the two halves apart.
    """

    def test_a_disc_is_named_by_the_disc_half_alone(self):
        assert bibliographic.is_a_disc("1 audio disc")
        assert bibliographic.is_a_disc("1 videodisc")

    def test_an_online_resource_is_not_a_disc(self):
        """It is refused by the other half, and this one must not claim it."""
        assert not bibliographic.is_a_disc("1 Online-Ressource (100 Seiten)")
        assert not bibliographic.is_physical_book("1 Online-Ressource (100 Seiten)", "X")

    def test_a_printed_extent_and_an_absent_one_are_not_discs(self):
        assert not bibliographic.is_a_disc("992 Seiten")
        assert not bibliographic.is_a_disc(None)


class TestAPersonNameInCatalogueOrder:
    """Catalogues hang life dates and roles off a name. None of it is the name."""

    def test_turns_catalogue_order_into_a_readable_name(self):
        assert flip_catalogue_name("Kane, Sean P.") == "Sean P. Kane"

    def test_keeps_the_full_stop_that_belongs_to_an_initial(self):
        """`Pohl, Robert O.` means nothing as `Robert O`, and the ISBD full stop
        stripped off `Melville, Herman.` looks the same to a regex."""
        assert flip_catalogue_name("Pohl, Robert O.") == "Robert O. Pohl"

    def test_drops_the_life_dates_a_catalogue_hangs_off_a_name(self):
        assert flip_catalogue_name("Melville, Herman, 1819-1891") == "Herman Melville"

    def test_strips_the_bnf_life_dates_and_role_together(self):
        assert (
            flip_catalogue_name("Zafón, Carlos (1964-2020). Auteur du texte")
            == "Carlos Zafón"
        )

    def test_leaves_an_ordinary_name_alone(self):
        assert flip_catalogue_name("Mann, Thomas") == "Thomas Mann"

    def test_leaves_a_corporate_name_alone(self):
        """Two commas is not "Surname, Forenames" and reordering would mangle it."""
        assert (
            flip_catalogue_name("Springer Verlag, Berlin, Heidelberg")
            == "Springer Verlag, Berlin, Heidelberg"
        )

    def test_leaves_a_two_comma_corporate_name_in_catalogue_order(self):
        assert (
            flip_catalogue_name("Springer, Berlin, Heidelberg")
            == "Springer, Berlin, Heidelberg"
        )


class TestOnlyTheBranchThatFlipsACellMayTakeItsFullStop:
    """"Left alone" is the docstring's word, and the noise strip broke it.

    `_strip_person_noise` removed a terminal full stop from every cell it was
    handed, including the ones the flip then refused to touch, and
    `_TRAILING_INITIAL` spares a single letter only, so every multi letter
    abbreviation lost its stop on the way through a branch that rewrote
    nothing.

    The population is not hypothetical. A LibraryThing "Primary Author" cell is
    typed by a member, so a full stop at its end is an abbreviation (`Dr.`,
    `Jr.`, `Co.`, `Inc.`, `Ltd.`) rather than the ISBD punctuation the removal
    exists for. Which of the two a cell carries is a fact about where the cell
    came from, so only a branch that is rewriting the name anyway may decide.
    """

    @pytest.mark.parametrize(
        "cell",
        [
            "Doubleday & Co.",
            "Simon & Schuster, New York, Inc.",
            "Harcourt Brace Jovanovich, New York, Inc.",
            "Frank Herbert",
            "Springer Verlag, Berlin, Heidelberg",
            "Ursula K. Le Guin",
        ],
    )
    def test_a_cell_it_will_not_flip_comes_back_as_it_arrived(self, cell):
        assert flip_catalogue_name(cell) == cell

    def test_a_trailing_separator_comma_still_comes_off(self):
        """The one edit a refused cell does take, and it is the edit `.strip()`
        already is: punctuation between fields rather than part of a name."""
        assert (
            flip_catalogue_name("Springer, Berlin, Heidelberg,")
            == "Springer, Berlin, Heidelberg"
        )

    def test_the_life_dates_still_come_off_a_cell_it_will_not_flip(self):
        """The bound in the other direction, and the one the first fix for this
        got wrong: a refused cell keeps its full stop, not its noise. Dates and
        a role word are not part of a corporate name either, and seven call
        sites in `metadata.py` store what comes back."""
        assert flip_catalogue_name("Zafón Carlos (1964-2020)") == "Zafón Carlos"
        assert (
            flip_catalogue_name("Bibliothèque nationale de France. Éditeur")
            == "Bibliothèque nationale de France"
        )

    def test_a_name_it_does_flip_does_lose_its_terminal_full_stop(self):
        """The other side of the same rule, and the arm without which
        `_drop_isbd_stop` can be deleted from the flip branch in silence:
        every other flipping case in this file is written without a stop.
        `Pohl, Robert O.` above is what stops the removal going too far."""
        assert flip_catalogue_name("Mann, Thomas.") == "Thomas Mann"

    def test_a_name_it_does_flip_still_loses_its_life_dates(self):
        """The evasion this guard is written against.

        Counting the commas before the noise comes off passes every arm above
        and silently stops this flipping, because the cell carries two commas
        until the dates go.
        """
        assert flip_catalogue_name("Melville, Herman, 1819-1891") == "Herman Melville"

    def test_a_full_stop_after_the_life_dates_does_not_save_them(self):
        """`_PERSON_NOISE`'s date arm is anchored at the end of the string, so
        a stop behind the dates hides them from it. That was uncovered only
        because the stop removal ran first, inside the same loop."""
        assert flip_catalogue_name("Melville, Herman, 1819-1891.") == "Herman Melville"

    def test_a_run_of_spaces_cannot_buy_the_regex_more_work(self):
        """Two of `_PERSON_NOISE`'s three arms are a `\\s*` in front of a rare
        literal, which is quadratic over a whitespace run, and this function is
        on the CSV import path. Measured on a worker node: 1.28 ms for one 500
        character run of spaces, against 1 microsecond once collapsed.
        """
        assert flip_catalogue_name("a" + " " * 498 + "b") == "a b"


class TestTheTwoLanguageTablesAreOneTable:
    """`BIBLIOGRAPHIC_CODES` is derived from `LANGUAGES` and must stay so.

    Two hand written tables would drift the first time one of them gained a
    language, and the only thing that would notice is a round trip nobody ran.
    """

    def test_every_language_the_readers_know_can_be_written(self):
        """Otherwise a book stored in a language the lookup path understands
        exports with no `041` at all, silently."""
        missing = sorted(set(LANGUAGES.values()) - set(BIBLIOGRAPHIC_CODES))
        assert missing == []

    def test_every_code_written_reads_back_as_the_code_it_came_from(self):
        """The inversion is not one to one, so this is the property that
        matters rather than the table's size."""
        for stored, written in BIBLIOGRAPHIC_CODES.items():
            assert LANGUAGES[written] == stored

    @pytest.mark.parametrize(
        "stored, code",
        [("de", "ger"), ("fr", "fre"), ("nl", "dut")],
    )
    def test_a_language_with_two_codes_is_written_in_the_bibliographic_one(
        self, stored, code
    ):
        """MARC's own Code List for Languages takes the bibliographic code, and
        both codes read back as the same two letter one, so nothing else here
        can see a reordering of `LANGUAGES` silently choosing the other."""
        assert BIBLIOGRAPHIC_CODES[stored] == code


class TestTheProseRuleIsReachedOnlyThroughACarrierAwareDoor:
    """`is_physical_book` has four callers and each is a door of its own.

    One for MARC and one for each Dublin Core dialect, plus MODS. A fifth is a
    parse path that has skipped the carrier test, or a new source whose
    serialisation nobody classified. `bibliographic._NOT_A_BOOK` is written in
    German and English, so a Czech online resource reached a shelf (#124); the
    codes answer that, and the way a code test stops being applied is that
    somebody parses a record the way the neighbours do, minus one line.

    **The scan is every module of ours and not one file, and that is what
    publishing this name cost.** While the rule was `metadata._is_physical_book`
    a second module reaching it had to spell a private name, which
    `tests/test_marc.py::test_marc_is_the_only_module_reaching_into_another`
    refuses outside `marc.py`. A public name in another module is refused by
    neither, so the check that used to read `metadata.py` alone now reads the
    package.

    **Both call spellings, and the `Attribute` arm is the one that matters
    here.** `metadata.py` imports the name, so its calls are `Name`; every other
    module would reach it as `bibliographic.is_physical_book`, which an `ast`
    walk keyed on `Name` cannot see. A guard that saw one spelling would be
    green on the whole class of evasion it was written for.

    **What it cannot see**, stated rather than left to be found. An aliased call
    (`door = is_physical_book` then `door(...)`), which no module here takes,
    and a caller that asks and **discards** the answer, which is the limit every
    guard keyed on call names lives with and the one
    `tests/test_shelf.py::TestTheShelfIsTheOnlyWayIn` records for the privacy
    rule. A source that reimplements the prose rule rather than calling it is
    outside this check entirely: that is a second copy of an alternation, which
    is a finding on its own before it is a hole here.
    """

    #: Every caller, as `<path>::<function>`, so a door moving file is a failure
    #: here rather than a silent pass.
    #:
    #: **The path and not the module stem**, which a critic measured: this
    #: package holds more than one `opds.py` and more than one `covers.py`, so a
    #: stem key is not one to one over the tree it is asked about. Keyed on the
    #: stem, a new `routers/metadata.py` defining `_bnf_record` and calling the
    #: rule left this set unchanged and the assertion green.
    #:
    #: **And the function half is qualified for the same reason**, one rung in:
    #: a `def` nested inside another function, or a method, takes the name of
    #: whatever encloses it too. Keyed on the innermost name alone, a second
    #: caller named `_bnf_record` nested inside another function of
    #: `metadata.py` was invisible. Both are driven below rather than described.
    DOORS = frozenset(
        {
            "metadata.py::_marc_is_physical_book",
            "metadata.py::_bnf_record",
            "metadata.py::_loc_record",
            "metadata.py::_nkp_record",
        }
    )

    @staticmethod
    def _callers(name: str, root: Path = BACKEND) -> set[str]:
        """Every function under `root` that calls `name`, by either spelling.

        **`root` is a parameter for the reason `_python_sources` takes one**: a
        walk asserted only against this checkout is a walk nobody has watched
        fail. The test below drives it against a tree it builds.
        """
        found: set[str] = set()

        def visit(node: ast.AST, path: str, qualified: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                ):
                    inner = (
                        child.name
                        if qualified == "<module>"
                        else f"{qualified}.{child.name}"
                    )
                    visit(child, path, inner)
                    continue
                if isinstance(child, ast.Call):
                    func = child.func
                    if (isinstance(func, ast.Name) and func.id == name) or (
                        isinstance(func, ast.Attribute) and func.attr == name
                    ):
                        found.add(f"{path}::{qualified}")
                visit(child, path, qualified)

        for path in _python_sources(root):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            visit(tree, str(path.relative_to(root)), "<module>")
        return found

    def test_the_walk_reaches_this_package_and_not_an_installed_copy(self):
        """Every assertion below is about whatever the walk returns, so a wrong
        anchor makes them vacuous while staying green. `test_marc.py` records
        the pipeline where that happened."""
        walked = {path.stem for path in _python_sources(BACKEND)}
        assert {"bibliographic", "metadata", "marc"} <= walked
        assert "site-packages" not in BACKEND.parts

    def test_only_the_four_doors_reach_the_prose_rule(self):
        callers = self._callers("is_physical_book")
        assert callers == set(self.DOORS), sorted(callers ^ set(self.DOORS))

    def test_a_fifth_caller_is_reported_whichever_way_it_is_spelled(self, tmp_path):
        """The evasion this guard exists for, driven rather than stated.

        `metadata.py` imports the name, so every call in the repository today is
        an `ast.Name`; a guard keyed on that alone would be green on the whole
        class of evasion publishing the name opened, which is a module reaching
        it as `bibliographic.is_physical_book`. Both spellings are put to the
        real walk here, and a module scope call with them, because a rule
        applied outside a function is still a path that skipped the door.
        """
        (tmp_path / "importer.py").write_text(
            "import bibliographic\n"
            "from bibliographic import is_physical_book\n"
            "def plainly(extent):\n"
            "    return is_physical_book(extent, 'T')\n"
            "def by_attribute(extent):\n"
            "    return bibliographic.is_physical_book(extent, 'T')\n"
            "AT_IMPORT = bibliographic.is_physical_book('1 online resource', 'T')\n",
            encoding="utf-8",
        )
        assert self._callers("is_physical_book", tmp_path) == {
            "importer.py::plainly",
            "importer.py::by_attribute",
            "importer.py::<module>",
        }

    def test_a_door_is_named_by_its_file_and_not_by_its_module_stem(self, tmp_path):
        """A fifth caller that reuses a door's function name in another file.

        **The evasion a stem key let through, and it is not hypothetical**: the
        walk covers files whose stems repeat, `opds` three times among them, so
        the key space was already not one to one over the tree being asked
        about. A critic seat drove this against the live walk and the assertion
        above stayed green, because the new caller landed on a key the expected
        set already held.
        """
        (tmp_path / "metadata.py").write_text(
            "import bibliographic\n"
            "def _bnf_record(extent):\n"
            "    return bibliographic.is_physical_book(extent, 'T')\n",
            encoding="utf-8",
        )
        (tmp_path / "routers").mkdir()
        (tmp_path / "routers" / "metadata.py").write_text(
            "import bibliographic\n"
            "def _bnf_record(extent):\n"
            "    return bibliographic.is_physical_book(extent, 'T')\n",
            encoding="utf-8",
        )
        assert self._callers("is_physical_book", tmp_path) == {
            "metadata.py::_bnf_record",
            "routers/metadata.py::_bnf_record",
        }

    def test_a_door_is_named_by_what_encloses_it_and_not_by_its_own_name(
        self, tmp_path
    ):
        """The same collision one rung in, inside a single file.

        A `def` nested in another function, and a method, can take a door's own
        name, and keyed on the innermost name alone the second caller lands on
        the key the expected set already holds and disappears. A critic seat
        drove this against the live walk and the assertion above stayed green.
        """
        (tmp_path / "metadata.py").write_text(
            "import bibliographic\n"
            "def _bnf_record(extent):\n"
            "    return bibliographic.is_physical_book(extent, 'T')\n"
            "def elsewhere(extent):\n"
            "    def _bnf_record(e):\n"
            "        return bibliographic.is_physical_book(e, 'T')\n"
            "    return _bnf_record(extent)\n"
            "class Reader:\n"
            "    def _bnf_record(self, extent):\n"
            "        return bibliographic.is_physical_book(extent, 'T')\n",
            encoding="utf-8",
        )
        assert self._callers("is_physical_book", tmp_path) == {
            "metadata.py::_bnf_record",
            "metadata.py::elsewhere._bnf_record",
            "metadata.py::Reader._bnf_record",
        }
