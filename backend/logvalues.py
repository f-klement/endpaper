"""How much of an untrusted value reaches a log line.

**One fact with one home, and it had three call sites in two modules before it
had a module.** It lived in `classifications.py`, which is not what it is about:
`routers/books.py` already imported it from there, and the third caller,
`enums.member_or`, has no business importing the classification rules to find
out how long a log line may be.

The value being logged always came from outside: a catalogue response, an
uploaded archive, a column a restore wrote. None of those is bounded by anything
this application controls, and two of them are not bounded by the schema either.
SQLite does not enforce a VARCHAR length, so a `VARCHAR(20)` column holds a
100,000 character string quite happily, and an unclipped `%r` of it writes all
of them every time the row is read.

**Measured 2026-09-16**, against the three columns behind `models.DegradingEnum`:
one 200 row page carrying a 10,000 character stray value emitted 600 warnings and
6,044,600 bytes, and the poison's length is a free multiplier. The reader is the
unauthenticated public catalogue, whose rate limit is 120 requests a minute and
whose page cap is 200, so one address sustains hundreds of megabytes a minute of
log at that size. The degrade this bounds was written to stop a poisoned row 500
ing a page; unbounded it trades that for a cheaper way to fill a disk.
"""

#: How much of a third party value reaches the log.
#:
#: 200 characters is enough to recognise what arrived and to find the row, and
#: short enough that a log line stays a log line. `backup.py` and `covers.py`
#: clip their own at 120 and 200 by hand and predate this.
LOGGED_VALUE_MAX = 200


def clipped(value: object) -> str:
    """A third party value, short enough to log. See `LOGGED_VALUE_MAX`.

    **`repr` first, then the slice.** Slicing the value itself raises
    `TypeError` on anything that is not a sequence, and the values this is
    called on are `object`: an archive supplies integers and dictionaries as
    readily as strings. `backup.py` records that failure at its own site.

    `repr` is also what makes the line safe to read: it escapes the newline
    that would otherwise forge a second log entry, and the control characters
    that would otherwise reach a terminal.
    """
    text = repr(value)
    return text if len(text) <= LOGGED_VALUE_MAX else text[:LOGGED_VALUE_MAX] + "..."
