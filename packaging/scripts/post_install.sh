#!/bin/sh
# Generic post-install hook shared by the Zeloo packaging recipes.
#
# Responsibilities:
#   1. Materialise the runtime workspace directory tree.
#   2. Normalise ownership/permissions so the runtime user can read & write.
#   3. Surface a friendly hint pointing the operator at the next step
#      (`zeloo doctor` and `zeloo install`).
#
# Behaviour is intentionally portable: it works on POSIX systems that do not
# ship systemd (BSD, minimal containers, CI runners) and degrades gracefully
# when systemd is not present.

set -eu

ZELOO_USER="${ZELOO_USER:-zeloo}"
ZELOO_HOME="${ZELOO_HOME:-/var/lib/zeloo}"
ZELOO_BIN="${ZELOO_BIN:-/usr/bin/zeloo}"

log() {
    printf '[zeloo postinstall] %s\n' "$*"
}

ensure_user() {
    if command -v getent >/dev/null 2>&1 && getent passwd "$ZELOO_USER" >/dev/null 2>&1; then
        return 0
    fi
    if command -v useradd >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir "$ZELOO_HOME" "$ZELOO_USER" || true
    elif command -v adduser >/dev/null 2>&1; then
        adduser --system --no-create-home --home "$ZELOO_HOME" "$ZELOO_USER" || true
    else
        log "warning: could not locate useradd/adduser; skipping user provisioning"
    fi
}

ensure_directories() {
    for sub in workspace archive profile memory skills logs; do
        path="$ZELOO_HOME/$sub"
        if [ ! -d "$path" ]; then
            mkdir -p "$path"
        fi
        chmod 0750 "$path" 2>/dev/null || true
    done
    if command -v chown >/dev/null 2>&1; then
        chown -R "$ZELOO_USER":"$ZELOO_USER" "$ZELOO_HOME" 2>/dev/null || true
    fi
}

ensure_systemd_unit() {
    if [ ! -d /run/systemd/system ]; then
        log "systemd not detected; skipping service enable step"
        return 0
    fi
    if [ ! -f /etc/systemd/system/zeloo.service ]; then
        log "no /etc/systemd/system/zeloo.service present; skipping enable"
        return 0
    fi
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl enable zeloo.service >/dev/null 2>&1 || true
    fi
}

log "running post-install hooks"
ensure_user
ensure_directories
ensure_systemd_unit

log "Zeloo has been installed."
log "Run '$ZELOO_BIN doctor' to verify the install."
log "Run '$ZELOO_BIN install' for first-run workspace setup."

exit 0
