"""Anonymous-bind guards.

LDAP has two ways to authenticate as nobody while returning success, and both
are easy to reach by accident:

1. A simple bind with an **empty password**. Most directories treat it as an
   anonymous bind, so forwarding one turns "leave the password blank" into a
   login as anybody in the directory.
2. A bind that supplies a **DN but no password** (an "unauthenticated" bind).
   RFC 4513 requires servers to treat this as anonymous. It is the easy
   configuration mistake: set LDAP_BIND_DN, forget LDAP_BIND_PASSWORD, and the
   service account silently searches with anonymous rights while everything
   still appears to work.

These are kept in their own module because they are the security property of
this feature, and they should be obvious to anyone reading the test tree.
"""

import pytest
from ldap3.core.exceptions import LDAPException

import auth_backends
from config import validate_auth_config


@pytest.fixture
def ldap_configured(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "ldap")
    monkeypatch.setenv("LDAP_URL", "ldap://directory.invalid")
    monkeypatch.setenv("LDAP_USER_BASE_DN", "ou=people,dc=example,dc=org")


class TestHasPassword:
    @pytest.mark.parametrize("value", ["correct-horse", " leading", "trailing ", "  x  "])
    def test_accepts_a_real_password(self, value):
        assert auth_backends.has_password(value) is True

    @pytest.mark.parametrize("value", ["", "   ", "\t", "\n", None])
    def test_rejects_empty_and_whitespace_only(self, value):
        # Whitespace-only cannot be deliberate, and some directories normalise
        # it to empty before comparing, which lands back on an anonymous bind.
        assert auth_backends.has_password(value) is False


class TestMemberBind:
    @pytest.mark.parametrize("password", ["", "   ", "\t"])
    def test_never_contacts_the_directory(self, db, ldap_configured, monkeypatch, password):
        def must_not_connect(*args: object, **kwargs: object) -> None:
            raise AssertionError("connected to the directory without a real password")

        monkeypatch.setattr(auth_backends, "_connect", must_not_connect)

        assert auth_backends.authenticate_ldap(db, "kim", password) is None


class TestConnectRefusesAnonymousBinds:
    """`_connect` is the backstop, so a future caller cannot bypass the check."""

    def test_a_dn_without_a_password_is_refused(self, ldap_configured):
        with pytest.raises(LDAPException, match="anonymous bind"):
            auth_backends._connect("cn=service,dc=example,dc=org", "")

    def test_a_dn_with_a_whitespace_password_is_refused(self, ldap_configured):
        with pytest.raises(LDAPException, match="anonymous bind"):
            auth_backends._connect("cn=service,dc=example,dc=org", "   ")

    def test_the_error_names_the_setting_to_fix(self, ldap_configured):
        with pytest.raises(LDAPException, match="LDAP_BIND_PASSWORD"):
            auth_backends._connect("cn=service,dc=example,dc=org", None)

    def test_a_deliberate_anonymous_search_is_still_allowed(self, ldap_configured):
        """No DN at all is a considered choice, not a mistake.

        The guard only fires when a DN is supplied without a password. With
        neither, a connection object comes back. Nothing touches the network
        here: ldap3 connects lazily, and auto_bind is off.
        """
        connection = auth_backends._connect(None, None)

        assert connection is not None
        assert connection.bound is False


class TestStartupValidation:
    def test_a_bind_dn_without_a_password_fails_startup(self, ldap_configured, monkeypatch):
        # Caught before the app serves a single request, rather than silently
        # searching the directory with anonymous rights forever.
        monkeypatch.setenv("LDAP_BIND_DN", "cn=service,dc=example,dc=org")
        monkeypatch.setenv("LDAP_BIND_PASSWORD", "")

        with pytest.raises(RuntimeError, match="anonymous bind"):
            validate_auth_config()

    def test_a_whitespace_password_also_fails(self, ldap_configured, monkeypatch):
        monkeypatch.setenv("LDAP_BIND_DN", "cn=service,dc=example,dc=org")
        monkeypatch.setenv("LDAP_BIND_PASSWORD", "   ")

        with pytest.raises(RuntimeError):
            validate_auth_config()

    def test_a_bind_dn_with_a_password_is_fine(self, ldap_configured, monkeypatch):
        monkeypatch.setenv("LDAP_BIND_DN", "cn=service,dc=example,dc=org")
        monkeypatch.setenv("LDAP_BIND_PASSWORD", "service-secret")

        validate_auth_config()

    def test_no_bind_dn_is_fine(self, ldap_configured, monkeypatch):
        """Anonymous search is a legitimate configuration for a public tree."""
        monkeypatch.delenv("LDAP_BIND_DN", raising=False)
        monkeypatch.delenv("LDAP_BIND_PASSWORD", raising=False)

        validate_auth_config()
