#!/usr/bin/env bash
# Zeloo Agent — contributor / user installation script
# Usage: bash setup-Zeloo.sh [--dev]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_MODE=0

for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=1 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

echo "=== Zeloo Agent Setup ==="
echo "Project dir: $PROJECT_DIR"

# ── 1. Python version check ──────────────────────────────────────────
echo ""
echo "[1/5] Checking Python version..."
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION#*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "ERROR: Python >= 3.11 required, found $PY_VERSION"
  exit 1
fi
echo "  Python $PY_VERSION OK"

# ── 2. Create virtual environment ────────────────────────────────────
echo ""
echo "[2/5] Creating virtual environment..."
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  echo "  Created .venv"
else
  echo "  .venv already exists, skipping"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── 3. Install dependencies ──────────────────────────────────────────
echo ""
echo "[3/5] Installing dependencies..."
if command -v uv >/dev/null 2>&1; then
  echo "  Using uv for fast installs..."
  uv pip install -r "$PROJECT_DIR/requirements.txt"
  if [ "$DEV_MODE" -eq 1 ]; then
    uv pip install -e "$PROJECT_DIR[dev]"
  fi
else
  echo "  Using pip..."
  pip install --upgrade pip
  pip install -r "$PROJECT_DIR/requirements.txt"
  if [ "$DEV_MODE" -eq 1 ]; then
    pip install -e "$PROJECT_DIR[dev]"
  fi
fi
echo "  Dependencies installed"

# ── 4. Set up Zeloo home directory ──────────────────────────────────
echo ""
echo "[4/5] Setting up Zeloo home..."
zeloo_HOME="${zeloo_HOME:-$HOME/.Zeloo}"
mkdir -p "$zeloo_HOME/skills" "$zeloo_HOME/memories"

CONFIG_FILE="$zeloo_HOME/config.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
  cp "$PROJECT_DIR/config.yaml.example" "$CONFIG_FILE"
  echo "  Created $CONFIG_FILE (edit to configure provider/model)"
else
  echo "  $CONFIG_FILE already exists, skipping"
fi

# ── 5. Set up .env ────────────────────────────────────────────────────
echo ""
echo "[5/5] Setting up environment file..."
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
  echo "  Created .env (fill in API keys)"
else
  echo "  .env already exists, skipping"
fi

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit ~/.Zeloo/config.yaml to set your provider and model"
echo "  2. Edit .env to add your API keys (OPENAI_API_KEY, etc.)"
echo "  3. Run the agent:"
echo "       source .venv/bin/activate"
echo "       python cli.py chat"
echo ""
if [ "$DEV_MODE" -eq 1 ]; then
echo "  Dev tools installed: pytest, ruff, mypy"
echo "  Run tests:  python -m pytest tests/unit/"
echo "  Run lint:   ruff check ."
fi
