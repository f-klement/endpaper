"""How a classification scheme's call numbers sort.

A scheme says what a number means. A **filing rule** says where the number
stands on a shelf. Those are two facts, and this module holds the second one
per scheme, because the app used to hold a single answer and apply it to every
scheme it drew: the call number column offered one order, `min(number) where
scheme = ddc`, over a column that also draws Library of Congress numbers. A
library shelving by LCC got a Dewey order, silently and with no error.

Read from Koha, whose `Classification sources` seed six schemes each naming a
sorting routine, `dewey`, `lcc` or `generic`. The design is taken; Koha is GPL
and none of its code is.

**Three rules, four schemes.** Dewey and Library of Congress each get their
own. The two subject vocabularies get the generic one, which sorts a value as
the text it is and declares that no shelf may be ordered by it.

**A rule answers once, in Python, and the answer is stored.** `sort_key` is
the whole of a rule's arithmetic; `models.Classification.sort_key` holds what
it returned and `shelf.py` orders on that column. The rule used to be written
twice, in Python and in SQL, and the SQL half was the expensive part of every
shelf listing: a twelve arm `CASE` rebuilt per classification row. At the worst
case a member can construct, `MAX_CLASSIFICATIONS_PER_BOOK` rows across 20,000
books, that was **2.3 s per request on one box and 3.2 s on another**, which is
what `docs/decisions.md` records. Each box is a corpus of its own and the two
are not the ends of one range.

**The ticket that ordered this records 2.7 s for the first box**, and the
disagreement is left standing rather than averaged: two records of one
measurement that differ are a thing to resolve at the instrument, not in a
docstring. Storing the key deleted the SQL half, so there is no longer a second
implementation to drift.

**Changing a rule changes stored data.** Every key in
`classifications.sort_key` was computed by the rule as it stood when the row
was written, and nothing recomputes it on read: not paying that is the point
of the column. So an edit to any `sort_key` here needs an Alembic revision that
recomputes the column, and a rule edited without one leaves a library filed by
the old rule with no error anywhere.

**Nothing here queries, and nothing here names a table.** `models.py` calls
`sort_key_for` on the way in and `shelf.py` reads the column. That keeps the
privacy rule where it belongs and keeps this module invisible to the four
guards in `tests/test_shelf.py`.
"""

import re
from abc import ABC, abstractmethod
from typing import ClassVar, Final

import ddc
from enums import ClassificationScheme


class FilingRule(ABC):
    """One scheme's answer to "where does this number stand on a shelf"."""

    #: The routine's name, spelled as Koha spells it. For a test and a report.
    name: ClassVar[str]

    #: Whether this app may offer a shelf order under this rule. See
    #: `GenericFiling` for why one rule answers no.
    orders_a_shelf: ClassVar[bool]

    @abstractmethod
    def recognises(self, number: str) -> bool:
        """Whether this is a number in the scheme this rule files.

        `ddc.notation` already answers this for Dewey and refuses what is not
        one. Every rule can now say the same about its own.
        """

    @abstractmethod
    def sort_key(self, number: str) -> str:
        """The string that files this number, ordered as plain text.

        A key rather than a comparison, because the order is produced by a
        database sorting a column and a database cannot be handed a comparison.
        """


class GenericFiling(FilingRule):
    """No schedule, so the value files as the text it is.

    **It recognises everything, which is not laziness.** A rule with no
    schedule has nothing to check a number against, and answering False would
    be a claim it cannot make. Koha's `generic` routine is the same admission.

    **And it orders no shelf.** Sorting an unknown scheme's values as text is
    the honest thing to do with the values; offering that as a *shelf order*
    would be exactly the defect this module exists to fix, which is promising an
    order nobody has verified. So the generic rule is a fallback for a key and
    never an entry in `SHELF_SCHEMES`.
    """

    name: ClassVar[str] = "generic"
    orders_a_shelf: ClassVar[bool] = False

    def recognises(self, number: str) -> bool:
        return True

    def sort_key(self, number: str) -> str:
        return number


class DeweyFiling(FilingRule):
    """A Dewey number files as its own text, once the segmentation prime is gone.

    **Text order is shelf order here, and that is a property of the notation
    rather than a convenience.** `ddc._NOTATION` admits exactly three leading
    digits and an optional decimal fraction, so every recognised number is the
    same width up to the point, and a fraction compares digit by digit the way
    it compares numerically: `004`, then `155.9042`, then `830`.
    `tests/test_filing.py` derives that against `float` rather than restating
    it.

    **One transformation, and it is not cosmetic.**
    `ClassificationIn.dewey_numbers_are_notations` validates *through*
    `ddc.notation` and does not write its answer back, so `005.13/3` is
    accepted and stored with the prime in it. Text order then files it before
    `005.133`, which is the same heading, and after `005.13`, which is a
    different one. Removing the prime is what `ddc.notation` would have
    returned.

    **No `strip`, deliberately.** `ClassificationIn.tidy_number` collapses the
    whitespace at every door into this table, so a stored number has none at
    its edges and a strip here would guard a case that cannot arrive. Adding
    one would not be free either: it would file a number differently from the
    text it was stored as, which is a rule this scheme does not have.
    """

    name: ClassVar[str] = "dewey"
    orders_a_shelf: ClassVar[bool] = True

    def recognises(self, number: str) -> bool:
        return ddc.notation(number) is not None

    def sort_key(self, number: str) -> str:
        return number.replace(ddc.SEGMENTATION_PRIME, "")


#: How wide each part of a Library of Congress key is padded to, and how far
#: each part is read.
#:
#: The class letters are one to three (`Q`, `QA`, `KJC`). The class number is
#: an integer of one to four digits, since the schedules run to 9999. Its
#: decimal extension is capped at six, which is past anything the Library of
#: Congress publishes and is a cap rather than a claim.
#:
#: **The three are read by `_LCC` and by `MAX_KEY_GROWTH`, and one revision
#: copies them.** Widening any of them lengthens every key already stored, so
#: it is a data change as much as a code one: see the module docstring.
_LETTERS_WIDTH: Final = 3
_INTEGER_WIDTH: Final = 4
_DECIMAL_WIDTH: Final = 6

#: A call number, as far as its class number goes: letters, an integer, an
#: optional decimal extension, and then everything else.
#:
#: **ASCII classes rather than `\\w` and `\\d`.** The schedules are ASCII, and
#: the shorthands are not: Python's `\\d` matches `٣` and `str.isalpha` matches
#: `ü`, so `\\d` would read `٣٤` as a class number and pad it into a shelf
#: position the Library of Congress has never published. Such a value files
#: under the generic rule instead, as its own text.
#: `tests/test_filing.py::TestTheKeyIsAsciiOnly` pins that.
#:
#: **`DOTALL`, and matched in full, and it is load bearing rather than tidy.**
#: Without it `.` refuses a newline, so `QA76\\nS75` falls to the generic key
#: and files as raw text while every other number in class QA76 files padded,
#: which separates one row from its own class. Bare `.` already matches a tab
#: and a carriage return, so the newline is the only character that pins this
#: flag: `tests/test_filing.py::TestTheKeyReadsPastANewline` is the test that
#: goes red without it. `fullmatch` is what makes the `$` question moot.
#:
#: `ClassificationIn.tidy_number` collapses whitespace at the door, so no
#: request can put a newline in the column. This does not rely on that, for the
#: reason `shelf._looks_like_a_notation` exists: a row written before a
#: validator holds whatever it was given, and `backup.restore` writes this
#: table through `backup._TABLES` rather than through the schema, so an old
#: archive restores whatever it holds.
_LCC: Final = re.compile(
    rf"([A-Za-z]{{1,{_LETTERS_WIDTH}}})"
    rf"([0-9]{{1,{_INTEGER_WIDTH}}})"
    rf"(?:\.([0-9]{{1,{_DECIMAL_WIDTH}}}))?"
    r"(.*)",
    re.DOTALL,
)

#: What pads the class letters out to `_LETTERS_WIDTH`.
#:
#: A space, because it has to sort **before** every letter: `Q` stands ahead of
#: `QA` on a shelf, and `Q` padded with anything from `A` upwards would stand
#: behind it.
_LETTER_PAD: Final = " "


class LccFiling(FilingRule):
    """A Library of Congress call number files by four parts, padded.

    **Text order is not shelf order here, which is the whole reason this module
    exists.** The class letters sort as text and the class number does not:
    `BF75` stands before `BF575` on a shelf and after it in a string
    comparison. Measured against the live row `BF575.S75 E64 2022`, 2026-08-29.

    The key pads each part to a fixed width so that plain text comparison
    reproduces the shelf:

    | part | width | pad | why |
    |---|---|---|---|
    | class letters | 3 | trailing space | `Q` before `QA` |
    | class integer | 4 | leading zero | `BF75` before `BF575` |
    | class decimal | 6 | trailing zero | `BF575` before `BF575.5` |
    | the rest | none | | see below |

    **The rest is left verbatim, and that is a measurement rather than a
    shortcut.** What follows the class number is cutters and a date, and a
    cutter number is read as a decimal fraction: `.S75` is 0.75 and `.S8` is
    0.8, so `.S75` files first. Lexicographic order over digit strings *is*
    decimal fraction order, so the cutters need no padding at all. What they do
    need is their separator kept: with the dots and spaces removed, `S7 A1` and
    `S75` both collapse to `S7...` and the shorter cutter files second, which is
    wrong.

    **The decimal extension is the one part that cannot be left to the rest.**
    `BF575.S75` is class 575 with a cutter and `BF575.5.S75` is class 575.5, so
    they file in that order; comparing the raw remainders `.S75` and `.5.S75`
    puts the digit first and reverses them.

    **Two spellings of one shelf position file apart, and that is the cost of
    leaving the rest verbatim.** The live sources supply both
    `HQ1090.3 .M67 1999` and `QA76.73.J38 F57 2020`, so the cutter separator
    arrives with and without a leading space, and a space sorts before a point.
    Collapsing them would cost the cutter boundary above, which is worse, and
    the two spellings still land in the same class.

    **A value this cannot read files under the generic rule.** `metadata.py`
    applies no scheme specific normaliser to an LCC number, deliberately, so
    beyond the whitespace collapse every door shares the column holds what a
    catalogue wrote. A key that refused would have to raise or return nothing,
    and a shelf order that omits a row is worse than one that files it by its
    text.
    """

    name: ClassVar[str] = "lcc"
    orders_a_shelf: ClassVar[bool] = True

    def recognises(self, number: str) -> bool:
        return _LCC.fullmatch(number) is not None

    def sort_key(self, number: str) -> str:
        match = _LCC.fullmatch(number)
        if match is None:
            return GENERIC.sort_key(number)
        letters, integer, decimal, rest = match.groups()
        return (
            letters.upper().ljust(_LETTERS_WIDTH, _LETTER_PAD)
            + integer.rjust(_INTEGER_WIDTH, "0")
            + (decimal or "").ljust(_DECIMAL_WIDTH, "0")
            + rest
        )


#: The most characters a key can carry that the number it files did not.
#:
#: **A stored key needs a column, and a column needs a width.** The generic and
#: Dewey rules never lengthen a value: one returns it and the other removes a
#: character. `LccFiling.sort_key` is the one that can, and by a bounded
#: amount: it emits `_LETTERS_WIDTH + _INTEGER_WIDTH + _DECIMAL_WIDTH`
#: characters in place of the prefix `_LCC` consumed, and the shortest prefix
#: that regex matches is one letter and one digit. So the growth is those three
#: widths less two, and it is reached by `Q1`.
#:
#: Derived rather than written as 11, because the three widths are the fact and
#: a literal beside them is a second one.
#: `tests/test_filing.py::TestTheKeyGrowsByABoundedAmount` derives the same
#: number by measuring every shape instead, which is the second instrument.
MAX_KEY_GROWTH: Final = _LETTERS_WIDTH + _INTEGER_WIDTH + _DECIMAL_WIDTH - 2

GENERIC: Final = GenericFiling()
DEWEY: Final = DeweyFiling()
LIBRARY_OF_CONGRESS: Final = LccFiling()

#: Which rule files each published scheme.
#:
#: **A scheme missing from here files under the generic rule rather than
#: raising**, which is the arrangement `classifications.SCHEME_ORDER` already
#: uses for the same reason: adding a member to `ClassificationScheme` must not
#: be able to break a listing by forgetting a table. What it *cannot* do is
#: acquire a shelf order by accident, because the generic rule orders none.
FILING_RULES: Final[dict[ClassificationScheme, FilingRule]] = {
    ClassificationScheme.DDC: DEWEY,
    ClassificationScheme.LCC: LIBRARY_OF_CONGRESS,
    ClassificationScheme.GND: GENERIC,
    ClassificationScheme.LCSH: GENERIC,
}


def rule_for(scheme: ClassificationScheme) -> FilingRule:
    """The filing rule for one scheme. See `FILING_RULES` for the fallback."""
    return FILING_RULES.get(scheme, GENERIC)


def sort_key_for(scheme: object, number: str) -> str:
    """The stored key for one row, from whatever that row's two columns hold.

    **The one entry point every writer of `classifications.sort_key` uses**, so
    that the ORM hook, the restore path and a test cannot each decide the
    question differently. `models.Classification._file_the_number` is the hook
    and `backup._parse_row` is the restore.

    **`scheme` is `object` because the column is a plain `VARCHAR(20)` and one
    write path has no validator.** `backup.restore` inserts through Core, so an
    archive may carry `"scheme": "udc"`, or a number, or nothing this app has
    ever published. A scheme this app cannot name is exactly the case
    `FILING_RULES` already answers with the generic rule: file it as its own
    text and order no shelf by it. Raising instead would turn one unrecognised
    row into a failed restore of a whole library.

    Two ways to be unnameable and both end here: not text at all, and text this
    app does not publish. A `ClassificationScheme` passes the first test because
    it is a `StrEnum`.
    """
    if isinstance(scheme, str):
        try:
            return rule_for(ClassificationScheme(scheme)).sort_key(number)
        except ValueError:
            pass
    return GENERIC.sort_key(number)


#: The schemes a shelf may be ordered by, derived from the rules themselves.
#:
#: Derived rather than written out, so "which schemes file a shelf" is stated
#: once, on the rule that answers it. `shelf._SHELF_SORTS` pairs each of these
#: with the `BookSort` value that asks for it, and `tests/test_shelf.py` pins
#: that the two cover each other.
SHELF_SCHEMES: Final[tuple[ClassificationScheme, ...]] = tuple(
    scheme for scheme, rule in FILING_RULES.items() if rule.orders_a_shelf
)
