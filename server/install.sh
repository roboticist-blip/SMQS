#!/bin/bash

set -e

echo "======================================"
echo " IoT Telemetry Platform Installer"
echo "======================================"

echo "[1/6] installing..."
cd "$(dirname "$0")"
python3 -m venv .venv

echo "[2/6] Installing required packages..."
.venv/bin/pip install -r requirements.txt

echo "[3/6] Installing Docker..."

if ! command -v docker &> /dev/null
then
    sudo dnf install -y dnf-plugins-core
    sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
    sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "[4/6] Starting Docker..."
sudo systemctl enable docker
sudo systemctl start docker

echo "[5/6] Adding user to docker group..."
sudo usermod -aG docker $USER

echo "[6/6] Starting IoT stack..."

docker compose down || true
docker compose pull
docker compose up -d

echo "======================================"
echo " Installation Complete"
echo "======================================"

echo "dash board http://localhost:3000/"
echo "mqtt server http://localhost:8000/health"
echo "api : http://localhost:8000/api/latest"