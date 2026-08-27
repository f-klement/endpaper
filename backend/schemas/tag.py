from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from enums import TagCategory, TagKey

MAX_TAG_NAME = 100


def known_key(value: Any) -> TagKey | None:
    """The key as this version understands it, or None.

    `tags.key` is a plain string in the database, so a library moved back to an
    older image can hold a key that version has never heard of. Refusing such a
    row would 500 the whole tag list, which is one response for the whole
    vocabulary and is fetched on nearly every page; forgetting the key costs
    that one tag its translation and nothing else.

    `in` on the enum rather than a membership set: since 3.12 a value that is
    not a member answers False instead of raising, which is exactly the
    behaviour wanted and is why this needs no try.
    """
    return TagKey(value) if value in TagKey else None


#: A tag key as it leaves the API: the enum, or None where this version does not
#: recognise what the column holds.
#:
#: A type rather than a validator per model, because there are two models
#: carrying this field and one rule for it. `TagStat` used to be the plain enum
#: and so **raised** on a key `TagOut` forgot, which is the failure `known_key`
#: exists to prevent, reachable through whichever of the two a page happened to
#: draw. Adding a third model with the key now cannot get it wrong by omission.
KnownTagKey = Annotated[TagKey | None, BeforeValidator(known_key)]


class TagOut(BaseModel):
    id: int
    name: str
    category: TagCategory
    #: Which seeded tag this is, or None for one the library invented or
    #: renamed. The client shows the name in the reader's language by looking
    #: it up on this, and falls back to `name` when it is absent, which is what
    #: leaves an invented tag exactly as it was typed. See `TagKey`.
    key: KnownTagKey = None
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
