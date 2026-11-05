# syntax=docker/dockerfile:1
# Builds the Linux imaging environment that PXE clients boot into.
# Output (via scripts/build-bootenv.sh): vmlinuz, initrd.img, filesystem.squashfs
#
# The kernel is Debian's signed kernel, so this boots with Secure Boot enabled.
FROM debian:trixie AS rootfs
ENV DEBIAN_FRONTEND=noninteractive
# Package list and setup.sh are shared with the non-Docker (mmdebstrap) build
COPY packages.txt setup.sh /tmp/build/
# Kernel and firmware from trixie-backports, for new hardware
COPY apt/backports.sources /etc/apt/sources.list.d/
COPY apt/backports.pref /etc/apt/preferences.d/
RUN sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' \
      /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && grep -vE '^\s*(#|$)' /tmp/build/packages.txt | xargs apt-get install -y --no-install-recommends

COPY rootfs/ /
COPY agent/mck-agent /usr/local/bin/mck-agent
COPY agent/ui/ /usr/local/share/mck-agent/ui/
RUN sh /tmp/build/setup.sh && rm -rf /tmp/build

FROM debian:trixie AS squash
RUN apt-get update && apt-get install -y --no-install-recommends squashfs-tools
COPY --from=rootfs / /rootfs
RUN mkdir /out \
 && cp "$(ls /rootfs/boot/vmlinuz-* | sort -V | tail -n1)" /out/vmlinuz \
 && cp "$(ls /rootfs/boot/initrd.img-* | sort -V | tail -n1)" /out/initrd.img \
 && mksquashfs /rootfs /out/filesystem.squashfs -comp zstd -Xcompression-level 15 -noappend -e boot

FROM scratch
COPY --from=squash /out/ /
