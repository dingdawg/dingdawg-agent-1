"""MCP tools for usage metering and subscription billing.

Tools
-----
billing.usage      — Get current and historical usage via UsageMeter
billing.subscribe  — Create or upgrade a subscription, optionally
                     returning a Stripe checkout URL

Both tools return the standard ok/err envelope with an MCPReceipt.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from isg_agent.capabilities.shared.foundation import (
    err,
    iso_now,
    make_receipt,
    ok,
)
from isg_agent.payments.usage_meter import PRICING_TIERS, UsageMeter

__all__ = [
    "billing_usage",
    "billing_subscribe",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCPReceipt builder
# ---------------------------------------------------------------------------


def _mcp_receipt(
    action_type: str,
    triggered_by: str,
    outcome: str,
    *,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build an MCPReceipt dict using the shared foundation make_receipt."""
    return make_receipt(
        action_type=action_type,
        triggered_by=triggered_by,
        outcome=outcome,
        timestamp=timestamp or iso_now(),
    )


# ---------------------------------------------------------------------------
# Tool: billing.usage
# ---------------------------------------------------------------------------


async def billing_usage(
    meter: UsageMeter,
    agent_id: str,
    year_month: Optional[str] = None,
    history_months: int = 6,
    triggered_by: str = "mcp_tool",
) -> dict[str, Any]:
    """MCP tool: billing.usage

    Retrieve current usage summary and historical usage data for an agent.

    Parameters
    ----------
    meter:
        The application's UsageMeter instance (injected by the MCP
        dispatcher or FastAPI dependency).
    agent_id:
        The agent whose usage to query.
    year_month:
        Target month in ``"YYYY-MM"`` format.  Defaults to the current
        UTC month when omitted.
    history_months:
        How many months of history to include (default 6, max 24).
    triggered_by:
        Actor identifier for the MCPReceipt.

    Returns
    -------
    dict
        ``ok`` envelope on success::

            {
                "ok": True,
                "data": {
                    "summary": {
                        "year_month": str,
                        "plan": str,
                        "total_actions": int,
                        "free_actions": int,
                        "billed_actions": int,
                        "total_amount_cents": int,
                        "remaining_free": int,
                        "actions_included": int,
                    },
                    "history": [
                        {
                            "year_month": str,
                            "total_actions": int,
                            "free_actions": int,
                            "billed_actions": int,
                            "total_amount_cents": int,
                        },
                        ...
                    ],
                    "pricing_tiers": {tier_name: tier_info, ...},
                },
                "receipt": MCPReceipt,
            }

        ``err`` envelope on failure.
    """
    action_type = "billing.usage"

    if not (1 <= history_months <= 24):
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"history_months must be between 1 and 24, got {history_months}",
        )

    try:
        summary = await meter.get_usage_summary(agent_id, year_month=year_month)
        history = await meter.get_usage_history(agent_id, months=history_months)
    except Exception as exc:
        logger.error(
            "billing.usage MCP tool failed for agent_id=%s: %s", agent_id, exc
        )
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"Usage query failed: {type(exc).__name__}: {exc}",
        )

    receipt = _mcp_receipt(action_type, triggered_by, "executed")
    return ok(
        data={
            "summary": summary,
            "history": history,
            "pricing_tiers": PRICING_TIERS,
        },
        receipt=receipt,
    )


# ---------------------------------------------------------------------------
# Tool: billing.subscribe
# ---------------------------------------------------------------------------


async def billing_subscribe(
    meter: UsageMeter,
    agent_id: str,
    user_id: str,
    plan: str,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
    return_checkout_url: bool = False,
    triggered_by: str = "mcp_tool",
    stripe_client: Optional[Any] = None,
) -> dict[str, Any]:
    """MCP tool: billing.subscribe

    Create or upgrade a subscription for an agent/user pair.  Optionally
    creates a Stripe Checkout session and returns the hosted URL.

    Parameters
    ----------
    meter:
        The application's UsageMeter instance.
    agent_id:
        The agent to subscribe.
    user_id:
        The user who owns the agent.
    plan:
        Target plan name — one of ``free``, ``starter``, ``pro``,
        ``enterprise``.
    stripe_customer_id:
        Existing Stripe Customer ID (``cus_...``).  If empty and
        ``return_checkout_url`` is True, a new customer is created via
        the StripeClient.
    stripe_subscription_id:
        Existing Stripe Subscription ID if already subscribed externally.
    return_checkout_url:
        When True, attempt to create a Stripe Checkout session and include
        the hosted URL in the response.  Requires a configured StripeClient.
    triggered_by:
        Actor identifier for the MCPReceipt.
    stripe_client:
        Optional :class:`~isg_agent.payments.stripe_client.StripeClient`
        instance.  Required when ``return_checkout_url=True``.

    Returns
    -------
    dict
        ``ok`` envelope on success::

            {
                "ok": True,
                "data": {
                    "subscription": {
                        "id": str,
                        "agent_id": str,
                        "user_id": str,
                        "plan": str,
                        "actions_included": int,
                        "price_cents_monthly": int,
                        "current_period_start": str,
                        "current_period_end": str,
                        "is_active": bool,
                    },
                    "checkout_url": str | None,
                    "tier_info": {plan_info dict},
                },
                "receipt": MCPReceipt,
            }

        ``err`` envelope on failure.
    """
    action_type = "billing.subscribe"

    # Validate plan up-front for a clean error message
    if plan not in PRICING_TIERS:
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=(
                f"Invalid plan {plan!r}. "
                f"Valid plans: {sorted(PRICING_TIERS.keys())}"
            ),
        )

    # ------------------------------------------------------------------
    # Create or update subscription record
    # ------------------------------------------------------------------
    try:
        subscription = await meter.create_subscription(
            agent_id=agent_id,
            user_id=user_id,
            plan=plan,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )
    except ValueError as exc:
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=str(exc),
        )
    except Exception as exc:
        logger.error(
            "billing.subscribe MCP tool failed for agent_id=%s user_id=%s: %s",
            agent_id,
            user_id,
            exc,
        )
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"Subscription creation failed: {type(exc).__name__}: {exc}",
        )

    # ------------------------------------------------------------------
    # Optional Stripe Checkout session
    # ------------------------------------------------------------------
    checkout_url: Optional[str] = None

    if return_checkout_url and stripe_client is not None and plan != "free":
        try:
            import stripe as _stripe  # noqa: PLC0415

            tier = PRICING_TIERS[plan]
            price_cents = tier["price_cents_monthly"]

            # Create a Stripe Checkout session (hosted payment page)
            session = _stripe.checkout.Session.create(
                mode="subscription",
                payment_method_types=["card"],
                customer=stripe_customer_id if stripe_customer_id else None,
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": price_cents,
                            "recurring": {"interval": "month"},
                            "product_data": {
                                "name": f"DD Agent 1 — {tier['name']} Plan",
                                "description": (
                                    f"{tier['actions_included']} actions/month"
                                ),
                            },
                        },
                        "quantity": 1,
                    }
                ],
                metadata={
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "plan": plan,
                },
                success_url="https://app.dingdawg.com/billing/success",
                cancel_url="https://app.dingdawg.com/billing/cancel",
            )
            checkout_url = getattr(session, "url", None)
            logger.info(
                "Stripe Checkout session created for agent_id=%s plan=%s",
                agent_id,
                plan,
            )
        except Exception as exc:
            # Non-fatal: subscription record was already saved; log and continue
            logger.warning(
                "billing.subscribe: Stripe Checkout session failed "
                "(subscription still saved): %s",
                exc,
            )

    receipt = _mcp_receipt(action_type, triggered_by, "executed")
    return ok(
        data={
            "subscription": subscription,
            "checkout_url": checkout_url,
            "tier_info": PRICING_TIERS[plan],
        },
        receipt=receipt,
    )
