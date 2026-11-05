"""Storage mode detection (NVMe, AHCI, Intel VMD, SATA RAID mode, RST RAID volumes)
and the check that stops Windows deploys that won't boot."""
import json
import os

import pytest
from test_usb import load_agent

agent = load_agent()


def make_sysfs(root):
    """A fake /sys with one machine of each kind of storage."""
    def mk(path, **files):
        os.makedirs(root / path, exist_ok=True)
        for name, value in files.items():
            (root / path / name).write_text(value)

    def link(path, target):
        os.makedirs((root / path).parent, exist_ok=True)
        os.symlink(root / target, root / path)

    mk("bus/pci/drivers/vmd")
    mk("bus/pci/drivers/ahci")
    mk("bus/pci/drivers/nvme")

    # NVMe behind Intel VMD (00:0e.0 is the VMD controller)
    mk("devices/pci0000:00/0000:00:0e.0", **{"class": "0x010400"})
    link("devices/pci0000:00/0000:00:0e.0/driver", "bus/pci/drivers/vmd")
    mk("devices/pci0000:00/0000:00:0e.0/pci10000:e0/10000:e1:00.0/nvme/nvme0", **{"class": ""})
    link("block/nvme0n1/device", "devices/pci0000:00/0000:00:0e.0/pci10000:e0/10000:e1:00.0/nvme/nvme0")

    # Plain NVMe
    mk("devices/pci0000:00/0000:00:1d.0/0000:03:00.0/nvme/nvme1", **{"class": ""})
    mk("devices/pci0000:00/0000:00:1d.0/0000:03:00.0", **{"class": "0x010802"})
    link("block/nvme1n1/device", "devices/pci0000:00/0000:00:1d.0/0000:03:00.0/nvme/nvme1")

    # SATA disk on a controller in AHCI mode, and one in RAID mode
    mk("devices/pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0", **{"class": ""})
    mk("devices/pci0000:00/0000:00:17.0", **{"class": "0x010601"})
    link("block/sda/device", "devices/pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0")
    mk("devices/pci0000:01/0000:01:17.0/ata2/host1/target1:0:0/1:0:0:0", **{"class": ""})
    mk("devices/pci0000:01/0000:01:17.0", **{"class": "0x010400", "vendor": "0x8086"})
    link("devices/pci0000:01/0000:01:17.0/driver", "bus/pci/drivers/ahci")
    link("block/sdb/device", "devices/pci0000:01/0000:01:17.0/ata2/host1/target1:0:0/1:0:0:0")
    mk("devices/pci0000:01/0000:01:17.0/ata3/host2/target2:0:0/2:0:0:0", **{"class": ""})
    link("block/sdc/device", "devices/pci0000:01/0000:01:17.0/ata3/host2/target2:0:0/2:0:0:0")

    # An RST RAID1 volume (md126) in an IMSM container (md127) over sdb + sdc,
    # and an ordinary Linux md array that isn't RST
    mk("block/md127/md", metadata_version="external:imsm", level="container")
    mk("block/md126/md", metadata_version="external:/md127/0", level="raid1")
    mk("block/md126", size=str(500_000_000_000 // 512))
    for m in ("sdb", "sdc"):
        mk("block/md126/slaves")
        os.symlink(root / "block" / m, root / "block" / "md126" / "slaves" / m)
    mk("block/md0/md", metadata_version="1.2", level="raid1")

    # A non-Intel RAID card (e.g. LSI) also reports the RAID PCI class
    mk("devices/pci0000:02/0000:02:00.0/host3/target3:0:0/3:0:0:0", **{"class": ""})
    mk("devices/pci0000:02/0000:02:00.0", **{"class": "0x010400", "vendor": "0x1000"})
    link("block/sdd/device", "devices/pci0000:02/0000:02:00.0/host3/target3:0:0/3:0:0:0")
    return root


@pytest.fixture()
def sysfs(tmp_path):
    return str(make_sysfs(tmp_path))


def test_controller_detection(sysfs):
    assert agent.disk_controller("nvme0n1", sysfs) == "vmd"
    assert agent.disk_controller("nvme1n1", sysfs) == "nvme"
    assert agent.disk_controller("sda", sysfs) == "ahci"
    assert agent.disk_controller("sdb", sysfs) == "sata-raid-mode"
    assert agent.disk_controller("sdd", sysfs) == "other"


def test_rst_raid_volumes(sysfs):
    volumes = agent.rst_volumes(sysfs)
    assert volumes == [{"name": "md126", "level": "raid1", "members": ["sdb", "sdc"],
                        "size": 500_000_000_000 // 512 * 512, "boot_driver": "iaStorAC"}]


def test_member_disks_are_hidden_and_volume_listed(sysfs, monkeypatch):
    monkeypatch.setattr(agent, "SYSFS", sysfs)
    monkeypatch.setattr(agent, "boot_media_disks", lambda: set())
    lsblk = {"blockdevices": [
        {"name": n, "path": f"/dev/{n}", "size": 256e9, "model": "X", "serial": "", "tran": t, "type": "disk",
         "rm": False, "ro": False}
        for n, t in (("nvme0n1", "nvme"), ("sda", "sata"), ("sdb", "sata"), ("sdc", "sata"))]}
    monkeypatch.setattr(agent, "sh", lambda cmd, check=True: json.dumps(lsblk))
    disks = {d["path"]: d for d in agent.list_disks()}
    assert set(disks) == {"/dev/md126", "/dev/nvme0n1", "/dev/sda"}  # sdb/sdc only as the volume
    assert disks["/dev/md126"]["storage"] == "rst-raid" and disks["/dev/md126"]["raid_level"] == "raid1"
    assert disks["/dev/md126"]["members"] == ["/dev/sdb", "/dev/sdc"]
    assert disks["/dev/nvme0n1"]["boot_driver"] == "iaStorVD"
    assert disks["/dev/sda"]["boot_driver"] == "storahci"


VMD_DISK = {"path": "/dev/nvme0n1", "boot_driver": "iaStorVD"}
AHCI_DISK = {"path": "/dev/sda", "boot_driver": "storahci"}
NVME_DISK = {"path": "/dev/nvme1n1", "boot_driver": "stornvme"}


def windows(kind="block", boot_driver=None):
    meta = {"storage": {"boot_driver": boot_driver}} if boot_driver else {}
    return {"os_family": "windows", "kind": kind, "meta": meta}


@pytest.mark.parametrize("image, disk, blocked", [
    (windows(boot_driver="iaStorVD"), VMD_DISK, False),        # same machine type
    (windows(boot_driver="iaStorVD"), NVME_DISK, True),        # VMD image onto plain NVMe
    (windows(boot_driver="stornvme"), VMD_DISK, True),         # plain image onto VMD
    (windows(boot_driver="stornvme"), AHCI_DISK, False),       # Windows has both of these
    (windows(boot_driver="iaStorAC"), VMD_DISK, True),         # two different RST drivers
    (windows(kind="wim"), VMD_DISK, True),                     # stock WIM has no RST driver
    (windows(kind="wim"), NVME_DISK, False),
    (windows(), VMD_DISK, False),                              # old capture: unknown, don't block
    ({"os_family": "linux", "kind": "block", "meta": {"storage": {"boot_driver": "stornvme"}}}, VMD_DISK, False),
])
def test_storage_mismatch(image, disk, blocked):
    problem = agent.storage_mismatch(image, disk)
    assert bool(problem) == blocked
    if problem:
        assert "INACCESSIBLE_BOOT_DEVICE" in problem and disk["path"] in problem


def test_deploy_check_blocks_unless_overridden(monkeypatch):
    monkeypatch.setattr(agent, "target_disk", lambda path: VMD_DISK)
    logged = []

    class R:
        def log(self, line):
            logged.append(line)

    task = {"disk": "/dev/nvme0n1", "image": windows(boot_driver="stornvme"), "params": {}}
    with pytest.raises(RuntimeError, match="Deploy anyway"):
        agent.check_storage(task, R())
    task["params"]["allow_storage_mismatch"] = True
    agent.check_storage(task, R())
    assert logged and logged[0].startswith("Warning:")


def test_partitions_come_from_sysfs_not_lsblk(tmp_path, monkeypatch):
    """The Acer TravelMate's layout: kernel has nvme0n1p1-p4, lsblk's JSON showed none."""
    disk = tmp_path / "block" / "nvme0n1"
    layout = {1: (204800, "vfat", "SYSTEM"), 2: (16384, "", None), 3: (246230016, "ntfs", "Windows"),
              4: (867328, "ntfs", "Recovery")}  # sizes in KiB, as /proc/partitions showed them
    for n, (kib, _, _) in layout.items():
        (disk / f"nvme0n1p{n}").mkdir(parents=True)
        (disk / f"nvme0n1p{n}" / "partition").write_text(str(n))
        (disk / f"nvme0n1p{n}" / "size").write_text(str(kib * 2))  # 512-byte sectors
    (disk / "queue").mkdir()  # not a partition: ignored
    (disk / "nvme0n1p_bogus").mkdir()  # no "partition" file: ignored

    def fake_blkid(node):
        n = int(node[-1])
        fs, label = layout[n][1], layout[n][2]
        return {k: v for k, v in (("TYPE", fs), ("LABEL", label), ("UUID", f"uuid-{n}")) if v}

    monkeypatch.setattr(agent, "blkid_probe", fake_blkid)
    parts = agent.partitions("nvme0n1", str(tmp_path))
    assert [(p["path"], p["partn"], p["fstype"], p["label"]) for p in parts] == [
        ("/dev/nvme0n1p1", 1, "vfat", "SYSTEM"), ("/dev/nvme0n1p2", 2, "", None),
        ("/dev/nvme0n1p3", 3, "ntfs", "Windows"), ("/dev/nvme0n1p4", 4, "ntfs", "Recovery")]
    assert parts[2]["size"] == 246230016 * 1024
    monkeypatch.setattr(agent, "SYSFS", str(tmp_path))
    assert agent.part_node("/dev/nvme0n1", 3) == "/dev/nvme0n1p3"


def test_partitions_of_an_md_volume(tmp_path, monkeypatch):
    (tmp_path / "block" / "md126" / "md126p1").mkdir(parents=True)
    (tmp_path / "block" / "md126" / "md126p1" / "partition").write_text("1")
    (tmp_path / "block" / "md126" / "md126p1" / "size").write_text("2048")
    monkeypatch.setattr(agent, "blkid_probe", lambda node: {"TYPE": "ntfs"})
    assert [p["path"] for p in agent.partitions("md126", str(tmp_path))] == ["/dev/md126p1"]
