"""What a household's OPDS server looks like over the API.

The credential is never here in either direction beyond the write that sets it:
what comes back is a provenance, a mask and whether the stored envelope can be
opened, which is exactly what the catalogue settings screen is told about a
roster source. See `credentials.CredentialView`.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from enums import CredentialProvenance
from schemas.imports import ImportResultOut

#: Matches `models.OpdsServer.name` and `ck_opds_servers_name`.
MAX_SERVER_NAME = 100

#: Matches `models.OpdsServer.base_url`.
MAX_BASE_URL = 255


class OpdsServerIn(BaseModel):
    """A server an admin is adding, or the two fields of one they are editing.

    **The address is validated here as well as at the route**, and the two are
    not the same check said twice: this bounds the length and the shape a column
    can hold, and `opds.is_fetchable` decides whether this server will open a
    connection to it. The second is the security rule and it runs again before
    every single request, including for the paging links the feed itself writes,
    which never come through this model at all.
    """

    #: **`StringConstraints` rather than `Field` plus a validator**, and the
    #: order is the whole reason. `strip_whitespace` runs **before** the length
    #: check, where an `@field_validator` runs after it: with the validator, a
    #: name of three spaces passed `min_length=1`, stripped to nothing, and was
    #: refused by `ck_opds_servers_name` as a 500 instead of by this model as a
    #: 422. Measured through the route.
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_SERVER_NAME
        ),
    ]
    base_url: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_BASE_URL),
    ]


class OpdsCredentialIn(BaseModel):
    """A login at one household server.

    Both halves are required. `credentials.put` refuses a blank either way and
    refuses a colon in the username, because RFC 7617 forbids one in a Basic
    user-id and this application keeps one representation of the pair.
    """

    username: Annotated[str, Field(min_length=1, max_length=255)]
    password: Annotated[str, Field(min_length=1, max_length=255)]


class OpdsServerOut(BaseModel):
    """One configured server, and never its login.

    `credential_username_preview` is masked by the route, in
    `settings_store.mask`, which is where every other preview in this
    application is masked.
    """

    id: int
    name: str
    base_url: str
    #: Which level supplies this server's login, if any. One field rather than a
    #: flag per level: see `enums.CredentialProvenance`.
    credential_provenance: CredentialProvenance
    credential_username_preview: str
    #: A login is held and this deployment cannot open it. The remedy is on the
    #: encryption key, not on this row.
    credential_unreadable: bool


class OpdsServerSummaryOut(BaseModel):
    """One server as a member may see it: enough to name it and to sync it.

    **Deliberately not `OpdsServerOut` with fields omitted.** The address is the
    configuration an admin owns and `credential_provenance` is about a secret;
    a separate model means neither can be added back by somebody widening a
    response they did not realise a member reads.
    """

    id: int
    name: str


class OpdsSyncOut(ImportResultOut):
    """What one sync did, over the shared import result.

    **The extra fields are what only this route can answer**, and each exists
    because of a question a person actually asks when nothing arrives.

    `entries_not_held` answers "why did my library not come in": an entry counts
    only when it says the member holds the book, so a large number here means
    the address given is a shelf index, or a feed offering titles for sale or
    loan rather than listing what is on the shelf. See `opds.HOLDING_RELS`.

    `truncated` answers "is that all of it": true when a cap or the sync
    deadline stopped the walk before the feed ran out. A sync that stopped early
    has still written what it read, so this is the difference between a complete
    picture and a partial one.
    """

    pages_read: int = Field(ge=0, description="Pages of the feed that were walked")
    entries_not_held: int = Field(
        ge=0,
        description=(
            "Entries passed over because they say nothing about the member "
            "holding the book: a link to another feed, or a title offered for "
            "sale or loan"
        ),
    )
    truncated: bool = Field(
        default=False,
        description="A cap or the deadline stopped the walk before the feed ended",
    )
