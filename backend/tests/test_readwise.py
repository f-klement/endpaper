"""The Readwise pull's own rules, below the routes: reading a page, the token's
seal, and who the daily job is due for.

What a pull writes is reached through the routes, in
`tests/routers/test_readwise.py`.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

import credentials
import readwise
from models import (
    HIGHLIGHT_TEXT_MAX,
    MEMBER_LOGIN_ENVELOPE_MAX_BYTES,
    READWISE_TOKEN_MAX,
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
