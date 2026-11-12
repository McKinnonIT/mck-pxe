import io
import tarfile

from mckpxe.db import SessionLocal
from mckpxe.drivers import files_dir
from mckpxe.models import Driver, DriverPack

MAC = "aa:bb:cc:dd:ee:01"
HW = {
    "mac": MAC, "ip": "10.0.0.50", "manufacturer": "LENOVO", "model": "21K5", "sku": "ThinkPad E14 Gen 6",
    "serial": "PF123", "cpu": "Intel", "ram_mb": 16000, "boot_mode": "uefi", "secure_boot": True,
    "disks": [{"path": "/dev/nvme0n1", "size": 512110190592, "model": "SSD"}],
    "hardware_ids": ["PCI\\VEN_8086&DEV_15F3", "PCI\\VEN_10EC&DEV_8168"],
}


def run_agent_task(client, ok=True, result=None, upload=None):
    task = client.get(f"/api/agent/next?mac={MAC}").json()
    assert task, "expected a queued task"
    for name, body in (upload or {}).items():
        assert client.put(f"/api/agent/tasks/{task['id']}/upload/{name}", content=body).status_code == 200
    r = client.post(f"/api/agent/tasks/{task['id']}/progress", json={"progress": 50, "message": "half", "log": ["hi"]})
    assert r.json() == {"cancelled": False}
    client.post(f"/api/agent/tasks/{task['id']}/complete", json={"ok": ok, "message": "done", **(result or {})})
    return task


def test_capture_then_deploy_with_drivers(client, data_dir):
    host_id = client.post("/api/agent/register", json=HW).json()["host_id"]

    # Idle machine gets a menu defaulting to the imaging environment, the first entry
    grub = client.get(f"/api/boot/grub/{MAC}.cfg").text
    assert "set default=0" in grub and "set timeout=5" in grub
    # Local disk is the last of the six entries, after the ISO library and netboot.xyz
    entries = [line for line in grub.splitlines() if line.startswith("menuentry")]
    assert len(entries) == 6 and entries[5] == 'menuentry "Boot from local disk" {'
    assert entries[3].startswith('menuentry "ISO library') and "snponly.efi" in grub
    assert entries[4].startswith('menuentry "netboot.xyz') and "chainloader (http," in grub
    ipxe = client.get(f"/api/boot/ipxe/{MAC}").text
    items = [line.split()[1] for line in ipxe.splitlines() if line.startswith("item ")]
    assert items == ["imaging", "safe", "text", "isos", "netboot", "local"]
    assert "--default imaging --timeout 5000" in ipxe

    # The Settings page can switch the default to the local disk and change the countdown
    r = client.put("/api/settings/boot-menu", json={"default": "local", "timeout": 10})
    assert r.json() == {"default": "local", "timeout": 10}
    grub = client.get(f"/api/boot/grub/{MAC}.cfg").text
    assert "set default=5" in grub and "set timeout=10" in grub
    assert "--default local --timeout 10000" in client.get(f"/api/boot/ipxe/{MAC}").text
    assert client.put("/api/settings/boot-menu", json={"default": "usb"}).status_code == 400
    assert client.put("/api/settings/boot-menu", json={"timeout": -1}).status_code == 400
    assert client.put("/api/settings/boot-menu", json={"timeout": "soon"}).status_code == 400

    # Admin queues a capture; machine now boots straight into imaging
    r = client.post("/api/tasks", json={"host_id": host_id, "type": "capture", "kind": "block",
                                        "name": "E14 golden", "disk": "/dev/nvme0n1"})
    assert r.status_code == 200, r.text
    grub = client.get(f"/api/boot/grub/{MAC}.cfg").text
    assert "set default=0" in grub and "set timeout=0" in grub  # the imaging entry, straight away
    assert "fetch=http://10.0.0.5/boot/filesystem.squashfs" in grub
    assert "ethdevice-timeout=60" in grub  # time for switch ports with spanning tree
    assert "goto ${target}" in client.get(f"/api/boot/ipxe/{MAC}").text

    # Second task for the same machine is refused
    assert client.post("/api/tasks", json={"host_id": host_id, "type": "capture", "name": "x",
                                           "disk": "/dev/nvme0n1"}).status_code == 409

    meta = {"table": "gpt", "sector_size": 512, "required_bytes": 1, "partitions": []}
    task = run_agent_task(client, result={"os_family": "windows", "meta": meta},
                          upload={"table.sfdisk": b"label: gpt\n", "p1.pc.zst": b"x" * 1000})
    image = client.get(f"/api/images/{task['image']['id']}").json()
    assert image["status"] == "ready" and image["os_family"] == "windows"
    assert image["size_bytes"] == 1011
    assert (data_dir / "images" / str(image["id"]) / "p1.pc.zst").exists()

    # Path traversal in upload names is rejected
    client.post("/api/tasks", json={"host_id": host_id, "type": "capture", "name": "y", "disk": "/dev/nvme0n1"})
    t = client.get(f"/api/agent/next?mac={MAC}").json()
    assert client.put(f"/api/agent/tasks/{t['id']}/upload/..%2Fevil", content=b"x").status_code in (400, 404)
    client.post(f"/api/agent/tasks/{t['id']}/complete", json={"ok": False, "message": "cancelled"})

    # Driver library: one generic pack (match by hardware ID), one model pack, one other model
    with SessionLocal() as db:
        generic = DriverPack(name="Intel LAN", status="ready")
        generic.drivers = [
            Driver(inf_path="lan/e1.inf", directory="lan", hardware_ids=["PCI\\VEN_8086&DEV_15F3"]),
            Driver(inf_path="wifi/w.inf", directory="wifi", hardware_ids=["PCI\\VEN_8086&DEV_A0F0"]),
        ]
        model = DriverPack(name="E14 Gen 6 pack", manufacturer="Lenovo", model_match="E14 Gen 6", status="ready")
        model.drivers = [Driver(inf_path="audio/a.inf", directory="audio", hardware_ids=[])]
        other = DriverPack(name="Dell pack", manufacturer="Dell", model_match="Latitude", status="ready")
        other.drivers = [Driver(inf_path="x/x.inf", directory="x", hardware_ids=["PCI\\VEN_8086&DEV_15F3"])]
        db.add_all([generic, model, other])
        db.commit()
        gid = generic.id
    for d in ("lan", "wifi"):
        (files_dir(gid) / d).mkdir(parents=True, exist_ok=True)
        (files_dir(gid) / d / f"{d}.inf").write_text("[Version]")

    preview = client.get(f"/api/hosts/{host_id}/drivers").json()
    assert {p["pack"]["name"]: [d["inf_path"] for d in p["drivers"]] for p in preview} == {
        "Intel LAN": ["lan/e1.inf"], "E14 Gen 6 pack": ["audio/a.inf"],
    }
    models = client.get("/api/models").json()
    e14 = next(m for m in models if m["model"] == "21K5")
    assert e14["packs"] == [{"id": model.id, "name": "E14 Gen 6 pack"}]

    # Deploy the captured image; the agent gets file URLs and a driver plan
    client.patch(f"/api/images/{image['id']}", json={"unattend": "<unattend/>"})
    r = client.post("/api/tasks", json={"host_id": host_id, "type": "deploy", "image_id": image["id"],
                                        "disk": "/dev/nvme0n1"})
    assert r.status_code == 200, r.text
    task = client.get(f"/api/agent/next?mac={MAC}").json()
    assert task["files_url"] == f"http://10.0.0.5/files/images/{image['id']}/"
    assert task["unattend_url"].endswith(f"/images/{image['id']}/unattend.xml")
    assert client.get(task["unattend_url"].replace("http://10.0.0.5", "")).text == "<unattend/>"
    lan = next(d for d in task["drivers"] if d["name"] == "Intel LAN")
    tar = client.get(lan["url"].replace("http://10.0.0.5", "")).content
    names = tarfile.open(fileobj=io.BytesIO(tar)).getnames()
    assert "lan/lan.inf" in names and not any(n.startswith("wifi") for n in names)

    # Cancel while running: agent is told on its next progress report
    client.post(f"/api/tasks/{task['id']}/cancel")
    r = client.post(f"/api/agent/tasks/{task['id']}/progress", json={"progress": 10})
    assert r.json() == {"cancelled": True}
    client.post(f"/api/agent/tasks/{task['id']}/complete", json={"ok": False, "message": "cancelled"})
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "cancelled"


def test_wim_deploy_needs_bcd(client):
    with SessionLocal() as db:
        from mckpxe.models import Image
        img = Image(name="Win11", kind="wim", os_family="windows", status="ready",
                    meta={"indexes": [{"index": 1, "name": "Education"}, {"index": 3, "name": "Pro"}]})
        db.add(img)
        db.commit()
        image_id = img.id
    host_id = client.post("/api/agent/register", json=HW).json()["host_id"]
    body = {"host_id": host_id, "type": "deploy", "image_id": image_id, "disk": "/dev/nvme0n1", "wim_index": 3}
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 400 and "BCD" in r.json()["detail"]
    assert client.put("/api/settings/bcd", content=b"nope").status_code == 400
    assert client.put("/api/settings/bcd", content=b"regf" + b"\0" * 100).status_code == 200
    assert client.post("/api/tasks", json={**body, "wim_index": 2}).status_code == 400
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 200, r.text
    task = client.get(f"/api/agent/next?mac={MAC}").json()
    assert task["params"]["wim_index"] == 3 and task["bcd_url"] == "http://10.0.0.5/files/system/BCD"
