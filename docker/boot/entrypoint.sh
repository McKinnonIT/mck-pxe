#!/bin/sh
set -eu

: "${SERVER_IP:?SERVER_IP must be set to the address of this server on the imaging network}"
: "${PXE_SUBNET:?PXE_SUBNET must be set to the network address, e.g. 10.10.0.0}"
export PXE_NETMASK="${PXE_NETMASK:-255.255.255.0}"

render() { envsubst '${SERVER_IP} ${PXE_SUBNET} ${PXE_NETMASK}' < "/etc/mck-pxe/$1" > "$2"; }

render dnsmasq.conf.tmpl /etc/dnsmasq.conf
render boot.ipxe.tmpl /tftp/boot.ipxe
# Debian's signed GRUB looks in different places depending on build; cover both.
render grub.cfg.tmpl /tftp/grub/grub.cfg
cp /tftp/grub/grub.cfg /tftp/debian-installer/amd64/grub/grub.cfg

if [ -n "${PXE_INTERFACE:-}" ]; then
  printf 'interface=%s\nbind-dynamic\n' "$PXE_INTERFACE" >> /etc/dnsmasq.conf
fi

if [ ! -f /tftp/mckpxe/vmlinuz ]; then
  echo "WARNING: boot environment not built yet (run scripts/build-bootenv.sh)" >&2
fi

exec dnsmasq --keep-in-foreground --log-facility=- --conf-file=/etc/dnsmasq.conf
