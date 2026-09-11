#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# install_systemd.sh - Install Zeloo as a systemd service on Linux.
# ---------------------------------------------------------------------------

SERVICE_NAME="zeloo"
SOCKET_NAME="zeloo-gateway"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/../systemd/${SERVICE_NAME}.service"
SOCKET_SRC="${SCRIPT_DIR}/../systemd/${SOCKET_NAME}.socket"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}.service"
SOCKET_DEST="/etc/systemd/system/${SOCKET_NAME}.socket"

# ---------------------------------------------------------------------------
# Platform guard
# ---------------------------------------------------------------------------
if [[ "${OSTYPE:-}" != linux* ]]; then
    echo "ERROR: This installer is for Linux only. Use install_launchd.sh on macOS." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Root guard
# ---------------------------------------------------------------------------
if [[ ${EUID} -ne 0 ]]; then
    echo "ERROR: Please run with sudo: sudo $0" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Verify source files exist
# ---------------------------------------------------------------------------
if [[ ! -f "$SERVICE_SRC" ]]; then
    echo "ERROR: Service file not found: $SERVICE_SRC" >&2
    exit 2
fi
if [[ ! -f "$SOCKET_SRC" ]]; then
    echo "WARN: Optional socket unit not found: $SOCKET_SRC (continuing without it)" >&2
    SOCKET_SRC=""
fi

# ---------------------------------------------------------------------------
# 2. Create dedicated system user
# ---------------------------------------------------------------------------
if ! id -u zeloo >/dev/null 2>&1; then
    echo "[1/5] Creating system user 'zeloo'..."
    useradd --system \
            --shell /bin/false \
            --home /var/lib/Zeloo \
            --comment "Zeloo Agent Runtime" \
            zeloo
else
    echo "[1/5] System user 'zeloo' already exists."
fi

# ---------------------------------------------------------------------------
# 3. Create runtime directories
# ---------------------------------------------------------------------------
echo "[2/5] Creating runtime directories..."
mkdir -p /var/lib/Zeloo /var/log/Zeloo /etc/Zeloo
chown -R zeloo:zeloo /var/lib/Zeloo /var/log/Zeloo
chmod 750 /var/lib/Zeloo /var/log/Zeloo /etc/Zeloo

# ---------------------------------------------------------------------------
# 4. Install unit files
# ---------------------------------------------------------------------------
echo "[3/5] Installing unit files..."
cp "$SERVICE_SRC" "$SERVICE_DEST"
chmod 644 "$SERVICE_DEST"

if [[ -n "$SOCKET_SRC" ]]; then
    cp "$SOCKET_SRC" "$SOCKET_DEST"
    chmod 644 "$SOCKET_DEST"
fi

# ---------------------------------------------------------------------------
# 5. Reload, enable, start
# ---------------------------------------------------------------------------
echo "[4/5] Reloading systemd manager configuration..."
systemctl daemon-reload

echo "[5/5] Enabling and starting services..."
systemctl enable "$SERVICE_NAME"
systemctl enable "$SOCKET_NAME" 2>/dev/null || true

systemctl restart "$SERVICE_NAME"
systemctl restart "$SOCKET_NAME" 2>/dev/null || true

# Allow a moment for the service to settle, then show status
sleep 1

echo ""
echo "==================================================="
echo "Zeloo installed successfully."
echo "Service status : $(systemctl is-active "$SERVICE_NAME")"
echo "Socket status  : $(systemctl is-active "$SOCKET_NAME" 2>/dev/null || echo 'n/a')"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status $SERVICE_NAME"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo "  sudo systemctl stop   $SERVICE_NAME"
echo "==================================================="