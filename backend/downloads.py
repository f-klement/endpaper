"""What makes a response a download rather than a page.

One thing, said once for the two routes that send a file: the
`Content-Disposition` header. They built its value with the same f-string each
and neither declared it, so the same fact lived at two sites and in neither
document.

**The declaration is not decoration here, it is the property a guard selects
on.** `frontend/tests/api/mutator.test.ts` derives which operations
`frontend/src/api/mutator.ts` fetches through `downloadFile`, and therefore
which media types that file's `Accept` header has to carry, by reading the
committed schema for a 200 that declares this header. A list of route names
beside that test would be the enumeration this repository has already been
wrong with; an attachment disposition is what a download *is*. The cover routes
send image bytes into an `<img>`, set no disposition, and are correctly outside
the set.
"""

from datetime import UTC, datetime
from typing import Any, Final

#: The header declaration both download operations put in their `responses`.
DOWNLOAD_DISPOSITION: Final[dict[str, dict[str, Any]]] = {
    "Content-Disposition": {
        "description": 'Names the saved file: `attachment; filename="..."`.',
        "schema": {"type": "string"},
    }
}


def datestamp() -> str:
    """The day a download was produced, for the saved file's name.

    **UTC, and the zone is named rather than inherited.** `date.today()` reads
    whatever zone the host is set to, so the same build stamped a different day
    depending on an environment variable nobody chose: UTC in the published
    image, which sets none, and the local day on a developer's machine. One
    archive and one export taken in the same minute could disagree with the
    rows inside them, every `DateTime` column in this application being UTC.

    **Not the viewer's day, and it cannot be.** The browser knows which day it
    is where the reader sits and the server does not, so a name stamped here is
    always somebody's clock. UTC is the one this application already keeps, and
    it is the same answer twice in a row rather than a different one per host.
    """
    return datetime.now(UTC).date().isoformat()


def attachment(filename: str) -> dict[str, str]:
    """The response headers that save `filename` rather than rendering it.

    **No escaping, and that is a property of the callers rather than a gap.**
    Both build their name from a format or an extension and `datestamp()`, so
    no caller-supplied text reaches it and there is no quote to break out of. A
    caller passing a name from a request would need RFC 6266 encoding, which
    this does not do: it would be a new caller and this docstring is where it
    should stop.
    """
    return {"Content-Disposition": f'attachment; filename="{filename}"'}
