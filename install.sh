#!/usr/bin/env bash
# ============================================================================
# Zeloo Agent Installer for Linux / macOS / WSL2 / Termux
# ============================================================================
#
# Hermes Agent parity — same flow as ``NousResearch/hermes-agent``'s
# ``scripts/install.sh``:
#
#   1. Bootstrap uv
#   2. Provision Python 3.11 via uv (no system Python required)
#   3. Create venv at ``<repo>/.venv``
#   4. uv pip install -r requirements.txt
#   5. Symlink ``zeloo`` to ~/.local/bin/zeloo
#   6. Stamp ``~/.zeloo/.install_method = git``
#   7. Optionally launch ``zeloo setup``
#
# Usage (canonical one-liner):
#
#   curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
#
# Parameters:
#   --branch <name>     Git branch (default: main)
#   --commit <sha>      Pin to commit SHA
#   --tag <tag>         Pin to tag (e.g. v0.16.0)
#   --zeloo-home <path> Data directory (default: ~/.zeloo)
#   --install-dir <path> Code location (default: $ZELOO_HOME/zeloo)
#   --skip-setup        Skip post-install wizard
#   --skip-deps         Don't run dep_ensure
#   --ensure <name>     Bootstrap one external dep (called by dep_ensure.py)
#   --postinstall       Run full external-deps bootstrap
#   --non-interactive   Fail instead of prompting
#
# ============================================================================

set -euo pipefail

# ── Defaults ───────────────────────────────────────────────────────────
BRANCH="main"
COMMIT=""
TAG=""
ZELOO_HOME="${ZELOO_HOME:-$HOME/.zeloo}"
INSTALL_DIR=""
SKIP_SETUP=0
SKIP_DEPS=0
ENSURE=""
POST_INSTALL=0
NON_INTERACTIVE=0

# ── Argument parsing ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch) BRANCH="$2"; shift 2 ;;
        --commit) COMMIT="$2"; shift 2 ;;
        --tag)    TAG="$2";    shift 2 ;;
        --zeloo-home)  ZELOO_HOME="$2";  shift 2 ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --skip-setup)  SKIP_SETUP=1;  shift ;;
        --skip-deps)   SKIP_DEPS=1;   shift ;;
        --ensure)      ENSURE="$2";   shift 2 ;;
        --postinstall) POST_INSTALL=1; shift ;;
        --non-interactive) NON_INTERACTIVE=1; shift ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$INSTALL_DIR" ]]; then
    INSTALL_DIR="$ZELOO_HOME/zeloo"
fi

# ── Logging helpers ──────────────────────────────────────────────────
log_stage() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
log_step()  { printf "    %s\n" "$*"; }
log_ok()    { printf "    \033[1;32m[OK]\033[0m %s\n" "$*"; }
log_warn()  { printf "    \033[1;33m[WARN]\033[0m %s\n" "$*"; }
log_fail()  { printf "    \033[1;31m[FAIL]\033[0m %s\n" "$*" >&2; exit 1; }

# ── Stage dispatch (mirror Hermes install.sh) ───────────────────────
if [[ -n "$ENSURE" ]]; then
    ensure_mode "$ENSURE"
    exit 0
fi
if [[ "$POST_INSTALL" == 1 ]]; then
    post_install_mode
    exit 0
fi

main

# ──────────────────────────────────────────────────────────────────────
function ensure_mode() {
    local dep_name="$1"
    # Comma-separated list support
    IFS=',' read -ra deps <<< "$dep_name"
    for dep in "${deps[@]}"; do
        dep="$(echo "$dep" | xargs)"
        case "$dep" in
            ripgrep) install_ripgrep ;;
            ffmpeg)  install_ffmpeg  ;;
            node)    install_node    ;;
            git)     install_git     ;;
            uv)      install_uv      ;;
            *) log_warn "Unknown dep '$dep' — skipping" ;;
        esac
    done
}

function post_install_mode() {
    log_stage "Running full post-install dependency bootstrap"
    install_ripgrep
    install_ffmpeg
    install_node
    install_git
    log_ok "Post-install complete"
}

# ──────────────────────────────────────────────────────────────────────
function install_uv() {
    if command -v uv >/dev/null 2>&1; then
        log_ok "uv already installed"
        return
    fi
    log_stage "Installing uv (Astral Python manager)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
}

function install_git() {
    if command -v git >/dev/null 2>&1; then
        log_ok "git already installed"
        return
    fi
    log_stage "Installing git"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y git
    elif command -v brew >/dev/null 2>&1; then
        brew install git
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y git
    else
        log_warn "Please install git manually: https://git-scm.com/downloads"
    fi
}

function install_ripgrep() {
    if command -v rg >/dev/null 2>&1; then
        log_ok "ripgrep already installed"
        return
    fi
    log_stage "Installing ripgrep"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y ripgrep
    elif command -v brew >/dev/null 2>&1; then
        brew install ripgrep
    else
        log_warn "Please install ripgrep manually: https://github.com/BurntSushi/ripgrep"
    fi
}

function install_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1; then
        log_ok "ffmpeg already installed"
        return
    fi
    log_stage "Installing ffmpeg"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y ffmpeg
    elif command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    else
        log_warn "Please install ffmpeg manually: https://ffmpeg.org/download.html"
    fi
}

function install_node() {
    if command -v node >/dev/null 2>&1; then
        log_ok "node already installed"
        return
    fi
    log_stage "Installing Node.js LTS"
    if command -v apt-get >/dev/null 2>&1; then
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    elif command -v brew >/dev/null 2>&1; then
        brew install node
    else
        log_warn "Please install Node.js manually: https://nodejs.org/"
    fi
}

# ──────────────────────────────────────────────────────────────────────
function main() {
    log_stage "Zeloo Agent Installer (Linux/macOS/WSL2)"
    log_step "Branch / Tag / Commit: ${COMMIT:-$TAG:$BRANCH}"
    log_step "Install dir:  $INSTALL_DIR"
    log_step "Data dir:     $ZELOO_HOME"

    # 1. Ensure git is available
    if ! command -v git >/dev/null 2>&1; then
        install_git
    fi

    # 2. Bootstrap uv
    install_uv
    export PATH="$HOME/.local/bin:$PATH"

    # 3. Provision Python 3.11 via uv
    if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
        log_stage "Provisioning Python 3.11 via uv"
        uv python install 3.11 >/dev/null 2>&1 || true
    fi

    # 4. Clone the repo if not already inside one
    if [[ ! -f "$INSTALL_DIR/cli.py" ]]; then
        log_stage "Cloning Zeloo repository"
        mkdir -p "$INSTALL_DIR"
        # TODO: replace with the actual public repository URL when published.
        REPO="${ZELOO_REPO:-https://github.com/your-org/zeloo.git}"
        git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
        if [[ -n "$COMMIT" ]]; then
            (cd "$INSTALL_DIR" && git checkout "$COMMIT")
        fi
    else
        log_ok "Existing checkout detected at $INSTALL_DIR"
    fi

    # 5. Create venv + install requirements
    if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
        log_stage "Creating virtual environment at $INSTALL_DIR/.venv"
        (cd "$INSTALL_DIR" && uv venv .venv --python 3.11)
    fi

    log_stage "Installing Python dependencies"
    (cd "$INSTALL_DIR" && uv pip install -r requirements.txt)

    # 6. Install in editable mode so `zeloo` resolves
    (cd "$INSTALL_DIR" && uv pip install -e .)

    # 7. Register global `zeloo` command on ~/.local/bin
    local zeloo_bin="$INSTALL_DIR/.venv/bin/zeloo"
    if [[ -x "$zeloo_bin" ]]; then
        log_stage "Registering global \`zeloo\` command"
        mkdir -p "$HOME/.local/bin"
        ln -sf "$zeloo_bin" "$HOME/.local/bin/zeloo"
        # Ensure ~/.local/bin is on PATH for the current shell session
        case ":$PATH:" in
            *":$HOME/.local/bin:"*) ;;
            *) export PATH="$HOME/.local/bin:$PATH" ;;
        esac
        # Persist in shell rc file
        for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
            if [[ -f "$rc" ]] || [[ "$rc" == *.profile ]]; then
                if ! grep -q '\.local/bin' "$rc" 2>/dev/null; then
                    echo '' >> "$rc"
                    echo '# Added by Zeloo installer' >> "$rc"
                    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
                fi
            fi
        done
        log_ok "\`zeloo\` registered at $HOME/.local/bin/zeloo"
    else
        log_warn "\`zeloo\` not built — invoke via \`python -m zeloo_cli.click_app\`"
    fi

    # 8. Stamp install method (so dep_ensure.py can find this script)
    log_stage "Stamping install method"
    ZELOO_HOME="$ZELOO_HOME" INSTALL_DIR="$INSTALL_DIR" \
    "$INSTALL_DIR/.venv/bin/python" - <<'PYEOF'
import json, os
from pathlib import Path
home = Path(os.environ['ZELOO_HOME'])
home.mkdir(parents=True, exist_ok=True)
marker = home / '.install_method'
install_dir = os.environ['INSTALL_DIR']
ref_kind, ref_value = (
    ('commit', os.environ.get('COMMIT', '')) if os.environ.get('COMMIT') else
    ('tag', os.environ.get('TAG', '')) if os.environ.get('TAG') else
    ('branch', os.environ.get('BRANCH', 'main'))
)
marker.write_text(json.dumps({
    'kind': 'git',
    'install_dir': install_dir,
    'ref_kind': ref_kind,
    'ref_value': ref_value,
}, indent=2), encoding='utf-8')
print(f'[OK] install_method stamped at {marker}')
PYEOF

    # 9. Provision ~/.zeloo/ data directory
    log_stage "Creating Zeloo data directory at $ZELOO_HOME"
    mkdir -p "$ZELOO_HOME/profile" "$ZELOO_HOME/memory" "$ZELOO_HOME/skills" "$ZELOO_HOME/archive"

    # 10. Optionally launch the setup wizard
    if [[ "$SKIP_SETUP" == 0 ]]; then
        log_stage "Launching Zeloo setup wizard"
        "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/cli.py" setup
    fi

    log_stage "Installation complete!"
    log_step "Open a new terminal and run:  zeloo chat -q \"hello\""
    log_step "Verify with:                   zeloo doctor"
    log_step "Re-run the wizard later:       zeloo setup"
}
