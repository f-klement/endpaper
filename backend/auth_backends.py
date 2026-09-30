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

import mailer
from accounts import record_verification
from auth import verify_password
from config import (
    auth_mode,
    ldap_admin_group,
    ldap_bind_dn,
    ldap_bind_password,
    ldap_email_attribute,
    ldap_start_tls,
    ldap_url,
    ldap_user_base_dn,
    ldap_user_filter,
    ldap_username_attribute,
    proxy_admin_group,
    proxy_email_header,
    proxy_groups_header,
    proxy_user_header,
)
from enums import AuthMode, VerificationProvenance
from logvalues import clipped
from models import USERNAME_MAX, User

logger = logging.getLogger("endpaper.auth")

# Seconds to wait on the directory. It sits on the request path for a login,
# so an unreachable server must fail rather than hang a worker.
LDAP_TIMEOUT_SECONDS = 5


# ── Shadow accounts ───────────────────────────────────────────────────────────


def _free_username(db: Session, base: str) -> str:
    """`base` with the lowest numeric suffix nobody is using.

    Terminates: every candidate it rejects is a distinct row that already
    exists, and there are finitely many of those. Truncated to fit
    `users.username`, so a maximum-length name does not come back too long to
    store: the width, the hyphen and the suffix together are what has to fit.

    **`USERNAME_MAX` rather than the number**, because a truncation written as a
    literal keeps truncating at the old width after the column is widened and
    nothing goes red.
    """
    suffix = 2
    while True:
        candidate = f"{base[: USERNAME_MAX - 1 - len(str(suffix))]}-{suffix}"
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
        "Renamed the test account %s to %s: a %s identity of that name signed in, "
        "and a test account is never adopted by a directory",
        clipped(taken),
        clipped(user.username),
        source.value,
    )
    db.flush()


def directory_owns_email(auth_source: str) -> bool:
    """Whether the directory behind this row decides its address.

    **The whole of the "who may edit it" rule, in one place.** Empty
    configuration means the directory has no opinion, and an app must not read
    silence as an assertion: that is the same reasoning `_admin_group_set`
    carries for demotion, and it is why `LDAP_EMAIL_ATTRIBUTE` and
    `PROXY_EMAIL_HEADER` default to empty rather than to `mail` and
    `Remote-Email`.

    So the two owner decisions on issue #80 are one rule rather than a conflict.
    The directory owns the address wherever it has been told which attribute
    carries one, and there the field is read only for everybody, an admin
    included, because a write nobody may make is a write the next sign in cannot
    silently revert. Everywhere else it is the member's own, and an admin may
    write it for anybody.

    Takes the stored string rather than an `AuthMode`, because every caller has
    a row in hand and `users.auth_source` carries no `CheckConstraint`: a
    restored row spelling it something else is a row no directory is configured
    for, which is exactly the `False` this returns.
    """
    if auth_source == AuthMode.PROXY.value:
        return bool(proxy_email_header())
    if auth_source == AuthMode.LDAP.value:
        return bool(ldap_email_attribute())
    return False


def _directory_email(raw: str | None) -> str | None:
    """What a directory asserted, or None if it asserted nothing usable.

    Checked with `mailer.looks_like_address`, the same rule the household
    address passes, so a directory cannot write into `users.email` a string the
    mailer would later refuse. It is also the header injection control: this
    value comes from a directory attribute or an upstream header, and both are
    outside this app.

    Bounded by `mailer.MAX_ADDRESS` before the length check can matter, because
    SQLite does not enforce `String(320)`. The 2026-08-18 incident was a
    4000-character `Remote-User` writing a 4000-character account.

    None for anything it will not take, so an unusable attribute is
    indistinguishable from an absent one. Both mean the directory named no
    address, and both clear the column where the directory owns it.
    """
    value = (raw or "").strip()
    if not value or len(value) > mailer.MAX_ADDRESS:
        return None
    return value if mailer.looks_like_address(value) else None


def _address_was_refused(raw: str | None) -> bool:
    """Did the directory assert something this app will not store?

    **Not the same event as the directory naming no address**, and the two were
    logged identically at INFO until a reviewer separated them. Both end in the
    column being cleared, and only one of them is somebody's mistake or
    somebody's attempt: a `Remote-Email` carrying a newline is the header
    injection shape the address rule exists to refuse, and it arrives on the
    same request whose `Remote-User` a refusal already logs at WARNING with the
    peer.

    Defined once, beside `_directory_email`, so "refused" cannot come to mean
    two things. The callers log it, because only they know whether there is a
    peer to name.
    """
    return bool((raw or "").strip()) and _directory_email(raw) is None


def upsert_directory_user(
    db: Session,
    username: str,
    *,
    is_admin: bool,
    source: AuthMode,
    email: str | None = None,
) -> User | None:
    """Find or create the local row backing a directory identity.

    `None` means the identity was refused and no row exists for it: today the
    one cause is a name wider than the column, argued at that check. Both
    callers already answer `User | None`, so a refused sign-in is a failed one.

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

    **`email` is re-applied on the same terms as `is_admin`, and only where the
    directory owns it.** `directory_owns_email` is asked here rather than by the
    callers, so "the directory decides" and "the directory is authoritative
    including its silence" are one decision in one place. Where it owns the
    value, an entry with no address clears the column, which is the demotion
    case unchanged. Where it does not, this touches nothing: a member's own
    address survives an LDAP deployment that never mentions addresses.

    **The clearing is not symmetric with the demotion, and that is the cost of
    copying the rule.** A wrongly demoted member is restored by putting them
    back in the admin group and signing in again. A cleared address is gone:
    the value is not kept anywhere, and the field is read only from the moment
    the attribute is configured, so neither the member nor an admin can type it
    back. `.env.example`, `README.md` and `DOCKERHUB.md` all say so, because
    the person who turns the attribute on is the one who needs to know.
    """
    # **Refused, not truncated, and this is where both doors meet.** The
    # column is `String(USERNAME_MAX)` and SQLite does not enforce a VARCHAR
    # length, so a directory returning a longer identifier used to write the
    # row and log it at that size.
    #
    # Truncating instead would be worse than storing it. The match below is on
    # `User.username`, which is unique, so two directory identities sharing a
    # `USERNAME_MAX` character prefix would land on one row and the second
    # sign-in would inherit the first's books, loans and notes, with a 200 and
    # nothing in the log. `catalogue._drop_unstorable` already ruled that way
    # for a catalogue record: half a value is an assertion nobody made.
    #
    # Here rather than at either resolution site, because this is the single
    # `User(...)` construction site the directory modes reach.
    # `tests/test_house_rules.py::TestEveryDirectoryDoorWritesThroughOneFunnel`
    # counts those sites per module, so a door appended here moves the census
    # rather than hiding behind a path that was already in it. It sees a call
    # to the model class and nothing else: a row written through Core, which
    # `backup.restore` does, is past it and past this check, and only the
    # column constraint `docs/decisions.md` declined would have bound that.
    #
    # **Only the LDAP door reaches this refusal, and saying so is the point.**
    # `_PROXY_USERNAME` derives its repeat from `USERNAME_MAX`, so the proxy
    # door already refused a wider name before this existed and returns None
    # without ever calling here. What is new is the LDAP door, where the value
    # is a directory attribute nothing bounded. This is the backstop for the
    # proxy door rather than its bound: widening that regex past the column
    # lands here instead of writing a row.
    #
    # **It also refuses a sign-in a stored row used to get.** The check sits
    # above the lookup, so a row already wider than the column, written before
    # this or restored through Core, no longer matches and its owner is locked
    # out until somebody renames it. Deliberate: that is the 2026-08-18 row as
    # well as a legitimate long directory name, and the line below names the
    # width and the name so an operator can find which.
    #
    # **And the lockout is per mode, which is the half that reads as a
    # contradiction otherwise.** Local mode never calls here, so the same wide
    # row signs in through `authenticate_local` and is served in full by the
    # member list, whose schema carries no ceiling. Switching a deployment
    # from local to a directory mode is therefore what turns that row from
    # working into locked out.
    #
    # `USERNAME_MAX` rather than a written width, for the reason
    # `_free_username` gives: a literal goes on refusing at the old width after
    # the column moves.
    if len(username) > USERNAME_MAX:
        # **Wording that shares no prefix with the proxy door's refusal, on
        # purpose.** With `source.value` at the front this reads `Refused a
        # proxy identity`, which is also how the header refusal opens, and an
        # alert rule or log filter keyed on that would conflate an
        # unauthenticated header event with a directory attribute one.
        # `tests/test_auth_backends.py::TestADirectoryNameWiderThanTheColumnIsRefused`
        # holds the two apart.
        logger.warning(
            "Refused a name users.username cannot hold: %d characters "
            "against %d, from a %s identity. %s",
            len(username),
            USERNAME_MAX,
            source.value,
            clipped(username),
        )
        return None

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
            "Making %s an admin: it is the first account in this library",
            clipped(username),
        )
        is_admin = True

    if user is not None and user.is_admin and not is_admin and not _admin_group_set(source):
        logger.warning(
            "Keeping admin rights for %s: no admin group is configured for %s, "
            "so there is nothing to demote them on",
            clipped(username),
            source.value,
        )
        is_admin = True

    # Asked once, before both branches. Where the directory does not own the
    # address, `asserted` stays None and nothing below reads it, which is what
    # keeps a locally typed address from being cleared by a sign in.
    owns_email = directory_owns_email(source.value)
    asserted = _directory_email(email) if owns_email else None

    if user is None:
        user = User(
            username=username,
            password_hash=None,
            is_admin=is_admin,
            auth_source=source.value,
            email=asserted,
        )
        # A directory authenticated this identity, so this app never held the
        # credential and has nothing of its own to verify. Stamped rather than
        # left null, because null is what the account policy refuses a sign in
        # for, and `app_holds_the_password` and this line have to agree about a
        # row that is neither of the two directories.
        record_verification(user, VerificationProvenance.DIRECTORY)
        db.add(user)
        # WARNING, not INFO. Creating an account is the most consequential
        # thing this app does without anybody clicking anything, and under
        # proxy auth it happens on an ordinary GET. The one record of the
        # 2026-08-18 incident was an INFO line in a stream nobody reads.
        logger.warning(
            "Created account %s from a %s identity, admin=%s",
            clipped(username),
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
    #
    # The address is compared only where the directory owns it. Dropping
    # `owns_email` from this clause would make an unconfigured directory assert
    # None and clear every stored address on the next sign in, which is the
    # exact shape of the silent demotion the paragraph above exists to prevent.
    changed = (
        user.is_admin != is_admin
        or user.auth_source != source.value
        or (owns_email and user.email != asserted)
    )
    if changed:
        if user.is_admin != is_admin:
            logger.warning(
                "Admin rights for %s changed to %s by a %s identity",
                clipped(username),
                is_admin,
                source.value,
            )
        if owns_email and user.email != asserted:
            # The fact, never the address: this goes to a log an operator
            # reads, and an address is the one part of an envelope worth
            # keeping out of one. `mailer._deliver` logs a refused recipient
            # count for the same reason.
            logger.info(
                "The %s directory %s the address for %s",
                source.value,
                "cleared" if asserted is None else "set",
                clipped(username),
            )
            user.email = asserted
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

    # **Every log line below that names the value typed at the login screen
    # passes it through `clipped`, and removing one lets an unauthenticated
    # caller write a log line of their own.** `username` is the one value in
    # this function that arrives straight off the wire: `LoginRequest` bounds
    # its length and deliberately carries no pattern, so a newline in it
    # reaches here.
    #
    # **The quantifier is narrow on purpose.** Two log lines below name no
    # username at all, or name one that did not come off the wire: the service
    # bind failure logs the directory's result, and the refused address line
    # logs `resolved_username`, which the directory supplied. That second one
    # is clipped now too, as is every site in `upsert_directory_user`, which
    # both directory doors funnel through and which refuses a name the column
    # cannot hold rather than storing or truncating it.
    #
    # **The service bind failure is bare, and what makes it safe is
    # `dict.__repr__`, not the site.** `Connection.result` is a dict, so `%s`
    # reprs each member and a directory `message` carrying a newline comes out
    # escaped. Clipping it instead would cut a realistic Active Directory bind
    # failure from 206 characters to 203 and take the operator's only
    # diagnostic with it. **So logging a member of that dict directly, the
    # obvious readability improvement, loses the escaping and needs `clipped`.**
    #
    # **What still goes past, stated rather than left to be found**: the
    # refused address line in `user_from_proxy_headers` names a value
    # `_PROXY_USERNAME` has already bounded, and the refusal line above it
    # names one the regex has just refused, which is why it clips. Each says
    # at its own site why it is spelled the way it is. Nothing here bounds a
    # username once it is stored: `schemas/user.py`'s `UserOut.username` is a
    # bare `str`, so the member list serialises a row of any width in full,
    # and `auth._encode` writes the same value into the token's `username`
    # claim. Both are named by path because a reader of this note has to be
    # able to reach them.
    #
    # `clipped` is `repr` then a slice, and **what does the work at these two
    # sites is the repr**, which escapes the newline that would otherwise forge
    # a second entry. The slice is dead here, the schema having already bounded
    # the value.
    # `tests/routers/test_auth.py::TestAnUntrustedUsernameCannotForgeALogLine`
    # fails if a log line from an auth route starts carrying a control
    # character.

    try:
        with _connect(ldap_bind_dn(), ldap_bind_password()) as search_connection:
            if not search_connection.bind():
                logger.error("LDAP service bind failed: %s", search_connection.result)
                return None

            # The address attribute is appended only when one is configured,
            # so the shipped default asks the directory for exactly what it
            # always asked for. An unconditional `"mail"` here would change the
            # search every deployment makes on an upgrade nobody opted into.
            attributes = [ldap_username_attribute(), "memberOf"]
            email_attribute = ldap_email_attribute()
            if email_attribute:
                attributes.append(email_attribute)

            search_connection.search(
                search_base=ldap_user_base_dn(),
                search_filter=search_filter,
                attributes=attributes,
            )
            if not search_connection.entries:
                # No such member. Deliberately indistinguishable from a wrong
                # password to whoever is asking.
                return None
            if len(search_connection.entries) > 1:
                logger.error(
                    "LDAP filter matched %d entries for %s",
                    len(search_connection.entries),
                    clipped(username),
                )
                return None

            entry = search_connection.entries[0]
            user_dn = entry.entry_dn
            groups = [str(group) for group in (entry.memberOf.values if "memberOf" in entry else [])]
            # Trust the directory's spelling of the name, not the one typed, so
            # "Kim" and "kim" cannot become two accounts.
            resolved_username = str(entry[ldap_username_attribute()].value)
            # Read inside the `with`, like everything else off the entry: the
            # connection is closed below and an ldap3 entry is not usable after
            # it. `.value` is None for a present but empty attribute and a
            # multi-valued one yields the first, both of which
            # `_directory_email` reduces to "the directory named no address".
            resolved_email = (
                str(entry[email_attribute].value)
                if email_attribute and email_attribute in entry and entry[email_attribute].value
                else None
            )

        with _connect(user_dn, password) as user_connection:
            if not user_connection.bind():
                return None

    except LDAPException as failure:
        # Directory unreachable or misconfigured, reported to the caller as an
        # ordinary failed login.
        #
        # **`error` rather than `exception`, and the traceback is the price.**
        # Traded 2026-09-28, deliberately. `logger.exception` emits `exc_info`
        # as well as the interpolated argument, and ldap3 puts the assertion
        # value verbatim into the message of the `LDAPInvalidValueError` it
        # raises when the attribute the filter names has a strict schema
        # validator. `uid`, the shipped default, has none; `uidNumber` on an
        # RFC 2307 schema does, which is what a numeric login site configures.
        # `escape_filter_chars` leaves CR and LF alone, so the traceback wrote
        # the caller's forged line as a line of its own, past the `clipped` on
        # the argument beside it.
        #
        # **What is given up is the site, and that is more than "some ldap3
        # frames".** The `try` opens at the service bind, so a traceback from
        # it always began with this function and often `_connect` as well.
        # Three places raise into this handler, the service bind, the search
        # and the user re bind, and the one message below is now identical for
        # all three: a socket error at the first and the same class at the
        # third were told apart by line number and no longer are.
        #
        # `repr` keeps the exception **class**, so the kind survives and the
        # place does not. That is the trade, taken deliberately, because a
        # forged log line is worse than a coarser one. The alternative that
        # keeps both is validating the value before the search, which is a
        # larger change than this one.
        # `tests/routers/test_auth.py` asserts the class is still named; it
        # asserts nothing about the site, because the site is gone.
        logger.error(
            "LDAP authentication failed for %s: %s", clipped(username), clipped(failure)
        )
        return None

    if _address_was_refused(resolved_email):
        # The same event as the proxy branch and it is logged at the same level.
        # There is no peer: the value came from the directory this deployment
        # configured, so the attribute is what identifies it.
        logger.warning(
            "Refused the %r attribute for %s: %d characters, not an address. "
            "The stored address is cleared.",
            email_attribute,
            clipped(resolved_username),
            len(resolved_email or ""),
        )

    return upsert_directory_user(
        db,
        resolved_username,
        is_admin=_is_member_of_admin_group(entry, groups),
        source=AuthMode.LDAP,
        email=resolved_email,
    )


# ── Proxy ─────────────────────────────────────────────────────────────────────


#: What a username coming from a header may look like.
#:
#: Deliberately narrow: letters, digits and the three separators a directory
#: actually uses. It is not an attempt to authenticate the header, which is
#: impossible from here. It bounds the damage of a header that is wrong, which
#: is a different and achievable goal.
#:
#: **The repeat is `USERNAME_MAX` minus the leading character**, derived rather
#: than written, because the whole point of the length arm is that a header
#: cannot write a row `users.username` will not hold: a literal here would go on
#: refusing at the old width after the column moved, in either direction.
_PROXY_USERNAME = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._@-]{{0,{USERNAME_MAX - 1}}}$")


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

    * The name has to look like a username. `String(USERNAME_MAX)` is not
      enforced by SQLite, so an unvalidated header wrote whatever length it
      liked; a 4000-character `Remote-User` produced a 4000-character account.
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
        # **Both bounds, composed, and neither alone is enough.** The slice
        # bounds the input; `clipped` reprs and bounds that repr at
        # `LOGGED_VALUE_MAX`. An escape costs up to four characters per
        # character, so a slice of 80 reprs to 322, and `clipped` on its own
        # sees the whole header and spends its whole 203 even on an ordinary
        # one. Measured over a 4000 character header, emitted characters:
        #
        #     input       slice under %r   clipped alone   composed
        #     ordinary                82             203         82
        #     newlines               162             203        162
        #     NULs                   322             203        203
        #
        # Composed is tightest or equal on all three. **Where it is not
        # tightest it costs two characters, at a repr of 201, and one at
        # 202**: those are the widths where the repr passes `LOGGED_VALUE_MAX`
        # by less than the three characters the ellipsis adds, so the clip
        # spends 203 where the slice alone would have spent 201 or 202. Both
        # are reachable from an eighty character slice, 201 from twenty NULs,
        # fifty nine newlines and one ordinary character, 202 from forty NULs
        # and forty ordinary ones. **Escape widths are mixed**: over all of
        # Unicode a character reprs to one, two, four, six or ten characters,
        # so the repr does not step uniformly, and reading 201 as unreachable
        # because a four-character escape steps the length by three holds only
        # while one width is used throughout.
        #
        # **This is the one username log line an unauthenticated caller
        # reaches, and it fires only where the regex has just refused the
        # value**, so the hostile rows are the ones it sees and the ordinary
        # row is the one it never does: an argument for dropping either bound
        # that rests on the ordinary row rests on the wrong row.
        #
        # What composing gives up: past 203 characters of repr the operator
        # sees a truncated refused header rather than all 80 escaped
        # characters. It is a header the regex already refused, and 203 is
        # enough to recognise what arrived.
        #
        # `%s`, because `clipped` has already repr'd. A site left at `%r`
        # escapes twice, and
        # `tests/test_auth_backends.py::TestTheDirectorySuccessPathCannotForgeALogLine`
        # collects every argument this module reprs and refuses any but the
        # two it records as deliberately bare, whatever spelling carries the
        # argument.
        logger.warning(
            "Refused a proxy identity that does not look like a username: %s (%d chars) from %s",
            clipped(username[:80]),
            len(username),
            _peer(request),
        )
        return None

    raw_groups = (request.headers.get(proxy_groups_header()) or "").strip()
    groups = [group.strip() for group in raw_groups.split(",") if group.strip()]

    wanted = proxy_admin_group()
    is_admin = bool(wanted) and any(group.lower() == wanted.lower() for group in groups)

    # Read only when a header is configured, for the reason in
    # `config.proxy_email_header`: an upstream that sends nothing must not be
    # read as asserting that a member has no address.
    email_header = proxy_email_header()
    email = request.headers.get(email_header) if email_header else None

    if _address_was_refused(email):
        # WARNING and the peer, for the reason the refused username above gets
        # them: this is the header injection shape, on the same request, from
        # the same unauthenticated source. It also **clears** any stored
        # address, so an operator reading INFO would see the same line here as
        # for an upstream that simply sends nobody an address.
        #
        # The length and never the value. An address is a member's, and
        # `mailer._deliver` logs a count of refused recipients rather than a
        # list for the same reason; what an operator needs from this line is
        # that the upstream sent something unusable, and from where.
        # `username` is bare rather than clipped: `_PROXY_USERNAME` matched it
        # above, so it is at most `USERNAME_MAX` characters of
        # `[A-Za-z0-9._@-]` and clipping would change nothing it can carry.
        logger.warning(
            "Refused the %s header for %r: %d characters, not an address, from %s. "
            "The stored address is cleared.",
            email_header,
            username,
            len(email or ""),
            _peer(request),
        )

    return upsert_directory_user(
        db, username, is_admin=is_admin, source=AuthMode.PROXY, email=email
    )


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
