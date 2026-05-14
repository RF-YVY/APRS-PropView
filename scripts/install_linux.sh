#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-aprs-propview}"
INSTALL_DIR="${INSTALL_DIR:-/opt/aprs-propview}"
RUN_USER="${APRS_PROPVIEW_USER:-${SUDO_USER:-${USER}}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-running with sudo so the installer can write ${INSTALL_DIR} and systemd files..."
  exec sudo \
    SERVICE_NAME="${SERVICE_NAME}" \
    INSTALL_DIR="${INSTALL_DIR}" \
    APRS_PROPVIEW_USER="${RUN_USER}" \
    PYTHON_BIN="${PYTHON_BIN}" \
    bash "$0"
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Missing ${PYTHON_BIN}. Install python3 and python3-venv, then run this script again." >&2
  exit 1
fi

if ! id "${RUN_USER}" >/dev/null 2>&1; then
  echo "User '${RUN_USER}' does not exist. Set APRS_PROPVIEW_USER to a valid user." >&2
  exit 1
fi

RUN_GROUP="$(id -gn "${RUN_USER}")"

echo "Installing APRS PropView"
echo "  Source:  ${REPO_DIR}"
echo "  Target:  ${INSTALL_DIR}"
echo "  Service: ${SERVICE_NAME}"
echo "  User:    ${RUN_USER}"

mkdir -p "${INSTALL_DIR}"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude ".git" \
    --exclude ".venv" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    "${REPO_DIR}/" "${INSTALL_DIR}/"
else
  tar -C "${REPO_DIR}" \
    --exclude ".git" \
    --exclude ".venv" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    -cf - . | tar -C "${INSTALL_DIR}" -xf -
fi

chown -R "${RUN_USER}:${RUN_USER}" "${INSTALL_DIR}"

sudo -u "${RUN_USER}" "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"
sudo -u "${RUN_USER}" "${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip
sudo -u "${RUN_USER}" "${INSTALL_DIR}/.venv/bin/python" -m pip install -r "${INSTALL_DIR}/requirements.txt"

if [[ ! -f "${INSTALL_DIR}/config.toml" && -f "${INSTALL_DIR}/config.toml.example" ]]; then
  sudo -u "${RUN_USER}" cp "${INSTALL_DIR}/config.toml.example" "${INSTALL_DIR}/config.toml"
fi

if getent group dialout >/dev/null 2>&1; then
  usermod -aG dialout "${RUN_USER}"
  echo "Added ${RUN_USER} to the dialout group for serial TNC access."
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=APRS PropView
Documentation=https://github.com/RF-YVY/APRS-PropView
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=-/etc/default/${SERVICE_NAME}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > "/etc/default/${SERVICE_NAME}" <<EOF
# Optional environment overrides for APRS PropView.
# The application reads config.toml from ${INSTALL_DIR}.
PYTHONUNBUFFERED=1
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

echo
echo "Install complete."
echo "Edit ${INSTALL_DIR}/config.toml or start the service and configure from the web UI."
echo "Start now: sudo systemctl start ${SERVICE_NAME}"
echo "Logs:      journalctl -u ${SERVICE_NAME} -f"
