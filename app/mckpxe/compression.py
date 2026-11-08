"""Recompressing disk (block) images on the server.

Machines capture at zstd level 3, which keeps up with the network. Here the
server recompresses the finished files at a higher level in the background.
zstd decompresses about as fast at any level, so a smaller image deploys just
as quickly and sends less over the network. The cost is server CPU time while
compressing.

One image at a time, at low CPU priority. Each partition file is written to a
temporary file, checked, and swapped in only if it's smaller, so the image can
still be deployed while this runs (a deploy that already has a file open keeps
reading the old one).

WIM images keep their LZX compression and aren't touched.
"""
import logging
import os
import queue
import subprocess
import threading
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .images import dir_size, image_dir
from .models import Image, ImageCompression, ServerSetting, utcnow

log = logging.getLogger("uvicorn.error")

CAPTURE_LEVEL = 3  # what the agent captures at
LEVELS = {9: "Balanced", 15: "Small", 19: "Smallest"}
SETTING_KEY = "compression"
TMP_PREFIX = ".recompress-"
CHUNK = 4 << 20

_queue: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


# --------------------------------------------------------------------------- settings

def get_settings(db: Session) -> dict:
    """{"auto_level": int | None}: recompress new disk images to this level, or not at all."""
    row = db.get(ServerSetting, SETTING_KEY)
    level = row.value.get("auto_level") if row and isinstance(row.value, dict) else None
    return {"auto_level": level if level in LEVELS else None}


def put_settings(db: Session, data: dict) -> dict:
    level = data.get("auto_level")
    if level is not None and level not in LEVELS:
        raise HTTPException(400, f"auto_level must be one of {sorted(LEVELS)} or null")
    row = db.get(ServerSetting, SETTING_KEY)
    if row:
        row.value = {"auto_level": level}
    else:
        db.add(ServerSetting(key=SETTING_KEY, value={"auto_level": level}))
    db.commit()
    return {"auto_level": level}


# --------------------------------------------------------------------------- state

def state_of(db: Session, image_id: int) -> ImageCompression:
    row = db.get(ImageCompression, image_id)
    if not row:
        row = ImageCompression(image_id=image_id, level=CAPTURE_LEVEL)
        db.add(row)
        db.flush()
    return row


def state_out(row: ImageCompression | None) -> dict:
    if not row:
        return {"level": CAPTURE_LEVEL, "target": None, "state": "idle", "progress": 0, "error": "",
                "saved_bytes": 0}
    return {"level": row.level, "target": row.target, "state": row.state, "progress": row.progress,
            "error": row.error, "saved_bytes": row.saved_bytes}


def compressible(image: Image) -> bool:
    return image.kind == "block" and image.status == "ready"


def request(db: Session, image: Image, level: int) -> ImageCompression:
    """Queue an image for recompression at this level."""
    if level not in LEVELS:
        raise HTTPException(400, f"level must be one of {sorted(LEVELS)}")
    if not compressible(image):
        raise HTTPException(400, "Only finished disk images can be compressed (WIMs are already compressed)")
    row = state_of(db, image.id)
    if row.state in ("queued", "running"):
        raise HTTPException(409, "This image is already being compressed")
    if row.level >= level:
        raise HTTPException(400, f"This image is already at level {row.level}")
    row.target, row.state, row.progress, row.error = level, "queued", 0, ""
    row.updated_at = utcnow()
    db.commit()
    _enqueue(image.id)
    return row


def after_capture(db: Session, image: Image) -> None:
    """A disk image just finished capturing or uploading: compress it if Settings say so."""
    level = get_settings(db)["auto_level"]
    if level and compressible(image):
        row = state_of(db, image.id)
        row.level = CAPTURE_LEVEL
        db.commit()
        request(db, image, level)


def resume() -> None:
    """At startup: clear half-written files and requeue anything interrupted."""
    with SessionLocal() as db:
        rows = db.scalars(select(ImageCompression).where(ImageCompression.state.in_(("queued", "running")))).all()
        for row in rows:
            for tmp in image_dir(row.image_id).glob(TMP_PREFIX + "*"):
                tmp.unlink(missing_ok=True)
            row.state, row.progress = "queued", 0
        db.commit()
        for row in rows:
            _enqueue(row.image_id)


# --------------------------------------------------------------------------- worker

def _enqueue(image_id: int) -> None:
    global _worker
    _queue.put(image_id)
    with _lock:
        if not _worker or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="recompress")
            _worker.start()


def _work() -> None:
    while True:
        try:
            image_id = _queue.get(timeout=5)
        except queue.Empty:
            return
        try:
            run(image_id)
        except Exception:  # keep the worker alive for the next image
            log.exception("Recompressing image %s failed", image_id)


def _nice():
    os.nice(10)


def recompress_file(src: Path, level: int, on_progress=lambda done, total: None) -> int:
    """Recompress one .zst file in place at `level`. Returns bytes saved (0 if not smaller)."""
    tmp = src.with_name(TMP_PREFIX + src.name)
    total = src.stat().st_size
    dec = subprocess.Popen(["zstd", "-dcq"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, preexec_fn=_nice)
    comp = subprocess.Popen(["zstd", "-q", "-T0", f"-{level}", "-f", "-o", str(tmp)], stdin=dec.stdout,
                            stderr=subprocess.PIPE, preexec_fn=_nice)
    dec.stdout.close()  # comp owns the read end now
    done = 0
    try:
        with open(src, "rb") as f:
            while chunk := f.read(CHUNK):
                dec.stdin.write(chunk)
                done += len(chunk)
                on_progress(done, total)
        dec.stdin.close()
        if dec.wait() != 0:
            raise RuntimeError(f"Couldn't read {src.name}: {dec.stderr.read().decode().strip()}")
        if comp.wait() != 0:
            raise RuntimeError(f"Couldn't compress {src.name}: {comp.stderr.read().decode().strip()}")
        check = subprocess.run(["zstd", "-tq", str(tmp)], capture_output=True, text=True, preexec_fn=_nice)
        if check.returncode != 0:
            raise RuntimeError(f"The recompressed {src.name} failed its check: {check.stderr.strip()}")
        saved = total - tmp.stat().st_size
        if saved <= 0:
            tmp.unlink()
            return 0
        os.replace(tmp, src)
        return saved
    except BaseException:
        for p in (dec, comp):
            if p.poll() is None:
                p.kill()
        tmp.unlink(missing_ok=True)
        raise


def run(image_id: int) -> None:
    """Recompress every partition file of one image to its target level."""
    with SessionLocal() as db:
        image = db.get(Image, image_id)
        row = db.get(ImageCompression, image_id)
        if not image or not row or row.state != "queued" or not row.target:
            return
        files = sorted(p for p in image_dir(image_id).glob("*.zst") if p.is_file())
        total = sum(p.stat().st_size for p in files) or 1
        row.state, row.progress, row.error = "running", 0, ""
        db.commit()
        level, before, saved, done = row.target, image.size_bytes, 0, 0
        last = [0.0]

        def progress(file_done, _file_total):
            pct = round((done + file_done) * 100 / total, 1)
            if pct - last[0] >= 1:
                last[0] = row.progress = pct
                row.updated_at = utcnow()
                db.commit()

        try:
            for f in files:
                size = f.stat().st_size
                saved += recompress_file(f, level, progress)
                done += size
                image.size_bytes = dir_size(image_dir(image_id))
                db.commit()
            row.level, row.target, row.state, row.progress = level, None, "idle", 100
            row.saved_bytes = max(saved, before - image.size_bytes, 0)
        except Exception as e:
            if not image_dir(image_id).exists():
                return  # the image was deleted meanwhile
            row.state, row.target, row.error = "error", None, str(e)[:1000]
            image.size_bytes = dir_size(image_dir(image_id))
        row.updated_at = utcnow()
        db.commit()
