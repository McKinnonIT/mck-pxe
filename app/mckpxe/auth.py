from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import settings


@dataclass
class User:
    email: str
    name: str


def current_user(request: Request) -> User:
    """Identity comes from Pangolin (Google OIDC) via forwarded headers."""
    email = (request.headers.get("Remote-Email") or request.headers.get("Remote-User") or "").strip().lower()
    name = request.headers.get("Remote-Name") or ""
    if not email and settings.dev_user:
        email, name = settings.dev_user, "Developer"
    if not email:
        raise HTTPException(401, "Not authenticated (expected Pangolin Remote-Email header)")
    if settings.admin_emails and email not in settings.admin_emails:
        raise HTTPException(403, "Not an mck-pxe administrator")
    if settings.admin_domain and not email.endswith("@" + settings.admin_domain):
        raise HTTPException(403, "Not an mck-pxe administrator")
    return User(email=email, name=name or email)
