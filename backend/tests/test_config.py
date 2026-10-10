"""Tests for backend/config.py.

The point of this module is that settings are read per call, not frozen at
import. These tests exist mainly to keep it that way.
"""

import pytest

import config
from enums import AppEnv
from tests.helpers import an_authority


class TestRegistrationEnabled:
    def test_defaults_to_true_when_unset(self, monkeypatch):
        monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)
        assert config.registration_enabled() is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "False", " false "])
    def test_false_in_any_casing_or_padding_disables_it(self, monkeypatch, value):
        monkeypatch.setenv("ALLOW_REGISTRATION", value)
        assert config.registration_enabled() is False

    @pytest.mark.parametrize("value", ["true", "yes", "1", "", "no"])
    def test_anything_other_than_false_leaves_it_enabled(self, monkeypatch, value):
        """Fail open: only the literal string "false" locks people out."""
        monkeypatch.setenv("ALLOW_REGISTRATION", value)
        assert config.registration_enabled() is True

    def test_is_re_read_on_every_call(self, monkeypatch):
        monkeypatch.setenv("ALLOW_REGISTRATION", "true")
        assert config.registration_enabled() is True
        monkeypatch.setenv("ALLOW_REGISTRATION", "false")
        assert config.registration_enabled() is False


class TestSecretKey:
    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "a-different-secret")
        assert config.secret_key() == "a-different-secret"

    def test_falls_back_to_a_development_placeholder(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        assert "change-in-production" in config.secret_key()


class TestDatabaseUrl:
    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./somewhere.db")
        assert config.database_url() == "sqlite:///./somewhere.db"

    def test_defaults_into_the_data_directory(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert str(config.DATA_DIR) in config.database_url()


class TestPaths:
    def test_covers_live_under_the_data_directory(self):
        assert config.COVERS_DIR.parent == config.DATA_DIR

    def test_data_dir_is_absolute(self):
        """Relative paths would resolve against the working directory, which
        differs between uvicorn, pytest and the container."""
        assert config.DATA_DIR.is_absolute()

    def test_ensure_data_dirs_is_idempotent(self):
        config.ensure_data_dirs()
        config.ensure_data_dirs()
        assert config.COVERS_DIR.is_dir()


class TestServeFrontend:
    """`SERVE_FRONTEND=false` is how a relay asks for API-only."""

    def test_defaults_to_true_when_unset(self, monkeypatch):
        monkeypatch.delenv("SERVE_FRONTEND", raising=False)
        assert config.serve_frontend() is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "False", " false "])
    def test_false_in_any_casing_or_padding_switches_it_off(self, monkeypatch, value):
        monkeypatch.setenv("SERVE_FRONTEND", value)
        assert config.serve_frontend() is False

    @pytest.mark.parametrize("value", ["true", "yes", "1", "", "no"])
    def test_anything_other_than_false_keeps_serving(self, monkeypatch, value):
        """Fails towards the ordinary deployment: only the literal string
        "false" takes the frontend away."""
        monkeypatch.setenv("SERVE_FRONTEND", value)
        assert config.serve_frontend() is True

    def test_is_re_read_on_every_call(self, monkeypatch):
        monkeypatch.setenv("SERVE_FRONTEND", "true")
        assert config.serve_frontend() is True
        monkeypatch.setenv("SERVE_FRONTEND", "false")
        assert config.serve_frontend() is False


class TestAllowedImageExtensions:
    def test_covers_the_formats_browsers_render(self):
        assert {"jpg", "jpeg", "png", "webp"} == config.ALLOWED_IMAGE_EXTENSIONS

    def test_excludes_svg(self):
        """SVG can carry script, and these files are served from our origin."""
        assert "svg" not in config.ALLOWED_IMAGE_EXTENSIONS

    def test_is_immutable(self):
        assert isinstance(config.ALLOWED_IMAGE_EXTENSIONS, frozenset)


class TestAppEnv:
    def test_dev_is_recognised(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "dev")
        assert config.app_env() is AppEnv.DEV

    @pytest.mark.parametrize("value", ["prod", "production", "", "staging", "developement"])
    def test_anything_else_is_production(self, monkeypatch, value):
        """Fails safe: a typo must not silently relax the startup checks."""
        monkeypatch.setenv("APP_ENV", value)
        assert config.app_env() is AppEnv.PROD

    def test_unset_is_production(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        assert config.app_env() is AppEnv.PROD

    def test_dev_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "DEV")
        assert config.app_env() is AppEnv.DEV

    def test_surrounding_whitespace_is_tolerated(self, monkeypatch):
        """Env values picked up from YAML often carry a trailing space."""
        monkeypatch.setenv("APP_ENV", "  dev  ")
        assert config.app_env() is AppEnv.DEV


class TestValidateSecretKey:
    """Booting production with the example key means every token is forgeable."""

    @pytest.mark.parametrize(
        "placeholder",
        [
            "dev-secret-change-in-production",
            "change-this-in-production",
            "replace-with-at-least-32-random-characters",
            "REPLACE_WITH_A_LONG_RANDOM_STRING",
        ],
    )
    def test_rejects_every_shipped_placeholder(self, monkeypatch, placeholder):
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SECRET_KEY", placeholder)
        with pytest.raises(RuntimeError, match="placeholder"):
            config.validate_secret_key()

    def test_rejects_a_short_key(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SECRET_KEY", "too-short")
        with pytest.raises(RuntimeError, match="at least"):
            config.validate_secret_key()

    def test_accepts_a_long_random_key(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SECRET_KEY", "x" * config.MIN_SECRET_KEY_LENGTH)
        config.validate_secret_key()

    def test_measures_bytes_not_characters(self, monkeypatch):
        """A 31-character key of multi-byte characters is long enough in bytes;
        a 31-character ASCII one is not."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SECRET_KEY", "a" * (config.MIN_SECRET_KEY_LENGTH - 1))
        with pytest.raises(RuntimeError, match="at least 32 bytes; got 31"):
            config.validate_secret_key()

    def test_dev_is_exempt(self, monkeypatch):
        """Local work must not need a generated secret to start."""
        monkeypatch.setenv("APP_ENV", "dev")
        monkeypatch.setenv("SECRET_KEY", "dev-secret-change-in-production")
        config.validate_secret_key()

    def test_the_error_says_how_to_fix_it(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SECRET_KEY", "change-this-in-production")
        with pytest.raises(RuntimeError, match="still the example placeholder") as caught:
            config.validate_secret_key()
        assert "secrets.token_urlsafe" in str(caught.value)


class TestUploadLimits:
    def test_there_is_a_size_cap(self):
        """The body is read into memory before it is written, so an unbounded
        upload is a denial-of-service, not just an untidy file."""
        assert config.MAX_UPLOAD_BYTES > 0

    def test_the_cap_is_generous_enough_for_a_cover(self):
        assert config.MAX_UPLOAD_BYTES >= 2 * 1024 * 1024


class TestLdapStartupRefusesCleartext:
    """`validate_auth_config` under `AUTH_MODE=ldap`, on how the directory is
    reached. The bind credentials have their own arms in
    `tests/test_auth_backends_bindguard.py`."""

    @pytest.fixture(autouse=True)
    def ldap(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "ldap")
        monkeypatch.setenv("LDAP_USER_BASE_DN", "ou=people,dc=example,dc=org")
        monkeypatch.setenv("LDAP_BIND_DN", "cn=service,dc=example,dc=org")
        monkeypatch.setenv("LDAP_BIND_PASSWORD", "service-secret")
        for name in ("LDAP_START_TLS", "LDAP_ALLOW_CLEARTEXT", "LDAP_CA_FILE"):
            monkeypatch.delenv(name, raising=False)

    def test_a_plain_url_is_refused_naming_both_ways_out(self, monkeypatch):
        monkeypatch.setenv("LDAP_URL", "ldap://directory.example.org")

        with pytest.raises(RuntimeError, match="cleartext") as refused:
            config.validate_auth_config()

        assert "LDAP_START_TLS=true" in str(refused.value)
        assert "LDAP_ALLOW_CLEARTEXT=true" in str(refused.value)

    def test_an_anonymous_search_over_a_plain_url_is_refused_too(self, monkeypatch):
        """No service password goes out, but the member's bind after the search
        sends theirs, and that is every sign in."""
        monkeypatch.setenv("LDAP_URL", "ldap://directory.example.org")
        monkeypatch.delenv("LDAP_BIND_DN")
        monkeypatch.delenv("LDAP_BIND_PASSWORD")

        with pytest.raises(RuntimeError, match="cleartext"):
            config.validate_auth_config()

    def test_a_url_with_no_scheme_is_cleartext(self, monkeypatch):
        """ldap3 dials a bare host without TLS, so it is refused as one."""
        monkeypatch.setenv("LDAP_URL", "directory.example.org")

        with pytest.raises(RuntimeError, match="cleartext"):
            config.validate_auth_config()

    def test_allowing_cleartext_by_name_lets_a_plain_url_start(self, monkeypatch):
        monkeypatch.setenv("LDAP_URL", "ldap://directory.example.org")
        monkeypatch.setenv("LDAP_ALLOW_CLEARTEXT", "true")

        config.validate_auth_config()

    def test_start_tls_lets_a_plain_url_start(self, monkeypatch):
        monkeypatch.setenv("LDAP_URL", "ldap://directory.example.org")
        monkeypatch.setenv("LDAP_START_TLS", "true")

        config.validate_auth_config()

    def test_an_ldaps_url_starts(self, monkeypatch):
        monkeypatch.setenv("LDAP_URL", "ldaps://directory.example.org")

        config.validate_auth_config()


class TestLdapCaFileIsCheckedAtStartup:
    @pytest.fixture(autouse=True)
    def ldaps(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "ldap")
        monkeypatch.setenv("LDAP_URL", "ldaps://directory.example.org")
        monkeypatch.setenv("LDAP_USER_BASE_DN", "ou=people,dc=example,dc=org")
        for name in ("LDAP_START_TLS", "LDAP_ALLOW_CLEARTEXT", "LDAP_BIND_DN"):
            monkeypatch.delenv(name, raising=False)

    def test_a_file_that_is_not_there_fails_startup_naming_it(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LDAP_CA_FILE", str(tmp_path / "never-mounted.pem"))

        with pytest.raises(RuntimeError, match="LDAP_CA_FILE"):
            config.validate_auth_config()

    def test_a_file_holding_no_certificate_fails_startup_naming_it(self, monkeypatch, tmp_path):
        not_a_bundle = tmp_path / "ca.pem"
        not_a_bundle.write_text("this is not a certificate\n")
        monkeypatch.setenv("LDAP_CA_FILE", str(not_a_bundle))

        with pytest.raises(RuntimeError, match="LDAP_CA_FILE"):
            config.validate_auth_config()

    def test_a_file_holding_a_certificate_is_accepted(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LDAP_CA_FILE", str(an_authority("a private CA", tmp_path).pem))

        config.validate_auth_config()

    def test_a_file_beside_a_connection_with_no_tls_is_refused(self, monkeypatch, tmp_path):
        """It would never be read, and a deployment that set it believes the
        directory is verified."""
        monkeypatch.setenv("LDAP_URL", "ldap://directory.example.org")
        monkeypatch.setenv("LDAP_ALLOW_CLEARTEXT", "true")
        monkeypatch.setenv("LDAP_CA_FILE", str(an_authority("a private CA", tmp_path).pem))

        with pytest.raises(RuntimeError, match="never be read"):
            config.validate_auth_config()
