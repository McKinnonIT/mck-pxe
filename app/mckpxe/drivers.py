"""Driver library: unpack vendor driver packs, index INF files, and pick the
drivers each machine needs."""
import os
import re
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import Driver, DriverPack, Host

# Hardware IDs, normalised to the same short forms the agent reports
HWID_PATTERNS = [
    (re.compile(r"PCI\\VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})", re.I), "PCI\\VEN_{}&DEV_{}"),
    (re.compile(r"USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I), "USB\\VID_{}&PID_{}"),
    (re.compile(r"HDAUDIO\\FUNC_[0-9A-F]{2}&VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})", re.I), "HDAUDIO\\VEN_{}&DEV_{}"),
    (re.compile(r"ACPI\\VEN_([A-Z0-9]{3,4})&DEV_([0-9A-F]{4})", re.I), "ACPI\\{}{}"),
    (re.compile(r"ACPI\\([A-Z0-9]{7,8})(?![A-Z0-9&_])", re.I), "ACPI\\{}"),
]

ARCHIVE_EXTS = {".zip", ".cab", ".7z", ".exe", ".msi", ".tar", ".gz", ".tgz", ".rar"}


def pack_dir(pack_id: int) -> Path:
    return settings.drivers_dir / str(pack_id)


def files_dir(pack_id: int) -> Path:
    return pack_dir(pack_id) / "files"


# --------------------------------------------------------------------------- INF parsing

def decode_inf(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if len(raw) > 1 and raw[1:2] == b"\x00":
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip() if not line.lstrip().startswith('"') else line.strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            current = line[1:line.index("]")].strip().lower()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def _kv(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines:
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def extract_hwids(text: str) -> list[str]:
    ids = set()
    for pattern, fmt in HWID_PATTERNS:
        for m in pattern.finditer(text):
            ids.add(fmt.format(*m.groups()).upper())
    return sorted(ids)


def parse_inf(raw: bytes) -> dict | None:
    """Return driver info, or None if the INF doesn't target 64-bit x86 Windows."""
    text = decode_inf(raw)
    sections = parse_sections(text)
    version = _kv(sections.get("version", []))
    strings = _kv(sections.get("strings", []))

    def resolve(value: str) -> str:
        value = value.strip()
        m = re.fullmatch(r"%([^%]+)%", value)
        if m:
            value = strings.get(m.group(1).lower(), value)
        return value.strip('"')

    # [Manufacturer] lines look like: %Mfg% = Models, NTamd64, NTamd64.10.0
    decorations = []
    for line in sections.get("manufacturer", []):
        if "=" in line:
            decorations += [d.strip().lower() for d in line.split("=", 1)[1].split(",")[1:]]
    if decorations and not any(d.startswith(("ntamd64", "nt.")) or d == "nt" for d in decorations):
        return None

    driver_ver = version.get("driverver", "")
    return {
        "class_name": resolve(version.get("class", "")),
        "provider": resolve(version.get("provider", "")),
        "version": driver_ver.split(",")[-1].strip() if driver_ver else "",
        "hardware_ids": extract_hwids(text),
    }


# --------------------------------------------------------------------------- extraction

def _run(cmd: list[str]) -> bool:
    return subprocess.run(cmd, capture_output=True).returncode == 0


def extract_archive(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if _run(["7z", "x", "-y", f"-o{dest}", str(src)]) and any(dest.iterdir()):
        return
    if src.suffix.lower() == ".exe" and _run(["innoextract", "-s", "-d", str(dest), str(src)]):
        return
    raise RuntimeError(f"Could not extract {src.name}. Supported: zip, cab, 7z, tar, and most vendor .exe packs.")


def has_inf(path: Path) -> bool:
    return any(p.suffix.lower() == ".inf" for p in path.rglob("*") if p.is_file())


def expand_nested(root: Path) -> None:
    """Some vendor packs wrap the real drivers in further archives."""
    if has_inf(root):
        return
    for archive in [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS]:
        try:
            extract_archive(archive, archive.with_name(archive.stem + "_x"))
            archive.unlink()
        except RuntimeError:
            pass


def process_pack(pack_id: int) -> None:
    """Background job: unpack an uploaded driver pack and index its INFs."""
    with SessionLocal() as db:
        pack = db.get(DriverPack, pack_id)
        if not pack:
            return
        pack.status = "processing"
        db.commit()
        try:
            upload = pack_dir(pack_id) / "upload"
            dest = files_dir(pack_id)
            shutil.rmtree(dest, ignore_errors=True)
            source = upload.with_suffix(Path(pack.filename).suffix.lower() or ".zip")
            upload.rename(source)
            extract_archive(source, dest)
            expand_nested(dest)
            source.unlink(missing_ok=True)
            index_pack(db, pack, dest)
            pack.size_bytes = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
            pack.status = "ready" if pack.drivers else "error"
            pack.error = "" if pack.drivers else "No 64-bit Windows drivers (INF files) found in this pack."
        except Exception as e:  # surface any failure in the admin UI
            pack.status, pack.error = "error", str(e)
        db.commit()


def index_pack(db: Session, pack: DriverPack, root: Path) -> None:
    pack.drivers.clear()
    for inf in sorted(root.rglob("*")):
        if not inf.is_file() or inf.suffix.lower() != ".inf":
            continue
        info = parse_inf(inf.read_bytes())
        if not info:
            continue
        rel = inf.relative_to(root)
        pack.drivers.append(Driver(inf_path=str(rel), directory=str(rel.parent), **info))


# --------------------------------------------------------------------------- selection

def model_matches(pack: DriverPack, host: Host) -> bool:
    if not pack.model_match:
        return False
    if pack.manufacturer and pack.manufacturer.lower() not in (host.manufacturer or "").lower():
        return False
    haystack = f"{host.model} {host.sku}".lower()
    return any(t.strip().lower() in haystack for t in pack.model_match.split(",") if t.strip())


def select_drivers(db: Session, host: Host) -> list[dict]:
    """Decide which drivers a machine gets.

    - Model packs (OEM driver packs) whose model match fits the machine: every driver.
    - Generic library packs: only drivers whose hardware IDs are present in the machine.
    """
    host_ids = {h.upper() for h in host.hardware_ids or []}
    packs = db.scalars(select(DriverPack).where(DriverPack.enabled, DriverPack.status == "ready")).all()
    plan = []
    for pack in packs:
        if model_matches(pack, host):
            drivers, reason = list(pack.drivers), f"model match ({pack.model_match})"
        elif not pack.model_match:
            drivers = [d for d in pack.drivers if host_ids.intersection(d.hardware_ids or [])]
            reason = "hardware ID match"
        else:
            continue
        if drivers:
            plan.append({"pack": pack, "drivers": drivers, "reason": reason})
    return plan


def minimal_dirs(dirs: list[str]) -> list[str]:
    """Drop directories already covered by a parent in the list."""
    out: list[str] = []
    for d in sorted(set(dirs), key=lambda x: (x.count("/"), x)):
        if d in (".", ""):
            return ["."]
        if not any(d == p or d.startswith(p.rstrip("/") + "/") for p in out):
            out.append(d)
    return out


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "drivers"


def tar_stream(pack_id: int, dirs: list[str]):
    root = files_dir(pack_id)
    safe = [d for d in minimal_dirs(dirs) if ".." not in Path(d).parts and (root / d).is_dir()]
    if not safe:
        return
    proc = subprocess.Popen(["tar", "-c", "-C", str(root), "--", *safe], stdout=subprocess.PIPE)
    try:
        while chunk := proc.stdout.read(1 << 20):
            yield chunk
    finally:
        proc.stdout.close()
        proc.wait()


def remove_pack_files(pack_id: int) -> None:
    shutil.rmtree(pack_dir(pack_id), ignore_errors=True)


def ensure_dirs() -> None:
    for d in (settings.images_dir, settings.drivers_dir, settings.system_dir):
        os.makedirs(d, exist_ok=True)
