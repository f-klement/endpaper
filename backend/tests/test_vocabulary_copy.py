"""Tests for backend/vocabulary_copy.py.

A load is written beside the copy in use and swapped in by one commit, so a
lookup reads the previous copy until then and a failed load leaves it; the
release is fetched through respx from the captures in
`tests/fixtures/vocabularies/`, never from the internet.
"""

import asyncio
import gzip
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

import fetch
import vocabulary_copy
from database import SessionLocal, engine
from enums import HeadingUse, VocabularyLoadPhase
from models import VOCABULARY_IDENTIFIER_MAX, VOCABULARY_LABEL_MAX, VocabularyCopy, VocabularyLabel
from vocabularies import Entry
from vocabulary_copy import Heading, Progress, Refused, Unknown

FIXTURES = Path(__file__).parent / "fixtures" / "vocabularies"
GND_RELEASE = gzip.compress((FIXTURES / "gnd_sachbegriff_2026_11_20.jsonld").read_bytes())
GND_ORIGIN = vocabulary_copy.scheme("gnd").origin or ""
FETCHED = datetime(2026, 11, 20, 12, 0)


@pytest.fixture(autouse=True)
def no_load_from_another_test(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Progress and threads are the process's own, so each test starts with
    none and waits for the loads it started before the database is emptied."""
    threads: dict[str, threading.Thread] = {}
    monkeypatch.setattr(vocabulary_copy, "_PROGRESS", {})
    monkeypatch.setattr(vocabulary_copy, "_THREADS", threads)
    yield
    for thread in list(threads.values()):
        thread.join(timeout=30)


def _after(held: threading.Event) -> Callable[[httpx.Request], httpx.Response]:
    """A release that answers, with a failure, only once `held` is set."""

    def answer(_request: httpx.Request) -> httpx.Response:
        held.wait(30)
        return httpx.Response(503)

    return answer


def _gnd(entry_id: str, subject: str, *synonyms: str) -> Entry:
    return Entry(id=entry_id, scheme="gnd", subject=subject, synonyms=synonyms)


def _label_rows(db) -> int:
    return db.scalar(select(func.count()).select_from(VocabularyLabel))


def _load(db, *entries: Entry) -> int:
    return vocabulary_copy.load(db, "gnd", iter(entries), FETCHED, None)


class TestTheLoadAndTheSwap:
    def test_a_load_becomes_the_current_copy(self, db):
        kept = _load(db, _gnd("(DE-588)1", "Abfall", "Müll"))

        assert kept == 1
        assert (db.get(VocabularyCopy, "gnd").entries, db.get(VocabularyCopy, "gnd").fetched_at) == (
            1,
            FETCHED,
        )
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Abfall") == ("(DE-588)1",)

    def test_the_previous_copy_answers_until_the_swap(self, db, monkeypatch):
        monkeypatch.setattr(vocabulary_copy, "BATCH", 1)
        _load(db, _gnd("(DE-588)1", "Alt"))
        seen_midway = []

        def release() -> Iterator[Entry]:
            yield _gnd("(DE-588)2", "Neu")
            with SessionLocal() as elsewhere:
                seen_midway.append(
                    (
                        vocabulary_copy.preferred_identifiers(elsewhere, "gnd", "Alt"),
                        vocabulary_copy.preferred_identifiers(elsewhere, "gnd", "Neu"),
                    )
                )
            yield _gnd("(DE-588)3", "Dritte")

        vocabulary_copy.load(db, "gnd", release(), FETCHED, None)

        assert seen_midway == [(("(DE-588)1",), ())]
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Alt") == ()
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Neu") == ("(DE-588)2",)

    def test_a_load_failing_midway_leaves_the_previous_copy_and_none_of_its_own_rows(self, db, monkeypatch):
        monkeypatch.setattr(vocabulary_copy, "BATCH", 1)
        _load(db, _gnd("(DE-588)1", "Alt"))

        def cut() -> Iterator[Entry]:
            yield _gnd("(DE-588)2", "Neu")
            raise OSError("the release was cut")

        with pytest.raises(OSError, match="cut"):
            vocabulary_copy.load(db, "gnd", cut(), FETCHED, None)

        assert db.get(VocabularyCopy, "gnd").generation == 1
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Alt") == ("(DE-588)1",)
        assert _label_rows(db) == 1

    def test_a_swap_removes_the_previous_generation(self, db):
        _load(db, _gnd("(DE-588)1", "Alt", "Älter"))
        _load(db, _gnd("(DE-588)2", "Neu"))

        assert _label_rows(db) == 1

    def test_the_previous_generation_is_deleted_a_batch_to_a_statement(self, db, monkeypatch):
        """One statement over a whole generation held SQLite's write lock past
        every other writer's busy timeout."""
        _load(db, _gnd("(DE-588)1", "Alt", "Älter", "Ältest"), _gnd("(DE-588)2", "Zwei", "Doppelt"))
        monkeypatch.setattr(vocabulary_copy, "BATCH", 2)
        deletes: list[str] = []

        @event.listens_for(engine, "after_cursor_execute")
        def counted(_conn, _cursor, statement, *_args) -> None:
            if statement.lstrip().upper().startswith("DELETE FROM VOCABULARY_LABELS"):
                deletes.append(statement)

        try:
            _load(db, _gnd("(DE-588)3", "Neu"))
        finally:
            event.remove(engine, "after_cursor_execute", counted)

        # One before the load finding nothing stale, then five rows two at a
        # time and the statement that finds none left: the cursor's rowcount
        # reads 0 in this event on SQLite, so statements are what is counted.
        assert (_label_rows(db), len(deletes)) == (1, 5)

    def test_a_failure_removing_the_previous_rows_after_the_swap_leaves_the_load_done(self, db, monkeypatch):
        """The new copy is current by then, so the load reports what it loaded."""
        _load(db, _gnd("(DE-588)1", "Alt"))
        discard = vocabulary_copy._discard

        def locked_after_the_swap(session, scheme_id: str, keep: int | None) -> None:
            if keep == 2:
                raise OperationalError("DELETE", {}, Exception("database is locked"))
            discard(session, scheme_id, keep)

        monkeypatch.setattr(vocabulary_copy, "_discard", locked_after_the_swap)

        assert _load(db, _gnd("(DE-588)2", "Neu")) == 1
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Neu") == ("(DE-588)2",)

    def test_rows_a_stopped_load_left_behind_do_not_block_the_next(self, db):
        """A process killed mid load leaves the next generation's rows; written
        again, they would break the unique constraint."""
        _load(db, _gnd("(DE-588)1", "Alt"))
        db.add(
            VocabularyLabel(scheme="gnd", generation=2, identifier="(DE-588)2", label="Neu", preferred=True)
        )
        db.commit()

        assert _load(db, _gnd("(DE-588)2", "Neu")) == 1
        assert _label_rows(db) == 1

    def test_an_identifier_repeated_in_a_release_keeps_its_first_entry(self, db):
        kept = _load(db, _gnd("(DE-588)1", "Erste"), _gnd("(DE-588)1", "Zweite"))

        assert kept == 1
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Zweite") == ()

    def test_an_entry_whose_identifier_or_preferred_label_is_past_its_column_is_passed_over(self, db):
        kept = _load(
            db,
            _gnd("(DE-588)" + "1" * VOCABULARY_IDENTIFIER_MAX, "Lang"),
            _gnd("(DE-588)2", "x" * (VOCABULARY_LABEL_MAX + 1)),
            _gnd("(DE-588)3", "Kurz"),
        )

        assert (kept, db.get(VocabularyCopy, "gnd").entries) == (1, 1)

    def test_an_alternate_label_past_its_column_is_dropped_alone(self, db):
        _load(db, _gnd("(DE-588)1", "Kurz", "x" * (VOCABULARY_LABEL_MAX + 1), "Knapp"))

        assert vocabulary_copy.headings_for(db, "gnd", "Knapp") == (Heading("(DE-588)1", "Kurz"),)
        assert _label_rows(db) == 2


class TestTheLookups:
    def test_a_decomposed_label_finds_the_composed_preferred_label(self, db):
        _load(db, _gnd("(DE-588)1", "Müll"))

        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Müll") == ("(DE-588)1",)

    def test_the_exact_preferred_label_lookup_does_not_match_an_alternate(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall", "Müll"))

        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Müll") == ()

    def test_two_entries_sharing_a_preferred_label_are_both_returned(self, db):
        _load(db, _gnd("(DE-588)2", "Bank"), _gnd("(DE-588)1", "Bank"))

        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Bank") == ("(DE-588)1", "(DE-588)2")

    def test_another_vocabularys_copy_is_not_read(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall"))

        assert vocabulary_copy.preferred_identifiers(db, "lcsh", "Abfall") == ()

    def test_a_variant_finds_its_entry_under_the_preferred_label(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall", "Müll", "Abfälle"))

        assert vocabulary_copy.headings_for(db, "gnd", "Müll") == (Heading("(DE-588)1", "Abfall"),)

    def test_nothing_is_found_before_a_copy_is_loaded(self, db):
        assert vocabulary_copy.headings_for(db, "gnd", "Abfall") == ()


class TestTheSuggestion:
    """What the heading field offers as a cataloguer types."""

    @staticmethod
    def _offered(db, typed: str, use: HeadingUse = HeadingUse.SUBJECT) -> list[str]:
        return [heading.label for heading in vocabulary_copy.suggest(db, "gnd", typed, use)]

    def test_a_label_beginning_with_what_was_typed_is_offered_under_its_preferred_label(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall", "Müll"), _gnd("(DE-588)2", "Mühle"))

        offered = vocabulary_copy.suggest(db, "gnd", "Mül", HeadingUse.SUBJECT)

        assert offered == (Heading("(DE-588)1", "Abfall"),)

    def test_a_first_letter_typed_in_lower_case_finds_the_capitalised_heading(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall"))

        assert self._offered(db, "abf") == ["Abfall"]

    def test_an_entry_matching_under_two_labels_is_offered_once(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall", "Abfälle"))

        assert self._offered(db, "Abf") == ["Abfall"]

    def test_at_most_the_cap_is_offered_in_label_order(self, db):
        count = vocabulary_copy.SUGGEST_MAX + 3
        _load(db, *(_gnd(f"(DE-588){n}", f"Bau {n:02d}") for n in reversed(range(count))))

        assert self._offered(db, "Bau") == [f"Bau {n:02d}" for n in range(vocabulary_copy.SUGGEST_MAX)]

    def test_fewer_characters_than_the_minimum_offer_nothing(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall"))

        assert self._offered(db, "A" * (vocabulary_copy.SUGGEST_MIN - 1)) == []

    def test_a_use_the_copies_do_not_serve_offers_nothing(self, db):
        """A subject file offers no heading to a field filling a name."""
        _load(db, _gnd("(DE-588)1", "Abfall"))

        assert self._offered(db, "Abf", HeadingUse.NAME) == []

    def test_a_wildcard_typed_is_a_character(self, db):
        _load(db, _gnd("(DE-588)1", "Abfall"), _gnd("(DE-588)2", "A%b"))

        assert self._offered(db, "A%") == ["A%b"]

    def test_only_a_vocabulary_with_a_copy_loaded_is_suggestible(self, db):
        assert vocabulary_copy.suggestible(db) == ()

        _load(db, _gnd("(DE-588)1", "Abfall"))

        assert [scheme.id for scheme in vocabulary_copy.suggestible(db)] == ["gnd"]


class TestTheBatchedPreferredLabelLookup:
    """What a MARC upload asks once per file (option AC)."""

    @staticmethod
    def _lcsh(db, *subjects: str) -> None:
        entries = (
            Entry(
                id=f"http://id.loc.gov/authorities/subjects/sh{n}",
                scheme="lcsh",
                subject=subject,
                synonyms=(),
            )
            for n, subject in enumerate(subjects)
        )
        vocabulary_copy.load(db, "lcsh", entries, FETCHED, None)

    def test_only_the_pairs_whose_scheme_holds_the_label_as_preferred_are_held(self, db):
        self._lcsh(db, "Toxicology")
        _load(db, _gnd("(DE-588)1", "Abfall", "Müll"))

        asked = {
            ("lcsh", "Toxicology"),
            ("lcsh", "Abbreviations as Topic"),
            ("gnd", "Müll"),
            ("gnd", "Toxicology"),
        }
        assert vocabulary_copy.held_preferred_labels(db, asked) == {("lcsh", "Toxicology")}

    def test_a_pair_is_returned_as_it_was_asked(self, db):
        _load(db, _gnd("(DE-588)1", "Müll"))

        decomposed = "Mu\u0308ll"
        assert vocabulary_copy.held_preferred_labels(db, {("gnd", decomposed)}) == {("gnd", decomposed)}

    def test_labels_past_one_query_are_asked_in_the_next(self, db, monkeypatch):
        monkeypatch.setattr(vocabulary_copy, "_ASKED_AT_ONCE", 1)
        self._lcsh(db, "Pharmacology", "Toxicology")

        asked = {("lcsh", "Pharmacology"), ("lcsh", "Toxicology")}
        assert vocabulary_copy.held_preferred_labels(db, asked) == asked

    def test_a_label_differing_only_in_case_is_not_held(self, db):
        self._lcsh(db, "Toxicology")

        assert vocabulary_copy.held_preferred_labels(db, {("lcsh", "toxicology")}) == frozenset()

    def test_a_label_only_a_generation_not_yet_swapped_in_holds_is_not_held(self, db):
        self._lcsh(db, "Toxicology")
        db.add(
            VocabularyLabel(
                scheme="lcsh", generation=2, identifier="sh9", label="Pharmacology", preferred=True
            )
        )
        db.commit()

        assert vocabulary_copy.held_preferred_labels(db, {("lcsh", "Pharmacology")}) == frozenset()

    def test_nothing_is_held_before_a_copy_is_loaded(self, db):
        assert vocabulary_copy.held_preferred_labels(db, {("lcsh", "Toxicology")}) == frozenset()


class TestTheFetch:
    def test_the_release_is_written_and_its_last_modified_returned_as_utc(self, tmp_path):
        reports: list[Progress] = []
        with respx.mock:
            respx.get(GND_ORIGIN).mock(
                return_value=httpx.Response(
                    200, content=GND_RELEASE, headers={"Last-Modified": "Wed, 04 Nov 2026 07:30:00 GMT"}
                )
            )
            released = vocabulary_copy.fetch_release(GND_ORIGIN, tmp_path / "r", reports.append)

        assert released == datetime(2026, 11, 4, 7, 30)
        assert (tmp_path / "r").read_bytes() == GND_RELEASE
        assert reports[-1] == Progress(VocabularyLoadPhase.FETCHING, len(GND_RELEASE), len(GND_RELEASE))

    def test_an_unreadable_last_modified_is_no_release_date(self, tmp_path):
        with respx.mock:
            respx.get(GND_ORIGIN).mock(
                return_value=httpx.Response(200, content=b"x", headers={"Last-Modified": "soon"})
            )
            assert vocabulary_copy.fetch_release(GND_ORIGIN, tmp_path / "r", lambda _: None) is None

    def test_a_status_other_than_200_is_refused(self, tmp_path):
        with respx.mock:
            respx.get(GND_ORIGIN).mock(return_value=httpx.Response(404))
            with pytest.raises(fetch.FetchRefused, match="404"):
                vocabulary_copy.fetch_release(GND_ORIGIN, tmp_path / "r", lambda _: None)

    def test_a_release_still_arriving_at_the_deadline_is_refused(self, tmp_path, monkeypatch):
        """A source trickling bytes inside each read's timeout held the one load
        slot for the life of the process."""
        monkeypatch.setattr(vocabulary_copy, "RELEASE_SECONDS", 0.2)

        async def trickle(_request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, content=GND_RELEASE)

        with respx.mock:
            respx.get(GND_ORIGIN).mock(side_effect=trickle)
            with pytest.raises(fetch.DeadlineExceeded):
                vocabulary_copy.fetch_release(GND_ORIGIN, tmp_path / "r", lambda _: None)

    def test_a_release_past_the_cap_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vocabulary_copy, "MAX_RELEASE", len(GND_RELEASE) - 1)
        with respx.mock:
            respx.get(GND_ORIGIN).mock(return_value=httpx.Response(200, content=GND_RELEASE))
            with pytest.raises(fetch.ResponseTooLarge):
                vocabulary_copy.fetch_release(GND_ORIGIN, tmp_path / "r", lambda _: None)


class TestStartingALoad:
    def test_a_release_is_fetched_converted_and_loaded_leaving_no_file(self, db, tmp_path):
        with respx.mock:
            respx.get(GND_ORIGIN).mock(return_value=httpx.Response(200, content=GND_RELEASE))
            vocabulary_copy.start("gnd", tmp_path).join(timeout=30)

        (status,) = [one for one in vocabulary_copy.statuses(db) if one.scheme.id == "gnd"]
        assert (status.copy.entries if status.copy else None, status.progress) == (5, None)
        assert vocabulary_copy.preferred_identifiers(db, "gnd", "Abfall") == ("(DE-588)4000098-9",)
        # Every file a load writes sits beside the data file: the release, the
        # converted copy and the partial the conversion writes aside.
        assert list((tmp_path / (vocabulary_copy.scheme("gnd").data_file or "")).parent.iterdir()) == []

    def test_a_failed_fetch_is_recorded_and_loads_nothing(self, db, tmp_path):
        with respx.mock:
            respx.get(GND_ORIGIN).mock(return_value=httpx.Response(503))
            vocabulary_copy.start("gnd", tmp_path).join(timeout=30)

        (status,) = [one for one in vocabulary_copy.statuses(db) if one.scheme.id == "gnd"]
        assert (status.copy, status.progress.phase if status.progress else None) == (
            None,
            VocabularyLoadPhase.FAILED,
        )

    def test_a_partial_file_a_killed_conversion_left_is_removed(self, tmp_path):
        data_file = tmp_path / (vocabulary_copy.scheme("gnd").data_file or "")
        data_file.parent.mkdir(parents=True)
        left = data_file.with_name(f".{data_file.name}.k1ll3d.partial")
        left.write_bytes(b"half")

        with respx.mock:
            respx.get(GND_ORIGIN).mock(return_value=httpx.Response(503))
            vocabulary_copy.start("gnd", tmp_path).join(timeout=30)

        assert not left.exists()

    def test_a_second_download_of_one_vocabulary_while_the_first_runs_is_refused(self, tmp_path):
        held = threading.Event()
        with respx.mock:
            respx.get(GND_ORIGIN).mock(side_effect=_after(held))
            first = vocabulary_copy.start("gnd", tmp_path)
            try:
                with pytest.raises(Refused, match="under way"):
                    vocabulary_copy.start("gnd", tmp_path)
            finally:
                held.set()
                first.join(timeout=30)

    def test_a_vocabulary_whose_licence_permits_no_copy_is_refused(self, monkeypatch):
        query_only = replace(vocabulary_copy.scheme("gnd"), data_file=None, origin=None, suggest="lobid")
        monkeypatch.setattr(vocabulary_copy, "declared", lambda: (query_only,))

        with pytest.raises(Refused, match="licence"):
            vocabulary_copy.start("gnd")

    def test_an_undeclared_vocabulary_is_unknown(self):
        with pytest.raises(Unknown):
            vocabulary_copy.start("mesh")
