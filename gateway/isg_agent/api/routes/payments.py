"""Payment endpoints: Stripe Checkout, webhook handling, billing portal, and usage tracking.

Provides the HTTP API for Stripe payment integration:
- Create Stripe Checkout Session (hosted page — user enters card there)
- Handle Stripe webhooks (signature verified — subscription lifecycle events)
- Create Stripe Customer Portal session (manage/cancel subscription)
- Query subscription status from Stripe
- Create PaymentIntent ($1.00 per transaction — legacy, keep for backwards compat)
- Query user usage (free messages remaining, payment status)

All endpoints except webhook require JWT authentication.

Stripe Checkout flow:
  1. Frontend calls POST /create-checkout-session with plan
  2. Backend creates Stripe Checkout Session (mode=subscription)
  3. Backend returns {checkout_url}
  4. Frontend redirects window.location.href = checkout_url
  5. User pays on Stripe's hosted page
  6. Stripe redirects to /billing?success=true
  7. Stripe fires webhook (checkout.session.completed) → backend activates subscription

Webhook events handled:
  - checkout.session.completed      → activate subscription in DB
  - customer.subscription.created   → upsert subscription record from Stripe object
  - customer.subscription.updated   → sync plan tier on upgrade/downgrade
  - customer.subscription.deleted   → cancel subscription
  - invoice.paid                    → renew subscription period
  - invoice.payment_succeeded       → clear payment-failure flag (mirrors invoice.paid)
  - invoice.payment_failed          → mark subscription inactive
  - payment_intent.succeeded        → legacy PaymentIntent flow
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import stripe

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.middleware.rate_limiter_middleware import auth_rate_limit
from isg_agent.payments.middleware import PaymentGate
from isg_agent.payments.stripe_client import StripeClient
from isg_agent.payments.usage_meter import PRICING_TIERS, UsageMeter

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

# ---------------------------------------------------------------------------
# Stripe price IDs mapping
# These are either read from env vars (preferred) or fall back to lookup
# by product name via the Stripe API.
# To set up: create Products + Prices in your Stripe dashboard, then
# set STRIPE_PRICE_STARTER, STRIPE_PRICE_PRO, STRIPE_PRICE_ENTERPRISE.
# ---------------------------------------------------------------------------
_STRIPE_PRICE_IDS: dict[str, str] = {
    # Monthly prices
    "pro":               os.environ.get("STRIPE_PRICE_PRO_MONTHLY",        os.environ.get("STRIPE_PRICE_PRO", "")),
    "team":              os.environ.get("STRIPE_PRICE_TEAM_MONTHLY",        ""),
    "enterprise":        os.environ.get("STRIPE_PRICE_ENTERPRISE_MONTHLY",  os.environ.get("STRIPE_PRICE_ENTERPRISE", "")),
    # Annual prices (20% off)
    "pro_annual":        os.environ.get("STRIPE_PRICE_PRO_ANNUAL",          ""),
    "team_annual":       os.environ.get("STRIPE_PRICE_TEAM_ANNUAL",         ""),
    "enterprise_annual": os.environ.get("STRIPE_PRICE_ENTERPRISE_ANNUAL",   ""),
}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateIntentRequest(BaseModel):
    """Optional: override the default $1.00 amount."""

    amount_cents: int = 100
    session_id: str = ""


class CreateIntentResponse(BaseModel):
    """Response from payment intent creation."""

    client_secret: str
    payment_intent_id: str
    amount_cents: int


class UsageResponse(BaseModel):
    """User's message usage and payment status."""

    total_messages: int
    free_remaining: int
    payment_required: bool
    is_paid: bool


class WebhookResponse(BaseModel):
    """Acknowledgement of webhook processing."""

    received: bool
    event_type: str = ""


class SkillUsageSummaryResponse(BaseModel):
    """Usage summary for skill-based metered billing."""

    total_actions: int
    free_actions: int
    billed_actions: int
    total_amount_cents: int
    remaining_free: int
    plan: str
    year_month: str
    actions_included: int


class SkillUsageHistoryResponse(BaseModel):
    """Usage history entry."""

    year_month: str
    total_actions: int
    free_actions: int
    billed_actions: int
    total_amount_cents: int


class SubscribeRequest(BaseModel):
    """Request to create a subscription plan."""

    agent_id: str
    plan: str  # free, starter, pro, enterprise


class SubscribeResponse(BaseModel):
    """Response after creating a subscription."""

    id: str
    agent_id: str
    user_id: str
    plan: str
    actions_included: int
    price_cents_monthly: int
    current_period_start: str
    current_period_end: str
    is_active: bool


class CheckoutSessionRequest(BaseModel):
    """Request to create a Stripe Checkout Session for subscription upgrade."""

    plan: str      # pro, team, enterprise
    billing: str = "monthly"  # monthly or annual
    agent_id: str = ""  # Optional — empty string means platform-level subscription
    success_url: str = ""  # Override — defaults to /billing?success=true
    cancel_url: str = ""   # Override — defaults to /billing?canceled=true


class CheckoutSessionResponse(BaseModel):
    """Response with the Stripe-hosted checkout URL."""

    checkout_url: str
    session_id: str


class BillingPortalResponse(BaseModel):
    """Response with the Stripe Customer Portal URL."""

    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    """Current subscription status fetched live from Stripe."""

    plan: str
    stripe_status: str  # active, past_due, canceled, trialing, etc.
    stripe_subscription_id: str
    stripe_customer_id: str
    current_period_end: str
    cancel_at_period_end: bool
    is_active: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_stripe_client(request: Request) -> Optional[StripeClient]:
    """Extract the StripeClient from app state (may be None)."""
    return getattr(request.app.state, "stripe_client", None)


def _get_usage_meter(request: Request) -> Optional[UsageMeter]:
    """Extract the UsageMeter from app state (may be None)."""
    return getattr(request.app.state, "usage_meter", None)


def _get_payment_gate(request: Request) -> PaymentGate:
    """Extract the PaymentGate from app state."""
    gate: Optional[PaymentGate] = getattr(request.app.state, "payment_gate", None)
    if gate is None:
        # Fallback: create a disabled gate
        return PaymentGate(stripe_client=None)
    return gate


def _get_app_domain(request: Request) -> str:
    """Return the canonical public base URL for Stripe success/cancel redirects.

    Priority order (highest to lowest):
    1. ``ISG_AGENT_PUBLIC_URL`` / ``settings.public_url`` — canonical domain.
       Prevents leaking the internal Railway hostname in Stripe redirect URLs.
    2. Legacy domain/app_url settings fields (kept for backward compat).
    3. Fallback: construct from request — local dev only.
    """
    from isg_agent.config import get_settings

    # Primary: use the explicit public URL env var
    cfg = get_settings()
    if cfg.public_url:
        return cfg.public_url.rstrip("/")
    # Legacy: check app.state settings
    state_settings = getattr(request.app.state, "settings", None)
    if state_settings is not None:
        domain = getattr(state_settings, "domain", "") or getattr(state_settings, "app_url", "")
        if domain:
            return domain.rstrip("/")
    # Fallback: derive from request (local dev only)
    return str(request.base_url).rstrip("/")


def _get_price_id_for_plan(plan: str) -> str:
    """Return the Stripe Price ID for a given plan name.

    Reads from _STRIPE_PRICE_IDS which is populated from env vars at module
    load time (STRIPE_PRICE_STARTER, STRIPE_PRICE_PRO, STRIPE_PRICE_ENTERPRISE).

    Returns empty string if not configured (caller must handle this case).
    """
    return _STRIPE_PRICE_IDS.get(plan, "")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /create-checkout-session
# ---------------------------------------------------------------------------


@router.post(
    "/create-checkout-session",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe Checkout Session for subscription upgrade",
)
@auth_rate_limit()
async def create_checkout_session(
    body: CheckoutSessionRequest,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> CheckoutSessionResponse:
    """Create a Stripe Checkout Session for a subscription plan.

    The caller redirects ``window.location.href`` to ``checkout_url``.
    After payment, Stripe redirects back to ``/billing?success=true``.
    The subscription is activated via the ``checkout.session.completed`` webhook.

    Plans that may be purchased: ``starter``, ``pro``, ``enterprise``.
    The ``free`` plan does not require a Checkout Session.

    Requires Stripe to be configured (STRIPE_SECRET_KEY env var).
    Requires the corresponding STRIPE_PRICE_* env var to be set.
    Returns 503 if Stripe is not configured.
    Returns 400 if the plan is invalid or price ID is not configured.
    """
    client = _get_stripe_client(request)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured",
        )

    if body.plan not in {"pro", "team", "enterprise"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan: {body.plan!r}. Valid plans: {list(PRICING_TIERS.keys())}",
        )

    if body.plan == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Free plan does not require a checkout session. Use POST /subscribe with plan=free.",
        )

    price_id = _get_price_id_for_plan(f"{body.plan}_annual" if body.billing == "annual" else body.plan)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stripe price ID not configured for plan '{body.plan}'. "
                f"Set STRIPE_PRICE_{body.plan.upper()} environment variable."
            ),
        )

    domain = _get_app_domain(request)
    success_url = body.success_url or f"{domain}/billing?success=true&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = body.cancel_url or f"{domain}/billing?canceled=true"

    # -----------------------------------------------------------------------
    # HARDENED customer lookup — 3-layer, no eventual consistency risk.
    #
    # Layer 1: Our DB (usage_subscriptions) — zero API calls, always fresh.
    # Layer 2: stripe.Customer.list(email=) — STRONGLY consistent (not search).
    #          stripe.Customer.search() is eventually consistent (up to 1hr lag).
    #          NEVER use search() in a checkout flow.
    # Layer 3: Create new customer — UUID idempotency key per attempt (not per
    #          user), so the same user can checkout multiple plans without
    #          hitting Stripe's "same key, different params" IdempotencyError.
    # -----------------------------------------------------------------------
    try:
        customer_id = ""

        # Layer 1: Check our own DB first — authoritative, zero network call.
        meter = _get_usage_meter(request)
        if meter is not None:
            try:
                sub = await meter.get_user_subscription(
                    agent_id=body.agent_id or "default",
                    user_id=user.user_id,
                )
                if sub:
                    customer_id = sub.get("stripe_customer_id", "")
            except Exception as _db_err:
                logger.debug("DB stripe_customer_id lookup failed: %s", _db_err)

        # Layer 2: stripe.Customer.list(email=) — strongly consistent.
        if not customer_id:
            by_email = await stripe.Customer.list_async(email=user.email, limit=1)
            if by_email.data:
                customer_id = by_email.data[0].id

        # Layer 3: Create — fresh UUID idempotency key (not user-scoped key,
        # which would collide across different plan/agent_id combos).
        if not customer_id:
            customer = await stripe.Customer.create_async(
                email=user.email,
                metadata={
                    "user_id": user.user_id,
                    "agent_id": body.agent_id,
                    "platform": "isg_agent_1",
                },
                idempotency_key=str(uuid.uuid4()),
            )
            customer_id = customer.id

        session = await stripe.checkout.Session.create_async(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            # client_reference_id = fallback user lookup in webhooks if
            # customer metadata is missing. Always set this.
            client_reference_id=user.user_id,
            subscription_data={
                "metadata": {
                    "user_id": user.user_id,
                    "agent_id": body.agent_id,
                    "plan": body.plan,
                    "platform": "isg_agent_1",
                }
            },
            # metadata on the session itself (for checkout.session.completed)
            metadata={
                "user_id": user.user_id,
                "agent_id": body.agent_id,
                "plan": body.plan,
            },
        )

    except stripe.StripeError as exc:
        logger.error("Stripe Checkout Session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        )
    except Exception as exc:
        logger.error("Unexpected error creating checkout session: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider error",
        )

    # Audit record
    audit_chain = getattr(request.app.state, "audit_chain", None)
    if audit_chain is not None:
        await audit_chain.record(
            event_type="checkout_session_created",
            actor=user.user_id,
            details={
                "session_id": session.id,
                "plan": body.plan,
                "agent_id": body.agent_id,
                "price_id": price_id,
            },
        )

    logger.info(
        "Checkout session created: user=%s plan=%s session=%s",
        user.user_id, body.plan, session.id,
    )

    return CheckoutSessionResponse(
        checkout_url=session.url,
        session_id=session.id,
    )


# ---------------------------------------------------------------------------
# GET /billing-portal
# ---------------------------------------------------------------------------


@router.get(
    "/billing-portal",
    response_model=BillingPortalResponse,
    summary="Create a Stripe Customer Portal session for subscription management",
)
@auth_rate_limit()
async def create_billing_portal(
    request: Request,
    response: Response,
    agent_id: str = "",
    user: CurrentUser = Depends(require_auth),
) -> BillingPortalResponse:
    """Create a Stripe Customer Portal session.

    The portal lets the customer update payment methods, view invoices,
    and cancel their subscription.  The caller redirects to ``portal_url``.

    Requires the user to have an existing Stripe Customer ID in their
    subscription record.  Returns 404 if no subscription exists yet.
    Returns 503 if Stripe is not configured.
    """
    client = _get_stripe_client(request)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured",
        )

    # Find the Stripe customer ID from the usage subscription record
    meter = _get_usage_meter(request)
    stripe_customer_id = ""

    if meter is not None and agent_id:
        sub = await meter.get_user_subscription(agent_id=agent_id, user_id=user.user_id)
        if sub:
            stripe_customer_id = sub.get("stripe_customer_id", "")

    # Fallback: search Stripe directly by user metadata
    if not stripe_customer_id:
        try:
            existing = await stripe.Customer.search_async(
                query=f'metadata["user_id"]:"{user.user_id}"',
                limit=1,
            )
            if existing.data:
                stripe_customer_id = existing.data[0].id
        except Exception as exc:
            logger.warning("Failed to search Stripe customer: %s", exc)

    if not stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found. Purchase a plan first.",
        )

    domain = _get_app_domain(request)
    return_url = f"{domain}/billing"

    try:
        portal_session = await stripe.billing_portal.Session.create_async(
            customer=stripe_customer_id,
            return_url=return_url,
        )
    except stripe.StripeError as exc:
        logger.error("Billing portal session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        )

    logger.info(
        "Billing portal session created: user=%s customer=%s",
        user.user_id, stripe_customer_id,
    )

    return BillingPortalResponse(portal_url=portal_session.url)


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=SubscriptionStatusResponse,
    summary="Get subscription status from Stripe (live)",
)
@auth_rate_limit()
async def get_subscription_status(
    request: Request,
    response: Response,
    agent_id: str = "",
    user: CurrentUser = Depends(require_auth),
) -> SubscriptionStatusResponse:
    """Return the current subscription status fetched live from Stripe.

    Returns the local DB record if no Stripe subscription ID is stored,
    which may happen for users on the free plan or before webhook delivery.
    Returns 404 if no subscription record exists.
    Returns 503 if Stripe is not configured.
    """
    client = _get_stripe_client(request)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured",
        )

    meter = _get_usage_meter(request)
    if meter is None or not agent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_id query parameter is required",
        )

    sub = await meter.get_user_subscription(agent_id=agent_id, user_id=user.user_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found for this agent. User is on the default free tier.",
        )

    stripe_sub_id = sub.get("stripe_subscription_id", "")
    stripe_customer_id = sub.get("stripe_customer_id", "")

    # If we have a Stripe subscription ID, fetch live status
    if stripe_sub_id:
        try:
            stripe_sub = await stripe.Subscription.retrieve_async(stripe_sub_id)
            return SubscriptionStatusResponse(
                plan=sub.get("plan", "free"),
                stripe_status=stripe_sub.status,
                stripe_subscription_id=stripe_sub_id,
                stripe_customer_id=stripe_customer_id,
                current_period_end=str(stripe_sub.current_period_end),
                cancel_at_period_end=stripe_sub.cancel_at_period_end,
                is_active=stripe_sub.status in ("active", "trialing"),
            )
        except stripe.StripeError as exc:
            logger.warning("Failed to fetch Stripe subscription %s: %s", stripe_sub_id, exc)
            # Fall through to local data

    # Return from local DB
    return SubscriptionStatusResponse(
        plan=sub.get("plan", "free"),
        stripe_status="local_only",
        stripe_subscription_id=stripe_sub_id,
        stripe_customer_id=stripe_customer_id,
        current_period_end=sub.get("current_period_end", ""),
        cancel_at_period_end=False,
        is_active=bool(sub.get("is_active", True)),
    )


@router.post(
    "/create-intent",
    response_model=CreateIntentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe PaymentIntent ($1.00)",
)
@auth_rate_limit()
async def create_payment_intent(
    body: CreateIntentRequest,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> CreateIntentResponse:
    """Create a Stripe PaymentIntent for $1.00.

    Returns the ``client_secret`` for the frontend to confirm payment
    via Stripe Elements or Stripe.js.

    Requires authentication. Returns 503 if Stripe is not configured.
    """
    client = _get_stripe_client(request)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured",
        )

    try:
        result = await client.create_payment_intent(
            user_id=user.user_id,
            session_id=body.session_id or "default",
            amount_cents=body.amount_cents,
        )
    except Exception as exc:
        logger.error("Failed to create PaymentIntent: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider error",
        )

    # Record payment event to audit chain if available
    audit_chain = getattr(request.app.state, "audit_chain", None)
    if audit_chain is not None:
        await audit_chain.record(
            event_type="payment_intent_created",
            actor=user.user_id,
            details={
                "payment_intent_id": result["payment_intent_id"],
                "amount_cents": body.amount_cents,
            },
        )

    return CreateIntentResponse(
        client_secret=result["client_secret"],
        payment_intent_id=result["payment_intent_id"],
        amount_cents=body.amount_cents,
    )


async def _process_stripe_event(
    event: dict,
    meter: Any,
    audit_chain: Any,
    gate: Any,
) -> None:
    """Background processor for Stripe webhook events.

    Runs AFTER the route has already returned 200 to Stripe.  All business
    logic (subscription provisioning, dunning, audit) lives here so we never
    risk a Stripe delivery timeout (30s) from slow DB or downstream calls.
    """
    event_type = event.get("type", "unknown")
    event_id = event.get("id", "")
    data_object = event.get("data", {}).get("object", {})

    try:
        if event_type == "checkout.session.completed":
            metadata = data_object.get("metadata", {})
            user_id = metadata.get("user_id", "") or data_object.get("client_reference_id", "")
            agent_id = metadata.get("agent_id", "")
            plan = metadata.get("plan", "starter")
            stripe_customer_id = data_object.get("customer", "")
            stripe_subscription_id = data_object.get("subscription", "")

            if user_id and meter:
                try:
                    await meter.create_subscription(
                        agent_id=agent_id or "default",
                        user_id=user_id,
                        plan=plan,
                        stripe_customer_id=stripe_customer_id,
                        stripe_subscription_id=stripe_subscription_id,
                    )
                    logger.info(
                        "Checkout completed: user=%s plan=%s sub=%s",
                        user_id, plan, stripe_subscription_id,
                    )
                except Exception as exc:
                    logger.error("Failed to activate subscription from checkout: %s", exc)

            if user_id and gate is not None:
                gate.mark_paid(user_id)

            if audit_chain and user_id:
                await audit_chain.record(
                    event_type="checkout_session_completed",
                    actor=user_id,
                    details={
                        "session_id": data_object.get("id", ""),
                        "plan": plan,
                        "agent_id": agent_id,
                        "stripe_subscription_id": stripe_subscription_id,
                    },
                )

        elif event_type == "customer.subscription.created":
            stripe_subscription_id = data_object.get("id", "")
            stripe_customer_id = data_object.get("customer", "")
            sub_metadata = data_object.get("metadata", {})
            user_id = sub_metadata.get("user_id", "")
            agent_id = sub_metadata.get("agent_id", "")
            items_data = data_object.get("items", {}).get("data", [])
            plan = sub_metadata.get("plan", "")
            if not plan and items_data:
                price_meta = items_data[0].get("price", {}).get("metadata", {})
                plan = price_meta.get("plan", "")
            plan = plan or "starter"

            if user_id and meter:
                try:
                    await meter.create_subscription(
                        agent_id=agent_id or "default",
                        user_id=user_id,
                        plan=plan,
                        stripe_customer_id=stripe_customer_id,
                        stripe_subscription_id=stripe_subscription_id,
                    )
                except Exception as exc:
                    logger.error("subscription.created handler failed (sub=%s): %s", stripe_subscription_id, exc)

            if user_id and gate is not None:
                gate.mark_paid(user_id)

            if audit_chain and user_id:
                await audit_chain.record(
                    event_type="subscription_created_webhook",
                    actor=user_id,
                    details={
                        "stripe_subscription_id": stripe_subscription_id,
                        "stripe_customer_id": stripe_customer_id,
                        "plan": plan,
                        "agent_id": agent_id,
                    },
                )

        elif event_type == "customer.subscription.updated":
            stripe_subscription_id = data_object.get("id", "")
            stripe_customer_id = data_object.get("customer", "")
            sub_metadata = data_object.get("metadata", {})
            user_id = sub_metadata.get("user_id", "")
            agent_id = sub_metadata.get("agent_id", "")
            stripe_status = data_object.get("status", "")
            items_data = data_object.get("items", {}).get("data", [])
            plan = sub_metadata.get("plan", "")
            if not plan and items_data:
                price_meta = items_data[0].get("price", {}).get("metadata", {})
                plan = price_meta.get("plan", "")

            if meter and stripe_subscription_id:
                if stripe_status in ("canceled", "unpaid"):
                    try:
                        await meter.deactivate_subscription_by_stripe_id(stripe_subscription_id)
                    except Exception as exc:
                        logger.error("deactivate on subscription.updated failed: %s", exc)
                elif stripe_status in ("active", "trialing") and plan:
                    try:
                        updated = await meter.update_subscription_plan_by_stripe_id(
                            stripe_subscription_id=stripe_subscription_id,
                            new_plan=plan,
                            stripe_customer_id=stripe_customer_id,
                        )
                        if not updated and user_id:
                            await meter.create_subscription(
                                agent_id=agent_id or "default",
                                user_id=user_id,
                                plan=plan,
                                stripe_customer_id=stripe_customer_id,
                                stripe_subscription_id=stripe_subscription_id,
                            )
                    except Exception as exc:
                        logger.error("update plan on subscription.updated failed: %s", exc)

            if audit_chain:
                await audit_chain.record(
                    event_type="subscription_updated_webhook",
                    actor=user_id or stripe_customer_id,
                    details={
                        "stripe_subscription_id": stripe_subscription_id,
                        "stripe_customer_id": stripe_customer_id,
                        "plan": plan,
                        "stripe_status": stripe_status,
                        "agent_id": agent_id,
                    },
                )

        elif event_type == "invoice.paid":
            stripe_customer_id = data_object.get("customer", "")
            stripe_subscription_id = data_object.get("subscription", "")
            if meter and stripe_subscription_id:
                try:
                    reactivated = await meter.reactivate_subscription_by_stripe_id(stripe_subscription_id)
                    if reactivated:
                        logger.info("Subscription re-activated via dunning recovery: sub=%s", stripe_subscription_id)
                except Exception as exc:
                    logger.error("reactivate on invoice.paid failed: %s", exc)
            if audit_chain:
                await audit_chain.record(
                    event_type="invoice_paid",
                    actor=stripe_customer_id,
                    details={"invoice_id": data_object.get("id", ""), "amount_paid": data_object.get("amount_paid", 0), "stripe_subscription_id": stripe_subscription_id},
                )

        elif event_type == "invoice.payment_succeeded":
            stripe_customer_id = data_object.get("customer", "")
            stripe_subscription_id = data_object.get("subscription", "")
            if meter and stripe_subscription_id:
                try:
                    await meter.reactivate_subscription_by_stripe_id(stripe_subscription_id)
                except Exception as exc:
                    logger.error("reactivate on invoice.payment_succeeded failed: %s", exc)
            if audit_chain:
                await audit_chain.record(
                    event_type="invoice_payment_succeeded",
                    actor=stripe_customer_id,
                    details={"invoice_id": data_object.get("id", ""), "amount_paid": data_object.get("amount_paid", 0), "stripe_subscription_id": stripe_subscription_id},
                )

        elif event_type == "invoice.payment_failed":
            stripe_customer_id = data_object.get("customer", "")
            stripe_subscription_id = data_object.get("subscription", "")
            if meter and stripe_subscription_id:
                try:
                    await meter.deactivate_subscription_by_stripe_id(stripe_subscription_id)
                except Exception as exc:
                    logger.error("deactivate on invoice.payment_failed failed: %s", exc)
            if audit_chain:
                await audit_chain.record(
                    event_type="invoice_payment_failed",
                    actor=stripe_customer_id,
                    details={"invoice_id": data_object.get("id", ""), "stripe_subscription_id": stripe_subscription_id},
                )

        elif event_type == "customer.subscription.deleted":
            stripe_customer_id = data_object.get("customer", "")
            stripe_subscription_id = data_object.get("id", "")
            sub_metadata = data_object.get("metadata", {})
            user_id = sub_metadata.get("user_id", "")
            agent_id = sub_metadata.get("agent_id", "")
            if meter and stripe_subscription_id:
                try:
                    await meter.deactivate_subscription_by_stripe_id(stripe_subscription_id)
                except Exception as exc:
                    logger.error("deactivate on subscription.deleted failed: %s", exc)
            if audit_chain:
                await audit_chain.record(
                    event_type="subscription_canceled",
                    actor=user_id or stripe_customer_id,
                    details={"stripe_subscription_id": stripe_subscription_id, "agent_id": agent_id},
                )

        elif event_type == "payment_intent.succeeded":
            metadata = data_object.get("metadata", {})
            user_id = metadata.get("user_id", "")
            if user_id and gate is not None:
                gate.mark_paid(user_id)
                if audit_chain:
                    await audit_chain.record(
                        event_type="payment_succeeded",
                        actor=user_id,
                        details={"payment_intent_id": data_object.get("id", ""), "amount": data_object.get("amount", 0)},
                    )

        else:
            logger.debug("Unhandled webhook event type: %s", event_type)

        # Mark processed AFTER successful handling
        if event_id and meter is not None:
            await meter.mark_event_processed(event_id, event_type)

    except Exception as exc:
        logger.error(
            "Background webhook processing failed event_id=%s type=%s: %s",
            event_id, event_type, exc, exc_info=True,
        )
        # Do NOT re-raise — Stripe already got 200, retrying won't help.
        # Log to monitoring. Use a dead-letter queue for critical recovery.


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Stripe webhook handler",
)
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks) -> WebhookResponse:
    """Handle Stripe webhook events.

    Verifies the webhook signature using the configured webhook secret.
    Handles both subscription lifecycle events (from Stripe Checkout) and
    the legacy payment_intent.succeeded event.

    Events processed:
    - checkout.session.completed      → activate subscription in UsageMeter DB
    - customer.subscription.created   → upsert subscription record from Stripe object
    - customer.subscription.updated   → sync plan on upgrade/downgrade
    - customer.subscription.deleted   → cancel subscription
    - invoice.paid                    → renew subscription period
    - invoice.payment_succeeded       → clear payment-failure flag (mirrors invoice.paid)
    - invoice.payment_failed          → deactivate subscription
    - payment_intent.succeeded        → legacy: mark user as paid in PaymentGate

    This endpoint does NOT require JWT authentication (Stripe sends webhooks
    directly).  Security is enforced via webhook signature verification.
    """
    client = _get_stripe_client(request)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured",
        )

    # Read raw body for signature verification
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    try:
        event = client.verify_webhook(payload=payload, signature=signature)
    except ValueError as exc:
        logger.warning("Webhook verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook request",
        )
    except Exception as exc:
        logger.warning("Webhook signature invalid: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )

    event_type = event.get("type", "unknown")
    event_id = event.get("id", "")
    data_object = event.get("data", {}).get("object", {})
    audit_chain = getattr(request.app.state, "audit_chain", None)
    meter = _get_usage_meter(request)

    # ------------------------------------------------------------------
    # Idempotency guard — skip if we already processed this event_id.
    # Stripe retries webhooks on 5xx or timeout; without this guard a
    # checkout.session.completed or invoice.paid could fire twice.
    # ------------------------------------------------------------------
    if event_id and meter is not None:
        if await meter.is_event_processed(event_id):
            logger.info(
                "Webhook event already processed, skipping: id=%s type=%s",
                event_id, event_type,
            )
            return WebhookResponse(received=True, event_type=event_type)

    # ------------------------------------------------------------------
    # Dispatch to background processor — return 200 immediately.
    #
    # Stripe retries any webhook that doesn't get a 2xx within 30s.
    # All business logic (DB writes, audit, dunning) runs in the
    # background AFTER we've already acked Stripe.  The _process_stripe_event
    # helper handles idempotency marking and all event types.
    # ------------------------------------------------------------------
    gate = _get_payment_gate(request)
    background_tasks.add_task(
        _process_stripe_event,
        dict(event),
        meter,
        audit_chain,
        gate,
    )
    return WebhookResponse(received=True, event_type=event_type)


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Get user's message usage and payment status",
)
@auth_rate_limit()
async def get_usage(
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> UsageResponse:
    """Return the authenticated user's message usage.

    Shows total messages sent, remaining free messages, whether payment
    is required, and whether the user is marked as paid.
    """
    gate = _get_payment_gate(request)
    usage = gate.get_usage(user.user_id)

    return UsageResponse(
        total_messages=int(usage["total_messages"]),
        free_remaining=int(usage["free_remaining"]),
        payment_required=bool(usage["payment_required"]),
        is_paid=bool(usage["is_paid"]),
    )


# ---------------------------------------------------------------------------
# Skill Usage Metering Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/usage/{agent_id}",
    response_model=SkillUsageSummaryResponse,
    summary="Get skill usage summary for current billing period",
)
@auth_rate_limit()
async def get_skill_usage(
    request: Request,
    response: Response,
    agent_id: str,
    year_month: Optional[str] = None,
    user: CurrentUser = Depends(require_auth),
) -> SkillUsageSummaryResponse:
    """Get usage summary for an agent for the current or specified billing period.

    Returns total actions, free actions, billed actions, amount, and plan info.
    """
    meter = _get_usage_meter(request)
    if meter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage metering is not configured",
        )

    summary = await meter.get_usage_summary(agent_id, year_month)
    return SkillUsageSummaryResponse(**summary)


@router.get(
    "/usage/{agent_id}/history",
    response_model=list[SkillUsageHistoryResponse],
    summary="Get usage history for past N months",
)
@auth_rate_limit()
async def get_skill_usage_history(
    request: Request,
    response: Response,
    agent_id: str,
    months: int = 6,
    user: CurrentUser = Depends(require_auth),
) -> list[SkillUsageHistoryResponse]:
    """Get usage history for an agent over the past N months.

    Returns a list of monthly summaries sorted most recent first.
    """
    meter = _get_usage_meter(request)
    if meter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage metering is not configured",
        )

    history = await meter.get_usage_history(agent_id, months)
    return [SkillUsageHistoryResponse(**h) for h in history]


@router.post(
    "/subscribe",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subscription plan for an agent",
)
@auth_rate_limit()
async def create_subscription(
    body: SubscribeRequest,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> SubscribeResponse:
    """Create or update a subscription plan for an agent.

    Valid plans: free, starter ($29/mo), pro ($79/mo), enterprise ($199/mo).
    """
    meter = _get_usage_meter(request)
    if meter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage metering is not configured",
        )

    if body.plan not in {"pro", "team", "enterprise"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan: {body.plan!r}. Valid plans: {list(PRICING_TIERS.keys())}",
        )

    # Gate paid plans: require Stripe configuration
    if body.plan != "free":
        client = _get_stripe_client(request)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Paid plans ({body.plan}) require Stripe payment. Contact support to enable billing.",
            )

    try:
        sub = await meter.create_subscription(
            agent_id=body.agent_id,
            user_id=user.user_id,
            plan=body.plan,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Record to audit chain
    audit_chain = getattr(request.app.state, "audit_chain", None)
    if audit_chain is not None:
        await audit_chain.record(
            event_type="subscription_created",
            actor=user.user_id,
            details={
                "agent_id": body.agent_id,
                "plan": body.plan,
                "price_cents_monthly": sub["price_cents_monthly"],
            },
        )

    return SubscribeResponse(**sub)
