"""Local accounts: passwords, sign-in sessions and the role checks.

Roles:
  admin       the admin console and the imaging environment
  technician  the imaging environment only (start captures and deploys at a machine)

The admin console signs in with a cookie. The imaging environment signs in
through the agent, which gets a bearer token for actions it asks the server for.

Password hashes use scrypt, written as scrypt:N:r:p:salt:hash (base64url). The
format has no "$" or spaces so it can go on a kernel command line, which is
how the boot USB carries its offline account.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, UserSession, utcnow

ROLES = ("admin", "technician")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
MIN_PASSWORD = 8
SESSION_HOURS = 12
COOKIE = "mckpxe_session"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}:{_b64(salt)}:{_b64(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, h = stored.split(":")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(_unb64(h)))
        return hmac.compare_digest(got, _unb64(h))
    except (ValueError, TypeError):
        return False


# Checked against when the username doesn't exist, so a wrong username takes as
# long as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Usernames are 1-32 lowercase letters, numbers, dots, dashes or underscores")
    return username


def check_new_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise HTTPException(400, f"Passwords need at least {MIN_PASSWORD} characters")
    return password


# --------------------------------------------------------------------------- sign-in throttling

FAIL_WINDOW = 15 * 60
MAX_FAILS = 10
_fails: dict[str, list[float]] = {}


def _recent(key: str) -> list[float]:
    now = time.monotonic()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
    return _fails[key]


def authenticate(db: Session, username: str, password: str, client: str) -> User:
    """The enabled user with this username and password, or an HTTP error."""
    username = (username or "").strip().lower()
    keys = (f"ip:{client}", f"user:{username}")
    if any(len(_recent(k)) >= MAX_FAILS for k in keys):
        raise HTTPException(429, "Too many failed sign-ins. Wait 15 minutes and try again.")
    user = db.scalars(select(User).where(User.username == username)).first()
    ok = verify_password(password or "", user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.enabled:
        for k in keys:
            _recent(k).append(time.monotonic())
        raise HTTPException(401, "Wrong username or password")
    for k in keys:
        _fails.pop(k, None)
    user.last_login = utcnow()
    return user


# --------------------------------------------------------------------------- sessions

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(db: Session, user: User, kind: str) -> str:
    """Start a session; returns the token (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    db.execute(delete(UserSession).where(UserSession.expires_at < utcnow()))
    db.add(UserSession(token_hash=_token_hash(token), user_id=user.id, kind=kind,
                       expires_at=utcnow() + timedelta(hours=SESSION_HOURS)))
    db.commit()
    return token


def end_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
    db.commit()


def end_user_sessions(db: Session, user_id: int, keep: str | None = None) -> None:
    """Sign a user out everywhere (after a password change or disabling them)."""
    q = delete(UserSession).where(UserSession.user_id == user_id)
    if keep:
        q = q.where(UserSession.token_hash != _token_hash(keep))
    db.execute(q)
    db.commit()


def session_user(db: Session, token: str | None, kind: str) -> User | None:
    if not token:
        return None
    s = db.scalars(select(UserSession).where(UserSession.token_hash == _token_hash(token),
                                            UserSession.kind == kind)).first()
    if not s:
        return None
    expires = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires < utcnow() or not s.user.enabled:
        return None
    return s.user


@dataclass
class Me:
    id: int
    username: str
    name: str
    role: str
    token: str


def current_user(request: Request, db: Session = Depends(get_db)) -> Me:
    """Any signed-in admin console user."""
    token = request.cookies.get(COOKIE)
    user = session_user(db, token, "web")
    if not user:
        raise HTTPException(401, "Not signed in")
    if user.role != "admin":
        raise HTTPException(403, "This account can only sign in on the imaging environment")
    return Me(user.id, user.username, user.name or user.username, user.role, token)


def console_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The person signed in at a machine's imaging environment (bearer token)."""
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else None
    user = session_user(db, token, "console")
    if not user:
        raise HTTPException(401, "Sign in at this machine with a server account to do this")
    return user
