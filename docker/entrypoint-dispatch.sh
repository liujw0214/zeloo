#!/bin/sh
# docker/entrypoint-dispatch.sh — mode dispatcher based on zeloo_MODE
#
# Supported modes:
#   cli      — Interactive CLI session  (default)
#   gateway  — API gateway server
#   web     — Web interface
#   tui     — Terminal UI
#   cron     — Cron scheduler worker
#
# Usage (in Dockerfile):
#   ENTRYPOINT ["/usr/local/bin/entrypoint-dispatch.sh"]
#   CMD ["cli"]

set -e

zeloo_MODE="${zeloo_MODE:-cli}"

echo "[entrypoint-dispatch] mode=$zeloo_MODE"

case "$zeloo_MODE" in
    cli)
        echo "[entrypoint-dispatch] Starting Zeloo CLI..."
        exec Zeloo chat
        ;;
    gateway)
        echo "[entrypoint-dispatch] Starting Zeloo Gateway..."
        exec Zeloo gateway
        ;;
    web)
        echo "[entrypoint-dispatch] Starting Zeloo Web..."
        exec Zeloo web
        ;;
    tui)
        echo "[entrypoint-dispatch] Starting Zeloo TUI..."
        exec Zeloo tui
        ;;
    cron)
        echo "[entrypoint-dispatch] Starting Zeloo Cron worker..."
        exec Zeloo cron-worker
        ;;
    *)
        echo "[entrypoint-dispatch] Unknown mode: $zeloo_MODE" >&2
        echo "Supported: cli | gateway | web | tui | cron" >&2
        exit 1
        ;;
esac
