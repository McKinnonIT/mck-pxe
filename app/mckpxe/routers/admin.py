"""Admin API used by the web UI. Every route needs a signed-in admin (see auth.py)."""
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import boot_menu, iso
from ..auth import Me, current_user
from ..config import settings
from ..db import get_db
from ..drivers import model_matches, pack_dir, process_pack, remove_pack_files, select_drivers
from ..images import image_dir, process_wim, remove_image_files
from ..models import DriverPack, Host, Image, Task
from ..serialize import host_out, image_out, pack_out, task_out
from ..tasks import ACTIVE, active_task, cancel_task, create_task

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(current_user)])


async def save_stream(request: Request, path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with open(path, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            size += len(chunk)
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")
    return size


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


# --------------------------------------------------------------------------- general

@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    hosts = db.scalars(select(Host)).all()
    tasks = db.scalars(select(Task).where(Task.status.in_(ACTIVE)).order_by(Task.id)).all()
    recent = db.scalars(select(Task).where(Task.status.not_in(ACTIVE)).order_by(Task.id.desc()).limit(8)).all()
    return {
        "hosts": len(hosts),
        "online": sum(1 for h in hosts if host_out(h)["online"]),
        "images": db.scalar(select(func.count()).select_from(Image).where(Image.status == "ready")),
        "image_bytes": db.scalar(select(func.coalesce(func.sum(Image.size_bytes), 0))),
        "driver_packs": db.scalar(select(func.count()).select_from(DriverPack)),
        "active_tasks": [task_out(t) for t in tasks],
        "recent_tasks": [task_out(t) for t in recent],
    }


@router.get("/settings/boot-menu")
def get_boot_menu(db: Session = Depends(get_db)):
    return boot_menu.get(db)


@router.put("/settings/boot-menu")
def set_boot_menu(data: dict = Body(...), db: Session = Depends(get_db)):
    return boot_menu.put(db, data)


@router.get("/settings")
def get_settings():
    boot = {name: (settings.bootenv_dir / name).exists() for name in ("vmlinuz", "initrd.img", "filesystem.squashfs")}
    return {
        "server_ip": settings.server_ip,
        "bcd_present": settings.bcd_path.exists(),
        "bootenv": boot,
    }


@router.put("/settings/bcd")
async def upload_bcd(request: Request):
    tmp = settings.system_dir / "BCD.upload"
    await save_stream(request, tmp)
    with open(tmp, "rb") as f:
        if f.read(4) != b"regf":
            tmp.unlink()
            raise HTTPException(400, "That isn't a BCD store (expected a registry hive)")
    tmp.rename(settings.bcd_path)
    return {"ok": True}


@router.delete("/settings/bcd")
def delete_bcd():
    settings.bcd_path.unlink(missing_ok=True)
    return {"ok": True}


# --------------------------------------------------------------------------- boot USB / ISO

@router.get("/iso")
def iso_status():
    return iso.status()


@router.post("/iso/build")
def iso_build():
    state = iso.status()
    if not state["available"]:
        raise HTTPException(400, "Can't build the ISO yet. Missing: " + ", ".join(state["missing"]))
    if not iso.start_build():
        raise HTTPException(409, "Already building")
    return iso.status()


@router.get("/iso/download")
def iso_download():
    if not iso.iso_path().exists():
        raise HTTPException(404, "No ISO built yet")
    return FileResponse(iso.iso_path(), media_type="application/octet-stream", filename="mck-pxe-boot.iso")


# --------------------------------------------------------------------------- hosts

@router.get("/hosts")
def list_hosts(db: Session = Depends(get_db)):
    hosts = db.scalars(select(Host).order_by(Host.last_seen.desc())).all()
    out = []
    for h in hosts:
        item = host_out(h)
        task = active_task(db, h.id)
        item["task"] = task_out(task) if task else None
        out.append(item)
    return out


@router.get("/hosts/{host_id}")
def get_host(host_id: int, db: Session = Depends(get_db)):
    host = get_or_404(db, Host, host_id)
    out = host_out(host)
    out["hardware_ids"] = host.hardware_ids
    tasks = db.scalars(select(Task).where(Task.host_id == host.id).order_by(Task.id.desc()).limit(20)).all()
    out["tasks"] = [task_out(t) for t in tasks]
    return out


@router.patch("/hosts/{host_id}")
def update_host(host_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    host = get_or_404(db, Host, host_id)
    for field in ("name", "notes"):
        if field in data:
            setattr(host, field, str(data[field]))
    db.commit()
    return host_out(host)


@router.delete("/hosts/{host_id}")
def delete_host(host_id: int, db: Session = Depends(get_db)):
    host = get_or_404(db, Host, host_id)
    if active_task(db, host.id):
        raise HTTPException(409, "Cancel this machine's task first")
    for t in db.scalars(select(Task).where(Task.host_id == host.id)):
        db.delete(t)
    db.delete(host)
    db.commit()
    return {"ok": True}


@router.get("/hosts/{host_id}/drivers")
def host_drivers(host_id: int, db: Session = Depends(get_db)):
    """Preview what the driver injector would install on this machine."""
    host = get_or_404(db, Host, host_id)
    plan = select_drivers(db, host)
    return [
        {"pack": {"id": e["pack"].id, "name": e["pack"].name}, "reason": e["reason"],
         "drivers": [{"inf_path": d.inf_path, "class_name": d.class_name, "provider": d.provider,
                      "version": d.version} for d in e["drivers"]]}
        for e in plan
    ]


# --------------------------------------------------------------------------- images

@router.get("/images")
def list_images(db: Session = Depends(get_db)):
    return [image_out(i) for i in db.scalars(select(Image).order_by(Image.created_at.desc()))]


@router.get("/images/{image_id}")
def get_image(image_id: int, db: Session = Depends(get_db)):
    image = get_or_404(db, Image, image_id)
    out = image_out(image)
    out["unattend"] = image.unattend
    return out


@router.patch("/images/{image_id}")
def update_image(image_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    image = get_or_404(db, Image, image_id)
    for field in ("name", "description", "unattend"):
        if field in data:
            setattr(image, field, str(data[field]))
    if data.get("os_family") in ("windows", "linux", "other"):
        image.os_family = data["os_family"]
    db.commit()
    return image_out(image)


@router.delete("/images/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    image = get_or_404(db, Image, image_id)
    if db.scalars(select(Task.id).where(Task.image_id == image.id, Task.status.in_(ACTIVE))).first():
        raise HTTPException(409, "Image is in use by a queued or running task")
    db.delete(image)
    db.commit()
    remove_image_files(image_id)
    return {"ok": True}


@router.put("/images/upload-wim")
async def upload_wim(request: Request, background: BackgroundTasks, name: str, description: str = "",
                     db: Session = Depends(get_db), user: Me = Depends(current_user)):
    """Upload a WIM or ESD (e.g. install.wim from Windows media) as a deployable image."""
    image = Image(name=name.strip() or "Windows", description=description, kind="wim", os_family="windows",
                  status="uploading", source="upload", created_by=user.username)
    db.add(image)
    db.commit()
    try:
        await save_stream(request, image_dir(image.id) / "upload.wim")
    except Exception:
        db.delete(image)
        db.commit()
        remove_image_files(image.id)
        raise
    image.status = "processing"
    db.commit()
    background.add_task(process_wim, image.id)
    return image_out(image)


# --------------------------------------------------------------------------- tasks

@router.get("/tasks")
def list_tasks(active: bool = False, limit: int = 100, db: Session = Depends(get_db)):
    q = select(Task).order_by(Task.id.desc()).limit(min(limit, 500))
    if active:
        q = q.where(Task.status.in_(ACTIVE))
    return [task_out(t) for t in db.scalars(q)]


@router.post("/tasks")
def new_task(data: dict = Body(...), db: Session = Depends(get_db), user: Me = Depends(current_user)):
    host = get_or_404(db, Host, int(data.get("host_id") or 0))
    return task_out(create_task(db, host, data, user.username))


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    return task_out(get_or_404(db, Task, task_id), with_log=True)


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: int, db: Session = Depends(get_db)):
    task = get_or_404(db, Task, task_id)
    cancel_task(db, task)
    return task_out(task)


# --------------------------------------------------------------------------- drivers

@router.get("/driver-packs")
def list_packs(db: Session = Depends(get_db)):
    return [pack_out(p) for p in db.scalars(select(DriverPack).order_by(DriverPack.manufacturer, DriverPack.name))]


@router.get("/driver-packs/{pack_id}")
def get_pack(pack_id: int, db: Session = Depends(get_db)):
    return pack_out(get_or_404(db, DriverPack, pack_id), with_drivers=True)


@router.put("/driver-packs/upload")
async def upload_pack(request: Request, background: BackgroundTasks, name: str, filename: str,
                      manufacturer: str = "", model_match: str = "",
                      db: Session = Depends(get_db), user: Me = Depends(current_user)):
    pack = DriverPack(name=name.strip() or filename, filename=filename, manufacturer=manufacturer.strip(),
                      model_match=model_match.strip(), created_by=user.username)
    db.add(pack)
    db.commit()
    try:
        await save_stream(request, pack_dir(pack.id) / "upload")
    except Exception:
        db.delete(pack)
        db.commit()
        remove_pack_files(pack.id)
        raise
    pack.status = "processing"
    db.commit()
    background.add_task(process_pack, pack.id)
    return pack_out(pack)


@router.patch("/driver-packs/{pack_id}")
def update_pack(pack_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    pack = get_or_404(db, DriverPack, pack_id)
    for field in ("name", "manufacturer", "model_match"):
        if field in data:
            setattr(pack, field, str(data[field]).strip())
    if "enabled" in data:
        pack.enabled = bool(data["enabled"])
    db.commit()
    return pack_out(pack)


@router.delete("/driver-packs/{pack_id}")
def delete_pack(pack_id: int, db: Session = Depends(get_db)):
    pack = get_or_404(db, DriverPack, pack_id)
    db.delete(pack)
    db.commit()
    remove_pack_files(pack_id)
    return {"ok": True}


@router.get("/models")
def models_seen(db: Session = Depends(get_db)):
    """Every hardware model that has PXE booted, with the packs that cover it."""
    hosts = db.scalars(select(Host)).all()
    packs = db.scalars(select(DriverPack).where(DriverPack.status == "ready")).all()
    counts = Counter((h.manufacturer, h.model) for h in hosts)
    out = []
    for (manufacturer, model), count in counts.most_common():
        sample = next(h for h in hosts if (h.manufacturer, h.model) == (manufacturer, model))
        matched = [{"id": p.id, "name": p.name} for p in packs if model_matches(p, sample)]
        out.append({"manufacturer": manufacturer, "model": model, "hosts": count, "packs": matched})
    return out
