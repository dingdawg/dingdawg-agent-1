#!/usr/bin/env bash
# =============================================================================
# DingDawg Agent 1 — Post-Deploy Verification
# =============================================================================
# Run immediately after ANY deploy (railway up, vercel --prod, env var change).
# Detects:
#   1. Backend down (Railway deploy didn't come up)
#   2. Domain mismatch (Vercel BACKEND_URL still points to old dead Railway URL)
#   3. Auth layer failure (JWT middleware not running)
#   4. Security regression (docs endpoint accidentally exposed)
#   5. Proxy routing failure (Vercel rewrites not forwarding to Railway)
#
# Usage:
#   bash scripts/deploy_check.sh              # check both Railway + Vercel
#   bash scripts/deploy_check.sh railway      # check Railway backend only
#   bash scripts/deploy_check.sh vercel       # check Vercel frontend + proxy only
#   bash scripts/deploy_check.sh --help
#
# Exit codes:
#   0 — all checks passed
#   N — N critical check(s) failed
#
# Requirements: curl (pre-installed on all Unix systems)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Production URLs — update RAILWAY if the Railway domain changes.
# Updating this single variable is the ONLY manual step after a domain change.
# ---------------------------------------------------------------------------
RAILWAY="${BACKEND_URL:-https://api.dingdawg.com}"
VERCEL="https://app.dingdawg.com"
OLD_RAILWAY="https://isg-agent-production.up.railway.app"

# ---------------------------------------------------------------------------
# Colour helpers (disabled when stdout is not a TTY, e.g. CI logs)
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

PASS_TAG="${GREEN}[PASS]${RESET}"
FAIL_TAG="${RED}[FAIL]${RESET}"
WARN_TAG="${YELLOW}[WARN]${RESET}"
INFO_TAG="${BLUE}[INFO]${RESET}"

PASS=0
FAIL=0
WARN=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# http_status <url> [extra curl flags...]
# Returns the HTTP status code, or "000" if curl failed/timed out.
http_status() {
  local url="$1"
  shift
  curl -s -o /dev/null -w "%{http_code}" \
    --connect-timeout 10 \
    --max-time 15 \
    "$@" \
    "$url" 2>/dev/null || echo "000"
}

# check_critical <name> <url> <expected_status> [extra curl flags...]
# Fails if status != expected. Increments FAIL counter.
check_critical() {
  local name="$1"
  local url="$2"
  local expected="$3"
  shift 3
  local status
  status=$(http_status "$url" "$@")
  if [ "$status" = "$expected" ]; then
    echo -e "  ${PASS_TAG} ${name}: ${status}"
    PASS=$((PASS + 1))
  else
    echo -e "  ${FAIL_TAG} ${name}: got ${status}, expected ${expected}"
    echo -e "         URL: ${url}"
    FAIL=$((FAIL + 1))
  fi
}

# check_warn <name> <url> <expected_status> [extra curl flags...]
# Reports as WARN if status != expected. Does NOT increment FAIL.
check_warn() {
  local name="$1"
  local url="$2"
  local expected="$3"
  shift 3
  local status
  status=$(http_status "$url" "$@")
  if [ "$status" = "$expected" ]; then
    echo -e "  ${PASS_TAG} ${name}: ${status}"
    PASS=$((PASS + 1))
  else
    echo -e "  ${WARN_TAG} ${name}: got ${status}, expected ${expected} (informational)"
    WARN=$((WARN + 1))
  fi
}

# check_dead <name> <url>
# PASSes if the URL is unreachable (000) or returns non-200.
# FAILs if the URL returns 200 (old domain resurrected).
check_dead() {
  local name="$1"
  local url="$2"
  local status
  status=$(http_status "$url")
  if [ "$status" = "200" ]; then
    echo -e "  ${FAIL_TAG} ${name}: returned 200 (OLD DOMAIN IS ALIVE — traffic may route there)"
    echo -e "         URL: ${url}"
    FAIL=$((FAIL + 1))
  else
    echo -e "  ${PASS_TAG} ${name}: ${status} (dead/redirected — correct)"
    PASS=$((PASS + 1))
  fi
}

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo ""
  echo "Usage: bash scripts/deploy_check.sh [railway|vercel|both] [--help]"
  echo ""
  echo "  railway  — check Railway backend only"
  echo "  vercel   — check Vercel frontend + proxy only"
  echo "  both     — check everything (default)"
  echo ""
  echo "Run after: railway up, vercel --prod, or any BACKEND_URL env var change."
  echo ""
  exit 0
fi

TARGET="${1:-both}"

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  DingDawg Agent 1 — Post-Deploy Verification${RESET}"
echo -e "${BOLD}  $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
echo -e "${BOLD}============================================================${RESET}"

# ===========================================================================
# SECTION 1 — Railway Backend
# Checks: health, auth layer, security gating, key public endpoints
# ===========================================================================
if [ "$TARGET" = "railway" ] || [ "$TARGET" = "both" ]; then
  echo ""
  echo -e "${BOLD}--- Railway Backend (${RAILWAY}) ---${RESET}"
  echo ""

  # Core liveness
  check_critical "Health endpoint"         "$RAILWAY/health"                     "200"

  # Auth layer running
  check_critical "Admin auth gate"         "$RAILWAY/api/v1/admin/whoami"        "401"
  check_critical "Auth refresh exists"     "$RAILWAY/auth/refresh"               "405"

  # Security gating — these MUST stay 404 in production
  check_critical "Docs gated (not public)" "$RAILWAY/docs"                       "404"
  check_critical "Redoc gated"             "$RAILWAY/redoc"                      "404"
  check_critical "OpenAPI gated"           "$RAILWAY/openapi.json"               "404"

  # Public endpoints
  check_critical "Onboarding sectors"      "$RAILWAY/api/v1/onboarding/sectors"  "200"
  check_critical "Templates public"        "$RAILWAY/api/v1/templates"           "200"

  # Auth endpoint existence (POST-only — send empty JSON to trigger 422 body validation)
  echo ""
  echo -e "  ${INFO_TAG} Checking auth endpoint existence (POST endpoints)..."

  status=$(http_status "$RAILWAY/auth/register" \
    -X POST \
    -H "Content-Type: application/json" \
    -d '{}')
  if [ "$status" = "422" ]; then
    echo -e "  ${PASS_TAG} /auth/register: 422 (exists, body validation working)"
    PASS=$((PASS + 1))
  elif [ "$status" = "200" ] || [ "$status" = "400" ]; then
    echo -e "  ${WARN_TAG} /auth/register: ${status} (exists but unexpected status)"
    WARN=$((WARN + 1))
  else
    echo -e "  ${FAIL_TAG} /auth/register: ${status} (expected 422 — route may be missing)"
    FAIL=$((FAIL + 1))
  fi

  status=$(http_status "$RAILWAY/auth/login" \
    -X POST \
    -H "Content-Type: application/json" \
    -d '{}')
  if [ "$status" = "422" ] || [ "$status" = "401" ]; then
    echo -e "  ${PASS_TAG} /auth/login: ${status} (exists)"
    PASS=$((PASS + 1))
  else
    echo -e "  ${FAIL_TAG} /auth/login: ${status} (expected 422 or 401)"
    FAIL=$((FAIL + 1))
  fi

  # Auth-protected routes must return 401/403, NOT 404 (route missing) or 500 (crash)
  echo ""
  echo -e "  ${INFO_TAG} Checking auth-protected routes return 401/403 (not 404/500)..."

  for route in \
    "/api/v1/cli/agents" \
    "/api/v1/marketplace/templates" \
    "/api/v1/billing/plans"; do
    status=$(http_status "$RAILWAY${route}")
    if [ "$status" = "401" ] || [ "$status" = "403" ] || [ "$status" = "200" ]; then
      echo -e "  ${PASS_TAG} ${route}: ${status}"
      PASS=$((PASS + 1))
    elif [ "$status" = "404" ]; then
      echo -e "  ${FAIL_TAG} ${route}: 404 (route missing from build)"
      FAIL=$((FAIL + 1))
    else
      echo -e "  ${WARN_TAG} ${route}: ${status} (unexpected — investigate if persistent)"
      WARN=$((WARN + 1))
    fi
  done
fi

# ===========================================================================
# SECTION 2 — Vercel Frontend + Proxy
# The domain mismatch check is here: if Railway is healthy but these proxy
# checks fail, BACKEND_URL env var in Vercel is almost certainly stale.
# ===========================================================================
if [ "$TARGET" = "vercel" ] || [ "$TARGET" = "both" ]; then
  echo ""
  echo -e "${BOLD}--- Vercel Frontend (${VERCEL}) ---${RESET}"
  echo ""

  # Basic frontend liveness
  check_critical "Frontend homepage"   "$VERCEL"             "200"
  check_critical "Login page"          "$VERCEL/login"       "200"
  check_critical "Admin page"          "$VERCEL/admin"       "200"

  # Proxy checks — these test Vercel's BACKEND_URL env var is correct.
  # A 502 here with Railway healthy = domain mismatch.
  echo ""
  echo -e "  ${INFO_TAG} Proxy checks (502 here = Vercel BACKEND_URL is stale)..."

  check_critical "Proxy→/health"        "$VERCEL/health"        "200"
  check_critical "Proxy→/auth/refresh"  "$VERCEL/auth/refresh"  "405"
  check_critical "Proxy→/api/v1/templates" "$VERCEL/api/v1/templates" "200"
fi

# ===========================================================================
# SECTION 3 — Old Domain Resurrection Check
# If old Railway domain returns 200, traffic may accidentally route there.
# ===========================================================================
if [ "$TARGET" = "both" ]; then
  echo ""
  echo -e "${BOLD}--- Old Domain (should be dead) ---${RESET}"
  echo ""
  check_dead "Old Railway URL" "$OLD_RAILWAY/health"
fi

# ===========================================================================
# DOMAIN MISMATCH DIAGNOSIS
# If Railway is up but Vercel proxy is down, print actionable diagnosis.
# ===========================================================================
if [ "$TARGET" = "both" ] && [ "$FAIL" -gt 0 ]; then
  # Re-probe the two signals silently
  railway_status=$(http_status "$RAILWAY/health")
  proxy_status=$(http_status "$VERCEL/health")

  if [ "$railway_status" = "200" ] && [ "$proxy_status" != "200" ]; then
    echo ""
    echo -e "${RED}${BOLD}*** DOMAIN MISMATCH DETECTED ***${RESET}"
    echo -e "  Railway backend is UP (${railway_status}) but Vercel proxy returned ${proxy_status}."
    echo -e "  Root cause: Vercel BACKEND_URL env var likely points to old/dead Railway domain."
    echo ""
    echo -e "  ${BOLD}Fix:${RESET}"
    echo -e "    1. Open Vercel dashboard → Project → Settings → Environment Variables"
    echo -e "    2. Update BACKEND_URL to: ${RAILWAY}"
    echo -e "    3. Redeploy Vercel: vercel --prod"
    echo -e "    4. Re-run this script"
  fi
fi

# ===========================================================================
# SUMMARY
# ===========================================================================
echo ""
echo -e "${BOLD}============================================================${RESET}"
echo -e "  Results: ${GREEN}${PASS} passed${RESET}, ${RED}${FAIL} failed${RESET}, ${YELLOW}${WARN} warnings${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo ""

if [ "$FAIL" -gt 0 ]; then
  # Best-effort desktop notification — ignored if notify-send is absent
  notify-send --urgency=critical \
    "DingDawg Deploy Check" \
    "${FAIL} check(s) FAILED — see terminal" 2>/dev/null || true
  exit "$FAIL"
fi

exit 0
