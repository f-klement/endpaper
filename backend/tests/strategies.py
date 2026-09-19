"""Generators shared by more than one property based test.

A strategy lives here when two test files draw from it, and stays in its own
file otherwise. A shared module of generators nobody shares is a second place
to look for a fact that already has one home.

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

from collections.abc import Callable
from typing import Any, Final

from hypothesis import HealthCheck, Phase, find, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample, Unsatisfiable
from hypothesis.strategies import SearchStrategy

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
