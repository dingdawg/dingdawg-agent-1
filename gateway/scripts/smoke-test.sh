#!/usr/bin/env bash
# =============================================================================
# DingDawg Agent 1 — Post-Deploy Smoke Test
# =============================================================================
# Quick sanity check to run immediately after `railway up`.
# Tests public endpoints, auth surface, security gating, and key API routes.
#
# Usage:
#   bash scripts/smoke-test.sh
#   bash scripts/smoke-test.sh https://your-custom-backend.up.railway.app
#
# Exit codes:
#   0 — all critical checks passed
#   1 — one or more critical checks failed
#
# Requirements: curl (installed on virtually all Unix systems)
# =============================================================================

set -euo pipefail

BACKEND_URL="${1:-${BACKEND_URL:-https://api.dingdawg.com}}"

# ---------------------------------------------------------------------------
# Colour helpers (disabled when not a TTY)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  RED='' GREEN='' YELLOW='' BLUE='' BOLD='' RESET=''
fi

PASS="${GREEN}[PASS]${RESET}"
FAIL="${RED}[FAIL]${RESET}"
WARN="${YELLOW}[WARN]${RESET}"
INFO="${BLUE}[INFO]${RESET}"

FAILURES=0

# ---------------------------------------------------------------------------
# Helper: HTTP status check
# ---------------------------------------------------------------------------
http_status() {
  curl -s -o /dev/null -w "%{http_code}" \
    --max-time 10 \
    --connect-timeout 5 \
    "$@" 2>/dev/null || echo "000"
}

# ---------------------------------------------------------------------------
# Helper: check response body contains a substring
# ---------------------------------------------------------------------------
body_contains() {
  local url="$1"
  local search="$2"
  curl -sf --max-time 10 --connect-timeout 5 "$url" 2>/dev/null | grep -q "$search"
}

# ---------------------------------------------------------------------------
# Helper: record a critical failure
# ---------------------------------------------------------------------------
fail_critical() {
  local msg="$1"
  echo -e "  ${FAIL} ${msg}"
  FAILURES=$((FAILURES + 1))
}

# ===========================================================================
# HEADER
# ===========================================================================
echo ""
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  DingDawg Agent 1 — Post-Deploy Smoke Test${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo -e "  Backend: ${BOLD}${BACKEND_URL}${RESET}"
echo ""

# ===========================================================================
# 1. Health check
# ===========================================================================
echo -e "${BOLD}--- Core Health ---${RESET}"

if body_contains "${BACKEND_URL}/health" '"status"'; then
  echo -e "  ${PASS} /health — backend responding"
else
  fail_critical "/health — backend not responding or malformed response"
fi

# ===========================================================================
# 2. Onboarding sectors — public endpoint, gaming sector required
# ===========================================================================
echo ""
echo -e "${BOLD}--- Public Endpoints ---${RESET}"

if body_contains "${BACKEND_URL}/api/v1/onboarding/sectors" "gaming"; then
  echo -e "  ${PASS} /api/v1/onboarding/sectors — gaming sector present"
else
  fail_critical "/api/v1/onboarding/sectors — missing or gaming sector absent"
fi

# ===========================================================================
# 3. Templates API — gaming templates required
# ===========================================================================
if body_contains "${BACKEND_URL}/api/v1/templates" "Game Coach"; then
  echo -e "  ${PASS} /api/v1/templates — Game Coach template present"
else
  fail_critical "/api/v1/templates — missing or Game Coach template absent"
fi

# ===========================================================================
# 4. Auth endpoints exist (422 = exists, body validated; 404 = missing)
# ===========================================================================
echo ""
echo -e "${BOLD}--- Auth Surface ---${RESET}"

STATUS=$(http_status -X POST "${BACKEND_URL}/auth/register" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$STATUS" = "422" ]; then
  echo -e "  ${PASS} /auth/register → 422 (exists, body validation working)"
elif [ "$STATUS" = "200" ]; then
  echo -e "  ${WARN} /auth/register → 200 with empty body (unexpected)"
else
  fail_critical "/auth/register → ${STATUS} (expected 422 — may be missing or crashed)"
fi

STATUS=$(http_status -X POST "${BACKEND_URL}/auth/login" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "401" ]; then
  echo -e "  ${PASS} /auth/login → ${STATUS} (exists)"
else
  fail_critical "/auth/login → ${STATUS} (expected 422 or 401)"
fi

STATUS=$(http_status -X POST "${BACKEND_URL}/auth/forgot-password" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$STATUS" = "422" ] || [ "$STATUS" = "200" ]; then
  echo -e "  ${PASS} /auth/forgot-password → ${STATUS} (exists)"
else
  fail_critical "/auth/forgot-password → ${STATUS} (expected 422 or 200)"
fi

# ===========================================================================
# 5. Security gating — docs MUST return 404
# ===========================================================================
echo ""
echo -e "${BOLD}--- Security Gating ---${RESET}"

STATUS=$(http_status "${BACKEND_URL}/docs")
if [ "$STATUS" = "404" ]; then
  echo -e "  ${PASS} /docs → 404 (gated — API schema not exposed)"
else
  fail_critical "/docs → ${STATUS} (CRITICAL: API schema is publicly exposed!)"
fi

STATUS=$(http_status "${BACKEND_URL}/redoc")
if [ "$STATUS" = "404" ]; then
  echo -e "  ${PASS} /redoc → 404 (gated)"
else
  fail_critical "/redoc → ${STATUS} (CRITICAL: redoc is publicly exposed!)"
fi

STATUS=$(http_status "${BACKEND_URL}/openapi.json")
if [ "$STATUS" = "404" ]; then
  echo -e "  ${PASS} /openapi.json → 404 (gated)"
else
  fail_critical "/openapi.json → ${STATUS} (CRITICAL: OpenAPI schema is publicly exposed!)"
fi

# ===========================================================================
# 6. Auth-protected routes (should return 401/403, NOT 404 or 500)
# ===========================================================================
echo ""
echo -e "${BOLD}--- Auth-Protected Routes ---${RESET}"

STATUS=$(http_status "${BACKEND_URL}/api/v1/cli/agents")
if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  echo -e "  ${PASS} /api/v1/cli/agents → ${STATUS} (auth required — correct)"
elif [ "$STATUS" = "404" ]; then
  fail_critical "/api/v1/cli/agents → 404 (route missing)"
else
  echo -e "  ${INFO} /api/v1/cli/agents → ${STATUS}"
fi

STATUS=$(http_status -X POST "${BACKEND_URL}/api/v1/cli/device-code" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$STATUS" = "200" ] || [ "$STATUS" = "422" ]; then
  echo -e "  ${PASS} /api/v1/cli/device-code → ${STATUS} (device flow exists)"
elif [ "$STATUS" = "404" ]; then
  fail_critical "/api/v1/cli/device-code → 404 (route missing)"
else
  echo -e "  ${INFO} /api/v1/cli/device-code → ${STATUS}"
fi

STATUS=$(http_status "${BACKEND_URL}/api/v1/marketplace/templates")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
  echo -e "  ${PASS} /api/v1/marketplace/templates → ${STATUS}"
elif [ "$STATUS" = "404" ]; then
  fail_critical "/api/v1/marketplace/templates → 404 (marketplace route missing)"
else
  echo -e "  ${INFO} /api/v1/marketplace/templates → ${STATUS}"
fi

# ===========================================================================
# 7. Widget endpoint (informational — needs an agent slug to test fully)
# ===========================================================================
echo ""
echo -e "${BOLD}--- Widget / Streaming (informational) ---${RESET}"

STATUS=$(http_status -X POST "${BACKEND_URL}/api/v1/widget/test/message" \
  -H "Content-Type: application/json" \
  -d '{"message":"smoke-test"}')
echo -e "  ${INFO} /api/v1/widget/test/message → ${STATUS}  (401/404 expected without real agent slug)"

STATUS=$(http_status -X POST "${BACKEND_URL}/api/v1/widget/test/stream" \
  -H "Content-Type: application/json" \
  -d '{"message":"smoke-test","session_id":"smoke"}')
echo -e "  ${INFO} /api/v1/widget/test/stream → ${STATUS}  (streaming — any non-500 is acceptable)"

# ===========================================================================
# 8. Stripe billing surface (informational — webhook needs real signature)
# ===========================================================================
echo ""
echo -e "${BOLD}--- Stripe Billing (informational) ---${RESET}"

STATUS=$(http_status -X POST "${BACKEND_URL}/api/v1/billing/webhook" \
  -H "Content-Type: application/json" \
  -d '{"type":"test"}')
if [ "$STATUS" = "400" ] || [ "$STATUS" = "403" ] || [ "$STATUS" = "422" ]; then
  echo -e "  ${PASS} /api/v1/billing/webhook → ${STATUS} (exists, rejects unsigned payload)"
elif [ "$STATUS" = "404" ]; then
  fail_critical "/api/v1/billing/webhook → 404 (Stripe webhook route missing)"
else
  echo -e "  ${INFO} /api/v1/billing/webhook → ${STATUS}"
fi

# ===========================================================================
# SUMMARY
# ===========================================================================
echo ""
echo -e "${BOLD}------------------------------------------------------------${RESET}"
if [ "$FAILURES" -eq 0 ]; then
  echo -e "  ${PASS} ${BOLD}All smoke tests passed. Deploy looks healthy.${RESET}"
else
  echo -e "  ${FAIL} ${BOLD}${FAILURES} critical check(s) failed. Investigate before sending traffic.${RESET}"
fi
echo -e "${BOLD}------------------------------------------------------------${RESET}"
echo ""

exit "$FAILURES"
