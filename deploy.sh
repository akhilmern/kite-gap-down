#!/usr/bin/env bash
# deploy.sh — pull latest code, build frontend, restart backend
# Run from the project root:  bash deploy.sh
set -euo pipefail

# ── Resolve project root (where this script lives) ───────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Working directory: $SCRIPT_DIR"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
echo ""
echo "==> [1/4] Pulling latest code from git (forcing override)..."

# Fetch all updates from remote first
git fetch --all

# Reset any modified tracked files (like the JSON file) to match the upstream branch
git reset --hard origin/$(git branch --show-current)

# Clean untracked files (optional - remove the -d if you keep untracked logs/config files in this folder)
# git clean -fd 

# Pull to guarantee we are up to date
git pull

# ── 2. Build frontend ─────────────────────────────────────────────────────────
echo ""
echo "==> [2/4] Building frontend..."
cd "$SCRIPT_DIR/frontend"
npm ci --silent
npm run build
echo "    Frontend built → frontend/dist/"

# ── 3. Install / update Python dependencies in venv ──────────────────────────
echo ""
echo "==> [3/4] Updating Python dependencies..."
cd "$SCRIPT_DIR/backend"

# Explicitly use our compiled Python 3.12 path
SYSTEM_PYTHON="/usr/local/bin/python3.12"
VENV_PYTHON=".venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "    No venv found — creating one with $SYSTEM_PYTHON..."
    $SYSTEM_PYTHON -m venv .venv
else
    # Verify versions against our target 3.12 binary instead of global 'python3'
    SYSTEM_VER="$($SYSTEM_PYTHON -c 'import sys; print(sys.version_info[:2])')"
    VENV_VER="$(.venv/bin/python -c 'import sys; print(sys.version_info[:2])')"
    if [ "$SYSTEM_VER" != "$VENV_VER" ]; then
        echo "    Python version changed ($VENV_VER → $SYSTEM_VER) — recreating venv..."
        rm -rf .venv
        $SYSTEM_PYTHON -m venv .venv
    fi
fi

.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "    Python dependencies up to date."

# ── 4. Restart backend ────────────────────────────────────────────────────────
echo ""
echo "==> [4/4] Restarting backend..."
cd "$SCRIPT_DIR/backend"

# Prefer systemd if a unit file for this service exists
if systemctl is-active --quiet upstox-gapdown 2>/dev/null; then
    echo "    Restarting via systemd..."
    sudo systemctl restart upstox-gapdown
    echo "    Backend restarted (systemd)."
else
    # No systemd unit — kill any existing process on port 7778 and relaunch
    echo "    Stopping any existing backend on port 6666..."
    pkill -f "run.py" 2>/dev/null || true
    # Give it a moment to release the port
    sleep 1

    LOG_FILE="$SCRIPT_DIR/backend/logs/backend.log"
    mkdir -p "$SCRIPT_DIR/backend/logs"

    echo "    Starting backend in background (logs → backend/logs/backend.log)..."
    nohup .venv/bin/python run.py >> "$LOG_FILE" 2>&1 &
    BACKEND_PID=$!
    echo "    Backend started (PID $BACKEND_PID)."
    echo "$BACKEND_PID" > "$SCRIPT_DIR/backend/logs/backend.pid"
fi

echo ""
echo "==> Deploy complete."