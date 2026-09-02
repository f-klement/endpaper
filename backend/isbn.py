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
    """Modulus-11 check. The final digit may be `X`, meaning ten.

    **`isascii()` beside every `isdigit()`, and it is load bearing.** See
    `is_valid_isbn13`, which carries the measurement: `str.isdigit()` is True
    for characters `int()` refuses and for characters `int()` accepts and this
    application must not store.
    """
    if len(candidate) != _ISBN10_LENGTH:
        return False

    body, check = candidate[:9], candidate[9]
    if not (body.isascii() and body.isdigit()):
        return False
    if not (check.isascii() and (check.isdigit() or check == "X")):
        return False

    total = sum(int(digit) * (10 - position) for position, digit in enumerate(body))
    total += 10 if check == "X" else int(check)
    return total % 11 == 0


def is_valid_isbn13(candidate: str) -> bool:
    """Modulus-10 check with alternating 1/3 weights (the EAN-13 scheme).

    **`isascii()` is what makes the `int()` below safe, and without it this
    function had two live defects.** `str.isdigit()` is true of far more than
    `0` to `9`, and the two halves of that fail in opposite directions:

    * A superscript two, `U+00B2`, is `isdigit()` and `int()` **raises** on it.
      `GET /api/books/lookup?isbn=978` followed by ten of them is thirteen
      characters, passed the length check, and came out of the router as an
      unhandled `ValueError`. Executed against the running app.
    * An Arabic-Indic zero, `U+0660`, is `isdigit()` and `int()` **accepts** it
      as 0. So a checksum computed over it can pass, and `POST /api/books` with
      `978316148410` and one of those stored that string: a second copy of a
      book `uq_books_isbn_single_copy` could no longer see as the same one.

    Both are fixed here rather than at the routers, because every caller of
    `parse` inherits the promise that what comes back is thirteen ASCII digits.
    `metadata._nkp_query` states that promise in its own reasoning, and it was
    asserted before it was true.
    """
    if len(candidate) != _ISBN13_LENGTH or not (
        candidate.isascii() and candidate.isdigit()
    ):
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


#: The registration group element's assigned ranges, by Bookland prefix and by
#: how many digits the element is.
#:
#: **A registration group is not a fixed number of digits and cannot be read off
#: a string prefix.** `978-3` is German language publishing, `978-80` is Czech,
#: `978-960` and `978-618` are both Greek, `978-9974` is Uruguayan. So the only
#: way to say which group an ISBN belongs to is to match the assigned ranges
#: longest-plausible-first, which is what this table is for.
#:
#: **`6` is not a group and reading it as one is the trap this table exists to
#: stop.** Greek publishing's second group is `978-618` and Brazil's second is
#: `978-65`, both three and two digits starting with 6. A survey script written
#: for #122 treated `6` as a single digit group, filed all 23 of those ISBNs
#: under a group that does not exist, and produced a plausible table with
#: nothing failing.
#:
#: **The ranges are deliberately narrow where the published list is growing.**
#: An ISBN in a range this table does not cover decodes to `None`, and every
#: caller treats `None` as "no claim", so a narrow range makes the answer
#: *unknown* rather than *wrong*. A range set too wide does the opposite: it
#: invents a group name, and `sources.SERVES_GROUPS` would then skip a catalogue
#: for a book it holds. Unknown is recoverable and wrong is silent, so when the
#: published list moves, widen this table late rather than early.
#:
#: The list is ISBN International's and it is a real published document, the
#: RangeMessage. What is encoded here is only the **shape** of it, the ranges an
#: element of each length may fall in, and not the 200-odd individual
#: assignments, because no caller here needs to name the country.
_GROUP_RANGES: Final[dict[str, tuple[tuple[int, str, str], ...]]] = {
    "978": (
        (1, "0", "5"),
        (1, "7", "7"),
        (2, "65", "65"),
        (2, "80", "94"),
        (3, "600", "649"),
        (3, "950", "989"),
        (4, "9911", "9989"),
        (5, "99901", "99993"),
    ),
    "979": (
        (1, "8", "8"),
        (2, "10", "13"),
    ),
}


#: What separates the Bookland prefix from the group element in a group's name.
#: Written once so `registration_group` and `group_prefix` cannot disagree about
#: the spelling of a value one of them builds and the other takes apart.
_GROUP_SEPARATOR: Final = "-"


def group_prefix(group: str) -> str | None:
    """The Bookland prefix a registration group belongs to: `978-960` is `978`.

    None for anything not shaped like a group this module produces, and the
    callers treat that as "no claim" for the same reason `registration_group`
    does.

    **This exists because 978 and 979 are two separate assignment spaces**, and a
    remit listing only 978 groups is silent about 979 rather than negative about
    it. `sources._serves` is the only caller and carries that argument.
    """
    prefix, separator, element = group.partition(_GROUP_SEPARATOR)
    if not separator or prefix not in _GROUP_RANGES or not element:
        return None
    return prefix


def registration_group(raw: str | None) -> str | None:
    """Which registration group this ISBN belongs to, as `978-3` or `978-618`.

    None where there is no answer to give: not an ISBN at all, or an element in
    a range `_GROUP_RANGES` does not cover. **None means "no claim", never "no
    group"**, and every caller has to treat it as "ask anyway", because the
    alternative is a catalogue silently not asked about a book it holds.

    **The ranges are prefix free, so the first match is the only match.** That is
    a property of the published list rather than of this loop: single digit
    groups are 0 to 5 and 7, two digit ones start with 6, 8 or 9, three digit
    ones with 6 or 9, and no shorter assigned element is the start of a longer
    one. So there is no longest-match tie to break and the order of the table is
    presentation rather than precedence.
    """
    # **`parse` first, and not only to reject rubbish.** The range test below is
    # a string comparison, so a non ASCII digit would be ordered against `"0"`
    # to `"9"` by code point and could fall inside a range it has nothing to do
    # with. `parse` is what guarantees thirteen ASCII digits reach it.
    isbn = parse(raw)
    if isbn is None:
        return None
    prefix, rest = isbn[:3], isbn[3:]
    for length, low, high in _GROUP_RANGES.get(prefix, ()):
        element = rest[:length]
        if low <= element <= high:
            return f"{prefix}{_GROUP_SEPARATOR}{element}"
    return None
