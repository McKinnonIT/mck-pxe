from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    ip: Mapped[str | None] = mapped_column(String(45))
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    sku: Mapped[str] = mapped_column(String(200), default="")
    serial: Mapped[str] = mapped_column(String(200), default="")
    cpu: Mapped[str] = mapped_column(String(200), default="")
    ram_mb: Mapped[int] = mapped_column(Integer, default=0)
    boot_mode: Mapped[str] = mapped_column(String(10), default="")
    secure_boot: Mapped[bool] = mapped_column(Boolean, default=False)
    disks: Mapped[list] = mapped_column(JSON, default=list)
    hardware_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(10))  # block | wim
    os_family: Mapped[str] = mapped_column(String(20), default="other")  # windows | linux | other
    status: Mapped[str] = mapped_column(String(20), default="capturing")  # capturing | processing | ready | error
    error: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    unattend: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BootIso(Base):
    """An ISO in the ISO library, booted over the network from the PXE menu (not deployed)."""
    __tablename__ = "boot_isos"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="uploading")  # uploading | processing | ready | error
    error: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    boot: Mapped[dict] = mapped_column(JSON, default=dict)  # isolib.detect() recipe
    extra_args: Mapped[str] = mapped_column(Text, default="")  # added to the kernel arguments
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DriverPack(Base):
    __tablename__ = "driver_packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    # Comma-separated model name fragments. Empty = generic library pack,
    # where drivers are picked per machine by hardware ID.
    model_match: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="uploading")  # uploading | processing | ready | error
    error: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    drivers: Mapped[list["Driver"]] = relationship(back_populates="pack", cascade="all, delete-orphan")


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("driver_packs.id", ondelete="CASCADE"), index=True)
    inf_path: Mapped[str] = mapped_column(String(1000))
    directory: Mapped[str] = mapped_column(String(1000))
    class_name: Mapped[str] = mapped_column(String(100), default="")
    provider: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[str] = mapped_column(String(100), default="")
    hardware_ids: Mapped[list] = mapped_column(JSON, default=list)

    pack: Mapped[DriverPack] = relationship(back_populates="drivers")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), index=True)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(10))  # capture | deploy
    kind: Mapped[str] = mapped_column(String(10))  # block | wim
    disk: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed | cancelled
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[float] = mapped_column(Float, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    log: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    host: Mapped[Host] = relationship()
    image: Mapped[Image | None] = relationship()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="technician")  # admin | technician
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # web (admin console) | console (imaging environment)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class ServerSetting(Base):
    """Settings changed in the admin UI (rather than the .env file)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON)


class ImageCompression(Base):
    """Recompression of a disk image's files on the server (see compression.py)."""
    __tablename__ = "image_compression"

    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=3)  # zstd level the files are at now
    target: Mapped[int | None] = mapped_column(Integer)  # level being compressed to
    state: Mapped[str] = mapped_column(String(20), default="idle")  # idle | queued | running | error
    progress: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    saved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # from the last recompression
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# An image's compression state, removed with the image
Image.compression = relationship(ImageCompression, uselist=False, cascade="all, delete-orphan", lazy="selectin")
