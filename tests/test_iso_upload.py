"""A Windows ISO upload is unpacked to the install.wim/esd inside it."""
import shutil
import subprocess

import pytest

from mckpxe.images import extract_from_iso

WIM = b"MSWIM\0\0\0" + b"x" * 100

pytestmark = pytest.mark.skipif(not (shutil.which("7z") and shutil.which("xorriso")), reason="needs 7z and xorriso")


def make_iso(tmp_path, name, data):
    media = tmp_path / "media"
    (media / "sources").mkdir(parents=True)
    (media / "sources" / name).write_bytes(data)
    iso = tmp_path / "upload.wim"
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-J", "-r", "-o", str(iso), str(media)], check=True)
    return iso


@pytest.mark.parametrize("name", ["install.wim", "install.esd"])
def test_iso_replaced_by_install_image(tmp_path, name):
    iso = make_iso(tmp_path, name, WIM)
    extract_from_iso(iso)
    assert iso.read_bytes() == WIM
    assert not (tmp_path / "iso-extract").exists()


def test_wim_left_alone(tmp_path):
    wim = tmp_path / "upload.wim"
    wim.write_bytes(WIM)
    extract_from_iso(wim)
    assert wim.read_bytes() == WIM


def test_iso_without_install_image_fails(tmp_path):
    iso = make_iso(tmp_path, "boot.wim", WIM)
    with pytest.raises(RuntimeError, match="Windows ISO"):
        extract_from_iso(iso)
