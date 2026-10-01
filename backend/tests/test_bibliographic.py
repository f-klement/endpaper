"""Tests for backend/bibliographic.py.

Every rule here is read by decoders for several serialisations, so a test that
reaches one of those decoders is testing the decoder. These are the rules on
their own: one value in, one answer out, no record and no transport.

The catalogue shaped cases live where the catalogue does. `tests/test_metadata.py`
pins what the DNB, the NKP, the BnF and the Library of Congress do with these
answers, and `tests/test_marc.py` pins what an uploaded file and an export do.
"""

import ast
import inspect
import re
import string
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import bibliographic
from bibliographic import (
    BIBLIOGRAPHIC_CODES,
    LANGUAGES,
    flip_catalogue_name,
    is_placeholder_title,
    pages_from_extent,
    split_title_statement,
    strip_isbd_punctuation,
)
from models import MAX_PAGE_NUMBER_IN_A_BOOK
from tests.strategies import text_around, witness
from tests.test_house_rules import BACKEND, _python_sources

#: The letter class `bibliographic._AN_INITIAL` scopes a flag out of, written
#: here rather than parsed back out of that constant: the arm below is about
#: what the flag does to this class, so reading the class off the thing under
#: test would agree with it by construction.
_AN_INITIAL_CLASS = "[A-Za-z]"


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
    publishing this name cost.** While the rule was a private name in `metadata.py`
    a second module reaching it had to spell a private name, which
    `tests/test_marc.py::TestNoModuleReadsAnotherModulesPrivateNames` refuses
    everywhere. A public name in another module is refused by neither, so the
    check that used to read `metadata.py` alone now reads the package.

    **Both call spellings, and the `Attribute` arm is the one that matters
    here.** `marc_fields.py` imports the name, so its calls are `Name`; every
    other module reaches it as `bibliographic.is_physical_book`, which an `ast`
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
            "marc_fields.py::Fields.describes_a_book",
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


# ── The same rules as properties ──────────────────────────────────────────────
#
# **The classes above are catalogue records: the wordings six national libraries
# actually send.** They are the reason each rule is shaped the way it is and
# they stay. What is below is what the wordings are instances of, over strings
# nobody picked, and the two answer different questions. A case says "the DNB
# writes this"; a property says "and nothing else gets through either".
#
# **Every generator here is derived from the rule it is about**, and two of them
# from the very regular expression under test, through `from_regex`. That is
# deliberate where the property is an agreement between two functions: the disc
# alternation is half of the not-a-book one, this module's docstring says so,
# and a generator built from the disc pattern is what notices if the halves stop
# agreeing.

_TEXT = st.text(max_size=80)
_MAYBE_TEXT = st.one_of(st.none(), _TEXT)

#: An extent statement naming a disc, generated from the pattern that defines
#: one rather than from the wordings a reader can think of.
_DISC_EXTENTS = text_around(st.from_regex(bibliographic._IS_A_DISC, fullmatch=True))

#: An extent statement naming something published online, the same way.
_ONLINE_EXTENTS = text_around(st.from_regex(bibliographic._ONLINE_FORMS, fullmatch=True))

#: A title that is a position in a multi-volume set.
_PLACEHOLDER = st.from_regex(bibliographic._PLACEHOLDER_TITLES, fullmatch=True)

#: The units an extent statement is read through, which is the list the rule
#: itself carries: only spellings actually measured are in it.
_UNITS = st.sampled_from(["Seiten", "S.", "p.", "pp.", "stran", "Bl."])


def _digit_run(length: st.SearchStrategy[int]) -> st.SearchStrategy[str]:
    """A run of digits of a drawn length, built by repetition.

    **Not `st.text(min_size=4_301)`, and the difference is the whole point of
    the witness beside this.** Hypothesis draws sizes from a distribution that
    reaches the maximum rarely, so a strategy whose only long values sit at the
    top of a wide size range produces them almost never: the first version of
    this generator failed its own reachability witness at two thousand
    examples. Drawing the length and repeating gives the long case its own
    branch.
    """
    return st.builds(
        lambda seed, size: (seed * (size // len(seed) + 1))[:size],
        st.text(alphabet="0123456789", min_size=1, max_size=20),
        length,
    )


#: An extent statement with a unit on it, including the digit run that turned
#: every MARC source into a 500 at once: one record carried 4,301 digits in its
#: `300 $a`, and CPython refuses an integer conversion above that with a
#: `ValueError` no handler on that path was catching.
_EXTENTS = st.one_of(
    _TEXT,
    st.builds(lambda run, unit: f"{run} {unit}", _digit_run(st.integers(1, 8)), _UNITS),
    st.builds(
        lambda run, unit: f"{run} {unit}",
        _digit_run(st.integers(4_301, 4_600)),
        _UNITS,
    ),
)


def _text_arguments(function) -> list[Any] | None:
    """A strategy per parameter, or None when this signature is not all text.

    Read off the annotations rather than off a list of function names, so a
    rule added to the module is swept by the property below without anybody
    remembering to add it. A signature this cannot answer for is what the arm
    under `TestEveryRuleHereIsSwept` reports, by name.
    """
    strategies: list[Any] = []
    for parameter in inspect.signature(function).parameters.values():
        if parameter.annotation is str:
            strategies.append(_TEXT)
        elif parameter.annotation == (str | None):
            strategies.append(_MAYBE_TEXT)
        else:
            return None
    return strategies


def _pure_rules() -> dict[str, tuple]:
    """Every function this module defines, with the arguments it takes."""
    return {
        name: (function, _text_arguments(function))
        for name, function in vars(bibliographic).items()
        if inspect.isfunction(function)
        and function.__module__ == bibliographic.__name__
        # `__annotate__` is the module's own PEP 649 annotation evaluator, put
        # here by the interpreter rather than by anybody writing a rule.
        and not name.startswith("__")
    }


class TestEveryRuleHereIsSwept:
    def test_the_sweep_covers_every_function_in_the_module(self):
        """**The arm that fails when a rule joins the module and nothing tests it.**

        A new function whose parameters are not text is not a failure of the
        rule, it is a signature this sweep cannot build arguments for, and the
        answer is to teach `_text_arguments` about it rather than to let it sit
        outside the properties unnoticed. Naming the functions here instead
        would be a list somebody has to remember, which is the thing this
        repository keeps paying for.
        """
        unswept = [name for name, (_, args) in _pure_rules().items() if args is None]
        assert not unswept, (
            f"these rules take arguments the property sweep cannot generate: "
            f"{unswept}. Teach `_text_arguments` their annotation."
        )

    def test_the_sweep_finds_the_module(self):
        """The vacuity arm. Every assertion over `_pure_rules()` passes on an
        empty dictionary, including the one above."""
        assert len(_pure_rules()) >= 9


@pytest.mark.property
class TestEveryRuleAnswersForAnyString:
    @given(data=st.data())
    def test_no_rule_here_raises_on_any_text(self, data):
        """**A catalogue is an outside input and a decoder has no handler**, so
        a rule here that raises reaches the client as a 500.

        This is the sweep, and it asks only that every rule answers. It draws
        from `_TEXT`, so it is deliberately not where the hostile shapes live:
        those are under the classes below, each with the witness that proves
        its generator still reaches them.
        """
        for name, (function, strategies) in _pure_rules().items():
            if strategies is None:
                continue
            arguments = [data.draw(strategy) for strategy in strategies]
            try:
                function(*arguments)
            except Exception as error:
                raise AssertionError(
                    f"{name} raised {type(error).__name__} on {arguments!r}"
                ) from error


#: A run of text a catalogue would put between two ISBD separators.
_PHRASE = st.text(
    st.characters(categories=("Lu", "Ll", "Nd"), include_characters=" "),
    min_size=1,
    max_size=10,
)

#: A whole title statement, with the separators the two rules below are about.
#:
#: **Free text alone was the first version of this and it was nearly vacuous.**
#: The separators are three characters with a space on each side, so
#: `st.text()` produces one about nine times in two thousand draws: measured
#: over ten runs of two hundred, `" / "` appeared in seven of them and in two
#: runs nothing below exercised its own subject at all. The witnesses under this
#: class are what caught that, and this generator is what fixed it.
_TITLE_STATEMENTS = st.one_of(
    _TEXT,
    st.builds(
        lambda original, title, subtitle, second, responsibility: (
            original + title + subtitle + second + responsibility
        ),
        st.one_of(st.just(""), _PHRASE.map(lambda text: f"[{text}] ; ")),
        _PHRASE,
        st.one_of(st.just(""), _PHRASE.map(lambda text: f" : {text}")),
        st.one_of(st.just(""), _PHRASE.map(lambda text: f" ; {text}")),
        st.one_of(st.just(""), _PHRASE.map(lambda text: f" / {text}")),
    ),
)

#: A subfield ending in the punctuation that introduces the next one.
_ISBD_SUBFIELDS = st.one_of(
    _TEXT,
    st.builds(
        lambda text, separator, padding: text + separator + padding,
        _PHRASE,
        st.sampled_from(["", "/", ":", ";", ",", "=", " :", " ;"]),
        st.sampled_from(["", " ", "  "]),
    ),
)


@pytest.mark.property
class TestAValueIsQuotedFromTheRecordNeverRewritten:
    """Both of these hand back a slice of what arrived.

    A stored row is a catalogue assertion, and one this app has quietly
    rewritten is worse than one it declined: the schema validators state that
    for their own columns and these are the same rule for a title.
    """

    @given(raw=_ISBD_SUBFIELDS)
    def test_stripping_isbd_punctuation_only_removes(self, raw):
        stripped = strip_isbd_punctuation(raw)
        assert stripped in raw
        assert stripped == stripped.strip()

    @given(raw=_TITLE_STATEMENTS)
    def test_a_title_is_a_slice_of_the_statement_it_came_from(self, raw):
        title, subtitle = split_title_statement(raw)
        assert title in raw
        assert title == title.strip()
        assert " / " not in title, "the statement of responsibility survived"
        assert subtitle is None or (subtitle and subtitle == subtitle.strip())

    def test_the_generator_still_reaches_a_statement_of_responsibility(self):
        """`" / " not in title` is the only assertion above that can fail, so a
        generator producing no slash leaves that test asserting nothing."""
        witness(
            _TITLE_STATEMENTS,
            lambda raw: " / " in raw,
            reaches="a statement of responsibility",
        )

    def test_the_generator_still_reaches_a_subtitle(self):
        witness(
            _TITLE_STATEMENTS,
            lambda raw: split_title_statement(raw)[1] is not None,
            reaches="a statement that splits into a subtitle",
        )

    def test_the_generator_still_reaches_a_bracketed_original_title(self):
        """Asked as the arm firing rather than as the shape arriving: a
        statement that starts with a bracket and comes back without one is the
        only evidence the substitution ran."""
        witness(
            _TITLE_STATEMENTS,
            lambda raw: raw.startswith("[")
            and not split_title_statement(raw)[0].startswith("["),
            reaches="a translation whose original title is dropped",
        )

    def test_the_generator_still_reaches_punctuation_that_comes_off(self):
        witness(
            _ISBD_SUBFIELDS,
            lambda raw: strip_isbd_punctuation(raw) != raw.strip(),
            reaches="a subfield ending in the separator for the next one",
        )


@pytest.mark.property
class TestAPageCountIsBoundedWhateverArrives:
    """The recorded case is one record with 4,301 digits in its `300 $a`, which
    turned search and lookup into a 500 for every MARC source at once, because
    CPython refuses an integer conversion above that with a `ValueError` and
    nothing on that path was catching one.

    **`_EXTENTS` is where that input is generated and this is where it is
    asserted**, which is why the incident is named here rather than beside the
    sweep above: a generator of 80 character strings cannot hold 4,301 digits,
    so a claim about this record attached to that sweep would be describing a
    case it can never produce.
    """

    @given(raw=_EXTENTS)
    def test_the_answer_is_none_or_a_number_a_book_could_have(self, raw):
        pages = pages_from_extent(raw)
        assert pages is None or 0 < pages <= MAX_PAGE_NUMBER_IN_A_BOOK

    def test_the_generator_still_reaches_the_digit_run_that_caused_the_500(self):
        witness(
            _EXTENTS,
            lambda raw: sum(character.isdigit() for character in raw) > 4_300,
            reaches="an extent with more digits than CPython will convert",
        )

    def test_the_generator_still_reaches_an_extent_with_a_page_count_in_it(self):
        witness(
            _EXTENTS,
            lambda raw: pages_from_extent(raw) is not None,
            reaches="an extent that names a number of pages",
        )


@pytest.mark.property
class TestTheTwoHalvesOfOneRefusalStayOneRefusal:
    """`is_a_disc` is half of `is_physical_book`'s alternation, and this module's
    docstring is where that is claimed. A generator built from the disc pattern
    is what notices when the halves stop agreeing: split them and the property
    fails with a disc that is also a physical book.
    """

    @given(extent=_DISC_EXTENTS, title=_MAYBE_TEXT)
    def test_a_disc_is_never_a_physical_book(self, extent, title):
        assert bibliographic.is_a_disc(extent)
        assert not bibliographic.is_physical_book(extent, title)

    @given(extent=_ONLINE_EXTENTS, title=_MAYBE_TEXT)
    def test_an_online_resource_is_never_a_physical_book_either(self, extent, title):
        assert not bibliographic.is_physical_book(extent, title)

    @given(title=_PLACEHOLDER)
    def test_a_volume_slot_is_a_placeholder_title(self, title):
        assert is_placeholder_title(title)

    def test_the_disc_generator_reaches_more_than_one_wording(self):
        """The alternation is eight wordings wide and a generator stuck on the
        first of them would pass this class while testing one."""
        witness(
            _DISC_EXTENTS,
            lambda extent: "dvd" not in extent.lower(),
            reaches="a disc that is not spelled dvd",
        )


#: A word a person's name is made of.
_WORD = st.text(st.characters(categories=("Lu", "Ll")), min_size=1, max_size=8)

#: A span of life dates, in the two spellings this module's noise pattern was
#: written against: the BnF's `(1964-2020)` and MARC's `, 1819-1891`. A living
#: person has an open span, which is the empty second year.
_YEARS = st.builds(
    lambda born, died: f"{born}-{died}",
    st.integers(min_value=1_000, max_value=2_100),
    st.one_of(st.just(""), st.integers(min_value=1_000, max_value=2_100).map(str)),
)

#: A role word, read off the module rather than listed beside it.
#:
#: **A derivation refuses nothing, which is what the shape assertion below is
#: for.** A role removed from `bibliographic._PERSON_ROLES` narrows `_NOISE`
#: and `_ROLE_SURNAMES` in silence, and a property over a generator that
#: cannot reach its class is green and empty. One site reddens by name
#: instead.
_ROLES = st.sampled_from(bibliographic._PERSON_ROLES)

#: Life dates, in the two spellings a catalogue hangs them off a name with.
#:
#: **Named apart from the role word arm because they have to be crossed with
#: it.** A generator that offers a cell either dates or a role word cannot
#: reach the cell that carries both, and that is the cell the noise arms
#: compete over.
_DATE_NOISE = st.one_of(
    st.just(""),
    _YEARS.map(lambda years: f" ({years})"),
    _YEARS.map(lambda years: f", {years}"),
)

#: What a catalogue hangs off a name, as those catalogues write it.
_NOISE = st.one_of(_DATE_NOISE, _ROLES.map(lambda role: f". {role} du texte"))

#: A cell whose surname IS a role word, with the role word it was built from.
#:
#: Flipping `Autrice, A A.` manufactures `A A. Autrice`, where the initial's
#: full stop now sits exactly where the BnF puts the separator in front of a
#: designation, and the noise strip took the surname off as appended noise.
#:
#: **Both orders, because they break on different passes.** The catalogue
#: order cell survives one flip and loses the surname on the second, which is
#: the export and import round trip; the direct order cell is what that export
#: writes, and it loses the surname on the first pass, where an idempotence
#: property cannot see it at all.
#:
#: **Crossed with the life dates and with the ISBD stop, which is not a
#: combination for its own sake.** The refusal that keeps the role word sits
#: on the same arm that reaches the end of the cell, so a cell carrying dates
#: *after* the role word is the one where the arms compete: an earlier
#: refusal that consumed its match hid the date arms behind it and the cell
#: then flipped around the date's comma. A generator offering one or the other
#: is green on all of it.
#:
#: **Nothing else in `_CATALOGUE_NAMES` reaches a role word in surname
#: position.** They entered it through `_NOISE` alone, where they are always
#: appended, so the stability property was green over 20,000 examples against
#: a live defect. `_WORD` draws from every Unicode letter, so reaching one by
#: chance is not a bound anybody should rely on.
#:
#: The role word rides beside the cell because the arms assert where it ends
#: up, and a cell alone cannot say which word was the surname.
_ROLE_SURNAME_CELLS = st.one_of(
    st.builds(
        lambda role, forenames, initial, dates, stop: (
            f"{role}, {forenames} {initial}.{dates}{stop}",
            role,
        ),
        _ROLES,
        _WORD,
        st.sampled_from(string.ascii_uppercase),
        _DATE_NOISE,
        st.sampled_from(["", "."]),
    ),
    st.builds(
        lambda role, forenames, initial, dates, stop: (
            f"{forenames} {initial}. {role}{dates}{stop}",
            role,
        ),
        _ROLES,
        _WORD,
        st.sampled_from(string.ascii_uppercase),
        _DATE_NOISE,
        st.sampled_from(["", "."]),
    ),
)

#: The same cells without the role word beside them, for the generator that
#: takes cells.
_ROLE_SURNAMES = _ROLE_SURNAME_CELLS.map(lambda built: built[0])

#: A person or corporate cell as a catalogue writes it: in catalogue order or
#: not, with or without the noise, with or without the ISBD full stop, and with
#: the trailing initial that is the one full stop belonging to the name.
_CATALOGUE_NAMES = st.one_of(
    st.builds(
        lambda surname, forenames, noise, stop: f"{surname}, {forenames}{noise}{stop}",
        _WORD,
        _WORD,
        _NOISE,
        st.sampled_from(["", "."]),
    ),
    st.builds(
        lambda name, noise, stop: f"{name}{noise}{stop}",
        _WORD,
        _NOISE,
        st.sampled_from(["", "."]),
    ),
    st.builds(
        lambda surname, forenames, initial: f"{surname}, {forenames} {initial}.",
        _WORD,
        _WORD,
        # **ASCII, because the rule it is about is.** `_TRAILING_INITIAL` is
        # `[A-Za-z]`, so `Pohl, Robert O.` keeps its full stop and the same
        # name with a Scandinavian or Greek initial loses it. Generating
        # outside ASCII here would be generating the other branch under this
        # branch's name, and the witness below is what caught that.
        st.sampled_from(string.ascii_uppercase),
    ),
    _ROLE_SURNAMES,
)


@pytest.mark.property
class TestAFlippedNameIsStillAName:
    @given(raw=_TEXT)
    def test_runs_of_whitespace_are_gone_on_both_branches(self, raw):
        """**Not tidying: a bound.** Two of the noise pattern's three arms are a
        `\\s*` in front of a rare literal, which is quadratic over a run of
        spaces, and one upload of 10,464 rows whose author cell was 498 spaces
        measured 17.96 s of CPU for that column alone before the collapse went
        in. The collapse is only a bound while it happens on every branch, which
        is what this asks and a case about a name cannot."""
        flipped = flip_catalogue_name(raw)
        assert " ".join(flipped.split()) == flipped

    @given(raw=_TEXT)
    def test_nothing_is_ever_added_to_a_cell(self, raw):
        """Every branch removes or reorders. A cell that came back longer than
        it arrived would be this app writing into a catalogue's assertion."""
        assert len(flip_catalogue_name(raw)) <= len(" ".join(raw.split()))

    @given(name=_CATALOGUE_NAMES)
    def test_flipping_a_flipped_name_changes_nothing(self, name):
        """**Scoped to a name, and the scope is the findings below rather than
        a convenience.** The CSV import runs this once per cell, and a library
        exported and imported again meets it a second time on the already
        flipped form, so a name has to be stable under it.

        Two shapes are outside the scope and each is pinned by a named case
        under this class rather than left to be rediscovered: a cell whose
        surname is punctuation, and a cell whose full stop belongs to the name
        but is not one this module's initial pattern matches.
        """
        once = flip_catalogue_name(name)
        assert flip_catalogue_name(once) == once

    @given(built=_ROLE_SURNAME_CELLS)
    def test_a_role_word_standing_as_the_surname_ends_up_the_surname(self, built):
        """The half the stability property above cannot see.

        A direct order cell loses its surname on the **first** pass, so it
        comes back already settled and flipping it again changes nothing. Only
        an arm that asks what is left can tell that the name is gone.

        **It asserts where the role word lands, not that one appears.** An
        earlier version asked only whether some role word was still in the
        output, which `1948-2020 Marie A. Auteur` satisfies: the surname was
        there, in the wrong place, behind the life dates the refusal had
        swallowed. Position is the cheapest assertion that can tell those
        apart.
        """
        cell, role = built
        assert flip_catalogue_name(cell).rstrip(".").split()[-1] == role

    @given(built=_ROLE_SURNAME_CELLS)
    def test_the_life_dates_still_come_off_a_cell_whose_surname_is_a_role_word(
        self, built
    ):
        """The arms compete over this cell and only one of them may win.

        The role arm reaches the end of the cell, so a refusal that consumed
        its match took the life dates out of reach of the arms that own them.
        Two docstrings in the module promise dates come off whichever branch
        runs, and this is what holds them to it.

        **No mutation of the pattern reddens this arm, and that is not a sign
        it is dead.** It is green under every mutant of `_PERSON_NOISE` and
        reddens only when the refusal is rebuilt as a callback on the
        substitution, which a sweep cannot write because it edits expressions
        rather than replacing a mechanism. Measured by hand against a rebuild
        of that callback: 60 of 180 direct order cells carrying dates after a
        role word kept them, against 0 here.
        """
        cell, _ = built
        assert not any(character.isdigit() for character in flip_catalogue_name(cell))

    def test_the_generator_covers_every_role_word_the_module_strips(self):
        """**The derived population, asserted, which is what deriving costs.**

        `_ROLES` reads the module, so a role added there widens `_NOISE` and
        `_ROLE_SURNAMES` by itself. The same reading makes a role **removed**
        there shrink them in silence, and this is the one site that reddens by
        name and prints the member that moved.
        """
        assert sorted(bibliographic._PERSON_ROLES) == [
            "Auteur",
            "Autrice",
            "Compilateur",
            "Editeur",
            "Illustrateur",
            "Illustratrice",
            "Préfacier",
            "Traducteur",
            "Traductrice",
            "Éditeur",
        ]

    def test_the_generator_still_reaches_a_surname_that_is_a_role_word(self):
        """Keyed on position rather than on the presence of a role word: the
        appended noise arm carries one too, and it is neither the head of the
        cell nor its last word."""
        witness(
            _CATALOGUE_NAMES,
            lambda name: name.split(",")[0] in bibliographic._PERSON_ROLES
            or name.split()[-1] in bibliographic._PERSON_ROLES,
            reaches="a cell whose surname is a role word",
        )

    def test_the_generator_still_reaches_a_cell_that_is_reordered(self):
        witness(
            _CATALOGUE_NAMES,
            lambda name: "," in name and flip_catalogue_name(name) != name,
            reaches="a cell in catalogue order",
        )

    def test_the_generator_still_reaches_a_cell_carrying_life_dates(self):
        witness(
            _CATALOGUE_NAMES,
            lambda name: any(character.isdigit() for character in name)
            and not any(
                character.isdigit() for character in flip_catalogue_name(name)
            ),
            reaches="a cell whose life dates come off",
        )

    def test_the_generator_still_reaches_the_full_stop_that_is_part_of_a_name(self):
        """`Melville, Herman.` loses its stop and `Pohl, Robert O.` keeps one,
        and the two are the same shape to anything but `_TRAILING_INITIAL`. A
        generator that reached only the first would leave the harder half of
        `_drop_isbd_stop` untouched."""
        witness(
            _CATALOGUE_NAMES,
            lambda name: "," in name
            and name.endswith(".")
            and "." in flip_catalogue_name(name),
            reaches="a flipped name that keeps an initial's full stop",
        )


class TestACellWhoseSurnameIsPunctuationIsNotAName:
    """Where flipping stops being stable, found by the property above and pinned.

    `;,0` has exactly one comma, so it takes the flipping branch and comes back
    as `0 ;`. On a second pass the leading semicolon is trailing, which is where
    `_strip_person_noise` rstrips it, and the cell changes again.

    **Recorded rather than fixed, and the bound is why.** Nothing reaches this
    but a cell whose surname is punctuation, and no catalogue and no importer
    produces one: a real cell ending in a semicolon is trimmed on the first pass
    before the comma is counted. What it costs is that this function is a reader
    of catalogue person strings and not a general normaliser, which is the claim
    the property above is scoped by.
    """

    def test_it_flips_and_then_settles_somewhere_else(self):
        assert flip_catalogue_name(";,0") == "0 ;"
        assert flip_catalogue_name("0 ;") == "0"


class TestARoleWordCanBeTheSurname:
    """`Autrice, A A.` flipped to `A A. Autrice` and then to `A A`.

    `_PERSON_NOISE`'s role arm needs a full stop in front of the role word,
    and the flip manufactures one out of the trailing initial that
    `_drop_isbd_stop` is careful to keep. A second pass then read the surname
    as the designation the BnF appends and deleted it, with a 200 and no
    error.

    **The stop is the key, and it is not the only one the cell carries.** A
    designation is usually a role word with a space separated qualifier
    behind it while a surname runs on without one, and a rule reading both
    keys does better than this one on `Kane, Sean P. Auteur du texte`. It is
    recorded because the choice was not binary, not because it is the better
    one.

    **What it costs is measured, and no spelling of it was found that pays
    nothing.** The conjunction beats this version on the designation cell and
    fails on other shapes, and **which shapes depends on how the qualifier is
    spelled**, so no mechanism is named here: three spellings were measured
    and they do not agree on what breaks. The one fixed point across all of
    them is that the answer that keeps the initial's stop needs the stop
    written back, which only a form that consumes its match can do, and that
    form is the one this version replaced.
    """

    def test_a_surname_that_is_a_role_word_survives_the_round_trip(self):
        """**The second call is the arm and the first is the setup.** Flipping
        a catalogue order cell once was never the damage: that flip is what
        manufactures the stop, so an arm asserting only its result is green on
        the defect and green on the fix."""
        assert flip_catalogue_name("Autrice, A A.") == "A A. Autrice"
        assert flip_catalogue_name("A A. Autrice") == "A A. Autrice"

    def test_a_leading_initial_is_the_same_stop_and_costs_the_first_pass(self):
        """`_TRAILING_INITIAL` begins with `^` for this: a cell already in
        direct order lost its surname without being flipped at all, so no
        property about flipping twice could reach it."""
        assert flip_catalogue_name("A. Autrice") == "A. Autrice"

    def test_a_surname_that_merely_begins_with_a_role_word_survives_too(self):
        """`[^.]*` lets the arm run from the role word to the end of the cell,
        so the class is every surname starting with one rather than the
        surnames that are one."""
        assert flip_catalogue_name("Autrice-Martin, A A.") == "A A. Autrice-Martin"
        assert flip_catalogue_name("A A. Autrice-Martin") == "A A. Autrice-Martin"

    def test_the_designations_this_repository_has_seen_still_come_off(self):
        """The refusal is on the stop and not on the role word. Every whole
        person cell in this tree carrying a designation hangs it off a closing
        bracket or off a letter, so none of them is an initial's stop and none
        of them changed."""
        assert (
            flip_catalogue_name("Zafón, Carlos (1964-2020). Auteur du texte")
            == "Carlos Zafón"
        )
        assert (
            flip_catalogue_name("Camus, Albert (1913-1960). Auteur du texte")
            == "Albert Camus"
        )
        assert (
            flip_catalogue_name("Bibliothèque nationale de France. Éditeur")
            == "Bibliothèque nationale de France"
        )

    def test_a_designation_behind_an_initial_is_what_this_now_keeps(self):
        """**The false refusal the fix buys, and it is not a free trade.**

        The stop after `P.` belongs to the name, so the arm no longer reads it
        as a separator and a genuine designation survives into the cell.

        **Measured through `authors.author_key`, which is where it costs
        something.** That key turns punctuation into a space, so the old
        answer, `Sean P Kane`, keys the same as `Sean P. Kane` and folds onto
        the right person: what the old answer lost was a displayed full stop
        and nothing else. This answer keys differently from every other
        spelling of the name, so it mints an author that no import will ever
        fold onto and only an alias row undoes.

        So the trade is a display loss against an identity loss, and it goes
        against this branch on **this** family. It is taken because the
        defect family costs a deleted surname, which is worse than either, and
        because no cell of this shape is in this tree while three of the other
        shape are.
        """
        assert (
            flip_catalogue_name("Kane, Sean P. Auteur du texte")
            == "Sean P. Auteur du texte Kane"
        )

    @pytest.mark.parametrize(
        "cell, settles_at",
        [
            # An abbreviation, which is the shape a flip can hand back: see
            # the arm below.
            ("Dr. Autrice", "Dr"),
            # A letter outside `[A-Za-z]`, in a module whose role words are
            # French and whose catalogue is not English.
            ("É. Autrice", "É"),
            # A compound forename abbreviated with a hyphen.
            ("J.-P. Autrice", "J.-P"),
            # A space between the initial and its own full stop.
            ("A A . Autrice", "A A"),
        ],
    )
    def test_a_prefix_the_initial_pattern_does_not_match_still_costs_the_surname(
        self, cell, settles_at
    ):
        """**What is left over, stated as one family rather than as a list.**

        Every one of these is a full stop that belongs to the name in front of
        a role word, and `_TRAILING_INITIAL` does not match the text before
        it. The rows are witnesses to the family and are not a bound on it.

        **Widening the letter class is not the fix.** `_drop_isbd_stop` reads
        the same pattern, so a wider class changes which cells keep their
        terminal stop, and widening the shape from one letter to a letter run
        was measured to stop
        `Bibliothèque nationale de France. Éditeur` losing its designation at
        all, which the arm above pins.
        """
        assert flip_catalogue_name(cell) == settles_at

    def test_the_two_readers_of_an_initials_stop_agree_on_every_codepoint(self):
        """**One shape, two compilations, and only one of them carries a flag.**

        `_TRAILING_INITIAL` compiles bare; the refusal compiles into
        `_PERSON_NOISE`, which carries `re.IGNORECASE`, and that flag widens a
        bare `[A-Za-z]` by the codepoints whose case folding lands inside it.
        Without the scoped `(?-i:...)` the two disagreed on these four, and a
        cell built from one of them got two answers: it lost its terminal stop
        because one reader saw no initial there, and kept its surname because
        the other one did.

        **The set is derived from the flag rather than listed**, so a Unicode
        release that adds a fifth reddens by name instead of slipping past
        four literals.

        The class is typed here rather than parsed back out of the module, so
        that this arm does not agree with the thing under test by
        construction. The first assertion is what stops that costing
        something: without it the module's class could move and this would go
        on deriving over the old one, narrowing in silence.
        """
        # The expected value is on the left because ruff reads the ALL_CAPS
        # side as the constant and calls the other order a Yoda condition.
        assert f"(?-i:{_AN_INITIAL_CLASS})" == bibliographic._AN_INITIAL

        strict = re.compile(_AN_INITIAL_CLASS)
        widened_by_the_flag = [
            codepoint
            for codepoint in range(0x110000)
            if re.fullmatch(_AN_INITIAL_CLASS, chr(codepoint), re.IGNORECASE)
            and not strict.fullmatch(chr(codepoint))
        ]
        assert [hex(codepoint) for codepoint in widened_by_the_flag] == [
            "0x130",
            "0x131",
            "0x17f",
            "0x212a",
        ]

        refusal = re.compile(
            bibliographic._NOT_AN_INITIALS_STOP + r"\.$", re.IGNORECASE
        )
        for codepoint in widened_by_the_flag:
            for before in ("", " ", ".", "x"):
                cell = f"{before}{chr(codepoint)}."
                owned = bool(bibliographic._TRAILING_INITIAL.search(cell))
                refused = refusal.search(cell) is None
                assert owned == refused, cell

    def test_a_doubled_full_stop_hands_the_next_pass_an_abbreviation(self):
        """**The route into that family that a flip opens**, which is why the
        family is not only a hand typed cell.

        A doubled stop is an abbreviation ending a subfield that also carries
        ISBD terminal punctuation. `_drop_isbd_stop` takes one of the two, the
        abbreviation keeps its own, and the flip puts it in front of the
        surname.

        **`_CATALOGUE_NAMES` builds a doubled stop and not this cell**, which
        is a narrower exclusion than it looks: measured at 494 doubled stops
        in 30,000 draws, and a targeted search finds one at once. What it
        cannot build is the **multi letter prefix** in front of one, and that
        is the half no key available in this module closes, so the stability
        property over that generator stays green while this arm is what keeps
        the route visible.
        """
        assert flip_catalogue_name("Autrice, Dr..") == "Dr. Autrice"
        assert flip_catalogue_name("Dr. Autrice") == "Dr"
