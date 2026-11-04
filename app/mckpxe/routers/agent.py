"""API for the imaging agent running on PXE-booted machines.

Reachable from the imaging network without login (machines can't do OIDC).
Console-initiated tasks can be protected with AGENT_PIN.
"""
import hmac
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..drivers import tar_stream
from ..images import SAFE_NAME, image_dir
from ..models import Host, Image, Task, utcnow
from ..tasks import create_task, finish_task, start_task

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
    return {"host_id": host.id, "name": host.name or mac, "pin_required": bool(settings.agent_pin)}


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


@router.post("/tasks")
def console_task(data: dict = Body(...), db: Session = Depends(get_db)):
    """A technician at the machine started a deploy or capture from the console menu."""
    host = host_by_mac(db, data.get("mac", ""))
    if settings.agent_pin and not hmac.compare_digest(str(data.get("pin", "")), settings.agent_pin):
        raise HTTPException(403, "Wrong PIN")
    task = create_task(db, host, data, user=f"console:{host.name or host.mac}")
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
    if task.type != "capture" or not SAFE_NAME.match(filename):
        raise HTTPException(400, "Invalid upload")
    folder = image_dir(task.image_id)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{filename}.part"
    size = 0
    with open(tmp, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            size += len(chunk)
    tmp.rename(folder / filename)
    return {"bytes": size}


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
