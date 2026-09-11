#!/bin/sh
# docker/tini-shim.sh — tini compatibility shim
#
# If tini (PID 1 init) is present, delegate to it.
# Otherwise execute the command directly.
#
# Usage:
#   docker run --init opencontainers/image ...
# or
#   ./tini-shim.sh -- Zeloo run

if command -v tini > /dev/null 2>&1; then
    exec tini -- "$@"
else
    exec "$@"
fi
