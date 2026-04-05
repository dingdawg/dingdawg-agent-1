"""Payment gate middleware — free tier + paid access control.

Tracks per-user CHAT MESSAGE counts and enforces the free chat-message limit
(default 5 messages).  After the limit is reached, users must have a valid
payment method via Stripe.

NOTE: This middleware gates CHAT MESSAGES only.  Skill-action limits
(Free=50/month, Starter=500/month, Pro=2,000/month, Enterprise=unlimited)
are enforced separately by UsageMeter in payments/usage_meter.py.

The gate is OPTIONAL: if no StripeClient is provided (Stripe not configured),
all requests are allowed unconditionally.
"""

from __future__ import annotations

import logging
from typing import Optional

from isg_agent.payments.stripe_client import StripeClient

__all__ = [
    "PaymentGate",
]

logger = logging.getLogger(__name__)


class PaymentGate:
    """Checks if a user can send chat messages (free tier or paid).

    Gates CHAT MESSAGES only — not skill actions.  Skill-action quotas
    (Free=50/month, Starter=500/month, Pro=2,000/month, Enterprise=unlimited)
    are enforced by UsageMeter in payments/usage_meter.py.

    Free tier: 5 chat messages per user. After that, the user must have a
    valid payment method (handled client-side via Stripe Elements).

    If no ``stripe_client`` is provided, the gate is DISABLED and all
    users are allowed unconditionally.  This enables local development
    without Stripe keys.

    Parameters
    ----------
    stripe_client:
        Optional StripeClient instance.  When ``None``, the gate is open.
    free_tier_limit:
        Number of free chat messages before payment is required.
    """

    FREE_TIER_LIMIT = 5

    def __init__(
        self,
        stripe_client: Optional[StripeClient] = None,
        free_tier_limit: int = 5,
    ) -> None:
        self._stripe = stripe_client
        self._free_tier_limit = free_tier_limit
        # In-memory message counts per user_id
        self._message_counts: dict[str, int] = {}
        # Set of user IDs with confirmed payment
        self._paid_users: set[str] = set()

    @property
    def is_enabled(self) -> bool:
        """Return ``True`` if Stripe is configured and the gate is active."""
        return self._stripe is not None

    def check_access(self, user_id: str) -> tuple[bool, int]:
        """Check whether a user is allowed to send a message.

        Parameters
        ----------
        user_id:
            The authenticated user's identifier.

        Returns
        -------
        tuple[bool, int]
            ``(allowed, remaining_free)``
            - ``allowed``: ``True`` if the user can send a message.
            - ``remaining_free``: Number of free messages remaining (0 if paid
              or if the limit has been exceeded).
        """
        # Gate disabled (no Stripe) — always allow
        if not self.is_enabled:
            return True, self._free_tier_limit

        # Paid users always allowed
        if user_id in self._paid_users:
            return True, 0

        count = self._message_counts.get(user_id, 0)
        remaining = max(0, self._free_tier_limit - count)

        if count < self._free_tier_limit:
            return True, remaining

        # Free tier exhausted and not paid
        return False, 0

    def record_message(self, user_id: str) -> None:
        """Increment the message count for a user.

        Parameters
        ----------
        user_id:
            The authenticated user's identifier.
        """
        current = self._message_counts.get(user_id, 0)
        self._message_counts[user_id] = current + 1

    def mark_paid(self, user_id: str) -> None:
        """Mark a user as having confirmed payment.

        Paid users bypass the free tier limit indefinitely.

        Parameters
        ----------
        user_id:
            The user to mark as paid.
        """
        self._paid_users.add(user_id)
        logger.info("User %s marked as paid — unlimited access", user_id)

    def get_usage(self, user_id: str) -> dict[str, object]:
        """Return usage information for a user.

        Parameters
        ----------
        user_id:
            The authenticated user's identifier.

        Returns
        -------
        dict
            Contains ``total_messages``, ``free_remaining``,
            ``payment_required``, and ``is_paid``.
        """
        count = self._message_counts.get(user_id, 0)
        is_paid = user_id in self._paid_users
        remaining = max(0, self._free_tier_limit - count) if not is_paid else 0
        payment_required = (
            not is_paid
            and count >= self._free_tier_limit
            and self.is_enabled
        )

        return {
            "total_messages": count,
            "free_remaining": remaining,
            "payment_required": payment_required,
            "is_paid": is_paid,
        }

    def reset_user(self, user_id: str) -> None:
        """Reset a user's message count and payment status.

        Useful for testing or administrative resets.

        Parameters
        ----------
        user_id:
            The user to reset.
        """
        self._message_counts.pop(user_id, None)
        self._paid_users.discard(user_id)
