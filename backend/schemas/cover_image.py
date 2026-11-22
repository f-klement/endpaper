"""A further image of a Book, as a response gives it. Read only.

`models.CoverImage` carries the reasoning. No request model: an image arrives
as a multipart upload, and the other two writes are addressed by `id` alone.
"""

from pydantic import BaseModel


class CoverImageOut(BaseModel):
    """Where one further image of a Book is served, and what addresses it."""

    model_config = {"from_attributes": True}

    #: What the delete route and the shelf route are addressed by.
    id: int
    #: Served behind the Book's read rule, like `cover_url` when it is local.
    url: str
