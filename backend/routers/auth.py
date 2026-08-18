from fastapi import APIRouter, HTTPException, Request, status

from auth import create_access_token, hash_password
from auth_backends import authenticate, local_signup_allowed
from config import auth_mode, registration_enabled
from dependencies import CurrentUser, DbSession
from models import User
from ratelimit import client_address, login_key, login_limiter, register_limiter
from schemas import AuthConfigOut, LoginRequest, Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    """Public: the login page reads this before anyone holds a token.

    Read per request rather than captured at import, so closing registration
    takes effect without restarting the container.
    """
    return AuthConfigOut(
        # The frontend uses this to decide what to render: `proxy` means show
        # no auth screen at all, `ldap` means a login form with no signup tab.
        auth_mode=auth_mode(),
        registration_enabled=local_signup_allowed() and registration_enabled(),
    )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request, db: DbSession) -> Token:
    register_limiter.check(client_address(request))

    if not local_signup_allowed():
        raise HTTPException(
            status_code=403,
            detail="Accounts are managed by the directory, not here.",
        )
    if not registration_enabled():
        raise HTTPException(status_code=403, detail="Registration is disabled")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Whoever registers first becomes the admin. There is no other way to
    # become one, and no endpoint grants the flag afterwards.
    is_first = db.query(User).count() == 0
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=is_first,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return Token(
        access_token=create_access_token(user.id, user.username),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, db: DbSession) -> Token:
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
    login_limiter.reset(key)
    return Token(
        access_token=create_access_token(user.id, user.username),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> User:
    return current_user
