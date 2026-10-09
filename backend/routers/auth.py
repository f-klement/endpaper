import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

import accounts
import mailer
import settings_store
from auth import (
    clear_cover_cookie,
    create_access_token,
    create_cover_token,
    hash_password,
    require_admin,
    set_cover_cookie,
    verify_password,
)
from auth_backends import authenticate, local_signup_allowed
from config import auth_mode, registration_enabled
from dependencies import CurrentUser, DbSession
from enums import AuthMode, VerificationProvenance
from models import User, is_switch_target
from ratelimit import (
    account_key,
    client_address,
    login_key,
    login_limiter,
    recovery_code_limiter,
    recovery_request_account_limiter,
    recovery_request_address_limiter,
    register_limiter,
)
from schemas import (
    AuthConfigOut,
    LoginRequest,
    RegistrationOut,
    ResetRedeem,
    ResetRequest,
    Token,
    UserCreate,
    UserOut,
    VerificationRedeem,
    VerificationRequest,
)

logger = logging.getLogger("endpaper.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigOut)
def auth_config(db: DbSession) -> AuthConfigOut:
    """Public: the login page reads this before anyone holds a token.

    Read per request rather than captured at import, so closing registration
    takes effect without restarting the container.
    """
    return AuthConfigOut(
        # The frontend uses this to decide what to render: `proxy` means show
        # no auth screen at all, `ldap` means a login form with no signup tab.
        auth_mode=auth_mode(),
        registration_enabled=local_signup_allowed() and registration_enabled(),
        # Whether recovery and confirmation are offered at all. Both are drawn
        # from the server's answer rather than derived in the browser from
        # `auth_mode`, which is the rule `public_catalogue_published` already
        # sets: a client that recomputes a conjunction is a second place for it
        # to be wrong.
        password_reset_enabled=accounts.reset_refusal() is None,
        verification_required=settings_store.accounts_are_open_to_outsiders(db),
    )


@router.post(
    "/register", response_model=RegistrationOut, status_code=status.HTTP_201_CREATED
)
def register(
    payload: UserCreate,
    request: Request,
    response: Response,
    db: DbSession,
    background: BackgroundTasks,
) -> RegistrationOut:
    # Both refusals come BEFORE the limiter, deliberately. Under ldap or proxy
    # auth, and with signups closed, this route cannot create an account at
    # all, so charging the caller for the attempt spends a real budget on a
    # certain 403. That budget is keyed on the source address, which behind a
    # reverse proxy is one key for everybody. The limiter now guards only the
    # path that can actually mint an account.
    if not local_signup_allowed():
        raise HTTPException(status_code=403, detail=_signup_refusal())
    if not registration_enabled():
        raise HTTPException(status_code=403, detail="Registration is disabled")

    register_limiter.check(client_address(request))

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Whoever registers first becomes the admin. There is no other way to
    # become one, and no endpoint grants the flag afterwards.
    is_first = db.query(User).count() == 0
    # **The policy is read once, here, and stamped onto the row.** An account is
    # made under the policy in force when it is made: turning the switch on later
    # gates the accounts created after it and never strands a member already in
    # the library, and turning it off never quietly admits somebody who
    # registered while it was on and never confirmed. See `docs/decisions.md`.
    #
    # **Never the first account**, which is the one nobody could confirm: it is
    # the admin, so there is no admin to override it and no mailbox configured
    # yet to send it anything. A deployment that switched the policy on before
    # anybody registered would otherwise be a library with no way in at all.
    must_confirm = settings_store.accounts_are_open_to_outsiders(db) and not is_first
    if must_confirm and payload.email is None:
        # Before the account is made rather than after: an account with nothing
        # to send a code to, on a deployment that requires one, is one only an
        # admin can ever let in.
        raise HTTPException(
            status_code=400,
            detail="An address is required: this library confirms new accounts.",
        )

    # **The address is set here rather than only on the settings screen**, which
    # is the one moment somebody is already typing their details. `UserCreate`
    # normalises it, so "" from a form nobody filled in arrives as None and the
    # account is created exactly as it was before the field existed.
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=is_first,
        email=payload.email,
    )
    if not must_confirm:
        accounts.record_verification(user, VerificationProvenance.NOT_REQUIRED)
    db.add(user)
    db.commit()
    db.refresh(user)

    if must_confirm:
        code = accounts.start_verification(db, user)
        _post_the_code(background, accounts.verification_mail(db, user, code))
        # **No token, and no cover cookie either.** An account that may do
        # nothing gets nothing that could act as it, and a cookie is a second
        # copy of a session living outside localStorage.
        return RegistrationOut(verification_required=True)

    token = create_access_token(db, user.id, user.username)
    set_cover_cookie(
        response, create_cover_token(db, user.id, user.username), secure=_is_https(request)
    )
    return RegistrationOut(
        verification_required=False,
        token=Token(access_token=token, user=UserOut.model_validate(user)),
    )


def _post_the_code(
    background: BackgroundTasks,
    parts: tuple[mailer.MailConfig, str, str] | None,
) -> None:
    """Hand a confirmation mail to the background, if there is one to send.

    **After the response, never inside it.** `mailer.send` is blocking and talks
    to somebody else's server, so sending it inline would make registering wait
    on a mail host that may be slow, unreachable, or dribbling one byte at a
    time. The member's account already exists by then; a send that fails is
    logged and answered by asking for the code again.

    None means there was nothing to send: no address on the account, or no mail
    server configured. Both are ordinary on an install whose recovery path is
    the admin override, and neither is an error.
    """
    if parts is None:
        return
    config, subject, body = parts
    background.add_task(_send_quietly, config, subject, body)


def _send_quietly(config: mailer.MailConfig, subject: str, body: str) -> None:
    """Send, and let a failure be a log line rather than an unhandled task."""
    try:
        mailer.send(config, subject, body)
    except Exception:
        # Broad, because this runs after the response has gone: anything raised
        # here reaches nobody, and smtplib raises several unrelated families.
        logger.exception("Could not send a confirmation code")


def _signup_refusal() -> str:
    """Why this deployment will not create an account, in words that are true.

    One sentence used to answer for both directory modes, and in proxy mode it
    named something that need not exist: the upstream may be an SSO portal, an
    OIDC provider or a header set by the reverse proxy itself, with no
    directory anywhere. Telling somebody to ask a directory administrator who
    does not exist is worse than saying nothing.
    """
    if auth_mode() is AuthMode.PROXY:
        return "Accounts are managed by whoever signs you in, not here."
    return "Accounts are managed by the directory, not here."


@router.post("/login", response_model=Token)
def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> Token:
    key = login_key(payload.username, request)
    login_limiter.check(key)

    # Dispatches to the configured backend. In proxy mode this always returns
    # None: there is nothing to check here because the proxy already did it.
    user = authenticate(db, payload.username, payload.password)
    if user is None:
        # One message for both cases, deliberately: distinguishing "no such
        # user" from "wrong password" lets an attacker enumerate accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Getting it right clears the count, so a member who mistyped a few times
    # is not left rationed for the rest of the window.
    # **After the password check and never before it.** The refusal names the
    # reason, which is a sentence somebody who has just registered needs, and
    # saying it to a caller who had not proved the password would be an account
    # enumeration oracle. `accounts.verification_blocks` is the same rule
    # `_user_from_token` asks, so a token cannot outlive the refusal.
    refusal = accounts.sign_in_refusal(db, user)
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)

    login_limiter.reset(key)
    token = create_access_token(db, user.id, user.username)
    # Also as a cookie, scoped to /covers alone, because an <img> tag cannot
    # send the Authorization header this token normally travels in. See
    # auth.COVER_COOKIE_NAME for why that is safe on that route and nowhere
    # else.
    set_cover_cookie(
        response, create_cover_token(db, user.id, user.username), secure=_is_https(request)
    )
    return Token(
        access_token=token,
        user=UserOut.model_validate(user),
    )


# ── Getting back in, and proving an address ───────────────────────────────────
#
# The four routes here are the only ones in the application reachable with no
# session at all besides the public catalogue, and every rule they share follows
# from that rather than from taste:
#
#   * each answers the same whatever it found, so none is a roster;
#   * each is charged to two counters, one for the address and one for the named
#     account, because either alone leaves the other attack standing;
#   * neither redemption returns a token. A code is spent on setting a password
#     or on settling a state, and the member then signs in, which is also the
#     check that what they set works.


def _charge_a_request(username: str, request: Request) -> None:
    """Spend the recovery budget, on both keys, before anything is looked up.

    Before the lookup, so the answer cannot be timed, and both keys because the
    owner named both cases: a per address limit alone lets a botnet queue a
    hundred requests against one member, and a per account limit alone lets one
    address work through the roster slowly.
    """
    recovery_request_address_limiter.check(client_address(request))
    recovery_request_account_limiter.check(account_key(username))


@router.post("/reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: ResetRequest, request: Request, db: DbSession
) -> Response:
    """Ask an admin to approve a password reset for this account.

    **Unauthenticated, because there is no other moment.** A member who could
    sign in would not need this. Everything else about the route follows: it
    answers 202 whether or not the account exists, making a request grants
    nothing, and at most one request per account is ever live.

    **This is the only place in the application that creates a reset request**,
    which is what separates a recovery flow from a back door: an admin may
    approve one and cannot start one. The residual is recorded rather than
    hidden, since the route takes a username anybody may type. See
    `accounts.request_password_reset` and `docs/decisions.md`.

    Refused outright where the deployment does not hold the password, with a
    message naming the system that does. That refusal discloses nothing:
    `GET /auth/config` already publishes the auth mode to the login page.
    """
    refusal = accounts.reset_refusal()
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)
    _charge_a_request(payload.username, request)
    accounts.request_password_reset(db, payload.username)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/reset/redeem", status_code=status.HTTP_204_NO_CONTENT)
def redeem_password_reset(
    payload: ResetRedeem, request: Request, db: DbSession
) -> Response:
    """Spend an approved code on a new password.

    204 and no token. The code is not a session and never becomes one: the
    member signs in with what they just set, which is also the check that it
    works.

    One message for every failure, exactly as `/auth/login` answers one for a
    missing account and a wrong password, and for the sharper version of the
    same reason: this caller holds no session at all.
    """
    refusal = accounts.reset_refusal()
    if refusal is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)
    key = login_key(payload.username, request)
    recovery_code_limiter.check(key)
    if not accounts.redeem_reset(
        db, payload.username, payload.code, payload.new_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code is not usable. Ask an admin to approve a reset.",
        )
    recovery_code_limiter.reset(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/verify/request", status_code=status.HTTP_202_ACCEPTED)
def request_verification(
    payload: VerificationRequest,
    request: Request,
    db: DbSession,
    background: BackgroundTasks,
) -> Response:
    """Send this account's confirmation code again.

    202 whatever happened, including for an account that is already confirmed,
    that does not exist, or that has no address. A route saying which would tell
    a stranger which names are taken and which of them have a mailbox.

    **And it costs the same either way**, which the body alone does not buy.
    Minting a code is a bcrypt and finding no account is one indexed SELECT, so
    without the discarded comparison the two branches differ by a hash and the
    roster is readable off a clock. `accounts.spend_a_comparison` carries the
    measurement, once; `tests/test_accounts.py::TestNeitherBranchOfAResendIsFree`
    compares the two counts rather than checking each is non zero, which is the
    weaker property the first version of that guard settled for.
    """
    _charge_a_request(payload.username, request)
    user = db.query(User).filter(User.username == payload.username).first()
    if user is not None and accounts.verification_blocks(db, user):
        code = accounts.start_verification(db, user)
        _post_the_code(background, accounts.verification_mail(db, user, code))
    else:
        accounts.spend_a_comparison(payload.username)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/verify", status_code=status.HTTP_204_NO_CONTENT)
def confirm_address(
    payload: VerificationRedeem, request: Request, db: DbSession
) -> Response:
    """Settle an account by returning the code sent to its address.

    204 and no token, for the reason the reset redemption returns none: a code
    proves an address rather than authenticating a person, so the member signs in
    afterwards with the password they already chose.
    """
    key = login_key(payload.username, request)
    recovery_code_limiter.check(key)
    if not accounts.redeem_verification(db, payload.username, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code is not usable. Ask for a new one.",
        )
    recovery_code_limiter.reset(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/switch", response_model=Token)
def switch_account(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> Token:
    """Exchange a password an admin supplies for a session on a test account.

    A login performed on another account's behalf, not impersonation, and the
    difference is the password: it is required and checked the ordinary way.
    The admin knows it because the admin set it. Drop that check and this
    becomes a button that reads anybody's library.

    `LoginRequest`, not a schema of its own, because this **is** a login and
    the same two reasons apply: the registration length floor must not lock out
    a password set before it, and a 422 saying "too short" is a different
    answer from a 401 saying "wrong".

    The two refusals differ here, unlike at `/auth/login`, and can. That route
    answers one message for both cases so nobody can enumerate accounts; this
    one is called by an admin who may already list every account. So a name
    that is not a test account is a **404**, which is true of it as far as this
    route is concerned, and a wrong password is a **401**.

    Rate limited on the same counter as `/auth/login`, keyed the same way. The
    caller holds an admin token, so this is not the first line of defence; it
    is that a password check reachable over HTTP is a password check worth
    bounding, and this one hands back a session on a different account.
    """
    key = login_key(payload.username, request)
    login_limiter.check(key)

    target = db.query(User).filter(User.username == payload.username).first()
    # `is_switch_target` is the rule, in one place, and it is what keeps a
    # directory-backed member out: an admin able to mint a session for one
    # could read that member's private books.
    if not is_switch_target(target):
        raise HTTPException(status_code=404, detail="No such test account")

    # `or ""` is for the type checker alone: being a switch target already
    # means having a hash. An empty one fails the check rather than raising.
    if not verify_password(payload.password, target.password_hash or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password for that account",
        )

    login_limiter.reset(key)
    # WARNING, and it names both accounts. This is the one action in the app
    # that puts one member's session in another member's hands, and
    # `auth_backends` already sets the precedent: the consequential things are
    # logged loudly, because the record of the last incident was an INFO line
    # nobody was reading.
    logger.warning(
        "Admin %r switched into the test account %r",
        current_user.username,
        target.username,
    )

    token = create_access_token(db, target.id, target.username)
    # Exactly like /auth/login, cover cookie included: an <img> cannot send the
    # Authorization header, so without it the switched session has no covers.
    set_cover_cookie(
        response,
        create_cover_token(db, target.id, target.username),
        secure=_is_https(request),
    )
    return Token(access_token=token, user=UserOut.model_validate(target))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    """Drop the cover cookie.

    The access token lives in the browser and signing out discards it there,
    but the cookie is ours and would otherwise sit in the browser until it
    expired: on a shared machine, the next person's first page load would still
    fetch covers as the person who left.

    No authentication required, and none wanted. This only deletes something
    the caller already holds, and demanding a valid token would mean an expired
    session could never clear its own cookie.
    """
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_cover_cookie(response)
    return response


def _is_https(request: Request) -> bool:
    """Whether the browser's connection was secure, not ours to the proxy.

    A Secure cookie is silently dropped over plain HTTP, so a LAN deployment
    without a certificate would lose its covers with nothing to explain why.
    The forwarded header is what carries the browser's side of it.
    """
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "") == "https"
    )


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> User:
    return current_user
