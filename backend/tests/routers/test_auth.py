"""Tests for backend/routers/auth.py: registration, login, /auth/me."""

import pytest

from auth import COVER_COOKIE_NAME
from models import User
from tests.helpers import directory_with, proxy_headers


class TestRegister:
    def test_first_account_becomes_admin(self, client):
        res = client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        assert res.status_code == 201
        assert res.json()["user"]["is_admin"] is True

    def test_second_account_is_not_admin(self, client, admin):
        res = client.post("/auth/register", json={"username": "second", "password": "pw12345678"})
        assert res.status_code == 201
        assert res.json()["user"]["is_admin"] is False

    def test_registration_returns_a_usable_token(self, client):
        token = client.post(
            "/auth/register", json={"username": "first", "password": "pw12345678"}
        ).json()["access_token"]
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200

    def test_duplicate_username_is_rejected(self, client, admin):
        res = client.post("/auth/register", json={"username": "admin", "password": "pw12345678"})
        assert res.status_code == 400
        assert "taken" in res.json()["detail"].lower()

    def test_password_is_never_returned(self, client):
        body = client.post(
            "/auth/register", json={"username": "first", "password": "pw12345678"}
        ).json()
        assert "password" not in body["user"]
        assert "password_hash" not in body["user"]

    def test_password_is_stored_hashed_not_plain(self, client, db):
        client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        stored = db.query(User).filter(User.username == "first").one().password_hash
        assert stored != "pw12345678"
        assert stored.startswith("$2")

    def test_missing_field_is_422(self, client):
        assert client.post("/auth/register", json={"username": "only"}).status_code == 422

    def test_a_password_under_the_floor_is_422(self, client):
        """8 characters, and the floor is `UserCreate`'s so it applies to every
        route that creates an account, not only this one."""
        res = client.post("/auth/register", json={"username": "first", "password": "pw12345"})
        assert res.status_code == 422

    def test_a_password_at_the_floor_is_accepted(self, client):
        res = client.post("/auth/register", json={"username": "first", "password": "pw123456"})
        assert res.status_code == 201


class TestAnAddressCanBeGivenWhileTheAccountIsBeingMade:
    """#103. The one moment somebody is already typing their details.

    The address is `User.email`, nullable, and it stays nullable: an account
    made without one is the account this route made before the field existed,
    which is every account today.
    """

    def test_an_address_sent_at_registration_is_stored(self, client, db):
        res = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": "first@example.org",
            },
        )
        assert res.status_code == 201
        assert db.query(User).filter(User.username == "first").one().email == (
            "first@example.org"
        )

    def test_an_account_made_without_one_still_has_none(self, client, db):
        client.post("/auth/register", json={"username": "first", "password": "pw12345678"})
        assert db.query(User).filter(User.username == "first").one().email is None

    def test_an_empty_string_is_no_address_rather_than_a_refusal(self, client, db):
        """A browser sends "" for a field nobody filled in, and refusing that
        would make the optional field compulsory for anyone using a form."""
        res = client.post(
            "/auth/register",
            json={"username": "first", "password": "pw12345678", "email": "  "},
        )
        assert res.status_code == 201
        assert db.query(User).filter(User.username == "first").one().email is None

    def test_something_that_is_not_an_address_is_422(self, client, db):
        res = client.post(
            "/auth/register",
            json={"username": "first", "password": "pw12345678", "email": "not one"},
        )
        assert res.status_code == 422
        assert db.query(User).filter(User.username == "first").first() is None

    def test_a_header_injection_attempt_is_422(self, client):
        """The same rule `PUT /users/me/email` enforces, which is the point of
        there being one rule: this address reaches `mailer` like any other."""
        res = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": "a@example.org\nBcc: victim@example.org",
            },
        )
        assert res.status_code == 422

    def test_an_address_past_the_column_is_422(self, client):
        res = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": f"{'a' * 320}@example.org",
            },
        )
        assert res.status_code == 422

    def test_the_address_is_not_served_back_with_the_account(self, client):
        """`UserOut` carries no address, which is what stops one appearing in
        every book payload. Registration returns a `UserOut` like any other."""
        body = client.post(
            "/auth/register",
            json={
                "username": "first",
                "password": "pw12345678",
                "email": "first@example.org",
            },
        ).json()
        assert "email" not in body["user"]


class TestRegistrationDisabled:
    @pytest.fixture(autouse=True)
    def disable_registration(self, monkeypatch):
        monkeypatch.setenv("ALLOW_REGISTRATION", "false")

    def test_register_is_403(self, client):
        res = client.post("/auth/register", json={"username": "nope", "password": "pw12345678"})
        assert res.status_code == 403

    def test_config_reports_it(self, client):
        assert client.get("/auth/config").json()["registration_enabled"] is False

    def test_login_still_works(self, client, db):
        """Disabling signups must not lock out the accounts that already exist."""
        from auth import hash_password

        db.add(User(username="existing", password_hash=hash_password("pw12345678")))
        db.commit()
        res = client.post("/auth/login", json={"username": "existing", "password": "pw12345678"})
        assert res.status_code == 200

    def test_the_flag_is_read_per_request_not_at_import(self, client, monkeypatch):
        """Regression: the flag used to be a module constant needing a restart."""
        monkeypatch.setenv("ALLOW_REGISTRATION", "true")
        assert client.get("/auth/config").json()["registration_enabled"] is True


class TestLogin:
    def test_correct_credentials_return_a_token(self, client, admin):
        res = client.post("/auth/login", json={"username": "admin", "password": "password123"})
        assert res.status_code == 200
        assert res.json()["token_type"] == "bearer"

    def test_wrong_password_is_401(self, client, admin):
        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 401

    def test_unknown_username_is_401(self, client, admin):
        res = client.post("/auth/login", json={"username": "ghost", "password": "password123"})
        assert res.status_code == 401

    def test_unknown_user_and_wrong_password_are_indistinguishable(self, client, admin):
        """Different messages here would let an attacker enumerate accounts."""
        wrong_pw = client.post("/auth/login", json={"username": "admin", "password": "x"})
        no_user = client.post("/auth/login", json={"username": "ghost", "password": "x"})
        assert wrong_pw.json()["detail"] == no_user.json()["detail"]

    def test_username_comparison_is_case_sensitive(self, client, admin):
        res = client.post("/auth/login", json={"username": "ADMIN", "password": "password123"})
        assert res.status_code == 401

    def test_it_sets_the_cover_cookie(self, client, admin):
        """An <img> cannot send the Authorization header, so without this every
        cover on the page 401s under local auth."""
        res = client.post("/auth/login", json={"username": "admin", "password": "password123"})
        assert COVER_COOKIE_NAME in res.cookies

    def test_the_cover_cookie_is_scoped_to_the_cover_route(self, client, admin):
        """Path, HttpOnly and SameSite are what keep a second copy of an
        identity from being a CSRF hole. The scope claim inside it is tested in
        tests/test_auth.py; this is the browser's half."""
        res = client.post("/auth/login", json={"username": "admin", "password": "password123"})

        header = res.headers["set-cookie"]
        assert "Path=/covers" in header
        assert "HttpOnly" in header
        assert "SameSite=lax" in header.replace("Samesite", "SameSite")

    def test_getting_it_right_clears_the_count(self, client, admin):
        """Otherwise somebody who mistypes their password nine times and then
        gets it right is rationed for the rest of the window."""
        for _ in range(9):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})

        assert (
            client.post(
                "/auth/login", json={"username": "admin", "password": "password123"}
            ).status_code
            == 200
        )
        for _ in range(9):
            assert (
                client.post(
                    "/auth/login", json={"username": "admin", "password": "wrong"}
                ).status_code
                == 401
            )

    def test_guesses_are_bounded(self, client, admin):
        for _ in range(10):
            client.post("/auth/login", json={"username": "admin", "password": "wrong"})

        res = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 429
        assert "Retry-After" in res.headers


class TestAuthConfig:
    def test_is_public(self, client):
        """The login page reads this before anyone has a token."""
        assert client.get("/auth/config").status_code == 200

    def test_defaults_to_enabled(self, client):
        assert client.get("/auth/config").json()["registration_enabled"] is True

    def test_reports_the_auth_mode(self, client):
        """The frontend renders a different screen per mode, so it has to be
        told which one is in force before anyone signs in."""
        assert client.get("/auth/config").json()["auth_mode"] == "local"


class TestMe:
    def test_returns_the_authenticated_account(self, client, member):
        body = client.get("/auth/me", headers=member["headers"]).json()
        assert body["username"] == "member"
        assert body["is_admin"] is False

    def test_requires_a_token(self, client):
        assert client.get("/auth/me").status_code == 401


# ── The other two auth modes ──────────────────────────────────────────────────
#
# `auth_backends.py` has thorough unit tests. What these cover is the flow
# through the HTTP routes: which of them answer, which refuse, and what each
# one leaves behind in the database. Every route is exercised in every mode,
# because the interesting failures are the ones where a route that should be
# inert quietly is not.


class TestLdapMode:
    @pytest.fixture(autouse=True)
    def mode(self, ldap_mode):
        return ldap_mode

    def test_config_reports_the_mode(self, client):
        assert client.get("/auth/config").json()["auth_mode"] == "ldap"

    def test_config_turns_signup_off(self, client):
        """Whatever ALLOW_REGISTRATION says: this app does not own the accounts."""
        assert client.get("/auth/config").json()["registration_enabled"] is False

    def test_register_is_403(self, client):
        res = client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert res.status_code == 403
        assert "directory" in res.json()["detail"]

    def test_register_creates_nothing(self, client, db):
        client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert db.query(User).count() == 0

    def test_a_refused_signup_does_not_spend_the_limiter(self, client):
        """Regression: the limiter ran first, so an anonymous caller could
        exhaust a real budget on a route that can never succeed."""
        for _ in range(10):
            assert (
                client.post(
                    "/auth/register", json={"username": "kim", "password": "pw12345678"}
                ).status_code
                == 403
            )

    def test_login_binds_and_returns_a_token(self, client, monkeypatch):
        directory_with(monkeypatch)
        res = client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert res.status_code == 200
        assert res.json()["user"]["username"] == "kim"

    def test_login_creates_the_shadow_row(self, client, db, monkeypatch):
        """Every foreign key in the schema points at users.id, so a directory
        identity needs a local row before it can own anything."""
        directory_with(monkeypatch)
        client.post("/auth/login", json={"username": "kim", "password": "password123"})

        user = db.query(User).filter(User.username == "kim").one()
        assert user.password_hash is None
        assert user.auth_source == "ldap"

    def test_login_sets_the_cover_cookie(self, client, monkeypatch):
        # An <img> tag cannot send the Authorization header, so without this
        # every cover on the page 401s.
        directory_with(monkeypatch)
        res = client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert COVER_COOKIE_NAME in res.cookies

    def test_a_rejected_bind_is_401(self, client, monkeypatch):
        directory_with(monkeypatch, user_bind=False)
        res = client.post("/auth/login", json={"username": "kim", "password": "wrong"})
        assert res.status_code == 401

    def test_a_rejected_bind_creates_nothing(self, client, db, monkeypatch):
        directory_with(monkeypatch, user_bind=False)
        client.post("/auth/login", json={"username": "kim", "password": "wrong"})
        assert db.query(User).count() == 0

    def test_the_token_from_a_bind_works_on_me(self, client, monkeypatch):
        directory_with(monkeypatch)
        token = client.post(
            "/auth/login", json={"username": "kim", "password": "password123"}
        ).json()["access_token"]

        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.json()["username"] == "kim"

    def test_me_without_a_token_is_401(self, client):
        assert client.get("/auth/me").status_code == 401


class TestProxyMode:
    @pytest.fixture(autouse=True)
    def mode(self, proxy_mode):
        return proxy_mode

    def test_config_reports_the_mode(self, client):
        """The frontend renders no auth screen at all in this mode."""
        assert client.get("/auth/config").json()["auth_mode"] == "proxy"

    def test_config_turns_signup_off(self, client):
        assert client.get("/auth/config").json()["registration_enabled"] is False

    def test_register_is_403(self, client):
        res = client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert res.status_code == 403

    def test_the_refusal_does_not_name_a_directory(self, client):
        """There need not be one: the upstream may be an SSO portal or a header
        the reverse proxy sets. Naming a directory sends people to ask an
        administrator who does not exist."""
        detail = client.post(
            "/auth/register", json={"username": "kim", "password": "pw12345678"}
        ).json()["detail"]
        assert "directory" not in detail.lower()

    def test_register_creates_nothing(self, client, db):
        client.post("/auth/register", json={"username": "kim", "password": "pw12345678"})
        assert db.query(User).count() == 0

    def test_login_is_401(self, client):
        """There is no password to check: the proxy already authenticated."""
        res = client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert res.status_code == 401

    def test_login_creates_nothing(self, client, db):
        """A login body must never be a way to mint an account in this mode."""
        client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert db.query(User).count() == 0

    def test_me_reads_the_header(self, client):
        res = client.get("/auth/me", headers=proxy_headers("kim"))
        assert res.status_code == 200
        assert res.json()["username"] == "kim"

    def test_me_without_a_header_is_401(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_a_bearer_token_alone_is_not_enough(self, client, admin):
        """The header is the only identity this mode accepts. A token minted
        before the switch must not keep working around the proxy."""
        assert client.get("/auth/me", headers=admin["headers"]).status_code == 401

    def test_the_first_header_identity_becomes_the_admin(self, client):
        """Otherwise a deployment with no groups header has a catalogue nobody
        can administer, and no recovery short of editing the database."""
        assert client.get("/auth/me", headers=proxy_headers("kim")).json()["is_admin"] is True

    def test_a_malformed_identity_is_refused(self, client, db):
        client.get("/auth/me", headers=proxy_headers("x" * 400))
        assert db.query(User).count() == 0

    def test_no_route_sets_the_cover_cookie(self, client):
        """Nothing here logs in, so nothing mints one, `/auth/switch` aside.
        Covers work anyway, because the proxy sets its header on the image
        request too. Proved in tests/routers/test_covers.py rather than
        assumed."""
        res = client.get("/auth/me", headers=proxy_headers("kim"))
        assert COVER_COOKIE_NAME not in res.cookies


# ── Switching to a test account ───────────────────────────────────────────────
#
# The one route that hands a session on one account to somebody holding
# another's. What is worth pinning is the refusals: a directory-backed account
# is never a target in any mode, and a session is never issued without the
# password.


@pytest.fixture
def test_account(client, admin) -> dict:
    """An admin-created test account, made the way the UI makes one."""
    res = client.post(
        "/api/users/test-accounts",
        json={"username": "tester", "password": "pw12345678"},
        headers=admin["headers"],
    )
    assert res.status_code == 201, res.text
    return dict(res.json(), password="pw12345678")


class TestSwitchAccount:
    def test_the_right_password_returns_a_token_for_the_target(
        self, client, admin, test_account
    ):
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["user"]["username"] == "tester"
        assert res.json()["user"]["is_admin"] is False

    def test_the_token_acts_as_the_target(self, client, admin, test_account):
        token = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()["access_token"]

        res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.json()["username"] == "tester"

    def test_it_sets_the_cover_cookie(self, client, admin, test_account):
        """Exactly like a login: without it the switched session has no covers."""
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert COVER_COOKIE_NAME in res.cookies

    def test_a_wrong_password_is_401(self, client, admin, test_account):
        """The password is the difference between this and impersonation."""
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "wrong"},
            headers=admin["headers"],
        )
        assert res.status_code == 401

    def test_an_unknown_name_is_404(self, client, admin):
        res = client.post(
            "/auth/switch",
            json={"username": "ghost", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_an_ordinary_member_is_not_a_target(self, client, admin, member):
        """Even with the right password, and even though this is local mode
        where the admin could type it into the login form instead. The rule is
        the account, not the mode."""
        res = client.post(
            "/auth/switch",
            json={"username": "member", "password": "password123"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_the_admin_own_account_is_not_a_target(self, client, admin):
        res = client.post(
            "/auth/switch",
            json={"username": "admin", "password": "password123"},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_a_non_admin_is_403(self, client, admin, member, test_account):
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=member["headers"],
        )
        assert res.status_code == 403

    def test_it_needs_a_session(self, client, admin, test_account):
        res = client.post(
            "/auth/switch", json={"username": "tester", "password": "pw12345678"}
        )
        assert res.status_code == 401

    def test_guesses_are_bounded(self, client, admin, test_account):
        """The caller is an admin, so this is not the first line of defence. It
        is that a password check reachable over HTTP is one worth bounding."""
        for _ in range(10):
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "wrong"},
                headers=admin["headers"],
            )

        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "wrong"},
            headers=admin["headers"],
        )
        assert res.status_code == 429

    def test_getting_it_right_clears_the_count(self, client, admin, test_account):
        for _ in range(9):
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "wrong"},
                headers=admin["headers"],
            )

        assert (
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "pw12345678"},
                headers=admin["headers"],
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "wrong"},
                headers=admin["headers"],
            ).status_code
            == 401
        )

    def test_a_switched_session_cannot_switch_again(self, client, admin, test_account):
        """The session is the test account's, and a test account is never an
        admin. Without this an admin's one switch is a session that can reach
        every other test account without the password to any of them."""
        token = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()["access_token"]

        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_a_switched_session_cannot_create_a_test_account(
        self, client, admin, test_account, db
    ):
        token = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        ).json()["access_token"]

        res = client.post(
            "/api/users/test-accounts",
            json={"username": "another", "password": "pw12345678"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert res.status_code == 403
        assert db.query(User).filter(User.username == "another").first() is None

    def test_it_is_logged_with_both_names(self, client, admin, test_account, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            client.post(
                "/auth/switch",
                json={"username": "tester", "password": "pw12345678"},
                headers=admin["headers"],
            )

        switches = [r for r in caplog.records if "switched into" in r.message]
        assert switches and switches[0].levelno == logging.WARNING
        assert "'admin'" in switches[0].getMessage()
        assert "'tester'" in switches[0].getMessage()


class TestSwitchInLdapMode:
    @pytest.fixture(autouse=True)
    def mode(self, ldap_mode):
        return ldap_mode

    def test_an_admin_can_switch_into_a_test_account(self, client, admin, test_account):
        """The reason the feature exists: `/auth/login` cannot reach a local
        password in this mode, so this is the only way to see the library as an
        ordinary member sees it."""
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=admin["headers"],
        )
        assert res.status_code == 200

    def test_a_directory_account_is_never_a_target(self, client, admin, db, monkeypatch):
        """Even after a successful bind has created the shadow row, and even if
        an admin somehow knows the password. An admin able to mint a session
        for a directory member could read that member's private books."""
        directory_with(monkeypatch)
        client.post("/auth/login", json={"username": "kim", "password": "password123"})
        assert db.query(User).filter(User.username == "kim").one().auth_source == "ldap"

        res = client.post(
            "/auth/switch",
            json={"username": "kim", "password": "password123"},
            headers=admin["headers"],
        )
        assert res.status_code == 404


class TestSwitchInProxyMode:
    """Where the precedence between a header and a token has to be explicit."""

    @pytest.fixture(autouse=True)
    def mode(self, proxy_mode):
        return proxy_mode

    @pytest.fixture
    def boss(self, client) -> dict:
        """The first header identity, which is how an admin exists here."""
        client.get("/auth/me", headers=proxy_headers("boss"))
        return proxy_headers("boss")

    @pytest.fixture
    def switched(self, client, boss) -> str:
        client.post(
            "/api/users/test-accounts",
            json={"username": "tester", "password": "pw12345678"},
            headers=boss,
        )
        res = client.post(
            "/auth/switch",
            json={"username": "tester", "password": "pw12345678"},
            headers=boss,
        )
        assert res.status_code == 200, res.text
        return str(res.json()["access_token"])

    def test_the_switch_token_beats_the_proxy_header(self, client, boss, switched):
        res = client.get(
            "/auth/me", headers={**boss, "Authorization": f"Bearer {switched}"}
        )
        assert res.json()["username"] == "tester"

    def test_dropping_the_token_restores_the_proxy_identity(self, client, boss, switched):
        """This is the whole of "switch back" in this mode: the upstream names
        the admin again on the very next request."""
        assert client.get("/auth/me", headers=boss).json()["username"] == "boss"

    def test_a_directory_account_is_never_a_target(self, client, boss, db):
        client.get("/auth/me", headers=proxy_headers("kim"))

        res = client.post(
            "/auth/switch",
            json={"username": "kim", "password": "pw12345678"},
            headers=boss,
        )
        assert res.status_code == 404

    def test_an_ordinary_token_still_does_not_beat_the_header(self, client, boss, admin):
        """The narrow acceptance is the point. A token minted before a
        deployment moved to proxy auth names a real member, and reviving it
        would be a way around the proxy."""
        res = client.get("/auth/me", headers={**boss, **admin["headers"]})
        assert res.json()["username"] == "boss"

    def test_a_switch_token_stops_working_when_the_flag_comes_off(
        self, client, boss, switched, db
    ):
        """`is_switch_target` is re-read per request rather than frozen into
        the token, so the row is what decides."""
        account = db.query(User).filter(User.username == "tester").one()
        account.is_test_account = False
        db.commit()

        res = client.get(
            "/auth/me", headers={**boss, "Authorization": f"Bearer {switched}"}
        )
        assert res.json()["username"] == "boss"

    def test_a_switch_token_alone_still_works_without_a_header(self, client, boss, switched):
        """The token is a session in its own right, not a modifier on a header."""
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {switched}"})
        assert res.json()["username"] == "tester"
