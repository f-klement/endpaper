"""What a deadline is, and the two questions every holder of one asks.

A deadline here is an **absolute `time.monotonic()` timestamp**: not a
duration, not wall clock. `None` means the callee's own budget applies.

Measured before this module existed: `covers` and `z3950` had each grown a
private helper for the second question below, and `z3950` and `fetch` spelled
it inline as well. Four sites, two spellings of the clock (`monotonic()` and
`time.monotonic()`), and one arithmetic in four places is four chances for the
clock choice to drift.

**A caller that binds the result names it `remaining`**, because `left` is the
function.

## Two functions, and deliberately no third

Composition is not here. `z3950.association` refuses a deadline further away
than its own `TIMEOUT_SECONDS`: a **ceiling**, and its docstring says why a
caller may only ask for less. `opds.sync` caps each page at the smaller of the
sync's end and one request's timeout: a **clamp** on a running total. A single
narrowing door expresses the clamp and cannot express the ceiling, so a caller
would satisfy the ceiling by construction, the refusal behind it would become
dead code, and the next reader would delete it with nothing going red.
`tests/test_deadline.py::TestTheDoorIsTwoFunctionsWide` fails on a third
public name **and on a further parameter to either of these two**, which is
where that argument gets re-read: a door widens sideways as easily as it grows
a name, and `in_(seconds, ceiling=...)` is that same narrowing under a name
already on the list.

Expiry is not here either. `authority` raises `AuthorityUnavailable`, `fetch`
and `z3950` raise `DeadlineExceeded`, and `opds` returns what it has with
`truncated=True`: an OPDS sync that runs out of time is not an error. One
raising reader cannot serve all three, so `left` returns the figure and each
module keeps its own answer to "the budget is spent".

Budgets stay with the module that owns them too: `in_` takes the figure rather
than holding one.
"""

import time
from typing import overload


def in_(seconds: float) -> float:
    """A deadline that many seconds from now."""
    return time.monotonic() + seconds


@overload
def left(deadline: float) -> float: ...


@overload
def left(deadline: None) -> None: ...


def left(deadline: float | None) -> float | None:
    """Seconds until the deadline, negative past it, `None` for no budget.

    **A figure rather than a boolean**, which is what lets a caller cap one
    request at what is actually left: a budget of four seconds is four seconds
    and not four plus one timeout. A caller treats `<= 0` as spent.

    Overloaded so that a holder of a definite deadline (`z3950`'s association
    has one for its whole life) gets a `float` and does not narrow a `None` it
    cannot receive.
    """
    return None if deadline is None else deadline - time.monotonic()
