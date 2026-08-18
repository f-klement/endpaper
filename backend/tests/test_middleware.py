"""Tests for backend/middleware.py: the response hardening headers."""

import pytest


@pytest.fixture
def headers(client):
    """Headers from a normal, successful request."""
    return client.get("/auth/config").headers


class TestSecurityHeaders:
    def test_nosniff(self, headers):
        """Without this a browser may re-interpret an uploaded file as HTML."""
        assert headers["x-content-type-options"] == "nosniff"

    def test_framing_is_denied(self, headers):
        assert headers["x-frame-options"] == "DENY"

    def test_referrer_is_not_leaked(self, headers):
        assert headers["referrer-policy"] == "no-referrer"

    def test_a_content_security_policy_is_set(self, headers):
        assert "content-security-policy" in headers

    def test_headers_are_present_on_errors_too(self, client):
        """An error response is still a response a browser will act on."""
        res = client.get("/api/books/999999", headers={"Authorization": "Bearer nope"})
        assert res.headers["x-content-type-options"] == "nosniff"


class TestContentSecurityPolicy:
    @pytest.fixture
    def csp(self, headers):
        return {
            part.strip().split(" ")[0]: part.strip()
            for part in headers["content-security-policy"].split(";")
        }

    def test_scripts_are_same_origin_only(self, csp):
        assert csp["script-src"] == "script-src 'self'"

    def test_scripts_are_not_granted_unsafe_inline(self, csp):
        """This is the half of the policy that actually blunts XSS."""
        assert "unsafe-inline" not in csp["script-src"]
        assert "unsafe-eval" not in csp["script-src"]

    def test_styles_are_granted_unsafe_inline_deliberately(self, csp):
        # React applies the login background through an inline style attribute,
        # and inline styles cannot be nonced the way scripts can.
        assert "'unsafe-inline'" in csp["style-src"]

    def test_book_cover_hosts_are_allowed(self, csp):
        assert "covers.openlibrary.org" in csp["img-src"]

    def test_objects_are_blocked(self, csp):
        assert csp["object-src"] == "object-src 'none'"

    def test_framing_is_blocked_in_the_policy_too(self, csp):
        assert csp["frame-ancestors"] == "frame-ancestors 'none'"


class TestPermissionsPolicy:
    def test_camera_is_allowed_for_the_scanner(self, headers):
        assert "camera=(self)" in headers["permissions-policy"]

    def test_microphone_and_location_are_denied(self, headers):
        policy = headers["permissions-policy"]
        assert "microphone=()" in policy
        assert "geolocation=()" in policy


class TestHsts:
    def test_absent_over_plain_http(self, headers):
        """A LAN deployment with no certificate would otherwise lock members
        out of their own library after the first visit."""
        assert "strict-transport-security" not in headers

    def test_present_when_the_proxy_reports_https(self, client):
        res = client.get("/auth/config", headers={"X-Forwarded-Proto": "https"})
        assert "strict-transport-security" in res.headers

    def test_includes_a_long_max_age(self, client):
        res = client.get("/auth/config", headers={"X-Forwarded-Proto": "https"})
        assert "max-age=31536000" in res.headers["strict-transport-security"]
