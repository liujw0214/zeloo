#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# install_launchd.sh - Install Zeloo as a macOS LaunchDaemon.
# ---------------------------------------------------------------------------

PLIST_NAME="com.zeloo.agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="${SCRIPT_DIR}/../launchd/${PLIST_NAME}.plist"
PLIST_DEST="/Library/LaunchDaemons/${PLIST_NAME}.plist"

# ---------------------------------------------------------------------------
# Platform guard
# ---------------------------------------------------------------------------
if [[ "${OSTYPE:-}" != darwin* ]]; then
    echo "ERROR: This installer is for macOS only. Use install_systemd.sh on Linux." >&2
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
# 1. Verify source plist exists
# ---------------------------------------------------------------------------
if [[ ! -f "$PLIST_SRC" ]]; then
    echo "ERROR: Plist not found: $PLIST_SRC" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# 2. Create runtime directories
# ---------------------------------------------------------------------------
echo "[1/4] Creating runtime directories..."
mkdir -p /var/lib/Zeloo
mkdir -p /var/log/Zeloo
chmod 755 /var/lib/Zeloo /var/log/Zeloo

# ---------------------------------------------------------------------------
# 3. Install plist
# ---------------------------------------------------------------------------
echo "[2/4] Installing plist to $PLIST_DEST..."
cp "$PLIST_SRC" "$PLIST_DEST"
chmod 644 "$PLIST_DEST"
chown root:wheel "$PLIST_DEST"

# ---------------------------------------------------------------------------
# 4. Load + start via launchctl
# ---------------------------------------------------------------------------
echo "[3/4] Loading daemon into launchd..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"

echo "[4/4] Starting service..."
launchctl start "$PLIST_NAME"

sleep 1

echo ""
echo "==================================================="
echo "Zeloo installed successfully."
echo "Plist status  : $(launchctl list | grep "$PLIST_NAME" || echo 'not loaded')"
echo ""
echo "Useful commands:"
echo "  sudo launchctl list | grep $PLIST_NAME"
echo "  tail -f /var/log/Zeloo/zeloo.out.log"
echo "  sudo launchctl unload $PLIST_DEST"
echo "==================================================="