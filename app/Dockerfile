FROM python:3.13-slim-trixie
RUN apt-get update \
 && apt-get install -y --no-install-recommends wimtools 7zip innoextract tar zstd \
      xorriso mtools dosfstools isolinux syslinux-common \
 && rm -rf /var/lib/apt/lists/*
# Boot loaders for the USB/ISO image: Microsoft-signed shim, Debian-signed GRUB, isolinux
RUN apt-get update && mkdir /tmp/pkgs && cd /tmp/pkgs \
 && apt-get download shim-signed grub-efi-amd64-signed \
 && for p in *.deb; do dpkg-deb -x "$p" /tmp/x; done \
 && mkdir -p /usr/share/mck-pxe/iso && cd /usr/share/mck-pxe/iso \
 && cp "$(find /tmp/x -name 'shimx64.efi.signed*' | sort | tail -n1)" bootx64.efi \
 && cp /tmp/x/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed grubx64.efi \
 && cp /usr/lib/ISOLINUX/isolinux.bin /usr/lib/ISOLINUX/isohdpfx.bin /usr/lib/syslinux/modules/bios/ldlinux.c32 . \
 && rm -rf /tmp/pkgs /tmp/x /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mckpxe ./mckpxe
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "mckpxe.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
