from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config import auth_mode, secret_key
from database import get_db
from enums import AuthMode
from models import User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

# bcrypt hashes at most the first 72 bytes of a password and ignores the rest.
# The C implementation truncates silently; the Python binding raises instead, so
# truncation is done here to keep the behaviour of previously stored hashes.
BCRYPT_MAX_BYTES = 72

# auto_error=False so a missing token is not an automatic 401: in proxy mode
# there is no token at all, and the caller is identified by a header instead.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database: treat as a failed login, not a 500.
        return False


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, secret_key(), algorithm=ALGORITHM)


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if auth_mode() is AuthMode.PROXY:
        # Imported here rather than at module scope: auth_backends imports this
        # module for verify_password, so a top-level import would be circular.
        from auth_backends import user_from_proxy_headers

        proxied = user_from_proxy_headers(db, request)
        if proxied is None:
            raise credentials_exception
        return proxied

    if token is None:
        raise credentials_exception

    try:
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        # `from None` deliberately: the JWT failure detail must not reach the
        # client, and a chained traceback would be noise in the logs.
        raise credentials_exception from None

    user = db.get(User, int(user_id))
    if user is None:
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
