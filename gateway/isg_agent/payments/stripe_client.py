"""Stripe payment integration — $1/transaction model.

Wraps the Stripe Python SDK for PaymentIntent creation, payment verification,
webhook signature verification, and customer management.  All amounts are in
cents (100 = $1.00).

The client is designed to be OPTIONAL: if no API key is configured, the
PaymentGate middleware allows all requests without payment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import stripe

__all__ = [
    "PaymentResult",
    "StripeClient",
]

logger = logging.getLogger(__name__)

# Default transaction amount: $1.00
DEFAULT_AMOUNT_CENTS = 100


@dataclass(frozen=True)
class PaymentResult:
    """Result of a payment operation.

    Attributes
    ----------
    success:
        Whether the payment was successful.
    payment_intent_id:
        The Stripe PaymentIntent ID (present on success and some failures).
    error:
        Human-readable error message (present on failure).
    amount_cents:
        The amount charged in cents.
    """

    success: bool
    payment_intent_id: str | None = None
    error: str | None = None
    amount_cents: int = DEFAULT_AMOUNT_CENTS


class StripeClient:
    """Stripe payment client for ISG Agent 1.

    Parameters
    ----------
    api_key:
        Stripe secret API key (``sk_test_...`` or ``sk_live_...``).
    webhook_secret:
        Stripe webhook endpoint secret for signature verification.
    """

    def __init__(self, api_key: str, webhook_secret: str = "") -> None:
        self.webhook_secret = webhook_secret
        stripe.api_key = api_key
        # Use HTTPX async client so Stripe calls don't block the asyncio event loop.
        # Without this, stripe SDK falls back to synchronous `requests`, which
        # blocks uvicorn workers under load. Required for production FastAPI.
        try:
            stripe.default_http_client = stripe.HTTPXClient()
        except Exception:  # pragma: no cover — older stripe SDK versions
            pass

    async def create_payment_intent(
        self,
        user_id: str,
        session_id: str,
        amount_cents: int = DEFAULT_AMOUNT_CENTS,
    ) -> dict[str, Any]:
        """Create a Stripe PaymentIntent.

        Parameters
        ----------
        user_id:
            The authenticated user's ID (stored in metadata).
        session_id:
            The agent session ID (stored in metadata).
        amount_cents:
            Amount to charge in cents (default $1.00).

        Returns
        -------
        dict
            Contains ``client_secret`` and ``payment_intent_id``.

        Raises
        ------
        stripe.StripeError
            On any Stripe API error.
        """
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            metadata={
                "user_id": user_id,
                "session_id": session_id,
                "platform": "isg_agent_1",
            },
        )
        logger.info(
            "PaymentIntent created: %s for user=%s session=%s amount=%d",
            intent.id,
            user_id,
            session_id,
            amount_cents,
        )
        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
        }

    async def verify_payment(self, payment_intent_id: str) -> PaymentResult:
        """Verify the status of a PaymentIntent.

        Parameters
        ----------
        payment_intent_id:
            The Stripe PaymentIntent ID to check.

        Returns
        -------
        PaymentResult
            Success if status is ``"succeeded"``, failure otherwise.
        """
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        except stripe.StripeError as exc:
            logger.warning(
                "Failed to retrieve PaymentIntent %s: %s",
                payment_intent_id,
                exc,
            )
            return PaymentResult(
                success=False,
                payment_intent_id=payment_intent_id,
                error=str(exc),
            )

        if intent.status == "succeeded":
            return PaymentResult(
                success=True,
                payment_intent_id=intent.id,
                amount_cents=intent.amount,
            )

        return PaymentResult(
            success=False,
            payment_intent_id=intent.id,
            error=f"Payment status: {intent.status}",
            amount_cents=intent.amount,
        )

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        """Verify a Stripe webhook signature and return the event.

        Parameters
        ----------
        payload:
            Raw request body bytes.
        signature:
            The ``Stripe-Signature`` header value.

        Returns
        -------
        dict
            The verified Stripe event object.

        Raises
        ------
        ValueError
            If the webhook secret is not configured.
        stripe.SignatureVerificationError
            If the signature is invalid.
        """
        if not self.webhook_secret:
            raise ValueError("Webhook secret not configured")

        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=self.webhook_secret,
        )
        logger.info(
            "Webhook verified: type=%s id=%s",
            event.get("type", "unknown"),
            event.get("id", "unknown"),
        )
        return dict(event)

    async def create_customer(
        self,
        email: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Create a Stripe Customer.

        Parameters
        ----------
        email:
            Customer email address.
        metadata:
            Optional key-value metadata to attach to the customer.

        Returns
        -------
        str
            The Stripe Customer ID (``cus_...``).

        Raises
        ------
        stripe.StripeError
            On any Stripe API error.
        """
        customer = stripe.Customer.create(
            email=email,
            metadata=metadata or {},
        )
        logger.info("Stripe customer created: %s for %s", customer.id, email)
        return customer.id
