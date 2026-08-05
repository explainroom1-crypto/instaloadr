#!/usr/bin/env bash
set -euo pipefail

# deploy_backend.sh
# Usage: run this on the server from any user account:
# 1) Pull latest repo changes: git -C /path/to/repo pull
# 2) Make this script executable (once): chmod +x backend/deploy_backend.sh
# 3) Run as root (or with sudo): sudo backend/deploy_backend.sh

# This script:
# - detects the backend folder (where this script lives)
# - ensures a Python venv exists
# - installs requirements
# - writes a systemd service file at /etc/systemd/system/instaloadr-backend.service
# - enables & starts the service

# NOTE: This script assumes the repo is located on the server and this file
# lives in the backend folder. It runs the service as root for simplicity.
# For production, consider moving the project to /opt and running as a non-root user.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$SCRIPT_DIR"
VENV="$BACKEND/venv"
SYSTEMD_FILE="/etc/systemd/system/instaloadr-backend.service"

echo "Backend directory: $BACKEND"

# Create venv if missing
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

# Upgrade pip and install requirements
echo "Installing Python dependencies into virtualenv..."
"$VENV/bin/pip" install --upgrade pip setuptools wheel
"$VENV/bin/pip" install -r "$BACKEND/requirements.txt"

# Write systemd service (runs as root by default)
echo "Writing systemd service to $SYSTEMD_FILE"
sudo tee "$SYSTEMD_FILE" > /dev/null <<SERVICE
[Unit]
Description=InstaLoadr backend
After=network.target

[Service]
User=root
WorkingDirectory=$BACKEND
Environment="ENVIRONMENT=production"
Environment="CORS_ALLOWED_ORIGINS=https://instaloadr.com,https://www.instaloadr.com"
ExecStart=$VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port 5000
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
SERVICE

# Reload systemd and enable/start service
echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable --now instaloadr-backend

# Show status and quick checks
sleep 1
sudo systemctl status instaloadr-backend --no-pager || true

# show uvicorn binary and a quick health check (best-effort)
ls -l "$VENV/bin/uvicorn" || true
curl -i http://127.0.0.1:5000/health || true

echo "Deploy script finished. If any errors appeared above, paste them to your support engineer or me."