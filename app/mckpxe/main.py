import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import update

from . import compression
from .db import Base, SessionLocal, engine
from .drivers import ensure_dirs
from .models import DriverPack, Image
from .routers import accounts, admin, agent, boot

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    Base.metadata.create_all(engine)
    # Background jobs don't survive a restart; flag anything left half-done.
    with SessionLocal() as db:
        db.execute(update(Image).where(Image.status.in_(("uploading", "processing")))
                   .values(status="error", error="Interrupted by a server restart; upload again"))
        db.execute(update(DriverPack).where(DriverPack.status.in_(("uploading", "processing")))
                   .values(status="error", error="Interrupted by a server restart; upload again"))
        db.commit()
        password = accounts.ensure_admin(db)
    compression.resume()
    if password:
        log.warning("Created the first account: username admin, password %s (also saved in %s). "
                    "Sign in and change it.", password, accounts.initial_password_file())
    yield


app = FastAPI(title="mck-pxe", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(agent.router)
app.include_router(boot.router)
app.include_router(accounts.router)
app.include_router(accounts.admin)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"ok": True}
