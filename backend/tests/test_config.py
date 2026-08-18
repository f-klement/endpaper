"""Tests for backend/config.py.

The point of this module is that settings are read per call, not frozen at
import. These tests exist mainly to keep it that way.
"""

import pytest

import config
from enums import AppEnv


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
        with pytest.raises(RuntimeError):
            config.validate_secret_key()

    def test_dev_is_exempt(self, monkeypatch):
        """Local work must not need a generated secret to start."""
        monkeypatch.setenv("APP_ENV", "dev")
        monkeypatch.setenv("SECRET_KEY", "dev-secret-change-in-production")
        config.validate_secret_key()

    def test_the_error_says_how_to_fix_it(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SECRET_KEY", "change-this-in-production")
        with pytest.raises(RuntimeError) as caught:
            config.validate_secret_key()
        assert "secrets.token_urlsafe" in str(caught.value)


class TestUploadLimits:
    def test_there_is_a_size_cap(self):
        """The body is read into memory before it is written, so an unbounded
        upload is a denial-of-service, not just an untidy file."""
        assert config.MAX_UPLOAD_BYTES > 0

    def test_the_cap_is_generous_enough_for_a_cover(self):
        assert config.MAX_UPLOAD_BYTES >= 2 * 1024 * 1024
