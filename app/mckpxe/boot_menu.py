"""How the PXE boot menu behaves for machines with nothing queued.

Set on the admin UI's Settings page. Machines with a queued task always boot
straight into imaging, whatever is set here.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import ServerSetting

KEY = "boot_menu"
DEFAULTS = {
    # The entry picked when the countdown runs out: "imaging" (the first entry) or "local"
    "default": "imaging",
    "timeout": 5,  # seconds the menu waits
}
MAX_TIMEOUT = 300


def get(db: Session) -> dict:
    row = db.get(ServerSetting, KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def put(db: Session, data: dict) -> dict:
    new = get(db)
    if "default" in data:
        if data["default"] not in ("imaging", "local"):
            raise HTTPException(400, "default must be imaging or local")
        new["default"] = data["default"]
    if "timeout" in data:
        try:
            timeout = int(data["timeout"])
        except (TypeError, ValueError):
            raise HTTPException(400, "timeout must be a number of seconds") from None
        if not 0 <= timeout <= MAX_TIMEOUT:
            raise HTTPException(400, f"timeout must be between 0 and {MAX_TIMEOUT} seconds")
        new["timeout"] = timeout
    row = db.get(ServerSetting, KEY)
    if row:
        row.value = new
    else:
        db.add(ServerSetting(key=KEY, value=new))
    db.commit()
    return new
