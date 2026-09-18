#!/usr/bin/env bash
# scripts/build-web.sh — Build the dashboard web UI and write the content-hash stamp
# so the dashboard can skip rebuilding on restart.
#
# Usage:
#   ./scripts/build-web.sh               # npm install (if needed) + build + stamp
#   ./scripts/build-web.sh --skip-install  # build + stamp only (faster when deps unchanged)
#
# What it does:
#   1. (optional) npm install in the web workspace — skipped when --skip-install.
#   2. cd web && npm run build — produces zeloo_cli/web_dist/.
#   3. Compute the source-tree content hash and write /root/.Zeloo/web-ui-build-stamp.json
#      with the exact fields _stamp_is_current() looks for (contentHash, builtAt).
#
# After this, restart the dashboard with --skip-build to pick up the freshly built dist
# (or let the dashboard auto-detect via /api/runtime/version and surface a banner).

set -euo pipefail

SKIP_INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --skip-install) SKIP_INSTALL=1 ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# Resolve repo root (parent of this script's parent).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
    echo "==> npm install (web workspace)"
    npm install --workspace web --prefer-offline
fi

echo "==> npm run build (web workspace)"
cd web
npm run build
cd "$REPO_ROOT"

# Stamp must be written with the SAME helper the dashboard uses, otherwise
# _stamp_is_current() will reject it and the dashboard will rebuild from scratch.
echo "==> writing web-ui-build-stamp.json"
.venv/bin/python - <<'PY'
from zeloo_cli.main_web_build import _compute_web_ui_content_hash, _web_ui_stamp_path
from pathlib import Path
import json
from datetime import datetime, timezone

web = Path("/root/zeloo/web")
content = _compute_web_ui_content_hash(web.parent, web)
stamp = Path(_web_ui_stamp_path())
stamp.parent.mkdir(parents=True, exist_ok=True)
stamp.write_text(json.dumps({
    "contentHash": content,
    "builtAt": datetime.now(timezone.utc).isoformat(),
}, indent=2) + "\n")
print(f"stamp: {stamp}  contentHash={content[:12]}…")
PY

echo
echo "==> done. Restart the dashboard with --skip-build to serve the new dist:"
echo "       Zeloo dashboard --host 0.0.0.0 --port 9119 --no-open --skip-build"