#!/bin/sh
# Final setup inside the imaging environment, after packages and files are in.
# Shared by the Docker and mmdebstrap builds (scripts/build-bootenv.sh).
set -eu
chmod +x /usr/local/bin/mck-agent
systemctl enable systemd-networkd
systemctl mask apt-daily.timer apt-daily-upgrade.timer e2scrub_reap.service
# No RAID scrubs or mail alerts here: the agent assembles RST volumes itself, read-only until a deploy
systemctl mask mdmonitor.service mdcheck_start.timer mdcheck_continue.timer mdmonitor-oneshot.timer
passwd -l root
update-initramfs -u -k all
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin
