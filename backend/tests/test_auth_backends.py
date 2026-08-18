"""Tests for backend/auth_backends.py.

The LDAP tests drive a fake directory rather than a real one: what is worth
pinning here is our own logic (the empty-password guard, filter escaping,
shadow accounts, admin group mapping), not ldap3's ability to speak LDAP.
"""

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request

import auth_backends
from auth import hash_password
from enums import AuthMode
from models import User

# ── Fake directory ────────────────────────────────────────────────────────────


class FakeEntry:
    def __init__(self, dn: str, username: str, groups: list[str], attribute: str = "uid"):
        self.entry_dn = dn
        self._username = username
        self._attribute = attribute
        self.memberOf = SimpleNamespace(values=groups)
        self._has_groups = bool(groups)

    def __contains__(self, item: str) -> bool:
        return item == "memberOf" and self._has_groups

    def __getitem__(self, item: str) -> SimpleNamespace:
        if item == self._attribute:
            return SimpleNamespace(value=self._username)
        raise KeyError(item)


class FakeConnection:
    """Stands in for an ldap3 Connection.

    `bind_results` is consumed in order: the first bind is the service account
    searching, the second is the member proving their password.
    """

    def __init__(self, *, bind_results: list[bool], entries: list[FakeEntry]):
        self._bind_results = list(bind_results)
        self.entries: list[FakeEntry] = []
        self._available = entries
        self.result = "fake"
        self.searched_filter: str | None = None

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def bind(self) -> bool:
        return self._bind_results.pop(0) if self._bind_results else False

    def search(self, search_base: str, search_filter: str, attributes: list[str]) -> None:
        self.searched_filter = search_filter
        self.entries = self._available


@pytest.fixture
def ldap_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "ldap")
    monkeypatch.setenv("LDAP_URL", "ldap://directory.invalid")
    monkeypatch.setenv("LDAP_USER_BASE_DN", "ou=people,dc=example,dc=org")
    monkeypatch.setenv("LDAP_ADMIN_GROUP", "cn=librarians,ou=groups,dc=example,dc=org")


def install_directory(monkeypatch, connections: list[FakeConnection]) -> list[FakeConnection]:
    """Hand out the given connections, in order, to each _connect() call."""
    handed_out: list[FakeConnection] = []
    queue = list(connections)

    def fake_connect(user: str | None = None, password: str | None = None) -> FakeConnection:
        connection = queue.pop(0)
        connection.bound_as = (user, password)  # type: ignore[attr-defined]
        handed_out.append(connection)
        return connection

    monkeypatch.setattr(auth_backends, "_connect", fake_connect)
    return handed_out


def directory_with(monkeypatch, *, groups: list[str] | None = None, user_bind: bool = True):
    entry = FakeEntry("uid=kim,ou=people,dc=example,dc=org", "kim", groups or [])
    return install_directory(
        monkeypatch,
        [
            FakeConnection(bind_results=[True], entries=[entry]),
            FakeConnection(bind_results=[user_bind], entries=[]),
        ],
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


class TestLdapAdminGroup:
    def test_membership_grants_admin(self, db, ldap_mode, monkeypatch):
        directory_with(monkeypatch, groups=["cn=librarians,ou=groups,dc=example,dc=org"])

        user = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert user is not None and user.is_admin is True

    def test_absence_does_not(self, db, ldap_mode, monkeypatch):
        directory_with(monkeypatch, groups=["cn=readers,ou=groups,dc=example,dc=org"])

        user = auth_backends.authenticate_ldap(db, "kim", "correct-horse")

        assert user is not None and user.is_admin is False

    def test_admin_is_re_evaluated_on_every_sign_in(self, db, ldap_mode, monkeypatch):
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

    def test_other_groups_do_not(self, db):
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
