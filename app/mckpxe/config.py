import os
from dataclasses import dataclass, field
from pathlib import Path


def _list(name: str) -> list[str]:
    return [v.strip().lower() for v in os.environ.get(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "postgresql+psycopg://mckpxe:mckpxe@db/mckpxe")
    data_dir: Path = Path(os.environ.get("DATA_DIR", "/data"))
    # Address PXE clients use to reach this server (nginx on port 80)
    server_ip: str = os.environ.get("SERVER_IP", "127.0.0.1")
    # Optional PIN required for tasks started from the machine's console
    agent_pin: str = os.environ.get("AGENT_PIN", "")
    # What machines boot into when they have no queued task: "local" or "imaging"
    default_boot: str = os.environ.get("DEFAULT_BOOT", "local")
    # Pangolin passes Remote-Email; optionally restrict who may administer
    admin_emails: list[str] = field(default_factory=lambda: _list("ADMIN_EMAILS"))
    admin_domain: str = os.environ.get("ADMIN_DOMAIN", "").lower()
    # Local development only: act as this user when no auth headers are present
    dev_user: str = os.environ.get("DEV_USER", "")

    @property
    def public_url(self) -> str:
        return f"http://{self.server_ip}"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def drivers_dir(self) -> Path:
        return self.data_dir / "drivers"

    @property
    def system_dir(self) -> Path:
        return self.data_dir / "system"

    @property
    def bcd_path(self) -> Path:
        return self.system_dir / "BCD"

    @property
    def bootenv_dir(self) -> Path:
        return self.data_dir / "bootenv"


settings = Settings()
