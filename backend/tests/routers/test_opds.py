"""The OPDS routes: who may configure a server, who may sync one, and what a
sync writes.

`tests/test_opds.py` is the unit level home for the reader's bounds and
`tests/test_importing.py` for what an applied record does to a Book. This file
covers what only a request can show: the admin gate, the credential lifecycle,
and that deleting or moving a server takes its login with it.
"""

import pytest
import respx

import credentials
import fetch
from models import CatalogueCredential, OpdsServer

BASE = "http://library.invalid:8083/opds/books"

#: Where a writer that is not a route moves a server to.
MOVED = "http://attacker.invalid:8083/opds/books"

FEED = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<title>All books</title>"
    "<entry><title>Small Gods</title>"
    "<author><name>Terry Pratchett</name></author>"
    '<link rel="http://opds-spec.org/acquisition" href="/d/1"/></entry>'
    "<entry><title>Recently added</title>"
    '<link rel="subsection" href="/opds/recent"/></entry>'
    "<entry><title>On sale elsewhere</title>"
    '<link rel="http://opds-spec.org/acquisition/buy" href="/b/1"/></entry>'
    "</feed>"
)


@pytest.fixture
def encryption_key():
    """A key, so a credential can be sealed. Removed again by the conftest."""
    credentials.store_key(credentials.generate_phrase())


def make_server(client, admin, *, name="Home library", base_url=BASE) -> dict:
    response = client.post(
        "/api/opds/servers",
        json={"name": name, "base_url": base_url},
        headers=admin["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestOnlyAnAdminConfiguresWhichMachinesThisServerWillOpen:
    """Which addresses this application connects to is a deployment question.

    An admin typing a hostname turns this server into a request generator aimed
    at an address they choose, which is a capability nothing else on their list
    has. It is not one a member gets.
    """

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/opds/servers"),
            ("post", "/api/opds/servers"),
            ("put", "/api/opds/servers/1"),
            ("delete", "/api/opds/servers/1"),
            ("put", "/api/opds/servers/1/credential"),
            ("delete", "/api/opds/servers/1/credential"),
        ],
    )
    def test_a_member_is_refused(self, client, member, method, path):
        # `client.request`, because `TestClient.get` and `.delete` take no
        # `json=` and the gate has to be checked on those two as well.
        response = client.request(
            method.upper(),
            path,
            json={"name": "x", "base_url": BASE, "username": "u", "password": "p"},
            headers=member["headers"],
        )

        assert response.status_code == 403

    def test_a_member_may_still_sync_a_server_an_admin_configured(
        self, client, admin, member
    ):
        """Syncing writes into the catalogue as the member who asked, exactly as
        a CSV import does. It adds no address."""
        server = make_server(client, admin)

        with respx.mock:
            respx.get(BASE).respond(text=FEED)
            response = client.post(
                f"/api/opds/servers/{server['id']}/sync", headers=member["headers"]
            )

        assert response.status_code == 200

    def test_a_member_can_learn_which_servers_they_may_sync(self, client, admin, member):
        """**The id has to come from somewhere.** Without this route the split
        this class asserts is not deliverable: the full listing is admin only,
        so a member could reach the sync only by guessing an integer, and the
        test above hides that by taking the id from the admin's own response.
        """
        server = make_server(client, admin)

        listed = client.get("/api/opds/servers/mine", headers=member["headers"]).json()

        assert listed == [{"id": server["id"], "name": "Home library"}]

    def test_that_listing_carries_no_address_and_no_credential_state(
        self, client, admin, member, encryption_key
    ):
        """The address is the configuration an admin owns and the provenance is
        about a secret. Neither belongs on a screen that offers a button."""
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        body = client.get("/api/opds/servers/mine", headers=member["headers"]).text

        assert BASE not in body
        assert "credential" not in body


class TestAddingAndEditingAServer:
    def test_a_server_is_added_and_listed_with_no_login(self, client, admin):
        added = make_server(client, admin)

        listed = client.get("/api/opds/servers", headers=admin["headers"]).json()

        assert [(s["id"], s["name"], s["base_url"]) for s in listed] == [
            (added["id"], "Home library", BASE)
        ]
        assert listed[0]["credential_provenance"] == "none"

    @pytest.mark.parametrize(
        "address",
        [
            "file:///etc/passwd",
            "gopher://library.invalid/opds",
            "http://library.invalid@evil.invalid/opds",
            "http://library.invalid:99999/opds",
            "not an address",
        ],
    )
    def test_an_address_this_server_will_not_open_is_refused_at_the_write(
        self, client, admin, address
    ):
        response = client.post(
            "/api/opds/servers",
            json={"name": "Home library", "base_url": address},
            headers=admin["headers"],
        )

        assert response.status_code in (400, 422)

    def test_an_empty_name_is_refused(self, client, admin):
        response = client.post(
            "/api/opds/servers",
            json={"name": "   ", "base_url": BASE},
            headers=admin["headers"],
        )

        assert response.status_code == 422

    def test_an_address_only_one_of_the_two_parsers_can_read_is_refused(
        self, client, admin
    ):
        """The write gate and the fetch gate have to be one set. `is_fetchable`
        parses with `urlsplit` and `credentials.origin_of` with `httpx.URL`, and
        a host carrying a fullwidth letter is admitted by the first and answered
        `""` by the second: storable, and a 502 on every sync afterwards."""
        response = client.post(
            "/api/opds/servers",
            json={"name": "Home library", "base_url": "http://ｃalibre.home:8083/opds"},
            headers=admin["headers"],
        )

        assert response.status_code == 400

    def test_editing_a_server_that_does_not_exist_is_a_404(self, client, admin):
        response = client.put(
            "/api/opds/servers/999",
            json={"name": "x", "base_url": BASE},
            headers=admin["headers"],
        )

        assert response.status_code == 404


class TestALoginNeverFollowsAServerToADifferentMachine:
    """A moved row must not keep a login that names the machine it left.

    The envelope is sealed over its origin, so a login left behind could not be
    sent to the new address anyway. What this route buys is an honest row: a
    login kept across a move reports as held and unreadable for the rest of its
    life, which reads as a damaged row and sends somebody after a recovery
    phrase. Both edits that can produce a move are covered.
    """

    def test_a_rename_keeps_the_login(self, client, admin, encryption_key):
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        edited = client.put(
            f"/api/opds/servers/{server['id']}",
            json={"name": "The shed", "base_url": BASE},
            headers=admin["headers"],
        ).json()

        assert edited["credential_provenance"] == "stored"

    def test_a_path_change_on_the_same_machine_keeps_the_login(
        self, client, admin, encryption_key
    ):
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        edited = client.put(
            f"/api/opds/servers/{server['id']}",
            json={"name": "Home library", "base_url": f"{BASE}/all"},
            headers=admin["headers"],
        ).json()

        assert edited["credential_provenance"] == "stored"

    @pytest.mark.parametrize(
        "moved_to",
        [
            "http://elsewhere.invalid:8083/opds/books",
            "https://library.invalid:8083/opds/books",
            "http://library.invalid:9090/opds/books",
        ],
    )
    def test_moving_to_another_origin_drops_the_login(
        self, client, admin, db, encryption_key, moved_to
    ):
        """Host, scheme and port each make it a different machine."""
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        edited = client.put(
            f"/api/opds/servers/{server['id']}",
            json={"name": "Home library", "base_url": moved_to},
            headers=admin["headers"],
        ).json()

        assert edited["credential_provenance"] == "none"
        assert db.query(CatalogueCredential).count() == 0




class TestAnEnvelopeDoesNotOpenBesideAnAddressAnotherWriterChose:
    """What holds when the route above is not the writer, which is the point.

    `PUT /api/opds/servers/{id}` drops the login on a move and
    `backup._without_household_logins` drops it out of an archive, but neither
    is the last writer this column will ever have: `backup.restore` already
    inserts through Core with no validating arm, and a stray `UPDATE` needs no
    route at all. `credentials.seal` binds the origin, so a moved row makes the
    envelope unopenable rather than making the request go somewhere else.
    """

    @staticmethod
    def _move(db, server_id: int, address: str) -> OpdsServer:
        """Straight onto the column, which is what a restore and an UPDATE both do."""
        db.query(OpdsServer).filter(OpdsServer.id == server_id).update(
            {OpdsServer.base_url: address}
        )
        db.commit()
        db.expire_all()
        return db.get(OpdsServer, server_id)

    @pytest.fixture
    def sealed(self, client, admin, encryption_key):
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )
        return server

    def test_the_login_still_opens_at_the_address_it_was_entered_for(self, db, sealed):
        row = db.get(OpdsServer, sealed["id"])
        held = credentials.for_request(db, row.credential_key, row.base_url)
        assert held is not None
        assert held.header_for(BASE) != {}

    def test_a_row_moved_under_it_carries_nothing(self, db, sealed):
        row = self._move(db, sealed["id"], MOVED)
        assert credentials.for_request(db, row.credential_key, row.base_url) is None

    def test_and_the_envelope_is_still_there_to_be_removed(self, db, sealed):
        self._move(db, sealed["id"], MOVED)
        assert db.query(CatalogueCredential).count() == 1

    def test_the_screen_reports_it_held_and_unreadable_rather_than_gone(
        self, client, admin, db, sealed
    ):
        """Or an admin is told the login vanished and types it in again blind."""
        self._move(db, sealed["id"], MOVED)
        listed = client.get("/api/opds/servers", headers=admin["headers"]).json()
        assert (listed[0]["credential_provenance"], listed[0]["credential_unreadable"]) == (
            "stored",
            True,
        )

    @respx.mock
    def test_and_a_sync_of_the_moved_row_sends_no_authorization_header(
        self, client, admin, db, sealed
    ):
        """The measurement the ticket was raised on, run the other way round.

        With the source alone as associated data this request carried the
        household's `Basic` header to a host the archive named.
        """
        route = respx.get(MOVED).respond(text=FEED)
        self._move(db, sealed["id"], MOVED)

        client.post(f"/api/opds/servers/{sealed['id']}/sync", headers=admin["headers"])

        assert "authorization" not in route.calls[0].request.headers



class TestTheCredentialLifecycle:
    def test_a_stored_login_is_reported_as_stored_and_masked(
        self, client, admin, encryption_key
    ):
        server = make_server(client, admin)

        body = client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "samwise", "password": "hunter2"},
            headers=admin["headers"],
        ).json()

        assert body["credential_provenance"] == "stored"
        assert "hunter2" not in str(body)
        assert body["credential_username_preview"] != "samwise"
        assert body["credential_username_preview"]

    def test_storing_a_login_with_no_encryption_key_is_refused(self, client, admin):
        server = make_server(client, admin)

        response = client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        assert response.status_code == 409

    def test_a_username_carrying_a_colon_is_refused(self, client, admin, encryption_key):
        """RFC 7617 forbids one in a Basic user-id, and this application keeps
        one representation of the pair."""
        server = make_server(client, admin)

        response = client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam:wise", "password": "hunter2"},
            headers=admin["headers"],
        )

        assert response.status_code == 400

    def test_forgetting_a_login_succeeds_whether_or_not_there_was_one(
        self, client, admin
    ):
        server = make_server(client, admin)

        response = client.delete(
            f"/api/opds/servers/{server['id']}/credential", headers=admin["headers"]
        )

        assert response.status_code == 200
        assert response.json()["credential_provenance"] == "none"

    def test_deleting_a_server_takes_its_sealed_login_with_it(
        self, client, admin, db, encryption_key
    ):
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )
        assert db.query(CatalogueCredential).count() == 1

        client.delete(f"/api/opds/servers/{server['id']}", headers=admin["headers"])

        assert db.query(CatalogueCredential).count() == 0

    def test_each_server_gets_its_own_credential_key(self, client, admin, db):
        """Random rather than derived from the row id, so a deleted server can
        never lend its login to the next one added."""
        first = make_server(client, admin, name="One")
        make_server(client, admin, name="Two")

        keys = {row.credential_key for row in db.query(OpdsServer).all()}

        assert len(keys) == 2
        assert all(key.startswith("opds-") for key in keys)
        assert all(credentials.is_safe_source(key) for key in keys)
        assert first["id"] not in {int(k.split("-")[1], 16) for k in keys}


class TestASync:
    @respx.mock
    def test_only_what_the_member_holds_arrives_and_it_arrives_owned(
        self, client, admin
    ):
        """The shelf index and the title offered for sale are both passed over.
        An entitlement is not a holding, and this route's only assertion is
        ownership."""
        respx.get(BASE).respond(text=FEED)
        server = make_server(client, admin)

        body = client.post(
            f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"]
        ).json()

        assert (body["created"], body["entries_not_held"]) == (1, 2)
        assert body["pages_read"] == 1
        listed = client.get("/api/books", headers=admin["headers"]).json()
        assert [(b["title"], b["ownership"]) for b in listed["items"]] == [
            ("Small Gods", "owned")
        ]

    @respx.mock
    def test_a_holding_with_no_description_is_a_created_row_and_not_a_failure(
        self, client, admin
    ):
        """**The outcome is deliberate rather than incidental.** A feed carries
        a title and an author and nothing else, so a book added by a sync has no
        description until the catalogue chain supplies one, and for a born
        digital title it may never: of the eight catalogues a title search asks,
        six refuse a record that says it is electronic, five of them on codes
        and one on prose. A row like that is this route working, and it is
        reported under `created` so that it does not read as an import that half
        failed.
        """
        respx.get(BASE).respond(text=FEED)
        server = make_server(client, admin)

        body = client.post(
            f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"]
        ).json()

        assert (body["created"], body["skipped"]) == (1, 0)
        book = client.get("/api/books", headers=admin["headers"]).json()["items"][0]
        assert book["description"] is None
        assert (book["title"], book["author"]) == ("Small Gods", "Terry Pratchett")

    @respx.mock
    def test_syncing_twice_matches_rather_than_doubling_the_catalogue(
        self, client, admin
    ):
        respx.get(BASE).respond(text=FEED)
        server = make_server(client, admin)

        client.post(f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"])
        second = client.post(
            f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"]
        ).json()

        assert (second["created"], second["matched"]) == (0, 1)

    @respx.mock
    def test_a_stored_login_is_sent_to_that_server(
        self, client, admin, encryption_key
    ):
        route = respx.get(BASE).respond(text=FEED)
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        client.post(f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"])

        assert route.calls[0].request.headers["authorization"].startswith("Basic ")

    @respx.mock
    def test_a_server_that_refuses_is_a_502_naming_the_status(self, client, admin):
        respx.get(BASE).respond(status_code=401)
        server = make_server(client, admin)

        response = client.post(
            f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"]
        )

        assert response.status_code == 502
        assert "401" in response.json()["detail"]

    @respx.mock
    def test_a_failure_never_names_the_address_either(self, client, admin, member):
        """The 502 reaches a member and the address is otherwise admin only.

        Driven with an over-cap body rather than a connection error, because
        every `fetch.FetchRefused` formats the URL into its own message and a
        `ConnectError` does not: with the cheaper failure this guard would pass
        against the code it exists to refuse.
        """
        respx.get(BASE).respond(
            content=b"<feed>" + b"x" * (fetch.MAX_RESPONSE_BYTES + 1) + b"</feed>"
        )
        server = make_server(client, admin)

        response = client.post(
            f"/api/opds/servers/{server['id']}/sync", headers=member["headers"]
        )

        assert response.status_code == 502
        assert "library.invalid" not in response.text

    @respx.mock
    def test_a_failure_never_names_the_login(self, client, admin, encryption_key):
        respx.get(BASE).respond(status_code=500)
        server = make_server(client, admin)
        client.put(
            f"/api/opds/servers/{server['id']}/credential",
            json={"username": "sam", "password": "hunter2"},
            headers=admin["headers"],
        )

        response = client.post(
            f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"]
        )

        assert "hunter2" not in response.text
        assert "sam" not in response.text

    def test_syncing_a_server_that_does_not_exist_is_a_404(self, client, admin):
        response = client.post("/api/opds/servers/999/sync", headers=admin["headers"])

        assert response.status_code == 404

    @respx.mock
    def test_nothing_is_created_when_the_caller_asked_for_none(self, client, admin):
        respx.get(BASE).respond(text=FEED)
        server = make_server(client, admin)

        body = client.post(
            f"/api/opds/servers/{server['id']}/sync?create_missing=false",
            headers=admin["headers"],
        ).json()

        assert (body["created"], body["unmatched_titles"]) == (0, ["Small Gods"])

    @respx.mock
    def test_a_sync_spends_the_import_rate_limit(self, client, admin):
        """A walk of somebody's whole library and a write per entry, against an
        address an admin chose rather than one this build ships."""
        respx.get(BASE).respond(text=FEED)
        server = make_server(client, admin)

        codes = [
            client.post(
                f"/api/opds/servers/{server['id']}/sync", headers=admin["headers"]
            ).status_code
            for _ in range(4)
        ]

        assert 429 in codes
