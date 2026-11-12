"""ISO library: installers, live systems and tools, booted over the network.

An uploaded ISO is unpacked next to itself. detect() looks at its layout and
returns a recipe: the kernel and initrds iPXE loads, and the kernel arguments
that make the system find the rest of itself over HTTP instead of a USB stick.

Secure Boot has to be off for these: the kernels aren't signed by anything
mck-pxe's boot chain trusts.
"""
import re
import shutil
import subprocess
from pathlib import Path

from .config import settings
from .db import SessionLocal
from .models import BootIso


def iso_dir(iso_id: int) -> Path:
    return settings.data_dir / "isos" / str(iso_id)


def remove_iso_files(iso_id: int) -> None:
    d = iso_dir(iso_id)
    if d.exists():
        subprocess.run(["chmod", "-R", "u+w", str(d)], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def find(tree: Path, pattern: str) -> str | None:
    """First file under tree matching a glob (case-insensitive), as a path relative to tree."""
    rx = re.compile(re.escape(pattern).replace(r"\*", "[^/]*") + "$", re.I)
    hits = sorted(str(p.relative_to(tree)) for p in tree.rglob("*") if p.is_file())
    return next((h for h in hits if rx.match(h)), None)


def debian_codename(tree: Path) -> str | None:
    dists = tree / "dists"
    names = [p.name for p in dists.iterdir() if p.is_dir() and not p.is_symlink()] if dists.is_dir() else []
    names = [n for n in names if n not in ("stable", "testing", "unstable", "oldstable")]
    return names[0] if names else None


def detect(tree: Path) -> dict:
    """Work out how to boot an unpacked ISO.

    Paths in the recipe are relative to the unpacked tree; {tree} and {iso} in
    args are filled in with the HTTP URLs of the tree and the ISO file.
    """
    def recipe(family, label, kernel, initrds, args, **extra):
        return {"family": family, "label": label, "kernel": kernel, "initrds": initrds, "args": args, **extra}

    # Ubuntu and its family (Mint, Pop!_OS, Kubuntu...): casper downloads the whole ISO into RAM
    if k := find(tree, "casper*/vmlinuz*"):
        folder = k.split("/")[0]
        initrd = find(tree, f"{folder}/initrd*")
        args = "boot=casper ip=dhcp url={iso} cloud-config-url=/dev/null"
        if folder != "casper":
            args += f" live-media-path=/{folder}"
        return recipe("casper", "Ubuntu-based", k, [initrd], args, needs_ram_for_iso=True)

    # Proxmox VE / Backup Server: the installer looks for the ISO packed into its initrd
    if (k := find(tree, "boot/linux26")) and find(tree, "boot/initrd.img"):
        return recipe("proxmox", "Proxmox", k, ["boot/initrd.img"], "ramdisk_size=16777216 rw quiet splash=silent",
                      iso_in_initrd="/proxmox.iso", needs_ram_for_iso=True)

    # Fedora, RHEL, Rocky, Alma: live images and the Anaconda installer
    live_sq = find(tree, "LiveOS/squashfs.img")
    k = find(tree, "images/pxeboot/vmlinuz") or find(tree, "boot/x86_64/loader/linux")
    if k:
        initrd = find(tree, "images/pxeboot/initrd.img") or find(tree, "boot/x86_64/loader/initrd")
        if live_sq and not find(tree, "images/install.img"):
            return recipe("fedora-live", "Fedora-based live", k, [initrd],
                          f"root=live:{{tree}}/{live_sq} rd.live.image rd.neednet=1 ip=dhcp")
        has_packages = (tree / "Packages").is_dir() or (tree / "BaseOS").is_dir()
        src = "inst.repo" if has_packages else "inst.stage2"
        return recipe("anaconda", "Fedora / RHEL installer", k, [initrd], f"{src}={{tree}} ip=dhcp")

    # Arch Linux and archiso-based (EndeavourOS...)
    if k := find(tree, "*/boot/x86_64/vmlinuz-linux*"):
        base = k.split("/")[0]
        ucode = [u for u in (find(tree, f"{base}/boot/intel-ucode.img"), find(tree, f"{base}/boot/amd-ucode.img")) if u]
        initrd = find(tree, f"{base}/boot/x86_64/initramfs-linux*.img")
        return recipe("archiso", "Arch-based", k, [*ucode, initrd],
                      f"archisobasedir={base} archiso_http_srv={{tree}}/ ip=dhcp")

    # Debian live-boot: Debian live, GParted, Clonezilla, Kali
    if (k := find(tree, "live/vmlinuz*")) and find(tree, "live/filesystem.squashfs"):
        initrd = find(tree, "live/initrd*")
        return recipe("debian-live", "Debian-based live", k, [initrd],
                      "boot=live components fetch={tree}/live/filesystem.squashfs")

    # Debian installer: the ISO's own initrd only looks for a CD, so use Debian's
    # netboot installer for the same release (it installs from the internet)
    if find(tree, "install.amd/vmlinuz") and (codename := debian_codename(tree)):
        url = (f"https://deb.debian.org/debian/dists/{codename}/main/installer-amd64/current/images/"
               "netboot/debian-installer/amd64")
        return recipe("debian-installer", f"Debian installer ({codename})", "_netboot/linux", ["_netboot/initrd.gz"],
                      "", download={"_netboot/linux": f"{url}/linux", "_netboot/initrd.gz": f"{url}/initrd.gz"})

    # Anything else: try the ISO's own boot loader (UEFI) or boot the ISO image (BIOS)
    return recipe("generic", "Unrecognised (tries the ISO's own boot loader)", None, [], "",
                  efi=find(tree, "EFI/BOOT/BOOTX64.EFI"))


def unpack(iso: Path, tree: Path) -> None:
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True)
    # xorriso reads Rock Ridge, so file names and case come out as the distro made them
    r = subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", "/", str(tree)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        detail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
        raise RuntimeError(f"Couldn't read the ISO; is the file complete? ({detail})" if detail else "Not a readable ISO")
    subprocess.run(["chmod", "-R", "u+w,a+rX", str(tree)], capture_output=True)
    if not any(tree.iterdir()):
        raise RuntimeError("Not a readable ISO (nothing inside it)")


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-fsSL", "-o", str(dest), url], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Couldn't download {url}: {r.stderr.strip()}")


def process_iso(iso_id: int) -> None:
    """Background job: unpack an uploaded ISO and work out how to boot it."""
    with SessionLocal() as db:
        item = db.get(BootIso, iso_id)
        if not item:
            return
        item.status = "processing"
        db.commit()
        d = iso_dir(iso_id)
        try:
            # ponytail: keeps the ISO and its unpacked copy (2x the space); some recipes
            # need one, some the other. Trim per family if disk space gets tight.
            unpack(d / "image.iso", d / "tree")
            if find(d / "tree", "sources/install.wim") or find(d / "tree", "sources/install.esd"):
                raise RuntimeError("This is a Windows ISO. Upload it on the Images page to deploy it.")
            boot = detect(d / "tree")
            for rel, url in boot.pop("download", {}).items():
                fetch(url, d / "tree" / rel)
            item.boot = boot
            item.size_bytes = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            item.status, item.error = "ready", ""
        except Exception as e:  # surface any failure in the admin UI
            item.status, item.error = "error", str(e)
        db.commit()


def ipxe_script(item: BootIso) -> str:
    """iPXE commands that boot one ISO, for BIOS and UEFI machines."""
    b = item.boot or {}
    base = f"{settings.public_url}/files/isos/{item.id}"
    tree, iso = f"{base}/tree", f"{base}/image.iso"
    lines = ["#!ipxe", f"echo Booting {item.name}..."]
    # UEFI machines run the ISO's own EFI program when the recipe has one (memtest, unknown ISOs)
    if b.get("efi"):
        lines += ["iseq ${platform} efi || goto bios", f"chain {tree}/{b['efi']}", ":bios"]
    if b.get("kernel"):
        names = [f"i{n}" for n in range(len(b["initrds"]))]
        # BOOTIF tells the initrd which network card iPXE booted from (casper, dracut, archiso, live-boot)
        args = " ".join(a for a in [*(f"initrd={n}" for n in names), "BOOTIF=01-${netX/mac:hexhyp}",
                                    b["args"].format(tree=tree, iso=iso), item.extra_args] if a)
        lines.append(f"kernel {tree}/{b['kernel']} {args}".rstrip())
        lines += [f"initrd --name {n} {tree}/{p}" for n, p in zip(names, b["initrds"], strict=True)]
        if b.get("iso_in_initrd"):
            lines.append(f"initrd {iso} {b['iso_in_initrd']}")
        lines.append("boot")
    else:
        lines.append(f"sanboot --no-describe {iso}")
    return "\n".join(lines) + "\n"
