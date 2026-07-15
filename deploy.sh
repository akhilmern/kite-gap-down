#!/usr/bin/env bash
# deploy.sh — Build frontend + start backend

set -e

echo "=== Gap-Down Trading System Deploy ==="

# 1. Copy env
if [ ! -f .env ]; then
  echo "Creating .env from .env.example …"
  cp .env.example .env
fi

# 2. Install backend deps
echo "Installing Python dependencies…"
pip install -r backend/requirements.txt

# 3. Build frontend
echo "Installing frontend dependencies…"
cd frontend
npm install
echo "Building frontend…"
npm run build
cd ..
# Copy dist to backend-accessible path
cp -r frontend/dist backend/dist 2>/dev/null || true

# 4. Create data/logs dirs
mkdir -p backend/data backend/logs

# 5. Start backend
echo "Starting backend on port 6666…"
python backend/run.py
