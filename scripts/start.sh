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

echo ""
echo "=== Mail Client is running ==="
echo "  Web UI:  https://email.mcchord.net"
echo "  API:     https://email.mcchord.net/api"
echo ""
