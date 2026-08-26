from pydantic import BaseModel, Field, field_validator

from enums import TagCategory

MAX_TAG_NAME = 100


class TagOut(BaseModel):
    id: int
    name: str
    category: TagCategory
    #: Whether `seed_tags()` owns it. The UI uses this to decide whether to
    #: offer a delete, since deleting a seeded tag would only bring it back at
    #: the next restart.
    is_predefined: bool = False
    #: How many books carry it. Present so the confirmation can say what is
    #: about to happen: "delete this tag" and "take this off 214 books" are
    #: different decisions and only one of them is obvious from the name.
    book_count: int = 0
    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    """A tag the library is inventing.

    No category is accepted. Everything created this way is CUSTOM: asking
    somebody to file "Holiday reads" under type, genre or age is asking a
    question with no right answer, and a wrong answer scatters their tag
    through a curated list.
    """

    name: str = Field(min_length=1, max_length=MAX_TAG_NAME)

    @field_validator("name")
    @classmethod
    def tidy(cls, value: str) -> str:
        """Collapse the whitespace somebody pasted in.

        A name of only spaces passes `min_length` and then renders as an
        invisible tag nobody can select or find again.
        """
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("A tag needs a name.")
        return cleaned
