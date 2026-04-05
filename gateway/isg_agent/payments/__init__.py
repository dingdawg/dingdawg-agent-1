"""Payment processing for ISG Agent 1 — Stripe $1/transaction model.

Provides StripeClient for payment intent creation and webhook verification,
PaymentGate for free-tier gating (5 free messages before payment required),
and UsageMeter for skill-based metered billing ($1/action).
"""

from isg_agent.payments.middleware import PaymentGate
from isg_agent.payments.stripe_client import PaymentResult, StripeClient
from isg_agent.payments.usage_meter import PRICING_TIERS, UsageMeter

__all__ = [
    "PRICING_TIERS",
    "PaymentGate",
    "PaymentResult",
    "StripeClient",
    "UsageMeter",
]
