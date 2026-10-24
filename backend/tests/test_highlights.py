"""The highlight ledger below the routes: its lookups, and what a race between
two deletes costs."""

from datetime import datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

import highlights
import koreader_highlights
from database import SessionLocal
from enums import HighlightSource
from models import HIGHLIGHT_SOURCE_KEY_MAX, QUOTE_TEXT_MAX, Book, DeletedHighlight, Highlight
from schemas import KoreaderHighlightIn

DIGEST = "0123456789abcdef0123456789abcdef"
MARK = KoreaderHighlightIn(
    pos0="/body/p[1]/text().0",
    pos1="/body/p[1]/text().9",
    text="Fear is the mind-killer.",
    highlighted_at="2026-03-01 22:15:09",
)


def test_a_write_past_one_lookup_chunk_finds_every_held_row(db, member, make_book):
    """The row past the bound is found, so the second write is unchanged
    throughout rather than one insert of a key already held."""
    book_id = make_book(member["headers"])["id"]
    member_id = member["user"]["id"]
    marks = {
        f"key {n}": highlights.Mark(text=f"passage {n}", note=None, page=None, highlighted_at=None)
        for n in range(highlights._LOOKUP_CHUNK + 1)
    }
    highlights.write(db, member_id, HighlightSource.READWISE, book_id, marks)
    db.commit()

    again = highlights.write(db, member_id, HighlightSource.READWISE, book_id, marks)

    assert (again.created, again.unchanged) == (0, len(marks))


def test_an_import_lengthening_a_shared_highlight_past_the_quote_ceiling_makes_it_private(
    db, member, make_book
):
    """Sharing is refused past the ceiling, so an import carrying the passage
    past it takes the share back rather than showing it to the shelf."""
    book_id = make_book(member["headers"])["id"]
    member_id = member["user"]["id"]

    def passage(text):
        return {"7": highlights.Mark(text=text, note=None, page=None, highlighted_at=None)}

    highlights.write(db, member_id, HighlightSource.READWISE, book_id, passage("short"))
    db.commit()
    db.query(Highlight).update({"is_shared": True})
    db.commit()

    highlights.write(db, member_id, HighlightSource.READWISE, book_id, passage("x" * (QUOTE_TEXT_MAX + 1)))
    db.commit()

    assert db.query(Highlight.is_shared).scalar() is False


def _a_share_commits_once_the_row_is_read(db) -> list[int]:
    """Commit the author's share from another session the moment the write
    loads the row, so the write holds it as private and the database has it
    shared. Answers the ids it shared, to show the race was run."""
    db.expunge_all()
    shared: list[int] = []

    def the_share_commits(session, instance):
        if shared or not isinstance(instance, Highlight):
            return
        shared.append(instance.id)
        with SessionLocal() as other:
            other.query(Highlight).filter(Highlight.id == instance.id).update({"is_shared": True})
            other.commit()

    event.listen(db, "loaded_as_persistent", the_share_commits)
    return shared


def test_a_share_committed_while_an_import_moves_it_is_taken_back(db, member, make_book):
    """The write read the row private on one Book, the author shares it there,
    and the write then moves it to another: it lands private, whatever the
    write had read."""
    first = make_book(member["headers"])["id"]
    second = make_book(member["headers"], title="Emma")["id"]
    member_id = member["user"]["id"]
    marks = {"7": highlights.Mark(text="passage", note=None, page=None, highlighted_at=None)}
    highlights.write(db, member_id, HighlightSource.READWISE, first, marks)
    db.commit()
    shared = _a_share_commits_once_the_row_is_read(db)

    highlights.write(db, member_id, HighlightSource.READWISE, second, marks)
    db.commit()

    assert len(shared) == 1
    assert db.query(Highlight.book_id, Highlight.is_shared).one() == (second, False)


def test_a_second_import_of_an_unchanged_passage_past_the_quote_ceiling_writes_nothing(db, member, make_book):
    """Clearing the share past the ceiling is part of a write, so a passage
    already past it and unchanged is not written again: its row keeps the time
    it was last changed."""
    book_id = make_book(member["headers"])["id"]
    member_id = member["user"]["id"]
    marks = {"7": highlights.Mark(text="x" * (QUOTE_TEXT_MAX + 1), note=None, page=None, highlighted_at=None)}
    highlights.write(db, member_id, HighlightSource.READWISE, book_id, marks)
    db.commit()
    long_ago = datetime(2020, 1, 1)
    db.query(Highlight).update({"updated_at": long_ago})
    db.commit()

    again = highlights.write(db, member_id, HighlightSource.READWISE, book_id, marks)
    db.commit()

    assert again.unchanged == 1
    assert db.query(Highlight.updated_at).scalar() == long_ago


def test_a_share_committed_while_an_import_lengthens_it_is_taken_back(db, member, make_book):
    """The write read the row private, the author shares it, and the write then
    carries it past the quote ceiling: it lands private, whatever the write had
    read."""
    book_id = make_book(member["headers"])["id"]
    member_id = member["user"]["id"]

    def passage(text):
        return {"7": highlights.Mark(text=text, note=None, page=None, highlighted_at=None)}

    highlights.write(db, member_id, HighlightSource.READWISE, book_id, passage("short"))
    db.commit()
    shared = _a_share_commits_once_the_row_is_read(db)

    highlights.write(db, member_id, HighlightSource.READWISE, book_id, passage("x" * (QUOTE_TEXT_MAX + 1)))
    db.commit()

    assert len(shared) == 1
    assert db.query(Highlight.is_shared).scalar() is False


def test_a_removal_takes_only_the_member_s_own_row_under_a_shared_key(db, member, other_user, make_book):
    """Two members linking one Readwise account hold the same ids, and one
    member's pull reporting a deletion leaves the other's row."""
    book_id = make_book(member["headers"])["id"]
    marks = {"7": highlights.Mark(text="passage", note=None, page=None, highlighted_at=None)}
    for account in (member, other_user):
        highlights.write(db, account["user"]["id"], HighlightSource.READWISE, book_id, marks)
    db.commit()

    removed = highlights.remove(db, member["user"]["id"], HighlightSource.READWISE, ["7"])
    db.commit()

    assert removed == 1
    assert [row.user_id for row in db.query(Highlight)] == [other_user["user"]["id"]]


def test_a_hand_delete_committed_before_the_held_lookup_stays_deleted(db, member, make_book):
    """The write reads remembered keys and held rows in two statements, and the
    delete commits just before the held one: the mark is left out rather than
    written back as new."""
    book_id = make_book(member["headers"])["id"]
    member_id = member["user"]["id"]
    marks = {"7": highlights.Mark(text="passage", note=None, page=None, highlighted_at=None)}
    highlights.write(db, member_id, HighlightSource.READWISE, book_id, marks)
    db.commit()
    row_id = db.query(Highlight).one().id
    deleted: list[bool] = []

    def the_delete_commits_before_the_held_lookup(state):
        if deleted or not state.is_select:
            return
        if state.statement.column_descriptions[0]["entity"] is not Highlight:
            return
        deleted.append(True)
        with SessionLocal() as other:
            other.add(DeletedHighlight(user_id=member_id, source=HighlightSource.READWISE, source_key="7"))
            other.flush()
            other.query(Highlight).filter(Highlight.id == row_id).delete()
            other.commit()

    event.listen(db, "do_orm_execute", the_delete_commits_before_the_held_lookup)

    counts = highlights.write(db, member_id, HighlightSource.READWISE, book_id, marks)
    db.commit()

    assert (counts.created, counts.left_deleted) == (0, 1)
    assert db.query(Highlight).count() == 0


def test_a_second_delete_racing_the_first_finds_nothing_rather_than_failing(db, member, make_book):
    """Both find the row, the other commits first, and this commit then meets
    the unique index on the remembered key: answered as no such row."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    key = next(iter(koreader_highlights.keyed(DIGEST, [MARK])))
    koreader_highlights.import_koreader(db, book, member_id, DIGEST, [MARK])
    row_id = db.query(Highlight).one().id

    def the_other_delete_commits_first(session, *_):
        with SessionLocal() as other:
            other.add(DeletedHighlight(user_id=member_id, source=HighlightSource.KOREADER, source_key=key))
            other.query(Highlight).filter(Highlight.id == row_id).delete()
            other.commit()

    event.listen(db, "before_flush", the_other_delete_commits_first, once=True)

    assert highlights.delete_own(db, book, member_id, row_id) is False
    assert db.query(DeletedHighlight).count() == 1


class TestTheRememberedKeyIsBoundedInBytes:
    """`ck_deleted_highlights_bounds` bounds bytes, for a value the character
    arm and the NUL clause both admit: one `x'C0'` and its continuation bytes
    are one character to SQLite's `length()` and as many bytes as were written.
    """

    def _insert(self, db, member_id: int, total: int) -> None:
        raw = b"\xc0" + b"\x80" * (total - 1)
        db.execute(
            text(
                "INSERT INTO deleted_highlights (user_id, source, source_key) "
                f"VALUES (:member, 'koreader', CAST(x'{raw.hex()}' AS TEXT))"
            ),
            {"member": member_id},
        )
        db.commit()

    def test_one_byte_past_the_budget_is_refused(self, db, member):
        with pytest.raises(IntegrityError) as refusal:
            self._insert(db, member["user"]["id"], 4 * HIGHLIGHT_SOURCE_KEY_MAX + 1)

        assert "ck_deleted_highlights_bounds" in str(refusal.value)

    def test_the_budget_itself_is_stored(self, db, member):
        self._insert(db, member["user"]["id"], 4 * HIGHLIGHT_SOURCE_KEY_MAX)

        assert db.query(DeletedHighlight).count() == 1
