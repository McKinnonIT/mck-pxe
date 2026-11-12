#!/usr/bin/env bash
# Download netboot.xyz's boot loaders into the boot folder, for the PXE menu's
# "netboot.xyz" entry (Linux installers, live systems and tools from the internet).
#   ./scripts/fetch-netboot-xyz.sh [DIR]     (default: data/bootenv)
# Does nothing if this version is already there. Change VERSION to update.
set -euo pipefail
VERSION=3.0.3
DIR=${1:-data/bootenv}
FILES="netboot.xyz.efi netboot.xyz.lkrn"
URL=https://github.com/netbootxyz/netboot.xyz/releases/download/$VERSION

[ "$(cat "$DIR/.netboot-xyz-version" 2>/dev/null)" = "$VERSION" ] && exit 0
mkdir -p "$DIR"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/sums" "$URL/netboot.xyz-sha256-checksums.txt"
for f in $FILES; do
  curl -fsSL -o "$tmp/$f" "$URL/$f"
  (cd "$tmp" && grep -E "[ *]$f\$" sums | sha256sum -c --quiet -)
done
for f in $FILES; do install -m 644 "$tmp/$f" "$DIR/$f"; done
echo "$VERSION" > "$DIR/.netboot-xyz-version"
echo "netboot.xyz $VERSION is in $DIR"
