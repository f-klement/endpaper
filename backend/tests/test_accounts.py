"""The account lifecycle: proving an address, and getting back in.

The rules here are the ones that decide whether an admin confirmed reset is a
recovery flow or a back door, so most of what follows is a guard rather than a
behaviour check.
"""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import accounts
import settings_store
from enums import AuthMode, SettingKey, VerificationProvenance
from models import PasswordResetRequest, User

BACKEND = Path(__file__).resolve().parent.parent


def _sources() -> list[Path]:
    """Every module of this app's own, migrations and the test tree excluded.

    **Stated as an exclusion.** An inclusion list is what goes stale the next
    time the backend grows a directory, which is the shape of guard defect this
    repository has already made once.
    """
    return [
        path
        for path in BACKEND.rglob("*.py")
        if ".venv" not in path.parts
        and "tests" not in path.parts
        and "migrations" not in path.parts
    ]


def _turn_the_policy_on(db) -> None:
    settings_store.set_value(db, SettingKey.ACCOUNTS_OPEN_TO_OUTSIDERS, "true")


class TestOnlyAMemberStartsAReset:
    """An admin may approve a request and may not make one.

    **The asymmetry the whole design rests on**, and it is structural: exactly
    one function inserts the row, and exactly one unauthenticated route calls
    it. An admin panel that could create a request would be an account takeover
    button with a friendly name.

    The residual is not covered here because no test can cover it: the request
    route takes a username anybody may type, so an admin can post a member's
    name and then approve it. `docs/decisions.md` records that, and the two
    tests below it here are what make doing so impossible to do quietly.
    """

    def test_no_module_but_accounts_constructs_a_reset_request(self) -> None:
        """The insert lives in one place, checked over the source rather than
        by trusting a review to notice a second one."""
        offenders: list[str] = []
        for path in _sources():
            if path.name == "accounts.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "PasswordResetRequest"
                ):
                    offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
        assert offenders == [], (
            "A reset request is created outside accounts.py: "
            f"{offenders}. Only a member may start a reset, and the one insert "
            "being reachable from one unauthenticated route is what makes that "
            "true rather than intended."
        )

    def test_accounts_creates_one_in_exactly_one_function(self) -> None:
        """And inside that module, in the one function named for it.

        Without this the rule above is satisfied by a second creator sitting
        beside the first, which is the same hole one file further in.
        """
        tree = ast.parse((BACKEND / "accounts.py").read_text())
        creators = [
            function.name
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef)
            and any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "PasswordResetRequest"
                for node in ast.walk(function)
            )
        ]
        assert creators == ["request_password_reset"], creators

    def test_approving_a_member_who_asked_for_nothing_creates_nothing(
        self, client, admin, member, db
    ) -> None:
        res = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        )
        assert res.status_code == 404, res.text
        assert db.query(PasswordResetRequest).count() == 0


class TestTheRecoveryRoutesAreNotARoster:
    """An unauthenticated route that says who exists is a roster.

    Both routes answer identically for a name that exists and one that does
    not, which is the same rule `/auth/login` follows for a wrong password and
    for a missing account.
    """

    def test_a_request_answers_the_same_for_a_name_nobody_holds(
        self, client, member
    ) -> None:
        real = client.post("/auth/reset/request", json={"username": "member"})
        absent = client.post("/auth/reset/request", json={"username": "nobody"})
        assert (real.status_code, real.text) == (absent.status_code, absent.text)
        assert real.status_code == 202

    def test_redeeming_answers_the_same_for_a_name_nobody_holds(
        self, client, member
    ) -> None:
        real = client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": "AAAA-AAAA-AAAA", "new_password": "abcdefgh"},
        )
        absent = client.post(
            "/auth/reset/redeem",
            json={"username": "nobody", "code": "AAAA-AAAA-AAAA", "new_password": "abcdefgh"},
        )
        assert (real.status_code, real.json()) == (absent.status_code, absent.json())
        assert real.status_code == 400

    def test_confirming_answers_the_same_for_a_name_nobody_holds(
        self, client, member
    ) -> None:
        real = client.post(
            "/auth/verify", json={"username": "member", "code": "AAAA-AAAA-AAAA"}
        )
        absent = client.post(
            "/auth/verify", json={"username": "nobody", "code": "AAAA-AAAA-AAAA"}
        )
        assert (real.status_code, real.json()) == (absent.status_code, absent.json())


class TestOneLiveRequestPerAccount:
    def test_asking_twice_queues_one_request(self, client, member, db) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        client.post("/auth/reset/request", json={"username": "member"})
        assert db.query(PasswordResetRequest).count() == 1

    def test_an_expired_request_is_replaced_rather_than_blocking(
        self, client, member, db
    ) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        row = db.query(PasswordResetRequest).one()
        row.expires_at = accounts.now() - timedelta(seconds=1)
        db.commit()

        client.post("/auth/reset/request", json={"username": "member"})
        db.expire_all()
        rows = db.query(PasswordResetRequest).all()
        assert len(rows) == 1
        # Not the primary key: SQLite hands the deleted row's rowid straight back
        # to the insert that follows it, so an id comparison here passes on a
        # tree where nothing was replaced and fails on one where it was.
        assert rows[0].expires_at > accounts.now()

    def test_asking_again_does_not_cancel_a_code_already_read_out(
        self, client, admin, member, db
    ) -> None:
        """An admin has already told the member this code. Replacing the row
        underneath them would answer a second click by invalidating it."""
        client.post("/auth/reset/request", json={"username": "member"})
        approval = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        )
        code = approval.json()["code"]

        client.post("/auth/reset/request", json={"username": "member"})

        res = client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )
        assert res.status_code == 204, res.text


class TestACodeIsSpentOnce:
    def test_a_redeemed_code_does_not_work_twice(
        self, client, admin, member
    ) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]

        assert (
            client.post(
                "/auth/reset/redeem",
                json={"username": "member", "code": code, "new_password": "brandnew1"},
            ).status_code
            == 204
        )
        again = client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "otherone1"},
        )
        assert again.status_code == 400

    def test_an_expired_code_does_not_work(
        self, client, admin, member, db
    ) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        row = db.query(PasswordResetRequest).one()
        row.code_expires_at = accounts.now() - timedelta(seconds=1)
        db.commit()

        res = client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )
        assert res.status_code == 400

    def test_spacing_and_case_are_not_part_of_the_code(
        self, client, admin, member
    ) -> None:
        """Somebody reading a code back drops the hyphens or types it lower
        case, and neither is a different code."""
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]

        res = client.post(
            "/auth/reset/redeem",
            json={
                "username": "member",
                "code": f" {code.replace('-', ' ').lower()} ",
                "new_password": "brandnew1",
            },
        )
        assert res.status_code == 204, res.text

    def test_the_code_is_not_stored_in_the_clear(
        self, client, admin, member, db
    ) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        stored = db.query(PasswordResetRequest).one().code_hash
        assert stored is not None
        assert accounts.normalise_code(code) not in stored


class TestAResetEndsEverySessionOnTheAccount:
    """The half a member cannot miss.

    A reset that left the member's live session working would be
    indistinguishable from a quiet takeover until their next sign in, which
    under a week long token is a week.
    """

    def test_the_members_own_token_stops_working(
        self, client, admin, member
    ) -> None:
        assert client.get("/auth/me", headers=member["headers"]).status_code == 200

        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )

        assert client.get("/auth/me", headers=member["headers"]).status_code == 401

    def test_nobody_elses_session_is_touched(self, client, admin, member) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )
        assert client.get("/auth/me", headers=admin["headers"]).status_code == 200

    def test_the_new_password_signs_in(self, client, admin, member) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )
        res = client.post(
            "/auth/login", json={"username": "member", "password": "brandnew1"}
        )
        assert res.status_code == 200, res.text

    def test_redeeming_hands_back_no_session(self, client, admin, member) -> None:
        """A code proves a person asked, not that they are anybody. The member
        signs in afterwards, which is also the check the password works."""
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        res = client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )
        assert res.status_code == 204
        assert res.content == b""


class TestTheMemberIsToldWhoApproved:
    def test_the_account_carries_the_approver_afterwards(
        self, client, admin, member
    ) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        code = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        client.post(
            "/auth/reset/redeem",
            json={"username": "member", "code": code, "new_password": "brandnew1"},
        )

        token = client.post(
            "/auth/login", json={"username": "member", "password": "brandnew1"}
        ).json()["access_token"]
        res = client.get(
            "/api/users/me/security", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200, res.text
        assert res.json()["password_reset_approved_by"] == "admin"
        assert res.json()["password_reset_at"] is not None

    def test_an_account_nothing_happened_to_says_so(
        self, client, member
    ) -> None:
        res = client.get("/api/users/me/security", headers=member["headers"])
        assert res.json()["password_reset_at"] is None


class TestResetIsRefusedWhereTheAppDoesNotHoldThePassword:
    """A reset under ldap or proxy either does nothing or resets the wrong
    thing, so the flow refuses and names the system that owns the credential."""

    @pytest.mark.parametrize(
        ("mode", "fragment"),
        [("ldap", "directory"), ("proxy", "signs you in")],
    )
    def test_the_request_route_refuses_and_says_who_owns_it(
        self, client, monkeypatch, mode, fragment
    ) -> None:
        monkeypatch.setenv("AUTH_MODE", mode)
        res = client.post("/auth/reset/request", json={"username": "member"})
        assert res.status_code == 403
        assert fragment in res.json()["detail"]

    def test_the_login_page_is_told_not_to_offer_it(
        self, client, monkeypatch
    ) -> None:
        monkeypatch.setenv("AUTH_MODE", "ldap")
        assert client.get("/auth/config").json()["password_reset_enabled"] is False

    def test_a_directory_row_is_never_a_reset_target(self, client, db) -> None:
        db.add(
            User(
                username="fromldap",
                password_hash=None,
                auth_source=AuthMode.LDAP.value,
            )
        )
        db.commit()
        client.post("/auth/reset/request", json={"username": "fromldap"})
        assert db.query(PasswordResetRequest).count() == 0

    def test_a_row_whose_auth_source_is_junk_is_not_a_directory_row(self) -> None:
        """`app_holds_the_password` is an exclusion, so an unrecognised
        `auth_source` fails **closed**: the app treats it as its own and applies
        the policy, rather than waving it past a gate meant for directories."""
        from models import app_holds_the_password

        assert app_holds_the_password(User(username="x", auth_source="")) is True
        assert app_holds_the_password(User(username="x", auth_source="LOCAL")) is True
        assert (
            app_holds_the_password(User(username="x", auth_source=AuthMode.LDAP.value))
            is False
        )


class TestOnlyAnAdminAssertionNamesAnAdmin:
    """The pairing `users` has no check constraint for.

    Adding one forces a batch rewrite of a table carrying a self referential
    foreign key, so one writer plus this test is the enforcement. `models.User`
    and the migration both say so at their own sites.
    """

    @pytest.mark.parametrize(
        "source",
        [
            VerificationProvenance.NOT_REQUIRED,
            VerificationProvenance.EMAIL,
            VerificationProvenance.DIRECTORY,
        ],
    )
    def test_every_other_provenance_names_nobody(self, source) -> None:
        user = User(username="x")
        accounts.record_verification(user, source)
        assert user.email_verified_by_user_id is None
        assert user.email_verification_source == source.value

    def test_an_admin_assertion_without_an_admin_is_refused(self) -> None:
        with pytest.raises(ValueError):
            accounts.record_verification(User(username="x"), VerificationProvenance.ADMIN)

    def test_another_provenance_with_an_admin_is_refused(self) -> None:
        admin = User(username="a")
        admin.id = 1
        with pytest.raises(ValueError):
            accounts.record_verification(
                User(username="x"), VerificationProvenance.EMAIL, by=admin
            )


class TestAnUnconfirmedAccountMayDoNothing:
    """Owner's decision, 2026-09-06: the login is refused outright.

    Read only was refused on surface: a third account state threaded through
    every write path is a silent hole where a path forgets it. The check sits at
    the boundary that produces a session, and at the one that accepts a token
    already minted, and those are the same function.
    """

    def test_registering_under_the_policy_hands_back_no_token(
        self, client, admin, db
    ) -> None:
        _turn_the_policy_on(db)
        res = client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["verification_required"] is True
        assert res.json()["token"] is None

    def test_signing_in_is_refused_with_a_reason(self, client, admin, db) -> None:
        _turn_the_policy_on(db)
        client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )
        res = client.post(
            "/auth/login", json={"username": "stranger", "password": "password123"}
        )
        assert res.status_code == 403
        assert "confirmed" in res.json()["detail"]

    def test_a_token_an_unconfirmed_account_holds_is_refused(
        self, client, admin, db
    ) -> None:
        """The gate is in `_user_from_token`, which every token path funnels
        through, rather than in the two `get_current_user` functions: a check
        placed in the callers is a check the next caller does not have.

        The account is built here rather than taken from a fixture, because
        every path in the application stamps a confirmation and the fixtures now
        do too. An account with none is what a hand edited row or an archive
        older than this migration produces, and this is what happens to one.
        """
        from auth import create_access_token, hash_password

        stray = User(username="stray", password_hash=hash_password("password123"))
        db.add(stray)
        db.commit()
        db.refresh(stray)
        token = create_access_token(db, stray.id, stray.username)
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/auth/me", headers=headers).status_code == 200
        _turn_the_policy_on(db)
        assert client.get("/auth/me", headers=headers).status_code == 401

    def test_the_refusal_lifts_when_an_admin_confirms(
        self, client, admin, db
    ) -> None:
        _turn_the_policy_on(db)
        client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )
        stranger = db.query(User).filter(User.username == "stranger").one()

        res = client.post(
            f"/api/users/{stranger.id}/verify", headers=admin["headers"]
        )
        assert res.status_code == 200, res.text
        assert res.json()["verified_by"] == "admin"
        assert (
            client.post(
                "/auth/login",
                json={"username": "stranger", "password": "password123"},
            ).status_code
            == 200
        )

    def test_the_policy_being_off_refuses_nobody(self, client, member) -> None:
        assert client.get("/auth/me", headers=member["headers"]).status_code == 200

    def test_an_account_made_while_the_policy_was_off_is_stamped_confirmed(
        self, client, admin, db
    ) -> None:
        """Turning the switch on afterwards must not strand a member already
        here, which is what stamping at creation buys."""
        client.post(
            "/auth/register", json={"username": "household", "password": "password123"}
        )
        _turn_the_policy_on(db)
        res = client.post(
            "/auth/login", json={"username": "household", "password": "password123"}
        )
        assert res.status_code == 200, res.text

    def test_the_first_account_is_never_gated(self, client, db) -> None:
        """There would be no admin to override it, and no mailbox configured
        yet, so a deployment that switched the policy on first would have no way
        in at all."""
        _turn_the_policy_on(db)
        res = client.post(
            "/auth/register", json={"username": "first", "password": "password123"}
        )
        assert res.status_code == 201, res.text
        assert res.json()["verification_required"] is False
        assert res.json()["token"] is not None

    def test_an_address_is_required_where_one_will_be_confirmed(
        self, client, admin, db
    ) -> None:
        _turn_the_policy_on(db)
        res = client.post(
            "/auth/register", json={"username": "stranger", "password": "password123"}
        )
        assert res.status_code == 400
        assert db.query(User).filter(User.username == "stranger").first() is None


class TestConfirmationDoesNotApplyToADirectoryAccount:
    def test_an_admin_cannot_confirm_what_a_directory_authenticated(
        self, client, admin, db
    ) -> None:
        db.add(
            User(
                username="fromldap",
                password_hash=None,
                auth_source=AuthMode.LDAP.value,
            )
        )
        db.commit()
        target = db.query(User).filter(User.username == "fromldap").one()
        res = client.post(
            f"/api/users/{target.id}/verify", headers=admin["headers"]
        )
        assert res.status_code == 409

    def test_a_directory_row_is_stamped_when_it_is_created(self, db) -> None:
        from auth_backends import upsert_directory_user

        user = upsert_directory_user(
            db, "kim", is_admin=False, source=AuthMode.LDAP
        )
        assert user.email_verification_source == VerificationProvenance.DIRECTORY.value


class TestTheCodeIsNeverServedTwice:
    def test_the_queue_carries_no_code(self, client, admin, member) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        )
        listing = client.get("/api/users/password-resets", headers=admin["headers"])
        assert listing.status_code == 200
        # The **keys**, not a substring of the body: `code_expires_at` contains
        # the word and is not a code, so a substring check here reports a leak
        # that is not there and would be relaxed by whoever met it next.
        assert [set(row) & {"code", "code_hash"} for row in listing.json()] == [set()]

    def test_the_queue_says_until_when_the_code_works(
        self, client, admin, member
    ) -> None:
        """**What an admin has left after a reload.** The plaintext lives in
        component state and is gone; this field is the only thing that still
        says when it stops working, and dropping it from the response was not
        caught by the frontend test, which drives the component with a prop.
        """
        client.post("/auth/reset/request", json={"username": "member"})
        client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        )
        row = client.get(
            "/api/users/password-resets", headers=admin["headers"]
        ).json()[0]

        assert row["code_expires_at"] is not None
        assert row["approved_by"] == "admin"

    def test_re_approving_mints_a_different_code(
        self, client, admin, member
    ) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        first = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        second = client.post(
            f"/api/users/password-resets/{member['user']['id']}/approve",
            headers=admin["headers"],
        ).json()["code"]
        assert first != second
        assert (
            client.post(
                "/auth/reset/redeem",
                json={"username": "member", "code": first, "new_password": "brandnew1"},
            ).status_code
            == 400
        )


class TestTheAdminPanelIsAdminOnly:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/users/password-resets"),
            ("get", "/api/users/verification"),
            ("post", "/api/users/password-resets/1/approve"),
            ("delete", "/api/users/password-resets/1"),
            ("post", "/api/users/1/verify"),
        ],
    )
    def test_a_member_is_refused(self, client, member, method, path) -> None:
        res = getattr(client, method)(path, headers=member["headers"])
        assert res.status_code == 403, res.text

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/users/password-resets"),
            ("get", "/api/users/verification"),
            ("post", "/api/users/password-resets/1/approve"),
            ("delete", "/api/users/password-resets/1"),
            ("post", "/api/users/1/verify"),
            ("get", "/api/users/me/security"),
        ],
    )
    def test_nobody_at_all_is_refused(self, client, method, path) -> None:
        assert getattr(client, method)(path).status_code == 401


class TestDecliningARequest:
    def test_it_leaves_the_queue(self, client, admin, member, db) -> None:
        client.post("/auth/reset/request", json={"username": "member"})
        res = client.request(
            "DELETE",
            f"/api/users/password-resets/{member['user']['id']}",
            headers=admin["headers"],
        )
        assert res.status_code == 204, res.text
        assert db.query(PasswordResetRequest).count() == 0


class TestTheRecoveryRoutesAreRateLimited:
    def test_the_address_budget_bounds_a_flood_across_accounts(
        self, client, member
    ) -> None:
        """A per account limit alone lets one address work through the roster
        slowly, so the address is charged too."""
        from ratelimit import RECOVERY_REQUEST_LIMIT

        for index in range(RECOVERY_REQUEST_LIMIT.max_attempts):
            res = client.post("/auth/reset/request", json={"username": f"n{index}"})
            assert res.status_code == 202
        res = client.post("/auth/reset/request", json={"username": "member"})
        assert res.status_code == 429

    def test_the_account_budget_bounds_a_flood_against_one_member(
        self, client, member, monkeypatch
    ) -> None:
        """And a per address limit alone lets a botnet queue a hundred requests
        against one member, so the account is charged too."""
        import ratelimit

        # The address key is the one this client shares across the loop, so it
        # is lifted rather than the account key being tested through it.
        monkeypatch.setattr(
            ratelimit,
            "recovery_request_address_limiter",
            ratelimit.SlidingWindowLimiter(
                ratelimit.RateLimit(max_attempts=1000, window_seconds=60)
            ),
        )
        monkeypatch.setattr(
            "routers.auth.recovery_request_address_limiter",
            ratelimit.recovery_request_address_limiter,
        )
        for _ in range(ratelimit.RECOVERY_REQUEST_LIMIT.max_attempts):
            assert (
                client.post(
                    "/auth/reset/request", json={"username": "member"}
                ).status_code
                == 202
            )
        assert (
            client.post("/auth/reset/request", json={"username": "member"}).status_code
            == 429
        )

    def test_guessing_a_code_is_bounded(self, client, member) -> None:
        from ratelimit import RECOVERY_CODE_LIMIT

        for _ in range(RECOVERY_CODE_LIMIT.max_attempts):
            client.post(
                "/auth/reset/redeem",
                json={
                    "username": "member",
                    "code": "AAAA-AAAA-AAAA",
                    "new_password": "abcdefgh",
                },
            )
        res = client.post(
            "/auth/reset/redeem",
            json={
                "username": "member",
                "code": "AAAA-AAAA-AAAA",
                "new_password": "abcdefgh",
            },
        )
        assert res.status_code == 429


class TestConfirmingByCode:
    def test_the_code_confirms_the_account(self, client, admin, db) -> None:
        _turn_the_policy_on(db)
        client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )
        user = db.query(User).filter(User.username == "stranger").one()
        code = accounts.start_verification(db, user)

        res = client.post(
            "/auth/verify", json={"username": "stranger", "code": code}
        )
        assert res.status_code == 204, res.text
        db.refresh(user)
        assert user.email_verification_source == VerificationProvenance.EMAIL.value
        assert (
            client.post(
                "/auth/login",
                json={"username": "stranger", "password": "password123"},
            ).status_code
            == 200
        )

    def test_a_spent_code_does_not_work_twice(self, client, admin, db) -> None:
        _turn_the_policy_on(db)
        client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )
        user = db.query(User).filter(User.username == "stranger").one()
        code = accounts.start_verification(db, user)
        client.post("/auth/verify", json={"username": "stranger", "code": code})
        again = client.post(
            "/auth/verify", json={"username": "stranger", "code": code}
        )
        assert again.status_code == 400


class TestTheOverrideDoesNotRewriteAConfirmationSomebodyElseMade:
    """An account that settled itself is left alone.

    Re-stamping would overwrite a member's own confirmation with an admin's
    name, so the member's account screen would afterwards say an admin confirmed
    an address they proved themselves. The admin screen hides the control for
    such a row, and a client is not a control.
    """

    def test_a_second_confirmation_keeps_the_first_record(
        self, client, admin, db
    ) -> None:
        _turn_the_policy_on(db)
        client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )
        user = db.query(User).filter(User.username == "stranger").one()
        code = accounts.start_verification(db, user)
        client.post("/auth/verify", json={"username": "stranger", "code": code})

        res = client.post(f"/api/users/{user.id}/verify", headers=admin["headers"])

        assert res.status_code == 200, res.text
        assert res.json()["verification_source"] == VerificationProvenance.EMAIL.value
        assert res.json()["verified_by"] is None


class TestNeitherBranchOfAResendIsFree:
    """The resend route mints a code for an account that is waiting and does
    nothing for a name nobody holds, and minting one is a bcrypt.

    Without the discarded comparison the two branches differ by the cost of a
    bcrypt, which is the roster read off a clock rather than off the body. The
    body is identical either way and that is checked in
    `TestTheRecoveryRoutesAreNotARoster`; this checks the other channel.
    """

    def _counted(self, monkeypatch):
        """Count every bcrypt this module performs, real work included."""
        # Warm the dummy hash first, so the count describes the request rather
        # than the one time cost of building it.
        accounts.spend_a_comparison("warm")
        calls: list[str] = []
        # Through `auth`, not through `accounts`, which imported the two names
        # rather than exporting them. `monkeypatch.setattr` still installs the
        # counters on `accounts`, which is the namespace the calls are made in.
        from auth import hash_password as real_hash
        from auth import verify_password as real_verify

        def counting_hash(value: str) -> str:
            calls.append("hash")
            return real_hash(value)

        def counting_verify(plain: str, hashed: str) -> bool:
            calls.append("verify")
            return real_verify(plain, hashed)

        monkeypatch.setattr(accounts, "hash_password", counting_hash)
        monkeypatch.setattr(accounts, "verify_password", counting_verify)
        return calls

    def test_both_branches_cost_the_same(
        self, client, admin, db, monkeypatch
    ) -> None:
        """**Equality, not presence, and the difference is an evasion.**

        The first version of this asserted each branch performed *at least one*
        bcrypt, in two separate tests. Moving `spend_a_comparison` out of the
        `else` and charging it unconditionally passes both of those and restores
        the oracle inverted: the waiting branch then pays two and the unknown
        name pays one. The security seat found it; the property the route needs
        is that the two are equal, so that is what is compared.
        """
        _turn_the_policy_on(db)
        client.post(
            "/auth/register",
            json={
                "username": "stranger",
                "password": "password123",
                "email": "stranger@example.org",
            },
        )

        calls = self._counted(monkeypatch)
        client.post("/auth/verify/request", json={"username": "stranger"})
        waiting = len(calls)

        calls.clear()
        client.post("/auth/verify/request", json={"username": "nobody"})
        unknown = len(calls)

        assert waiting > 0, "neither branch performed a bcrypt, so this compares nothing"
        assert waiting == unknown, (
            f"the branch that mints a code performed {waiting} bcrypts and the "
            f"branch that mints nothing performed {unknown}. The difference is "
            "readable over a network and is the roster the identical response "
            "body withholds."
        )


class TestTheRevocationCutoffCarriesSubSecondPrecision:
    """The half of session revocation that whole seconds break, in both
    directions, at an explicit fractional cutoff.

    **Neither direction was guarded except by where the wall clock fell.**
    `TestAResetEndsEverySessionOnTheAccount` exercises this incidentally: it
    passes with a re-floored cutoff whenever the sign in and the reset land
    either side of a second boundary, which is most of the time. The design seat
    found that, and these two set the cutoff and the `iat` by hand instead.

    Both were live defects on this tree, one after the other:

    * floored, a token minted in the same second as the reset survived it, which
      is the session the reset exists to end;
    * unfloored on one side only, a member signing in immediately after their own
      reset presented an `iat` that floored to before the cutoff and was refused
      the session the password they had just set was for.
    """

    def _user(self, db, cutoff) -> User:
        user = User(username="cutoff", password_hash="x")
        accounts.record_verification(user, VerificationProvenance.NOT_REQUIRED)
        user.sessions_valid_from = cutoff
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def test_a_token_from_earlier_in_the_same_second_is_refused(self, db) -> None:
        cutoff = accounts.now().replace(microsecond=900_000)
        user = self._user(db, cutoff)
        # 12:00:00.1 against a cutoff of 12:00:00.9. Whole seconds make both
        # 12:00:00 and let this token through.
        issued = (cutoff.replace(microsecond=100_000).replace(tzinfo=UTC)).timestamp()

        assert accounts.session_is_live(db, user, issued) is False

    def test_a_token_from_later_in_the_same_second_is_accepted(self, db) -> None:
        cutoff = accounts.now().replace(microsecond=900_000)
        user = self._user(db, cutoff)
        # 12:00:00.95 against the same cutoff: the sign in that follows a reset.
        # Whole seconds floor it to 12:00:00 and refuse the member the session
        # the password they just set is for.
        issued = (cutoff.replace(microsecond=950_000).replace(tzinfo=UTC)).timestamp()

        assert accounts.session_is_live(db, user, issued) is True

    def test_a_token_with_no_issue_time_is_refused_once_the_column_is_set(
        self, db
    ) -> None:
        """A token minted before the column existed carries no `iat` at all."""
        user = self._user(db, accounts.now())

        assert accounts.session_is_live(db, user, None) is False

    def test_a_token_with_no_issue_time_is_accepted_while_it_is_not(self, db) -> None:
        """So an upgrade ends nobody's session, and the first reset after it ends
        every session on that account."""
        user = User(username="untouched", password_hash="x")
        accounts.record_verification(user, VerificationProvenance.NOT_REQUIRED)
        db.add(user)
        db.commit()
        db.refresh(user)

        assert accounts.session_is_live(db, user, None) is True


class TestATokenRecordsWhenItWasMintedToBetterThanASecond:
    """The other half of the revocation rule, and it sits in `auth._encode`.

    **Written as an evasion attempt that got through.** Rounding `iat` back to a
    whole second was not caught by anything: the class above drives
    `session_is_live` directly with a float and never reaches the encoder, and
    the end to end arms pass or fail on where the wall clock falls, which is a
    flake rather than a guard.

    The type is the property, and asserting it is what makes this deterministic.
    PyJWT turns a `datetime` claim into whole seconds through `utctimetuple`, so
    handing it one silently reintroduces the rounding; handing it a float leaves
    a float, which is what RFC 7519's NumericDate allows. A fractional part could
    be zero by chance one time in a million, and a type cannot be.
    """

    def test_the_issue_time_is_not_a_whole_second(self, db, member) -> None:
        import jwt

        from auth import ALGORITHM, create_access_token
        from config import secret_key

        token = create_access_token(db, member["user"]["id"], "member")
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])

        assert isinstance(payload["iat"], float), (
            "`iat` came back as an int, so it was rounded to a whole second on "
            "the way in. A member signing in inside the same second as their own "
            "reset then presents an issue time earlier than the cutoff and is "
            "refused the session the password they just set is for."
        )
        assert abs(payload["iat"] - datetime.now(UTC).timestamp()) < 5
