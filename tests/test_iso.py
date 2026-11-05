import dataclasses

from mckpxe import iso


def test_status_lists_whats_missing(client):
    s = client.get("/api/iso").json()
    assert s["available"] is False and s["built"] is None
    assert "imaging environment: vmlinuz" in s["missing"]
    assert any(m.startswith("boot loader:") for m in s["missing"])
    assert s["server"] == "http://10.0.0.5"


def test_build_refused_until_ready(client):
    r = client.post("/api/iso/build")
    assert r.status_code == 400 and "Missing" in r.json()["detail"]
    assert client.get("/api/iso/download").status_code == 404


def test_boot_configs_point_at_server_and_load_into_ram():
    for cfg in (iso.grub_cfg(), iso.isolinux_cfg()):
        assert "/live/vmlinuz" in cfg and "/live/initrd.img" in cfg
        assert "boot=live toram mckpxe.server=http://10.0.0.5" in cfg
        assert "fetch=" not in cfg  # boots from the stick, not the network


def test_status_flags_stale_iso(client, data_dir, monkeypatch):
    bootenv = data_dir / "bootenv"
    bootenv.mkdir(parents=True, exist_ok=True)
    for f in iso.BOOTENV_FILES:
        (bootenv / f).write_bytes(b"x")
    iso.iso_path().write_bytes(b"iso")
    iso.meta_path().write_text('{"server": "http://10.0.0.5", "bootenv_stamp": 0, "size_bytes": 3, "built_at": "x"}')
    s = client.get("/api/iso").json()
    assert s["built"]["size_bytes"] == 3 and s["stale"] is True  # imaging environment changed since
    assert client.get("/api/iso/download").content == b"iso"

    monkeypatch.setattr(iso, "settings", dataclasses.replace(iso.settings, server_ip="10.0.0.9"))
    assert iso.status()["stale"] is True
