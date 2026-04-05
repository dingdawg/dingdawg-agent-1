#!/usr/bin/env bash
# =============================================================================
# DingDawg Agent 1 — Docker Health Check Script
# =============================================================================
# Used by Docker HEALTHCHECK to verify the application is responsive.
# Returns exit 0 (healthy) or exit 1 (unhealthy).
# =============================================================================

PORT="${PORT:-${ISG_AGENT_PORT:-8900}}"

# Attempt to reach the health endpoint with a 3-second timeout
response=$(curl -sf --max-time 3 "http://localhost:${PORT}/health" 2>/dev/null) || exit 1

# Verify the response contains a healthy status
# The /health endpoint returns: {"status": "healthy", ...}
echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if data.get('status') in ('healthy', 'degraded'):
        sys.exit(0)
    else:
        print(f'Unhealthy status: {data.get(\"status\")}', file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'Health check parse error: {e}', file=sys.stderr)
    sys.exit(1)
"
