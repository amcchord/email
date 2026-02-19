#!/bin/bash
set -e

echo "=== Mail Client Setup ==="

# Ensure we're in the right directory
cd /opt/mail

# Start PostgreSQL if not running
if ! pg_isready -q 2>/dev/null; then
    echo "Starting PostgreSQL..."
    pg_ctlcluster 17 main start || true
fi

# Start Redis if not running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Starting Redis..."
    redis-server --daemonize yes
fi

# Create Python venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Install/upgrade Python dependencies
echo "Installing Python dependencies..."
. venv/bin/activate
pip install -q -r requirements.txt

# Install Playwright Chromium browser for AI-powered unsubscribe
if [ -f "venv/bin/playwright" ]; then
    echo "Installing Playwright Chromium browser..."
    venv/bin/playwright install chromium --with-deps || echo "Playwright browser install failed (non-fatal)"
fi

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Generate encryption key if not set
if grep -q 'ENCRYPTION_KEY=$' .env 2>/dev/null; then
    KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    sed -i "s|ENCRYPTION_KEY=|ENCRYPTION_KEY=${KEY}|" .env
    echo "Generated encryption key"
fi

# Build frontend if needed
if [ ! -d "frontend/dist" ] || [ "frontend/src" -nt "frontend/dist" ]; then
    echo "Building frontend..."
    cd frontend
    npm install
    npm run build
    cd ..
fi

# Create log directory for Caddy
mkdir -p /var/log/caddy

echo "=== Setup complete ==="
