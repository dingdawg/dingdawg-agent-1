"""Stripe Connect — Express accounts for the DingDawg creator marketplace.

Architecture: Destination Charges (NOT Direct Charges)
- Platform (DingDawg) collects payment from customer
- Platform automatically takes 20% as application_fee_amount
- 80% transferred to creator via transfer_data.destination
- "Sellers will collect payments directly" must be OFF in Stripe Connect settings

Flow:
1. Creator publishes agent → create_express_account() → returns onboarding URL
2. Creator completes Stripe onboarding
3. Customer pays → create_destination_charge() → 80% auto-transferred to creator
4. Creator views earnings → get_creator_balance() / list_creator_payouts()
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import stripe

__all__ = ["StripeConnectClient"]

logger = logging.getLogger(__name__)

PLATFORM_FEE_RATE = 0.20   # 20% platform cut
CREATOR_SHARE_RATE = 0.80  # 80% to creator


class StripeConnectClient:
    """Manages Stripe Connect Express accounts and Destination Charges."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        public_url: str = "https://dingdawg.com",
    ) -> None:
        self._api_key = api_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self._enabled = bool(self._api_key and self._api_key.startswith("sk_"))
        self._public_url = public_url.rstrip("/")
        if not self._enabled:
            logger.warning("StripeConnectClient: STRIPE_SECRET_KEY not set — Connect disabled")

    def _set_key(self) -> None:
        stripe.api_key = self._api_key

    # -----------------------------------------------------------------------
    # Express account creation + onboarding
    # -----------------------------------------------------------------------

    async def create_express_account(
        self,
        email: str,
        creator_id: str,
        agent_name: str = "",
    ) -> dict[str, Any]:
        """Create a Stripe Express account for a creator and return the onboarding URL.

        Returns:
            {"account_id": "acct_xxx", "onboarding_url": "https://connect.stripe.com/..."}
        """
        if not self._enabled:
            return {"error": "stripe_connect_disabled"}

        self._set_key()
        try:
            account = await stripe.Account.create_async(
                type="express",
                email=email,
                capabilities={
                    "transfers": {"requested": True},
                    "card_payments": {"requested": True},
                },
                metadata={
                    "creator_id": creator_id,
                    "agent_name": agent_name,
                    "platform": "dingdawg",
                },
            )

            link = await stripe.AccountLink.create_async(
                account=account.id,
                refresh_url=f"{self._public_url}/creator/onboarding?refresh=true&creator={creator_id}",
                return_url=f"{self._public_url}/creator/onboarding-complete?creator={creator_id}",
                type="account_onboarding",
            )

            logger.info("Express account created: %s for creator %s", account.id, creator_id)
            return {"account_id": account.id, "onboarding_url": link.url}

        except stripe.StripeError as exc:
            logger.error("Failed to create Express account: %s", exc)
            return {"error": str(exc)}

    async def get_account_status(self, connected_account_id: str) -> dict[str, Any]:
        """Return onboarding + capabilities status for a connected account."""
        if not self._enabled:
            return {"error": "stripe_connect_disabled"}

        self._set_key()
        try:
            account = await stripe.Account.retrieve_async(connected_account_id)
            return {
                "account_id": account.id,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled,
                "details_submitted": account.details_submitted,
                "requirements": {
                    "currently_due": account.requirements.currently_due if account.requirements else [],
                    "eventually_due": account.requirements.eventually_due if account.requirements else [],
                    "disabled_reason": account.requirements.disabled_reason if account.requirements else None,
                },
            }
        except stripe.StripeError as exc:
            logger.error("Failed to retrieve account status: %s", exc)
            return {"error": str(exc)}

    # -----------------------------------------------------------------------
    # Destination Charges — platform collects, auto-splits 80/20
    # -----------------------------------------------------------------------

    async def create_destination_charge(
        self,
        amount_cents: int,
        currency: str = "usd",
        customer_id: str = "",
        connected_account_id: str = "",
        agent_id: str = "",
        description: str = "",
        payment_method_id: str = "",
    ) -> dict[str, Any]:
        """Create a Destination Charge — platform takes 20%, 80% goes to creator.

        The application_fee_amount is calculated automatically.
        transfer_data.destination routes 80% to the connected account.

        Args:
            amount_cents: Total amount charged to customer (e.g. 100 = $1.00)
            connected_account_id: Creator's Stripe account ID (acct_xxx)
        """
        if not self._enabled:
            return {"error": "stripe_connect_disabled"}

        if not connected_account_id:
            return {"error": "connected_account_id required"}

        self._set_key()

        application_fee = int(amount_cents * PLATFORM_FEE_RATE)

        try:
            charge_params: dict[str, Any] = {
                "amount": amount_cents,
                "currency": currency,
                "description": description or f"DingDawg agent: {agent_id}",
                "application_fee_amount": application_fee,
                "transfer_data": {"destination": connected_account_id},
                "metadata": {
                    "agent_id": agent_id,
                    "creator_account": connected_account_id,
                    "platform_fee_cents": application_fee,
                    "creator_amount_cents": amount_cents - application_fee,
                },
            }
            if customer_id:
                charge_params["customer"] = customer_id
            if payment_method_id:
                charge_params["payment_method"] = payment_method_id
                charge_params["confirm"] = True

            charge = await stripe.Charge.create_async(**charge_params)

            logger.info(
                "Destination charge created: %s | amount=%d | fee=%d | creator=%s",
                charge.id,
                amount_cents,
                application_fee,
                connected_account_id,
            )
            return {
                "charge_id": charge.id,
                "amount_cents": amount_cents,
                "platform_fee_cents": application_fee,
                "creator_amount_cents": amount_cents - application_fee,
                "status": charge.status,
            }

        except stripe.StripeError as exc:
            logger.error("Destination charge failed: %s", exc)
            return {"error": str(exc)}

    # -----------------------------------------------------------------------
    # Creator balance + payouts
    # -----------------------------------------------------------------------

    async def get_creator_balance(self, connected_account_id: str) -> dict[str, Any]:
        """Return available and pending balance for a creator's connected account."""
        if not self._enabled:
            return {"error": "stripe_connect_disabled"}

        self._set_key()
        try:
            balance = await stripe.Balance.retrieve_async(
                stripe_account=connected_account_id
            )
            available = sum(b.amount for b in balance.available if b.currency == "usd")
            pending = sum(b.amount for b in balance.pending if b.currency == "usd")
            return {
                "available_cents": available,
                "pending_cents": pending,
                "available_usd": available / 100,
                "pending_usd": pending / 100,
            }
        except stripe.StripeError as exc:
            logger.error("Failed to fetch creator balance: %s", exc)
            return {"error": str(exc)}

    async def list_creator_payouts(
        self,
        connected_account_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List recent payouts for a creator's connected account."""
        if not self._enabled:
            return []

        self._set_key()
        try:
            payouts = await stripe.Payout.list_async(
                limit=limit,
                stripe_account=connected_account_id,
            )
            return [
                {
                    "id": p.id,
                    "amount_cents": p.amount,
                    "amount_usd": p.amount / 100,
                    "status": p.status,
                    "arrival_date": p.arrival_date,
                    "created": p.created,
                    "description": p.description or "",
                }
                for p in payouts.data
            ]
        except stripe.StripeError as exc:
            logger.error("Failed to list creator payouts: %s", exc)
            return []
