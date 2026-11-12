# Network boot service: dnsmasq in proxyDHCP mode + TFTP.
# Boot loaders come from Debian's own packages so UEFI Secure Boot works:
#   UEFI  -> shim (signed by Microsoft) -> GRUB (signed by Debian) -> Debian kernel (signed)
#   BIOS  -> iPXE (undionly.kpxe) -> HTTP
FROM debian:trixie-slim AS loaders
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && mkdir /pkgs && cd /pkgs \
 && apt-get download shim-signed grub-efi-amd64-signed ipxe \
 && for p in *.deb; do dpkg-deb -x "$p" /extract; done \
 && mkdir -p /tftp/grub /tftp/debian-installer/amd64/grub \
 && cp "$(find /extract -name 'shimx64.efi.signed*' | sort | tail -n1)" /tftp/bootnetx64.efi \
 && cp /extract/usr/lib/grub/x86_64-efi-signed/grubnetx64.efi.signed /tftp/grubx64.efi \
 && cp /tftp/bootnetx64.efi /tftp/grubx64.efi /tftp/debian-installer/amd64/ \
 && cp /extract/usr/lib/ipxe/undionly.kpxe /extract/usr/lib/ipxe/snponly.efi /tftp/ \
 && cp /tftp/undionly.kpxe /tftp/undionly.kpxe.0

FROM debian:trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends dnsmasq gettext-base \
 && rm -rf /var/lib/apt/lists/*
COPY --from=loaders /tftp /tftp
COPY dnsmasq.conf.tmpl grub.cfg.tmpl boot.ipxe.tmpl entrypoint.sh /etc/mck-pxe/
RUN chmod +x /etc/mck-pxe/entrypoint.sh
ENTRYPOINT ["/etc/mck-pxe/entrypoint.sh"]
