"""The Readwise pull's own rules, below the routes: reading a page, a page
written again after losing a race, the token's seal, and who the daily job is
due for.

What a pull writes is reached through the routes, in
`tests/routers/test_readwise.py`.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, insert
from sqlalchemy.exc import IntegrityError

import credentials
import readwise
from database import SessionLocal
from enums import HighlightSource
from models import (
    HIGHLIGHT_TEXT_MAX,
    MEMBER_LOGIN_ENVELOPE_MAX_BYTES,
    READWISE_TOKEN_MAX,
    DeletedHighlight,
    Highlight,
    MemberLogin,
)


def _entry(**fields: object) -> dict[str, object]:
    return {
        "user_book_id": 7,
        "title": "Dune",
        "author": "Frank Herbert",
        "category": "books",
        "highlights": [],
    } | fields


class TestReadingAPage:
    def test_a_body_that_is_not_an_export_page_is_unreadable(self):
        with pytest.raises(readwise.Unreadable):
            readwise.read_page([{"results": []}])

    def test_an_entry_or_highlight_without_a_usable_id_is_dropped(self):
        page = readwise.read_page(
            {
                "results": [
                    _entry(user_book_id=True),
                    _entry(highlights=[{"id": "9", "text": "x"}, {"id": 9, "text": "kept"}]),
                ],
                "nextPageCursor": None,
            }
        )

        assert [entry.user_book_id for entry in page.entries] == [7]
        assert [mark.id for mark in page.entries[0].highlights] == [9]

    def test_an_id_listed_twice_is_one_highlight_and_the_later_wins(self):
        page = readwise.read_page(
            {"results": [_entry(highlights=[{"id": 9, "text": "first"}, {"id": 9, "text": "second"}])]}
        )

        assert [mark.text for mark in page.entries[0].highlights] == ["second"]

    def test_a_passage_past_the_ceiling_is_read_with_no_text_rather_than_cut(self):
        page = readwise.read_page(
            {"results": [_entry(highlights=[{"id": 1, "text": "a" * (HIGHLIGHT_TEXT_MAX + 1)}])]}
        )

        assert page.entries[0].highlights[0].text is None

    def test_a_nul_is_removed_from_a_passage(self):
        page = readwise.read_page({"results": [_entry(highlights=[{"id": 1, "text": "a\x00b"}])]})

        assert page.entries[0].highlights[0].text == "ab"

    def test_a_time_with_an_offset_is_stored_as_utc(self):
        page = readwise.read_page(
            {
                "results": [
                    _entry(
                        highlights=[
                            {"id": 1, "text": "x", "highlighted_at": "2026-03-01T22:15:09.5+01:00"}
                        ]
                    )
                ]
            }
        )

        assert page.entries[0].highlights[0].highlighted_at == datetime(2026, 3, 1, 21, 15, 9)


class TestAPageThatLostARace:
    """A hand delete commits while a page is being written, and the page's
    update then matches no row."""

    @staticmethod
    def _apply(db, member_id: int, *marks: dict[str, object]) -> readwise.Counts:
        counts = readwise.Counts()
        page = readwise.read_page({"results": [_entry(highlights=list(marks))]})
        index = readwise.build_index(db, member_id)
        readwise.apply_page(db, member_id, page, index, counts, whole=True)
        return counts

    @staticmethod
    def _a_hand_delete_commits_first(db, member_id: int) -> None:
        row_id = db.query(Highlight).one().id

        def delete(session, *_):
            with SessionLocal() as other:
                other.add(
                    DeletedHighlight(
                        user_id=member_id, source=HighlightSource.READWISE, source_key="9"
                    )
                )
                other.flush()
                other.query(Highlight).filter(Highlight.id == row_id).delete()
                other.commit()

        event.listen(db, "before_flush", delete, once=True)

    def test_a_pull_racing_a_hand_delete_leaves_the_mark_deleted(self, db, member, make_book):
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        member_id = member["user"]["id"]
        self._apply(db, member_id, {"id": 9, "text": "first"})
        self._a_hand_delete_commits_first(db, member_id)

        counts = self._apply(db, member_id, {"id": 9, "text": "edited at Readwise"})

        assert (counts.updated, counts.skipped) == (0, 1)
        assert db.query(Highlight).count() == 0

    def test_a_retried_page_counts_each_highlight_once(self, db, member, make_book):
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        member_id = member["user"]["id"]
        self._apply(db, member_id, {"id": 9, "text": "first"})
        self._a_hand_delete_commits_first(db, member_id)

        counts = self._apply(
            db, member_id, {"id": 9, "text": "edited at Readwise"}, {"id": 10, "text": "new"}
        )

        assert (counts.created, counts.updated, counts.skipped) == (1, 0, 1)


class TestAPageListingOneHighlightUnderTwoBooks:
    """Two answers are no answer, unless one Book already holds the highlight."""

    PASSAGE = {"id": 9, "text": "Fear is the mind-killer."}

    @staticmethod
    def _apply(db, member_id: int, *entries: dict[str, object]) -> readwise.Counts:
        counts = readwise.Counts()
        page = readwise.read_page({"results": list(entries)})
        index = readwise.build_index(db, member_id)
        readwise.apply_page(db, member_id, page, index, counts, whole=True)
        return counts

    def _both(self) -> tuple[dict[str, object], dict[str, object]]:
        return (
            _entry(user_book_id=7, title="Dune", highlights=[self.PASSAGE]),
            _entry(user_book_id=8, title="Children of Dune", highlights=[self.PASSAGE]),
        )

    def test_writes_it_once_on_the_book_already_holding_it(self, db, member, make_book):
        dune = make_book(member["headers"], title="Dune", author="Frank Herbert")["id"]
        make_book(member["headers"], title="Children of Dune", author="Frank Herbert")
        member_id = member["user"]["id"]
        self._apply(db, member_id, self._both()[0])

        self._apply(db, member_id, *self._both())

        assert [row.book_id for row in db.query(Highlight)] == [dune]

    def test_writes_it_on_neither_when_neither_holds_it(self, db, member, make_book):
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        make_book(member["headers"], title="Children of Dune", author="Frank Herbert")
        member_id = member["user"]["id"]

        counts = self._apply(db, member_id, *self._both())

        assert (counts.created, counts.skipped) == (0, 1)
        assert db.query(Highlight).count() == 0

    def test_writes_it_once_when_both_are_one_book_and_the_later_wins(
        self, db, member, make_book
    ):
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        member_id = member["user"]["id"]
        twice = (
            _entry(user_book_id=7, highlights=[{"id": 9, "text": "earlier"}]),
            _entry(user_book_id=8, highlights=[{"id": 9, "text": "later"}]),
        )

        counts = self._apply(db, member_id, *twice)

        assert (counts.created, counts.skipped) == (1, 0)
        assert [row.text for row in db.query(Highlight)] == ["later"]


class TestAPageListingOneHighlightLiveAndDeleted:
    """The page is one answer: a highlight live under one of its books is not
    removed by a deleted book on the same page carrying it. The row is shared
    first, so one removed and written again shows."""

    @pytest.mark.parametrize(
        ("deleted_first", "text"),
        [(False, "first"), (False, "edited at Readwise"), (True, "first")],
        ids=["live_first", "edited_live_first", "deleted_first"],
    )
    def test_the_live_listing_keeps_its_row(self, db, member, make_book, deleted_first, text):
        make_book(member["headers"], title="Dune", author="Frank Herbert")
        member_id = member["user"]["id"]
        apply = TestAPageListingOneHighlightUnderTwoBooks._apply
        apply(db, member_id, _entry(user_book_id=7, highlights=[{"id": 9, "text": "first"}]))
        db.query(Highlight).update({"is_shared": True})
        db.commit()
        live = _entry(user_book_id=7, highlights=[{"id": 9, "text": text}])
        gone = _entry(
            user_book_id=8, title="Emma", is_deleted=True, highlights=[{"id": 9, "text": "first"}]
        )

        apply(db, member_id, *((gone, live) if deleted_first else (live, gone)))

        assert db.query(Highlight.text, Highlight.is_shared).all() == [(text, True)]


@pytest.fixture
def key() -> bytes:
    credentials.store_key(credentials.generate_phrase())
    return credentials.require_key()


class TestTheSealedToken:
    def test_it_opens_only_for_the_member_it_was_sealed_for(self, key):
        envelope = credentials.seal_member_login(key, "readwise", 1, readwise.READWISE_ORIGIN, "t0ken")

        assert (
            credentials.unseal_member_login(key, "readwise", 1, readwise.READWISE_ORIGIN, envelope)
            == "t0ken"
        )
        with pytest.raises(credentials.UnreadableCredential):
            credentials.unseal_member_login(key, "readwise", 2, readwise.READWISE_ORIGIN, envelope)

    def test_the_widest_token_seals_to_the_column_ceiling(self, key):
        envelope = credentials.seal_member_login(
            key, "readwise", 1, readwise.READWISE_ORIGIN, "a" * READWISE_TOKEN_MAX
        )

        assert len(envelope.encode()) == MEMBER_LOGIN_ENVELOPE_MAX_BYTES

    def test_the_header_goes_to_readwise_and_nowhere_else(self):
        token = readwise.Token("t0ken")

        assert token.header_for(f"{readwise.READWISE_ORIGIN}/api/v2/export/") == {
            "Authorization": "Token t0ken"
        }
        assert token.header_for("https://readwise.io.example/api/v2/export/") == {}
        assert "t0ken" not in repr(token)


class TestWhoTheDailyJobIsDueFor:
    def test_a_member_never_pulled_or_pulled_a_day_ago_is_due_and_an_hour_ago_is_not(
        self, db, admin, member, other_user
    ):
        now = datetime(2026, 10, 15, 12, 0, 0)
        for user, last in (
            (admin, None),
            (member, now - timedelta(hours=24)),
            (other_user, now - timedelta(hours=1)),
        ):
            login = readwise.new_login(user["user"]["id"], "v2." + "x" * 40)
            login.last_run_at = last
            db.add(login)
        db.commit()

        assert readwise.due(db, now) == [admin["user"]["id"], member["user"]["id"]]


class TestTheEnvelopeCeilingIsOnBytes:
    """`ck_member_logins_envelope` bounds bytes, so a value under the ceiling in
    characters and over it in bytes is refused. The lead byte is the probe the
    character arm cannot see."""

    def _insert(self, db, member_id: int, envelope: str) -> None:
        db.execute(
            insert(MemberLogin).values(
                user_id=member_id, service="readwise", envelope=envelope
            )
        )
        db.commit()

    def test_the_byte_arm_refuses_what_the_characters_admit(self, db, member):
        tail = "\u00e9" * 10
        envelope = "v2." + "a" * (MEMBER_LOGIN_ENVELOPE_MAX_BYTES - 3 - len(tail) - 1) + tail

        assert len(envelope) < MEMBER_LOGIN_ENVELOPE_MAX_BYTES < len(envelope.encode())
        with pytest.raises(IntegrityError):
            self._insert(db, member["user"]["id"], envelope)

    def test_the_same_length_in_ascii_is_stored(self, db, member):
        self._insert(db, member["user"]["id"], "v2." + "a" * (MEMBER_LOGIN_ENVELOPE_MAX_BYTES - 3))

        assert db.query(MemberLogin).count() == 1
