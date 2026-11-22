"""The curated catalogue registry and the source test action, as the settings screen reads them."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

import isbn
from enums import Disposition, RegisteredCatalogue
from models import ISBN_MAX


class SourceTestIn(BaseModel):
    """What to ask a source when an admin tests it.

    **No `source` field**: the source is the path, for `SourceCredentialIn`'s
    reason. `isbn` is optional: left out, a registry entry is asked its own
    evidence ISBN and a seeded source `catalogue_access.DEFAULT_TEST_ISBN`.
    """

    isbn: str | None = Field(default=None, max_length=ISBN_MAX)

    @field_validator("isbn")
    @classmethod
    def _an_isbn(cls, value: str | None) -> str | None:
        # Normalised here, so the door is only ever handed the form a scan
        # hands it, and a string that is no ISBN never leaves the process.
        if value is None:
            return None
        parsed = isbn.parse(value)
        if parsed is None:
            raise ValueError("Not a valid ISBN.")
        return parsed


class ProbeEvidenceOut(BaseModel):
    """One probe of one catalogue: when, what was asked, and how it answered.

    **A disposition and never what came back**, and the same shape a shipped
    registry entry's evidence has: `registry.Evidence`.
    """

    probed_on: date
    isbn: str
    disposition: Disposition


class RegistryEntryOut(BaseModel):
    """One catalogue the registry ships, and whether this library picked it."""

    source: RegisteredCatalogue
    name: str
    #: ISO 3166-1 alpha-2.
    country: str
    kind: Literal["national", "union"]
    #: The host a test and a picked entry's lookup reach, shown so an admin sees where it goes.
    host: str
    picked: bool
    evidence: ProbeEvidenceOut


class CatalogueRegistryOut(BaseModel):
    """The whole registry this build ships, with its provenance and its age."""

    #: The directories the candidates were found in.
    listed_by: list[str]
    #: When the snapshot's evidence was taken.
    taken_on: date
    #: Whether that evidence is older than the registry trusts it.
    aged: bool
    entries: list[RegistryEntryOut]
