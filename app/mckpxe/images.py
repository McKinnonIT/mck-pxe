"""Image storage on disk, and processing of WIMs uploaded through the web UI."""
import re
import shutil
import subprocess
from pathlib import Path

from .config import settings
from .db import SessionLocal
from .models import Image


def image_dir(image_id: int) -> Path:
    return settings.images_dir / str(image_id)


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def remove_image_files(image_id: int) -> None:
    shutil.rmtree(image_dir(image_id), ignore_errors=True)


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def parse_wiminfo(text: str) -> list[dict]:
    """Parse `wimlib-imagex info` output into a list of indexes."""
    indexes, current = [], None
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        if key == "Index":
            current = {"index": int(value), "name": "", "description": "", "bytes": 0}
            indexes.append(current)
        elif current is not None:
            if key == "Name":
                current["name"] = value
            elif key == "Description":
                current["description"] = value
            elif key == "Total Bytes":
                current["bytes"] = int(value.replace(",", "") or 0)
            elif key == "Edition ID":
                current["edition"] = value
    return indexes


def extract_from_iso(src: Path) -> None:
    """If src is Windows install media (an ISO), replace it with the install.wim/esd inside."""
    with open(src, "rb") as f:
        if f.read(8) == b"MSWIM\0\0\0":
            return
    tmp = src.parent / "iso-extract"
    try:
        # Windows media hides its files from the ISO9660 layer (just a README), so read UDF first
        for fs in ("-tudf", "-tiso"):
            shutil.rmtree(tmp, ignore_errors=True)
            subprocess.run(["7z", "e", "-y", fs, f"-o{tmp}", str(src), "sources/install.wim", "sources/install.esd"],
                           capture_output=True, text=True)
            found = [p for p in tmp.glob("install.*") if p.suffix.lower() in (".wim", ".esd")] if tmp.exists() else []
            if found:
                found[0].replace(src)
                return
        raise RuntimeError("Not a WIM, ESD or Windows ISO (no sources/install.wim or install.esd inside)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process_wim(image_id: int) -> None:
    """Background job: convert an uploaded WIM/ESD into a pipable WIM.

    A pipable WIM can be streamed straight from HTTP into wimlib on the client,
    so deploys never have to stage the whole file in RAM or on disk.
    """
    with SessionLocal() as db:
        image = db.get(Image, image_id)
        if not image:
            return
        image.status = "processing"
        db.commit()
        src = image_dir(image_id) / "upload.wim"
        dst = image_dir(image_id) / "image.wim"
        try:
            extract_from_iso(src)
            info = subprocess.run(["wimlib-imagex", "info", str(src)], capture_output=True, text=True)
            if info.returncode != 0:
                raise RuntimeError(info.stderr.strip() or "Not a valid WIM/ESD file")
            indexes = parse_wiminfo(info.stdout)
            export = subprocess.run(
                ["wimlib-imagex", "export", str(src), "all", str(dst), "--pipable", "--compress=LZX"],
                capture_output=True, text=True,
            )
            if export.returncode != 0:
                raise RuntimeError(export.stderr.strip())
            src.unlink()
            image.meta = {"pipable": True, "indexes": indexes}
            image.size_bytes = dir_size(image_dir(image_id))
            image.status, image.error = "ready", ""
        except Exception as e:  # surface any failure in the admin UI
            image.status, image.error = "error", str(e)
        db.commit()
