"""Parsing, validation and canonicalisation of ISBNs.

Previously there was none of this: the scanner matched `^(97[89]\\d{10}|\\d{10})$`
and the API accepted any 10-to-20 character string. That had four consequences,
all of them observed rather than theoretical:

1. A valid ISBN-10 whose check digit is `X` was **rejected**. Roughly one ISBN-10
   in eleven ends in X, so a real slice of older books could not be scanned.
2. No checksum was verified, so a single misread digit produced a plausible-
   looking ISBN and a lookup for a book that cannot exist.
3. Hyphenated or space-padded input was rejected, which is exactly the form
   people paste into the manual-entry box.
4. ISBN-10 and ISBN-13 for the same book were stored as different strings, so
   the unique constraint did not actually prevent duplicates.

Everything is normalised to **ISBN-13** for storage, which is what fixes (4).
"""

from typing import Final

# Bookland prefixes. An EAN-13 that starts with anything else is a valid
# barcode but not a book (a food packet, a loyalty card) and must not reach
# the metadata lookup.
BOOKLAND_PREFIXES: Final = ("978", "979")

_ISBN10_LENGTH: Final = 10
_ISBN13_LENGTH: Final = 13


def normalise(raw: str) -> str:
    """Strip formatting and upper-case the check digit.

    ISBNs are written with hyphens or spaces grouping the registration
    elements, and those groupings vary by publisher, so they carry no
    information worth keeping.
    """
    return "".join(character for character in raw if character.isalnum()).upper()


def is_valid_isbn10(candidate: str) -> bool:
    """Modulus-11 check. The final digit may be `X`, meaning ten."""
    if len(candidate) != _ISBN10_LENGTH:
        return False

    body, check = candidate[:9], candidate[9]
    if not body.isdigit():
        return False
    if not (check.isdigit() or check == "X"):
        return False

    total = sum(int(digit) * (10 - position) for position, digit in enumerate(body))
    total += 10 if check == "X" else int(check)
    return total % 11 == 0


def is_valid_isbn13(candidate: str) -> bool:
    """Modulus-10 check with alternating 1/3 weights (the EAN-13 scheme)."""
    if len(candidate) != _ISBN13_LENGTH or not candidate.isdigit():
        return False

    total = sum(
        int(digit) * (1 if position % 2 == 0 else 3)
        for position, digit in enumerate(candidate)
    )
    return total % 10 == 0


def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert a valid ISBN-10 to its ISBN-13 form.

    The body is prefixed with 978 and a fresh modulus-10 check digit computed;
    the ISBN-10 check digit is discarded because the two schemes differ.
    """
    body = "978" + isbn10[:9]
    total = sum(
        int(digit) * (1 if position % 2 == 0 else 3)
        for position, digit in enumerate(body)
    )
    return body + str((10 - total % 10) % 10)


def isbn13_to_isbn10(isbn13: str) -> str | None:
    """Convert a 978-prefixed ISBN-13 back to ISBN-10, or None if impossible.

    Only 978 converts: the 979 range has no ISBN-10 equivalent, which is the
    whole reason it exists.
    """
    if not isbn13.startswith("978"):
        return None

    body = isbn13[3:12]
    total = sum(int(digit) * (10 - position) for position, digit in enumerate(body))
    remainder = (11 - total % 11) % 11
    return body + ("X" if remainder == 10 else str(remainder))


def parse(raw: str | None) -> str | None:
    """Normalise and validate, returning the canonical ISBN-13.

    Returns None for anything that is not a real ISBN, so callers can treat a
    falsy result as "not a book" without a second check. An ISBN-10 comes back
    converted, so the same book scanned in either form lands on one value.
    """
    if not raw:
        return None

    candidate = normalise(raw)

    if is_valid_isbn13(candidate):
        # A valid EAN-13 that is not Bookland is a real barcode for something
        # that is not a book.
        return candidate if candidate.startswith(BOOKLAND_PREFIXES) else None

    if is_valid_isbn10(candidate):
        return isbn10_to_isbn13(candidate)

    return None


def is_valid(raw: str | None) -> bool:
    return parse(raw) is not None


def equivalent_forms(raw: str | None) -> list[str]:
    """Every string this ISBN might already be stored as.

    Rows written before canonicalisation may hold the ISBN-10, so a duplicate
    check has to look for both forms or the same book gets added twice.
    """
    canonical = parse(raw)
    if canonical is None:
        return []

    forms = [canonical]
    as_isbn10 = isbn13_to_isbn10(canonical)
    if as_isbn10 is not None:
        forms.append(as_isbn10)
    return forms
