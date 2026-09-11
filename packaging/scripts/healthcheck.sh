#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# healthcheck.sh - Health probe for Docker / systemd / k8s / Nomad.
# Returns 0 if healthy, 1 otherwise.
# ---------------------------------------------------------------------------
set -u

PORT="${ZELOO_PORT:-9119}"
HOST="${ZELOO_HOST:-127.0.0.1}"
TIMEOUT="${ZELOO_HEALTHCHECK_TIMEOUT:-5}"
PATH_VALUE="${ZELOO_HEALTH_PATH:-/health}"

# Compose URL pieces safely
PROTO="${ZELOO_PROTO:-http}"
URL="${PROTO}://${HOST}:${PORT}${PATH_VALUE}"

# ---------------------------------------------------------------------------
# Probe using curl (preferred) or wget (fallback)
# ---------------------------------------------------------------------------
HTTP_CODE="000"

if command -v curl >/dev/null 2>&1; then
    HTTP_CODE=$(curl --silent --show-error \
                       --max-time "$TIMEOUT" \
                       --output /dev/null \
                       --write-out "%{http_code}" \
                       "$URL" 2>/dev/null || echo "000")
elif command -v wget >/dev/null 2>&1; then
    if wget --quiet --timeout="$TIMEOUT" --tries=1 --spider "$URL" 2>/dev/null; then
        HTTP_CODE="200"
    else
        HTTP_CODE="000"
    fi
else
    echo "ERROR: neither curl nor wget is available" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------
case "$HTTP_CODE" in
    200|204|301|302)
        echo "healthy (HTTP $HTTP_CODE, $URL)"
        exit 0
        ;;
    000)
        echo "unhealthy: connection failed to $URL (timeout=${TIMEOUT}s)"
        exit 1
        ;;
    *)
        echo "unhealthy (HTTP $HTTP_CODE from $URL)"
        exit 1
        ;;
esac