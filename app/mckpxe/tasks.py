"""Task creation and lifecycle, shared by the admin API and the agent API."""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .drivers import select_drivers, slug
from .images import dir_size, image_dir
from .models import Host, Image, Task, utcnow

ACTIVE = ("queued", "running")
ONLINE_WINDOW = timedelta(seconds=60)


def is_online(host: Host) -> bool:
    last = host.last_seen if host.last_seen.tzinfo else host.last_seen.replace(tzinfo=UTC)
    return datetime.now(UTC) - last < ONLINE_WINDOW


def active_task(db: Session, host_id: int) -> Task | None:
    return db.scalars(select(Task).where(Task.host_id == host_id, Task.status.in_(ACTIVE))).first()


def create_task(db: Session, host: Host, data: dict, user: str) -> Task:
    if active_task(db, host.id):
        raise HTTPException(409, "This machine already has a task queued or running")
    ttype, disk = data.get("type"), (data.get("disk") or "").strip()
    if ttype not in ("capture", "deploy"):
        raise HTTPException(400, "type must be capture or deploy")
    if not disk.startswith("/dev/"):
        raise HTTPException(400, "Choose a target disk")
    params = {"after": data.get("after") or ("reboot" if ttype == "deploy" else "wait")}

    if ttype == "deploy":
        image = db.get(Image, data.get("image_id") or 0)
        if not image or image.status != "ready":
            raise HTTPException(400, "Image is not ready")
        kind = image.kind
        params["drivers"] = data.get("drivers") or "auto"
        # The agent refuses Windows deploys whose RST/VMD storage mode doesn't match, unless this is set
        params["allow_storage_mismatch"] = bool(data.get("allow_storage_mismatch"))
        if kind == "wim":
            indexes = [i["index"] for i in image.meta.get("indexes", [])] or [1]
            index = int(data.get("wim_index") or indexes[0])
            if index not in indexes:
                raise HTTPException(400, f"WIM index must be one of {indexes}")
            if not settings.bcd_path.exists():
                raise HTTPException(400, "Upload a Windows BCD template in Settings before deploying WIM images")
            params["wim_index"] = index
    else:
        kind = data.get("kind") or "block"
        name = (data.get("name") or "").strip()
        if kind not in ("block", "wim"):
            raise HTTPException(400, "kind must be block or wim")
        if not name:
            raise HTTPException(400, "Give the new image a name")
        image = Image(name=name, description=data.get("description") or "", kind=kind,
                      status="capturing", source=f"{host.manufacturer} {host.model}".strip(), created_by=user)
        db.add(image)
        db.flush()
        params["name"] = name

    task = Task(host_id=host.id, image_id=image.id, type=ttype, kind=kind, disk=disk,
                params=params, created_by=user)
    db.add(task)
    db.commit()
    return task


def start_task(db: Session, task: Task) -> dict:
    """Mark a task running and build the instructions the agent needs."""
    base = settings.public_url
    task.status, task.started_at, task.message = "running", utcnow(), "Starting"
    image = task.image
    out = {
        "id": task.id, "type": task.type, "kind": task.kind, "disk": task.disk, "params": task.params,
        "image": {"id": image.id, "name": image.name, "kind": image.kind,
                  "os_family": image.os_family, "meta": image.meta} if image else None,
        "files_url": f"{base}/files/images/{task.image_id}/",
        "upload_url": f"{base}/api/agent/tasks/{task.id}/upload",
        "drivers": [],
    }
    if task.type == "deploy" and image:
        if image.os_family == "windows" and task.params.get("drivers") == "auto":
            plan = []
            for entry in select_drivers(db, task.host):
                pack = entry["pack"]
                plan.append({"pack_id": pack.id, "name": pack.name, "slug": f"{pack.id}-{slug(pack.name)}",
                             "dirs": sorted({d.directory for d in entry["drivers"]}),
                             "count": len(entry["drivers"])})
            task.params = {**task.params, "driver_plan": plan}
            out["params"] = task.params
            out["drivers"] = [
                {"name": p["name"], "slug": p["slug"], "count": p["count"],
                 "url": f"{base}/api/agent/tasks/{task.id}/drivers/{p['pack_id']}.tar"}
                for p in plan
            ]
        if image.unattend:
            out["unattend_url"] = f"{base}/api/agent/images/{image.id}/unattend.xml"
        if image.kind == "wim":
            out["bcd_url"] = f"{base}/files/system/BCD"
    db.commit()
    return out


def finish_task(db: Session, task: Task, ok: bool, message: str, result: dict) -> None:
    task.finished_at = utcnow()
    task.message = message
    if ok:
        task.status, task.progress = "done", 100
    else:
        task.status = "cancelled" if message == "cancelled" or task.cancel_requested else "failed"
    image = task.image
    if task.type == "capture" and image:
        if ok:
            image.meta = result.get("meta") or {}
            image.os_family = result.get("os_family") or image.os_family
            image.size_bytes = dir_size(image_dir(image.id))
            image.status, image.error = "ready", ""
        else:
            image.status, image.error = "error", message
    db.commit()


def cancel_task(db: Session, task: Task) -> None:
    if task.status == "queued" or (task.status == "running" and not is_online(task.host)):
        task.status, task.finished_at, task.message = "cancelled", utcnow(), "cancelled"
        if task.type == "capture" and task.image and task.image.status == "capturing":
            task.image.status, task.image.error = "error", "Capture cancelled"
    elif task.status == "running":
        task.cancel_requested = True
    db.commit()
