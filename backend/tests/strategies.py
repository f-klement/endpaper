"""Generators shared by more than one property based test.

A strategy lives here when two test files draw from it, and stays in its own
file otherwise. A shared module of generators nobody shares is a second place
to look for a fact that already has one home. `answer_of`, the one instrument
every property at a byte door reads, is here for the same reason.

**Every generator here is derived from the rule it is about, never from a list
of the ways that rule can be broken.** A hand written sweep is a claim about
its own bounds and nothing in it says so: one in this tree swept
`range(0x11000)` and read as though it covered Unicode, which is a sixteenth of
the codepoints. `hypothesis.strategies.characters` takes the Unicode category
itself, so the class is named by what it is rather than by the members somebody
could think of.

**A property is only a claim about what its generator can reach**, which is why
`witness` exists and why every property about a hostile class of input carries
one. Weaken a generator to a strategy that cannot produce the class and the
property still passes, having tested nothing: that is the failure these tests
were written against, so it is the one thing they are required to detect about
themselves.
"""

import ast
import encodings
import encodings.aliases
import inspect
import logging
import pkgutil
import string
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final
from xml.sax.saxutils import escape, quoteattr

from hypothesis import HealthCheck, Phase, find, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample, Unsatisfiable
from hypothesis.strategies import SearchStrategy

import marc
import marc_fields

#: The Unicode categories that mean "invisible", as categories rather than as
#: characters.
#:
#: `Cc` is the 65 control characters, `Cf` the format ones: SOFT HYPHEN, ZERO
#: WIDTH SPACE, the byte order mark and the bidirectional controls. Both schema
#: validators refuse exactly this pair, each after a narrower rule spelled as a
#: comparison reached the 24 ASCII controls and admitted the other 72
#: codepoints.
#:
#: **Written here rather than imported from either validator.** A test that
#: reads the module's own set agrees with it by construction, so it cannot
#: notice the set shrinking, which is the edit the categories exist to survive.
INVISIBLE_CATEGORIES: Final = ("Cc", "Cf")

#: What a witness search may spend before it reports the class unreachable.
#:
#: Deliberately not the active profile's budget. A profile dropped to one
#: example would otherwise make every witness vanish and every generator look
#: weakened, which is a second alarm for something the budget guard already
#: reports precisely.
_WITNESS_EXAMPLES: Final = 2_000

#: **Generation only, and no shrinking.** `find` shrinks what it finds to the
#: smallest value satisfying the predicate, which costs far more than the
#: search did and buys nothing here: the question is whether the class is
#: reachable at all, and the answer is the first hit. Measured on the disc
#: wording witness in `tests/test_bibliographic.py`, the two differ by two
#: orders of magnitude and find the same class.
_WITNESS_SETTINGS: Final = settings(
    max_examples=_WITNESS_EXAMPLES,
    phases=[Phase.generate],
    database=None,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)


def invisible_characters() -> SearchStrategy[str]:
    """One character whose Unicode category is `Cc` or `Cf`."""
    return st.characters(categories=INVISIBLE_CATEGORIES)


def text_around(inner: SearchStrategy[str], *, padding: int = 20) -> SearchStrategy[str]:
    """Arbitrary text with one drawn value somewhere inside it.

    The input that broke each of the recorded incidents was never the hostile
    character alone: it was one hostile character inside a value that otherwise
    looked ordinary, which is what reached a unique index and a filing key. A
    generator that only ever produces the character on its own tests the easy
    half.
    """
    return st.builds(
        lambda before, middle, after: before + middle + after,
        st.text(max_size=padding),
        inner,
        st.text(max_size=padding),
    )


def witness[T](
    strategy: SearchStrategy[T],
    predicate: Callable[[Any], bool],
    *,
    reaches: str,
) -> T:
    """One value the strategy produces that satisfies the predicate.

    **The control that stands beside a property, and the only guard against the
    evasion that matters here.** A property over a generator that cannot produce
    the interesting class is green and empty, and nothing in the suite output
    tells the two apart. Asserting the class is still reachable from the same
    strategy object is what fails loudly when somebody narrows it.

    Raises an `AssertionError` naming the class rather than letting
    hypothesis's own error surface, because the reader of that failure is
    looking at a generator and not at a property.
    """
    try:
        return find(strategy, predicate, settings=_WITNESS_SETTINGS)
    except (NoSuchExample, Unsatisfiable) as error:
        raise AssertionError(
            f"this generator no longer reaches {reaches}, so the property "
            f"beside it is a claim about its own bounds"
        ) from error


# ── Byte doors: draw a spec, build the bytes ──────────────────────────────────
#
# A byte door is a function turning bytes or text somebody else wrote into a
# value of this application; `docs/testing.md`, "Generated input", holds the
# rules. The generators below are shared by the files whose doors read the same
# format, and each builds its bytes from a drawn spec, because raw bytes reached
# nothing past the parse: measured in the design round, 0 of 3,000 draws past the
# MARC door's XML parse.


@dataclass(frozen=True)
class Node:
    """One XML element as a spec: what it is called, carries and contains.

    A spec rather than a string, so a counterexample prints as a structure a
    person can read and a named case rebuilds it through `xml_of`.
    """

    tag: str
    attrs: tuple[tuple[str, str], ...] = ()
    text: str = ""
    children: tuple[Node, ...] = ()
    #: A chain of this many `<x>` elements after the children, each the only
    #: child of the one above. **The structure atom**, carrying no text: an
    #: element nested past what any real document reaches allocates without
    #: producing a character, so no outcome a door answers can see it and an
    #: allocation bound can. A count rather than a chain of nodes, because the
    #: suite pod's stack is about a megabyte and a twenty thousand deep chain
    #: overflowed this module's own builder before it reached a door.
    nest: int = 0
    #: This many empty `<x/>` elements after the nest, side by side. **The
    #: width atom**, the nest's other half: an element costs its builder a node
    #: whatever its depth, and at a size the generators otherwise draw the
    #: allocation floor hides that cost. Drawn wide, it is the positive control
    #: for **the tree builder**: a builder that comes to spend more per element
    #: reds. No reader reads an `<x/>`, so a reader that comes to spend more per
    #: field it reads is outside it, measured: 800 bytes more per MARC
    #: `datafield` passed every arm.
    width: int = 0


def xml_of(node: Node) -> str:
    """A node as XML text. Escaped, so the structure drawn is the one parsed."""
    attrs = "".join(f" {name}={quoteattr(value)}" for name, value in node.attrs)
    inner = escape(node.text) + "".join(xml_of(child) for child in node.children)
    inner += "<x>" * node.nest + "</x>" * node.nest + "<x/>" * node.width
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


#: A nest far past any bound, as one named value rather than a drawn integer.
#:
#: **An atom, so a counterexample prints as this number** rather than as
#: whatever the shrinker settled on, and so the property reaches the class at
#: every seed. Deep enough that its allocation is the input's own size times
#: the per element cost, about forty times, which is the class the depth bound
#: exists to refuse.
FAR_PAST_ANY_DEPTH: Final = 20_000


#: How many siblings the width atom draws, as one named value.
#:
#: **Wide enough that the tree builder's cost per element, not the floor, sets
#: a door's peak.** Measured through `marc.read`, 20,000 empty elements peak near 0.6 of
#: the MARC door's bound, and a builder retaining 100 bytes more per element
#: takes them past it.
WIDE: Final = 20_000


def widths() -> SearchStrategy[int]:
    """How many empty siblings one drawn element carries: none, or `WIDE`."""
    return st.just(0) | st.just(WIDE)


def depths(bound: int) -> SearchStrategy[int]:
    """How deep one drawn nest goes, read against a door's own depth bound.

    Mostly none, then at, around and far past the bound, which is where the
    bound's arithmetic lives. `bound` is the depth the nest itself may reach,
    the door's bound less what the document already spends above it.
    """
    return st.one_of(
        st.just(0),
        st.integers(max(bound - 2, 0), bound + 2),
        st.just(FAR_PAST_ANY_DEPTH),
    )


def xml_characters() -> SearchStrategy[str]:
    """One character XML 1.0 can carry in text.

    **By category, not by list.** `Cs` is excluded because no encoding a
    document is written in carries a lone surrogate, `Cc` because XML refuses
    every C0 control but the three whitespace ones, which are named back in.
    The two noncharacters XML also refuses are the only characters named.
    """
    return st.characters(
        codec="utf-8",
        exclude_categories=("Cs", "Cc"),
        exclude_characters="￾￿",
        include_characters="\t\n\r",
    )


#: What a run of one unit is drawn as: a few thousand, up to past a typical
#: field's column.
#:
#: **A size atom, the frontend's remedy**: a regex or a fold that turns
#: superlinear does so on a run of one character, and hypothesis's default text
#: sizes never draw one long enough to matter.
_RUN: Final = st.integers(1_000, 8_000)


def field_values() -> SearchStrategy[str]:
    """One value a catalogue or a file writes into a field.

    Ordinary text, plus the shapes the readers parse: an ISBN, an extent, a
    year, ISBD punctuation, and a long run of one unit. The units are the ones
    the readers' own patterns are written over: a parenthesis, a space and a
    letter, which is where the BnF publisher rule turned quadratic.
    """
    return st.one_of(
        st.text(xml_characters(), max_size=40),
        st.from_regex(r"97[89][0-9]{10}", fullmatch=True),
        st.from_regex(r"[0-9]{1,4} (p|S|pages)\.?", fullmatch=True),
        st.from_regex(r"[0-9]{4}", fullmatch=True),
        st.sampled_from([" /", " :", " ;", " =", ".", ",", "[", "]"]),
        st.builds(
            lambda before, unit, count, after: before + unit * count + after,
            st.text(xml_characters(), max_size=8),
            st.sampled_from(["(", ")", " ", "a"]),
            _RUN,
            st.text(xml_characters(), max_size=8),
        ),
    )


# ── MARC21, which three byte doors read ───────────────────────────────────────


def _marc_tags() -> list[str]:
    """Every three digit tag the MARC readers name, read off their source.

    **Derived, so a tag a reader starts reading is drawn with no edit here.**
    The upload reader and the two catalogue profiles all read through
    `marc_fields.py`, and `marc.py` reads three of its own.
    """
    found: set[str] = set()
    for module in (marc_fields, marc):
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) == 3
                and node.value.isdigit()
            ):
                found.add(node.value)
    return sorted(found)


MARC_TAGS: Final = _marc_tags()

#: A subfield code is one lower case letter or digit, which is the format's own
#: closed set rather than the codes somebody remembered.
_SUBFIELD_CODES: Final = string.ascii_lowercase + string.digits


def marc_records() -> SearchStrategy[Node]:
    """One MARC21 `record` element, namespaced by the collection around it.

    A leader at its real length or truncated, control fields, and datafields
    over the tags the readers name. A title is drawn often rather than always,
    because a record with no `245 $a` is the reader's one refusal.
    """
    subfield = st.builds(
        lambda code, value: Node("subfield", (("code", code),), value),
        st.sampled_from(_SUBFIELD_CODES),
        field_values(),
    )
    datafield = st.builds(
        lambda tag, ind1, ind2, subfields: Node(
            "datafield",
            (("tag", tag), ("ind1", ind1), ("ind2", ind2)),
            children=tuple(subfields),
        ),
        st.sampled_from(MARC_TAGS),
        st.sampled_from(" 0123456789"),
        st.sampled_from(" 0123456789"),
        st.lists(subfield, max_size=4),
    )
    title = st.builds(
        lambda value: Node(
            "datafield",
            (("tag", "245"), ("ind1", "1"), ("ind2", "0")),
            children=(Node("subfield", (("code", "a"),), value),),
        ),
        field_values(),
    )
    return st.builds(
        lambda leader, titled, fields: Node(
            "record",
            children=(Node("leader", text=leader), *titled, *fields),
        ),
        st.one_of(st.just(marc.LEADER), st.text(xml_characters(), max_size=30)),
        st.lists(title, max_size=1),
        st.lists(datafield, max_size=6),
    )


# ── Encodings, derived from the codec registry ────────────────────────────────


def _text_codecs() -> list[str]:
    """Every codec name this Python resolves to a text encoding.

    **Walked off the `encodings` package and its alias table**, never listed:
    the codecs that decode to a lone surrogate under `errors="replace"`, the
    class behind a catalogue's 500, were found by walking it, and a list would
    have held the four everybody thinks of. A name is kept when it encodes and
    decodes text, which drops the bytes to bytes codecs and the one that refuses
    everything.
    """
    names = {module.name for module in pkgutil.iter_modules(encodings.__path__)}
    names |= set(encodings.aliases.aliases) | set(encodings.aliases.aliases.values())
    kept = []
    for name in sorted(names):
        try:
            "".encode(name)
            b"".decode(name)
        except (LookupError, UnicodeError):
            # `LookupError` is a bytes to bytes codec; `UnicodeError` is
            # `undefined`, the codec that refuses everything by design.
            continue
        kept.append(name)
    return kept


TEXT_CODECS: Final = _text_codecs()


def _decodes_to_a_lone_surrogate(codec: str) -> bool:
    """Whether bytes this codec wrote can decode, under `replace`, to a lone one."""
    try:
        written = "a\ud800b".encode(codec)
    except UnicodeError:
        return False
    return any(0xD800 <= ord(character) <= 0xDFFF for character in written.decode(codec, "replace"))


#: The codecs whose decoding can hand a parser a surrogate with no partner,
#: derived from what each one does rather than named.
#:
#: **Weighted in by the generator below, because they are a handful among
#: hundreds.** The first draft of the catalogue property drew uniformly from
#: `TEXT_CODECS`, over text with no surrogate in it, and was green on the tree
#: that let the class out as a 500.
SURROGATE_CODECS: Final = [codec for codec in TEXT_CODECS if _decodes_to_a_lone_surrogate(codec)]


def charsets() -> SearchStrategy[str]:
    """A charset a response may be labelled with: any text codec, often a
    hostile one."""
    return st.one_of(st.sampled_from(TEXT_CODECS), st.sampled_from(SURROGATE_CODECS))


def declared_encodings() -> SearchStrategy[str]:
    """A name an XML declaration may carry: one Python knows, or one it does not.

    The unknown half is drawn from the declaration's own grammar, so it reaches
    the parser rather than a syntax error, and is the class `marc._parsed` let
    out as `LookupError`.
    """
    return st.one_of(
        st.just("UTF-8"),
        st.sampled_from(TEXT_CODECS),
        st.from_regex(r"[A-Za-z][A-Za-z0-9._-]{0,11}", fullmatch=True),
    )


def encoded(text: str, codec: str) -> bytes:
    """Text as the bytes a server writing `codec` sends.

    A character the codec cannot carry becomes a character reference, which is
    how a server writing XML in that encoding spells it, so the document stays
    the one drawn. Where the codec takes no error handler at all, as `idna`
    does not, the bytes are UTF-8 under that label, which is a server
    mislabelling its body, and that is a fair input too. **`surrogatepass`
    there**, because the drawn text may carry a lone surrogate, which plain
    UTF-8 refuses: a draw of `idna` and one surrogate raised inside this
    builder rather than reaching a door.
    """
    try:
        return text.encode(codec, errors="xmlcharrefreplace")
    except UnicodeError:
        return text.encode("utf-8", errors="surrogatepass")


def patched(data: bytes, patches: tuple[tuple[int, int], ...]) -> bytes:
    """`data` with each `(offset, byte)` written over it, offsets wrapped.

    A few single byte patches beside a drawn structure, as the frontend draws
    them: the structure reaches past the parse, the patch reaches the bytes no
    structure spells.
    """
    if not data:
        return data
    out = bytearray(data)
    for offset, value in patches:
        out[offset % len(out)] = value
    return bytes(out)


PATCHES: Final = st.lists(
    st.tuples(st.integers(0, 1 << 20), st.integers(0, 255)), max_size=2
).map(tuple)


# ── The two instruments a property at a byte door reads ───────────────────────


@dataclass(frozen=True)
class Answered[T]:
    """What one call of a byte door did: its answer or its refusal, and its peak.

    `peak` is `tracemalloc`'s traced peak over the call, in bytes, which repeats
    to within a few hundred bytes on one interpreter: the deterministic half of
    what a door costs. Wall clock is not read, and `docs/decisions.md` says why.
    """

    value: T | None
    refusal: Exception | None
    peak: int


def answer_of[T](
    door: Callable[..., T],
    *args: Any,
    answers: type | tuple[type, ...],
    refuses: type[Exception] | None,
) -> Answered[T]:
    """Call a byte door and require its answer or its own declared refusal.

    **Any other exception propagates, and that is the property failing**, with
    hypothesis printing the spec that caused it. `refuses` is None for a door
    that declares it never raises, which is what a decoder declares.

    **The refusal class has to be defined in the module of the callable
    passed.** That refuses the evasion a shared helper invites, naming
    `Exception` or a standard library class the door happens to let out, which
    would turn every escape into an answer. **It is not a construction, and two
    things pass it that are read by eye instead**: a wrapper defined in a test
    beside its own refusal class turns any escape into that refusal, and a
    lambda, a `functools.partial` or a test helper calling a door is refused
    even with the door's own class, because its module is the test's. So a
    property passes the door itself, and a wrapper is reviewed.

    **The door is called once before the traced call, and that call is not
    counted.** A first call fills caches the process keeps: a codec's module
    imported for a declared encoding, and `linecache`'s copy of a source file
    when a lookup logs a traceback. A 442 byte catalogue response crossed the
    floor at 282,240 bytes in the suite on the call that first logged one, and
    in one process here a response the parser refuses peaked at 623,928 bytes on
    its first call and 56,171 on its second: a peak about the process rather
    than the input. The traced call is the second, so its peak is this input's
    cost to a warm process. **A door keeping state per input reads as free**:
    a memo on its parse, filled by the first call, leaves the second nothing to
    allocate, and a builder plant that reds all three XML properties passes
    with one, measured. Tracing the first call too is what would see it.

    **Logging is off for both calls.** A one past the bound catalogue response,
    refused and logged with its traceback, still peaked at 714,919 bytes on the
    suite's second call and passed on hypothesis's replay. The likely mechanism,
    not traced further, is the suite's capturing handler holding every record a
    run has logged in a list that reallocates in whichever call crosses its
    capacity. **On the three XML byte doors here** logging is a constant: their
    logged arguments are bounded, and a refused lookup's traceback formatting
    measured about 32 KB whatever the response's size, under the floor. A door
    that logged part of its input would pay that per byte, and this helper
    would hide it.
    """
    if refuses is not None and refuses.__module__ != door.__module__:
        raise AssertionError(
            f"{refuses.__qualname__} is defined in {refuses.__module__}, not in "
            f"{door.__module__}, so it is not a refusal that door declares"
        )
    if tracemalloc.is_tracing():
        raise AssertionError("something else is tracing allocations, so this peak would be theirs")
    was_disabled = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        try:
            door(*args)
        except Exception as error:
            if refuses is None or not isinstance(error, refuses):
                raise
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            try:
                value = door(*args)
            except Exception as error:
                if refuses is None or not isinstance(error, refuses):
                    raise
                return Answered(None, error, tracemalloc.get_traced_memory()[1])
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    finally:
        logging.disable(was_disabled)
    assert isinstance(value, answers), f"{door.__qualname__} answered {type(value)!r}"
    return Answered(value, None, peak)
