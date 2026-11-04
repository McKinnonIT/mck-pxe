#!/bin/sh
# Build the PXE imaging environment into data/bootenv/.
# Needs Docker with BuildKit. Works on any host; on Apple silicon it runs under emulation (slow).
set -eu
cd "$(dirname "$0")/.."
mkdir -p data/bootenv
docker build --platform linux/amd64 --output type=local,dest=data/bootenv bootenv/
ls -lh data/bootenv
