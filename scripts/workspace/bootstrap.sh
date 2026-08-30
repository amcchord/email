#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

install_desktop=false
install_playwright=false

for arg in "$@"; do
    case "$arg" in
        --desktop) install_desktop=true ;;
        --playwright) install_playwright=true ;;
        --help|-h)
            echo "Usage: $0 [--desktop] [--playwright]"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Usage: $0 [--desktop] [--playwright]" >&2
            exit 2
            ;;
    esac
done

if [[ -n "${PYTHON:-}" ]]; then
    python_bin="$PYTHON"
elif command -v python3.13 >/dev/null 2>&1; then
    python_bin="$(command -v python3.13)"
else
    python_bin="$(command -v python3)"
fi

for command_name in git node npm; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Missing required command: $command_name" >&2
        exit 1
    fi
done

python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_version" != "3.13" ]]; then
    echo "Warning: requirements.lock was generated with Python 3.13; using $python_version." >&2
fi

if [[ ! -x .venv/bin/python ]]; then
    echo "Creating .venv with $python_bin"
    "$python_bin" -m venv .venv
fi

echo "Installing pinned Python dependencies"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock

echo "Installing frontend dependencies"
npm --prefix frontend ci

if [[ "$install_desktop" == true ]]; then
    echo "Installing Electron dependencies"
    npm --prefix electron ci
fi

if [[ "$install_playwright" == true ]]; then
    echo "Installing Playwright Chromium for this user"
    .venv/bin/playwright install chromium
fi

echo
echo "Workspace ready. Run: make check"
