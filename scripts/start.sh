#!/bin/bash
set -e

cd /opt/mail

echo "=== Starting Mail Client ==="

# Ensure PostgreSQL is running
if ! pg_isready -q 2>/dev/null; then
    echo "Starting PostgreSQL..."
    sudo systemctl start postgresql
fi

# Ensure Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Starting Redis..."
    sudo systemctl start redis-server
fi

# Write initial build version so the auto-reload endpoint works
echo "$(date +%s)" > /opt/mail/.build_version

# Start services via systemd
echo "Starting API server..."
sudo systemctl start mailapp

echo "Starting background worker..."
sudo systemctl start mailworker

echo "Starting Caddy..."
sudo systemctl start caddy

# Start TUI server if installed
if systemctl is-enabled mailtui >/dev/null 2>&1; then
    echo "Starting TUI server..."
    sudo systemctl start mailtui
fi

echo ""
echo "=== Mail Client is running ==="
echo "  Web UI:  https://email.mcchord.net"
echo "  API:     https://email.mcchord.net/api"
if systemctl is-enabled mailtui >/dev/null 2>&1; then
    echo "  TUI SSH: ssh -p 2222 email.mcchord.net"
    echo "  TUI Web: https://email.mcchord.net/tui/"
fi
echo ""
