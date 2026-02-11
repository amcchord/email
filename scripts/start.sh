#!/bin/bash
set -e

cd /opt/mail

echo "=== Starting Mail Client ==="

# Start PostgreSQL if not running
if ! pg_isready -q 2>/dev/null; then
    echo "Starting PostgreSQL..."
    pg_ctlcluster 17 main start
fi

# Start Redis if not running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Starting Redis..."
    redis-server --daemonize yes
fi

# Activate venv
. venv/bin/activate

# Stop any existing processes
pkill -f "uvicorn backend.main" 2>/dev/null || true
pkill -f "arq backend.workers" 2>/dev/null || true

sleep 1

# Start FastAPI backend
echo "Starting API server..."
nohup uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 2 > /var/log/caddy/api.log 2>&1 &
echo "API server PID: $!"

# Start ARQ worker
echo "Starting background worker..."
nohup arq backend.workers.tasks.WorkerSettings > /var/log/caddy/worker.log 2>&1 &
echo "Worker PID: $!"

# Start Caddy
echo "Starting Caddy..."
caddy stop 2>/dev/null || true
caddy start --config /opt/mail/Caddyfile

echo ""
echo "=== Mail Client is running ==="
echo "  Web UI:  http://localhost:8080"
echo "  API:     http://localhost:8080/api"
echo "  Login:   admin / mountainlion1024"
echo ""
