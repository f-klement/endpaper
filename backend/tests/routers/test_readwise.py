"""A member's Readwise token and pull, reached as the account page reaches them.

Readwise is a fake behind `respx`: `FakeReadwise` answers the export as the
API documents it, books with their highlights nested, one book a page with
`nextPageCursor`, `updatedAfter` read against each highlight's `updated_at`,
and a deletion sent only under `includeDeleted=true`. It records every request
so a test can read what left this server.
"""

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import count

import httpx
import pytest
import respx
from sqlalchemy import event, text

import credentials
import readwise
from database import SessionLocal
from enums import HighlightSource
from models import BookIdentifier, DeletedHighlight, Highlight, MemberLogin, ReadwiseBook
from ratelimit import import_limiter

TOKEN = "rw0123456789abcdefTOKEN"

#: An edit long before any pull, so an incremental pull does not send it.
OLD = "2020-01-01T00:00:00Z"


def now() -> str:
    """An edit made now, after any pull's cursor."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC).replace(tzinfo=None)


def mark(ident: int = 101, **fields: object) -> dict[str, object]:
    return {
        "id": ident,
        "text": "Fear is the mind-killer.",
        "note": "",
        "location": 12,
        "location_type": "page",
        "highlighted_at": "2026-03-01T21:15:09Z",
        "updated_at": OLD,
        "is_deleted": False,
    } | fields


def entry(user_book_id: int = 7, *marks: dict[str, object], **fields: object) -> dict[str, object]:
    return {
        "user_book_id": user_book_id,
        "title": "Dune",
        "author": "Frank Herbert",
        "category": "books",
        "asin": None,
        "is_deleted": False,
        "highlights": list(marks) if marks else [mark()],
    } | fields


class FakeReadwise:
    """The export as documented. `put` replaces a book whole; `refusing` may
    answer a status instead for the requests it picks."""

    def __init__(self) -> None:
        self.library: dict[int, dict[str, object]] = {}
        self.refusing: Callable[[httpx.QueryParams], int | None] = lambda _params: None
        self.requests: list[httpx.Request] = []
        #: The auth route, set by the fixture, for its call count.
        self.auth: respx.Route | None = None

    def put(self, *entries: dict[str, object]) -> None:
        for one in entries:
            self.library[int(one["user_book_id"])] = one  # type: ignore[call-overload]

    def _shown(self, one: dict[str, object], after: datetime | None, deleted: bool):
        marks = [
            each
            for each in one["highlights"]  # type: ignore[attr-defined]
            if (deleted or not each["is_deleted"])
            and (after is None or _when(each["updated_at"]) > after)
        ]
        if one["is_deleted"] and not deleted:
            return None
        if after is not None and not marks:
            return None
        return one | {"highlights": marks}

    def export(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        refused = self.refusing(params)
        if refused is not None:
            return httpx.Response(refused)
        deleted = params.get("includeDeleted") == "true"
        after = _when(params["updatedAfter"]) if "updatedAfter" in params else None
        if "ids" in params:
            wanted = {int(one) for one in params["ids"].split(",")}
            chosen = [one for ident, one in sorted(self.library.items()) if ident in wanted]
            after = None
        else:
            chosen = [one for _ident, one in sorted(self.library.items())]
        results = [
            shown for one in chosen if (shown := self._shown(one, after, deleted)) is not None
        ]
        start = int(params.get("pageCursor", "0"))
        following = str(start + 1) if start + 1 < len(results) else None
        return httpx.Response(
            200,
            json={
                "count": len(results),
                "nextPageCursor": following,
                "results": results[start : start + 1],
            },
        )


@pytest.fixture
def fake() -> Iterator[FakeReadwise]:
    service = FakeReadwise()
    with respx.mock(assert_all_called=False) as mock:
        service.auth = mock.get(f"{readwise.READWISE_ORIGIN}/api/v2/auth/").respond(204)
        mock.route(method="GET", host="readwise.io", path="/api/v2/export/").mock(
            side_effect=service.export
        )
        yield service


@pytest.fixture
def encryption_key() -> None:
    credentials.store_key(credentials.generate_phrase())


def save(client, headers):
    return client.put("/api/readwise/token", json={"token": TOKEN}, headers=headers)


def pull(client, headers) -> dict:
    res = client.post("/api/readwise/sync", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def linked(client, member, encryption_key, fake) -> dict:
    """The member, with a token saved, and the limiter's count of that save
    forgotten, so a test may pull three times."""
    assert save(client, member["headers"]).status_code == 200
    import_limiter.reset()
    return member


def login(db) -> MemberLogin:
    db.expire_all()
    return db.query(MemberLogin).one()


def dune(make_book, headers, **fields) -> dict:
    return make_book(headers, title="Dune", author="Frank Herbert", **fields)


class TestTheToken:
    def test_saving_one_needs_an_encryption_key(self, client, member, fake):
        res = save(client, member["headers"])

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "no_key"

    def test_a_token_readwise_refuses_is_not_stored(self, client, member, encryption_key, db):
        with respx.mock:
            respx.get(f"{readwise.READWISE_ORIGIN}/api/v2/auth/").respond(401)
            res = save(client, member["headers"])

        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "token_refused"
        assert db.query(MemberLogin).count() == 0

    def test_a_saved_token_is_sealed_and_never_served(self, client, linked, db):
        account = client.get("/api/readwise/account", headers=linked["headers"])

        assert account.json()["has_token"] is True
        assert TOKEN not in account.text
        assert TOKEN not in db.query(MemberLogin).one().envelope

    def test_removing_it_keeps_the_highlights_already_pulled(
        self, client, linked, make_book, fake, db
    ):
        dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])

        res = client.delete("/api/readwise/token", headers=linked["headers"])

        assert res.status_code == 204
        assert db.query(MemberLogin).count() == 0
        assert db.query(ReadwiseBook).count() == 0
        assert db.query(Highlight).count() == 1

    def test_it_goes_with_its_member(self, linked, db):
        db.execute(text("DELETE FROM users WHERE id = :id"), {"id": linked["user"]["id"]})
        db.commit()

        assert db.query(MemberLogin).count() == 0

    def test_replacing_it_starts_the_pull_over(self, client, linked, make_book, fake):
        dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])

        assert save(client, linked["headers"]).status_code == 200
        pull(client, linked["headers"])

        assert "updatedAfter" not in fake.requests[-1].url.params

    def test_it_never_reaches_a_log(self, client, linked, fake, caplog):
        caplog.set_level(logging.DEBUG)
        fake.refusing = lambda _params: 500

        pull(client, linked["headers"])

        assert "Readwise export answered 500" in caplog.text
        assert TOKEN not in caplog.text


class TestTheLimiter:
    """Both routes that make this server call Readwise share the import
    limiter, three a minute, and the fourth never reaches Readwise."""

    def test_the_fourth_save_in_a_minute_is_refused_unasked(
        self, client, member, encryption_key, fake
    ):
        statuses = [save(client, member["headers"]).status_code for _ in range(4)]

        assert statuses == [200, 200, 200, 429]
        assert fake.auth is not None
        assert fake.auth.call_count == 3

    def test_the_fourth_pull_in_a_minute_is_refused_unasked(self, client, linked, fake):
        fake.put(entry())
        statuses = [
            client.post("/api/readwise/sync", headers=linked["headers"]).status_code
            for _ in range(4)
        ]

        assert statuses == [200, 200, 200, 429]
        assert len(fake.requests) == 3


class TestAPull:
    def test_without_a_token_it_is_refused(self, client, member):
        res = client.post("/api/readwise/sync", headers=member["headers"])

        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "no_token"

    def test_a_highlight_arrives_private_keyed_on_readwise_s_id(
        self, client, linked, make_book, fake, db
    ):
        book = dune(make_book, linked["headers"])
        fake.put(entry())

        assert pull(client, linked["headers"])["created"] == 1
        row = db.query(Highlight).one()
        assert (row.book_id, row.source, row.source_key, row.is_shared, row.page) == (
            book["id"], "readwise", "101", False, 12,
        )
        assert str(row.highlighted_at) == "2026-03-01 21:15:09"

    def test_only_the_token_and_readwise_s_own_values_leave(
        self, client, linked, make_book, fake
    ):
        dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])
        pull(client, linked["headers"])

        for request in fake.requests:
            assert request.headers["authorization"] == f"Token {TOKEN}"
            assert request.content == b""
            assert set(request.url.params) <= {"includeDeleted", "updatedAfter", "pageCursor", "ids"}

    def test_every_page_is_read(self, client, linked, make_book, fake, db):
        dune(make_book, linked["headers"])
        make_book(linked["headers"], title="Emma", author="Jane Austen")
        fake.put(entry(), entry(8, mark(202), title="Emma", author="Jane Austen"))

        assert pull(client, linked["headers"])["created"] == 2
        assert db.query(Highlight).count() == 2

    def test_the_next_pull_asks_from_ten_minutes_before_this_one_began(
        self, client, linked, fake, monkeypatch
    ):
        # A clock that moves on every reading, so a cursor read at the end of
        # the pull rather than at its start is a different value.
        ticks = (datetime(2026, 1, 2, 3, 4, 5) + timedelta(minutes=n) for n in count())
        monkeypatch.setattr(readwise, "_utcnow", lambda: next(ticks))
        pull(client, linked["headers"])
        pull(client, linked["headers"])

        assert fake.requests[-1].url.params["updatedAfter"] == "2026-01-02T02:54:05Z"

    def test_a_deletion_at_readwise_removes_the_row(self, client, linked, make_book, fake, db):
        dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])
        fake.put(entry(7, mark(is_deleted=True, updated_at=now())))

        assert pull(client, linked["headers"])["deleted"] == 1
        assert db.query(Highlight).count() == 0

    def test_a_highlight_deleted_here_is_not_pulled_back(
        self, client, linked, make_book, fake, db
    ):
        book = dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])
        row = db.query(Highlight).one()
        res = client.delete(
            f"/api/books/{book['id']}/highlights/{row.id}", headers=linked["headers"]
        )
        assert res.status_code == 204
        fake.put(entry(7, mark(note="edited at Readwise", updated_at=now())))

        counts = pull(client, linked["headers"])

        assert (counts["created"], counts["skipped"]) == (0, 1)
        assert db.query(Highlight).count() == 0

    def test_a_deletion_under_a_book_moved_out_of_books_removes_the_row(
        self, client, linked, make_book, fake, db
    ):
        dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])
        fake.put(entry(7, mark(is_deleted=True, updated_at=now()), category="articles"))

        pull(client, linked["headers"])

        assert db.query(Highlight).count() == 0

    def test_two_books_answering_the_title_are_no_answer(self, client, linked, make_book, fake, db):
        dune(make_book, linked["headers"])
        dune(make_book, linked["headers"])
        fake.put(entry())

        assert pull(client, linked["headers"])["waiting_count"] == 1
        assert db.query(Highlight).count() == 0
        account = client.get("/api/readwise/account", headers=linked["headers"]).json()
        assert account["waiting"] == [{"title": "Dune", "author": "Frank Herbert"}]

    def test_an_asin_on_one_book_decides_it(self, client, linked, make_book, fake, db):
        dune(make_book, linked["headers"])
        kindle = dune(
            make_book, linked["headers"], identifiers=[{"scheme": "asin", "value": "B00B7NPRY8"}]
        )
        fake.put(entry(asin="b00b7npry8"))

        pull(client, linked["headers"])

        assert db.query(Highlight).one().book_id == kindle["id"]

    def test_an_asin_on_two_books_is_no_answer_whatever_the_title_says(
        self, client, linked, make_book, fake, db
    ):
        asin = [{"scheme": "asin", "value": "B00B7NPRY8"}]
        dune(make_book, linked["headers"], identifiers=asin)
        # Written directly, because an add refuses a second Book carrying an
        # ASIN; two still arise from rows made before it did.
        messiah = make_book(linked["headers"], title="Dune Messiah", author="Frank Herbert")
        db.add(BookIdentifier(book_id=messiah["id"], scheme="asin", value="B00B7NPRY8"))
        db.commit()
        fake.put(entry(asin="B00B7NPRY8"))

        assert pull(client, linked["headers"])["waiting_count"] == 1

    def test_another_member_s_private_book_is_never_matched(
        self, client, linked, other_user, make_book, fake, db
    ):
        dune(make_book, other_user["headers"], is_private=True)
        fake.put(entry())

        assert pull(client, linked["headers"])["waiting_count"] == 1
        assert db.query(Highlight).count() == 0

    def test_a_waiting_book_is_asked_for_by_id_once_a_book_matches(
        self, client, linked, make_book, fake, db
    ):
        fake.put(entry())
        pull(client, linked["headers"])
        dune(make_book, linked["headers"])

        assert pull(client, linked["headers"])["created"] == 1
        assert fake.requests[-1].url.params["ids"] == "7"

    def test_a_book_matched_on_a_pull_that_stopped_is_asked_for_again(
        self, client, linked, make_book, fake, db
    ):
        fake.put(entry())
        pull(client, linked["headers"])
        dune(make_book, linked["headers"])
        fake.put(entry(7, mark(), mark(102, updated_at=now())))
        fake.refusing = lambda params: 429 if "ids" in params else None
        assert pull(client, linked["headers"])["outcome"] == "rate_limited"
        fake.refusing = lambda _params: None

        pull(client, linked["headers"])

        assert fake.requests[-1].url.params["ids"] == "7"
        assert {row.source_key for row in db.query(Highlight)} == {"101", "102"}

    def test_a_highlight_moved_to_another_book_is_private_again(
        self, client, linked, make_book, fake, db
    ):
        first = dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])
        row = db.query(Highlight).one()
        res = client.put(
            f"/api/books/{first['id']}/highlights/{row.id}/sharing",
            json={"is_shared": True},
            headers=linked["headers"],
        )
        assert res.status_code == 200, res.text
        assert client.delete(f"/api/books/{first['id']}", headers=linked["headers"]).status_code in (
            200,
            204,
        )
        second = dune(make_book, linked["headers"])

        pull(client, linked["headers"])

        db.expire_all()
        moved = db.query(Highlight).one()
        assert (moved.book_id, moved.is_shared) == (second["id"], False)


class TestTheCursorMovesOnlyWhenEverythingArrived:
    def test_a_refused_token_leaves_it(self, client, linked, fake, db):
        fake.refusing = lambda _params: 401

        assert pull(client, linked["headers"])["outcome"] == "token_refused"
        assert (login(db).last_outcome, login(db).synced_through) == ("token_refused", None)

    def test_a_rate_limit_leaves_it(self, client, linked, fake, db):
        fake.put(entry())
        pull(client, linked["headers"])
        before = login(db).synced_through
        fake.refusing = lambda _params: 429

        assert pull(client, linked["headers"])["outcome"] == "rate_limited"
        assert login(db).synced_through == before

    def test_a_page_bound_leaves_it_and_the_next_pull_resumes(
        self, client, linked, fake, db, monkeypatch
    ):
        fake.put(entry())
        pull(client, linked["headers"])
        before = login(db).synced_through
        fake.put(
            entry(7, mark(updated_at=now())),
            entry(8, mark(202, updated_at=now()), title="Emma"),
        )
        monkeypatch.setattr(readwise, "MAX_PAGES", 1)

        assert pull(client, linked["headers"])["outcome"] == "incomplete"
        assert login(db).synced_through == before
        monkeypatch.setattr(readwise, "MAX_PAGES", 500)
        asked = len(fake.requests)

        assert pull(client, linked["headers"])["outcome"] == "synced"
        assert fake.requests[asked].url.params.get("pageCursor") == "1"


    def test_a_resumed_walk_completes_with_the_time_it_first_began(
        self, client, linked, fake, db, monkeypatch
    ):
        ticks = (datetime(2026, 1, 2, 3, 4, 5) + timedelta(minutes=n) for n in count())
        monkeypatch.setattr(readwise, "_utcnow", lambda: next(ticks))
        pull(client, linked["headers"])
        fake.put(
            entry(7, mark(updated_at=now())),
            entry(8, mark(202, updated_at=now()), title="Emma"),
        )
        monkeypatch.setattr(readwise, "MAX_PAGES", 1)
        pull(client, linked["headers"])
        began = login(db).last_run_at
        assert began is not None
        monkeypatch.setattr(readwise, "MAX_PAGES", 500)

        assert pull(client, linked["headers"])["outcome"] == "synced"
        assert login(db).synced_through == began - readwise.OVERLAP

    def test_a_resumed_cursor_readwise_refuses_is_dropped(
        self, client, linked, fake, db, monkeypatch
    ):
        pull(client, linked["headers"])
        fake.put(
            entry(7, mark(updated_at=now())),
            entry(8, mark(202, updated_at=now()), title="Emma"),
        )
        monkeypatch.setattr(readwise, "MAX_PAGES", 1)
        pull(client, linked["headers"])
        monkeypatch.setattr(readwise, "MAX_PAGES", 500)
        fake.refusing = lambda params: 400 if "pageCursor" in params else None
        assert pull(client, linked["headers"])["outcome"] == "unavailable"
        fake.refusing = lambda _params: None
        import_limiter.reset()
        asked = len(fake.requests)

        assert pull(client, linked["headers"])["outcome"] == "synced"
        assert "pageCursor" not in fake.requests[asked].url.params

    def test_a_retried_page_keeps_its_resume_cursor(
        self, client, linked, make_book, fake, db, monkeypatch
    ):
        """A hand delete beats the first page's commit, and the page is written
        again: the rollback took the cursor and the walk's start with it, so the
        retry has to set both again or the next pull starts over."""
        dune(make_book, linked["headers"])
        fake.put(entry())
        pull(client, linked["headers"])
        held = db.query(Highlight).one()
        member_id, row_id = held.user_id, held.id
        fake.put(
            entry(7, mark(note="edited at Readwise", updated_at=now())),
            entry(8, mark(202, updated_at=now()), title="Emma"),
        )
        monkeypatch.setattr(readwise, "MAX_PAGES", 1)
        fired: list[int] = []

        def the_delete_commits_first(session, *_):
            # Every session of the app fires this; only the page's write, the
            # one holding a changed highlight, is the one to beat.
            if fired or not any(isinstance(row, Highlight) for row in session.dirty):
                return
            fired.append(row_id)
            with SessionLocal() as other:
                other.add(
                    DeletedHighlight(
                        user_id=member_id, source=HighlightSource.READWISE, source_key="101"
                    )
                )
                other.flush()
                other.query(Highlight).filter(Highlight.id == row_id).delete()
                other.commit()

        event.listen(SessionLocal, "before_flush", the_delete_commits_first)
        try:
            assert pull(client, linked["headers"])["outcome"] == "incomplete"
        finally:
            event.remove(SessionLocal, "before_flush", the_delete_commits_first)

        assert fired == [row_id]
        resumed = login(db)
        assert (resumed.resume_cursor, resumed.walk_started_at) == ("1", resumed.last_run_at)

    def test_a_book_whose_history_arrived_is_not_asked_for_again(
        self, client, linked, make_book, fake, db
    ):
        fake.put(entry())
        pull(client, linked["headers"])
        dune(make_book, linked["headers"])
        pull(client, linked["headers"])
        asked = len(fake.requests)

        pull(client, linked["headers"])

        assert all("ids" not in request.url.params for request in fake.requests[asked:])
