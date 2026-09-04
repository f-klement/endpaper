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

**A rule answers in two languages and both live here.** `sort_key` is the
Python answer and `sort_expression` is the SQL one. A listing is paginated in
the database, so the SQL is the answer a reader actually sees, and the Python
is what a test can read. One rule written twice is the shape that drifts, so
the two sit in one object and
`tests/test_shelf.py::TestTheFilingKeysAgree` evaluates both against real
SQLite over a corpus rather than trusting that they match. The widths and the
caps are module constants for the same reason: the regex and the SQL run
lengths have to stop at the same character or the two keys disagree on a long
value only.

**Nothing here queries, and nothing here names a table.** `sort_expression` is
handed a column by `shelf.py`. That keeps the privacy rule where it belongs and
keeps this module invisible to the four guards in `tests/test_shelf.py`.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar, Final

from sqlalchemy import SQLColumnExpression, String, and_, case, func, literal
from sqlalchemy.sql import ColumnElement

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

    @abstractmethod
    def sort_expression(
        self, column: SQLColumnExpression[str]
    ) -> SQLColumnExpression[str]:
        """`sort_key`, over a column, evaluated by the database."""


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

    def sort_expression(
        self, column: SQLColumnExpression[str]
    ) -> SQLColumnExpression[str]:
        return column


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
    its edges and a strip here would guard a case that cannot arrive. It would
    cost something real: `str.strip` is Unicode aware and SQLite's `trim`
    removes spaces only, so the Python key and the SQL key would disagree on a
    tab, which is the one thing this pair must never do.
    """

    name: ClassVar[str] = "dewey"
    orders_a_shelf: ClassVar[bool] = True

    def recognises(self, number: str) -> bool:
        return ddc.notation(number) is not None

    def sort_key(self, number: str) -> str:
        return number.replace(ddc.SEGMENTATION_PRIME, "")

    def sort_expression(
        self, column: SQLColumnExpression[str]
    ) -> SQLColumnExpression[str]:
        return func.replace(
            column, ddc.SEGMENTATION_PRIME, "", type_=String()
        )


#: How wide each part of a Library of Congress key is padded to, and how far
#: each part is read.
#:
#: **One statement of each, read by the regex and by the SQL alike.** The
#: Python side stops reading a run because a repetition count says so and the
#: SQL side stops because a `CASE` runs out of arms, and a value longer than
#: either cap has to break in the same place on both or the two keys differ on
#: exactly the inputs a short corpus does not carry.
#:
#: The class letters are one to three (`Q`, `QA`, `KJC`). The class number is
#: an integer of one to four digits, since the schedules run to 9999. Its
#: decimal extension is capped at six, which is past anything the Library of
#: Congress publishes and is a cap rather than a claim.
_LETTERS_WIDTH: Final = 3
_INTEGER_WIDTH: Final = 4
_DECIMAL_WIDTH: Final = 6

#: A call number, as far as its class number goes: letters, an integer, an
#: optional decimal extension, and then everything else.
#:
#: **ASCII classes rather than `\\w` and `\\d`.** Python's `\\d` matches
#: `٣` and `str.isalpha` matches `ü`, and SQLite's `BETWEEN 'A' AND 'Z'`
#: matches neither, so the shorthands would put a divergence in the one pair
#: that has to agree.
#:
#: **`DOTALL`, and matched in full, and it is load bearing rather than tidy.**
#: Without it `.` refuses a newline, so a value containing one falls to the
#: generic key in Python while SQLite's `substr` keeps building the padded one:
#: 530 mismatches in 20,000 random values carrying newlines, measured by the
#: design critic. `fullmatch` is what makes the `$` question moot.
#:
#: `ClassificationIn.tidy_number` collapses whitespace at the door, so no
#: request can put a newline in the column. This does not rely on that, for the
#: reason `shelf._looks_like_a_notation` exists: a row written before a
#: validator holds whatever it was given, and `backup.restore` writes this
#: table through `backup._TABLES` rather than through the schema, so an old
#: archive restores whatever it holds. **The same is true of the NUL that
#: `tidy_number` now refuses**, and the consequence there is the sharper one:
#: SQLite's string functions stop at a NUL and Python's do not, so such a row
#: keys differently on the two sides. It mis-sorts one row and is left rather
#: than chased, because a restore that dropped rows to satisfy a sort would be
#: the worse failure.
_LCC: Final = re.compile(
    rf"([A-Za-z]{{1,{_LETTERS_WIDTH}}})"
    rf"([0-9]{{1,{_INTEGER_WIDTH}}})"
    rf"(?:\.([0-9]{{1,{_DECIMAL_WIDTH}}}))?"
    r"(.*)",
    re.DOTALL,
)

#: The (class letters, class integer) length pairs the flattened key has an arm
#: for, and the **one** place that set is written.
#:
#: **Production iterates this and so does the disjointness guard**, which is the
#: whole point. The first version of that guard rebuilt the pairs as a literal
#: in its own body, so it could not see production grow an arm: mutating
#: `sort_expression` to `range(0, _INTEGER_WIDTH + 1)` changed 57 of the guard's
#: own 90 shapes and the guard still reported 0 overlaps and passed. Both critic
#: seats found that independently, and the implementer's attack on it had added
#: the arm to the guard's input rather than to production, which measures the
#: corpus and not the guard.
#:
#: A literal beside a range is two statements of one fact. This is one.
_ARM_SHAPES: Final = tuple(
    (letters, digits)
    for letters in range(1, _LETTERS_WIDTH + 1)
    for digits in range(1, _INTEGER_WIDTH + 1)
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

    def sort_expression(
        self, column: SQLColumnExpression[str]
    ) -> SQLColumnExpression[str]:
        """The key, as one `CASE` of twelve arms with literal offsets.

        **Flattened because the obvious shape is several times slower, and the
        table below is what says how much.** The
        first version computed the letter run and the digit run as `CASE`
        expressions and then used them as `substr` offsets. SQLAlchemy has no
        common subexpression elimination and SQL has no way to name a value
        inside an expression, so each run length was re-rendered at every
        offset that mentioned it: `letters` inside all four arms of the digit
        run, and the position past the integer inside all six arms of the
        decimal run and three times again in the tail. That is 522 `substr`
        calls for a four part key, every one of them evaluated per
        classification row per page.

        Measured in this tree on one four core development host, `ORDER BY
        <clause> LIMIT 25` over a seeded library whose books carry one Dewey
        and one LCC row each, best of 3. **Every column of a row from one run**,
        including the pre-flattening clause rebuilt for the comparison, because
        a pair drawn from two runs is how this paragraph went wrong twice:

        | books | `books.title` | `ddc` | `lcc` before | `lcc` after |
        |---|---|---|---|---|
        | 5,000 | 1.1 ms | 16.7 ms | 393.3 ms | 73.1 ms |
        | 20,000 | 4.2 ms | 70.6 ms | 1,652.3 ms | 291.8 ms |

        **The figure that holds across shapes is the cost per classification
        row**, because that is what the correlated subquery evaluates once per
        row: net of the title baseline, **0.078 and 0.082 ms before, 0.0144
        after**, a factor of **5.4x at 5,000 books and 5.7x at 20,000**. Both
        seats caught that written as a single 5.7x, which is true of the second
        row only. The security seat measured 0.131 against 0.020 on its own
        corpus, and 0.017 after this arm was trimmed.

        **The absolute milliseconds are a floor, not an estimate**, and the
        reason is the storage rather than the processor: SQLite here was backed
        by a file on tmpfs, so every read was RAM, where a deployment puts the
        database on real storage.

        **Most of an LCC row is expression evaluation rather than I/O, which
        is what storage would change, and the baseline for saying so has to be
        `ddc`.** It runs the identical correlated subquery over the identical
        rows and differs only in the expression, so the difference between them
        is expression cost above identical row access: **77% at 5,000 books and
        76% at 20,000** on the table above, and 83% on the design seat's own
        paired run.

        **`books.title` cannot be that baseline**, which is how the first
        version of this paragraph got 99%. It never reads `classifications` at
        all, so it is not an upper bound on this clause's I/O, and both figures
        in that ratio were themselves measured on tmpfs: two RAM speed numbers
        say nothing about what happens when one becomes disk speed. A cross
        instrument comparison dressed as a same instrument one, which is the
        fault this ticket has now paid for five times.

        **Do not read a ratio against `books.title` as a constant.** That order
        never touches this table, so the ratio grows with rows per book: the
        security seat measured 59.5x at one LCC row per book and 316x at four,
        both on its own corpus.

        `MAX_CLASSIFICATIONS_PER_BOOK` is 8, so the worst case a member can
        build is 8 rows on 20,000 books. **Each pair from one corpus, never
        mixed**: **13.2 s to 2.3 s** here (8 x 20,000 x 0.082 and x 0.0144) and
        **21.0 s to 3.2 s** on the security seat's (x 0.131 and x 0.020). Slow,
        and no longer enough to serialise the app from an ordinary catalogue.

        Both critic seats found the cost independently, which is the strongest
        signal this process produces.

        **The flattening is possible because both runs are bounded.** One to
        three class letters and one to four digits is twelve combinations, and
        naming the combination up front makes every offset inside the arm a
        literal. `CASE` short circuits, so exactly one arm is evaluated and
        nothing in it re-derives a length. The decimal run keeps
        `_run_length`, which is cheap once its start is a literal.

        **A stored key removes this rather than shrinking it, and it is what
        the reference implementation does.** Koha computes `cn_sort` on write.
        That is a column and a migration, and it is the obvious next move on
        this module.
        """
        arms = [self._arm(column, *shape) for shape in _ARM_SHAPES]
        return case(*arms, else_=GENERIC.sort_expression(column))

    @staticmethod
    def _arm(
        column: SQLColumnExpression[str], letters: int, digits: int
    ) -> tuple[ColumnElement[bool], SQLColumnExpression[str]]:
        """The test and the key for a call number of exactly these two lengths.

        **The arms are disjoint on their positive tests alone**, and an earlier
        version of this sentence credited the wrong half. It said a run of
        `letters` letters is that many followed by something that is not one,
        and appended a not-a-letter test at `letters + 1` to say so. That test
        guarded nothing: every arm carries at least one digit, its first digit
        test sits at exactly that position, and a digit is not a letter. So the
        digit test already ends the letter run, and dropping the branch is an
        equivalent mutant. The design seat demonstrated that rather than
        arguing it: 0 key mismatches on three corpora, and 0 of 3,920 values
        matching more than one arm.

        The digit run needs its own not-a-digit test and keeps it, because
        nothing follows it that is disjoint from a digit: the next character
        may be a point, a cutter letter or a space.

        **The deletion rests on every arm carrying at least one digit.** A
        `digits = 0` arm would make the deleted test necessary again, and the
        failure would be two arms matching one value rather than anything red.
        `_ARM_SHAPES` is what makes that checkable: production and the guard in
        `tests/test_shelf.py::TestTheFilingKeysAgree` read the same tuple, so a
        shape added to production is a shape the guard tests. Stated that way
        because the first version said "asserted rather than left to the range"
        while the guard held its own literal, which left it to the range twice.

        At either cap there is no closing test at all, because the run stops by
        being capped. `_LCC` caps its own repetitions at the same two
        constants, which is what keeps the two halves agreeing on a long value.
        """
        digits_at = letters + 1
        # The character past the class integer: a point when a decimal
        # extension follows, and the first of the cutters otherwise. A literal,
        # which is the whole point of this arm.
        after_integer = letters + digits + 1

        matches = [_is_letter(_substr(column, at, 1)) for at in range(1, letters + 1)]
        matches += [
            _is_digit(_substr(column, digits_at + offset, 1)) for offset in range(digits)
        ]
        if digits < _INTEGER_WIDTH:
            matches.append(~_is_digit(_substr(column, digits_at + digits, 1)))

        decimal = case(
            (
                _substr(column, after_integer, 1) == ".",
                _run_length(column, after_integer + 1, _is_digit, _DECIMAL_WIDTH),
            ),
            else_=0,
        )
        # A point with no digit after it belongs to a cutter, so the rest starts
        # at the point rather than past it. That is `BF575.S75`.
        rest_at = after_integer + case((decimal > 0, decimal + 1), else_=0)

        key = (
            _pad_right(
                func.upper(_substr(column, 1, letters), type_=String()),
                _LETTERS_WIDTH,
                _LETTER_PAD,
            )
            + _pad_left(_substr(column, digits_at, digits), digits, _INTEGER_WIDTH)
            + _pad_right(_substr(column, after_integer + 1, decimal), _DECIMAL_WIDTH, "0")
            + _substr(column, rest_at)
        )
        return and_(*matches), key


def _substr(
    value: SQLColumnExpression[str],
    start: SQLColumnExpression[int] | int,
    length: object = None,
) -> ColumnElement[str]:
    """`substr`, typed as text.

    **The type is the point.** Without it SQLAlchemy infers `NullType` and `+`
    on the result renders as arithmetic addition rather than `||`. Measured by
    dropping `type_` and evaluating the real expression: `BF575.S75 E64 2022`
    keys as `575`, `QA76.73.J38 F57 2020` as `730076`, `Q1` as `1`, and a value
    falling to the generic arm still keys as its own text. So the failure is
    not a uniform `0` and not an error: it is plausible looking integers beside
    strings, which a listing renders as an order that is partly right.
    """
    if length is None:
        return func.substr(value, start, type_=String())
    return func.substr(value, start, length, type_=String())


def _is_letter(char: SQLColumnExpression[str]) -> ColumnElement[bool]:
    """An ASCII letter, in either case.

    Through `upper` and a range rather than a character class, for the reason
    `shelf._looks_like_a_notation` gives: `GLOB` and a regex are one database's
    and this expression has no reason to know which one it is on. `A` to `Z` is
    contiguous, so the range admits letters and nothing else.
    """
    return func.upper(char, type_=String()).between("A", "Z")


def _is_digit(char: SQLColumnExpression[str]) -> ColumnElement[bool]:
    """A digit. `0` to `9` is contiguous, as above."""
    return char.between("0", "9")


def _run_length(
    value: SQLColumnExpression[str],
    start: SQLColumnExpression[int] | int,
    is_kind: Callable[[SQLColumnExpression[str]], ColumnElement[bool]],
    maximum: int,
) -> ColumnElement[int]:
    """How many characters from `start` are of this kind, capped at `maximum`.

    The first arm that matches wins, so the arms ask where the run **stops**.
    Past the end of the value `substr` returns the empty string, which is of no
    kind, so a short value stops on its own rather than needing a length test.

    Capped because the Python side is capped: a repetition count in `_LCC` and
    the number of arms here are the same bound stated twice, and
    `_LETTERS_WIDTH` and its two neighbours are what keep them equal.
    """
    return case(
        *(
            (~is_kind(_substr(value, start + offset, 1)), offset)
            for offset in range(maximum)
        ),
        else_=maximum,
    )


def _pad_right(
    value: SQLColumnExpression[str], width: int, fill: str
) -> ColumnElement[str]:
    """`value`, filled on the right to exactly `width`, and cut to it."""
    return _substr(value + literal(fill * width), 1, width)


def _pad_left(
    value: SQLColumnExpression[str],
    length: SQLColumnExpression[int] | int,
    width: int,
) -> ColumnElement[str]:
    """`value`, zero filled on the left to exactly `width`.

    Takes the value's length rather than calling `length()`, because the caller
    has already computed it as a run length and a second derivation of one fact
    is a second thing to get wrong.
    """
    return _substr(literal("0" * width) + value, length + 1, width)


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


#: The schemes a shelf may be ordered by, derived from the rules themselves.
#:
#: Derived rather than written out, so "which schemes file a shelf" is stated
#: once, on the rule that answers it. `shelf._SHELF_SORTS` pairs each of these
#: with the `BookSort` value that asks for it, and `tests/test_shelf.py` pins
#: that the two cover each other.
SHELF_SCHEMES: Final[tuple[ClassificationScheme, ...]] = tuple(
    scheme for scheme, rule in FILING_RULES.items() if rule.orders_a_shelf
)
