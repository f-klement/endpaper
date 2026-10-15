"""What a member's own screens send and are told about their Readwise pull.

The token goes in once and never comes back out: no schema here carries it on
the way out, so no response can.
"""

from pydantic import BaseModel, Field

from enums import ReadwiseOutcome
from models import READWISE_TOKEN_MAX
from schemas.common import UtcDateTime

#: How many waiting books one answer lists. The count beside it is exact.
WAITING_SHOWN = 100


class ReadwiseTokenIn(BaseModel):
    """The access token from `readwise.io/access_token`.

    **Letters, digits, `_` and `-` only**, which every token Readwise issues
    is: the value goes into a request header, and a character outside that set
    is either a paste error or a header injection.
    """

    token: str = Field(min_length=8, max_length=READWISE_TOKEN_MAX, pattern=r"^[A-Za-z0-9_-]+$")


class ReadwiseWaitingOut(BaseModel):
    """A Readwise book no Book here matched, so its highlights wait."""

    title: str
    author: str | None


class ReadwiseAccountOut(BaseModel):
    """Whether this member has a token saved, and how the last pull went."""

    has_token: bool
    #: When the token was saved, or null.
    token_set_at: UtcDateTime | None
    #: When a pull last started, or null before the first.
    last_run_at: UtcDateTime | None
    last_outcome: ReadwiseOutcome | None
    #: How many Readwise books match no Book here, exactly.
    waiting_count: int
    #: The first `WAITING_SHOWN` of them, by title.
    waiting: list[ReadwiseWaitingOut]


class ReadwiseSyncOut(BaseModel):
    """What one pull did, over the highlights it was sent."""

    outcome: ReadwiseOutcome
    created: int
    updated: int
    unchanged: int
    #: Rows removed because Readwise reported the highlight or its book deleted.
    deleted: int
    #: Highlights Readwise sent that were not stored: no text, past the length
    #: a highlight may have, or deleted here by the member.
    skipped: int
    #: Books matching no Book here after this pull.
    waiting_count: int
