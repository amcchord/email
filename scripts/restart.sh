#!/bin/bash
# =============================================================================
# restart.sh — Restart services after code changes
#
# Usage:
#   bash scripts/restart.sh              # Restart everything (frontend + backend + worker)
#   bash scripts/restart.sh --all        # Same as above
#   bash scripts/restart.sh --frontend   # Rebuild frontend only
#   bash scripts/restart.sh --backend    # Restart API server only
#   bash scripts/restart.sh --worker     # Restart background worker only
#   bash scripts/restart.sh --backend --worker   # Restart both backend services
#   bash scripts/restart.sh --frontend --backend # Rebuild frontend + restart API
#
# This script is idempotent and safe to call multiple times.
# It writes a build version to /opt/mail/.build_version so open browser tabs
# can detect the change and auto-refresh.
# =============================================================================
set -e

cd /opt/mail

# Parse flags
DO_FRONTEND=false
DO_BACKEND=false
DO_WORKER=false
DO_TUI=false
GOT_FLAGS=false

for arg in "$@"; do
    case "$arg" in
        --frontend)
            DO_FRONTEND=true
            GOT_FLAGS=true
            ;;
        --backend)
            DO_BACKEND=true
            GOT_FLAGS=true
            ;;
        --worker)
            DO_WORKER=true
            GOT_FLAGS=true
            ;;
        --tui)
            DO_TUI=true
            GOT_FLAGS=true
            ;;
        --all)
            DO_FRONTEND=true
            DO_BACKEND=true
            DO_WORKER=true
            DO_TUI=true
            GOT_FLAGS=true
            ;;
        *)
            echo "Unknown flag: $arg"
            echo "Usage: bash scripts/restart.sh [--frontend] [--backend] [--worker] [--tui] [--all]"
            exit 1
            ;;
    esac
done

# Default to --all if no flags provided
if [ "$GOT_FLAGS" = false ]; then
    DO_FRONTEND=true
    DO_BACKEND=true
    DO_WORKER=true
    DO_TUI=true
fi

echo "=== Restarting Services ==="

RESTARTED=""

# --- Frontend ---
if [ "$DO_FRONTEND" = true ]; then
    echo "[frontend] Rebuilding frontend..."
    cd frontend
    npm run build
    cd /opt/mail
    RESTARTED="${RESTARTED} frontend"
    echo "[frontend] Done."
fi

# --- Backend (uvicorn) ---
if [ "$DO_BACKEND" = true ]; then
    echo "[backend] Restarting API server..."
    sudo systemctl restart mailapp
    echo "[backend] Done."
    RESTARTED="${RESTARTED} backend"
fi

# --- Worker (arq) ---
if [ "$DO_WORKER" = true ]; then
    echo "[worker] Restarting background worker..."
    sudo systemctl restart mailworker
    echo "[worker] Done."
    RESTARTED="${RESTARTED} worker"
fi

# --- TUI (mailtui) ---
if [ "$DO_TUI" = true ]; then
    if systemctl is-enabled mailtui >/dev/null 2>&1; then
        echo "[tui] Restarting TUI server..."
        sudo systemctl restart mailtui
        echo "[tui] Done."
        RESTARTED="${RESTARTED} tui"
    else
        echo "[tui] TUI service not installed, skipping."
    fi
fi

# --- Write build version so open browser tabs auto-refresh ---
BUILD_VERSION=$(date +%s)
echo "$BUILD_VERSION" > /opt/mail/.build_version
echo "[version] Build version: $BUILD_VERSION"

echo ""
echo "=== Restart complete:${RESTARTED} ==="
echo ""
