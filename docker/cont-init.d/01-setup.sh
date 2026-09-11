#!/bin/sh
# docker/cont-init.d/01-setup.sh — container first-stage init (runs as PID 1 / init)
#
# Responsibilities:
#  1. Create required directory structure under /var/lib/Zeloo
#  2. Set correct ownership (Zeloo:Zeloo, uid=1000)
#  3. Seed default config if not present
#  4. Run database migrations if any

set -e

zeloo_DATA_DIR="/var/lib/Zeloo"
zeloo_CFG_DIR="$zeloo_DATA_DIR/.Zeloo"
DOCKER_CFG="/app/config.docker.yaml"

echo "[cont-init] Setting up Zeloo data directories..."

# Create directory tree
mkdir -p "$zeloo_DATA_DIR"
mkdir -p "$zeloo_CFG_DIR"
mkdir -p "$zeloo_DATA_DIR/skills"
mkdir -p "$zeloo_DATA_DIR/logs"
mkdir -p "$zeloo_DATA_DIR/memory"

# Set ownership (s6-overlay runs as root, app runs as Zeloo uid=1000)
if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 "$zeloo_DATA_DIR"
fi

echo "[cont-init] Directory setup complete: $zeloo_DATA_DIR"

# Seed default config
if [ ! -f "$zeloo_CFG_DIR/config.yaml" ] && [ -f "$DOCKER_CFG" ]; then
    echo "[cont-init] Seeding default config from $DOCKER_CFG"
    cp "$DOCKER_CFG" "$zeloo_CFG_DIR/config.yaml"
fi

# Mark first-stage init complete
touch "$zeloo_DATA_DIR/.cont-init-done"

echo "[cont-init] Done."
