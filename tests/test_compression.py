"""Recompressing disk images on the server (runs the real zstd)."""
import os
import shutil
import subprocess
import time

import pytest
from conftest import console_headers

from mckpxe import compression
from mckpxe.db import SessionLocal
from mckpxe.images import dir_size, image_dir
from mckpxe.models import Image

pytestmark = pytest.mark.skipif(not shutil.which("zstd"), reason="needs zstd")
MAC = "aa:bb:cc:dd:ee:33"


def sample(size=3 << 20) -> bytes:
    """Compressible like a disk: repeated structure with some variety."""
    words = [f"block {i:06d} file data {i * 7919 % 1000:03d} " for i in range(4000)]
    return ("".join(words) * (size // 150_000 + 1)).encode()[:size]


def zst(data: bytes, level: int) -> bytes:
    return subprocess.run(["zstd", f"-{level}", "-q", "-c"], input=data, capture_output=True, check=True).stdout


def unzst(path) -> bytes:
    return subprocess.run(["zstd", "-dcq", str(path)], capture_output=True, check=True).stdout


def make_image(kind="block", files=None) -> int:
    with SessionLocal() as db:
        img = Image(name=f"compress-{kind}", kind=kind, os_family="windows", status="ready", meta={})
        db.add(img)
        db.commit()
        image_id = img.id
    image_dir(image_id).mkdir(parents=True)
    for name, body in (files or {}).items():
        (image_dir(image_id) / name).write_bytes(body)
    return image_id


def wait_idle(client, image_id, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        c = client.get(f"/api/images/{image_id}").json()["compression"]
        if c["state"] in ("idle", "error"):
            return c
        time.sleep(0.1)
    raise AssertionError("compression didn't finish")


def test_recompress_file_is_smaller_and_identical(tmp_path):
    data = sample()
    f = tmp_path / "p1.pc.zst"
    f.write_bytes(zst(data, 1))
    before = f.stat().st_size
    seen = []
    saved = compression.recompress_file(f, 19, lambda done, total: seen.append(done))
    assert saved > 0 and f.stat().st_size == before - saved
    assert unzst(f) == data
    assert seen[-1] == before
    assert not list(tmp_path.glob(compression.TMP_PREFIX + "*"))


def test_file_that_doesnt_shrink_is_left_alone(tmp_path):
    f = tmp_path / "p1.raw.zst"
    f.write_bytes(zst(os.urandom(1 << 20), 19))
    before = f.read_bytes()
    assert compression.recompress_file(f, 9) == 0
    assert f.read_bytes() == before


def test_broken_file_fails_without_touching_it(tmp_path):
    f = tmp_path / "p1.pc.zst"
    f.write_bytes(b"not zstd at all")
    with pytest.raises(RuntimeError, match="Couldn't read"):
        compression.recompress_file(f, 9)
    assert f.read_bytes() == b"not zstd at all"
    assert not list(tmp_path.glob(compression.TMP_PREFIX + "*"))


def test_compress_button_end_to_end(client):
    data = sample()
    files = {"table.sfdisk": b"label: gpt\n", "p1.pc.zst": zst(data, 3), "p2.raw.zst": zst(data[:500_000], 3)}
    image_id = make_image(files=files)
    before = client.get(f"/api/images/{image_id}").json()
    assert before["compression"] == {"level": 3, "target": None, "state": "idle", "progress": 0, "error": "",
                                     "saved_bytes": 0}
    r = client.post(f"/api/images/{image_id}/compress", json={"level": 19})
    assert r.status_code == 200, r.text
    c = wait_idle(client, image_id)
    assert c["state"] == "idle" and c["level"] == 19 and c["saved_bytes"] > 0, c
    assert unzst(image_dir(image_id) / "p1.pc.zst") == data
    assert (image_dir(image_id) / "table.sfdisk").read_bytes() == b"label: gpt\n"
    # The image's size is what's on disk now
    assert client.get(f"/api/images/{image_id}").json()["size_bytes"] == dir_size(image_dir(image_id))
    # Already there, or lower: nothing to do
    assert client.post(f"/api/images/{image_id}/compress", json={"level": 15}).status_code == 400
    assert client.post(f"/api/images/{image_id}/compress", json={"level": 12}).status_code == 400


def test_only_finished_disk_images(client):
    wim = make_image(kind="wim", files={"image.wim": b"x"})
    assert client.get(f"/api/images/{wim}").json()["compression"] is None
    assert client.post(f"/api/images/{wim}/compress", json={"level": 19}).status_code == 400


def test_settings_compress_new_captures(client):
    assert client.get("/api/settings/compression").json()["auto_level"] is None
    assert client.put("/api/settings/compression", json={"auto_level": 4}).status_code == 400
    assert client.put("/api/settings/compression", json={"auto_level": 9}).json()["auto_level"] == 9
    try:
        client.post("/api/agent/register", json={"mac": MAC, "model": "T"})
        h = console_headers(client, MAC)
        body = {"mac": MAC, "name": "auto", "kind": "block"}
        image_id = client.post("/api/agent/images", headers=h, json=body).json()["id"]
        client.put(f"/api/agent/images/{image_id}/upload/p1.pc.zst", headers=h, content=zst(sample(), 3))
        client.post(f"/api/agent/images/{image_id}/complete", headers=h, json={"ok": True})
        c = wait_idle(client, image_id)
        assert c["level"] == 9 and c["saved_bytes"] > 0
    finally:
        client.put("/api/settings/compression", json={"auto_level": None})
