#!/usr/bin/env bash
# setup-stripe.sh — DingDawg one-time Stripe product + price + meter setup
# Run once after adding STRIPE_SECRET_KEY to your .env
# Output: .env.stripe with all generated price IDs and meter ID

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
OUTPUT_FILE="${SCRIPT_DIR}/.env.stripe"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  DingDawg Stripe Setup Script            ║"
echo "║  Creates products, prices, usage meter   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Load .env if present ────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
  export $(grep -v '^#' "$ENV_FILE" | grep '=' | xargs)
  echo "✓ Loaded .env"
fi

# ── Validate key ────────────────────────────────────────────────────────────
if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
  echo "✗ STRIPE_SECRET_KEY is not set."
  echo "  Add it to your .env file: STRIPE_SECRET_KEY=sk_live_..."
  exit 1
fi

if [[ "$STRIPE_SECRET_KEY" != sk_* ]]; then
  echo "✗ STRIPE_SECRET_KEY doesn't look valid (must start with sk_)"
  exit 1
fi

MODE="LIVE"
[[ "$STRIPE_SECRET_KEY" == sk_test_* ]] && MODE="TEST"
echo "✓ Stripe key validated (${MODE} mode)"
echo ""

# ── Check/install stripe Python SDK ─────────────────────────────────────────
if ! python3 -c "import stripe" 2>/dev/null; then
  echo "Installing stripe Python SDK..."
  pip install stripe --quiet
fi
echo "✓ stripe SDK ready"
echo ""

# ── Run the Python setup ─────────────────────────────────────────────────────
python3 - << PYEOF
import stripe
import os
import json

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

results = {}

def find_or_create_product(name, description, metadata_key):
    """Find existing DingDawg product by metadata, or create new one."""
    existing = stripe.Product.search(query=f'metadata["dingdawg_product"]:"{metadata_key}"')
    if existing.data:
        print(f"  ↩  Found existing product: {name} ({existing.data[0].id})")
        return existing.data[0]
    product = stripe.Product.create(
        name=name,
        description=description,
        metadata={"dingdawg_product": metadata_key, "platform": "dingdawg"},
    )
    print(f"  ✓  Created product: {name} ({product.id})")
    return product

def find_or_create_price(product_id, amount, interval, interval_count, label, metadata_key):
    """Find existing price or create new one. interval='month', interval_count=1 or 12."""
    existing = stripe.Price.search(
        query=f'metadata["dingdawg_price"]:"{metadata_key}" AND active:"true"'
    )
    if existing.data:
        print(f"    ↩  Found existing price: {label} ({existing.data[0].id})")
        return existing.data[0].id
    price = stripe.Price.create(
        product=product_id,
        unit_amount=amount,
        currency="usd",
        recurring={"interval": interval, "interval_count": interval_count},
        metadata={"dingdawg_price": metadata_key, "platform": "dingdawg", "label": label},
    )
    print(f"    ✓  Created price: {label} \${amount/100:.0f} ({price.id})")
    return price.id

def find_or_create_meter(event_name, meter_name):
    """Find existing meter or create new one."""
    try:
        existing = stripe.billing.Meter.list(status="active")
        for m in existing.data:
            if m.event_name == event_name:
                print(f"  ↩  Found existing meter: {meter_name} ({m.id})")
                return m.id
    except Exception:
        pass
    meter = stripe.billing.Meter.create(
        display_name=meter_name,
        event_name=event_name,
        customer_mapping={"type": "by_id", "event_payload_key": "stripe_customer_id"},
        value_settings={"event_payload_key": "value"},
        default_aggregation={"formula": "sum"},
    )
    print(f"  ✓  Created meter: {meter_name} ({meter.id})")
    return meter.id

# ── Pro ──────────────────────────────────────────────────────────────────────
print("Creating Pro product...")
pro = find_or_create_product("DingDawg Pro", "100 agent calls/day, premium models, priority support", "pro")
results["STRIPE_PRICE_PRO_MONTHLY"]  = find_or_create_price(pro.id, 4900,  "month", 1,  "Pro Monthly \$49",      "pro_monthly")
results["STRIPE_PRICE_PRO_ANNUAL"]   = find_or_create_price(pro.id, 46800, "year",  1,  "Pro Annual \$468/yr",   "pro_annual")

# ── Team ─────────────────────────────────────────────────────────────────────
print("Creating Team product...")
team = find_or_create_product("DingDawg Team", "300 agent calls/day, 5 seats, audit export", "team")
results["STRIPE_PRICE_TEAM_MONTHLY"]  = find_or_create_price(team.id, 14900, "month", 1, "Team Monthly \$149",    "team_monthly")
results["STRIPE_PRICE_TEAM_ANNUAL"]   = find_or_create_price(team.id, 142800, "year", 1, "Team Annual \$1,428/yr","team_annual")

# ── Enterprise ───────────────────────────────────────────────────────────────
print("Creating Enterprise product...")
ent = find_or_create_product("DingDawg Enterprise", "1,000 agent calls/day, 10 seats, SLA, dedicated support", "enterprise")
results["STRIPE_PRICE_ENTERPRISE_MONTHLY"]  = find_or_create_price(ent.id, 49900,  "month", 1, "Enterprise Monthly \$499",    "enterprise_monthly")
results["STRIPE_PRICE_ENTERPRISE_ANNUAL"]   = find_or_create_price(ent.id, 478800, "year",  1, "Enterprise Annual \$4,788/yr","enterprise_annual")

# ── Usage Meter ──────────────────────────────────────────────────────────────
print("Creating usage meter...")
results["STRIPE_METER_ID_AGENT_CALLS"] = find_or_create_meter("agent_calls", "Agent Calls")

# ── Write output ─────────────────────────────────────────────────────────────
output_path = os.path.join(os.path.dirname(os.environ.get("STRIPE_SECRET_KEY", "")) or ".", ".env.stripe")
output_path = "$OUTPUT_FILE"

lines = ["# Generated by setup-stripe.sh — copy into your .env", ""]
for key, val in results.items():
    lines.append(f"{key}={val}")

with open(output_path, "w") as f:
    f.write("\n".join(lines) + "\n")

print()
print("Results:")
for k, v in results.items():
    print(f"  {k}={v}")

print()
print(f"✅ Written to: {output_path}")
PYEOF

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Setup complete!                                             ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Next steps:                                                 ║"
echo "║  1. cat .env.stripe                                          ║"
echo "║  2. Copy those lines into your .env file                     ║"
echo "║  3. Run: vercel env add (each key) for your website          ║"
echo "║  4. Register webhook in Stripe dashboard:                    ║"
echo "║     URL: https://dingdawg.com/api/stripe-webhook             ║"
echo "║     Events: checkout.session.completed,                      ║"
echo "║             customer.subscription.*,                         ║"
echo "║             invoice.paid, invoice.payment_failed             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
