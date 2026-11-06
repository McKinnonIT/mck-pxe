"""Account recovery from the server's shell, for when nobody can sign in.

    python -m mckpxe.cli reset-password USERNAME

Sets a new random password (printed once), makes the account an enabled admin
and signs it out everywhere. Creates the account if it doesn't exist.
"""
import secrets
import sys

from sqlalchemy import select

from .auth import check_username, end_user_sessions, hash_password
from .db import Base, SessionLocal, engine
from .models import User


def reset_password(username: str) -> str:
    username = check_username(username)
    password = secrets.token_urlsafe(12)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.username == username)).first()
        if not user:
            user = User(username=username, name=username)
            db.add(user)
        user.password_hash, user.role, user.enabled = hash_password(password), "admin", True
        db.commit()
        end_user_sessions(db, user.id)
    return password


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "reset-password":
        print(__doc__.strip(), file=sys.stderr)
        return 2
    password = reset_password(argv[1])
    print(f"{argv[1]} is an admin with the password: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
