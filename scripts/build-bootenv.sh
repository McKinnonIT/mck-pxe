#!/bin/bash
# Build the imaging environment PXE clients boot into: vmlinuz, initrd.img and
# filesystem.squashfs.
#
#   ./scripts/build-bootenv.sh [--output DIR] [--docker | --no-docker]
#
# With Docker (default when it's available): works on any host. On Apple
#   silicon it runs under emulation, which is slow.
# Without Docker: uses mmdebstrap. Needs root on Debian 12/13 x86_64. In a
#   Proxmox LXC, turn on Options > Features > Nesting, because the build mounts
#   /proc and /sys inside the image.
#
# Both builds use bootenv/packages.txt and bootenv/setup.sh, so they produce
# the same environment. DIR defaults to data/bootenv.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=data/bootenv
MODE=auto
while [ $# -gt 0 ]; do
  case "$1" in
    --output) OUT=$2; shift 2 ;;
    --docker) MODE=docker; shift ;;
    --no-docker) MODE=native; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ "$MODE" = auto ]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then MODE=docker; else MODE=native; fi
fi
mkdir -p "$OUT"

if [ "$MODE" = docker ]; then
  echo "Building with Docker"
  docker build --platform linux/amd64 --output "type=local,dest=$OUT" bootenv/
  ls -lh "$OUT"
  exit 0
fi

echo "Building with mmdebstrap (no Docker)"
[ "$(id -u)" = 0 ] || { echo "Run as root (sudo $0) to build without Docker" >&2; exit 1; }
[ -f /etc/debian_version ] || { echo "Building without Docker needs Debian 12 or 13" >&2; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "Building without Docker needs an x86_64 machine" >&2; exit 1; }
if ! command -v mmdebstrap >/dev/null || ! command -v mksquashfs >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends mmdebstrap squashfs-tools >/dev/null
fi

work=$(mktemp -d /var/tmp/mck-pxe-bootenv.XXXXXX)
trap 'rm -rf "$work"' EXIT
packages=$(grep -vE '^\s*(#|$)' bootenv/packages.txt | paste -sd, -)

mmdebstrap \
  --variant=minbase \
  --components=main,contrib,non-free,non-free-firmware \
  --include="$packages" \
  --customize-hook="sync-in bootenv/rootfs /" \
  --customize-hook="upload bootenv/agent/mck-agent /usr/local/bin/mck-agent" \
  --customize-hook='mkdir -p "$1/usr/local/share/mck-agent/ui"' \
  --customize-hook="sync-in bootenv/agent/ui /usr/local/share/mck-agent/ui" \
  --customize-hook="upload bootenv/setup.sh /tmp/setup.sh" \
  --customize-hook='chroot "$1" sh /tmp/setup.sh' \
  --customize-hook='rm -f "$1/tmp/setup.sh"' \
  trixie "$work/rootfs" "${MIRROR:-http://deb.debian.org/debian}"

cp "$(ls "$work"/rootfs/boot/vmlinuz-* | sort -V | tail -n1)" "$work/vmlinuz"
cp "$(ls "$work"/rootfs/boot/initrd.img-* | sort -V | tail -n1)" "$work/initrd.img"
mksquashfs "$work/rootfs" "$work/filesystem.squashfs" -comp zstd -Xcompression-level 15 -noappend -e boot -quiet

# Swap the new files in together so PXE clients never see a half-built set
for f in vmlinuz initrd.img filesystem.squashfs; do
  install -m 644 "$work/$f" "$OUT/.$f.new"
done
for f in vmlinuz initrd.img filesystem.squashfs; do
  mv "$OUT/.$f.new" "$OUT/$f"
done
ls -lh "$OUT"
