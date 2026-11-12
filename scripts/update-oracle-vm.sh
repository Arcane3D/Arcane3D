#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/image-to-dxf"
if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi
cd "$APP_DIR"
git fetch origin
git pull --ff-only origin main
docker compose config --quiet
docker compose up -d --build
docker compose ps
