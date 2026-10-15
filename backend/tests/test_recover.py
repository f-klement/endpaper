"""The command line way back in, for a library with exactly one admin.

Not a feature and deliberately not reachable over HTTP: whoever runs the
container can already read and write the database, so this names a capability
that exists rather than adding one.
"""

import ast
import getpass

import kosync
import recover
from auth import verify_password
from models import User
from tests.corpus import BACKEND, shipped_modules


class TestNothingImportsIt:
    def test_no_module_of_the_app_imports_recover(self) -> None:
        """The only caller is somebody with a shell in the container.

        An import from a router would make this reachable over HTTP, which is
        the one property that would turn a documented operator capability into
        an endpoint that sets anybody's password.
        """
        offenders: list[str] = []
        read: set[str] = set()
        for path in shipped_modules():
            if path.name == "recover.py":
                continue
            read.add(path.parent.name)
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Import | ast.ImportFrom):
                    continue
                names_it = (
                    any(alias.name == "recover" for alias in node.names)
                    if isinstance(node, ast.Import)
                    else node.module == "recover"
                )
                if names_it:
                    offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
        assert offenders == [], offenders
        # **The packages it must cover, not a number.** This walk reads far more
        # files than any floor worth writing, so `read > 30` did not bind: a
        # mutation marking `routers` and `schemas` vendored left this guard
        # green, and a router is exactly where an import of this module would
        # make the password reset reachable over HTTP. Reading nothing is the
        # failure mode that matters most here. **No file count in this comment,
        # deliberately**: a figure written beside a rule drifts against the tree
        # within weeks and is then read as current, so recount it with a command
        # if you need it.
        assert {"routers", "schemas"} <= read, read


class TestSettingAPassword:
    def test_it_sets_one_and_ends_every_session(self, monkeypatch, db, member) -> None:
        typed = iter(["newpassword1", "newpassword1"])
        monkeypatch.setattr(getpass, "getpass", lambda _: next(typed))

        assert recover.main(["recover", "member"]) == 0

        user = db.query(User).filter(User.username == "member").one()
        db.refresh(user)
        assert verify_password("newpassword1", user.password_hash or "")
        assert user.sessions_valid_from is not None

    def test_it_signs_every_koreader_device_out(self, monkeypatch, db, member) -> None:
        user = db.query(User).filter(User.username == "member").one()
        kosync.mint(user)
        db.commit()
        typed = iter(["newpassword1", "newpassword1"])
        monkeypatch.setattr(getpass, "getpass", lambda _: next(typed))

        assert recover.main(["recover", "member"]) == 0

        db.refresh(user)
        assert user.kosync_key_digest is None

    def test_a_mismatch_changes_nothing(self, monkeypatch, db, member) -> None:
        typed = iter(["newpassword1", "typo"])
        monkeypatch.setattr(getpass, "getpass", lambda _: next(typed))

        assert recover.main(["recover", "member"]) == 1
        user = db.query(User).filter(User.username == "member").one()
        assert not verify_password("newpassword1", user.password_hash or "")

    def test_the_registration_length_floor_applies(
        self, monkeypatch, db, member
    ) -> None:
        """A command line is not a reason to store a password the app would
        refuse in a form."""
        typed = iter(["short", "short"])
        monkeypatch.setattr(getpass, "getpass", lambda _: next(typed))

        assert recover.main(["recover", "member"]) == 1

    def test_an_unknown_account_is_reported(self, monkeypatch, db, admin) -> None:
        typed = iter(["newpassword1", "newpassword1"])
        monkeypatch.setattr(getpass, "getpass", lambda _: next(typed))

        assert recover.main(["recover", "nobody"]) == 1

    def test_it_refuses_the_wrong_number_of_arguments(self) -> None:
        assert recover.main(["recover"]) == 2


class TestItRefusesAnAccountItDoesNotHoldThePasswordFor:
    """The same refusal a redemption makes, through the same predicate.

    A hash written on a directory row is one nothing ever checks, so the
    operator would leave believing the account was recovered. `README.md` points
    the last admin at this command, which is what makes a silent success worse
    than a refusal.
    """

    def test_a_directory_row_is_refused(self, monkeypatch, db, admin) -> None:
        from enums import AuthMode

        db.add(
            User(
                username="fromldap",
                password_hash=None,
                auth_source=AuthMode.LDAP.value,
            )
        )
        db.commit()
        typed = iter(["newpassword1", "newpassword1"])
        monkeypatch.setattr(getpass, "getpass", lambda _: next(typed))

        assert recover.main(["recover", "fromldap"]) == 1

        user = db.query(User).filter(User.username == "fromldap").one()
        assert user.password_hash is None
