"""Tests for backend/downloads.py.

The module is two facts the two download routes share: the attachment header,
and the day their saved filenames are stamped with. The second is what this
file is mostly about, because it was `date.today()` at both call sites and
that reads whichever zone the host is set to.
"""

from datetime import UTC, date, datetime

import pytest

import downloads
from tests.conftest import NINE_HOURS, NINE_HOURS_EAST, at_zone

#: A fixed instant chosen so the UTC day and the local day disagree.
#:
#: 15:30 UTC is 00:30 the next morning nine hours east, so the UTC day is the
#: 13th and the local day is the 14th. Any instant in the first hours of a
#: local morning east of Greenwich would do; this one is written out so the
#: two days are visible beside each other rather than computed.
JUST_AFTER_LOCAL_MIDNIGHT = datetime(2026, 3, 13, 15, 30, tzinfo=UTC)
THE_UTC_DAY = "2026-03-13"
THE_LOCAL_DAY = "2026-03-14"

@pytest.fixture
def frozen(monkeypatch):
    """Freeze `downloads`'s own clock at the instant above.

    `now(None)` answers the **local naive** time, which is what the real one
    does and is the whole subject here: a frozen clock that answered UTC to
    both spellings would make every arm below pass against either answer.

    **`date` is patched too, with `raising=False`, although the module does
    not bind it.** That is what lets an evasion spelled `date.today()` be
    observed, which is the spelling this helper was repaired from; without it
    a plant of the original defect reads the real clock and reddens for the
    wrong reason.
    """

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return JUST_AFTER_LOCAL_MIDNIGHT.astimezone().replace(tzinfo=None)
            return JUST_AFTER_LOCAL_MIDNIGHT.astimezone(tz)

    class _Day(date):
        @classmethod
        def today(cls):
            return JUST_AFTER_LOCAL_MIDNIGHT.astimezone().date()

    monkeypatch.setattr(downloads, "datetime", _Clock)
    monkeypatch.setattr(downloads, "date", _Day, raising=False)


class TestTheDatestampNamesItsZone:
    """**The arm states the ambient condition it depends on and refuses
    without it**, rather than defaulting.

    A probe for this defect inheriting the host's zone reports it absent: at
    an offset of zero or west, the UTC day and the local day are the same for
    this instant and `date.today()` would have answered correctly. So a run
    where the zone did not take is a run that measured nothing, and it has to
    say so rather than pass.
    """

    def test_the_fixture_really_moved_the_process_east(self, east_of_greenwich):
        """The refusal, as its own arm so it names itself when it fires.

        **The exact offset, not its sign.** `> 0` is what this asserted
        first, and it passes on any host already east of Greenwich **with
        the zone never applied**: driven with the fixture's own set dropped,
        this machine is at one hour east and the arm was green. A sign is a
        property of the host; the figure below is a property of the fixture
        having run.
        """
        offset = JUST_AFTER_LOCAL_MIDNIGHT.astimezone().utcoffset()

        assert offset == NINE_HOURS, (
            f"this process is at offset {offset} rather than nine hours east, so "
            "the zone never took and the arms below cannot observe the defect "
            "they are about: they would pass on a correct answer and on the old "
            "one alike"
        )

    def test_the_local_day_and_the_utc_day_really_disagree_here(self, east_of_greenwich):
        """The other half of the arming: the instant has to straddle midnight.

        Without this, a later edit moving the instant to the middle of the
        day would leave every arm below green against both answers.
        """
        assert JUST_AFTER_LOCAL_MIDNIGHT.astimezone().date().isoformat() == THE_LOCAL_DAY
        assert JUST_AFTER_LOCAL_MIDNIGHT.date().isoformat() == THE_UTC_DAY

    def test_it_answers_the_utc_day_rather_than_the_hosts(self, east_of_greenwich, frozen):
        """The defect itself. `date.today()` here answers the 14th."""
        assert downloads.datestamp() == THE_UTC_DAY

    def test_it_answers_the_same_day_whatever_the_host_is_set_to(self, frozen):
        """Nine hours east and wherever this machine is, one answer.

        The point of naming the zone is that the filename stops being a
        property of the host, so the arm is run twice over one frozen instant
        rather than asserting a constant once.
        """
        here = downloads.datestamp()
        with at_zone(NINE_HOURS_EAST):
            east = downloads.datestamp()

        assert here == east == THE_UTC_DAY


class TestTheAttachmentHeader:
    def test_it_names_the_file(self):
        assert downloads.attachment("endpaper-export-2026-03-13.csv") == {
            "Content-Disposition": 'attachment; filename="endpaper-export-2026-03-13.csv"'
        }
