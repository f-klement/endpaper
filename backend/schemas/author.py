from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from authors import AUTHOR_NAME_MAX, author_key
from models import AUTHOR_KEY_MAX

#: An author key as it arrives from a caller.
#:
#: Bounded for the reason every string field here is: it is compared against
#: keys built from `books.author`, which is 500 characters, so nothing longer
#: can match anything and accepting it only makes a bigger request body to
#: normalise. Not a `RowIdField`, because an author has no row to name, and not
#: an identity either: a key is derived from a name, so a merge retires it with
#: the spelling it came from. A retired one is resolved through the alias rows.
AuthorKeyField = Annotated[str, StringConstraints(min_length=1, max_length=AUTHOR_KEY_MAX)]

#: How many authors one merge may fold at once.
#:
#: A suggestion group is at most a handful, and this is the ceiling on a
#: hand-written request rather than on anything the UI produces. It exists so
#: the alias writer's repointing pass is bounded by a number in this file
#: rather than by how long a list somebody posted.
MAX_MERGE_KEYS = 50


class AuthorMergeOut(BaseModel):
    """A spelling that reached this author through somebody's merge.

    Carries the alias row's id because undoing a merge is deleting that row,
    and the spelling as written because the key it is stored under is
    normalised past the point of being readable ("le guin ursula k").
    """

    alias_id: int
    spelling: str


class AuthorOut(BaseModel):
    """One person, as far as this shelf knows, and what it knows about them.

    `key` is what the book filter and the merge endpoint address an author by,
    and it is derived from `name` rather than being an identity behind it: a
    merge retires the keys it folds, exactly as it retires the spellings. Both
    endpoints therefore accept either, and resolve a retired one through the
    alias rows.

    `book_count` is filtered by `visible_to`, like every count this API serves.
    An unfiltered one would announce that somebody's private books exist and
    how many, on a page every member can read.
    """

    key: str
    name: str
    book_count: int = Field(ge=0)
    #: Every spelling of this name on the shelf, most used first. The one the
    #: display name came from is in here too, unless a merge chose a name that
    #: no book carries.
    spellings: list[str] = Field(default_factory=list)
    #: The spellings folded in by a merge, each with the row that says so.
    #:
    #: **Only the ones this caller can already see.** An alias is a household
    #: wide statement about names, so it is shown like a collection name is;
    #: one whose spelling survives only on somebody else's private book is left
    #: out, because listing it would announce that the book exists.
    merged: list[AuthorMergeOut] = Field(default_factory=list)


class AuthorSuggestionOut(BaseModel):
    """Names that are probably one person, and the rules that said so.

    A suggestion, never a verdict. `reasons` is returned so a reader can tell a
    certainty from a guess: `spelling` is the same name with the spaces moved,
    `initials` is an abbreviated given name, and `fragment` is one name's words
    sitting inside another's, which is what a credit line stored in catalogue
    order splits into.
    """

    keys: list[str]
    names: list[str]
    reasons: list[str]


class AuthorMergeRequest(BaseModel):
    """Fold these spellings into this name.

    `keys` are authors that exist on the shelf. `keep_name` is free text and
    deliberately need not be one of them: a credit line stored as "Le Guin,
    Ursula K." splits into two people, neither of whom is spelled correctly,
    and the repair is to fold both into a name typed by hand. Nothing about
    that edits the book, and deleting the alias rows puts the shelf back.
    """

    keys: Annotated[
        list[AuthorKeyField],
        Field(min_length=1, max_length=MAX_MERGE_KEYS),
    ]
    keep_name: Annotated[str, StringConstraints(min_length=1, max_length=AUTHOR_NAME_MAX)]

    @field_validator("keep_name")
    @classmethod
    def tidy(cls, value: str) -> str:
        """Collapse the whitespace, and refuse a name that normalises to nothing.

        A name of only punctuation passes `min_length` and then has an empty
        key, which no spelling can ever match: the merge would appear to work
        and fold every named author into an author nothing can reach.
        """
        cleaned = " ".join(value.split())
        if not author_key(cleaned):
            raise ValueError("An author needs a name with a letter or a digit in it.")
        return cleaned
