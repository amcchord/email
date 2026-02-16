#!/usr/bin/env bash
# =============================================================================
# install.sh — Bootstrap the Mail App interactive setup wizard
#
# One-liner install (clones the repo and runs the wizard):
#   bash <(curl -sSL https://raw.githubusercontent.com/amcchord/email/main/scripts/install.sh)
#
# If already cloned:
#   bash scripts/install.sh
#   bash scripts/install.sh --verify    # Run health checks only
#
# This script:
#   1. Clones the repo if not already present
#   2. Ensures Python 3.11+ is available
#   3. Creates a temporary venv for the wizard's own dependencies
#   4. Installs rich + InquirerPy into that venv
#   5. Launches the interactive Python TUI wizard
#
# Idempotent — safe to run multiple times.
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/amcchord/email.git"
DEFAULT_INSTALL_DIR="/opt/mail"

# --- Colors (if terminal supports them) -----------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' NC=''
fi

info()  { echo -e "${BLUE}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()   { echo -e "${RED}[error]${NC} $*" >&2; }

# --- Collect arguments (before we potentially re-exec) --------------------
WIZARD_ARGS=()
INSTALL_DIR=""
for arg in "$@"; do
    case "$arg" in
        --install-dir=*)
            INSTALL_DIR="${arg#--install-dir=}"
            ;;
        *)
            WIZARD_ARGS+=("$arg")
            ;;
    esac
done

# --- Determine project root -----------------------------------------------
# Case 1: Running from inside the repo (bash scripts/install.sh)
# Case 2: Piped from curl (no BASH_SOURCE context) — need to clone first
resolve_project_root() {
    # If BASH_SOURCE is set and points to a real file, we're running from the repo
    if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [ "$(basename "$script_dir")" = "scripts" ]; then
            echo "$(dirname "$script_dir")"
        else
            echo "$script_dir"
        fi
        return 0
    fi
    return 1
}

PROJECT_ROOT=""
if PROJECT_ROOT="$(resolve_project_root 2>/dev/null)"; then
    ok "Running from existing repo: $PROJECT_ROOT"
else
    # We're being piped from curl — need to clone the repo
    echo ""
    echo -e "${BOLD}Mail App Installer${NC}"
    echo ""

    TARGET="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

    # Check if git is available
    if ! command -v git &>/dev/null; then
        err "git is required but not found."
        echo "  Install git first:"
        echo "    Debian/Ubuntu:  sudo apt install -y git"
        echo "    Fedora/RHEL:    sudo dnf install -y git"
        echo "    Arch:           sudo pacman -S git"
        exit 1
    fi

    if [ -d "$TARGET/.git" ]; then
        info "Repository already exists at $TARGET, pulling latest..."
        cd "$TARGET"
        git pull --ff-only origin main 2>/dev/null || warn "Could not pull (non-fatal, continuing with existing code)"
        PROJECT_ROOT="$TARGET"
    elif [ -d "$TARGET" ] && [ "$(ls -A "$TARGET" 2>/dev/null)" ]; then
        warn "$TARGET exists and is not empty."
        echo "  If this is an existing install, run: cd $TARGET && bash scripts/install.sh"
        echo "  Otherwise, remove the directory and re-run this script."
        exit 1
    else
        info "Cloning repository to $TARGET..."

        # Create parent directory if needed
        parent_dir="$(dirname "$TARGET")"
        if [ ! -d "$parent_dir" ]; then
            sudo mkdir -p "$parent_dir" 2>/dev/null || mkdir -p "$parent_dir"
        fi

        # Clone
        if ! git clone "$REPO_URL" "$TARGET" 2>&1; then
            err "Failed to clone repository."
            echo "  Check your internet connection and that git is configured."
            echo "  You can also clone manually:"
            echo "    git clone $REPO_URL $TARGET"
            echo "    cd $TARGET && bash scripts/install.sh"
            exit 1
        fi

        ok "Cloned to $TARGET"
        PROJECT_ROOT="$TARGET"
    fi
fi

cd "$PROJECT_ROOT"

SETUP_VENV="$PROJECT_ROOT/.setup_venv"

# --- Find Python 3.11+ ---------------------------------------------------
find_python() {
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
            local major="${ver%%.*}"
            local minor="${ver##*.}"
            if [ "${major:-0}" -ge 3 ] && [ "${minor:-0}" -ge 11 ]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN=""
if ! PYTHON_BIN="$(find_python)"; then
    err "Python 3.11+ is required but not found."
    echo ""
    echo "Install Python first:"
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora/RHEL:    sudo dnf install python3 python3-pip"
    echo "  Arch:           sudo pacman -S python python-pip"
    echo "  macOS:          brew install python@3.13"
    exit 1
fi

ok "Found Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

# --- Create wizard venv if needed ----------------------------------------
if [ ! -d "$SETUP_VENV" ] || [ ! -f "$SETUP_VENV/bin/python" ]; then
    info "Creating setup wizard virtual environment..."
    "$PYTHON_BIN" -m venv "$SETUP_VENV"
    ok "Created $SETUP_VENV"
fi

SETUP_PIP="$SETUP_VENV/bin/pip"
SETUP_PYTHON="$SETUP_VENV/bin/python"

# --- Install wizard dependencies -----------------------------------------
install_wizard_deps() {
    info "Installing wizard dependencies (rich, InquirerPy)..."
    "$SETUP_PIP" install --quiet --upgrade pip >/dev/null 2>&1
    "$SETUP_PIP" install --quiet "rich>=13.0" "InquirerPy>=0.3.4" >/dev/null 2>&1
    ok "Wizard dependencies installed."
}

# Check if deps are already satisfied
if "$SETUP_PYTHON" -c "import rich; import InquirerPy" 2>/dev/null; then
    ok "Wizard dependencies already installed."
else
    install_wizard_deps
fi

# --- Launch the wizard ---------------------------------------------------
echo ""
info "Launching setup wizard..."
echo ""

exec "$SETUP_PYTHON" -m scripts.setup "${WIZARD_ARGS[@]}"
