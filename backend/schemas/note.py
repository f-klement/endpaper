from datetime import datetime

from pydantic import BaseModel, Field

from schemas.user import UserOut

MAX_NOTE_LENGTH = 10_000


class NoteCreate(BaseModel):
    # min_length=1 is a real change: an empty note used to be accepted and then
    # rendered as a blank card nobody could tell apart from a rendering bug.
    content: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)


class NoteOut(BaseModel):
    id: int
    book_id: int
    user_id: int
    content: str
    #: True when this note is the author's alone, which is what an imported
    #: review is. Read only: it is absent from `NoteCreate`, which `edit_note`
    #: also takes, so a client that omitted the field would un-private the row
    #: on every edit.
    #:
    #: **On the wire, and no screen renders it yet.** It is what a member would
    #: need to tell which of their notes the rest of the library cannot see, and
    #: until something draws it they cannot: the field is here so the marker is
    #: not a second schema change behind the badge that shows it.
    #:
    #: Nothing leaks by reporting it: a note the caller may not read is not in
    #: the response at all, so the only `true` anybody sees is their own.
    is_private: bool
    created_at: datetime
    updated_at: datetime
    author: UserOut | None = None
    model_config = {"from_attributes": True}
