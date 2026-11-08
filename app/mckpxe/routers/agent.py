"""API for the imaging agent running on PXE-booted machines.

Machines reach this without signing in: they register, fetch queued tasks and
report progress. Anything a person starts at the machine (console tasks, adding
an image from a USB stick) needs the bearer token from /login.
"""
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import compression
from ..auth import authenticate, console_user, end_session, new_session
from ..config import settings
from ..db import get_db
from ..drivers import select_drivers, slug, tar_stream
from ..images import SAFE_NAME, dir_size, image_dir, remove_image_files
from ..models import Host, Image, Task, User, utcnow
from ..tasks import create_task, finish_task, start_task
from .accounts import client_ip

router = APIRouter(prefix="/api/agent", tags=["agent"])

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
HOST_FIELDS = ("ip", "manufacturer", "model", "sku", "serial", "cpu", "ram_mb", "boot_mode",
               "secure_boot", "disks", "hardware_ids")
MAX_LOG = 200_000


def norm_mac(mac: str) -> str:
    mac = (mac or "").strip().lower().replace("-", ":")
    if not MAC_RE.match(mac):
        raise HTTPException(400, "Invalid MAC address")
    return mac


def host_by_mac(db: Session, mac: str) -> Host:
    host = db.scalars(select(Host).where(Host.mac == norm_mac(mac))).first()
    if not host:
        raise HTTPException(404, "Unknown machine; register first")
    return host


def running_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if not task or task.status != "running":
        raise HTTPException(409, "Task is not running")
    return task


@router.post("/register")
def register(data: dict = Body(...), db: Session = Depends(get_db)):
    mac = norm_mac(data.get("mac", ""))
    host = db.scalars(select(Host).where(Host.mac == mac)).first()
    if not host:
        host = Host(mac=mac)
        db.add(host)
    for field in HOST_FIELDS:
        if field in data and data[field] is not None:
            setattr(host, field, data[field])
    host.last_seen = utcnow()
    db.commit()
    return {"host_id": host.id, "name": host.name or mac}


@router.get("/next")
def next_task(mac: str, db: Session = Depends(get_db)):
    host = host_by_mac(db, mac)
    host.last_seen = utcnow()
    task = db.scalars(
        select(Task).where(Task.host_id == host.id, Task.status == "queued").order_by(Task.id)
    ).first()
    if not task:
        db.commit()
        return None
    return start_task(db, task)


@router.get("/images")
def list_images(db: Session = Depends(get_db)):
    images = db.scalars(select(Image).where(Image.status == "ready").order_by(Image.name)).all()
    return [{"id": i.id, "name": i.name, "kind": i.kind, "os_family": i.os_family, "meta": i.meta} for i in images]


@router.post("/login")
def login(request: Request, data: dict = Body(...), db: Session = Depends(get_db)):
    """A technician or admin signing in at a machine's imaging environment."""
    host_by_mac(db, data.get("mac", ""))  # only machines that have registered
    user = authenticate(db, data.get("username", ""), data.get("password", ""), client_ip(request))
    token = new_session(db, user, "console")
    return {"token": token, "user": {"username": user.username, "name": user.name or user.username,
                                     "role": user.role}}


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(console_user)):
    end_session(db, request.headers["Authorization"][7:])
    return {"ok": True}


async def save_upload(request: Request, image_id: int, filename: str) -> int:
    """Stream a request body into one image file, appearing only once complete."""
    if not SAFE_NAME.match(filename):
        raise HTTPException(400, "Invalid file name")
    folder = image_dir(image_id)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{filename}.part"
    size = 0
    with open(tmp, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            size += len(chunk)
    tmp.rename(folder / filename)
    return size


@router.post("/tasks")
def console_task(data: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(console_user)):
    """Someone signed in at the machine started a deploy or capture."""
    host = host_by_mac(db, data.get("mac", ""))
    task = create_task(db, host, data, user=f"{user.username} at {host.name or host.mac}")
    return {"id": task.id}


@router.post("/tasks/{task_id}/progress")
def progress(task_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    task = running_task(db, task_id)
    if data.get("progress") is not None:
        task.progress = float(data["progress"])
    if data.get("message"):
        task.message = str(data["message"])[:500]
    if data.get("log"):
        task.log = (task.log + "".join(f"{line}\n" for line in data["log"]))[-MAX_LOG:]
    task.host.last_seen = utcnow()
    db.commit()
    return {"cancelled": task.cancel_requested}


@router.post("/tasks/{task_id}/complete")
def complete(task_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    task = running_task(db, task_id)
    if data.get("log"):
        task.log = (task.log + "".join(f"{line}\n" for line in data["log"]))[-MAX_LOG:]
    finish_task(db, task, bool(data.get("ok")), str(data.get("message") or ""), data)
    return {"ok": True}


@router.put("/tasks/{task_id}/upload/{filename}")
async def upload(task_id: int, filename: str, request: Request, db: Session = Depends(get_db)):
    """Streamed upload of one capture file (partition image, partition table, WIM)."""
    task = running_task(db, task_id)
    if task.type != "capture":
        raise HTTPException(400, "Invalid upload")
    return {"bytes": await save_upload(request, task.image_id, filename)}


@router.get("/tasks/{task_id}/drivers/{pack_id}.tar")
def drivers_tar(task_id: int, pack_id: int, db: Session = Depends(get_db)):
    task = running_task(db, task_id)
    plan = next((p for p in task.params.get("driver_plan", []) if p["pack_id"] == pack_id), None)
    if not plan:
        raise HTTPException(404, "Driver pack not part of this task")
    return StreamingResponse(tar_stream(pack_id, plan["dirs"]), media_type="application/x-tar")


@router.get("/images/{image_id}/unattend.xml", response_class=PlainTextResponse)
def unattend(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if not image or not image.unattend:
        raise HTTPException(404)
    return PlainTextResponse(image.unattend, media_type="application/xml")


# --------------------------------------------------------------------------- USB stick sync
#
# The boot USB can hold images. When the server is reachable, the console can
# copy a server image (and this machine's drivers) onto the stick, or add an
# image from the stick to the library.

def ready_image(db: Session, image_id: int) -> Image:
    image = db.get(Image, image_id)
    if not image or image.status != "ready":
        raise HTTPException(404, "Image not found or not ready")
    return image


@router.get("/images/{image_id}/manifest")
def image_manifest(image_id: int, mac: str = "", db: Session = Depends(get_db)):
    """Everything needed to copy an image to the stick, with drivers for the asking machine."""
    image = ready_image(db, image_id)
    base = settings.public_url
    files = [
        {"name": p.name, "size": p.stat().st_size, "url": f"{base}/files/images/{image.id}/{p.name}"}
        for p in sorted(image_dir(image.id).iterdir()) if p.is_file() and not p.name.startswith(".")
    ]
    drivers = []
    host = db.scalars(select(Host).where(Host.mac == norm_mac(mac))).first() if mac else None
    if host and image.os_family == "windows":
        for entry in select_drivers(db, host):
            pack = entry["pack"]
            drivers.append({"name": pack.name, "slug": f"{pack.id}-{slug(pack.name)}", "count": len(entry["drivers"]),
                            "url": f"{base}/api/agent/drivers/{pack.id}.tar?mac={host.mac}"})
    return {
        "image": {"id": image.id, "name": image.name, "description": image.description, "kind": image.kind,
                  "os_family": image.os_family, "meta": image.meta},
        "unattend": image.unattend,
        "files": files,
        "drivers": drivers,
        "bcd_url": f"{base}/files/system/BCD" if image.kind == "wim" and settings.bcd_path.exists() else None,
    }


@router.get("/drivers/{pack_id}.tar")
def drivers_for_machine(pack_id: int, mac: str, db: Session = Depends(get_db)):
    """The drivers from one pack that this machine would get on a deploy."""
    host = host_by_mac(db, mac)
    entry = next((e for e in select_drivers(db, host) if e["pack"].id == pack_id), None)
    if not entry:
        raise HTTPException(404, "No drivers from this pack match this machine")
    dirs = sorted({d.directory for d in entry["drivers"]})
    return StreamingResponse(tar_stream(pack_id, dirs), media_type="application/x-tar")


def importing_image(db: Session, image_id: int) -> Image:
    image = db.get(Image, image_id)
    if not image or image.status != "uploading" or not image.source.startswith("USB"):
        raise HTTPException(409, "This image isn't being uploaded")
    return image


@router.post("/images")
def import_image(data: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(console_user)):
    """Start adding an image from a USB stick to the library."""
    host = host_by_mac(db, data.get("mac", ""))
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "The image needs a name")
    if data.get("kind") not in ("block", "wim"):
        raise HTTPException(400, "kind must be block or wim")
    image = Image(
        name=name, description=str(data.get("description") or ""), kind=data["kind"],
        os_family=data.get("os_family") if data.get("os_family") in ("windows", "linux", "other") else "other",
        meta=data.get("meta") if isinstance(data.get("meta"), dict) else {},
        unattend=str(data.get("unattend") or ""), status="uploading",
        source=f"USB via {host.name or host.mac}", created_by=f"{user.username} at {host.name or host.mac}",
    )
    db.add(image)
    db.commit()
    return {"id": image.id}


@router.put("/images/{image_id}/upload/{filename}")
async def import_upload(image_id: int, filename: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(console_user)):
    importing_image(db, image_id)
    return {"bytes": await save_upload(request, image_id, filename)}


@router.post("/images/{image_id}/complete")
def import_complete(image_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                    user: User = Depends(console_user)):
    image = importing_image(db, image_id)
    if data.get("ok"):
        image.size_bytes = dir_size(image_dir(image.id))
        image.status, image.error = "ready", ""
    else:
        image.status, image.error = "error", str(data.get("message") or "Upload from USB failed")
        remove_image_files(image.id)
    db.commit()
    if data.get("ok"):
        compression.after_capture(db, image)
    return {"ok": True}
