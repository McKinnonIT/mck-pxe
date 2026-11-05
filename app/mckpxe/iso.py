"""Bootable USB/ISO image of the imaging environment.

The ISO boots the same kernel, initrd and squashfs that PXE clients get, but
from local media, so a machine only needs ordinary DHCP and HTTP access to
this server. Handy for testing before PXE/relay is set up.

Layout (hybrid: works burned to CD or written raw to a USB stick):
  /live/{vmlinuz,initrd.img,filesystem.squashfs}
  /boot/grub/grub.cfg       UEFI: shim -> Debian-signed GRUB (gcdx64) reads this
  /boot/grub/efi.img        FAT image with EFI/boot/*, the El Torito UEFI entry
  /EFI/boot/                same files, for tools that copy files instead of dd
  /isolinux/                BIOS boot
  /.disk/info               signed GRUB searches for this to find the ISO
"""
import json
import shutil
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from .config import settings

VOLUME_ID = "MCKPXE"
BOOTENV_FILES = ("vmlinuz", "initrd.img", "filesystem.squashfs")
LOADER_FILES = ("bootx64.efi", "grubx64.efi", "isolinux.bin", "ldlinux.c32", "isohdpfx.bin")
TOOLS = ("xorriso", "mkfs.vfat", "mmd", "mcopy")

_lock = threading.Lock()
_state = {"building": False, "error": ""}


def iso_path() -> Path:
    return settings.system_dir / "mck-pxe-boot.iso"


def meta_path() -> Path:
    return settings.system_dir / "mck-pxe-boot.json"


def kernel_args() -> str:
    # toram: copy the system into memory so the stick can be pulled out
    return f"boot=live toram mckpxe.server={settings.public_url} systemd.hostname=mckpxe quiet"


def bootenv_stamp() -> float:
    return max((settings.bootenv_dir / f).stat().st_mtime for f in BOOTENV_FILES)


def missing() -> list[str]:
    out = [f"imaging environment: {f}" for f in BOOTENV_FILES if not (settings.bootenv_dir / f).exists()]
    out += [f"boot loader: {f}" for f in LOADER_FILES if not (settings.iso_loaders_dir / f).exists()]
    out += [f"tool: {t}" for t in TOOLS if not shutil.which(t)]
    return out


def status() -> dict:
    meta = None
    if iso_path().exists() and meta_path().exists():
        meta = json.loads(meta_path().read_text())
    gaps = missing()
    stale = False
    if meta and not any(g.startswith("imaging") for g in gaps):
        stale = meta.get("server") != settings.public_url or meta.get("bootenv_stamp") != bootenv_stamp()
    return {
        "available": not gaps,
        "missing": gaps,
        "building": _state["building"],
        "error": _state["error"],
        "server": settings.public_url,
        "built": meta,
        "stale": stale,
    }


def grub_cfg() -> str:
    return f"""set timeout=3
set default=0

menuentry "mck-pxe imaging environment ({settings.public_url})" {{
  linux /live/vmlinuz {kernel_args()}
  initrd /live/initrd.img
}}

menuentry "Boot from local disk" {{
  exit
}}
"""


def isolinux_cfg() -> str:
    return f"""DEFAULT mckpxe
PROMPT 0
LABEL mckpxe
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img {kernel_args()}
"""


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {(p.stderr or p.stdout).strip()[-500:]}")


def _place(src: Path, dst: Path) -> None:
    """Hard link when possible (same filesystem), else copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst.hardlink_to(src)
    except OSError:
        shutil.copyfile(src, dst)


def build() -> None:
    """Build the ISO. Runs in a background thread; progress is in status()."""
    loaders = settings.iso_loaders_dir
    settings.system_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=settings.system_dir, prefix=".iso-") as tmp:
            root = Path(tmp) / "root"
            stamp = bootenv_stamp()
            for f in BOOTENV_FILES:
                _place(settings.bootenv_dir / f, root / "live" / f)
            (root / ".disk").mkdir(parents=True)
            (root / ".disk" / "info").write_text("mck-pxe imaging environment\n")
            (root / "boot" / "grub").mkdir(parents=True)
            (root / "boot" / "grub" / "grub.cfg").write_text(grub_cfg())
            (root / "isolinux").mkdir()
            for f in ("isolinux.bin", "ldlinux.c32"):
                shutil.copyfile(loaders / f, root / "isolinux" / f)
            (root / "isolinux" / "isolinux.cfg").write_text(isolinux_cfg())
            (root / "EFI" / "boot").mkdir(parents=True)
            for f in ("bootx64.efi", "grubx64.efi"):
                shutil.copyfile(loaders / f, root / "EFI" / "boot" / f)

            efi_img = root / "boot" / "grub" / "efi.img"
            _run(["mkfs.vfat", "-C", "-n", "MCKPXE_EFI", str(efi_img), "8192"])
            _run(["mmd", "-i", str(efi_img), "::/EFI", "::/EFI/boot"])
            _run(["mcopy", "-i", str(efi_img), str(loaders / "bootx64.efi"), str(loaders / "grubx64.efi"),
                  "::/EFI/boot/"])

            out = Path(tmp) / "out.iso"
            _run([
                "xorriso", "-as", "mkisofs", "-r", "-J", "-joliet-long", "-V", VOLUME_ID, "-o", str(out),
                "-isohybrid-mbr", str(loaders / "isohdpfx.bin"),
                "-b", "isolinux/isolinux.bin", "-c", "isolinux/boot.cat",
                "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
                "-eltorito-alt-boot", "-e", "boot/grub/efi.img", "-no-emul-boot", "-isohybrid-gpt-basdat",
                str(root),
            ])
            out.replace(iso_path())
        meta_path().write_text(json.dumps({
            "server": settings.public_url,
            "bootenv_stamp": stamp,
            "size_bytes": iso_path().stat().st_size,
            "built_at": datetime.now(UTC).isoformat(),
        }))
        _state["error"] = ""
    except Exception as e:  # shown on the Settings page
        _state["error"] = str(e)
    finally:
        _state["building"] = False


def start_build() -> bool:
    """Start a background build. False if one is already running."""
    with _lock:
        if _state["building"]:
            return False
        _state["building"], _state["error"] = True, ""
    threading.Thread(target=build, daemon=True).start()
    return True
