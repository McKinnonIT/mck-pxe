#!/bin/bash
# Install or update mck-pxe on a plain Debian 12/13 machine or LXC, without Docker.
#
#   git clone https://github.com/McKinnonIT/mck-pxe.git && cd mck-pxe
#   sudo ./scripts/install-lxc.sh
#
# Safe to run again: after `git pull`, re-run it to update in place.
# Settings live in /etc/mck-pxe/mck-pxe.env. The first run creates it, filling
# in what it can detect. Anything you set there (or pass as an environment
# variable on the first run) is kept on later runs.
#
# Optional on the first run:
#   SERVER_IP, PXE_SUBNET, PXE_NETMASK, PXE_INTERFACE   (detected if not given)
#   PANGOLIN_ENDPOINT, NEWT_ID, NEWT_SECRET             (installs the newt tunnel)
#   BOOTENV_SRC=/path/to/dir   folder holding vmlinuz, initrd.img and filesystem.squashfs
#
# The imaging environment is built here automatically when it's missing.
# REBUILD_BOOTENV=yes rebuilds it (do this after updates that change bootenv/);
# BUILD_BOOTENV=no skips building it.
set -euo pipefail

NODE_VERSION=22.23.4
NEWT_VERSION=1.19.0
NEWT_SHA256=6d40e223fa49d8bcfa9b7094208c58ff616997979bff7c884d0af61fcc1c5376

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX=/opt/mck-pxe
DATA=/var/lib/mck-pxe
ETC=/etc/mck-pxe
ENV_FILE=$ETC/mck-pxe.env
TFTP=$DATA/tftp

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "Run as root (sudo $0)"
[ -f /etc/debian_version ] || die "This script supports Debian 12 or 13 only"
[ -f "$REPO/app/requirements.txt" ] || die "Run this from a checkout of the mck-pxe repository"
case "$(uname -m)" in x86_64) NODE_ARCH=x64 NEWT_ARCH=amd64 ;; *) die "Only x86_64 is supported" ;; esac

# --------------------------------------------------------------------------- packages
say "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv nginx dnsmasq postgresql gettext-base curl ca-certificates \
  wimtools 7zip innoextract tar xz-utils iproute2 openssl \
  xorriso mtools dosfstools isolinux syslinux-common >/dev/null

# --------------------------------------------------------------------------- settings
say "Writing settings ($ENV_FILE)"
mkdir -p "$ETC"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true; }
# set_default KEY VALUE: keep an existing value in the file, else an env var, else VALUE
set_default() {
  local key=$1 value=$2
  if grep -qE "^$key=" "$ENV_FILE"; then return; fi
  [ -n "${!key:-}" ] && value=${!key}
  echo "$key=$value" >> "$ENV_FILE"
}

IFACE=$(ip -4 route show default | awk '{print $5; exit}')
[ -n "$IFACE" ] || die "No default route, so the network interface can't be detected"
DETECTED_IP=$(ip -4 -o addr show dev "$IFACE" | awk '{print $4; exit}')
[ -n "$DETECTED_IP" ] || die "Couldn't detect the IP address of $IFACE"
read -r NET_ADDR NET_MASK < <(python3 -c 'import ipaddress,sys; n=ipaddress.ip_interface(sys.argv[1]).network; print(n.network_address, n.netmask)' "$DETECTED_IP")

set_default SERVER_IP "${DETECTED_IP%/*}"
set_default PXE_SUBNET "$NET_ADDR"
set_default PXE_NETMASK "$NET_MASK"
set_default PXE_INTERFACE "$IFACE"
set_default POSTGRES_PASSWORD "$(openssl rand -hex 24)"
set_default DATABASE_URL "postgresql+psycopg://mckpxe:$(get POSTGRES_PASSWORD)@127.0.0.1/mckpxe"
set_default DATA_DIR "$DATA"
set_default DEFAULT_BOOT "local"
# TEST_MODE=yes also opens the admin UI on http://SERVER_IP:8080, for testing
# before Pangolin is set up. Sign-in is still required, but passwords then
# cross the network in plain HTTP.
set_default TEST_MODE "no"
set_default ISO_LOADERS_DIR "$PREFIX/iso-loaders"
set_default PANGOLIN_ENDPOINT ""
set_default NEWT_ID ""
set_default NEWT_SECRET ""

set -a; . "$ENV_FILE"; set +a
python3 -c 'import ipaddress,sys; ipaddress.ip_address(sys.argv[1])' "$SERVER_IP" 2>/dev/null \
  || die "SERVER_IP must be an IP address, not '$SERVER_IP' (edit $ENV_FILE)"

# --------------------------------------------------------------------------- users and folders
say "Creating service user and folders"
id mckpxe >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin mckpxe
mkdir -p "$DATA"/{images,drivers,system,bootenv} "$TFTP" "$PREFIX"
chmod 755 "$DATA" "$DATA/bootenv"
chown mckpxe:www-data "$DATA"/{images,drivers,system}
chmod 2750 "$DATA"/{images,drivers,system}   # nginx (www-data) serves these; setgid keeps the group

# --------------------------------------------------------------------------- database
say "Setting up PostgreSQL"
systemctl enable --now postgresql >/dev/null
for _ in $(seq 1 20); do runuser -u postgres -- pg_isready -q && break; sleep 1; done
psql_admin() { (cd / && runuser -u postgres -- psql -qtA -v ON_ERROR_STOP=1 "$@"); }

# Containers often have no locale set, so PostgreSQL defaults to SQL_ASCII,
# which the driver can't use. An empty database with the wrong encoding is
# recreated; one with data in it is left alone.
encoding=$(psql_admin -c "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = 'mckpxe'")
if [ -n "$encoding" ] && [ "$encoding" != UTF8 ]; then
  tables=$(psql_admin -d mckpxe -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
  [ "$tables" = 0 ] || die "Database mckpxe uses $encoding encoding and already has data. Convert it to UTF8 by hand."
  warn "Recreating empty database mckpxe as UTF8 (it was $encoding)"
  systemctl stop mck-pxe-api 2>/dev/null || true
  psql_admin -c "DROP DATABASE mckpxe"
fi

psql_admin -v pw="$POSTGRES_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE mckpxe LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mckpxe')\gexec
ALTER ROLE mckpxe PASSWORD :'pw';
SELECT 'CREATE DATABASE mckpxe OWNER mckpxe ENCODING ''UTF8'' LC_COLLATE ''C.UTF-8'' LC_CTYPE ''C.UTF-8'' TEMPLATE template0'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mckpxe')\gexec
SQL

# --------------------------------------------------------------------------- API
say "Installing the API"
rm -rf "$PREFIX/app"
cp -r "$REPO/app" "$PREFIX/app"
rm -rf "$PREFIX/app/.venv" "$PREFIX/app/dev.db"
[ -x "$PREFIX/venv/bin/python" ] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q -r "$PREFIX/app/requirements.txt"

cat > /etc/systemd/system/mck-pxe-api.service <<EOF
[Unit]
Description=mck-pxe API
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service

[Service]
User=mckpxe
Group=www-data
UMask=0027
EnvironmentFile=$ENV_FILE
WorkingDirectory=$PREFIX/app
ExecStart=$PREFIX/venv/bin/uvicorn mckpxe.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# Older installs signed everyone in as a fixed user in TEST_MODE; now everyone has an account
rm -f /etc/systemd/system/mck-pxe-api.service.d/test-mode.conf

# --------------------------------------------------------------------------- web UI
say "Building the web UI (Node $NODE_VERSION)"
NODE_DIR=$PREFIX/node-v$NODE_VERSION
if [ ! -x "$NODE_DIR/bin/node" ]; then
  tarball=node-v$NODE_VERSION-linux-$NODE_ARCH.tar.xz
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/$tarball" "https://nodejs.org/dist/v$NODE_VERSION/$tarball"
  curl -fsSL -o "$tmp/SHASUMS256.txt" "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt"
  (cd "$tmp" && grep " $tarball\$" SHASUMS256.txt | sha256sum -c --quiet) || die "Node download failed its checksum"
  mkdir -p "$NODE_DIR"
  tar -xJf "$tmp/$tarball" -C "$NODE_DIR" --strip-components=1
  rm -rf "$tmp"
fi
build=$(mktemp -d)
cp -r "$REPO/web/." "$build/"
rm -rf "$build/node_modules" "$build/dist"
(cd "$build" && PATH="$NODE_DIR/bin:$PATH" npm ci --silent && PATH="$NODE_DIR/bin:$PATH" npm run build --silent) >/dev/null
rm -rf "$PREFIX/web"
cp -r "$build/dist" "$PREFIX/web"
rm -rf "$build"

# --------------------------------------------------------------------------- nginx
say "Configuring nginx"
# Same config as the Docker image, rewritten for local paths. The admin UI
# listens on 127.0.0.1 only: newt runs on this machine and reaches it there.
admin_listen=127.0.0.1:8080
[ "$TEST_MODE" = yes ] && admin_listen=8080
sed -e "s|http://api:8000|http://127.0.0.1:8000|g" \
    -e "s|alias /srv/bootenv/;|alias $DATA/bootenv/;|" \
    -e "s|alias /data/images/;|alias $DATA/images/;|" \
    -e "s|alias /data/system/BCD;|alias $DATA/system/BCD;|" \
    -e "s|root /usr/share/nginx/html;|root $PREFIX/web;|" \
    -e "s|listen 8080;|listen $admin_listen;|" \
    -e "s|listen 80;|listen 80 default_server;|" \
    "$REPO/docker/nginx/default.conf" > /etc/nginx/sites-available/mck-pxe
ln -sf /etc/nginx/sites-available/mck-pxe /etc/nginx/sites-enabled/mck-pxe
rm -f /etc/nginx/sites-enabled/default
nginx -t -q

# --------------------------------------------------------------------------- PXE boot (dnsmasq)
say "Configuring PXE boot (proxyDHCP + TFTP)"
loaders=$(mktemp -d)
(cd "$loaders" && apt-get download -qq shim-signed grub-efi-amd64-signed ipxe >/dev/null 2>&1) \
  || die "Couldn't download boot loader packages"
for p in "$loaders"/*.deb; do dpkg-deb -x "$p" "$loaders/x"; done
mkdir -p "$TFTP/grub" "$TFTP/debian-installer/amd64/grub"
cp "$(find "$loaders/x" -name 'shimx64.efi.signed*' | sort | tail -n1)" "$TFTP/bootnetx64.efi"
cp "$loaders/x/usr/lib/grub/x86_64-efi-signed/grubnetx64.efi.signed" "$TFTP/grubx64.efi"
cp "$TFTP/bootnetx64.efi" "$TFTP/grubx64.efi" "$TFTP/debian-installer/amd64/"
cp "$loaders/x/usr/lib/ipxe/undionly.kpxe" "$TFTP/undionly.kpxe"
# Boot loaders for the USB/ISO image built from the Settings page
mkdir -p "$ISO_LOADERS_DIR"
cp "$TFTP/bootnetx64.efi" "$ISO_LOADERS_DIR/bootx64.efi"
cp "$loaders/x/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed" "$ISO_LOADERS_DIR/grubx64.efi"
cp /usr/lib/ISOLINUX/isolinux.bin /usr/lib/ISOLINUX/isohdpfx.bin \
   /usr/lib/syslinux/modules/bios/ldlinux.c32 "$ISO_LOADERS_DIR/"
chmod -R a+rX "$ISO_LOADERS_DIR"
cp "$TFTP/undionly.kpxe" "$TFTP/undionly.kpxe.0"
rm -rf "$loaders"
ln -sfn "$DATA/bootenv" "$TFTP/mckpxe"

render() { envsubst '${SERVER_IP} ${PXE_SUBNET} ${PXE_NETMASK}' < "$REPO/docker/boot/$1"; }
render boot.ipxe.tmpl > "$TFTP/boot.ipxe"
render grub.cfg.tmpl > "$TFTP/grub/grub.cfg"
cp "$TFTP/grub/grub.cfg" "$TFTP/debian-installer/amd64/grub/grub.cfg"
{
  render dnsmasq.conf.tmpl | sed "s|^tftp-root=.*|tftp-root=$TFTP|"
  if [ -n "${PXE_INTERFACE:-}" ]; then printf 'interface=%s\nbind-dynamic\n' "$PXE_INTERFACE"; fi
} > /etc/dnsmasq.d/mck-pxe.conf
chmod -R a+rX "$TFTP"

# --------------------------------------------------------------------------- imaging environment
say "Checking the imaging environment"
if [ -n "${BOOTENV_SRC:-}" ]; then
  for f in vmlinuz initrd.img filesystem.squashfs; do
    [ -f "$BOOTENV_SRC/$f" ] || die "$BOOTENV_SRC/$f not found"
    cp "$BOOTENV_SRC/$f" "$DATA/bootenv/$f"
  done
fi
missing=""
for f in vmlinuz initrd.img filesystem.squashfs; do [ -f "$DATA/bootenv/$f" ] || missing="$missing $f"; done
# Build it here (no Docker needed) when it's missing, or when asked to with
# REBUILD_BOOTENV=yes, e.g. after an update that changed bootenv/.
if { [ -n "$missing" ] || [ "${REBUILD_BOOTENV:-no}" = yes ]; } && [ "${BUILD_BOOTENV:-yes}" != no ]; then
  say "Building the imaging environment (takes 5-10 minutes)"
  if "$REPO/scripts/build-bootenv.sh" --no-docker --output "$DATA/bootenv"; then
    missing=""
  else
    warn "Building the imaging environment failed (see above). The rest of the install carries on."
  fi
fi
chmod 644 "$DATA"/bootenv/* 2>/dev/null || true

# --------------------------------------------------------------------------- Pangolin (newt)
if [ -n "${NEWT_ID:-}" ] && [ -n "${NEWT_SECRET:-}" ] && [ -n "${PANGOLIN_ENDPOINT:-}" ]; then
  say "Installing newt $NEWT_VERSION (Pangolin tunnel)"
  bin=/usr/local/bin/newt
  if ! "$bin" --version 2>/dev/null | grep -q "$NEWT_VERSION"; then
    curl -fsSL -o /tmp/newt "https://github.com/fosrl/newt/releases/download/$NEWT_VERSION/newt_linux_$NEWT_ARCH"
    echo "$NEWT_SHA256  /tmp/newt" | sha256sum -c --quiet || die "newt download failed its checksum"
    install -m 755 /tmp/newt "$bin"
    rm -f /tmp/newt
  fi
  cat > /etc/systemd/system/mck-pxe-newt.service <<EOF
[Unit]
Description=Pangolin tunnel (newt) for mck-pxe
After=network-online.target
Wants=network-online.target

[Service]
DynamicUser=yes
# Reads PANGOLIN_ENDPOINT, NEWT_ID and NEWT_SECRET
EnvironmentFile=$ENV_FILE
ExecStart=$bin
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  NEWT=yes
else
  NEWT=no
fi

# --------------------------------------------------------------------------- start
say "Starting services"
systemctl daemon-reload
systemctl enable -q mck-pxe-api nginx dnsmasq
systemctl restart mck-pxe-api
# Restart, not reload: a reload can't move a socket between 127.0.0.1 and all
# addresses (TEST_MODE), and nginx keeps the old config without saying so.
systemctl restart nginx
systemctl restart dnsmasq
[ "$NEWT" = yes ] && systemctl enable -q mck-pxe-newt && systemctl restart mck-pxe-newt

ok=no
for _ in $(seq 1 30); do
  curl -fs http://127.0.0.1:8000/api/health >/dev/null && ok=yes && break
  sleep 1
done
[ "$ok" = yes ] || die "The API didn't start. Check: journalctl -u mck-pxe-api -n 50"
curl -fs "http://$SERVER_IP/api/boot/ipxe/00:00:00:00:00:00" >/dev/null \
  || warn "nginx isn't answering on http://$SERVER_IP/ yet. Check: journalctl -u nginx -n 50"
systemctl is-active -q dnsmasq || warn "dnsmasq isn't running. Check: journalctl -u dnsmasq -n 50"

# --------------------------------------------------------------------------- summary
cat <<EOF

mck-pxe is installed.

  Server IP         $SERVER_IP (PXE answered on ${PXE_INTERFACE:-all interfaces}, subnet $PXE_SUBNET/$PXE_NETMASK)
  Admin UI          http://$([ "$TEST_MODE" = yes ] && echo "$SERVER_IP:8080 (TEST MODE)" || echo "127.0.0.1:8080, on this machine only")
  Pangolin target   http://127.0.0.1:8080
  Settings          $ENV_FILE
  Data              $DATA
EOF
if [ -f "$DATA/initial-admin-password.txt" ]; then
  cat <<EOF

  First sign-in: username admin, password $(cat "$DATA/initial-admin-password.txt")
  Change it after signing in (Account, bottom left). This note goes away once you do.
EOF
fi
if [ "$TEST_MODE" = yes ]; then
  printf '\n\033[1;31m  TEST MODE IS ON: the admin UI is reachable at http://%s:8080/\n' "$SERVER_IP"
  printf '  Passwords cross the network unencrypted. Turn it off when done: set\n'
  printf '  TEST_MODE=no in %s and run this script again.\033[0m\n' "$ENV_FILE"
fi
if [ "$NEWT" = no ]; then
  cat <<EOF

  Next: connect Pangolin. Create a Newt site for mck-pxe in Pangolin, add
  PANGOLIN_ENDPOINT, NEWT_ID and NEWT_SECRET to $ENV_FILE, then run this script again.
EOF
fi
if [ -n "$missing" ]; then
  cat <<EOF

  Missing imaging environment files:$missing
  PXE booting and the boot USB won't work until they're in $DATA/bootenv/.
  If the build failed in an LXC, turn on Nesting (Proxmox: Options > Features)
  and run this script again. Or copy the files from a machine that built them:
    scp sysadmin@docker04:~/mck-pxe/data/bootenv/* $DATA/bootenv/
EOF
fi
echo
