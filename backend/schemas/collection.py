from pydantic import BaseModel, Field, field_validator

from models import COLLECTION_NAME_MAX
from schemas.common import RowIdField, one_line_without_invisible_characters


class CollectionOut(BaseModel):
    """A named part of the shelf, and how much of it the caller can see.

    **Both fields are the caller's view, and the row set is too.** `book_count`
    is filtered by `visible_to`, like every other count this API serves; an
    unfiltered one would announce that somebody's private books exist and how
    many. The rows this appears in are filtered by the same question one level
    out, so a collection nothing the caller may see is filed in is absent
    rather than present with a zero. `shelving.Shelving` decides both.

    One consequence for a reader of the wire: a `book_count` of 0 means the
    collection is empty, or holds only books the caller can see in the trash.
    It no longer means "or holds books you cannot see".
    """

    id: int
    name: str
    book_count: int = Field(default=0, ge=0)
    model_config = {"from_attributes": True}


class CollectionCreate(BaseModel):
    """A collection the library is inventing.

    Any member may make one. A collection is shelving rather than permission,
    so there is nothing here to restrict to an admin.
    """

    name: str = Field(min_length=1, max_length=COLLECTION_NAME_MAX)

    @field_validator("name")
    @classmethod
    def tidy(cls, value: str) -> str:
        """One line, and a name that normalises to nothing is refused.

        A name of only spaces passes `min_length` and then renders as an
        invisible heading nobody can pick out of a list, and a name of only
        characters with no width did the same until they went too. The name is
        case-insensitively unique, so an invisible character is also a second
        shelf spelled like the first. `TagCreate.tidy` is the same rule on the
        same argument; both read it from one place now.
        """
        cleaned = one_line_without_invisible_characters(value)
        if not cleaned:
            raise ValueError("A collection needs a name.")
        return cleaned


class CollectionUpdate(CollectionCreate):
    """A rename. The name is the only thing a collection has."""


class CollectionAssign(BaseModel):
    """Which collection a book belongs to, or `null` for none.

    Its own endpoint rather than a field on `BookDetailsUpdate`, so the picker
    can save the moment somebody chooses. An explicit null is how a book is
    taken out of a collection without being put in another one.
    """

    collection_id: RowIdField | None = None
