"""USB stick storage: partition planning and folder layout in the agent, and
the server endpoints the console uses to copy images to and from the stick."""
import importlib.machinery
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
from conftest import console_headers

from mckpxe.db import SessionLocal
from mckpxe.drivers import files_dir
from mckpxe.images import image_dir
from mckpxe.models import Driver, DriverPack, Image

AGENT = Path(__file__).resolve().parents[1] / "bootenv" / "agent" / "mck-agent"
MAC = "aa:bb:cc:dd:ee:99"
GIB = 1 << 30


def load_agent():
    loader = importlib.machinery.SourceFileLoader("mck_agent", str(AGENT))
    spec = importlib.util.spec_from_loader("mck_agent", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


agent = load_agent()


def stick_mbr(entries, gpt=False):
    """First 1024 bytes of a stick with the given (type, start, count) MBR entries."""
    mbr = bytearray(1024)
    for i, (ptype, start, count) in enumerate(entries):
        mbr[446 + 16 * i: 462 + 16 * i] = agent.mbr_entry(start, count, ptype)
    mbr[510:512] = b"\x55\xaa"
    if gpt:
        mbr[512:520] = b"EFI PART"
    return bytes(mbr)


# --------------------------------------------------------------------------- partition planning

ISO = [(0x17, 0, 580_000), (0xEF, 580_000, 16_384)]  # like the ISO the server builds


def test_data_partition_goes_after_the_iso_aligned():
    slot, start, count = agent.plan_data_partition(stick_mbr(ISO), total_sectors=32 * GIB // 512)
    assert slot == 2
    assert start == 598_016 and start % 2048 == 0 and start >= 580_000 + 16_384
    assert start + count == 32 * GIB // 512


def test_written_entry_round_trips():
    mbr = bytearray(stick_mbr(ISO))
    slot, start, count = agent.plan_data_partition(bytes(mbr), 8 * GIB // 512)
    mbr[446 + 16 * slot: 462 + 16 * slot] = agent.mbr_entry(start, count)
    # Planning again sees the new partition and no space left
    with pytest.raises(RuntimeError, match="Not enough free space"):
        agent.plan_data_partition(bytes(mbr), 8 * GIB // 512)
    assert mbr[446 + 16 * slot + 4] == 0x07  # exFAT/NTFS type


@pytest.mark.parametrize("mbr, reason", [
    (stick_mbr(ISO, gpt=True), "older mck-pxe ISO"),
    (stick_mbr([(0xEE, 1, 100)]), "uses GPT"),
    (bytes(1024), "no MBR"),
    (stick_mbr([(0x17, 0, 100), (0xEF, 100, 10), (0x07, 2048, 10), (0x83, 4096, 10)]), "no free partition slot"),
])
def test_refuses_sticks_it_cant_safely_change(mbr, reason):
    with pytest.raises(RuntimeError, match=reason):
        agent.plan_data_partition(mbr, 32 * GIB // 512)


def test_small_stick_is_refused():
    with pytest.raises(RuntimeError, match="32 GB"):
        agent.plan_data_partition(stick_mbr(ISO), total_sectors=600_000 + (GIB // 2) // 512)


# --------------------------------------------------------------------------- stick folder layout

def test_store_lists_images_and_finds_model_drivers(tmp_path):
    hw = {"manufacturer": "LENOVO", "model": "21K5"}
    img = tmp_path / "images" / "e14-golden"
    (img / "drivers" / agent.model_key(hw)).mkdir(parents=True)
    (img / "image.json").write_text(json.dumps({"name": "E14", "kind": "block", "os_family": "windows", "meta": {}}))
    (img / "p3.pc.zst").write_bytes(b"x")
    (img / ".p4.pc.zst.part").write_bytes(b"half")  # interrupted copy: ignored
    drv = img / "drivers" / agent.model_key(hw)
    (drv / "1-intel.tar").write_bytes(b"tar")
    (drv / "index.json").write_text(json.dumps([
        {"name": "Intel", "slug": "1-intel", "count": 2, "file": "1-intel.tar"},
        {"name": "Gone", "slug": "2-gone", "count": 1, "file": "2-gone.tar"},  # file missing: skipped
    ]))
    (tmp_path / "images" / "broken").mkdir()  # no image.json: skipped

    images = agent.store_images(str(tmp_path))
    assert [i["name"] for i in images] == ["E14"]
    assert agent.image_files(images[0]) == ["p3.pc.zst"]
    drivers = agent.store_drivers(images[0], hw)
    assert [(d["name"], d["path"]) for d in drivers] == [("Intel", str(drv / "1-intel.tar"))]
    assert agent.store_drivers(images[0], {"manufacturer": "Dell Inc.", "model": "OptiPlex 7010"}) == []


def test_tasks_read_and_write_the_stick_or_the_server():
    local = {"local_dir": "/mnt/mckpxe-data/mck-pxe/images/x"}
    assert agent.upload_cmd(local, "p1.pc.zst") == "cat > /mnt/mckpxe-data/mck-pxe/images/x/p1.pc.zst"
    assert agent.source_cmd(local, "table.sfdisk") == "cat /mnt/mckpxe-data/mck-pxe/images/x/table.sfdisk"
    remote = {"upload_url": "http://s/api/agent/tasks/1/upload", "files_url": "http://s/files/images/2/"}
    assert agent.upload_cmd(remote, "a").endswith("-T - http://s/api/agent/tasks/1/upload/a")
    assert agent.source_cmd(remote, "a") == "curl -sSf http://s/files/images/2/a"
    assert agent.resource_cmd({"bcd_path": "/x/BCD"}, "bcd") == "cat /x/BCD"
    assert agent.ref_cmd({"url": "http://s/d.tar"}) == "curl -sSf http://s/d.tar"
    assert not agent.has_resource({"unattend_url": None}, "unattend")


# --------------------------------------------------------------------------- server endpoints

@pytest.fixture()
def host(client):
    hw = {"mac": MAC, "manufacturer": "LENOVO", "model": "21K5", "hardware_ids": ["PCI\\VEN_8086&DEV_550A"],
          "disks": []}
    return client.post("/api/agent/register", json=hw).json()["host_id"]


def test_manifest_lists_files_and_this_machines_drivers(client, host):
    with SessionLocal() as db:
        img = Image(name="Win11 E14", kind="block", os_family="windows", status="ready", unattend="<u/>",
                    meta={"table": "gpt"})
        pack = DriverPack(name="LAN library", status="ready")
        pack.drivers = [Driver(inf_path="lan/e.inf", directory="lan", hardware_ids=["PCI\\VEN_8086&DEV_550A"]),
                        Driver(inf_path="wifi/w.inf", directory="wifi", hardware_ids=["PCI\\VEN_8086&DEV_FFFF"])]
        db.add_all([img, pack])
        db.commit()
        image_id, pack_id = img.id, pack.id
    image_dir(image_id).mkdir(parents=True)
    (image_dir(image_id) / "table.sfdisk").write_text("label: gpt\n")
    (image_dir(image_id) / ".half.part").write_text("x")
    for d in ("lan", "wifi"):
        (files_dir(pack_id) / d).mkdir(parents=True)
        (files_dir(pack_id) / d / "x.inf").write_text("[Version]")

    m = client.get(f"/api/agent/images/{image_id}/manifest?mac={MAC}").json()
    assert m["image"]["name"] == "Win11 E14" and m["unattend"] == "<u/>"
    assert m["files"] == [{"name": "table.sfdisk", "size": 11,
                           "url": f"http://10.0.0.5/files/images/{image_id}/table.sfdisk"}]
    lan = next(d for d in m["drivers"] if d["name"] == "LAN library")
    assert lan["count"] == 1

    tar = client.get(lan["url"].replace("http://10.0.0.5", "")).content
    names = tarfile.open(fileobj=io.BytesIO(tar)).getnames()
    # (macOS tar adds ._ metadata entries when tests run on a Mac; GNU tar on the server doesn't)
    assert [n for n in names if not Path(n).name.startswith("._")] == ["lan", "lan/x.inf"]
    # Another machine's MAC that isn't registered gets nothing
    assert client.get(f"/api/agent/drivers/{pack_id}.tar?mac=aa:aa:aa:aa:aa:aa").status_code == 404


def test_import_from_usb(client, host):
    h = console_headers(client, MAC)
    r = client.post("/api/agent/images", headers=h, json={"mac": MAC, "name": "Captured offline", "kind": "block",
                                                          "os_family": "windows", "meta": {"table": "dos"}})
    image_id = r.json()["id"]
    assert client.get("/api/images").json()[0]["status"] == "uploading"
    up = f"/api/agent/images/{image_id}/upload"
    assert client.put(f"{up}/p1.pc.zst", headers=h, content=b"abc").json() == {"bytes": 3}
    assert client.put(f"{up}/..%2Fx", headers=h, content=b"a").status_code in (400, 404)
    client.post(f"/api/agent/images/{image_id}/complete", headers=h, json={"ok": True})

    image = client.get(f"/api/images/{image_id}").json()
    assert image["status"] == "ready" and image["size_bytes"] == 3
    assert image["source"].startswith("USB via") and image["meta"] == {"table": "dos"}
    assert image["created_by"].startswith("admin at ")
    # Finished imports can't be written to again
    assert client.put(f"{up}/p2.pc.zst", headers=h, content=b"x").status_code == 409


def test_failed_import_is_cleaned_up(client, host):
    h = console_headers(client, MAC)
    image_id = client.post("/api/agent/images", headers=h, json={"mac": MAC, "name": "x", "kind": "wim"}).json()["id"]
    client.put(f"/api/agent/images/{image_id}/upload/image.wim", headers=h, content=b"part")
    client.post(f"/api/agent/images/{image_id}/complete", headers=h, json={"ok": False, "message": "stick pulled out"})
    image = client.get(f"/api/images/{image_id}").json()
    assert image["status"] == "error" and image["error"] == "stick pulled out"
    assert not image_dir(image_id).exists()


def test_import_needs_someone_signed_in_at_the_machine(client, host):
    body = {"mac": MAC, "name": "x", "kind": "block"}
    assert client.post("/api/agent/images", json=body).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.post("/api/agent/images", headers=bad, json=body).status_code == 401
    image_id = client.post("/api/agent/images", headers=console_headers(client, MAC), json=body).json()["id"]
    # Uploading into it needs the token too
    assert client.put(f"/api/agent/images/{image_id}/upload/x.zst", content=b"x").status_code == 401
