"""Tests for backend/auth_backends.py.

The LDAP tests drive a fake directory rather than a real one: what is worth
pinning here is our own logic (the empty-password guard, filter escaping,
shadow accounts, admin group mapping), not ldap3's ability to speak LDAP.
"""

import ast
import logging
import os.path
import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from sqlalchemy import event

import auth_backends
from auth import hash_password
from enums import AuthMode
from logvalues import LOGGED_VALUE_MAX, clipped
from models import USERNAME_MAX, User
from tests.helpers import FakeConnection, FakeEntry, directory_with, install_directory

# The forged name and the two predicates, imported rather than copied: they
# carry the argument for which characters forge a line and which do not, and a
# second spelling of that set here would drift against the one that has been
# attacked. `tests/routers/test_auth.py` is their home.
from tests.routers.test_auth import (
    A_NAME_THAT_FORGES_A_LINE,
    _lines_forged_in,
    _one_line,
)

# ── Local ─────────────────────────────────────────────────────────────────────


class TestAuthenticateLocal:
    def test_accepts_the_right_password(self, db):
        db.add(User(username="kim", password_hash=hash_password("password123")))
        db.commit()

        assert auth_backends.authenticate_local(db, "kim", "password123") is not None

    def test_rejects_the_wrong_password(self, db):
        db.add(User(username="kim", password_hash=hash_password("password123")))
        db.commit()

        assert auth_backends.authenticate_local(db, "kim", "wrong") is None

    def test_rejects_an_unknown_username(self, db):
        assert auth_backends.authenticate_local(db, "ghost", "password123") is None

    def test_rejects_an_account_with_no_local_password(self, db):
        """A directory account must not be loggable-into locally, whatever is
        typed. Its password_hash is NULL, and NULL is not a credential."""
        db.add(User(username="kim", password_hash=None, auth_source="ldap"))
        db.commit()

        assert auth_backends.authenticate_local(db, "kim", "") is None
        assert auth_backends.authenticate_local(db, "kim", "anything") is None


# ── LDAP ──────────────────────────────────────────────────────────────────────


class TestAuthenticateLdap:
    def test_an_empty_password_never_reaches_the_directory(self, db, ldap_mode, monkeypatch):
        """The single most important assertion in this file.

        Most LDAP servers treat a bind with an empty password as an ANONYMOUS
        bind and return success. Forwarding one would turn "leave the password
        blank" into a login as anybody in the directory.
        """
        called = False

        def must_not_connect(*args: object, **kwargs: object) -> None:
            nonlocal called
            called = True
            raise AssertionError("connected to the directory with an empty password")

        monkeypatch.setattr(auth_backends, "_connect", must_not_connect)

        assert auth_backends.authenticate_ldap(db, "kim", "") is None
        assert called is False

    def test_a_successful_bind_creates_a_shadow_account(self, db, ldap_mode, monkeypatch):
        directory_with(monkeypatch)

        user = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert user is not None
        assert user.username == "kim"
        assert user.password_hash is None
        assert user.auth_source == AuthMode.LDAP.value

    def test_signing_in_again_reuses_the_same_account(self, db, ldap_mode, monkeypatch):
        directory_with(monkeypatch)
        first = auth_backends.authenticate_ldap(db, "kim", "correct-horse")
        directory_with(monkeypatch)
        second = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert db.query(User).filter(User.username == "kim").count() == 1

    def test_a_wrong_password_fails_the_user_bind(self, db, ldap_mode, monkeypatch):
        directory_with(monkeypatch, user_bind=False)

        assert auth_backends.authenticate_ldap(db, "kim", "wrong") is None

    def test_no_matching_entry_is_a_plain_failure(self, db, ldap_mode, monkeypatch):
        install_directory(monkeypatch, [FakeConnection(bind_results=[True], entries=[])])

        assert auth_backends.authenticate_ldap(db, "ghost", "whatever") is None

    def test_an_ambiguous_filter_is_refused(self, db, ldap_mode, monkeypatch):
        """Two matches means the filter is wrong. Picking one would be picking
        an identity at random."""
        entries = [
            FakeEntry("uid=kim,ou=a", "kim", []),
            FakeEntry("uid=kim,ou=b", "kim", []),
        ]
        install_directory(monkeypatch, [FakeConnection(bind_results=[True], entries=entries)])

        assert auth_backends.authenticate_ldap(db, "kim", "whatever") is None

    def test_the_username_is_escaped_into_the_filter(self, db, ldap_mode, monkeypatch):
        # Without escaping, a crafted username rewrites the search.
        handed_out = directory_with(monkeypatch)

        auth_backends.authenticate_ldap(db, "kim)(|(uid=*", "correct-horse")

        used = handed_out[0].searched_filter or ""
        assert "kim)(|(uid=*" not in used
        assert r"\29" in used or r"\28" in used

    def test_the_directory_spelling_of_the_name_wins(self, db, ldap_mode, monkeypatch):
        """Otherwise "Kim" and "kim" become two accounts with two libraries."""
        entry = FakeEntry("uid=kim,ou=people", "kim", [])
        install_directory(
            monkeypatch,
            [
                FakeConnection(bind_results=[True], entries=[entry]),
                FakeConnection(bind_results=[True], entries=[]),
            ],
        )

        user = auth_backends.authenticate_ldap(db, "KIM", "correct-horse")

        assert user is not None
        assert user.username == "kim"

    def test_an_unreachable_directory_is_a_failed_login_not_a_500(
        self, db, ldap_mode, monkeypatch
    ):
        from ldap3.core.exceptions import LDAPException

        def explode(*args: object, **kwargs: object) -> None:
            raise LDAPException("connection refused")

        monkeypatch.setattr(auth_backends, "_connect", explode)

        assert auth_backends.authenticate_ldap(db, "kim", "correct-horse") is None


@pytest.fixture
def not_first(db):
    """Somebody already exists, so the account under test is not the first.

    The first account in a library is an admin whatever the directory says,
    because proxy and LDAP mode refuse registration and a deployment whose
    group header is not configured would otherwise have no administrator and
    no way to get one. These tests are about group membership, which only
    decides anything from the second account onwards.
    """
    db.add(User(username="somebody-else", password_hash=None, is_admin=False))
    db.commit()


class TestLdapAdminGroup:
    def test_membership_grants_admin(self, db, ldap_mode, monkeypatch, not_first):
        directory_with(monkeypatch, groups=["cn=librarians,ou=groups,dc=example,dc=org"])

        user = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert user is not None
        assert user.is_admin is True

    def test_absence_does_not(self, db, ldap_mode, monkeypatch, not_first):
        directory_with(monkeypatch, groups=["cn=readers,ou=groups,dc=example,dc=org"])

        user = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert user is not None
        assert user.is_admin is False

    def test_admin_is_re_evaluated_on_every_sign_in(
        self, db, ldap_mode, monkeypatch, not_first
    ):
        """Removing someone from the admin group in the directory has to take
        effect, rather than being frozen at whatever it was on first login."""
        directory_with(monkeypatch, groups=["cn=librarians,ou=groups,dc=example,dc=org"])
        promoted = auth_backends.authenticate_ldap(db, "kim", "correct-horse")
        assert promoted is not None
        assert promoted.is_admin is True

        directory_with(monkeypatch, groups=[])
        demoted = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert demoted is not None
        assert demoted.is_admin is False


# ── Proxy ─────────────────────────────────────────────────────────────────────


def request_with(headers: dict[str, str]) -> Request:
    """A stand-in for a Request.

    `user_from_proxy_headers` reads nothing but `.headers`, so a full Request
    would be scaffolding for its own sake. The cast records that this is a
    deliberate partial double rather than an oversight.
    """
    return cast(Request, SimpleNamespace(headers=headers))


class TestProxyHeaders:
    @pytest.fixture(autouse=True)
    def proxy_mode(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "proxy")
        monkeypatch.setenv("PROXY_ADMIN_GROUP", "librarians")

    def test_names_the_member(self, db):
        user = auth_backends.user_from_proxy_headers(db, request_with({"Remote-User": "kim"}))

        assert user is not None
        assert user.username == "kim"
        assert user.auth_source == AuthMode.PROXY.value
        assert user.password_hash is None

    def test_no_header_is_no_user(self, db):
        assert auth_backends.user_from_proxy_headers(db, request_with({})) is None

    def test_an_empty_header_is_no_user(self, db):
        assert (
            auth_backends.user_from_proxy_headers(db, request_with({"Remote-User": "  "}))
            is None
        )

    def test_the_admin_group_grants_admin(self, db):
        user = auth_backends.user_from_proxy_headers(
            db, request_with({"Remote-User": "kim", "Remote-Groups": "readers,librarians"})
        )

        assert user is not None
        assert user.is_admin is True

    def test_other_groups_do_not(self, db, not_first):
        user = auth_backends.user_from_proxy_headers(
            db, request_with({"Remote-User": "kim", "Remote-Groups": "readers"})
        )

        assert user is not None
        assert user.is_admin is False

    def test_a_custom_header_name_is_honoured(self, db, monkeypatch):
        monkeypatch.setenv("PROXY_USER_HEADER", "X-Forwarded-User")

        user = auth_backends.user_from_proxy_headers(
            db, request_with({"X-Forwarded-User": "kim"})
        )

        assert user is not None
        assert user.username == "kim"

    def test_the_same_member_reuses_one_account(self, db):
        first = auth_backends.user_from_proxy_headers(db, request_with({"Remote-User": "kim"}))
        second = auth_backends.user_from_proxy_headers(db, request_with({"Remote-User": "kim"}))

        assert first is not None
        assert second is not None
        assert first.id == second.id


# ── Dispatch ──────────────────────────────────────────────────────────────────


class TestDispatch:
    def test_local_mode_uses_the_local_backend(self, db, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "local")
        db.add(User(username="kim", password_hash=hash_password("password123")))
        db.commit()

        assert auth_backends.authenticate(db, "kim", "password123") is not None

    def test_proxy_mode_never_authenticates_a_password(self, db, monkeypatch):
        """There is nothing to check: the proxy already did the authenticating,
        and accepting a password here would be a second, weaker door."""
        monkeypatch.setenv("AUTH_MODE", "proxy")
        db.add(User(username="kim", password_hash=hash_password("password123")))
        db.commit()

        assert auth_backends.authenticate(db, "kim", "password123") is None

    @pytest.mark.parametrize(
        ("mode", "expected"), [("local", True), ("ldap", False), ("proxy", False)]
    )
    def test_signup_is_only_offered_when_we_own_the_passwords(
        self, monkeypatch, mode, expected
    ):
        monkeypatch.setenv("AUTH_MODE", mode)
        assert auth_backends.local_signup_allowed() is expected


class TestProxyIdentityIsBounded:
    """A header cannot be authenticated from here. It can be bounded.

    On 2026-08-18 a pod inside the cluster sent `Remote-User: intruder`
    straight to the Service and left a permanent admin account behind. The
    NetworkPolicy in front of the Service is what stops that reaching the app
    at all; these are what stop a header that does arrive becoming a row
    nobody can explain.
    """

    @pytest.fixture(autouse=True)
    def proxy_mode(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "proxy")

    @pytest.mark.parametrize(
        "username",
        [
            # Off `USERNAME_MAX`, which is where `_PROXY_USERNAME` takes its
            # own repeat from, so the case stays "one past the bound" when the
            # column moves. A written 51 reddens the first time the column is
            # widened, with nothing broken.
            "x" * (USERNAME_MAX + 1),
            "x" * 4000,
            "has space",
            "-leading-dash",
            "semi;colon",
            "sql'injection",
            "new\nline",
            "../traversal",
            "<script>",
            "",
        ],
    )
    def test_a_name_that_is_not_a_username_is_refused(self, db, username):
        request = request_with({"Remote-User": username})

        assert auth_backends.user_from_proxy_headers(db, request) is None
        assert db.query(User).count() == 0

    @pytest.mark.parametrize(
        "username",
        ["rose", "local_admin", "a.b-c_d", "user@example.com", "x" * USERNAME_MAX],
    )
    def test_an_ordinary_name_still_works(self, db, username):
        request = request_with({"Remote-User": username})

        user = auth_backends.user_from_proxy_headers(db, request)

        assert user is not None
        assert user.username == username

    def test_a_refusal_is_logged_loudly_with_the_peer(self, db, caplog):
        """The only trace the incident left was an INFO line nobody watched."""
        with caplog.at_level(logging.WARNING):
            auth_backends.user_from_proxy_headers(
                db, request_with({"Remote-User": "bad name"})
            )

        assert any(
            "Refused a proxy identity" in record.message for record in caplog.records
        )

    def test_a_refused_header_cannot_forge_a_log_line(self, db, caplog):
        """The only username log line an unauthenticated caller reaches.

        The line exists to record a header the regex has just refused, so a
        forged name is the input it is built for rather than an edge case.
        **Nothing else asserts the escaping**: drop the clipper for a bare
        `%s` and every other arm in the repository stays green, including the
        structural one below, whose population is the wrapped arguments.

        Measured on the template: with the clipper, one line of 128
        characters; without it, two, the second standing on its own as
        `WARNING endpaper.auth granted (35 chars) from unknown`.
        """
        with caplog.at_level(logging.WARNING, logger="endpaper.auth"):
            auth_backends.user_from_proxy_headers(
                db, request_with({"Remote-User": A_NAME_THAT_FORGES_A_LINE})
            )

        records = [r for r in caplog.records if r.name == "endpaper.auth"]
        assert records, "the refusal did not fire, so this proved nothing"
        assert all(_one_line(record) for record in records)
        assert not _lines_forged_in(caplog.text)

    def test_creating_an_account_is_logged_at_warning(self, db, caplog):
        with caplog.at_level(logging.WARNING):
            auth_backends.upsert_directory_user(
                db, "newcomer", is_admin=True, source=AuthMode.PROXY
            )

        created = [r for r in caplog.records if "Created account" in r.message]
        assert created
        assert created[0].levelno == logging.WARNING

    def test_an_unchanged_identity_writes_nothing(self, db):
        """Every request reaches this in proxy mode.

        An unconditional commit was a write per request against the one SQLite
        writer, and an audit trail that could never say when anything actually
        changed.
        """
        auth_backends.upsert_directory_user(
            db, "rose", is_admin=False, source=AuthMode.PROXY
        )

        writes: list[str] = []

        def record(conn, cursor, statement, *rest):
            writes.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", record)
        try:
            auth_backends.upsert_directory_user(
                db, "rose", is_admin=False, source=AuthMode.PROXY
            )
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

        assert not any(
            statement.lstrip().upper().startswith("UPDATE") for statement in writes
        )

    def test_a_change_of_admin_rights_is_logged(self, db, caplog, monkeypatch):
        monkeypatch.setenv("PROXY_ADMIN_GROUP", "librarians")
        db.add(User(username="somebody-else", password_hash=None, is_admin=False))
        db.commit()
        auth_backends.upsert_directory_user(
            db, "rose", is_admin=False, source=AuthMode.PROXY
        )

        with caplog.at_level(logging.WARNING):
            auth_backends.upsert_directory_user(
                db, "rose", is_admin=True, source=AuthMode.PROXY
            )

        assert any("Admin rights for" in record.message for record in caplog.records)


class TestAdminBootstrap:
    """A library nobody can administer is the failure mode this prevents.

    Proxy and LDAP mode refuse registration, and `is_admin` comes only from
    the configured group. A stranger deploying this image with
    `AUTH_MODE=proxy` and no groups header would otherwise get a catalogue
    with no settings, no metadata key, no backup and no way to grant
    themselves any of it, recoverable only by editing the database by hand.
    """

    @pytest.fixture(autouse=True)
    def proxy_mode(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "proxy")

    def test_the_first_account_is_an_admin_whatever_the_directory_says(self, db):
        user = auth_backends.upsert_directory_user(
            db, "founder", is_admin=False, source=AuthMode.PROXY
        )
        assert user is not None
        assert user.is_admin is True

    def test_the_second_account_is_not(self, db):
        auth_backends.upsert_directory_user(
            db, "founder", is_admin=False, source=AuthMode.PROXY
        )
        second = auth_backends.upsert_directory_user(
            db, "later", is_admin=False, source=AuthMode.PROXY
        )
        assert second is not None
        assert second.is_admin is False

    def test_a_configured_group_still_grants_admin(self, db, monkeypatch):
        monkeypatch.setenv("PROXY_ADMIN_GROUP", "librarians")
        auth_backends.upsert_directory_user(
            db, "founder", is_admin=False, source=AuthMode.PROXY
        )
        second = auth_backends.upsert_directory_user(
            db, "later", is_admin=True, source=AuthMode.PROXY
        )
        assert second is not None
        assert second.is_admin is True


class TestSwitchingToADirectoryDoesNotDemote:
    """Turning proxy or LDAP auth on stripped the existing admin, silently.

    `is_admin` is re-applied on every request, and a header carrying no group
    means False, so the local admin lost their rights on their first page
    load with no message and no way back.
    """

    def test_an_existing_admin_keeps_their_rights(self, db, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "proxy")
        monkeypatch.delenv("PROXY_ADMIN_GROUP", raising=False)
        db.add(User(username="owner", password_hash="x", is_admin=True))
        db.add(User(username="other", password_hash="x", is_admin=False))
        db.commit()

        user = auth_backends.upsert_directory_user(
            db, "owner", is_admin=False, source=AuthMode.PROXY
        )

        assert user is not None
        assert user.is_admin is True

    def test_a_configured_group_can_still_demote(self, db, monkeypatch):
        """Demotion is a directory decision, not an accident of configuration."""
        monkeypatch.setenv("AUTH_MODE", "proxy")
        monkeypatch.setenv("PROXY_ADMIN_GROUP", "librarians")
        db.add(User(username="owner", password_hash="x", is_admin=True))
        db.add(User(username="other", password_hash="x", is_admin=False))
        db.commit()

        user = auth_backends.upsert_directory_user(
            db, "owner", is_admin=False, source=AuthMode.PROXY
        )

        assert user is not None
        assert user.is_admin is False

    def test_a_non_admin_is_not_promoted_by_the_same_rule(self, db, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "proxy")
        monkeypatch.delenv("PROXY_ADMIN_GROUP", raising=False)
        db.add(User(username="owner", password_hash="x", is_admin=True))
        db.add(User(username="other", password_hash="x", is_admin=False))
        db.commit()

        user = auth_backends.upsert_directory_user(
            db, "other", is_admin=False, source=AuthMode.PROXY
        )

        assert user is not None
        assert user.is_admin is False


# ── Test accounts are never adopted ───────────────────────────────────────────


class TestATestAccountIsNeverAdopted:
    """The collision this feature would otherwise have introduced.

    `upsert_directory_user` matches on **username**, so a directory identity
    named like an admin-created test account would adopt its row: `auth_source`
    flips, and the test account's books, loans and notes become that member's.
    The test account is renamed aside instead. See `docs/decisions.md`.
    """

    @pytest.fixture(autouse=True)
    def proxy_mode(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "proxy")

    @pytest.fixture
    def alice(self, db) -> User:
        """A test account, and an admin so the row is never the first one."""
        db.add(User(username="admin", password_hash=hash_password("password123"), is_admin=True))
        account = User(
            username="alice",
            password_hash=hash_password("password123"),
            is_test_account=True,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    def test_the_directory_identity_gets_a_row_of_its_own(self, db, alice):
        user = auth_backends.upsert_directory_user(
            db, "alice", is_admin=False, source=AuthMode.PROXY
        )

        assert user is not None
        assert user.id != alice.id
        assert user.username == "alice"
        assert user.auth_source == AuthMode.PROXY.value
        assert user.password_hash is None

    def test_the_test_account_is_renamed_rather_than_flipped(self, db, alice):
        auth_backends.upsert_directory_user(
            db, "alice", is_admin=False, source=AuthMode.PROXY
        )

        db.refresh(alice)
        assert alice.username == "alice-2"
        assert alice.is_test_account is True
        assert alice.auth_source == AuthMode.LOCAL.value
        assert alice.password_hash is not None

    def test_it_keeps_the_books_it_had(self, db, alice):
        from models import Book

        db.add(Book(title="Only alice can see this", is_private=True, added_by_user_id=alice.id))
        db.commit()

        adopted = auth_backends.upsert_directory_user(
            db, "alice", is_admin=False, source=AuthMode.PROXY
        )

        assert adopted is not None
        book = db.query(Book).filter(Book.title == "Only alice can see this").one()
        assert book.added_by_user_id == alice.id
        assert book.added_by_user_id != adopted.id

    def test_the_next_free_suffix_is_used(self, db, alice):
        db.add(User(username="alice-2", password_hash=hash_password("password123")))
        db.commit()

        auth_backends.upsert_directory_user(
            db, "alice", is_admin=False, source=AuthMode.PROXY
        )

        db.refresh(alice)
        assert alice.username == "alice-3"

    def test_the_new_name_still_fits_the_column(self, db):
        """`users.username` is `String(USERNAME_MAX)`, and SQLite would not complain.

        **The width is read rather than written.** This arm is the one whose
        subject is the fit, so a literal here reddens it on the commit that
        widens the column, saying a name does not fit when it does.
        """
        db.add(User(username="admin", password_hash=hash_password("password123"), is_admin=True))
        long_name = "a" * USERNAME_MAX
        db.add(
            User(
                username=long_name,
                password_hash=hash_password("password123"),
                is_test_account=True,
            )
        )
        db.commit()

        auth_backends.upsert_directory_user(
            db, long_name, is_admin=False, source=AuthMode.PROXY
        )

        renamed = db.query(User).filter(User.is_test_account.is_(True)).one()
        # **Against the column, not against the constant this fixture is built
        # from.** Both sides reading `USERNAME_MAX` checks the truncation
        # against itself, so moving the model's own width leaves this green
        # while the name no longer fits the column it invokes.
        declared = getattr(User.__table__.columns["username"].type, "length", None)
        # A column with no declared length has no fit to test, so say so rather
        # than comparing against None.
        assert declared is not None
        assert len(renamed.username) <= declared
        assert renamed.username.endswith("-2")

    def test_the_rename_is_logged_loudly(self, db, alice, caplog):
        """A username changing without anybody asking has to be findable."""
        with caplog.at_level(logging.WARNING):
            auth_backends.upsert_directory_user(
                db, "alice", is_admin=False, source=AuthMode.PROXY
            )

        renames = [r for r in caplog.records if "Renamed the test account" in r.message]
        assert renames
        assert renames[0].levelno == logging.WARNING
        assert "'alice-2'" in renames[0].getMessage()

    def test_an_ordinary_local_account_is_still_adopted(self, db):
        """The other half of the rule: a local account from before the switch
        to a directory keeps its row, its books and its history."""
        db.add(User(username="admin", password_hash=hash_password("password123"), is_admin=True))
        existing = User(username="kim", password_hash=hash_password("password123"))
        db.add(existing)
        db.commit()
        db.refresh(existing)

        adopted = auth_backends.upsert_directory_user(
            db, "kim", is_admin=False, source=AuthMode.PROXY
        )

        assert adopted is not None
        assert adopted.id == existing.id
        assert adopted.auth_source == AuthMode.PROXY.value



# ── A directory name the column cannot hold ───────────────────────────────────


def _declared_username_width() -> int:
    """`users.username`'s own width, read rather than written.

    **Against the column, not against the constant the fixtures are built
    from**, which is the reason `test_the_new_name_still_fits_the_column`
    gives: both sides reading `USERNAME_MAX` checks the bound against itself
    and stays green on the commit that moves the column.
    """
    declared = getattr(User.__table__.columns["username"].type, "length", None)
    # A column with no declared width has no bound to test, so say so rather
    # than comparing against None.
    assert declared is not None
    return int(declared)


class TestADirectoryNameWiderThanTheColumnIsRefused:
    """SQLite does not enforce `String(USERNAME_MAX)`, so the bound is applied
    in `upsert_directory_user`, which is where both directory doors meet.

    **Refused rather than truncated, and the arm below that matters most is
    the adoption one.** The funnel matches on `User.username`, which is
    unique, so a truncation would land two directory identities sharing a
    prefix on one row and hand the second the first's books, with a 200 and
    nothing in the log.
    """

    #: How much of an opening the two refusals compared below may share. Both
    #: report a refusal and both open `Refused a `, so that much is what they
    #: have in common while having nothing in common; anything past it is a
    #: grep that matches both. Measured over the two messages: ten characters
    #: today, sixteen under the reword that reads as green, twenty four under
    #: this branch's own earlier wording.
    LONGEST_SHARED_OPENING = "Refused a "

    def test_a_name_one_character_past_the_column_writes_no_row(self, db):
        too_wide = "a" * (_declared_username_width() + 1)

        assert (
            auth_backends.upsert_directory_user(
                db, too_wide, is_admin=False, source=AuthMode.LDAP
            )
            is None
        )
        assert db.query(User).count() == 0

    def test_a_name_of_exactly_the_column_width_signs_in(self, db):
        """The accepting case, without which refusing everything satisfies the
        rule above."""
        widest = "a" * _declared_username_width()

        user = auth_backends.upsert_directory_user(
            db, widest, is_admin=False, source=AuthMode.LDAP
        )

        assert user is not None
        assert user.username == widest
        assert db.query(User).filter(User.username == widest).one()

    def test_a_refused_name_does_not_adopt_the_row_its_prefix_owns(self, db):
        """The discriminating case between refusing and truncating.

        Truncating the second name would match the first row and flip its
        `auth_source`, its books and its loans onto whoever signed in second.
        """
        # An admin already exists, so the bootstrap rule does not make the
        # first directory row one and `is_admin` below is this arm's subject
        # rather than that rule's.
        db.add(User(username="admin", password_hash=hash_password("password123"), is_admin=True))
        db.commit()

        width = _declared_username_width()
        first = auth_backends.upsert_directory_user(
            db, "a" * width, is_admin=False, source=AuthMode.LDAP
        )
        assert first is not None

        second = auth_backends.upsert_directory_user(
            db, "a" * width + "b", is_admin=True, source=AuthMode.LDAP
        )

        assert second is None
        db.refresh(first)
        assert first.is_admin is False
        assert db.query(User).count() == 2

    def test_a_row_already_wider_than_the_column_can_no_longer_sign_in(self, db):
        """The residue, pinned as deliberate rather than left to be found.

        The check sits above the lookup, so a row written before this change
        or restored through Core is refused before it is ever matched. It
        cuts both ways by one mechanism: it locks out a leftover row of the
        2026-08-18 class, which is wanted, and a legitimate member whose
        directory name is long, which is not. The member sees a generic
        failed login, and the WARNING names the width and the name so an
        operator can find them and rename the row.

        Moving the check below the lookup, so that it bound creation only,
        is a different design: the wide row would sign in and go on writing
        its own log lines.
        """
        wide = "a" * (_declared_username_width() + 1)
        db.add(
            User(
                username=wide,
                password_hash=None,
                auth_source=AuthMode.LDAP.value,
            )
        )
        db.commit()

        assert (
            auth_backends.upsert_directory_user(
                db, wide, is_admin=False, source=AuthMode.LDAP
            )
            is None
        )
        assert db.query(User).filter(User.username == wide).one()

    def test_the_ldap_door_answers_none_rather_than_raising(
        self, db, ldap_mode, monkeypatch
    ):
        """A refused sign-in, not a 500. Both callers already answer
        `User | None`, so nothing downstream learns a new shape."""
        entry = FakeEntry(
            "uid=kim,ou=people,dc=example,dc=org",
            "k" * (_declared_username_width() + 1),
            [],
        )
        install_directory(
            monkeypatch,
            [
                FakeConnection(bind_results=[True], entries=[entry]),
                FakeConnection(bind_results=[True], entries=[]),
            ],
        )

        assert auth_backends.authenticate_ldap(db, "kim", "password123") is None
        assert db.query(User).count() == 0

    def test_the_refusal_names_the_width_and_the_name_it_refused(self, db, caplog):
        """Both, and the name is the half an operator cannot act without.

        The refusal is a lockout of a legitimate member, so a width with no
        name says something is broken and not which directory entry. It is at
        WARNING precisely so somebody goes and looks.

        **Driven as LDAP because that is the door that reaches it.**
        `_PROXY_USERNAME` derives its repeat from the column, so no
        proxy-sourced name of this width survives the regex and an arm driving
        one here would pin a message for a state production cannot enter.

        **The clipped form, not the raw one.** The line logs `clipped(...)`,
        and asserting the raw name passes only while the column plus the two
        quotes stays under `LOGGED_VALUE_MAX`, which is a coupling to a second
        constant this whole class exists to avoid: the width is read off the
        column precisely so that widening the column does not redden anything.
        The clip keeps 200 characters of the repr and the repr opens with a
        quote, so 199 of the name survive: the raw assertion fails from a
        column of 199 with nothing broken.
        """
        width = _declared_username_width()
        refused = "a" * (width + 1)

        with caplog.at_level(logging.WARNING, logger="endpaper.auth"):
            auth_backends.upsert_directory_user(
                db, refused, is_admin=False, source=AuthMode.LDAP
            )

        refusals = [
            r for r in caplog.records if "users.username cannot hold" in r.getMessage()
        ]
        assert refusals
        assert refusals[0].levelno == logging.WARNING
        assert str(width + 1) in refusals[0].getMessage()
        assert clipped(refused) in refusals[0].getMessage()

    def test_the_two_refusals_do_not_share_a_grep_prefix(self, db, caplog):
        """One is an unauthenticated header, the other a directory attribute.

        With the source value at the front the funnel's refusal would open
        `Refused a proxy identity` too, and an alert rule or log filter keyed
        on that prefix would conflate two events of different provenance.

        **The funnel is driven source-agnostically here and that is
        deliberate**, unlike the arm above, which takes the door that reaches
        it. The collision only ever existed in the proxy spelling, so an LDAP
        refusal could not show it, and the funnel is a public function a
        fourth door could hand a proxy-sourced name to.

        **The property, not one literal.** Pinning the string the collision
        happened to take passes on the next rewording that collides: `Refused
        a proxy sign-in: users.username cannot hold ...` shares `Refused a
        proxy ` and reads as green. What an alert rule keys on is a shared
        opening, so what is asserted is that these two share no more of one
        than the words that say a refusal happened.
        """
        with caplog.at_level(logging.WARNING, logger="endpaper.auth"):
            auth_backends.user_from_proxy_headers(
                db, request_with({"Remote-User": "bad name"})
            )
            auth_backends.upsert_directory_user(
                db,
                "a" * (_declared_username_width() + 1),
                is_admin=False,
                source=AuthMode.PROXY,
            )

        messages = [r.getMessage() for r in caplog.records if r.name == "endpaper.auth"]
        assert len(messages) == 2, messages
        header_refusal, funnel_refusal = messages
        assert "Refused a proxy identity" in header_refusal, (
            "the header refusal is not the message this compared, so the "
            "comparison below proved nothing"
        )

        shared = os.path.commonprefix([header_refusal, funnel_refusal])
        assert len(shared) <= len(self.LONGEST_SHARED_OPENING), (
            "the two refusals now share a grep prefix, so one alert rule "
            "matches an unauthenticated header event and a directory "
            f"attribute event alike. shared {shared!r}, at most "
            f"{self.LONGEST_SHARED_OPENING!r}"
        )


#: Where a logger method's format template sits among its arguments. **This is
#: the population of emitters, and widening it to anything on the logger costs
#: two false refusals**: `if logger.isEnabledFor(...)`, the standard guarded
#: logging idiom, reddens correct code with a message naming a format string
#: the line does not have, and a no-argument method such as
#: `getEffectiveLevel` raises `ValueError` off the unpacking, which is an error
#: rather than a failure and sends a reader hunting a broken test file. `log`
#: is here with an offset rather than excluded, because its template is the
#: second argument after the level: leaving it out would leave a spelling that
#: moves any site out of the rule.
_TEMPLATE_AT = {
    "debug": 0,
    "info": 0,
    "warning": 0,
    "warn": 0,
    "error": 0,
    "exception": 0,
    "critical": 0,
    "fatal": 0,
    "log": 1,
}

#: A `%` conversion, as `str.__mod__` reads one. **The conversion character is
#: the set `%` accepts, not `[a-zA-Z]`**, because a wider class invents a
#: conversion out of prose: a space is a legal flag, so `90% busy` reads as
#: `% b`. That narrowing is half the answer; the other half is the rule
#: skipping a call with no arguments, since `90% full` is `% f` under any
#: faithful reading of `%` and is still correct in a template `logging` never
#: formats.
#:
#: **What the narrowing gives up, stated because the class it replaced caught
#: it.** A template mixing a conversion `%` accepts with one it does not pairs
#: cleanly here, because only the accepted one is counted. `%s%z` with one
#: argument is the shape. At emit time the formatting fails, `logging` reports
#: it through `handleError` and **drops the record**, so nothing raises into
#: the caller and the line is simply gone: measured, `TypeError: not enough
#: arguments` where the unaccepted specifier leaves too few, and
#: `ValueError: unsupported format character` where it does not. The wider
#: class reddened that by counting two specifiers against one argument, and
#: reddened correct prose for the same reason. Catching it belongs to a rule
#: about templates that format, not to this one, which is about which values
#: get repr'd.
_SPECIFIER = re.compile(
    r"%(?:\((?P<key>[^)]*)\))?[-#0 +]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[hlL]?"
    r"(?P<conversion>[diouxXeEfFgGcrsa%])"
)


def _logger_names(tree: ast.Module) -> set[str]:
    """Every name in the module bound to a `getLogger(...)` result.

    **Derived rather than written as `logger`.** A second logger object, under
    any name, carries the same hazard, and a rule reading one literal receiver
    does not see it.

    It reads a binding: `name = getLogger(...)` or `name: Logger =
    getLogger(...)`, with the factory spelled bare or through a module. **A
    logger reached any other way is refused rather than skipped** by the rule
    that uses this, which reports an emitter call whose receiver is not in
    this set. A logger obtained inline, taken as a parameter, stored on an
    object or aliased is such a receiver, so each of those is a sentence
    somebody has to write here rather than a site that quietly leaves the
    population.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            bound = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound = [node.target.id]
        else:
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        callee = call.func
        factory = (isinstance(callee, ast.Attribute) and callee.attr == "getLogger") or (
            isinstance(callee, ast.Name) and callee.id == "getLogger"
        )
        if factory:
            names.update(bound)
    return names


def _emitting_calls(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    """Every call to a method in `_TEMPLATE_AT`, with the function around it.

    **The enclosing function is carried because it is what makes an
    exemption's reason true.** A reason such as "the proxy pattern has already
    matched this value" is a fact about one function, and an exemption keyed
    on the expression alone grants it to every function in the module that
    spells the value the same way. The two named `username` here mean
    different things: one has been through `_PROXY_USERNAME`, the other is the
    request body.

    **The population is the method name, not the receiver.** Deciding the
    receiver is a logger is the caller's job and it refuses what it cannot
    recognise, so a receiver this cannot resolve leaves the rule loudly rather
    than silently.

    **That refusal catches objects that are not loggers, and it is affordable
    only because this rule reads one module.** Every emitter-named attribute
    call in `auth_backends.py` is on `logger`, measured. Elsewhere in the tree
    they are not: `z3950_provisional.py` makes two calls to
    `bindings.error(...)`, declared to return a four element diagnostic tuple,
    and a `warnings.warn(...)` would read the same way anywhere it appeared.
    **Two calls rather than two line numbers: a position is anchored by
    nothing and points at wrong code in silence after any edit above it.**

    **So generalising this rule past one module costs a receiver test before
    the refusal**, which is a change here rather than another exemption: the
    exemption map is keyed on a function and a repr argument and has nowhere
    to put a receiver.

    A call in a decorator is attributed to the function it decorates, and a
    call in a lambda to whatever function encloses the lambda. Neither shape
    logs anything in this module.
    """
    found: list[tuple[str, ast.Call]] = []

    def descend(node: ast.AST, enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _TEMPLATE_AT
            ):
                found.append((enclosing, child))
            inner = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else enclosing
            )
            descend(child, inner)

    descend(tree, "<module>")
    return found


class TestTheDirectorySuccessPathCannotForgeALogLine:
    """The hazard this change created, armed before it could be paid for.

    Every site in `upsert_directory_user` interpolated the name with `%r`, and
    that repr was the only thing between a directory-supplied control
    character and a forged log line. Clipping moves each site to `%s`, so a
    half-done swap reintroduces the forgery the previous wave fixed.

    **Nothing else covers this branch.**
    `tests/routers/test_auth.py::TestAnUntrustedUsernameCannotForgeALogLine`
    sweeps the default auth mode only, and every arm of
    `TestADirectoryFailureCannotBeMadeToForgeALogLine` beside it is a failure
    path. The directory success path, where an account is created and its name
    logged, was unswept and safe by accident.

    Records are filtered to this app's own logger, and the level is raised on
    that logger alone. Raising the root logger to DEBUG turns on SQLAlchemy's
    statement log, which carries the bound parameter raw and would redden
    these arms for something they are not about.
    """

    #: A directory-supplied name, so the wire value is beside the point: the
    #: entry's attribute is what reaches the log.
    FORGED = A_NAME_THAT_FORGES_A_LINE

    #: The only arguments in `auth_backends` that may sit under `%r`, each with
    #: the reason it is bare. **The reason lives with the exemption**, so
    #: granting one is a sentence somebody has to write rather than a line
    #: somebody deletes.
    #:
    #: **Keyed by the enclosing function as well as the expression, because
    #: the function is what makes the reason true.** Both reasons below are
    #: facts about one function and neither survives being moved: keyed on the
    #: expression alone, the second grants every `username` in the module a
    #: repr, including the one in `authenticate_ldap`, which is the request
    #: body and reaches that line without a session. A reader checking this
    #: list before writing a repr would be told the exemption was already
    #: granted.
    DELIBERATELY_BARE = {
        ("authenticate_ldap", "email_attribute"): (
            "the configured attribute name, not a value off the wire. It comes "
            "from this deployment's own settings, and `%r` is what makes a "
            "setting that is empty or carries a stray space visible."
        ),
        ("user_from_proxy_headers", "username"): (
            "`_PROXY_USERNAME` has matched it earlier in this function, so it "
            "is at most `USERNAME_MAX` characters of `[A-Za-z0-9._@-]` and "
            "clipping it could not change anything it can carry. **The regex "
            "is what makes this true and it runs nowhere else**, so the same "
            "name in another function is unbounded."
        ),
    }

    def _directory_resolving(self, monkeypatch, name: str, email: str | None = None):
        entry = FakeEntry(
            "uid=kim,ou=people,dc=example,dc=org", name, [], email=email
        )
        return install_directory(
            monkeypatch,
            [
                FakeConnection(bind_results=[True], entries=[entry]),
                FakeConnection(bind_results=[True], entries=[]),
            ],
        )

    def _our_records(self, caplog):
        return [r for r in caplog.records if r.name == "endpaper.auth"]

    def test_a_created_account_carries_no_control_character_into_the_log(
        self, db, ldap_mode, monkeypatch, caplog
    ):
        self._directory_resolving(monkeypatch, self.FORGED)

        with caplog.at_level(logging.DEBUG, logger="endpaper.auth"):
            user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None, "the success path did not run, so this proved nothing"
        records = self._our_records(caplog)
        created = [r for r in records if "Created account" in r.getMessage()]
        assert created, "the creation line did not fire, so this proved nothing"
        assert all(_one_line(record) for record in records)
        assert not _lines_forged_in("\n".join(r.getMessage() for r in records))

    def test_a_renamed_test_account_carries_none_either(
        self, db, ldap_mode, monkeypatch, caplog
    ):
        """The second success-path line, and the one that names a stored value
        rather than the directory's: a restored archive can still hold a row
        whose username nothing bounded."""
        db.add(
            User(
                username=self.FORGED,
                password_hash=hash_password("password123"),
                is_test_account=True,
            )
        )
        db.commit()
        self._directory_resolving(monkeypatch, self.FORGED)

        with caplog.at_level(logging.DEBUG, logger="endpaper.auth"):
            auth_backends.authenticate_ldap(db, "kim", "password123")

        records = self._our_records(caplog)
        renames = [r for r in records if "Renamed the test account" in r.getMessage()]
        assert renames, "the rename line did not fire, so this proved nothing"
        assert all(_one_line(record) for record in records)
        assert not _lines_forged_in("\n".join(r.getMessage() for r in records))

    def test_no_record_carries_more_of_a_wide_name_than_the_clip_allows(
        self, db, ldap_mode, monkeypatch, caplog
    ):
        """The refused-address warning fires before the funnel refuses the
        name, so it is the site the funnel's bound does not reach.

        The run of a single character is what is measured, not the length of
        the record: the wording around the value is free to change, and a
        bound on the whole message would move with it.
        """
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        wide = "w" * 10_000
        self._directory_resolving(monkeypatch, wide, email="not-an-address")

        with caplog.at_level(logging.DEBUG, logger="endpaper.auth"):
            auth_backends.authenticate_ldap(db, "kim", "password123")

        records = self._our_records(caplog)
        assert [r for r in records if "not an address" in r.getMessage()], (
            "the refused-address line did not fire, so this proved nothing"
        )
        runs = [
            len(run)
            for record in records
            for run in re.findall("w+", record.getMessage())
        ]
        assert runs, "no record named the value at all, so this proved nothing"
        assert max(runs) <= LOGGED_VALUE_MAX

    def test_every_exemption_carries_a_reason(self):
        """The half that is mechanical. What the reason says is a reader's,
        the same split `TestEveryDirectoryDoorWritesThroughOneFunnel` makes
        over its own notes: a rule matching words in one passes on a sentence
        that says nothing."""
        assert all(reason.strip() for reason in self.DELIBERATELY_BARE.values())

    def test_only_the_two_bare_values_sit_under_a_repr_conversion(self):
        """The other direction of the same half-done swap, which no behavioural
        arm can see.

        `clipped` reprs and then slices, so a site left at `%r` double-reprs
        and reads as escaped when it is escaped twice. A site moved to `%s`
        with the `clipped` omitted is the forgery, and the arms above catch
        that one; this catches the pair the other way round, at every site in
        the module rather than at the ones a test drives.

        **The population is every argument under `%r`, not every argument
        wrapped in `clipped`.** Keying on the wrapper makes one defect pass or
        red on spelling: it sees `clipped(username)` written inline, and not
        the identical value bound to a local first, reached through a
        conditional expression, spelled `logvalues.clipped(...)`, or handed to
        a one-line helper. Each of those is a repr of a repr and each is
        invisible to a rule reading the argument. Reading the conversion
        instead makes the argument's spelling irrelevant: what is asserted is
        that the set of things this module reprs is the two it means to repr,
        each carrying its reason here, so **a new `%r` is reported whatever
        carries it** and granting it an exemption is where somebody writes
        down why.

        **Each exemption is keyed by the function it sits in**, because the
        reason granting it is a fact about that function and not about the
        module. See `DELIBERATELY_BARE`.

        **What it refuses rather than skips**, so that leaving the population
        costs a sentence: a template that is not a string literal, an emitter
        call on a receiver `_logger_names` cannot resolve to a logger, a call
        carrying no positional template, and a template using a mapping key,
        whose arguments cannot be paired by position.

        **What it does not reach**: a call with a literal template and no
        arguments, which `logging` never formats, so a literal percent in its
        prose is correct; and every module other than this one.
        """
        tree = ast.parse(Path(auth_backends.__file__).read_text())
        receivers = _logger_names(tree)
        assert receivers, "no logger is bound in the module, so this walked nothing"
        calls = _emitting_calls(tree)
        assert calls, "no emitting call was found, so this walked nothing"

        reprs: dict[tuple[str, str], int] = {}
        for enclosing, node in calls:
            callee = node.func
            assert isinstance(callee, ast.Attribute)  # `_emitting_calls` selects these
            receiver = callee.value
            assert isinstance(receiver, ast.Name), (
                f"line {node.lineno}: `{ast.unparse(callee)}` calls a method "
                f"this rule reads as an emitter, on a receiver it cannot "
                f"resolve to a logger. If it is a logger, teach "
                f"`_logger_names` the binding. If it is not, the population "
                f"selects on the method name alone and has outgrown this "
                f"module: narrow it at `_emitting_calls`, which says what "
                f"that costs"
            )
            assert receiver.id in receivers, (
                f"line {node.lineno}: `{ast.unparse(callee)}` calls a method "
                f"this rule reads as an emitter, on a receiver it cannot "
                f"resolve to a logger. If it is a logger, teach "
                f"`_logger_names` the binding. If it is not, the population "
                f"selects on the method name alone and has outgrown this "
                f"module: narrow it at `_emitting_calls`, which says what "
                f"that costs"
            )
            offset = _TEMPLATE_AT[callee.attr]
            assert len(node.args) > offset, (
                f"line {node.lineno}: `{callee.attr}` carries no positional "
                f"template, so this rule cannot pair anything with it"
            )
            template, arguments = node.args[offset], node.args[offset + 1 :]
            # The literal check comes before the argument-less skip and the
            # order is load bearing: skipping first sends every non-literal
            # template carrying no positional arguments out of the rule in
            # silence, and an f-string is a template that can carry a repr of
            # a repr.
            assert isinstance(template, ast.Constant), (
                f"line {node.lineno}: the format string is not a string literal, "
                f"so this rule cannot pair it with its arguments"
            )
            assert isinstance(
                template.value, str
            ), (
                f"line {node.lineno}: the format string is not a string literal, "
                f"so this rule cannot pair it with its arguments"
            )
            if not arguments:
                # `logging` formats only when there are arguments, so a literal
                # template with none carries no conversion to pair, and a
                # literal percent in its prose is correct.
                continue
            matches = [
                match
                for match in _SPECIFIER.finditer(template.value)
                if match.group("conversion") != "%"
            ]
            assert not any(match.group("key") for match in matches), (
                f"line {node.lineno}: a mapping key takes one dict rather than "
                f"positional arguments, so this rule cannot pair it"
            )
            conversions = [match.group("conversion") for match in matches]
            assert len(conversions) == len(arguments), (
                f"line {node.lineno}: {len(conversions)} specifiers against "
                f"{len(arguments)} arguments"
            )
            for conversion, argument in zip(conversions, arguments, strict=True):
                if conversion == "r":
                    reprs[(enclosing, ast.unparse(argument))] = node.lineno

        assert set(reprs) == set(self.DELIBERATELY_BARE), (
            "`%r` reprs its argument, and `clipped` has already repr'd, so a "
            "value reaching one escapes twice and reads as escaped. Either "
            "move the site to `%s`, or record here, against the function it "
            "sits in, why this one is bare. "
            f"under %r: {reprs}, recorded: {sorted(self.DELIBERATELY_BARE)}"
        )


# ── Addresses ─────────────────────────────────────────────────────────────────


class TestWhoOwnsAnAddress:
    """`directory_owns_email` is the whole of the "who may edit it" rule.

    Empty configuration means the directory has no opinion, which is the rule
    `_admin_group_set` already carries for demotion. Everything else in this
    feature reads the answer from here: the API refuses a write with 409 where
    it is true, and `upsert_directory_user` writes the column only where it is.
    """

    def test_a_local_account_is_nobody_elses_to_change(self):
        assert auth_backends.directory_owns_email(AuthMode.LOCAL.value) is False

    def test_ldap_owns_nothing_until_an_attribute_is_named(self, ldap_mode):
        assert auth_backends.directory_owns_email(AuthMode.LDAP.value) is False

    def test_ldap_owns_it_once_an_attribute_is_named(self, ldap_mode, monkeypatch):
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        assert auth_backends.directory_owns_email(AuthMode.LDAP.value) is True

    def test_proxy_owns_nothing_until_a_header_is_named(self, proxy_mode):
        assert auth_backends.directory_owns_email(AuthMode.PROXY.value) is False

    def test_proxy_owns_it_once_a_header_is_named(self, proxy_mode, monkeypatch):
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")
        assert auth_backends.directory_owns_email(AuthMode.PROXY.value) is True

    def test_the_two_are_configured_apart(self, ldap_mode, monkeypatch):
        """Naming an LDAP attribute says nothing about a proxy deployment, and
        one function answering for both would make it say something."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        assert auth_backends.directory_owns_email(AuthMode.PROXY.value) is False

    def test_a_stored_source_no_directory_is_configured_for_is_editable(self):
        """`users.auth_source` carries no CheckConstraint, so a restore can
        write a value that is not an `AuthMode` at all. That row belongs to no
        configured directory, which is the answer this returns."""
        assert auth_backends.directory_owns_email("something-a-restore-wrote") is False


class TestTheDirectoryWritesTheAddress:
    def test_an_address_is_stored_when_the_attribute_is_named(
        self, db, ldap_mode, monkeypatch
    ):
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="kim@example.org")

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email == "kim@example.org"

    def test_nothing_is_requested_or_stored_when_it_is_not(
        self, db, ldap_mode, monkeypatch
    ):
        """The shipped default. The search asks for exactly what it always
        asked for, so an upgrade changes no directory traffic."""
        handed_out = directory_with(monkeypatch, email="kim@example.org")

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email is None
        assert handed_out[0].searched_attributes == ["uid", "memberOf"]

    def test_the_attribute_is_added_to_the_search_when_it_is_named(
        self, db, ldap_mode, monkeypatch
    ):
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        handed_out = directory_with(monkeypatch, email="kim@example.org")

        auth_backends.authenticate_ldap(db, "kim", "password123")

        assert handed_out[0].searched_attributes == ["uid", "memberOf", "mail"]

    def test_the_address_is_re_applied_on_every_sign_in(self, db, ldap_mode, monkeypatch):
        """The `is_admin` rule, on the address: the directory is authoritative,
        so a change there takes effect at the next login."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="kim@example.org")
        auth_backends.authenticate_ldap(db, "kim", "password123")

        directory_with(monkeypatch, email="kim@work.example.org")
        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email == "kim@work.example.org"

    def test_an_entry_with_no_address_clears_a_stored_one(
        self, db, ldap_mode, monkeypatch
    ):
        """Absence is the directory speaking, exactly as absence from the admin
        group is a demotion once a group is configured."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="kim@example.org")
        auth_backends.authenticate_ldap(db, "kim", "password123")

        directory_with(monkeypatch, email=None)
        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email is None

    def test_an_empty_attribute_is_the_same_as_an_absent_one(
        self, db, ldap_mode, monkeypatch
    ):
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="")

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email is None

    def test_an_unconfigured_directory_leaves_a_stored_address_alone(
        self, db, ldap_mode, monkeypatch
    ):
        """The case the whole default turns on. A member typed their address in
        the app; the deployment names no attribute; signing in must not read
        that silence as the directory saying they have none."""
        db.add(
            User(username="kim", password_hash=None, auth_source=AuthMode.LDAP.value,
                 email="kim@example.org")
        )
        db.commit()
        directory_with(monkeypatch)

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email == "kim@example.org"

    @pytest.mark.parametrize(
        "value",
        [
            "kim@example.org\nBcc: elsewhere@example.org",
            "kim\x00@example.org",
            "kim\x1b@example.org",
            "kim@example.org,sam@example.org",
            "not an address",
        ],
    )
    def test_a_directory_value_that_is_not_an_address_is_refused(
        self, db, ldap_mode, monkeypatch, value
    ):
        """A directory attribute is outside this app. `Bcc: someone` in a `To`
        header is what an unchecked one buys, and a NUL is what a character
        class of `\\s@,;<>` lets through."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email=value)

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email is None

    def test_a_directory_value_with_surrounding_whitespace_is_stored_trimmed(
        self, db, ldap_mode, monkeypatch
    ):
        """Not refused, and the distinction is worth stating because a fixture
        here asserted the opposite for one round.

        The property that matters is what ends up in the column, and `strip()`
        runs before the check, so a trailing newline cannot survive into it: a
        directory attribute with a stray newline is a formatting artefact and
        trimming it is right. What `looks_like_address` must refuse on its own
        is what trimming cannot remove, which is the case above.
        """
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="  kim@example.org\n")

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email == "kim@example.org"

    def test_a_refused_directory_value_is_a_warning_and_not_a_shrug(
        self, db, ldap_mode, monkeypatch, caplog
    ):
        """"The directory named no address" and "the directory named something
        this app will not store" both clear the column and are not the same
        event. They were logged identically at INFO until a reviewer said so."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="kim@example.org\nBcc: elsewhere@example.org")

        with caplog.at_level(logging.INFO, logger="endpaper.auth"):
            auth_backends.authenticate_ldap(db, "kim", "password123")

        refusals = [r for r in caplog.records if "not an address" in r.getMessage()]
        assert refusals
        assert refusals[0].levelno == logging.WARNING
        assert "'mail'" in refusals[0].getMessage()
        # The length, never the value: an address is a member's, and this line
        # goes to a log an operator reads.
        assert "@" not in refusals[0].getMessage()

    def test_a_directory_naming_no_address_is_not_logged_as_a_refusal(
        self, db, ldap_mode, monkeypatch, caplog
    ):
        """The other half of the distinction, so the rule above cannot be
        satisfied by warning about everything."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")

        with caplog.at_level(logging.INFO, logger="endpaper.auth"):
            directory_with(monkeypatch, email=None)
            auth_backends.authenticate_ldap(db, "kim", "password123")

        assert not [r for r in caplog.records if "not an address" in r.getMessage()]

    def test_an_absurdly_long_directory_value_is_refused(self, db, ldap_mode, monkeypatch):
        """SQLite does not enforce `String(320)`, so the bound is applied here.
        The 2026-08-18 incident was a 4000 character header writing a 4000
        character account."""
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="k" * 4000 + "@example.org")

        user = auth_backends.authenticate_ldap(db, "kim", "password123")

        assert user is not None
        assert user.email is None

    def test_the_log_records_the_change_and_never_the_address(
        self, db, ldap_mode, monkeypatch, caplog
    ):
        monkeypatch.setenv("LDAP_EMAIL_ATTRIBUTE", "mail")
        directory_with(monkeypatch, email="kim@example.org")
        auth_backends.authenticate_ldap(db, "kim", "password123")

        with caplog.at_level(logging.INFO, logger="endpaper.auth"):
            directory_with(monkeypatch, email="kim@work.example.org")
            auth_backends.authenticate_ldap(db, "kim", "password123")

        lines = [record.getMessage() for record in caplog.records]
        assert any("directory set the address for 'kim'" in line for line in lines)
        assert not any("@" in line for line in lines)


class TestTheProxyHeaderCarriesAnAddress:
    def test_the_header_is_stored_when_one_is_named(self, db, proxy_mode, monkeypatch):
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")
        request = cast(
            Request,
            SimpleNamespace(
                headers={"Remote-User": "kim", "Remote-Email": "kim@example.org"},
                client=SimpleNamespace(host="10.0.0.1"),
            ),
        )

        user = auth_backends.user_from_proxy_headers(db, request)

        assert user is not None
        assert user.email == "kim@example.org"

    def test_a_refused_header_is_a_warning_naming_the_peer(
        self, db, proxy_mode, monkeypatch, caplog
    ):
        """The same shape the refused `Remote-User` above already logs, on the
        same request and from the same unauthenticated source. It also clears
        the stored address, so INFO would have said "no address here" for a
        header carrying a newline."""
        monkeypatch.setenv("PROXY_EMAIL_HEADER", "Remote-Email")
        request = cast(
            Request,
            SimpleNamespace(
                headers={
                    "Remote-User": "kim",
                    "Remote-Email": "kim@example.org\nBcc: elsewhere@example.org",
                },
                client=SimpleNamespace(host="10.0.0.1"),
            ),
        )

        with caplog.at_level(logging.INFO, logger="endpaper.auth"):
            user = auth_backends.user_from_proxy_headers(db, request)

        assert user is not None
        assert user.email is None
        refusals = [r for r in caplog.records if "not an address" in r.getMessage()]
        assert refusals
        assert refusals[0].levelno == logging.WARNING
        assert "10.0.0.1" in refusals[0].getMessage()
        assert "@" not in refusals[0].getMessage()

    def test_the_header_is_ignored_when_none_is_named(self, db, proxy_mode):
        """An upstream sending `Remote-Email` to a deployment that never asked
        for it is not the deployment's decision, so it is not honoured."""
        request = cast(
            Request,
            SimpleNamespace(
                headers={"Remote-User": "kim", "Remote-Email": "kim@example.org"},
                client=SimpleNamespace(host="10.0.0.1"),
            ),
        )

        user = auth_backends.user_from_proxy_headers(db, request)

        assert user is not None
        assert user.email is None
