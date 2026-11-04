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
