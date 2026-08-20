"""Tests for backend/auth_backends.py.

The LDAP tests drive a fake directory rather than a real one: what is worth
pinning here is our own logic (the empty-password guard, filter escaping,
shadow accounts, admin group mapping), not ldap3's ability to speak LDAP.
"""

import logging
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from sqlalchemy import event

import auth_backends
from auth import hash_password
from enums import AuthMode
from models import User
from tests.helpers import FakeConnection, FakeEntry, directory_with, install_directory

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

        assert first is not None and second is not None
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

        assert user is not None and user.is_admin is True

    def test_absence_does_not(self, db, ldap_mode, monkeypatch, not_first):
        directory_with(monkeypatch, groups=["cn=readers,ou=groups,dc=example,dc=org"])

        user = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert user is not None and user.is_admin is False

    def test_admin_is_re_evaluated_on_every_sign_in(
        self, db, ldap_mode, monkeypatch, not_first
    ):
        """Removing someone from the admin group in the directory has to take
        effect, rather than being frozen at whatever it was on first login."""
        directory_with(monkeypatch, groups=["cn=librarians,ou=groups,dc=example,dc=org"])
        promoted = auth_backends.authenticate_ldap(db, "kim", "correct-horse")
        assert promoted is not None and promoted.is_admin is True

        directory_with(monkeypatch, groups=[])
        demoted = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert demoted is not None and demoted.is_admin is False


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

        assert user is not None and user.is_admin is True

    def test_other_groups_do_not(self, db, not_first):
        user = auth_backends.user_from_proxy_headers(
            db, request_with({"Remote-User": "kim", "Remote-Groups": "readers"})
        )

        assert user is not None and user.is_admin is False

    def test_a_custom_header_name_is_honoured(self, db, monkeypatch):
        monkeypatch.setenv("PROXY_USER_HEADER", "X-Forwarded-User")

        user = auth_backends.user_from_proxy_headers(
            db, request_with({"X-Forwarded-User": "kim"})
        )

        assert user is not None and user.username == "kim"

    def test_the_same_member_reuses_one_account(self, db):
        first = auth_backends.user_from_proxy_headers(db, request_with({"Remote-User": "kim"}))
        second = auth_backends.user_from_proxy_headers(db, request_with({"Remote-User": "kim"}))

        assert first is not None and second is not None
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
        "mode,expected", [("local", True), ("ldap", False), ("proxy", False)]
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
            "x" * 51,
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
        "username", ["rose", "local_admin", "a.b-c_d", "user@example.com", "x" * 50]
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

    def test_creating_an_account_is_logged_at_warning(self, db, caplog):
        with caplog.at_level(logging.WARNING):
            auth_backends.upsert_directory_user(
                db, "newcomer", is_admin=True, source=AuthMode.PROXY
            )

        created = [r for r in caplog.records if "Created account" in r.message]
        assert created and created[0].levelno == logging.WARNING

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
        assert user.is_admin is True

    def test_the_second_account_is_not(self, db):
        auth_backends.upsert_directory_user(
            db, "founder", is_admin=False, source=AuthMode.PROXY
        )
        second = auth_backends.upsert_directory_user(
            db, "later", is_admin=False, source=AuthMode.PROXY
        )
        assert second.is_admin is False

    def test_a_configured_group_still_grants_admin(self, db, monkeypatch):
        monkeypatch.setenv("PROXY_ADMIN_GROUP", "librarians")
        auth_backends.upsert_directory_user(
            db, "founder", is_admin=False, source=AuthMode.PROXY
        )
        second = auth_backends.upsert_directory_user(
            db, "later", is_admin=True, source=AuthMode.PROXY
        )
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
        """`users.username` is String(50), and SQLite would not complain."""
        db.add(User(username="admin", password_hash=hash_password("password123"), is_admin=True))
        long_name = "a" * 50
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
        assert len(renamed.username) <= 50
        assert renamed.username.endswith("-2")

    def test_the_rename_is_logged_loudly(self, db, alice, caplog):
        """A username changing without anybody asking has to be findable."""
        with caplog.at_level(logging.WARNING):
            auth_backends.upsert_directory_user(
                db, "alice", is_admin=False, source=AuthMode.PROXY
            )

        renames = [r for r in caplog.records if "Renamed the test account" in r.message]
        assert renames and renames[0].levelno == logging.WARNING
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

        assert adopted.id == existing.id
        assert adopted.auth_source == AuthMode.PROXY.value
