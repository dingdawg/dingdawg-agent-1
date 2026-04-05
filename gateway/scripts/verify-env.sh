#!/usr/bin/env bash
# =============================================================================
# DingDawg Agent 1 — Pre-Deploy Environment Verification
# =============================================================================
# Run this before every `railway up` + `vercel --prod` to catch missing env
# vars before they cause silent production failures.
#
# Usage:
#   bash scripts/verify-env.sh
#   ./scripts/verify-env.sh
#
# Exit codes:
#   0 — all REQUIRED vars present (warnings may still be printed)
#   1 — one or more REQUIRED vars are missing
#
# Env vars are read from the CURRENT SHELL ENVIRONMENT.
# To test against a .env file:
#   set -a; source .env; set +a; bash scripts/verify-env.sh
# =============================================================================

set -euo pipefail

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

# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
MISSING_REQUIRED=0
MISSING_RECOMMENDED=0

# ---------------------------------------------------------------------------
# Helper: check a required variable
# ---------------------------------------------------------------------------
require_var() {
  local name="$1"
  local description="$2"
  local value="${!name:-}"

  if [ -z "$value" ]; then
    echo -e "  ${FAIL} ${BOLD}${name}${RESET} — ${description}"
    MISSING_REQUIRED=$((MISSING_REQUIRED + 1))
  else
    # Mask the value for secrets — show only first 4 chars
    local masked
    masked="${value:0:4}$(printf '*%.0s' {1..8})"
    echo -e "  ${PASS} ${BOLD}${name}${RESET} = ${masked}  (${description})"
  fi
}

# ---------------------------------------------------------------------------
# Helper: check a recommended variable
# ---------------------------------------------------------------------------
recommend_var() {
  local name="$1"
  local description="$2"
  local value="${!name:-}"

  if [ -z "$value" ]; then
    echo -e "  ${WARN} ${BOLD}${name}${RESET} — ${description}"
    MISSING_RECOMMENDED=$((MISSING_RECOMMENDED + 1))
  else
    local masked
    masked="${value:0:4}$(printf '*%.0s' {1..8})"
    echo -e "  ${PASS} ${BOLD}${name}${RESET} = ${masked}  (${description})"
  fi
}

# ---------------------------------------------------------------------------
# Helper: check a variable equals an expected value
# ---------------------------------------------------------------------------
expect_value() {
  local name="$1"
  local expected="$2"
  local description="$3"
  local value="${!name:-}"

  if [ -z "$value" ]; then
    echo -e "  ${WARN} ${BOLD}${name}${RESET} not set — ${description}"
    MISSING_RECOMMENDED=$((MISSING_RECOMMENDED + 1))
  elif [ "$value" = "$expected" ]; then
    echo -e "  ${PASS} ${BOLD}${name}${RESET} = \"${value}\"  (${description})"
  else
    echo -e "  ${WARN} ${BOLD}${name}${RESET} = \"${value}\" (expected \"${expected}\") — ${description}"
    MISSING_RECOMMENDED=$((MISSING_RECOMMENDED + 1))
  fi
}

# ---------------------------------------------------------------------------
# Helper: assert a variable does NOT equal a forbidden value
# ---------------------------------------------------------------------------
forbid_value() {
  local name="$1"
  local forbidden="$2"
  local description="$3"
  local value="${!name:-}"

  if [ "$value" = "$forbidden" ]; then
    echo -e "  ${FAIL} ${BOLD}${name}${RESET} = \"${value}\" — ${description}"
    MISSING_REQUIRED=$((MISSING_REQUIRED + 1))
  elif [ -z "$value" ]; then
    echo -e "  ${WARN} ${BOLD}${name}${RESET} not set — ${description}"
    MISSING_RECOMMENDED=$((MISSING_RECOMMENDED + 1))
  else
    echo -e "  ${PASS} ${BOLD}${name}${RESET} = \"${value}\"  (${description})"
  fi
}

# ===========================================================================
# HEADER
# ===========================================================================
echo ""
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  DingDawg Agent 1 — Pre-Deploy Environment Verification${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo ""

# ===========================================================================
# SECTION 1 — Backend env vars (Railway)
# ===========================================================================
echo -e "${BOLD}--- Backend (Railway) ---${RESET}"
echo ""

require_var  "ISG_AGENT_OPENAI_API_KEY"         "LLM calls — GPT-4o mini inference"
require_var  "ISG_AGENT_JWT_SECRET"             "JWT signing — auth token security"
require_var  "ISG_AGENT_STRIPE_SECRET_KEY"      "Stripe payments — \$1/action billing"
require_var  "ISG_AGENT_STRIPE_WEBHOOK_SECRET"  "Stripe webhook signature verification"
require_var  "ISG_AGENT_FRONTEND_URL"           "CORS allow-origin + email link base URL"

recommend_var "ISG_AGENT_TURNSTILE_SECRET_KEY"  "Cloudflare Turnstile server-side verify (\$0/1M checks)"
recommend_var "ISG_AGENT_SENDGRID_API_KEY"      "Transactional email delivery"

# S35: Inbound webhook credentials
recommend_var "ISG_AGENT_SENDGRID_INBOUND_USER" "SendGrid Inbound Parse Basic Auth username"
recommend_var "ISG_AGENT_SENDGRID_INBOUND_PASS" "SendGrid Inbound Parse Basic Auth password"
recommend_var "ISG_AGENT_TWILIO_AUTH_TOKEN"      "Twilio webhook HMAC-SHA1 signature validation"

# S34: Integration API keys (optional — features degrade gracefully without these)
recommend_var "ISG_AGENT_GOOGLE_CLIENT_ID"       "Google Calendar OAuth2 client ID"
recommend_var "ISG_AGENT_GOOGLE_CLIENT_SECRET"   "Google Calendar OAuth2 client secret"
recommend_var "ISG_AGENT_VAPI_API_KEY"           "Vapi voice integration API key"
recommend_var "ISG_AGENT_TWILIO_ACCOUNT_SID"     "Twilio account SID for outbound SMS"
recommend_var "ISG_AGENT_TWILIO_FROM_NUMBER"     "Twilio E.164 phone number for outbound SMS"

expect_value  "ISG_AGENT_WORKERS" "1"           "Must be 1 for SQLite (no connection sharing)"

forbid_value  "ISG_AGENT_DEPLOYMENT_ENV" "test" "MUST NOT be 'test' in production — disables ALL bot prevention"

echo ""

# ===========================================================================
# SECTION 2 — Frontend env vars (Vercel)
# ===========================================================================
echo -e "${BOLD}--- Frontend (Vercel) ---${RESET}"
echo ""

require_var   "BACKEND_URL"                     "Next.js API proxy target (e.g. https://...railway.app)"
recommend_var "NEXT_PUBLIC_TURNSTILE_SITE_KEY"  "Cloudflare Turnstile client-side challenge key"
recommend_var "NEXT_PUBLIC_APP_NAME"            "App display name (optional branding)"

echo ""

# ===========================================================================
# SECTION 3 — Production URL reminder
# ===========================================================================
echo -e "${BOLD}--- Deployment URLs (manual verification) ---${RESET}"
echo ""
echo -e "  ${INFO} Railway Backend  : https://api.dingdawg.com"
echo -e "  ${INFO} Vercel Frontend  : https://ding-dawg-agent-1.vercel.app"
echo -e "  ${INFO} Health endpoint  : https://api.dingdawg.com/health"
echo -e "  ${INFO} Docs (should 404): https://api.dingdawg.com/docs"
echo ""
echo -e "  After deploying, run:  bash scripts/smoke-test.sh"
echo ""

# ===========================================================================
# SUMMARY
# ===========================================================================
echo -e "${BOLD}------------------------------------------------------------${RESET}"

if [ "$MISSING_REQUIRED" -gt 0 ]; then
  echo -e "  ${FAIL} ${BOLD}${MISSING_REQUIRED} REQUIRED variable(s) missing — deploy will be broken${RESET}"
fi

if [ "$MISSING_RECOMMENDED" -gt 0 ]; then
  echo -e "  ${WARN} ${MISSING_RECOMMENDED} recommended variable(s) missing — functionality degraded"
fi

if [ "$MISSING_REQUIRED" -eq 0 ] && [ "$MISSING_RECOMMENDED" -eq 0 ]; then
  echo -e "  ${PASS} ${BOLD}All variables set. Safe to deploy.${RESET}"
elif [ "$MISSING_REQUIRED" -eq 0 ]; then
  echo -e "  ${PASS} All REQUIRED variables set. Warnings noted above."
fi

echo -e "${BOLD}------------------------------------------------------------${RESET}"
echo ""

exit "$MISSING_REQUIRED"
