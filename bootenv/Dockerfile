# syntax=docker/dockerfile:1
# Builds the Linux imaging environment that PXE clients boot into.
# Output (via scripts/build-bootenv.sh): vmlinuz, initrd.img, filesystem.squashfs
#
# The kernel is Debian's signed kernel, so this boots with Secure Boot enabled.
FROM debian:trixie AS rootfs
ENV DEBIAN_FRONTEND=noninteractive
RUN sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' \
      /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      linux-image-amd64 live-boot initramfs-tools systemd-sysv udev kmod \
      iproute2 ca-certificates curl python3 whiptail procps less nano \
      partclone wimtools ntfs-3g zstd pv \
      fdisk gdisk parted util-linux dosfstools e2fsprogs xfsprogs btrfs-progs exfatprogs \
      efibootmgr mokutil dmidecode pciutils usbutils \
      libhivex-bin libwin-hivex-perl \
      firmware-realtek firmware-bnx2 firmware-bnx2x \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin

COPY rootfs/ /
COPY agent/mck-agent /usr/local/bin/mck-agent
RUN chmod +x /usr/local/bin/mck-agent \
 && systemctl enable systemd-networkd \
 && systemctl mask apt-daily.timer apt-daily-upgrade.timer e2scrub_reap.service \
 && passwd -l root \
 && update-initramfs -u -k all

FROM debian:trixie AS squash
RUN apt-get update && apt-get install -y --no-install-recommends squashfs-tools
COPY --from=rootfs / /rootfs
RUN mkdir /out \
 && cp "$(ls /rootfs/boot/vmlinuz-* | sort -V | tail -n1)" /out/vmlinuz \
 && cp "$(ls /rootfs/boot/initrd.img-* | sort -V | tail -n1)" /out/initrd.img \
 && mksquashfs /rootfs /out/filesystem.squashfs -comp zstd -Xcompression-level 15 -noappend -e boot

FROM scratch
COPY --from=squash /out/ /
