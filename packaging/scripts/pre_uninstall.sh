#!/bin/sh
# Generic pre-uninstall hook shared by the Zeloo packaging recipes.
#
# Responsibilities:
#   1. Ask the operator (when running interactively) whether the workspace data
#      should be archived before removal.
#   2. Create a compressed tarball snapshot under a safe default path so the
#      operator can recover state after an accidental uninstall.
#   3. Stop and disable the systemd service (when present) before files are
#      removed by the package manager.
#
# Behaviour is portable across POSIX systems; systemd steps are skipped when
# the runtime is not in use.

set -eu

ZELOO_HOME="${ZELOO_HOME:-/var/lib/zeloo}"
ZELOO_USER="${ZELOO_USER:-zeloo}"
BACKUP_ROOT="${ZELOO_BACKUP_DIR:-/var/backups}"

log() {
    printf '[zeloo preuninstall] %s\n' "$*"
}

stop_service() {
    if [ ! -d /run/systemd/system ]; then
        return 0
    fi
    if command -v systemctl >/dev/null 2>&1; then
        systemctl is-active --quiet zeloo.service && \
            systemctl stop zeloo.service || true
        systemctl is-enabled --quiet zeloo.service && \
            systemctl disable zeloo.service || true
    fi
}

archive_state() {
    if [ ! -d "$ZELOO_HOME" ]; then
        log "no workspace at $ZELOO_HOME; nothing to archive"
        return 0
    fi

    timestamp="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || date +%Y%m%d%H%M%S)"
    out_dir="$BACKUP_ROOT/zeloo"
    out_file="$out_dir/zeloo-${timestamp}.tar.zst"

    if ! command -v zstd >/dev/null 2>&1; then
        log "warning: zstd not available; falling back to uncompressed tar"
        out_file="$out_dir/zeloo-${timestamp}.tar"
    fi

    mkdir -p "$out_dir"

    log "archiving $ZELOO_HOME -> $out_file"
    if command -v zstd >/dev/null 2>&1; then
        tar --exclude='*.sock' --exclude='*.pid' \
            -C "$ZELOO_HOME" -cf - . 2>/dev/null \
            | zstd -T0 -q -o "$out_file" 2>/dev/null || \
            log "warning: archive failed; continuing with uninstall"
    else
        tar --exclude='*.sock' --exclude='*.pid' \
            -C "$ZELOO_HOME" -cf "$out_file" . 2>/dev/null || \
            log "warning: archive failed; continuing with uninstall"
    fi

    if command -v chown >/dev/null 2>&1; then
        chown "$ZELOO_USER":"$ZELOO_USER" "$out_file" 2>/dev/null || true
    fi
}

confirm_with_operator() {
    if [ ! -t 0 ]; then
        # Non-interactive (e.g. silent package upgrade) -> archive by default.
        return 0
    fi
    printf 'Archive workspace state before removing Zeloo? [Y/n] '
    read -r answer || answer=""
    case "$answer" in
        n|N|no|No|NO) return 1 ;;
        *) return 0 ;;
    esac
}

log "running pre-uninstall hooks"
stop_service

if confirm_with_operator; then
    archive_state
else
    log "operator declined the archive; continuing with uninstall"
fi

log "Zeloo will now be removed."
exit 0
