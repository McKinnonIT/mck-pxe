"""Per-machine boot menus. Machines with a queued task boot straight into
imaging; everything else gets a short menu that defaults to the local disk."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import boot_menu, isolib
from ..config import settings
from ..db import get_db
from ..models import BootIso, Host, Task

router = APIRouter(prefix="/api/boot", tags=["boot"])

# Kernel argument for the backup text menu instead of the graphical (Firefox) UI
TEXT_MODE = "mckpxe.ui=text"
# Skip the GPU driver and use the firmware's display (simpledrm); the UI then
# draws in software. For machines whose graphics driver misbehaves.
SAFE_GRAPHICS = "nomodeset"
# GRUB menus number their entries: imaging, safe graphics, text mode, ISO library, netboot.xyz, then local disk
GRUB_LOCAL_ENTRY = 5
# The ISO library boots kernels nothing in the Secure Boot chain trusts, so it runs from iPXE.
# UEFI machines get there from GRUB through iPXE's snponly.efi, which asks for the library menu.
ISO_LIBRARY = "ISO library (Secure Boot off)"
# netboot.xyz: Linux installers and live systems from the internet. Its loaders are
# signed by nobody Secure Boot trusts, so machines need Secure Boot off for this entry.
NETBOOT_XYZ = "netboot.xyz - Linux installers (Secure Boot off)"


def kernel_args() -> str:
    s = settings.public_url
    return (f"boot=live ethdevice-timeout=60 fetch={s}/boot/filesystem.squashfs mckpxe.server={s} "
            "systemd.hostname=mckpxe md_mod.start_ro=1 quiet loglevel=3")


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
    menu = boot_menu.get(db)
    return menu["default"], menu["timeout"]


@router.get("/ipxe/{mac}", response_class=PlainTextResponse)
def ipxe(mac: str, platform: str = "", db: Session = Depends(get_db)):
    if platform == "efi":  # only UEFI machines that picked the ISO library in GRUB run iPXE
        return ipxe_isos(db)
    default, timeout = boot_choice(db, mac)
    s = settings.public_url
    return f"""#!ipxe
menu mck-pxe
item imaging mck-pxe imaging environment
item safe    mck-pxe imaging environment (safe graphics)
item text    mck-pxe imaging environment (text mode)
item isos    {ISO_LIBRARY}
item netboot {NETBOOT_XYZ}
item local   Boot from local disk
choose --default {default} --timeout {timeout * 1000} target && goto ${{target}}

:local
exit

:imaging
kernel {s}/boot/vmlinuz initrd=initrd.img {kernel_args()}
initrd {s}/boot/initrd.img
boot

:safe
kernel {s}/boot/vmlinuz initrd=initrd.img {kernel_args()} {SAFE_GRAPHICS}
initrd {s}/boot/initrd.img
boot

:text
kernel {s}/boot/vmlinuz initrd=initrd.img {kernel_args()} {TEXT_MODE}
initrd {s}/boot/initrd.img
boot

:isos
chain {s}/api/boot/ipxe-isos

:netboot
chain {s}/boot/netboot.xyz.lkrn
"""


@router.get("/ipxe-isos", response_class=PlainTextResponse)
def ipxe_isos(db: Session = Depends(get_db)):
    s = settings.public_url
    isos = db.scalars(select(BootIso).where(BootIso.status == "ready").order_by(BootIso.name)).all()
    items = ("\n".join(f"item iso{i.id} {i.name}" for i in isos)
             or "item --gap (No ISOs yet: add them on the ISO library page)")
    gotos = "\n".join(f":iso{i.id}\nchain {s}/api/boot/ipxe-iso/{i.id}\n" for i in isos)
    return f"""#!ipxe
menu ISO library
{items}
item --gap
item exit    Exit
choose target && goto ${{target}}

:exit
exit

{gotos}"""


@router.get("/ipxe-iso/{iso_id}", response_class=PlainTextResponse)
def ipxe_iso(iso_id: int, db: Session = Depends(get_db)):
    item = db.get(BootIso, iso_id)
    if not item or item.status != "ready":
        raise HTTPException(404, "ISO not found")
    return isolib.ipxe_script(item)


@router.get("/grub/{mac}.cfg", response_class=PlainTextResponse)
def grub(mac: str, db: Session = Depends(get_db)):
    default, timeout = boot_choice(db, mac)
    src = f"(http,{settings.server_ip})"
    return f"""set timeout={timeout}
set default={0 if default == 'imaging' else GRUB_LOCAL_ENTRY}

menuentry "mck-pxe imaging environment" {{
  echo "Loading mck-pxe..."
  linux {src}/boot/vmlinuz {kernel_args()}
  initrd {src}/boot/initrd.img
}}

menuentry "mck-pxe imaging environment (safe graphics)" {{
  echo "Loading mck-pxe..."
  linux {src}/boot/vmlinuz {kernel_args()} {SAFE_GRAPHICS}
  initrd {src}/boot/initrd.img
}}

menuentry "mck-pxe imaging environment (text mode)" {{
  echo "Loading mck-pxe..."
  linux {src}/boot/vmlinuz {kernel_args()} {TEXT_MODE}
  initrd {src}/boot/initrd.img
}}

menuentry "{ISO_LIBRARY}" {{
  echo "Loading iPXE..."
  chainloader (tftp,{settings.server_ip})/snponly.efi
}}

menuentry "{NETBOOT_XYZ}" {{
  echo "Loading netboot.xyz..."
  chainloader {src}/boot/netboot.xyz.efi
}}

menuentry "Boot from local disk" {{
  exit
}}
"""
