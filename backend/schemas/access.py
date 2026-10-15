from pydantic import BaseModel

from enums import AccessStatus
from schemas.common import UtcDateTime
from schemas.user import UserOut


class AccessDecision(BaseModel):
    """The holder's answer to one request: granted, or declined."""

    granted: bool


class AccessRequestOut(BaseModel):
    """One request for access to a digital copy, as its requester or holder reads it.

    `holder` is who the request is addressed to, fixed when it was made. A
    grant shares no file: the copy is handed over outside Endpaper, so this
    names who to ask for it.
    """

    id: int
    book_id: int
    status: AccessStatus
    requested_by: UserOut
    holder: UserOut
    requested_at: UtcDateTime
    decided_by: UserOut | None = None
    decided_at: UtcDateTime | None = None
    model_config = {"from_attributes": True}
