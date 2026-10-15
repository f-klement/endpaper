"""A catalogue's online link on a Book, as a response gives it. Read only.

`models.OnlineLink` carries the reasoning: an `856` a MARC import kept, never a
member's file reference and never fetched. No request model: the MARC import
is the only writer, and the one correction is a delete.
"""

from pydantic import BaseModel

from enums import LinkRelationship


class OnlineLinkOut(BaseModel):
    """The URL, the link text the record gave, and what the link is to the Book.

    A fact about the object as a catalogue record, so it is visible exactly
    when the Book is: `PublicBookOut` carries the same three fields as
    `schemas.public.PublicOnlineLinkOut`. The client renders `url` only through
    `safeHref`.
    """

    model_config = {"from_attributes": True}

    #: What the delete route is addressed by: `BookIdentifierOut`'s reason.
    id: int
    url: str
    label: str | None = None
    relation: LinkRelationship | None = None
