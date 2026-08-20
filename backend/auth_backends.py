"""Where "who is this?" gets answered.

Three modes, chosen with `AUTH_MODE`:

* **local** (default): accounts and bcrypt hashes in this database.
* **ldap**: credentials checked against a directory. Local signup is off, and
  a matching local row is created the first time someone signs in, because
  every foreign key in the schema points at `users.id`.
* **proxy**: an upstream (Authelia, oauth2-proxy, ...) has already
  authenticated the request and names the member in a header. No login screen.

Whatever the mode, a row in `users` is what the rest of the app works with. The
directory modes keep a *shadow* row: no password, `auth_source` recording where
it came from.
"""

import logging
import re

from fastapi import Request
from ldap3 import ALL, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.orm import Session

from auth import verify_password
from config import (
    auth_mode,
    ldap_admin_group,
    ldap_bind_dn,
    ldap_bind_password,
    ldap_start_tls,
    ldap_url,
    ldap_user_base_dn,
    ldap_user_filter,
    ldap_username_attribute,
    proxy_admin_group,
    proxy_groups_header,
    proxy_user_header,
)
from enums import AuthMode
from models import User

logger = logging.getLogger("endpaper.auth")

# Seconds to wait on the directory. It sits on the request path for a login,
# so an unreachable server must fail rather than hang a worker.
LDAP_TIMEOUT_SECONDS = 5


# ── Shadow accounts ───────────────────────────────────────────────────────────


def _free_username(db: Session, base: str) -> str:
    """`base` with the lowest numeric suffix nobody is using.

    Terminates: every candidate it rejects is a distinct row that already
    exists, and there are finitely many of those. Truncated to fit
    `users.username`, which is `String(50)`, so a maximum-length name does not
    come back too long to store.
    """
    suffix = 2
    while True:
        candidate = f"{base[: 49 - len(str(suffix))]}-{suffix}"
        if db.query(User).filter(User.username == candidate).first() is None:
            return candidate
        suffix += 1


def _move_test_account_aside(db: Session, user: User, source: AuthMode) -> None:
    """Free a test account's username for the directory identity of that name.

    `upsert_directory_user` matches on **username**, so without this a
    directory identity named like an admin-created test account adopts its row:
    `auth_source` flips, and the test account's books, loans and notes become
    that member's. Never adopting is the rule; the question is what to do
    instead, and none of the answers is free.

    Renaming, rather than refusing the sign-in. Refusing reads as the stricter
    choice and is the one that hurts: under proxy auth every request the real
    member makes would 401, this app has no endpoint that renames or deletes an
    account, so the remedy is a hand-edited database row. The test account is
    the disposable half of the collision, so it is the half that moves. It
    keeps its id, its data and its flag, so a session already switched into it
    keeps working and it is still a switch target under its new name.

    Loud, because a username changing without anybody asking is exactly the
    kind of thing that has to be findable afterwards.

    The rename is flushed on its own, before the caller inserts the new row.
    Both in one flush puts them in a single statement batch where the insert
    can land before the update and trip the unique index on `username`.
    """
    taken = user.username
    user.username = _free_username(db, taken)
    logger.warning(
        "Renamed the test account %r to %r: a %s identity of that name signed in, "
        "and a test account is never adopted by a directory",
        taken,
        user.username,
        source.value,
    )
    db.flush()


def upsert_directory_user(
    db: Session, username: str, *, is_admin: bool, source: AuthMode
) -> User:
    """Find or create the local row backing a directory identity.

    Admin status is re-applied on every sign-in, so removing someone from the
    admin group in the directory takes effect the next time they log in rather
    than being frozen at whatever it was when the row was first created.

    **Two exceptions to that, and both exist because the rule as written locks
    people out of their own library.**

    *The first account is an admin whatever the directory says.* In local mode
    that is what registration does. In proxy and LDAP mode registration is
    refused, and `is_admin` comes only from the configured group, so somebody
    deploying this image with `AUTH_MODE=proxy` and no groups header gets a
    catalogue nobody can administer: no settings, no metadata key, no backup,
    and no way to grant themselves any of it. There is no recovery path that
    does not involve editing the database by hand.

    *An existing admin is never demoted by a mode switch.* Turning on proxy or
    LDAP auth in front of a library that already had a local admin used to
    strip their rights on their first page load, silently, because the header
    carried no group. Demotion still works: it needs the admin group to be
    configured, so it is a directory decision rather than an accident of
    configuration.

    **A test account is never adopted.** The match is on username, so an
    admin-created test account named like a directory identity would otherwise
    hand over its books, loans and notes to whoever signs in with that name.
    It is renamed aside instead: see `_move_test_account_aside`.
    """
    user = db.query(User).filter(User.username == username).first()

    # Never adopt a test account. See `_move_test_account_aside`.
    #
    # The flag alone, deliberately, and NOT `is_switch_target`: this asks "did
    # an admin make this row", which is the question that decides whether its
    # books may change hands, and the answer must stay yes for a flagged row
    # that has stopped being switchable (a cleared hash, an edited
    # `auth_source`). Narrowing this to the switchable ones would quietly
    # re-open adoption for exactly the rows nobody is watching.
    if user is not None and user.is_test_account:
        _move_test_account_aside(db, user, source)
        user = None

    if user is None and db.query(User).count() == 0:
        # Same rule registration uses, for the same reason.
        logger.warning(
            "Making %r an admin: it is the first account in this library", username
        )
        is_admin = True

    if user is not None and user.is_admin and not is_admin and not _admin_group_set(source):
        logger.warning(
            "Keeping admin rights for %r: no admin group is configured for %s, "
            "so there is nothing to demote them on",
            username,
            source.value,
        )
        is_admin = True

    if user is None:
        user = User(
            username=username,
            password_hash=None,
            is_admin=is_admin,
            auth_source=source.value,
        )
        db.add(user)
        # WARNING, not INFO. Creating an account is the most consequential
        # thing this app does without anybody clicking anything, and under
        # proxy auth it happens on an ordinary GET. The one record of the
        # 2026-08-18 incident was an INFO line in a stream nobody reads.
        logger.warning(
            "Created account %r from a %s identity, admin=%s",
            username,
            source.value,
            is_admin,
        )
        db.commit()
        db.refresh(user)
        return user

    # Only write when something actually changed. Every request in proxy mode
    # reaches this, so an unconditional commit was a write per request against
    # the single SQLite writer, and an audit trail that could never say when
    # anything had genuinely changed.
    changed = user.is_admin != is_admin or user.auth_source != source.value
    if changed:
        if user.is_admin != is_admin:
            logger.warning(
                "Admin rights for %r changed to %s by a %s identity",
                username,
                is_admin,
                source.value,
            )
        user.is_admin = is_admin
        # An account that predates the switch to a directory keeps its rows and
        # its history; it simply stops being authenticated locally.
        user.auth_source = source.value
        db.commit()
        db.refresh(user)

    return user


# ── Local ─────────────────────────────────────────────────────────────────────


def authenticate_local(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ── LDAP ──────────────────────────────────────────────────────────────────────


def has_password(password: str | None) -> bool:
    """Is this something we are willing to send as a bind credential?

    Empty is the dangerous case, and whitespace-only is treated the same way:
    it cannot be a deliberate password, and some directories normalise it to
    empty before comparing, which lands back on the same anonymous bind.
    """
    return bool(password and password.strip())


def _connect(user: str | None = None, password: str | None = None) -> Connection:
    """Open a connection, refusing any binding that would be anonymous.

    LDAP has *two* ways to accidentally authenticate as nobody while looking
    like success:

      * a simple bind with an empty password (anonymous bind), and
      * a bind that supplies a DN but no password (an "unauthenticated" bind),
        which RFC 4513 requires servers to treat as anonymous.

    The second is the easy mistake to make in configuration: set LDAP_BIND_DN,
    forget LDAP_BIND_PASSWORD, and the service account silently becomes
    anonymous. Everything still appears to work, while the directory is being
    searched with whatever rights an anonymous caller has.
    """
    if user and not has_password(password):
        raise LDAPException(
            f"Refusing to bind as {user!r} without a password: the directory would "
            "treat this as an anonymous bind. Set LDAP_BIND_PASSWORD."
        )

    server = Server(ldap_url(), get_info=ALL, connect_timeout=LDAP_TIMEOUT_SECONDS)
    connection = Connection(
        server,
        user=user or None,
        password=password or None,
        auto_bind=False,
        receive_timeout=LDAP_TIMEOUT_SECONDS,
    )
    if ldap_start_tls():
        connection.start_tls()
    return connection


def _is_member_of_admin_group(entry: object, groups: list[str]) -> bool:
    """Exact, case-insensitive membership. Never a substring.

    This used to accept `wanted in group`, which grants admin for any group
    whose name merely *contains* the configured one. With `LDAP_ADMIN_GROUP`
    set to `admins`, membership of `cn=book-admins-readonly,...` was enough;
    with a full DN configured, a group under a `dc=home-clone` suffix matched
    too. Both were demonstrated. Creating a group is something ordinary
    directory users can often do, which makes it a privilege escalation rather
    than a loose comparison.

    The proxy path at `user_from_proxy_headers` has always compared exactly.
    """
    del entry  # Membership comes from `groups`, resolved by the caller.
    wanted = ldap_admin_group()
    if not wanted:
        return False
    wanted_lower = wanted.strip().lower()
    return any(wanted_lower == group.strip().lower() for group in groups)


def authenticate_ldap(db: Session, username: str, password: str) -> User | None:
    """Bind against the directory, then mirror the identity locally.

    Two-step: a service account (or an anonymous bind) searches for the entry,
    then the app re-binds *as that entry* with the supplied password. Binding
    directly with a constructed DN would only work for one directory layout.
    """
    # An empty password must never reach the server. Most LDAP servers treat a
    # bind with an empty password as an ANONYMOUS bind and return success, so
    # forwarding one turns "leave the password blank" into a login as anybody.
    # This is the single most important line in this function. `_connect`
    # enforces the same rule as a backstop, so a future caller cannot bypass it.
    if not has_password(password):
        return None

    # The username is escaped before substitution, so a value containing filter
    # metacharacters cannot rewrite the query.
    search_filter = ldap_user_filter().format(username=escape_filter_chars(username))

    try:
        with _connect(ldap_bind_dn(), ldap_bind_password()) as search_connection:
            if not search_connection.bind():
                logger.error("LDAP service bind failed: %s", search_connection.result)
                return None

            search_connection.search(
                search_base=ldap_user_base_dn(),
                search_filter=search_filter,
                attributes=[ldap_username_attribute(), "memberOf"],
            )
            if not search_connection.entries:
                # No such member. Deliberately indistinguishable from a wrong
                # password to whoever is asking.
                return None
            if len(search_connection.entries) > 1:
                logger.error(
                    "LDAP filter matched %d entries for %s",
                    len(search_connection.entries),
                    username,
                )
                return None

            entry = search_connection.entries[0]
            user_dn = entry.entry_dn
            groups = [str(group) for group in (entry.memberOf.values if "memberOf" in entry else [])]
            # Trust the directory's spelling of the name, not the one typed, so
            # "Kim" and "kim" cannot become two accounts.
            resolved_username = str(entry[ldap_username_attribute()].value)

        with _connect(user_dn, password) as user_connection:
            if not user_connection.bind():
                return None

    except LDAPException:
        # Directory unreachable or misconfigured. Logged with the traceback,
        # reported to the caller as an ordinary failed login.
        logger.exception("LDAP authentication failed for %s", username)
        return None

    return upsert_directory_user(
        db,
        resolved_username,
        is_admin=_is_member_of_admin_group(entry, groups),
        source=AuthMode.LDAP,
    )


# ── Proxy ─────────────────────────────────────────────────────────────────────


#: What a username coming from a header may look like.
#:
#: Deliberately narrow: letters, digits and the three separators a directory
#: actually uses. It is not an attempt to authenticate the header, which is
#: impossible from here. It bounds the damage of a header that is wrong, which
#: is a different and achievable goal.
_PROXY_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,49}$")


def _admin_group_set(source: AuthMode) -> bool:
    """Whether this mode has been told which group means admin.

    With no group configured, `is_admin` is always False, and re-applying that
    on every request is not a directory saying somebody is not an admin. It is
    the app having no opinion, and it must not be read as one.
    """
    if source is AuthMode.PROXY:
        return bool(proxy_admin_group())
    if source is AuthMode.LDAP:
        return bool(ldap_admin_group())
    return False


def _peer(request: Request) -> str:
    """The caller's address, for the log line, and never a raised exception.

    `request.client` is None for an ASGI transport that reports no peer. This
    is diagnostics on the refusal path: it must not be able to turn a rejected
    header into a 500.
    """
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def user_from_proxy_headers(db: Session, request: Request) -> User | None:
    """Trust an upstream's assertion of who this is.

    SAFE ONLY BEHIND A PROXY THAT SETS THESE HEADERS AND STRIPS INCOMING ONES.
    A header is client-supplied by default, so if this app is reachable
    directly then anyone can send `Remote-User: admin` and become an admin.
    That is a property of every proxy-auth integration, not a defect here, but
    it means AUTH_MODE=proxy must never be enabled on a container whose port is
    exposed beyond the proxy.

    **What this function can still do about it**, and now does, because on
    2026-08-18 a pod inside the cluster sent `Remote-User: intruder` straight
    to the Service and left a permanent admin account behind:

    * The name has to look like a username. `String(50)` is not enforced by
      SQLite, so an unvalidated header wrote whatever length it liked; a
      4000-character `Remote-User` produced a 4000-character account.
    * Anything rejected is logged at WARNING with the source address. The one
      trace that incident left was an INFO line nothing was watching.

    Neither makes the header trustworthy. The NetworkPolicy in front of the
    Service is what does that. These stop a mistake becoming a permanent row.
    """
    username = (request.headers.get(proxy_user_header()) or "").strip()
    if not username:
        return None

    if not _PROXY_USERNAME.match(username):
        # WARNING, and it names the peer: a rejected identity assertion is the
        # signature of either a misconfigured proxy or somebody reaching the
        # pod directly, and both are worth waking up for.
        logger.warning(
            "Refused a proxy identity that does not look like a username: %r (%d chars) from %s",
            username[:80],
            len(username),
            _peer(request),
        )
        return None

    raw_groups = (request.headers.get(proxy_groups_header()) or "").strip()
    groups = [group.strip() for group in raw_groups.split(",") if group.strip()]

    wanted = proxy_admin_group()
    is_admin = bool(wanted) and any(group.lower() == wanted.lower() for group in groups)

    return upsert_directory_user(db, username, is_admin=is_admin, source=AuthMode.PROXY)


# ── Dispatch ──────────────────────────────────────────────────────────────────


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Check a username and password using whichever backend is configured.

    Returns None in proxy mode: there is no password to check, because the
    proxy already did the authenticating.
    """
    mode = auth_mode()
    if mode is AuthMode.LOCAL:
        return authenticate_local(db, username, password)
    if mode is AuthMode.LDAP:
        return authenticate_ldap(db, username, password)
    return None


def local_signup_allowed() -> bool:
    """Registration only means anything when this app owns the passwords."""
    return auth_mode() is AuthMode.LOCAL
