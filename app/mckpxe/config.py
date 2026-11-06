import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "postgresql+psycopg://mckpxe:mckpxe@db/mckpxe")
    data_dir: Path = Path(os.environ.get("DATA_DIR", "/data"))
    # Address PXE clients use to reach this server (nginx on port 80)
    server_ip: str = os.environ.get("SERVER_IP", "127.0.0.1")
    # Password for the "admin" account created when there are no accounts yet.
    # Unset: a random one is generated and saved to DATA_DIR/system/initial-admin-password.txt
    initial_admin_password: str = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    # Boot loaders for the USB/ISO image (shim, signed GRUB, isolinux)
    iso_loaders_dir: Path = Path(os.environ.get("ISO_LOADERS_DIR", "/usr/share/mck-pxe/iso"))

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
