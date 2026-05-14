#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-aprs-propview}"
INSTALL_DIR="${INSTALL_DIR:-/opt/aprs-propview}"
REMOVE_DATA="${REMOVE_DATA:-0}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-running with sudo so the uninstaller can manage systemd files..."
  exec sudo \
    SERVICE_NAME="${SERVICE_NAME}" \
    INSTALL_DIR="${INSTALL_DIR}" \
    REMOVE_DATA="${REMOVE_DATA}" \
    bash "$0"
fi

systemctl stop "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
systemctl disable "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
rm -f "/etc/default/${SERVICE_NAME}"
systemctl daemon-reload

if [[ "${REMOVE_DATA}" == "1" ]]; then
  rm -rf "${INSTALL_DIR}"
  echo "Removed ${INSTALL_DIR}."
else
  echo "Service removed. Left ${INSTALL_DIR} in place."
  echo "Run with REMOVE_DATA=1 to remove the application files, config, and database."
fi
