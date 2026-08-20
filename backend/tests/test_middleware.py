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

    def test_every_host_covers_py_knows_about_is_allowed(self, csp):
        """The policy and `covers.py` used to be two separate lists, and they
        drifted: covers.py started resolving German ISBNs through
        portal.dnb.de, this policy never learned about it, and every cover on a
        German shelf was blocked with nothing anywhere saying why.

        The policy is now built from `covers.COVER_HOSTS`. This is the
        assertion that the tuple is complete."""
        import covers

        for host in covers.COVER_HOSTS:
            assert host in csp["img-src"], host

    def test_every_url_covers_py_can_build_is_permitted(self, csp):
        """One level below the test above: not "is the tuple in the policy" but
        "is a URL this app actually produces permitted by it".

        The URLs come from `tests/test_covers.py`, which lists every builder in
        one place, so a new builder fails there and here rather than shipping a
        cover the browser refuses. `covers.py` is the only module allowed to
        build one at all, which is asserted in that file too.
        """
        from tests.test_covers import every_buildable_url

        for url in every_buildable_url():
            origin = url.split("/", 3)
            allowed = f"{origin[0]}//{origin[2]}"
            assert allowed in csp["img-src"], url

    def test_uploaded_covers_are_allowed_from_our_own_origin(self, csp):
        assert "'self'" in csp["img-src"]

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


class TestBodySizeLimit:
    """The endpoints check their own limits, but only after Starlette has
    spooled the whole body to disk. These tests are about what never lands."""

    def test_an_oversized_upload_is_refused_by_its_declared_length(self, client, admin):
        """No body is sent at all: the Content-Length alone decides."""
        res = client.post(
            "/api/settings/login-image",
            headers=admin["headers"] | {"content-length": str(50 * 1024 * 1024)},
            content=b"",
        )
        assert res.status_code == 413
        assert "smaller" in res.json()["detail"]

    def test_the_restore_route_is_allowed_a_far_larger_body(self, client, admin):
        """A library's covers in one zip is legitimately bigger than 5 MB, so
        the cap is per route rather than global."""
        res = client.post(
            "/api/backup/restore",
            params={"confirm": True},
            headers=admin["headers"] | {"content-length": str(50 * 1024 * 1024)},
            content=b"",
        )
        assert res.status_code != 413

    def test_an_upload_that_declares_no_length_is_refused(self, client, admin):
        """Without a length there is nothing to check in advance, and the spool
        is bounded only by how long the client keeps sending."""
        res = client.post(
            "/api/settings/login-image",
            headers=admin["headers"]
            | {"content-type": "multipart/form-data; boundary=x", "transfer-encoding": "chunked"},
            content=b"",
        )
        assert res.status_code == 411

    def test_a_json_body_without_a_length_is_left_alone(self, client, admin):
        """The rule is deliberately multipart only: a JSON body is held in
        memory and bounded by the route's own parsing, and refusing it would
        break clients that stream."""
        res = client.post(
            "/api/books",
            headers=admin["headers"]
            | {"transfer-encoding": "chunked", "content-type": "application/json"},
            content=b'{"title": "Dune", "author": "Herbert"}',
        )
        assert res.status_code == 201

    def test_an_ordinary_request_passes_through(self, client, admin):
        res = client.get("/api/books", headers=admin["headers"])
        assert res.status_code == 200

    def test_a_refusal_still_carries_the_security_headers(self, client, admin):
        """It sits innermost so the layers around it still wrap the answer."""
        res = client.post(
            "/api/settings/login-image",
            headers=admin["headers"] | {"content-length": str(50 * 1024 * 1024)},
            content=b"",
        )
        assert res.headers["X-Content-Type-Options"] == "nosniff"
