#!/usr/bin/env bash
# =============================================================================
# DingDawg Agent 1 — Production Startup Script
# =============================================================================
# This script:
#   1. Sets sensible defaults for environment variables
#   2. Creates the data directory for SQLite if it doesn't exist
#   3. Initializes the database schema (idempotent — safe on every boot)
#   4. Starts uvicorn via exec (tini handles signal forwarding in Docker)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Vault key injection (QuantumVault — Kyber768 + AES-256-GCM)
# Loads ISG_AGENT_SECRET_KEY + STRIPE_SECRET_KEY from ~/.mila/luxe_vault.enc.
# Fail-open: if vault is unavailable, falls back to existing env (e.g. Railway vars).
# ---------------------------------------------------------------------------
GATEWAY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT_LOADER="$GATEWAY_DIR/vault_loader_gateway.py"
if [ -f "$VAULT_LOADER" ]; then
    vault_exports="$(python3 "$VAULT_LOADER" 2>/dev/null)" || true
    if [ -n "$vault_exports" ]; then
        eval "$vault_exports"
        echo "  [vault] Gateway keys loaded from QuantumVault"
    else
        echo "  [vault] WARNING: vault_loader returned empty — using existing env"
    fi
else
    echo "  [vault] WARNING: vault_loader_gateway.py not found — using existing env"
fi

# ---------------------------------------------------------------------------
# Defaults (overridable via environment)
# ---------------------------------------------------------------------------
HOST="${ISG_AGENT_HOST:-0.0.0.0}"
PORT="${PORT:-${ISG_AGENT_PORT:-8900}}"
LOG_LEVEL="${ISG_AGENT_LOG_LEVEL:-info}"
DB_PATH="${ISG_AGENT_DB_PATH:-./data/agent.db}"
WORKERS="${ISG_AGENT_WORKERS:-}"

# Calculate default worker count: 2 * CPU cores + 1 (capped at 4 for SQLite)
if [ -z "$WORKERS" ]; then
    CPU_COUNT=$(python3 -c "import os; print(os.cpu_count() or 1)")
    WORKERS=$(( 2 * CPU_COUNT + 1 ))
    # Cap at 4 workers — SQLite write-lock means more workers don't help
    if [ "$WORKERS" -gt 4 ]; then
        WORKERS=4
    fi
fi

echo "=== DingDawg Agent 1 — Starting ==="
echo "  Host:      $HOST"
echo "  Port:      $PORT"
echo "  Workers:   $WORKERS"
echo "  Log level: $LOG_LEVEL"
echo "  DB path:   $DB_PATH"

# ---------------------------------------------------------------------------
# Step 1: Create data directory (handle Railway volume permissions)
# ---------------------------------------------------------------------------
DB_DIR=$(dirname "$DB_PATH")
if [ ! -d "$DB_DIR" ]; then
    echo "  Creating data directory: $DB_DIR"
    mkdir -p "$DB_DIR"
fi

# Railway volumes mount as root-owned — ensure writable
if [ ! -w "$DB_DIR" ]; then
    echo "  WARNING: $DB_DIR not writable, attempting chmod..."
    if ! chmod 777 "$DB_DIR" 2>/dev/null; then
        echo "  ERROR: Cannot make $DB_DIR writable. Volume permission denied."
        echo "  Container must run as root or volume must be owned by container UID."
        echo "  Fix: Remove USER directive from Dockerfile or chown the volume."
        exit 1
    fi
    # Verify the chmod actually worked
    if [ ! -w "$DB_DIR" ]; then
        echo "  ERROR: $DB_DIR still not writable after chmod. Aborting."
        exit 1
    fi
    echo "  $DB_DIR is now writable."
fi

# ---------------------------------------------------------------------------
# Step 2: Initialize database schema (idempotent — CREATE IF NOT EXISTS)
# ---------------------------------------------------------------------------
echo "  Initializing database schema..."
python3 -c "
import asyncio
from isg_agent.db.engine import Database

async def init():
    db = Database(db_path='${DB_PATH}')
    await db.init()
    await db.close()
    print('  Database schema ready.')

asyncio.run(init())
"

# ---------------------------------------------------------------------------
# Step 3: Start uvicorn
# ---------------------------------------------------------------------------
# Using exec replaces the shell process with uvicorn, so uvicorn becomes PID 1
# (or the direct child of tini in Docker). This ensures SIGTERM from Docker
# is delivered directly to uvicorn for graceful shutdown of worker processes.
echo "  Starting uvicorn..."

exec uvicorn isg_agent.app:create_app \
    --factory \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --log-level "$LOG_LEVEL" \
    --access-log \
    --proxy-headers \
    --forwarded-allow-ips='*'
