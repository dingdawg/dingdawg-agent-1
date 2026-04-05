#!/bin/bash
# DingDawg Agent 1 — Python Environment Setup Script
# Run from: ~/Desktop/DingDawg-Agent-1/gateway/
# Usage: bash setup_env.sh

set -euo pipefail

GATEWAY_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=== DingDawg Agent 1 — Environment Setup ==="
echo "Gateway dir: $GATEWAY_DIR"

# Step 1: Remove old broken venv
if [ -d "$GATEWAY_DIR/.venv" ]; then
    echo "[1/5] Removing old broken venv..."
    rm -rf "$GATEWAY_DIR/.venv"
fi

# Step 2: Create fresh venv
echo "[2/5] Creating Python virtual environment..."
python3 -m venv "$GATEWAY_DIR/.venv"
echo "  Created .venv/ with $(python3 --version)"

# Step 3: Upgrade pip, setuptools, wheel
echo "[3/5] Upgrading pip, setuptools, wheel..."
"$GATEWAY_DIR/.venv/bin/pip" install --upgrade pip setuptools wheel 2>&1 | tail -3

# Step 4: Install project in editable mode with dev dependencies
echo "[4/5] Installing isg-agent in editable mode with dev deps..."
cd "$GATEWAY_DIR"
"$GATEWAY_DIR/.venv/bin/pip" install -e ".[dev]" 2>&1 | tail -10

# Step 5: Verify
echo "[5/5] Verifying installation..."

echo ""
echo "--- Import Check ---"
"$GATEWAY_DIR/.venv/bin/python3" -c "import isg_agent; print('  isg_agent: OK')" 2>&1 || echo "  isg_agent: FAILED"

"$GATEWAY_DIR/.venv/bin/python3" -c "
from isg_agent.core import audit, governance, convergence, constitution, time_lock, security
print('  All 6 core modules: OK')
" 2>&1 || echo "  Core module import: FAILED (see error above)"

echo ""
echo "--- Installed Packages ---"
"$GATEWAY_DIR/.venv/bin/pip" list --format=columns 2>&1

echo ""
echo "--- Test Discovery ---"
cd "$GATEWAY_DIR"
"$GATEWAY_DIR/.venv/bin/python3" -m pytest tests/ -v --co 2>&1 | tail -30

echo ""
echo "=== Setup Complete ==="
echo "To activate: source $GATEWAY_DIR/.venv/bin/activate"
echo "To run tests: cd $GATEWAY_DIR && .venv/bin/python -m pytest tests/ -v"
