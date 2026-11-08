from .compression import state_out
from .models import DriverPack, Host, Image, Task
from .tasks import is_online


def host_out(h: Host) -> dict:
    return {
        "id": h.id, "mac": h.mac, "name": h.name or h.mac, "ip": h.ip, "manufacturer": h.manufacturer,
        "model": h.model, "sku": h.sku, "serial": h.serial, "cpu": h.cpu, "ram_mb": h.ram_mb,
        "boot_mode": h.boot_mode, "secure_boot": h.secure_boot, "disks": h.disks,
        "hardware_id_count": len(h.hardware_ids or []), "notes": h.notes,
        "first_seen": h.first_seen, "last_seen": h.last_seen, "online": is_online(h),
    }


def image_out(i: Image) -> dict:
    return {
        "id": i.id, "name": i.name, "description": i.description, "kind": i.kind, "os_family": i.os_family,
        "status": i.status, "error": i.error, "size_bytes": i.size_bytes, "meta": i.meta,
        "has_unattend": bool(i.unattend), "source": i.source, "created_by": i.created_by,
        "created_at": i.created_at,
        "compression": state_out(i.compression) if i.kind == "block" else None,
    }


def pack_out(p: DriverPack, with_drivers: bool = False) -> dict:
    out = {
        "id": p.id, "name": p.name, "manufacturer": p.manufacturer, "model_match": p.model_match,
        "enabled": p.enabled, "status": p.status, "error": p.error, "filename": p.filename,
        "size_bytes": p.size_bytes, "driver_count": len(p.drivers), "created_by": p.created_by,
        "created_at": p.created_at,
        "classes": sorted({d.class_name for d in p.drivers if d.class_name}),
    }
    if with_drivers:
        out["drivers"] = [
            {"id": d.id, "inf_path": d.inf_path, "class_name": d.class_name, "provider": d.provider,
             "version": d.version, "hardware_id_count": len(d.hardware_ids or [])}
            for d in p.drivers
        ]
    return out


def task_out(t: Task, with_log: bool = False) -> dict:
    out = {
        "id": t.id, "type": t.type, "kind": t.kind, "disk": t.disk, "params": t.params, "status": t.status,
        "progress": t.progress, "message": t.message, "cancel_requested": t.cancel_requested,
        "created_by": t.created_by, "created_at": t.created_at, "started_at": t.started_at,
        "finished_at": t.finished_at,
        "host": {"id": t.host.id, "name": t.host.name or t.host.mac, "model": t.host.model} if t.host else None,
        "image": {"id": t.image.id, "name": t.image.name} if t.image else None,
    }
    if with_log:
        out["log"] = t.log
    return out
