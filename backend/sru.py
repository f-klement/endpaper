"""SRU, served rather than consumed, which is the other direction from `targets.py`.

## The second surface reachable without a session, answering the same five
## questions as the first

`routers/public.py` names them, and this module's whole placement is that it must
not answer any of them a second, different way:

| Question | Answered by |
|---|---|
| Is anything published at all? | `public_catalogue_is_published`, through `public_reader` |
| Which **rows** may be shown? | `Shelf.seen_by_the_public` |
| Which **columns** may be shown? | `marc.py`'s field mapping, pinned against `schemas/public.py` |
| How fast may a stranger ask? | `ratelimit.public_catalogue_limiter`, the same counter |
| May a crawler index it? | `middleware.SecurityHeadersMiddleware` |

**Reusing the publish gate is stricter than the ticket asked**, which wanted only
that library mode off makes the endpoint disappear. An institution that has not
published its catalogue has not published it over a protocol either, and this is
the only arrangement where the two surfaces cannot drift apart.

**The column question is the one that took work.** A row filter is necessary and
not sufficient: MARC has fields for the shelf mark, the price paid and the
acquisition source, and `marc.py` writes none of them, which is what makes
reusing it safe. `TestTheRecordCarriesNoColumnThePublicPayloadWithholds` keeps it
true, and the day an `852 $b` is added for a cataloguer that test fails and this
server needs a writer of its own.

## The CQL parser is the real work, and it is an outside input

Everything a stranger sends arrives in one string, so the parse is bounded
**five** ways, each with its own constant and its own diagnostic:
`MAX_QUERY_CHARS`, `MAX_NESTING_DEPTH`, `MAX_CLAUSES`, `MAX_WORDS_IN_A_TERM` and
`MAX_MASKS_IN_A_TERM`. The last two decide how many predicates a clause expands
into, which the first three do not bound. **The depth bound is enforced during
the recursion**, because the failure it stops is a `RecursionError` and a check
that runs after the parse never runs.

**Every refusal this module decides is a diagnostic in an HTTP 200**, never a
4xx: an SRU client reads the body, and a status it did not expect is not an
answer it can act on. **An exception that is not an `SruError` is still a 500**,
deliberately, because a bug here must not be dressed as a protocol answer.

## Nothing here writes, and nothing here parses XML

The module builds documents and never reads one, so there is no parser on the
untrusted path at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Any, Final
from urllib.parse import parse_qs
from xml.etree import ElementTree

from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

import marc
from enums import BookSort
from models import Book, Tag
from shelf import Loading, Shelf, order_for

# ── The diagnostic register ───────────────────────────────────────────────────


class Diagnostic(IntEnum):
    """The SRU diagnostics this server raises, by their number in set 1.

    One register for the whole module, and it is why the CQL parser is not a
    module of its own: a parse failure is diagnostic 13 or 38, a parameter
    failure is 6 or 8, and they are the same list.

    **The stronger version of that argument is false and was written here
    first.** Splitting the parser out does *not* force two lists of numbers or a
    translation table: a third module holding this enum and `SruError`, imported
    by both, is one register, no table and no import cycle. The real cost is
    smaller and is the actual reason: that third module's entire content would
    be an enum and an exception, so every reason a reader is chasing would be
    one more file to open, and neither half is large enough to earn it.

    Every member here is raised somewhere and
    `tests/test_sru.py::TestEveryDiagnosticIsReachable` is what says so: a
    diagnostic nothing can produce is a claim about the server that no client
    can act on.

    **The numbers were checked against a second source rather than remembered.**
    Three of them, 30, 31 and 36, were the ones this module's author was least
    sure of, and a number that is wrong here is a URI a client matches on and
    misroutes. `targets.py` already corroborated 8, 11 and 235 from contact with
    live servers; the rest were read off CLARIN's `fcs-sru-server`
    `SRUConstants.java`, an independent implementation of the same list, and all
    twenty two that existed then agreed name for name. Reading that list is also
    what found the members below that this module was answering with a general
    code.

    **No number is given for how many members there are now**, here or anywhere
    else: this enum has already grown twice since that check, a count in prose
    does not recount itself, and `TestEveryDiagnosticIsReachable` asserts
    totality against the enum rather than against a figure.
    """

    #: `operation=scan`, or anything else that is not explain or searchRetrieve.
    UNSUPPORTED_OPERATION = 4
    #: `version=2.0`. SRU 2.0 renamed half the parameters; claiming it and
    #: answering 1.2 is worse than saying no.
    UNSUPPORTED_VERSION = 5
    #: A parameter this server takes, carrying a value it does not: a
    #: `maximumRecords` that is not a number, or a parameter sent twice.
    UNSUPPORTED_PARAMETER_VALUE = 6
    #: `operation=searchRetrieve` with no `query`.
    MANDATORY_PARAMETER_NOT_SUPPLIED = 7
    #: A parameter nobody here has heard of.
    #:
    #: **Not the answer for a parameter the specification defines and this
    #: server declines**: those have their own numbers, and the difference is a
    #: different sentence to the client. See `_DECLINED_PARAMETERS`.
    UNSUPPORTED_PARAMETER = 8
    QUERY_SYNTAX_ERROR = 10
    #: `MAX_QUERY_CHARS`.
    TOO_MANY_CHARACTERS_IN_QUERY = 12
    #: Unbalanced parentheses, and `MAX_NESTING_DEPTH`.
    UNSUPPORTED_USE_OF_PARENTHESES = 13
    #: An unterminated quoted term.
    UNSUPPORTED_USE_OF_QUOTES = 14
    #: A context set prefix that is not one of `CONTEXT_SETS`.
    UNSUPPORTED_CONTEXT_SET = 15
    #: A known context set, an index it does not hold here.
    UNSUPPORTED_INDEX = 16
    #: `within`, `encloses`, `adj`, or a numeric relation on a text index.
    UNSUPPORTED_RELATION = 19
    #: Anything after a `/`. CQL puts relation modifiers there and this server
    #: implements none of them.
    UNSUPPORTED_RELATION_MODIFIER = 20
    #: A backslash before a character that is not one of `\ " * ? ^`.
    NON_SPECIAL_CHARACTER_ESCAPED = 26
    #: `dc.title=` with nothing after it, which is a valid CQL query that asks
    #: for something other than what was meant.
    EMPTY_TERM = 27
    #: `MAX_MASKS_IN_A_TERM`.
    TOO_MANY_MASKING_CHARACTERS = 30
    #: `^`, CQL's anchor.
    ANCHORING_NOT_SUPPORTED = 31
    #: A term that is not an integer, on `dc.date` or `rec.id`.
    TERM_IN_INVALID_FORMAT = 36
    #: `MAX_CLAUSES` and `MAX_WORDS_IN_A_TERM`. Both bound the number of
    #: predicates one query compiles to, which is the number of boolean
    #: operators between them.
    TOO_MANY_BOOLEAN_OPERATORS = 38
    #: `prox`.
    PROXIMITY_NOT_SUPPORTED = 39
    #: `resultSetTTL`. The only result set parameter SRU 1.2's searchRetrieve
    #: has, so declining it is declining result sets.
    RESULT_SETS_NOT_SUPPORTED = 50
    #: `startRecord` past the end of the result set.
    FIRST_RECORD_OUT_OF_RANGE = 61
    #: A `recordSchema` that is not MARCXML.
    UNKNOWN_SCHEMA_FOR_RETRIEVAL = 66
    #: A `recordPacking` that is not `xml`.
    #:
    #: Named for SRU 2.0's spelling of the parameter, `recordXMLEscaping`, and
    #: it is the same number in 1.2, where the 1.2 era list called it
    #: "unsupported record packing". This module answered 6 until the number was
    #: confirmed, which was a general code standing in for a specific one.
    UNSUPPORTED_XML_ESCAPING_VALUE = 71
    #: `recordXPath`.
    XPATH_RETRIEVAL_UNSUPPORTED = 72
    #: `sortKeys`, and CQL's `sortby`. A feature, not a typo: the client asked
    #: for sorting, in whichever of the two spellings SRU 1.2 left it.
    SORT_NOT_SUPPORTED = 80
    #: `stylesheet`, which is a refusal here rather than a gap. See the module
    #: docstring.
    STYLESHEETS_NOT_SUPPORTED = 110


#: Where a diagnostic's number is resolved, which is what a client matches on.
DIAGNOSTIC_URI: Final = "info:srw/diagnostic/1/"


class SruError(Exception):
    """A refusal that becomes a diagnostic in a 200 response.

    `details` is what the specification calls the machine readable half and is
    the only place client text is echoed. It goes through `_safe` first: the
    query string is an outside input, and this response is XML, so a control
    character copied straight out of it produces a document no client can parse.
    Refusing the request and then answering with malformed XML is the one
    outcome worse than not refusing it.
    """

    def __init__(self, diagnostic: Diagnostic, details: str = "") -> None:
        super().__init__(f"{diagnostic.name}: {details}")
        self.diagnostic = diagnostic
        self.details = _safe(details)


#: The longest a `<details>` fragment may be.
#:
#: It exists to name the thing that was refused, an index or a parameter, not to
#: quote the request back. A client that sent 900 characters of query does not
#: learn anything from receiving them again.
_DETAILS_CHARS: Final = 60


def _safe(value: str) -> str:
    """Client text, made safe to put in an XML document, and bounded.

    `str.isprintable()` is the test rather than a hand written class. It is
    **stricter** than XML 1.0's own rule rather than equal to it: false for
    everything in Unicode's Other and Separator categories, which covers every
    character XML refuses and a few it allows, and true for the plain space,
    which a phrase needs. Stricter is the safe direction here, since the cost is
    a dropped character in a message and the alternative is a document no client
    can parse.
    """
    return "".join(character for character in value if character.isprintable())[
        :_DETAILS_CHARS
    ]


# ── The bounds ────────────────────────────────────────────────────────────────
#
# Six numbers: five bound the parse and `MAX_RECORDS` bounds the response.
#
# **The product is what matters rather than any one of them, and the obvious
# product is wrong.** `MAX_CLAUSES * MAX_WORDS_IN_A_TERM` is the ceiling for an
# index over one column, and `cql.serverChoice` covers three, so the real figure
# is three times it. `tests/test_sru.py::TestTheWorstLegalQueryIsBounded`
# measures the compiled SQL for both shapes rather than trusting either
# multiplication, which is how that factor of three was found.

#: The longest query this server parses, in characters.
#:
#: It is also the term length bound and the reason there is not a separate one:
#: a term is a substring of the query, so a query of 1024 characters cannot
#: carry a term longer than that. A bound whose value is implied by another
#: bound is a second number to keep true.
#:
#: 1024 because the longest query this application's own client builds is a
#: title phrase and an ISBN, well under 200 characters, and a federated search
#: sending four indexes and four phrases is under 400.
MAX_QUERY_CHARS: Final = 1024

#: How deeply parentheses may nest.
#:
#: **Checked on the way in, not after the parse**, which is the whole point.
#: This is a recursive descent parser, so `"(" * 500` is 500 frames of Python
#: before anything looks at the shape of what was parsed, and CPython's default
#: limit is 1000 frames for the whole process. A check that runs after the parse
#: runs after the `RecursionError`. `tests/test_sru.py` drives a query of
#: `MAX_QUERY_CHARS` open parentheses and asserts a diagnostic rather than an
#: exception.
MAX_NESTING_DEPTH: Final = 8

#: How many search clauses one query may hold.
#:
#: Each is at least one SQL predicate, and with `any` or `all` it is one per
#: word. 16 is far above what a client sends: this application's own SRU
#: requests are one clause, and the largest shape in `targets.py` is a title
#: phrase ANDed word by word.
MAX_CLAUSES: Final = 16

#: How many whitespace separated words one term may hold.
#:
#: Counted for every term regardless of relation, because the relation is what
#: decides whether the words become separate predicates and a bound that
#: depended on the relation would be a bound a client chooses. `any` and `all`
#: expand a term of N words into N predicates joined by N-1 booleans, which is
#: why the refusal is diagnostic 38.
MAX_WORDS_IN_A_TERM: Final = 8

#: How many masking characters one term may hold.
#:
#: Not a cost bound, and the measurement behind that has been re-derived once
#: already: **the figure first published here was taken on a fixture that could
#: not match.** `('%a' * 400)` needs 400 literal `a`s inside a 120 character
#: title, so it failed at the first position on every row and never backtracked
#: at all, and 400 masks is above this bound anyway. Two review seats found that
#: independently, and the number outlived its own retraction in this file for a
#: commit, which is exactly the shape `CLAUDE.md` warns about.
#:
#: Re-derived on the worst shape this bound admits: `MAX_MASKS_IN_A_TERM`
#: wildcards alternating with a literal that matches at every position, then one
#: that cannot, so every position really is tried. Against 3,000 rows whose
#: title is 120 identical characters, warm, three runs: **12.7 to 13.2 ms in
#: total, which is 4.23 to 4.40 microseconds per row**. An ordinary `*a*` is 4.7
#: to 5.0 ms, 1.57 to 1.67 microseconds per row. So SQLite's LIKE does not
#: backtrack the way a regular expression engine would, which is the conclusion
#: the bad fixture reached correctly and could not support.
#:
#: The bound is here because a term of a thousand wildcards is not a search
#: anybody meant to run, and because a future storage engine is not promised to
#: behave as this one measured.
MAX_MASKS_IN_A_TERM: Final = 8

#: The integers this server will accept, which is the range SQLite can store.
#:
#: **Not a stylistic bound: without it three parameters are an unauthenticated
#: 500.** `int()` parses any number of digits, and SQLAlchemy hands the result
#: to SQLite, which raises `OverflowError: Python int too large to convert to
#: SQLite INTEGER` from inside the driver. That is not an `SruError`, so it
#: escapes `respond` and reaches the client as `Internal Server Error`. Measured
#: on the running app with no credentials: `rec.id`, `dc.date` and `startRecord`
#: all 500, for every value from 2**63 up to whatever the surrounding length
#: bound allows.
#:
#: **That upper end differs between the two sites and it is worth knowing which
#: is which.** A term lives inside `query`, so `MAX_QUERY_CHARS` caps it at
#: about a thousand digits and CPython's own 4,300 digit refusal is unreachable
#: on that path: this range is the only thing that refuses a term. A parameter
#: has no such cap, so `startRecord` really can reach the digit limit and be
#: refused by `int()` instead. Both arms are pinned, because a test written on
#: the assumption that they behave alike asserted the wrong diagnostic and
#: failed.
#:
#: **Both ends, because the negative arm is the same bug.** `dc.date > -<2**63+1>`
#: overflows exactly as the positive arm does.
#:
#: The two conversions below are the only `int()` calls in this module, so this
#: is one ceiling at two sites rather than an arm per caller.
SQLITE_MIN_INTEGER: Final = -(2**63)
SQLITE_MAX_INTEGER: Final = 2**63 - 1

#: How many records one response may carry, whatever `maximumRecords` asked for.
#:
#: **Clamped rather than refused**, which is what the specification expects: a
#: server returns what it is willing to return and the client reads
#: `numberOfRecords` to find out how much is left. `explain` advertises this in
#: `configInfo`, so a client can size its paging before it asks.
#:
#: 50 because a MARCXML record here is unbounded in one field: `520 $a` carries
#: the description, which no schema limits, so there is no record size this
#: number could have been derived from.
#: `tests/test_sru.py::TestTheRecordSizeThatDecidedTheCap` is what makes it a
#: measurement rather than a guess: it builds a full page of records with a
#: 2,000 character description each and fails if the response passes a quarter
#: of a mebibyte. Raising this constant, or adding a large field to the writer,
#: is then a decision somebody makes rather than one that happens.
MAX_RECORDS: Final = 50

#: How many records a client gets without asking.
#:
#: The specification's own suggestion, and the number every SRU server this
#: application talks to uses.
DEFAULT_RECORDS: Final = 10


# ── CQL, read ─────────────────────────────────────────────────────────────────


class Mask(Enum):
    """CQL's two wildcards, kept apart from the literal text of a term.

    A term cannot be one string once masking is supported, because `\\*` and `*`
    are the same character after the escape is resolved and mean opposite
    things. So a term is a sequence of literal runs and masks, and the escape is
    resolved exactly once, here, rather than being re-guessed by whatever builds
    the SQL.
    """

    ANY_STRING = auto()
    ANY_CHAR = auto()


#: One piece of a term: a run of literal characters, or a wildcard.
type Piece = str | Mask

_WHITESPACE: Final = re.compile(r"\s+")

#: The characters a backslash may precede in a term.
#:
#: CQL's own list. Anything else is diagnostic 26 rather than a silently
#: swallowed backslash, because a client escaping a character that needs no
#: escape has misunderstood something and a search that quietly finds nothing is
#: the worst way to be told.
_ESCAPABLE: Final = frozenset('\\"*?^')


@dataclass(frozen=True, slots=True)
class Term:
    """The right hand side of a search clause, with the escapes already resolved."""

    pieces: tuple[Piece, ...]

    @property
    def masked(self) -> bool:
        return any(isinstance(piece, Mask) for piece in self.pieces)

    @property
    def text(self) -> str:
        """The literal text. Meaningful only when `masked` is false."""
        return "".join(piece for piece in self.pieces if isinstance(piece, str))

    def words(self) -> tuple[Term, ...]:
        """This term split on whitespace, each word keeping its own masks.

        `any` and `all` are defined over the words of a term, so the split has
        to survive the masking: `dc.title any "harr* potter"` is two words and
        the first is masked.
        """
        words: list[tuple[Piece, ...]] = []
        current: list[Piece] = []
        for piece in self.pieces:
            if isinstance(piece, Mask):
                current.append(piece)
                continue
            for index, chunk in enumerate(_WHITESPACE.split(piece)):
                if index:
                    if current:
                        words.append(tuple(current))
                    current = []
                if chunk:
                    current.append(chunk)
        if current:
            words.append(tuple(current))
        return tuple(Term(word) for word in words)


@dataclass(frozen=True, slots=True)
class Clause:
    """One `index relation term`, with the index and relation lowercased.

    CQL keywords, index names and relation names are all case insensitive, so
    they are folded once here and everything downstream compares plain strings.
    An index of `""` is `cql.serverChoice`, which is what a bare term means.
    """

    index: str
    relation: str
    term: Term


@dataclass(frozen=True, slots=True)
class Boolean:
    """Two nodes and the operator between them.

    **CQL booleans are left associative and all have equal precedence**, which
    is not what a reader who writes SQL expects: `a or b and c` is `(a or b) and
    c` here and `a or (b and c)` in SQL. Parentheses are how a client says
    otherwise, and this is the one place the difference is written down.
    """

    operator: str
    left: Node
    right: Node


type Node = Clause | Boolean


class _Kind(Enum):
    WORD = auto()
    QUOTED = auto()
    OPEN = auto()
    CLOSE = auto()
    RELATION = auto()


@dataclass(frozen=True, slots=True)
class _Token:
    kind: _Kind
    text: str


#: The relation symbols, longest first so `==` is not read as two `=`.
_RELATION_SYMBOLS: Final = ("==", "<=", ">=", "<>", "=", "<", ">")

#: The relations spelled as words. `within`, `encloses` and `adj` are recognised
#: and then refused with diagnostic 19, which is a better answer than the syntax
#: error a parser that did not know them would give.
_RELATION_WORDS: Final = frozenset(
    {"all", "any", "exact", "within", "encloses", "adj"}
)

#: The booleans. `prox` is recognised for the same reason `within` is.
_BOOLEANS: Final = frozenset({"and", "or", "not", "prox"})

#: Characters that end a bare word.
#:
#: The backslash is **not** among them: it escapes the character after it, so a
#: word may contain `\"` and the scanner has to take both characters together.
_WORD_BREAK: Final = frozenset('()"=<>/')

#: An index name: an optional context set prefix, a dot, a name.
#:
#: The same shape `targets._INDEX` accepts on the way out, and matched with
#: `fullmatch` for the same reason: `$` matches before a trailing newline.
_INDEX_NAME: Final = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_]+)?")


def _tokenise(query: str) -> list[_Token]:
    """The query as tokens, or a diagnostic.

    Bounded by `MAX_QUERY_CHARS` before a character is looked at, so the number
    of tokens is bounded too and nothing below has to count them.
    """
    if len(query) > MAX_QUERY_CHARS:
        raise SruError(
            Diagnostic.TOO_MANY_CHARACTERS_IN_QUERY,
            f"at most {MAX_QUERY_CHARS} characters",
        )
    # Control characters end nothing and mean nothing in CQL, and one copied
    # into a `<details>` would be a response no client can parse. Refused at the
    # edge rather than sanitised later, because sanitising changes the query
    # somebody asked for into a different query and answers it.
    for character in query:
        if not character.isprintable() and character not in "\t\r\n":
            raise SruError(Diagnostic.QUERY_SYNTAX_ERROR, "a control character")

    tokens: list[_Token] = []
    position = 0
    length = len(query)
    while position < length:
        character = query[position]
        if character.isspace():
            position += 1
            continue
        if character == "(":
            tokens.append(_Token(_Kind.OPEN, "("))
            position += 1
            continue
        if character == ")":
            tokens.append(_Token(_Kind.CLOSE, ")"))
            position += 1
            continue
        if character == "/":
            # **A sort spec carries its modifiers on a `/` too, and that `/`
            # reaches here before a parser exists.** So the `sortby` arm in
            # `_Parser.parse` covers only the bare spelling, and CQL 1.2's
            # ordinary one, `sortby dc.date/ascending`, was answered 20: wrong
            # twice over, since it is not a relation modifier and the client
            # asked for sorting.
            #
            # Looking back for a bare `sortby` is what distinguishes the two,
            # and it is exact rather than approximate: a quoted `"sortby"` is a
            # QUOTED token and cannot match, so a search for that word is still
            # a search, and `dc.title =/rel dog` has no earlier `sortby` and
            # still gets 20.
            #
            # This is the round's own lesson landing on the round's own fix: the
            # first version pinned the one spelling a review named, and an
            # example is not a family.
            if any(
                token.kind is _Kind.WORD and token.text.lower() == "sortby"
                for token in tokens
            ):
                raise SruError(Diagnostic.SORT_NOT_SUPPORTED, "sortby")
            raise SruError(
                Diagnostic.UNSUPPORTED_RELATION_MODIFIER, "no relation modifiers"
            )
        if character == '"':
            text, position = _scan_quoted(query, position)
            tokens.append(_Token(_Kind.QUOTED, text))
            continue
        symbol = next(
            (
                candidate
                for candidate in _RELATION_SYMBOLS
                if query.startswith(candidate, position)
            ),
            None,
        )
        if symbol is not None:
            tokens.append(_Token(_Kind.RELATION, symbol))
            position += len(symbol)
            continue
        text, position = _scan_word(query, position)
        tokens.append(_Token(_Kind.WORD, text))
    return tokens


def _scan_quoted(query: str, position: int) -> tuple[str, int]:
    """A `"..."` term, returned raw: the escapes are resolved by `_pieces`."""
    position += 1
    characters: list[str] = []
    while position < len(query):
        character = query[position]
        if character == "\\":
            # The escaped character is taken whatever it is, including a quote,
            # so `"a\"b"` is one term. Whether the escape was legal is `_pieces`'
            # question, and answering it here would answer it twice.
            characters.append(query[position : position + 2])
            position += 2
            continue
        if character == '"':
            return "".join(characters), position + 1
        characters.append(character)
        position += 1
    raise SruError(Diagnostic.UNSUPPORTED_USE_OF_QUOTES, "unterminated quote")


def _scan_word(query: str, position: int) -> tuple[str, int]:
    """A bare word, returned raw."""
    characters: list[str] = []
    while position < len(query):
        character = query[position]
        if character == "\\":
            characters.append(query[position : position + 2])
            position += 2
            continue
        if character.isspace() or character in _WORD_BREAK:
            break
        characters.append(character)
        position += 1
    return "".join(characters), position


def _pieces(raw: str) -> Term:
    """One raw token as a term: escapes resolved, masks kept apart from text."""
    pieces: list[Piece] = []
    literal: list[str] = []
    masks = 0
    position = 0
    while position < len(raw):
        character = raw[position]
        if character == "\\":
            if position + 1 >= len(raw):
                raise SruError(
                    Diagnostic.QUERY_SYNTAX_ERROR, "a term ends with a backslash"
                )
            escaped = raw[position + 1]
            if escaped not in _ESCAPABLE:
                raise SruError(
                    Diagnostic.NON_SPECIAL_CHARACTER_ESCAPED, f"\\{escaped}"
                )
            literal.append(escaped)
            position += 2
            continue
        if character == "^":
            raise SruError(Diagnostic.ANCHORING_NOT_SUPPORTED, "^")
        if character in "*?":
            if literal:
                pieces.append("".join(literal))
                literal = []
            masks += 1
            if masks > MAX_MASKS_IN_A_TERM:
                raise SruError(
                    Diagnostic.TOO_MANY_MASKING_CHARACTERS,
                    f"at most {MAX_MASKS_IN_A_TERM} per term",
                )
            pieces.append(Mask.ANY_STRING if character == "*" else Mask.ANY_CHAR)
            position += 1
            continue
        literal.append(character)
        position += 1
    if literal:
        pieces.append("".join(literal))
    if not pieces:
        raise SruError(Diagnostic.EMPTY_TERM, "a term with nothing in it")
    return Term(tuple(pieces))


class _Parser:
    """Recursive descent over the tokens, with the two counted bounds.

    A class rather than a closure because both bounds are counters that outlive
    one call: the clause count is over the whole query and the depth is over one
    branch of it.
    """

    def __init__(self, tokens: Sequence[_Token]) -> None:
        self._tokens = tokens
        self._position = 0
        self._clauses = 0

    def parse(self) -> Node:
        node = self._query(depth=0)
        if self._position < len(self._tokens):
            token = self._tokens[self._position]
            # **`sortby` is a CQL clause, not a parameter, and that is where
            # SRU 1.2 put sorting.** It dropped `sortKeys` from the parameter
            # table in favour of this, so a client using the current spelling
            # was being told its CQL was malformed while the retired spelling
            # got the honest 80. Recognised and refused for the same reason
            # `_query` recognises `prox`, `within`, `encloses` and `adj`: a
            # named refusal is a better answer than a syntax error.
            if token.kind is _Kind.WORD and token.text.lower() == "sortby":
                raise SruError(Diagnostic.SORT_NOT_SUPPORTED, "sortby")
            raise SruError(
                Diagnostic.QUERY_SYNTAX_ERROR,
                f"unexpected {_safe(token.text)}",
            )
        return node

    def _peek(self) -> _Token | None:
        if self._position < len(self._tokens):
            return self._tokens[self._position]
        return None

    def _take(self) -> _Token:
        token = self._peek()
        if token is None:
            raise SruError(Diagnostic.QUERY_SYNTAX_ERROR, "the query ends early")
        self._position += 1
        return token

    def _query(self, depth: int) -> Node:
        """A clause, then any number of `boolean clause` pairs, left associative."""
        node = self._clause(depth)
        while True:
            token = self._peek()
            if token is None or token.kind is not _Kind.WORD:
                return node
            operator = token.text.lower()
            if operator not in _BOOLEANS:
                return node
            self._position += 1
            if operator == "prox":
                raise SruError(Diagnostic.PROXIMITY_NOT_SUPPORTED, "prox")
            node = Boolean(operator, node, self._clause(depth))

    def _clause(self, depth: int) -> Node:
        token = self._take()
        if token.kind is _Kind.CLOSE:
            raise SruError(
                Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES, "an unmatched )"
            )
        if token.kind is _Kind.OPEN:
            # **The depth bound is here and nowhere else.** One frame of this
            # method per level, so a bound checked after the parse is a bound
            # checked after the RecursionError.
            if depth + 1 > MAX_NESTING_DEPTH:
                raise SruError(
                    Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES,
                    f"at most {MAX_NESTING_DEPTH} deep",
                )
            node = self._query(depth + 1)
            closing = self._peek()
            if closing is None or closing.kind is not _Kind.CLOSE:
                raise SruError(
                    Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES, "an unclosed ("
                )
            self._position += 1
            return node
        if token.kind is _Kind.RELATION:
            raise SruError(
                Diagnostic.QUERY_SYNTAX_ERROR, "a relation with nothing before it"
            )

        relation, term_token = self._relation_and_term()
        if relation is None:
            index, relation, raw = "", "=", token.text
        else:
            if token.kind is not _Kind.WORD or not _INDEX_NAME.fullmatch(token.text):
                raise SruError(
                    Diagnostic.UNSUPPORTED_INDEX, _safe(token.text) or "an index"
                )
            index, raw = token.text.lower(), term_token.text

        self._clauses += 1
        if self._clauses > MAX_CLAUSES:
            raise SruError(
                Diagnostic.TOO_MANY_BOOLEAN_OPERATORS,
                f"at most {MAX_CLAUSES} search clauses",
            )
        term = _pieces(raw)
        if len(term.words()) > MAX_WORDS_IN_A_TERM:
            raise SruError(
                Diagnostic.TOO_MANY_BOOLEAN_OPERATORS,
                f"at most {MAX_WORDS_IN_A_TERM} words in a term",
            )
        return Clause(index, relation, term)

    def _relation_and_term(self) -> tuple[str | None, _Token]:
        """The relation and the term after it, or `None` for a bare term.

        Returns the token it did not consume as the second element only when
        the first is not None, so the caller reads one or the other. The bare
        term case cannot fail here: whatever was taken is the term.
        """
        token = self._peek()
        if token is None:
            return None, _Token(_Kind.WORD, "")
        if token.kind is _Kind.RELATION:
            relation = token.text
        elif token.kind is _Kind.WORD and token.text.lower() in _RELATION_WORDS:
            relation = token.text.lower()
        else:
            return None, _Token(_Kind.WORD, "")
        self._position += 1
        term = self._peek()
        # **`dc.title=` is an empty term, not a syntax error**, and the
        # difference is what a client does about it. `targets.cql_term` records
        # the same judgement from the writing side: `num=` parses, and it asks
        # for something other than what was meant. A `_take()` here would have
        # answered diagnostic 10 for the query the specification has 27 for.
        if term is None:
            raise SruError(Diagnostic.EMPTY_TERM, "a relation with no term after it")
        if term.kind not in (_Kind.WORD, _Kind.QUOTED):
            raise SruError(
                Diagnostic.QUERY_SYNTAX_ERROR, "a relation with no term after it"
            )
        self._position += 1
        return relation, term


def parse(query: str) -> Node:
    """One CQL query as a tree, or an `SruError` carrying its diagnostic."""
    tokens = _tokenise(query)
    if not tokens:
        raise SruError(Diagnostic.EMPTY_TERM, "an empty query")
    return _Parser(tokens).parse()


# ── The indexes, which are what `explain` reports ─────────────────────────────


class Cost(Enum):
    """What one comparison through an index costs, in two measured classes.

    **A property of the index, not of the column**, and that is a measurement
    rather than a design preference. The obvious derivation is "a column with no
    length limit is expensive", which gets `dc.description` right and
    `dc.subject` wrong: its column is `String(100)`, and it is a correlated
    `EXISTS` over a join.

    ## The reference corpus, stated because the numbers are only true of it

    3,000 books, 2,000 character descriptions, **one tag each**, warm, three
    runs, min to max. Per comparison is the **total divided by the number of
    comparisons**, not a slope between two rows:

    | index | comparisons | wall clock | per comparison |
    |---|---|---|---|
    | `cql.serverChoice` | 48 | 73 to 80 ms | 1.52 to 1.67 ms |
    | `dc.title` | 64 | 91 to 98 ms | 1.42 to 1.53 ms |
    | `dc.publisher` | 64 | 124 to 141 ms | 1.94 to 2.20 ms |
    | `dc.subject` | 16 | 122 to 144 ms | 7.63 to 9.00 ms |
    | `dc.description` | 8 | 134 to 140 ms | 16.75 to 17.50 ms |
    | `dc.subject` | 64 | 1067 to 1143 ms | 16.67 to 17.86 ms |

    **The two `dc.subject` rows are evidence that cost is not linear in
    comparisons**, which is why the weight is calibrated at the worst point
    rather than at an average: the same index is 7.6 to 9.0 ms per comparison at
    16 and 16.7 to 17.9 at 64.

    ## Why the expensive weight is 8

    **Worst against worst.** The dearest cheap index is `dc.publisher` at 2.20
    ms and the dearest expensive one at its worst point is 17.86 ms, and 17.86
    over 2.20 is 8.1. At 8 the two ceilings land together, 134 to 140 ms against
    91 to 141 ms.

    The number this is *not* is 11, which is the expensive class against the
    **cheapest** cheap index, and would size the whole budget on the best cheap
    case and overcharge the expensive one by about 40%.

    **That 8 also divides the budget is a coincidence and is deliberately not
    given as a reason.** Stating it would make the weight read as coupled to
    `MAX_COMPARISON_BUDGET` when it is not: move the budget to 100 and the
    divisibility evaporates while 8 stays right.

    ## What the table holds fixed, which is the honest limit of it

    **Tags per book.** `dc.subject` is a correlated `EXISTS` over `book_tags`,
    so its cost scales with how many tags a book carries, and every row above
    was taken at one. Measured independently by a review seat on its own corpus,
    eight `dc.subject` comparisons cost 126 to 138 ms at one tag per book and
    1,579 to 1,660 ms at forty, roughly linear in between, while
    `dc.description` and `dc.title` are flat across the same sweep. So this
    weight is correct at one tag and under-prices `dc.subject` by about five
    times at forty, and tags per book is the one input a library sets with no
    limit.

    That also explains a disagreement between two independent measurements that
    neither could explain alone: one has `dc.subject` roughly equal to
    `dc.description` and the other has it at 40% of it. **The equality is a
    property of a corpus rather than of the index.**

    Recorded rather than acted on, and it has its own ticket: reweighting on a
    dimension the server does not measure at request time is a design change
    rather than a correction, and doing it on this evidence would swap a bound
    correct at one tag per book for one correct at forty and wrong at one,
    against no measured distribution of how libraries actually tag.

    ## The shape of the enum

    Declared per row with no default, so a thirteenth index cannot be added
    without somebody deciding what it costs: the failure is a `TypeError` at
    import rather than a row that quietly charges nothing. Two classes rather
    than a continuum, because twelve rows do not support a finer resolution than
    the order of magnitude the table actually shows.
    """

    CHEAP = 1
    EXPENSIVE = 8


#: How much comparing may be spent on one query, in `Cost` units.
#:
#: **This is the bound the parse bounds do not give, and the first version of
#: this module did not have it.** `MAX_CLAUSES` and `MAX_WORDS_IN_A_TERM` bound
#: the **parse**: how much structure one query may hold, which is what stops a
#: hostile string costing memory and stack. They say nothing about what the
#: resulting SQL costs to run, because the same count of comparisons over
#: different columns differs by an order of magnitude.
#:
#: The old ceiling was stated in LIKE occurrences, and counting in that unit
#: made the **cheap** shape look like the worst case: 384 comparisons through
#: `cql.serverChoice` measure 584 to 650 ms, while 128 through `dc.description`,
#: which the same parse bounds also admit, measure 2091 to 2284 ms on this host
#: and were independently measured at 4.6 to 4.9 s on another. A count is not a
#: cost.
#:
#: **64, chosen so that the worst legal query in either class lands in the same
#: place.** Against the reference catalogue above: 64 cheap comparisons are 91
#: to 141 ms and 8 expensive ones are 134 to 140 ms. At the shared 120 a minute
#: that is about 17 seconds of work per 60 second window from one address, which
#: is well inside one core, on a counter `docs/security.md` honestly describes
#: as closer to a global cap than a per client one.
#:
#: **It is applied on top of the parse bounds and never instead of them**, so
#: nothing this admits was refused before: it is strictly tighter. What it now
#: refuses that it used to allow is named in `docs/security.md`, because a bound
#: expressed in a different unit is a different bound rather than a tighter one.
#:
#: The figure scales with the catalogue, which is why it is quoted against a
#: named size rather than stated as a property of the server.
MAX_COMPARISON_BUDGET: Final = 64


@dataclass(slots=True)
class _Budget:
    """How much comparing one query may still spend.

    Mutable and threaded through the compile, because the cost of a clause
    depends on which index it names and that is only known here. Counting after
    the fact off the compiled SQL was the previous arrangement and it counted
    the wrong unit; counting during construction is exact and refuses before the
    statement is executed rather than after it is built.
    """

    left: int

    def spend(self, comparisons: int, cost: Cost, index: Index) -> None:
        """Charge one comparison of a term against an index, or refuse.

        **The details name the index and what it actually costs**, which the
        first version did not: "at most 64 units of comparison" named a unit
        nothing publishes, so it was the one refusal here a client could read
        and still not know what to send instead. Every other bound says "at most
        16 search clauses", which is a number the client counted itself.

        **The charge is `comparisons * cost.value` and the first version of this
        message rendered `cost.value` alone.** They differ exactly where it
        matters: `cql.serverChoice` compares three columns at weight one, so it
        was told it cost 1 when it costs 3, and a client believing that sends 64
        terms and is refused at 22. That is the outcome this message exists to
        prevent, so the wrong half was the half a client reads.

        **The unit is a comparison, and `docs/api.md` says the same word.** The
        two disagreed, and two units in two places is what produced the defect:
        `=` compares a whole term once, while `any` and `all` compare once per
        word, so "a term" is true of one relation and not the other.

        **Kept short on purpose, because `_safe` truncates in silence.** The
        longer wording this replaced measured exactly 60 characters for
        `cql.serverChoice`, against a `_DETAILS_CHARS` of 60: not over, but with
        nothing spare, so a three digit budget, a longer index name or one
        reworded verb would have dropped the `a query` tail, which is the half a
        client needs to act. `tests/test_sru.py` pins the **headroom** rather
        than the current length, and pins that no constructible message is
        truncated at all, because pinning a length is how the next edit lands
        back on the limit.
        """
        charge = comparisons * cost.value
        self.left -= charge
        if self.left < 0:
            raise SruError(
                Diagnostic.TOO_MANY_BOOLEAN_OPERATORS,
                f"{index.qualified}: {charge} a comparison, "
                f"{MAX_COMPARISON_BUDGET} a query",
            )


class Field(Enum):
    """What an index searches, independently of what a client calls it.

    Two names for one field is the ordinary case here (`dc.identifier` and
    `bath.isbn` are both the ISBN), so the index table maps names onto these and
    the compiler switches on these.
    """

    ANYWHERE = auto()
    TITLE = auto()
    CREATOR = auto()
    PUBLISHER = auto()
    IDENTIFIER = auto()
    LANGUAGE = auto()
    DESCRIPTION = auto()
    SUBJECT = auto()
    DATE = auto()
    RECORD_ID = auto()


#: The relations a text index takes.
#:
#: `<>` is deliberately absent. On a nullable column it means "the value is
#: present and differs", which is not what a client reads it as, and CQL's `not`
#: says the other thing properly.
TEXT_RELATIONS: Final = ("=", "==", "exact", "any", "all")

#: The relations a numeric index takes. No `any` or `all`: a year has one word.
NUMERIC_RELATIONS: Final = ("=", "==", "exact", "<", "<=", ">", ">=")


@dataclass(frozen=True, slots=True)
class Index:
    """One searchable index, as `explain` publishes it."""

    #: The context set prefix, or `""` for an index with no prefix.
    context_set: str
    name: str
    field: Field
    title: str
    relations: tuple[str, ...]
    #: What one comparison through this index costs. No default: see `Cost`.
    cost: Cost

    @property
    def qualified(self) -> str:
        return f"{self.context_set}.{self.name}" if self.context_set else self.name


#: The context sets this server answers for, and where each is defined.
#:
#: A prefix outside this map is diagnostic 15 and one inside it with an unknown
#: name is diagnostic 16, which are different answers to a client: the first
#: says "I do not speak that vocabulary" and the second says "I speak it and do
#: not hold that index".
CONTEXT_SETS: Final = {
    "cql": "info:srw/cql-context-set/1/cql-v1.2",
    "dc": "info:srw/cql-context-set/1/dc-v1.1",
    "bath": "http://zing.z3950.org/cql/bath/2.0/",
    "bib": "info:srw/cql-context-set/1/bib-v1.0",
    "rec": "info:srw/cql-context-set/2/rec-1.1",
}

#: Every index this server implements.
#:
#: **`explain` is generated from this tuple**, so the document cannot claim an
#: index the compiler does not hold: that is the ticket's requirement, and
#: `tests/test_sru.py::TestExplainReportsTheIndexesThatExist` asserts it in both
#: directions rather than against a fixed document.
#:
#: `dc.subject` searches this library's **tags**, which is its own vocabulary
#: for a work and is what `PublicBookOut` publishes. Classification headings are
#: not indexed: see the module docstring.
INDEXES: Final = (
    Index("cql", "serverChoice", Field.ANYWHERE, "Anywhere", ("=", "any", "all"), Cost.CHEAP),
    Index("bib", "anywhere", Field.ANYWHERE, "Anywhere", ("=", "any", "all"), Cost.CHEAP),
    Index("dc", "title", Field.TITLE, "Title", TEXT_RELATIONS, Cost.CHEAP),
    Index("dc", "creator", Field.CREATOR, "Author", TEXT_RELATIONS, Cost.CHEAP),
    Index("dc", "publisher", Field.PUBLISHER, "Publisher", TEXT_RELATIONS, Cost.CHEAP),
    Index("dc", "identifier", Field.IDENTIFIER, "ISBN", TEXT_RELATIONS, Cost.CHEAP),
    Index("dc", "language", Field.LANGUAGE, "Language", TEXT_RELATIONS, Cost.CHEAP),
    Index(
        "dc", "description", Field.DESCRIPTION, "Description", TEXT_RELATIONS,
        # The one unbounded column: `books.description` is `Text`.
        Cost.EXPENSIVE,
    ),
    Index(
        "dc", "subject", Field.SUBJECT, "Subject", TEXT_RELATIONS,
        # A correlated EXISTS over a join, which measures the same as scanning
        # the unbounded column above even though its own column is String(100).
        Cost.EXPENSIVE,
    ),
    Index("dc", "date", Field.DATE, "Year of publication", NUMERIC_RELATIONS, Cost.CHEAP),
    Index("bath", "isbn", Field.IDENTIFIER, "ISBN", TEXT_RELATIONS, Cost.CHEAP),
    Index("rec", "id", Field.RECORD_ID, "Record identifier", ("=", "==", "exact"), Cost.CHEAP),
)

#: What a bare index name, one with no context set prefix, resolves to.
#:
#: CQL says an unprefixed index is in the server's default context set, and
#: naming that set `dc` would leave `isbn` unresolvable while `bath.isbn`
#: worked. So the default is a small table instead, and every entry in it names
#: an index that exists above.
BARE_INDEXES: Final = {
    "title": "dc.title",
    "creator": "dc.creator",
    "author": "dc.creator",
    "publisher": "dc.publisher",
    "identifier": "dc.identifier",
    "isbn": "bath.isbn",
    "language": "dc.language",
    "description": "dc.description",
    "subject": "dc.subject",
    "date": "dc.date",
    "year": "dc.date",
    "id": "rec.id",
    "anywhere": "cql.serverChoice",
    "serverchoice": "cql.serverChoice",
}

_BY_NAME: Final = {index.qualified.lower(): index for index in INDEXES}

#: The index a bare term means.
SERVER_CHOICE: Final = _BY_NAME["cql.serverchoice"]


def _resolve(name: str) -> Index:
    """The `Index` a client's index name means, or the diagnostic for why not."""
    if not name:
        return SERVER_CHOICE
    if "." in name:
        prefix = name.split(".", 1)[0]
        if prefix not in CONTEXT_SETS:
            raise SruError(Diagnostic.UNSUPPORTED_CONTEXT_SET, _safe(prefix))
        index = _BY_NAME.get(name)
        if index is None:
            raise SruError(Diagnostic.UNSUPPORTED_INDEX, _safe(name))
        return index
    qualified = BARE_INDEXES.get(name)
    if qualified is None:
        raise SruError(Diagnostic.UNSUPPORTED_INDEX, _safe(name))
    return _BY_NAME[qualified.lower()]


# ── Compiling a tree into a predicate ────────────────────────────────────────

#: The escape character in every LIKE pattern this module builds.
#:
#: A backslash, and it has to be passed to `ilike(escape=...)` explicitly:
#: SQLite has no default LIKE escape at all, so without it a `\%` in a pattern
#: is a literal backslash followed by a wildcard.
_LIKE_ESCAPE: Final = "\\"

#: What has to be escaped inside a LIKE pattern before a mask is put into it.
#:
#: The escape character first, or escaping the wildcards would then escape the
#: backslashes this loop just added.
_LIKE_SPECIAL: Final = (_LIKE_ESCAPE, "%", "_")

#: Which Book column each text field is.
#:
#: A table rather than a branch per field, so adding an index is a row in
#: `INDEXES` and a row here.
_COLUMNS: Final = {
    Field.TITLE: Book.title,
    Field.CREATOR: Book.author,
    Field.PUBLISHER: Book.publisher,
    Field.IDENTIFIER: Book.isbn,
    Field.LANGUAGE: Book.language,
    Field.DESCRIPTION: Book.description,
}

#: The columns a bare term searches.
#:
#: The same three `BookFilters.q` searches, so a bare CQL term and the JSON
#: catalogue's `q=` find the same books. Two answers to "search everything"
#: would be two things to keep in step.
_ANYWHERE_COLUMNS: Final = (Book.title, Book.author, Book.isbn)


def _pattern(term: Term, *, contains: bool) -> str:
    """One term as a SQL LIKE pattern.

    **The literal text is escaped before the masks are translated**, which is
    the ordering the whole correctness of this rests on: a client searching for
    `100%` means a per cent sign, and a client searching for `100*` means a
    wildcard, and the two arrive here as the same length of string.
    `tests/test_sru.py::TestMaskingMeansWhatTheClientMeant` pins it, and pins
    the other direction beside it: an asterisk behind a backslash is a literal
    asterisk and a bare one is a wildcard, asserted as one pair of queries over
    one pair of books, so neither half can pass on its own.

    Masking is supported rather than refused, and the reason is a measurement
    rather than a preference: see `MAX_MASKS_IN_A_TERM`, which carries the
    figure and the fixture it was taken on, and the retraction of the one it
    carried before.
    """
    body: list[str] = []
    for piece in term.pieces:
        if isinstance(piece, Mask):
            body.append("%" if piece is Mask.ANY_STRING else "_")
            continue
        text = piece
        for special in _LIKE_SPECIAL:
            text = text.replace(special, _LIKE_ESCAPE + special)
        body.append(text)
    pattern = "".join(body)
    return f"%{pattern}%" if contains else pattern


def _matches(column: Any, term: Term, *, contains: bool) -> ColumnElement[bool]:
    """One column against one term, and **NULL safe on purpose**.

    The `IS NOT NULL` looks redundant, and on its own it is: `NULL LIKE x` is
    NULL, so the row is dropped either way. It is here for what happens under
    CQL's `not`. `NOT (title LIKE 'x')` is NULL for a book with no title and the
    row is dropped, so `a not dc.publisher=x` would silently exclude every book
    with no publisher, which is the opposite of what the query says. With the
    guard the negation is `NOT (FALSE AND NULL)`, which SQL evaluates to TRUE.
    """
    return and_(
        column.isnot(None),
        column.ilike(_pattern(term, contains=contains), escape=_LIKE_ESCAPE),
    )


def _integer(term: Term, index: Index) -> int:
    """A term as an integer, for the two indexes that take one.

    **The range check is not tidiness.** Without it a term of twenty digits
    parses here, reaches SQLite and raises `OverflowError` from inside the
    driver, which is not an `SruError` and so leaves `respond` as a 500. See
    `SQLITE_MAX_INTEGER`.
    """
    if term.masked:
        raise SruError(
            Diagnostic.TERM_IN_INVALID_FORMAT, f"{index.qualified} takes a number"
        )
    text = term.text.strip()
    try:
        value = int(text)
    except ValueError:
        raise SruError(
            Diagnostic.TERM_IN_INVALID_FORMAT, f"{index.qualified} takes a number"
        ) from None
    if not SQLITE_MIN_INTEGER <= value <= SQLITE_MAX_INTEGER:
        raise SruError(
            Diagnostic.TERM_IN_INVALID_FORMAT,
            f"{index.qualified} takes a number this catalogue can hold",
        )
    return value


#: The SQL comparison each numeric relation is.
_COMPARISONS: Final[dict[str, Callable[[Any, int], ColumnElement[bool]]]] = {
    "<": lambda column, value: column < value,
    "<=": lambda column, value: column <= value,
    ">": lambda column, value: column > value,
    ">=": lambda column, value: column >= value,
}


def _clause_criteria(clause: Clause, budget: _Budget) -> ColumnElement[bool]:
    """One search clause as a predicate over `books`, charged to the budget."""
    index = _resolve(clause.index)
    if clause.relation not in index.relations:
        raise SruError(
            Diagnostic.UNSUPPORTED_RELATION,
            f"{_safe(clause.relation)} on {index.qualified}",
        )

    if index.field is Field.RECORD_ID:
        budget.spend(1, index.cost, index)
        return Book.id == _integer(clause.term, index)

    if index.field is Field.DATE:
        budget.spend(1, index.cost, index)
        value = _integer(clause.term, index)
        comparison = _COMPARISONS.get(clause.relation)
        if comparison is None:
            return and_(Book.year.isnot(None), Book.year == value)
        return and_(Book.year.isnot(None), comparison(Book.year, value))

    exact = clause.relation in ("==", "exact")
    if clause.relation in ("any", "all"):
        words = clause.term.words()
        joiner = or_ if clause.relation == "any" else and_
        return joiner(
            *(_field_criteria(index, word, budget, exact=False) for word in words)
        )
    return _field_criteria(index, clause.term, budget, exact=exact)


def _field_criteria(
    index: Index, term: Term, budget: _Budget, *, exact: bool
) -> ColumnElement[bool]:
    """One term against whichever columns an index covers, charged to the budget.

    **The charge is here rather than at the clause**, because this is the only
    place that knows how many columns a term is actually compared against:
    `cql.serverChoice` is three, everything else is one, and a term split by
    `any` or `all` arrives here once per word.
    """
    if index.field is Field.ANYWHERE:
        budget.spend(len(_ANYWHERE_COLUMNS), index.cost, index)
        return or_(
            *(
                _matches(column, term, contains=not exact)
                for column in _ANYWHERE_COLUMNS
            )
        )
    if index.field is Field.SUBJECT:
        budget.spend(1, index.cost, index)
        # A correlated exists over the tag join, which is the shape
        # `Shelf.matching` already uses for a tag filter. It needs no NULL
        # guard: `NOT EXISTS` is two valued, so `not` over it means what it says.
        return Book.tags.any(
            Tag.name.ilike(_pattern(term, contains=not exact), escape=_LIKE_ESCAPE)
        )
    budget.spend(1, index.cost, index)
    return _matches(_COLUMNS[index.field], term, contains=not exact)


def criteria(node: Node) -> ColumnElement[bool]:
    """A parsed query as one predicate, ready for `Shelf.where`.

    **Nothing here decides visibility**, and there is nothing here that could:
    every predicate this builds narrows a shelf that was already narrowed by
    `Shelf.seen_by_the_public`, which has no ownership arm to widen.

    **This is where the cost bound lives**, because it is the only place that
    sees the whole query and knows which index each clause names. See
    `MAX_COMPARISON_BUDGET` for why the parse bounds are not that bound.
    """
    return _criteria(node, _Budget(MAX_COMPARISON_BUDGET))


def _criteria(node: Node, budget: _Budget) -> ColumnElement[bool]:
    """The recursion, with one budget shared across the whole tree."""
    if isinstance(node, Clause):
        return _clause_criteria(node, budget)
    left, right = _criteria(node.left, budget), _criteria(node.right, budget)
    if node.operator == "and":
        return and_(left, right)
    if node.operator == "or":
        return or_(left, right)
    # CQL's `not` is binary: `a not b` is "a, excluding b". Not a unary
    # negation, and reading it as one would return the complement of the
    # library.
    return and_(left, not_(right))


# ── The request ──────────────────────────────────────────────────────────────

#: The parameters this server takes, per operation.
#:
#: A parameter whose name begins `x-` is an extension and is ignored, which the
#: specification requires. Anything else is refused, and by which diagnostic is
#: `_DECLINED_PARAMETERS`.
_EXPLAIN_PARAMETERS: Final = frozenset({"operation", "version", "recordPacking"})
_SEARCH_PARAMETERS: Final = frozenset(
    {
        "operation",
        "version",
        "query",
        "startRecord",
        "maximumRecords",
        "recordSchema",
        "recordPacking",
    }
)

#: Parameters the specification defines that this server declines, each with the
#: diagnostic the specification has for declining it.
#:
#: **Separate from the generic diagnostic 8, and that separation is the whole
#: point of the table.** A client sending `sortKeys` has not made a typo and has
#: not sent something nobody has heard of: it asked for a feature. 80 says "this
#: server does not sort" and 8 says "there is no such parameter", and only the
#: first tells the client what to do next.
#:
#: This module answered 8 to all three until the diagnostic list was read
#: against a second implementation, which is the same class of error as the
#: general codes it also replaced on `recordPacking`: a number that is safely
#: true and less use than the one the specification provides.
#:
#: `stylesheet` is the one that is a refusal rather than a gap: see the module
#: docstring for what honouring it would put in the response.
#: **Checked against SRU 1.2's searchRetrieve parameter table**, which is
#: `version`, `operation`, `query`, `startRecord`, `maximumRecords`,
#: `recordPacking`, `recordSchema`, `recordXPath`, `resultSetTTL`, `sortKeys`,
#: `stylesheet` and `extraRequestData`. Seven of those this server implements;
#: four are here; `extraRequestData` is the `x-` extension mechanism and is not
#: a parameter a client sends by that name. Naming the list is the point: a
#: table whose completeness is asserted rather than sourced is a claim nobody
#: can check, and `recordXPath` was missing from this one until it was.
_DECLINED_PARAMETERS: Final = {
    "sortKeys": Diagnostic.SORT_NOT_SUPPORTED,
    "stylesheet": Diagnostic.STYLESHEETS_NOT_SUPPORTED,
    "resultSetTTL": Diagnostic.RESULT_SETS_NOT_SUPPORTED,
    "recordXPath": Diagnostic.XPATH_RETRIEVAL_UNSUPPORTED,
}

#: The SRU versions this server answers to, and the one it assumes.
#:
#: **`version` is mandatory in SRU 1.1 and 1.2 and this server defaults it
#: anyway.** A strict reading answers diagnostic 7 to a request it could serve
#: perfectly well, and clients omit it. What is not relaxed is the value: 2.0
#: renamed `recordPacking` to `recordXMLEscaping` and changed the response
#: element names, so answering a 2.0 client with a 1.2 document would be worse
#: than refusing it.
SUPPORTED_VERSIONS: Final = ("1.1", "1.2")
DEFAULT_VERSION: Final = "1.2"

#: What `recordSchema` may say. MARCXML and nothing else.
MARCXML_SCHEMA: Final = "info:srw/schema/1/marcxml-v1.1"
SCHEMA_NAMES: Final = frozenset({"marcxml", MARCXML_SCHEMA})


@dataclass(frozen=True, slots=True)
class Server:
    """What `explain` has to say about where this server is.

    Supplied by the caller rather than read from configuration, because the only
    honest answer is the address the request arrived at and this module has no
    request. The router derives it and `_safe_host` bounds it: the host comes
    from a header the client sets, so it is echoed back to the client that sent
    it and to nobody else, and it is never used to build a request.
    """

    host: str
    port: int
    database: str


@dataclass(frozen=True, slots=True)
class _Request:
    """One SRU request, validated."""

    operation: str
    version: str
    query: str
    start_record: int
    maximum_records: int


def _single(values: Sequence[str], name: str) -> str:
    """One value for a parameter, or a refusal that it was sent twice.

    **Repeated parameters are refused rather than resolved**, and `targets.py`
    records why from the other side: a server that takes the first and a server
    that takes the last disagree about what was asked, and the client cannot
    tell which it got. There is no answer here that is right for both.
    """
    if len(values) > 1:
        raise SruError(
            Diagnostic.UNSUPPORTED_PARAMETER_VALUE, f"{name} was sent twice"
        )
    return values[0]


def _bounded_int(value: str, name: str, *, minimum: int) -> int:
    """A parameter as an integer inside the range this catalogue can hold.

    `int()` is bounded at one end already: CPython refuses to convert a string
    of more than 4,300 digits, which arrives here as the `ValueError` any other
    rubbish does. **That bound is far too high to be the one that matters**, and
    the window it leaves open is `2**63` to `10**4300`, where the value parses,
    reaches SQLite and raises `OverflowError` from the driver: not an
    `SruError`, so a 500. `startRecord` was the sharp case, because
    `_search_response` runs `page()` with `start_record - 1` **before** the
    range check that would have caught it. See `SQLITE_MAX_INTEGER`.

    **`maximumRecords` is clamped within this ceiling and refused above it**,
    which is a behaviour change worth naming: a value above `2**63` used to be
    clamped to `MAX_RECORDS` and is now diagnostic 6. Nothing a client sends is
    in that window, and one rule at one place is worth more than an exemption
    for the one caller whose value happens not to reach the database.
    """
    try:
        number = int(value)
    except ValueError:
        raise SruError(
            Diagnostic.UNSUPPORTED_PARAMETER_VALUE, f"{name} is not a number"
        ) from None
    if not minimum <= number <= SQLITE_MAX_INTEGER:
        raise SruError(
            Diagnostic.UNSUPPORTED_PARAMETER_VALUE,
            f"{name} is outside {minimum} to {SQLITE_MAX_INTEGER}",
        )
    return number


def _read_request(query_string: str) -> _Request:
    """The query string as a validated request, or the diagnostic for why not."""
    parameters = parse_qs(query_string, keep_blank_values=True)

    # **An absent `operation` is `searchRetrieve` when a `query` came with it,
    # and `explain` otherwise.** That is SRU 2.0's rule applied to 1.2, where the
    # parameter is nominally mandatory. Clients omit it, and a request carrying a
    # query and nothing else has said what it wants; answering it with an explain
    # document, or with diagnostic 7, is a refusal nobody learns anything from.
    operation = (
        _single(parameters["operation"], "operation")
        if "operation" in parameters
        else ("searchRetrieve" if "query" in parameters else "explain")
    )
    if operation not in ("explain", "searchRetrieve"):
        raise SruError(Diagnostic.UNSUPPORTED_OPERATION, _safe(operation))

    allowed = (
        _SEARCH_PARAMETERS if operation == "searchRetrieve" else _EXPLAIN_PARAMETERS
    )
    for name in parameters:
        if name.startswith("x-"):
            continue
        if name not in allowed:
            raise SruError(
                _DECLINED_PARAMETERS.get(name, Diagnostic.UNSUPPORTED_PARAMETER),
                _safe(name),
            )

    version = (
        _single(parameters["version"], "version")
        if "version" in parameters
        else DEFAULT_VERSION
    )
    if version not in SUPPORTED_VERSIONS:
        raise SruError(Diagnostic.UNSUPPORTED_VERSION, _safe(version))

    if "recordPacking" in parameters:
        packing = _single(parameters["recordPacking"], "recordPacking")
        if packing != "xml":
            raise SruError(
                Diagnostic.UNSUPPORTED_XML_ESCAPING_VALUE,
                f"recordPacking={_safe(packing)}",
            )

    if operation == "explain":
        return _Request("explain", version, "", 1, 0)

    if "recordSchema" in parameters:
        schema = _single(parameters["recordSchema"], "recordSchema")
        if schema not in SCHEMA_NAMES:
            raise SruError(Diagnostic.UNKNOWN_SCHEMA_FOR_RETRIEVAL, _safe(schema))

    if "query" not in parameters:
        raise SruError(Diagnostic.MANDATORY_PARAMETER_NOT_SUPPLIED, "query")
    query = _single(parameters["query"], "query")
    if not query.strip():
        raise SruError(Diagnostic.MANDATORY_PARAMETER_NOT_SUPPLIED, "query")

    start = (
        _bounded_int(_single(parameters["startRecord"], "startRecord"), "startRecord", minimum=1)
        if "startRecord" in parameters
        else 1
    )
    wanted = (
        _bounded_int(
            _single(parameters["maximumRecords"], "maximumRecords"),
            "maximumRecords",
            minimum=0,
        )
        if "maximumRecords" in parameters
        else DEFAULT_RECORDS
    )
    # **Clamped, not refused.** A client asking for a thousand records gets
    # fifty and a `numberOfRecords` telling it how many there were, which is how
    # SRU paging works. Refusing would make a reasonable client's first request
    # fail for a reason it has no way to have known.
    return _Request("searchRetrieve", version, query, start, min(wanted, MAX_RECORDS))


# ── The responses ────────────────────────────────────────────────────────────

#: The SRU response namespace, on the root element of every response.
SRW_NAMESPACE: Final = "http://www.loc.gov/zing/srw/"

#: The diagnostic namespace. A different one, and both are needed: a diagnostic
#: is a document from another schema embedded in this one.
DIAGNOSTIC_NAMESPACE: Final = "info:srw/xmlns/1/diagnostic-v1.1"

#: The ZeeRex schema an explain record is written in.
EXPLAIN_NAMESPACE: Final = "http://explain.z3950.org/dtd/2.0/"

#: What this database calls itself in `explain`.
#:
#: The application's name and nothing about the deployment. A library that wants
#: its own name here wants a setting, and there is not one: see
#: `enums.SettingKey`.
DATABASE_TITLE: Final = "Endpaper"

#: The media type every response carries.
#:
#: `application/xml` rather than `text/xml`: they differ in how a charset is
#: defaulted, and the explicit one is the one that cannot be got wrong.
MEDIA_TYPE: Final = "application/xml; charset=utf-8"


def _element(
    parent: ElementTree.Element, tag: str, text: str | None = None
) -> ElementTree.Element:
    child = ElementTree.SubElement(parent, tag)
    if text is not None:
        child.text = text
    return child


def _serialise(root: ElementTree.Element) -> str:
    """One response as a document.

    Namespaces are plain `xmlns` attributes rather than qualified tags, which is
    what `marc.write` does and for the same reason: a MARC record built by
    `marc.py` carries unqualified tags, so appending it into a tree whose
    elements are qualified would silently put every MARC element into the SRU
    namespace.
    """
    return ElementTree.tostring(root, encoding="unicode", xml_declaration=True)


def _diagnostic_response(error: SruError, version: str) -> str:
    """A refusal, as the specification wants it: a 200 with a diagnostic in it."""
    root = ElementTree.Element("searchRetrieveResponse", {"xmlns": SRW_NAMESPACE})
    _element(root, "version", version)
    _element(root, "numberOfRecords", "0")
    diagnostics = _element(root, "diagnostics")
    diagnostic = ElementTree.SubElement(
        diagnostics, "diagnostic", {"xmlns": DIAGNOSTIC_NAMESPACE}
    )
    _element(diagnostic, "uri", f"{DIAGNOSTIC_URI}{error.diagnostic.value}")
    if error.details:
        _element(diagnostic, "details", error.details)
    _element(diagnostic, "message", error.diagnostic.name.replace("_", " ").lower())
    return _serialise(root)


def _explain_response(version: str, server: Server) -> str:
    """What this server holds and how to ask it, generated from `INDEXES`.

    **Not a fixed document.** The ticket's requirement is that explain reports
    the indexes that are actually implemented, and the only way to keep that
    true through a later edit is to build it from the same table the compiler
    reads.
    """
    root = ElementTree.Element("explainResponse", {"xmlns": SRW_NAMESPACE})
    _element(root, "version", version)
    record = _element(root, "record")
    _element(record, "recordSchema", EXPLAIN_NAMESPACE)
    _element(record, "recordPacking", "xml")
    data = _element(record, "recordData")

    explain = ElementTree.SubElement(data, "explain", {"xmlns": EXPLAIN_NAMESPACE})
    info = _element(explain, "serverInfo")
    info.set("protocol", "SRU")
    info.set("version", version)
    _element(info, "host", server.host)
    _element(info, "port", str(server.port))
    _element(info, "database", server.database)

    database = _element(explain, "databaseInfo")
    _element(database, "title", DATABASE_TITLE)
    _element(
        database,
        "description",
        "The published catalogue. Private and deleted records are not served.",
    )

    indexes = _element(explain, "indexInfo")
    for prefix, identifier in CONTEXT_SETS.items():
        if any(index.context_set == prefix for index in INDEXES):
            ElementTree.SubElement(
                indexes, "set", {"identifier": identifier, "name": prefix}
            )
    for index in INDEXES:
        element = ElementTree.SubElement(
            indexes, "index", {"search": "true", "scan": "false", "sort": "false"}
        )
        _element(element, "title", index.title)
        mapping = _element(element, "map")
        name = _element(mapping, "name", index.name)
        name.set("set", index.context_set)
        configuration = _element(element, "configInfo")
        for relation in index.relations:
            _element(configuration, "supports", relation).set("type", "relation")

    schemas = _element(explain, "schemaInfo")
    schema = ElementTree.SubElement(
        schemas,
        "schema",
        {"identifier": MARCXML_SCHEMA, "name": "marcxml", "sort": "false"},
    )
    _element(schema, "title", "MARC21 in XML")

    configuration = _element(explain, "configInfo")
    _element(configuration, "default", str(DEFAULT_RECORDS)).set(
        "type", "numberOfRecords"
    )
    _element(configuration, "setting", str(MAX_RECORDS)).set("type", "maximumRecords")
    for feature in ("and", "or", "not"):
        _element(configuration, "supports", feature).set("type", "booleanModifier")
    _element(configuration, "supports", "*").set("type", "maskingCharacter")
    _element(configuration, "supports", "?").set("type", "maskingCharacter")
    return _serialise(root)


def _search_response(request: _Request, db: Session) -> str:
    """One `searchRetrieve`, from the parse to the records.

    The shelf is `seen_by_the_public`, unconditionally and with no argument that
    could change it. Everything the query says is a further narrowing on top of
    that, so an index added tomorrow narrows the public shelf rather than
    reaching past it: that is the property
    `tests/test_sru.py::TestNoIndexReachesAPrivateBook` asserts index by index,
    because one unfiltered index is the whole leak.
    """
    predicate = criteria(parse(request.query))
    # **`page`, never `all` and a Python slice.** The slice reads the whole
    # matching shelf into memory and then throws away all but ten rows of it,
    # which on a catalogue of any size is a request a stranger can make cheaply
    # and this server answers expensively. `page` puts the OFFSET and LIMIT in
    # the statement and returns the count from the same narrowing.
    #
    # `Loading.PUBLISHED` also fetches tags, which no MARC field carries. That is
    # one statement per response for nothing, and the alternative is a member of
    # `Loading` that fetches classifications alone, which is a change to
    # `shelf.py` rather than to this module.
    books, total = (
        Shelf.seen_by_the_public(db)
        .where(predicate)
        .page(
            request.start_record - 1,
            request.maximum_records,
            *order_for(BookSort.TITLE_ASC),
            load=Loading.PUBLISHED,
        )
    )
    # **After the query rather than before it**, so the count is the one the
    # response reports rather than a second count that could disagree with it.
    # A `startRecord` past the end is a client paging error and the
    # specification has a diagnostic for it; `startRecord` inside an empty
    # result set is not an error, because there was nothing to be past.
    if total and request.start_record > total:
        raise SruError(
            Diagnostic.FIRST_RECORD_OUT_OF_RANGE, f"{total} records matched"
        )

    root = ElementTree.Element("searchRetrieveResponse", {"xmlns": SRW_NAMESPACE})
    _element(root, "version", request.version)
    _element(root, "numberOfRecords", str(total))
    if books:
        records = _element(root, "records")
        for offset, book in enumerate(books):
            record = _element(records, "record")
            _element(record, "recordSchema", MARCXML_SCHEMA)
            _element(record, "recordPacking", "xml")
            _element(record, "recordData").append(marc.record_element(book))
            _element(record, "recordPosition", str(request.start_record + offset))
    following = request.start_record + len(books)
    if books and following <= total:
        _element(root, "nextRecordPosition", str(following))
    return _serialise(root)


def respond(query_string: str, db: Session, server: Server) -> str:
    """One SRU request as one XML document. The seam the tests drive.

    A query string rather than a parsed mapping, because the parameters are half
    the protocol: whether `operation` was sent twice, whether an unknown one was
    sent at all, and what a blank one means are all questions a mapping has
    already answered.

    **Every refusal that is this module's returns from here as a 200 with a
    diagnostic in it.** An `SruError` raised anywhere below is caught here, so
    there is no path from a hostile query to a traceback, and no path to a
    status code an SRU client does not expect.
    """
    version = DEFAULT_VERSION
    try:
        request = _read_request(query_string)
        version = request.version
        if request.operation == "explain":
            return _explain_response(version, server)
        return _search_response(request, db)
    except SruError as error:
        return _diagnostic_response(error, version)
