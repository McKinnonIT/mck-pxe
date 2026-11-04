"""Per-machine boot menus. Machines with a queued task boot straight into
imaging; everything else gets a short menu that defaults to the local disk."""
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Host, Task

router = APIRouter(prefix="/api/boot", tags=["boot"])


def kernel_args() -> str:
    s = settings.public_url
    return (f"boot=live fetch={s}/boot/filesystem.squashfs mckpxe.server={s} "
            "systemd.hostname=mckpxe quiet")


def has_queued_task(db: Session, mac: str) -> bool:
    mac = mac.lower().replace("-", ":")
    host = db.scalars(select(Host).where(Host.mac == mac)).first()
    if not host:
        return False
    return db.scalars(select(Task.id).where(Task.host_id == host.id, Task.status == "queued")).first() is not None


def boot_choice(db: Session, mac: str) -> tuple[str, int]:
    """(default entry, timeout seconds)"""
    if has_queued_task(db, mac):
        return "imaging", 0
    return ("imaging" if settings.default_boot == "imaging" else "local"), 5


@router.get("/ipxe/{mac}", response_class=PlainTextResponse)
def ipxe(mac: str, db: Session = Depends(get_db)):
    default, timeout = boot_choice(db, mac)
    s = settings.public_url
    return f"""#!ipxe
menu mck-pxe
item local   Boot from local disk
item imaging mck-pxe imaging environment
choose --default {default} --timeout {timeout * 1000} target && goto ${{target}}

:local
exit

:imaging
kernel {s}/boot/vmlinuz initrd=initrd.img {kernel_args()}
initrd {s}/boot/initrd.img
boot
"""


@router.get("/grub/{mac}.cfg", response_class=PlainTextResponse)
def grub(mac: str, db: Session = Depends(get_db)):
    default, timeout = boot_choice(db, mac)
    src = f"(http,{settings.server_ip})"
    return f"""set timeout={timeout}
set default={1 if default == 'imaging' else 0}

menuentry "Boot from local disk" {{
  exit
}}

menuentry "mck-pxe imaging environment" {{
  echo "Loading mck-pxe..."
  linux {src}/boot/vmlinuz {kernel_args()}
  initrd {src}/boot/initrd.img
}}
"""
