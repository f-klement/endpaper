"""Tests for backend/routers/covers.py.

This route exists to close a hole, so these tests are the hole. Covers used to
be a bare `StaticFiles` mount, which has no dependencies: nothing authenticated
the caller and nothing asked whether they could see the book. Cover files are
named by book id, so a member could read another member's **private** book
cover by counting integers.

The two that matter are `test_a_members_private_cover_is_not_readable_by_another`
and `test_an_invisible_cover_is_404_not_403`. Everything else is scaffolding.
"""

from auth import COVER_COOKIE_NAME
from config import COVERS_DIR
from tests.conftest import TEST_PASSWORD
from tests.helpers import PNG_BYTES, proxy_headers


def _add_book(client, account, *, title: str, is_private: bool) -> int:
    response = client.post(
        "/api/books",
        json={"title": title, "is_private": is_private},
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _upload_cover(client, account, book_id: int) -> str:
    response = client.post(
        f"/api/books/{book_id}/cover",
        files={"file": ("cover.png", PNG_BYTES, "image/png")},
        headers=account["headers"],
    )
    assert response.status_code == 200, response.text
    return str(response.json()["cover_url"])


class TestAuthorisation:
    def test_a_members_private_cover_is_not_readable_by_another(
        self, client, admin, member, covers_dir
    ):
        """The whole reason this router replaced a static mount."""
        book_id = _add_book(client, admin, title="A diary", is_private=True)
        url = _upload_cover(client, admin, book_id)

        assert client.get(url, headers=admin["headers"]).status_code == 200
        assert client.get(url, headers=member["headers"]).status_code == 404

    def test_an_invisible_cover_is_404_not_403(
        self, client, admin, member, covers_dir
    ):
        """A 403 would confirm the book id exists, which is what privacy
        withholds. Same rule the book endpoints already follow."""
        book_id = _add_book(client, admin, title="A diary", is_private=True)
        _upload_cover(client, admin, book_id)

        response = client.get(f"/covers/{book_id}.png", headers=member["headers"])
        assert response.status_code == 404

    def test_a_public_cover_is_readable_by_any_member(
        self, client, admin, member, covers_dir
    ):
        """The shared shelf still works: this is not a lockdown of everything."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)

        assert client.get(url, headers=member["headers"]).status_code == 200

    def test_requires_authentication(self, client, covers_dir):
        """Every other path 401s without an identity. This one answered from
        disk."""
        assert client.get("/covers/1.png").status_code == 401


class TestServing:
    def test_serves_the_bytes_with_an_image_type(self, client, admin, covers_dir):
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)

        response = client.get(url, headers=admin["headers"])
        assert response.headers["content-type"] == "image/png"
        assert response.content == PNG_BYTES

    def test_is_cached_privately(self, client, admin, covers_dir):
        """`public` would let a shared cache serve one member's cover to
        another, which is the thing this router exists to prevent."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)

        cache_control = client.get(url, headers=admin["headers"]).headers[
            "cache-control"
        ]
        assert "private" in cache_control
        assert "public" not in cache_control

    def test_a_missing_file_is_404(self, client, admin, covers_dir):
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        response = client.get(f"/covers/{book_id}.png", headers=admin["headers"])
        assert response.status_code == 404

    def test_a_book_that_does_not_exist_is_404(self, client, admin, covers_dir):
        assert (
            client.get("/covers/999999.png", headers=admin["headers"]).status_code
            == 404
        )

    def test_an_extension_we_do_not_serve_is_404(self, client, admin, covers_dir):
        """Otherwise the route is a way to read any file in the covers
        directory whose name happens to start with a book id."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        (COVERS_DIR / f"{book_id}.svg").write_bytes(b"<svg/>")

        response = client.get(f"/covers/{book_id}.svg", headers=admin["headers"])
        assert response.status_code in (404, 422)

    def test_the_extension_is_matched_case_insensitively(
        self, client, admin, covers_dir
    ):
        """Some phones upload `.PNG`. The stored name is lower case, so the
        request has to normalise rather than miss."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        _upload_cover(client, admin, book_id)

        assert (
            client.get(f"/covers/{book_id}.PNG", headers=admin["headers"]).status_code
            == 200
        )

    def test_a_traversal_attempt_does_not_escape_the_directory(
        self, client, admin, covers_dir
    ):
        """The book id is parsed as an int and the extension is letters only,
        so neither half can carry a separator. Pinned rather than assumed."""
        for path in (
            "/covers/../../etc/passwd",
            "/covers/1.jpg/../../../config.py",
            "/covers/%2e%2e%2f%2e%2e%2fconfig.py",
        ):
            assert client.get(path, headers=admin["headers"]).status_code in (404, 422)


class TestTheCoverCookie:
    """An `<img src>` cannot send an Authorization header.

    Under proxy auth that is invisible, because identity arrives in a request
    header on every request. Under local auth, which is the published image's
    default, it means every cover in the grid would 401. These pin the cookie
    that closes that, and the three properties that keep it from being CSRF.
    """

    def test_login_issues_a_cookie(self, client, admin):
        response = client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        assert response.status_code == 200
        assert COVER_COOKIE_NAME in response.cookies

    def test_the_cookie_reaches_only_the_cover_path(self, client, admin):
        """Path scoping is what makes this safe: the browser never sends it to
        a route that changes anything, so it cannot authenticate a write."""
        response = client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        cookie = response.headers["set-cookie"]
        assert "Path=/covers" in cookie

    def test_the_cookie_is_not_readable_by_script(self, client, admin):
        response = client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        assert "HttpOnly" in response.headers["set-cookie"]

    def test_the_cookie_is_not_sent_cross_site(self, client, admin):
        """Lax rather than None. Another site embedding a cover as an <img>
        gets a 401, not a picture."""
        response = client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        assert "SameSite=lax" in response.headers["set-cookie"].replace(
            "SameSite=Lax", "SameSite=lax"
        )

    def test_a_cover_loads_with_only_the_cookie(self, client, admin, covers_dir):
        """The point of the whole thing: no Authorization header anywhere."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)

        client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        # No headers argument: the TestClient carries the cookie jar alone.
        assert client.get(url).status_code == 200

    def test_the_cookie_does_not_authenticate_the_api(self, client, admin):
        """If it did, the path scoping would be decoration and this would be a
        CSRF hole on every write."""
        client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        assert client.get("/api/books").status_code == 401

    def test_the_cookie_does_not_override_a_valid_header(
        self, client, admin, member, covers_dir
    ):
        """The header still decides, so a cover fetched by the client behaves
        exactly like every other call."""
        book_id = _add_book(client, admin, title="A diary", is_private=True)
        url = _upload_cover(client, admin, book_id)

        client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        assert client.get(url, headers=member["headers"]).status_code == 404

    def test_the_cookie_token_is_useless_as_a_bearer_token(self, client, admin):
        """Path scoping stops the browser sending it to the API. This stops
        anything that gets hold of the value from replaying it there by hand,
        which is the case path scoping cannot cover."""
        client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        stolen = client.cookies[COVER_COOKIE_NAME]

        res = client.get("/api/books", headers={"Authorization": f"Bearer {stolen}"})

        assert res.status_code == 401

    def test_an_access_token_is_not_accepted_from_the_cookie(
        self, client, admin, covers_dir
    ):
        """The other direction: the cover route wants the scoped token there,
        so a full token planted in the cookie is refused rather than being a
        second way in."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)

        client.cookies.clear()
        client.cookies.set(COVER_COOKIE_NAME, admin["access_token"], path="/covers")

        assert client.get(url).status_code == 401

    def test_logging_out_clears_the_cookie(self, client, admin, covers_dir):
        """Otherwise it outlives the session: on a shared machine the next
        person's first page load still fetches covers as whoever left."""
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)
        client.post(
            "/auth/login",
            json={"username": admin["user"]["username"], "password": TEST_PASSWORD},
        )
        assert client.get(url).status_code == 200

        assert client.post("/auth/logout").status_code == 204

        assert client.get(url).status_code == 401

    def test_a_forged_cookie_is_refused(self, client, admin, covers_dir):
        book_id = _add_book(client, admin, title="Dune", is_private=False)
        url = _upload_cover(client, admin, book_id)

        client.cookies.set(COVER_COOKIE_NAME, "not.a.token", path="/covers")
        assert client.get(url).status_code == 401


class TestProxyMode:
    """No route in proxy mode ever sets the cover cookie, because nothing logs
    in. The claim that covers still work rests on the upstream setting its
    header on the image request too, which is a claim about somebody else's
    software, so it is proved here rather than assumed.
    """

    def test_a_cover_loads_from_the_proxy_header_alone(
        self, client, proxy_mode, covers_dir
    ):
        account = {"headers": proxy_headers("kim")}
        book_id = _add_book(client, account, title="Dune", is_private=False)
        url = _upload_cover(client, account, book_id)

        assert client.get(url, headers=proxy_headers("kim")).status_code == 200

    def test_a_cover_still_needs_an_identity(self, client, proxy_mode, covers_dir):
        account = {"headers": proxy_headers("kim")}
        book_id = _add_book(client, account, title="Dune", is_private=False)
        url = _upload_cover(client, account, book_id)

        assert client.get(url).status_code == 401

    def test_the_privacy_rule_still_applies(self, client, proxy_mode, covers_dir):
        """`visible_to()` runs on this route whatever named the caller."""
        owner = {"headers": proxy_headers("kim")}
        book_id = _add_book(client, owner, title="A diary", is_private=True)
        url = _upload_cover(client, owner, book_id)

        assert client.get(url, headers=proxy_headers("sam")).status_code == 404


class TestTheLoginBackground:
    """It lives in the covers directory but is not a cover.

    The login page renders before anyone holds a token, so making this
    authenticated turns the one screen every visitor sees into a broken image.
    Caught in review after the covers route first landed, hence the tests.
    """

    def _set(self, client, admin) -> str:
        response = client.post(
            "/api/settings/login-image",
            files={"file": ("bg.png", PNG_BYTES, "image/png")},
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.text
        return str(response.json()["url"])

    def test_it_is_readable_with_no_identity_at_all(self, client, admin, covers_dir):
        url = self._set(client, admin)
        assert client.get(url).status_code == 200

    def test_it_is_still_served_from_the_covers_path(self, client, admin, covers_dir):
        """settings.py writes it there and reports that URL, so the two must
        agree or the login page points at nothing."""
        assert self._set(client, admin).startswith("/covers/login_bg.")

    def test_it_is_cached_publicly_unlike_a_book_cover(
        self, client, admin, covers_dir
    ):
        """Same bytes for everybody, so a shared cache is correct here and
        wrong for a cover."""
        url = self._set(client, admin)
        assert "public" in client.get(url).headers["cache-control"]

    def test_an_unset_background_is_404_not_a_page(self, client, covers_dir):
        """Falling through to the SPA would answer an <img> with index.html and
        a 200, which renders as a broken image with nothing to explain it."""
        response = client.get("/covers/login_bg.png")
        assert response.status_code == 404
        assert "text/html" not in response.headers.get("content-type", "")

    def test_it_does_not_expose_other_files_by_name(self, client, admin, covers_dir):
        """The public route is one filename, not the directory."""
        book_id = _add_book(client, admin, title="A diary", is_private=True)
        _upload_cover(client, admin, book_id)
        assert client.get(f"/covers/{book_id}.png").status_code == 401
