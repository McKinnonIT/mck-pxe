"""ISO library: each distro family's layout is recognised and booted with the right arguments."""
import pytest

from mckpxe.isolib import detect

LAYOUTS = {
    "casper": ["casper/vmlinuz", "casper/initrd", "casper/filesystem.squashfs"],
    "proxmox": ["boot/linux26", "boot/initrd.img", "proxmox/packages.txt"],
    "anaconda": ["images/pxeboot/vmlinuz", "images/pxeboot/initrd.img", "images/install.img"],
    "fedora-live": ["images/pxeboot/vmlinuz", "images/pxeboot/initrd.img", "LiveOS/squashfs.img"],
    "archiso": ["arch/boot/x86_64/vmlinuz-linux", "arch/boot/x86_64/initramfs-linux.img",
                "arch/boot/intel-ucode.img", "arch/x86_64/airootfs.sfs"],
    "debian-live": ["live/vmlinuz", "live/initrd.img", "live/filesystem.squashfs"],
    "debian-installer": ["install.amd/vmlinuz", "install.amd/initrd.gz", "dists/trixie/Release"],
    "generic": ["EFI/BOOT/BOOTX64.EFI", "README.txt"],
}


def make(tmp_path, files):
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x")
    return tmp_path


@pytest.mark.parametrize("family", LAYOUTS)
def test_detects_family(tmp_path, family):
    assert detect(make(tmp_path, LAYOUTS[family]))["family"] == family


def test_recipes(tmp_path):
    r = detect(make(tmp_path / "a", ["casper_pop-os_24.04/vmlinuz.efi", "casper_pop-os_24.04/initrd.gz"]))
    assert r["kernel"] == "casper_pop-os_24.04/vmlinuz.efi" and "live-media-path=/casper_pop-os_24.04" in r["args"]
    r = detect(make(tmp_path / "b", LAYOUTS["archiso"]))
    assert r["initrds"] == ["arch/boot/intel-ucode.img", "arch/boot/x86_64/initramfs-linux.img"]
    r = detect(make(tmp_path / "c", LAYOUTS["debian-installer"]))
    assert "dists/trixie/main/installer-amd64" in r["download"]["_netboot/linux"]
    assert detect(make(tmp_path / "d", LAYOUTS["proxmox"]))["iso_in_initrd"] == "/proxmox.iso"
    assert detect(make(tmp_path / "e", [*LAYOUTS["anaconda"], "BaseOS/x"]))["args"].startswith("inst.repo={tree}")


def test_menu_and_boot_script(client):
    from mckpxe.db import SessionLocal
    from mckpxe.models import BootIso

    with SessionLocal() as db:
        db.add(BootIso(name="Arch", status="ready", extra_args="nomodeset",
                       boot={"family": "archiso", "kernel": "arch/k", "initrds": ["arch/u", "arch/i"],
                             "args": "archiso_http_srv={tree}/ ip=dhcp"}))
        db.add(BootIso(name="Proxmox", status="ready",
                       boot={"family": "proxmox", "kernel": "boot/linux26", "initrds": ["boot/initrd.img"],
                             "args": "rw", "iso_in_initrd": "/proxmox.iso"}))
        db.add(BootIso(name="Half-uploaded", status="processing"))
        db.commit()
        arch, pve = (i.id for i in db.query(BootIso).order_by(BootIso.id).limit(2))

    menu = client.get("/api/boot/ipxe-isos").text
    assert f"item iso{arch} Arch" in menu and "Half-uploaded" not in menu
    # UEFI machines reach iPXE only from GRUB's ISO library entry, so they get the library straight away
    assert client.get("/api/boot/ipxe/aa:bb:cc:dd:ee:ff?platform=efi").text == menu

    script = client.get(f"/api/boot/ipxe-iso/{arch}").text
    base = "http://10.0.0.5/files/isos"
    assert (f"kernel {base}/{arch}/tree/arch/k initrd=i0 initrd=i1 BOOTIF=01-${{netX/mac:hexhyp}} "
            f"archiso_http_srv={base}/{arch}/tree/ ip=dhcp nomodeset") in script
    assert f"initrd --name i1 {base}/{arch}/tree/arch/i" in script
    assert f"initrd {base}/{pve}/image.iso /proxmox.iso" in client.get(f"/api/boot/ipxe-iso/{pve}").text
    assert client.get("/api/boot/ipxe-iso/9999").status_code == 404
