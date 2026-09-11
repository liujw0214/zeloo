#!/bin/sh
# docker/main-wrapper.sh — main process wrapper with environment setup
#
# Responsibilities:
#  1. Source environment variables from /etc/profile.d/
#  2. Run one-time health check
#  3. Forward signals (TERM/INT) cleanly
#  4. exec into the target binary

set -e

echo "[main-wrapper] Starting Zeloo..."

# Source environment overrides
if [ -f /etc/profile.d/Zeloo-env.sh ]; then
    echo "[main-wrapper] Loading /etc/profile.d/Zeloo-env.sh"
    set -a
    . /etc/profile.d/Zeloo-env.sh
    set +a
fi

# Validate critical environment
if [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "[main-wrapper] WARNING: No API key found (OPENAI_API_KEY / ANTHROPIC_API_KEY)" >&2
fi

# Pre-flight health check (gateway mode only)
if [ "$zeloo_MODE" = "gateway" ]; then
    echo "[main-wrapper] Pre-flight health check..."
    if curl -sf --max-time 5 http://localhost:8080/health > /dev/null 2>&1; then
        echo "[main-wrapper] Health endpoint already responding — continuing"
    else
        echo "[main-wrapper] Health endpoint not responding yet — this is normal during startup"
    fi
fi

# Trap SIGTERM / SIGINT for graceful shutdown
trap 'echo "[main-wrapper] Received signal, forwarding..."' TERM INT

echo "[main-wrapper] Exec into Zeloo..."
exec Zeloo "$@"
