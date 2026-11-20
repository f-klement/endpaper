"""The local copy of each subject vocabulary, as the settings screen reads it."""

from pydantic import BaseModel

from enums import VocabularyLoadPhase
from schemas.common import UtcDateTime


class VocabularyProgressOut(BaseModel):
    """A load under way, or the one that failed last.

    `done` and `total` count bytes while `fetching` and entries while
    `loading`; `total` is null where the source did not say how many.
    """

    phase: VocabularyLoadPhase
    done: int
    total: int | None
    error: str | None


class VocabularyOut(BaseModel):
    """One declared subject vocabulary and what is loaded of it."""

    #: The code a heading's `scheme` carries, `gnd` or `lcsh`.
    scheme: str
    name: str
    #: The licence the declaration names, or null where it names none.
    licence: str | None
    #: Whether that licence permits a local copy. A vocabulary that may only be
    #: queried is never downloaded.
    copyable: bool
    #: Entries in the copy lookups read, or null before the first load finished.
    entries: int | None
    #: When this application fetched that copy.
    fetched_at: UtcDateTime | None
    #: The source's own date for the release, where it gave one.
    released: UtcDateTime | None
    progress: VocabularyProgressOut | None
