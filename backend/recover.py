"""Set a password from the container's command line.

**The last admin's way back in, and it is deliberately not a feature.** The admin
confirmed reset is member initiated by design, so a deployment with exactly one
admin has nobody who can approve that admin's own request. Owner's decision on
issue #105: that case belongs to the operator rather than to the product.
Whoever runs the container can already read and write the database, so this adds
no capability; it names the one that exists, so the last admin does not conclude
the deployment is lost. `README.md` carries the recipe.

**Never reachable over HTTP.** Nothing imports this module; it is run as
`python -m recover`, which means the only caller is somebody with a shell in the
container.

**The password is read from standard input and never from the argument list.**
An argument is in the shell's history and in `ps` output for every other process
on the host, which is a worse disclosure than the one this is repairing.

Everything a redemption does, this does too, and for the same reasons: it refuses
an account a directory authenticates, the hash is written through
`auth.hash_password`, so the 72 byte bcrypt bound is the one the rest of the app
applies, and `sessions_valid_from` moves, so a token somebody else is holding on
this account stops working. Confirming an account is
**not** one of the jobs here: the first account in a library is never gated, so
a sole admin cannot be waiting on one.
"""

import getpass
import sys

from accounts import now
from auth import hash_password
from database import SessionLocal
from models import User, app_holds_the_password
from schemas.user import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH


def main(argv: list[str]) -> int:
    """Set one account's password. Returns a process exit status."""
    if len(argv) != 2:
        print("usage: python -m recover <username>", file=sys.stderr)
        return 2
    username = argv[1]

    password = getpass.getpass("New password: ")
    if getpass.getpass("Again: ") != password:
        print("Those did not match.", file=sys.stderr)
        return 1
    # The registration policy, not a looser one. A command line is not a reason
    # to store a password the app would refuse in a form.
    if not MIN_PASSWORD_LENGTH <= len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES:
        print(
            f"A password is {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_BYTES} bytes.",
            file=sys.stderr,
        )
        return 1

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            print(f"No account called {username!r}.", file=sys.stderr)
            return 1
        # The same refusal a redemption makes, through the same predicate. A
        # directory row has no local credential, so a hash written here is one
        # nothing ever checks: the operator would leave believing the account was
        # recovered, which is worse than being told to look elsewhere.
        if not app_holds_the_password(user):
            print(
                f"{username!r} is authenticated by a directory. Its password is "
                "held there, not here.",
                file=sys.stderr,
            )
            return 1
        user.password_hash = hash_password(password)
        # The same clock every naive UTC column in this schema is written from.
        user.sessions_valid_from = now()
        db.commit()

    print(f"Password set for {username}. Every session on that account is over.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
