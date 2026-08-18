"""Helpers shared across the suite.

Kept out of conftest.py so test modules can import them directly. conftest is
loaded by pytest for its fixtures, and importing from it is fragile under the
importlib import mode this suite uses.
"""

from typing import Any

import httpx

# ── Image payloads ────────────────────────────────────────────────────────────
#
# Uploads are identified by their leading bytes, not by the filename, so a test
# payload has to carry a real magic number. These are the shortest byte strings
# each sniffer accepts.

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 8
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8

# Passes any extension check but is not an image. Used to prove the sniffer,
# not the filename, is what decides, and specifically that an SVG (which can
# carry script, and would be served from our own origin) is turned away.
NOT_AN_IMAGE = b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"


def items(response: httpx.Response) -> list[Any]:
    """Unwrap a paginated response body.

    Listing endpoints return a `Page` envelope rather than a bare array, so
    tests read the rows through this instead of indexing the body.
    """
    return list(response.json()["items"])


def total(response: httpx.Response) -> int:
    """The filtered row count from a paginated response, not the page length."""
    return int(response.json()["total"])


def titles(response: httpx.Response) -> list[str]:
    """Book titles from a paginated listing, in the order returned."""
    return [book["title"] for book in items(response)]
