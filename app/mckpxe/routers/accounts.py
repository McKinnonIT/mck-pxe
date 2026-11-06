"""Signing in to the admin console, managing accounts, and the boot USB's offline account."""
import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import (
    COOKIE,
    ROLES,
    SESSION_HOURS,
    Me,
    authenticate,
    check_new_password,
    check_username,
    current_user,
    end_session,
    end_user_sessions,
    hash_password,
    new_session,
    verify_password,
)
from ..config import settings
from ..db import get_db
from ..models import User, UserSession

router = APIRouter(prefix="/api", tags=["accounts"])


def client_ip(request: Request) -> str:
    # nginx sets X-Forwarded-For to the connecting address (it doesn't append)
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role, "enabled": u.enabled,
            "created_at": u.created_at, "last_login": u.last_login}


def me_out(me: Me) -> dict:
    return {"id": me.id, "username": me.username, "name": me.name, "role": me.role}


# --------------------------------------------------------------------------- sign in

@router.post("/auth/login")
def login(request: Request, response: Response, data: dict = Body(...), db: Session = Depends(get_db)):
    user = authenticate(db, data.get("username", ""), data.get("password", ""), client_ip(request))
    if user.role != "admin":
        db.commit()
        raise HTTPException(403, "This account can only sign in on the imaging environment")
    token = new_session(db, user, "web")
    https = request.headers.get("X-Forwarded-Proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True, samesite="strict",
                        secure=https, path="/")
    return {"id": user.id, "username": user.username, "name": user.name or user.username, "role": user.role}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    if token := request.cookies.get(COOKIE):
        end_session(db, token)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: Me = Depends(current_user)):
    return me_out(user)


@router.post("/me/password")
def change_my_password(data: dict = Body(...), db: Session = Depends(get_db), me: Me = Depends(current_user)):
    user = db.get(User, me.id)
    if not verify_password(data.get("current", ""), user.password_hash):
        raise HTTPException(400, "Your current password is wrong")
    user.password_hash = hash_password(check_new_password(data.get("new", "")))
    db.commit()
    end_user_sessions(db, user.id, keep=me.token)
    initial_password_file().unlink(missing_ok=True)
    return {"ok": True}


# --------------------------------------------------------------------------- accounts (admins only)

admin = APIRouter(prefix="/api", tags=["accounts"], dependencies=[Depends(current_user)])


def enabled_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.enabled))


@admin.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@admin.post("/users")
def create_user(data: dict = Body(...), db: Session = Depends(get_db)):
    username = check_username(data.get("username", ""))
    if db.scalars(select(User).where(User.username == username)).first():
        raise HTTPException(409, f"There's already an account called {username}")
    role = data.get("role", "technician")
    if role not in ROLES:
        raise HTTPException(400, "role must be admin or technician")
    user = User(username=username, name=str(data.get("name") or "").strip(), role=role,
                password_hash=hash_password(check_new_password(data.get("password", ""))))
    db.add(user)
    db.commit()
    return user_out(user)


@admin.patch("/users/{user_id}")
def update_user(user_id: int, data: dict = Body(...), db: Session = Depends(get_db), me: Me = Depends(current_user)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "No such account")
    if "name" in data:
        user.name = str(data["name"] or "").strip()
    if "role" in data:
        if data["role"] not in ROLES:
            raise HTTPException(400, "role must be admin or technician")
        if user.id == me.id and data["role"] != "admin":
            raise HTTPException(400, "You can't remove your own admin role")
        user.role = data["role"]
    if "enabled" in data:
        if user.id == me.id and not data["enabled"]:
            raise HTTPException(400, "You can't disable your own account")
        user.enabled = bool(data["enabled"])
    signed_out = False
    if data.get("password"):
        user.password_hash = hash_password(check_new_password(data["password"]))
        signed_out = True
    if not enabled_admins(db):
        db.rollback()
        raise HTTPException(400, "There must be at least one enabled admin")
    db.commit()
    if signed_out or not user.enabled:
        end_user_sessions(db, user.id, keep=me.token if user.id == me.id else None)
    return user_out(user)


@admin.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), me: Me = Depends(current_user)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "No such account")
    if user.id == me.id:
        raise HTTPException(400, "You can't delete your own account")
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.delete(user)
    if not enabled_admins(db):
        db.rollback()
        raise HTTPException(400, "There must be at least one enabled admin")
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- boot USB offline account

def usb_account_path():
    return settings.system_dir / "usb-account.json"


def usb_account() -> dict | None:
    """The account built into the boot USB, for signing in when the server can't be reached."""
    try:
        return json.loads(usb_account_path().read_text())
    except (OSError, ValueError):
        return None


@admin.get("/settings/usb-account")
def get_usb_account():
    a = usb_account()
    return {"username": a["username"], "updated_at": a.get("updated_at")} if a else None


@admin.put("/settings/usb-account")
def set_usb_account(data: dict = Body(...)):
    from ..models import utcnow

    account = {"username": check_username(data.get("username", "")),
               "password_hash": hash_password(check_new_password(data.get("password", ""))),
               "updated_at": utcnow().isoformat()}
    settings.system_dir.mkdir(parents=True, exist_ok=True)
    usb_account_path().write_text(json.dumps(account))
    usb_account_path().chmod(0o600)
    return {"username": account["username"], "updated_at": account["updated_at"]}


@admin.delete("/settings/usb-account")
def delete_usb_account():
    usb_account_path().unlink(missing_ok=True)
    return {"ok": True}


# --------------------------------------------------------------------------- first admin

def initial_password_file():
    return settings.data_dir / "initial-admin-password.txt"


def ensure_admin(db: Session) -> str | None:
    """Create the "admin" account when there are no accounts. Returns a generated
    password (also saved to initial-admin-password.txt) or None."""
    if db.scalar(select(func.count()).select_from(User)):
        return None
    import secrets

    password = settings.initial_admin_password or secrets.token_urlsafe(12)
    db.add(User(username="admin", name="Administrator", role="admin", password_hash=hash_password(password)))
    db.commit()
    if settings.initial_admin_password:
        return None
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    f = initial_password_file()
    f.write_text(password + "\n")
    f.chmod(0o600)
    return password
