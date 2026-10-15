"""What a member's own screens are told about their KOReader progress sync.

The device protocol is not here: it is KOReader's, answered by hand in
`routers/kosync.py`, and its bodies are not this application's to describe.
"""

from pydantic import BaseModel

from schemas.common import UtcDateTime


class KosyncAccountOut(BaseModel):
    """Whether this member can sign a device in, and as whom."""

    #: What a device sends as its username: the member's own.
    username: str
    #: Whether a sync password is set. The password itself is never served.
    has_password: bool
    #: When the current one was minted, or null.
    password_set_at: UtcDateTime | None


class KosyncPasswordOut(BaseModel):
    """A sync password just minted, served this once and never again."""

    username: str
    password: str


class KosyncDocumentOut(BaseModel):
    """One document a device has reported, as its owner sees it."""

    #: The name the device gives the file. Also this row's address.
    document: str
    #: 0 to 1, as the device sent it.
    percentage: float
    device: str
    #: When this server stored the last push.
    pushed_at: UtcDateTime
    #: What the device said the file is, when the member turned that on in
    #: KOReader. All three are null otherwise.
    title: str | None
    authors: str | None
    filename: str | None
    #: The Book it is linked to, or null while it waits in the inbox.
    book_id: int | None
