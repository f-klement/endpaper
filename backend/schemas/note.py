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
    created_at: datetime
    updated_at: datetime
    author: UserOut | None = None
    model_config = {"from_attributes": True}
