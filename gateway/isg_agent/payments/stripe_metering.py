"""Stripe Usage Metering — records agent_calls meter events.

Every time a user invokes an agent, call record_agent_call().
This sends a meter event to Stripe for usage-based billing.

Meter name: agent_calls
Event name: agent_calls
Customer mapping: by_id (stripe_customer_id)

Usage:
    meter = StripeMeteringClient()
    await meter.record_agent_call(stripe_customer_id="cus_xxx", quantity=1, agent_id="compliance")

Stripe API key resolution order:
    1. Explicit api_key argument
    2. ISG_AGENT_STRIPE_SECRET_KEY env var (canonical, matches pydantic-settings)
    3. STRIPE_SECRET_KEY env var (legacy fallback)

Warning: Railway dashboard MUST show ISG_AGENT_STRIPE_SECRET_KEY, not bare STRIPE_SECRET_KEY.
Bare names appear green in Railway UI but are silently ignored by pydantic-settings.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import stripe

__all__ = ["StripeMeteringClient"]

logger = logging.getLogger(__name__)


class StripeMeteringClient:
    """Records agent_calls meter events to Stripe for usage-based billing."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        # Check explicit arg first, then ISG_AGENT_STRIPE_SECRET_KEY (canonical for pydantic-settings),
        # then bare STRIPE_SECRET_KEY (legacy fallback).
        self._api_key = (
            api_key
            or os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY", "")
            or os.environ.get("STRIPE_SECRET_KEY", "")
        )
        self._enabled = bool(self._api_key and self._api_key.startswith("sk_"))
        if not self._enabled:
            logger.warning(
                "StripeMeteringClient: no valid Stripe API key found — metering disabled. "
                "Set ISG_AGENT_STRIPE_SECRET_KEY on Railway (ISG_AGENT_ prefix required)."
            )

    async def record_agent_call(
        self,
        stripe_customer_id: str,
        quantity: int = 1,
        agent_id: str = "",
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """Record an agent_calls meter event for a customer.

        Never raises — failures are logged and skipped so the actual
        agent call is never blocked by a billing failure.

        Returns True if the event was recorded, False if skipped/failed.
        """
        if not self._enabled or not stripe_customer_id:
            return False

        idem_key = idempotency_key or (
            f"agent_call_{stripe_customer_id}_{agent_id}_{int(time.time())}"
        )

        try:
            stripe.api_key = self._api_key
            await stripe.billing.MeterEvent.create_async(
                event_name="agent_calls",
                payload={
                    "stripe_customer_id": stripe_customer_id,
                    "value": str(quantity),
                },
                identifier=idem_key,
            )
            logger.debug(
                "Meter event recorded: customer=%s agent=%s qty=%d key=%s",
                stripe_customer_id,
                agent_id,
                quantity,
                idem_key,
            )
            return True
        except stripe.StripeError as exc:
            logger.warning("Stripe meter event failed (non-blocking): %s", exc)
            return False
        except Exception as exc:
            logger.warning("Unexpected meter error (non-blocking): %s", exc)
            return False

    async def get_usage_summary(
        self,
        stripe_customer_id: str,
        meter_id: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> dict[str, Any]:
        """Return usage summary for a customer from the agent_calls meter.

        meter_id: the mtr_xxx ID from your Stripe dashboard or STRIPE_METER_ID_AGENT_CALLS env var.
        """
        if not self._enabled:
            return {"total": 0, "error": "metering_disabled"}

        now = int(time.time())
        start = start_time or (now - 30 * 24 * 3600)  # default: last 30 days
        end = end_time or now

        try:
            stripe.api_key = self._api_key
            summaries = await stripe.billing.Meter.list_event_summaries_async(
                meter_id,
                customer=stripe_customer_id,
                start_time=start,
                end_time=end,
            )
            total = sum(s.aggregated_value for s in summaries.data)
            return {"total": int(total), "summaries": [s.to_dict() for s in summaries.data]}
        except stripe.StripeError as exc:
            logger.warning("Failed to fetch usage summary: %s", exc)
            return {"total": 0, "error": str(exc)}
