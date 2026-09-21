"""The one line a member typed, and the one place the API layer spells it.

Three normalisations live in `schemas/common.py` and the difference between
them is a decision about what the API accepts, not a tidying:

| function | a run of spaces | a NUL | a tab |
|---|---|---|---|
| `one_line` | one space | survives | one space |
| `one_line_without_invisible_characters` | one space | gone | one space |
| `one_line_without_any_control_character` | one space | gone | gone |

Which field takes which is argued at each field. What is here is the three
functions' own behaviour, the partition that keeps the middle rule from
becoming the bottom one, and the guard that keeps the API layer calling them
rather than writing the collapse out again. Before this, one line a member
typed was spelled nine times across seven modules, under two private functions
that shared a name and did different things.
"""

import ast
import inspect
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from schemas.common import (
    _CONTROL_CHARACTERS,
    _INVISIBLE_CHARACTERS,
    one_line,
    one_line_without_any_control_character,
    one_line_without_invisible_characters,
)
from tests.test_house_rules import BACKEND, _python_sources

#: The module the API layer is required to ask, found through the function
#: rather than by path, so moving the home moves the exemption with it.
_HOME = Path(inspect.getsourcefile(one_line) or "").resolve()


def _declares_an_api(source: str) -> bool:
    """Whether this module is one a member's own value arrives in.

    **The layer by what a module is, not by which directory it sits in.** A
    module that imports `pydantic` declares a request contract and one that
    imports `fastapi` declares a route or reads a query parameter; between them
    that is every door a typed value comes through. A list of directories would
    have been shorter and would forgive `backend/api/` on the day somebody adds
    it, which is the shape of guard this tree keeps paying for.

    **No count in this sentence, deliberately.** A figure here is one the next
    module added leaves wrong, and the arm below carries the measurement
    instead: it names a module a directory walk would have reached, one it
    would have missed, and one that must stay outside. The modules outside the
    population that collapse whitespace do so to match text or to derive a key
    rather than to store what somebody typed, which is a different rule with
    its own home.
    """
    tree = ast.parse(source)
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    return bool({"pydantic", "fastapi"} & imported)


def _api_layer() -> list[Path]:
    """Every module in that layer, through the walk this tree shares.

    `_python_sources` rather than an `rglob` of our own, which is the rule
    `test_house_rules.py` enforces over every test module: nine of them walked
    `backend/` excluding a list of directory names each had heard of, and none
    of the lists held the cache the pipeline creates.
    """
    return sorted(
        path
        for path in _python_sources()
        if path.resolve() != _HOME and _declares_an_api(path.read_text())
    )


def _bare_collapses(source: str) -> list[int]:
    r"""The lines of `source` that split on whitespace themselves.

    **The primitive rather than the phrasing.** `" ".join(value.split())` is
    how every one of the nine sites was written, but a guard matching that
    shape would pass `"".join(x.split())`, `x.split()[0]` and a collapse built
    over two statements. `str.split()` with no argument is the whitespace
    primitive underneath all of them, so the rule is that the API layer does
    not reach for it: measured at zero uses outside the home.

    **What it does not see**, stated rather than guarded: a collapse written
    `re.sub(r"\s+", " ", value)`, a `str.translate` over the space characters,
    or a loop. A `\s` arm was considered and left out, because the API layer
    holds one regex today and it reads a Host header: a rule refusing every
    whitespace class would refuse header parsing, which is a different rule
    wearing this one's clothes.
    """
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "split"
        and not node.args
        and not node.keywords
    )


def _docstrings_carrying_a_control_character(source: str) -> list[int]:
    """The lines of `source` whose docstring holds a control character.

    Holds one rather than names one: a docstring that is not raw interprets its
    own escapes. A newline is not counted, since a docstring is made of them.
    """
    return sorted(
        # A module carries no line number and its docstring opens the file.
        getattr(node, "lineno", 1)
        for node in ast.walk(ast.parse(source))
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        )
        for text in [ast.get_docstring(node, clean=False) or ""]
        if any(
            unicodedata.category(character) == "Cc" and character != "\n"
            for character in text
        )
    )


class TestCollapsingAWhitespaceRun:
    def test_a_run_of_spaces_becomes_one(self):
        assert one_line("Holiday   reads") == "Holiday reads"

    def test_the_ends_are_trimmed(self):
        assert one_line("  Holiday reads  ") == "Holiday reads"

    def test_a_value_of_only_whitespace_becomes_nothing(self):
        """Every caller rests on this: an empty result is what they refuse."""
        assert one_line(" \t\n ") == ""

    def test_a_character_with_no_width_survives_it(self):
        """The difference between this and the other two, pinned from the side
        that keeps them. A NUL is not whitespace, so nothing about splitting
        reaches it, and the four fields that take this one accept it."""
        assert one_line("a\x00b") == "a\x00b"


class TestRemovingWhatHasNoWidth:
    def test_a_nul_is_removed(self):
        assert one_line_without_invisible_characters("a\x00b") == "ab"

    def test_a_tab_is_still_a_word_break(self):
        r"""The half that a strip of every control character takes silently.

        `"Holiday\treads"` is two words wherever a person reads it back, and
        the fields that take this rule are names, labels and identifiers. Only
        a value that may be followed as a link wants the weld.
        """
        assert one_line_without_invisible_characters("Holiday\treads") == (
            "Holiday reads"
        )
        assert one_line_without_invisible_characters("Ursula K.\nLe Guin") == (
            "Ursula K. Le Guin"
        )

    def test_the_two_sets_partition_the_control_characters(self):
        """What keeps the middle rule from drifting into the bottom one.

        Every control character is either removed here or is whitespace the
        collapse turns into a space. Derived from `str.isspace`, which is the
        predicate `str.split` itself breaks on, so the two halves cannot
        overlap or leave a gap.
        """
        removed = set(_INVISIBLE_CHARACTERS)
        collapsed = {point for point in _CONTROL_CHARACTERS if chr(point).isspace()}

        assert removed | collapsed == set(_CONTROL_CHARACTERS)
        assert removed & collapsed == set()
        assert len(collapsed) == 10

    def test_the_wider_set_is_every_control_character_unicode_has(self):
        """The constant is written as three ranges and this is what says they
        are the category they claim to be.

        Swept rather than listed, and to `sys.maxunicode` rather than to a
        literal: a sweep written `range(0x11000)` covers a sixteenth of Unicode
        and reads exactly like one that does not.
        """
        assert set(_CONTROL_CHARACTERS) == {
            point
            for point in range(sys.maxunicode + 1)
            if unicodedata.category(chr(point)) == "Cc"
        }

    def test_a_zero_width_joiner_is_kept(self):
        """`Cf` is outside both sets, which is the line between removing a
        character and refusing the value. The joiners matter in Arabic and
        Indic scripts, so a name carrying one means something; a call number
        carrying one does not, and that is what bought the wider rule at the
        two validators that refuse rather than here."""
        joined = "क‍ष"

        assert one_line_without_invisible_characters(joined) == joined


class TestTheUrlRuleDeletesEvenATab:
    """Removing every control character before collapsing, rather than after.

    `CustomFieldValueUpdate.tidy` is the one field that takes this: the API
    answered 200 with an href no browser can follow.
    """

    URL = "https://a.example\t/x"

    def test_a_tab_inside_a_url_leaves_no_space_behind(self):
        assert one_line_without_any_control_character(self.URL) == (
            "https://a.example/x"
        )

    def test_the_other_order_is_the_bug_this_replaced(self):
        """The arm that goes red on a rewrite to `one_line(value).translate(...)`,
        which is the edit anybody simplifying this would make. Both orders
        remove the tab; only one of them removes what it left behind."""
        collapsed_first = one_line(self.URL).translate(_CONTROL_CHARACTERS)

        assert collapsed_first == "https://a.example /x"
        assert urlsplit(collapsed_first).hostname == "a.example "
        assert urlsplit(one_line_without_any_control_character(self.URL)).hostname == (
            "a.example"
        )

    def test_the_name_rule_is_not_this_one(self):
        """The two differ on exactly the character that made this field's case,
        so a caller that reached for the wrong one is visible here."""
        assert one_line_without_invisible_characters(self.URL) == (
            "https://a.example /x"
        )


class TestTheApiLayerAsksRatherThanSpelling:
    """One home for the collapse, enforced over a derived population.

    It answers what the old arrangement refused that this accepts: nothing.
    There was no rule, nine sites spelled the collapse out, three of them cited
    a sibling's docstring for it, and two private functions named `_one_line`
    had different bodies.
    """

    def test_no_module_splits_on_whitespace_itself(self):
        found = [
            f"{path.relative_to(BACKEND)}:{line}"
            for path in _api_layer()
            for line in _bare_collapses(path.read_text())
        ]
        assert found == [], (
            f"{found} collapse whitespace where the value arrives rather than "
            "asking `schemas.common`. Which of the three is the answer is a "
            "decision about what the field accepts: see the table in this "
            "file's docstring. A split that is not a collapse, tokenising a "
            "query say, belongs in a module that is neither a request contract "
            "nor a route, and if one belongs here then this rule wants "
            "rewriting rather than an exemption."
        )

    def test_the_walk_reaches_the_modules_it_is_meant_to(self):
        """A population that found nothing would forgive everything, which is
        the failure mode of asserting an empty list.

        `metadata.py` is named on the other side: it holds seven bare splits
        for matching a catalogue's text, so a population reaching it would be
        red for a rule it has never been under.
        """
        found = {str(path.relative_to(BACKEND)) for path in _api_layer()}

        assert "schemas/tag.py" in found
        assert "routers/books.py" in found
        assert "dependencies.py" in found
        # A module a walk of `schemas/`, `routers/` and `dependencies.py` would
        # not have reached, which is what the import predicate buys.
        assert "auth.py" in found
        assert "metadata.py" not in found
        assert str(_HOME.relative_to(BACKEND)) not in found
        assert len(found) > 30, f"only {len(found)} modules walked"

    def test_the_matcher_can_tell_a_collapse_from_a_call(self):
        """Driven against a string, because a rule that only ever runs on this
        checkout is a rule whose arms cannot be driven."""
        assert _bare_collapses('x = " ".join(value.split())') == [1]
        assert _bare_collapses("x = value.split()[0]") == [1]
        assert _bare_collapses("x = one_line(value)") == []
        assert _bare_collapses('x = value.split(",")') == []

    def test_no_docstring_in_the_layer_carries_a_control_character(self):
        """The class this change found in its own first draft, twice.

        A docstring about an invisible character has to quote one, and a
        docstring that is not raw interprets the escape, so the module ships
        the character its own sentence is about: a NUL in `one_line.__doc__`,
        and a newline that broke the example claiming a newline is a word
        break. Making the string raw is the fix and this sweep is what makes it
        stick, in a layer where a docstring is also the description the client
        is handed.
        """
        carried = [
            f"{path.relative_to(BACKEND)}:{line}"
            for path in [*_api_layer(), _HOME]
            for line in _docstrings_carrying_a_control_character(path.read_text())
        ]
        assert carried == [], (
            f"{carried} hold a control character in a docstring rather than an "
            "escape naming one. Make the docstring raw."
        )

    def test_the_docstring_matcher_can_be_driven(self):
        """Its sibling's reason: a rule that only ever runs on this checkout is
        a rule whose arms cannot be driven."""
        assert _docstrings_carrying_a_control_character('def f():\n    """a\\x00b"""') == [1]
        assert _docstrings_carrying_a_control_character('def f():\n    r"""a\\x00b"""') == []
        assert _docstrings_carrying_a_control_character('def f():\n    """a\\tb"""') == [1]
        assert _docstrings_carrying_a_control_character('x = "a\\x00b"') == []

    def test_the_layer_is_read_off_the_module_rather_than_its_directory(self):
        """The arm that says a new top level package is covered with no edit."""
        assert _declares_an_api("from pydantic import BaseModel")
        assert _declares_an_api("import fastapi")
        assert _declares_an_api("from fastapi import Query")
        assert not _declares_an_api("import re\n\nx = value.split()")
