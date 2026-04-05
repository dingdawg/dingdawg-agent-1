"""Usage-based billing for skill executions.

Meters every skill execution at $1/action (configurable).
Tracks usage in SQLite, reports to Stripe via meter events.
Supports free tier (first N actions/month free) and subscription overrides.

All amounts are stored in cents internally (100 = $1.00).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite
import stripe

__all__ = [
    "UsageMeter",
    "PRICING_TIERS",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------

PRICING_TIERS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free",
        "price_cents_monthly": 0,
        "price_cents_annual": 0,
        "calls_per_day": 25,
        "overage_cents": 0,
        "overage_blocked": True,
    },
    "pro": {
        "name": "Pro",
        "price_cents_monthly": 4900,   # $49/mo
        "price_cents_annual": 3900,    # $39/mo billed annually ($468/yr)
        "calls_per_day": 100,
        "overage_cents": 10,           # $0.10/call
        "overage_blocked": False,
    },
    "team": {
        "name": "Team",
        "price_cents_monthly": 14900,  # $149/mo
        "price_cents_annual": 11900,   # $119/mo billed annually ($1,428/yr)
        "calls_per_day": 300,
        "seats": 5,
        "overage_cents": 10,
        "overage_blocked": False,
    },
    "enterprise": {
        "name": "Enterprise",
        "price_cents_monthly": 49900,  # $499/mo
        "price_cents_annual": 39900,   # $399/mo billed annually ($4,788/yr)
        "calls_per_day": 1000,
        "seats": 10,
        "overage_cents": 10,
        "overage_blocked": False,
    },
    "payg": {
        "name": "Pay As You Go",
        "price_cents_monthly": 0,
        "price_cents_annual": 0,
        "calls_per_day": -1,           # Unlimited
        "overage_cents": 25,           # $0.25/call
        "overage_blocked": False,
    },
}


def _current_year_month() -> str:
    """Return current UTC year-month as 'YYYY-MM'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class UsageMeter:
    """Usage-based billing meter for skill executions.

    Records every skill execution in SQLite with billing status.
    Optionally reports billable events to Stripe metered billing.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    stripe_client:
        Optional StripeClient instance for reporting to Stripe.
    price_per_action:
        Default price per action in dollars (default $1.00).
    free_tier_limit:
        Number of free actions per month for users without a subscription.
    """

    def __init__(
        self,
        db_path: str,
        stripe_client: Any = None,
        price_per_action: float = 1.00,
        free_tier_limit: int = 50,
    ) -> None:
        self._db_path = db_path
        self._stripe = stripe_client
        self._price_per_action_cents = int(price_per_action * 100)
        self._free_tier_limit = free_tier_limit

    async def _get_db(self) -> aiosqlite.Connection:
        """Open an aiosqlite connection."""
        db = await aiosqlite.connect(self._db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        return db

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    async def init_tables(self) -> None:
        """Create usage tracking tables if they don't exist."""
        db = await self._get_db()
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS usage_records (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT '',
                    amount_cents INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'recorded',
                    stripe_usage_record_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_usage_records_agent
                    ON usage_records(agent_id);
                CREATE INDEX IF NOT EXISTS idx_usage_records_user
                    ON usage_records(user_id);
                CREATE INDEX IF NOT EXISTS idx_usage_records_created
                    ON usage_records(created_at);

                CREATE TABLE IF NOT EXISTS usage_subscriptions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    stripe_customer_id TEXT DEFAULT '',
                    stripe_subscription_id TEXT DEFAULT '',
                    plan TEXT NOT NULL DEFAULT 'free',
                    actions_included INTEGER NOT NULL DEFAULT 50,
                    current_period_start TEXT NOT NULL,
                    current_period_end TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(agent_id, user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_usage_subs_agent_user
                    ON usage_subscriptions(agent_id, user_id);

                CREATE TABLE IF NOT EXISTS usage_summary (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    year_month TEXT NOT NULL,
                    total_actions INTEGER NOT NULL DEFAULT 0,
                    free_actions INTEGER NOT NULL DEFAULT 0,
                    billed_actions INTEGER NOT NULL DEFAULT 0,
                    total_amount_cents INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(agent_id, year_month)
                );

                CREATE INDEX IF NOT EXISTS idx_usage_summary_agent_month
                    ON usage_summary(agent_id, year_month);

                CREATE TABLE IF NOT EXISTS processed_webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                """
            )
            await db.commit()
        finally:
            await db.close()

        logger.info("Usage metering tables initialised")

    # ------------------------------------------------------------------
    # Core usage recording
    # ------------------------------------------------------------------

    async def record_usage(
        self,
        agent_id: str,
        user_id: str,
        skill_name: str,
        action: str = "",
    ) -> dict[str, Any]:
        """Record a skill execution and determine billing.

        1. Check if agent/user has a subscription
        2. If within free tier or subscription included actions -> status=free_tier
        3. If over limit -> status=recorded, amount=price_per_action
        4. Insert usage record
        5. Update monthly summary
        6. If Stripe is configured and billable, fire-and-forget report

        Returns
        -------
        dict
            Contains ``usage_id``, ``status``, ``amount_cents``,
            ``remaining_free``.
        """
        now = _utc_now_iso()
        year_month = _current_year_month()
        usage_id = str(uuid.uuid4())

        db = await self._get_db()
        try:
            # 1. Get subscription (or default to free tier)
            sub = await self._get_subscription_row(db, agent_id, user_id)
            plan = sub["plan"] if sub else "free"
            tier = PRICING_TIERS.get(plan, PRICING_TIERS["free"])

            # Use constructor's free_tier_limit for users without a subscription
            if sub is None:
                actions_included = self._free_tier_limit
            else:
                actions_included = tier["actions_included"]
            overage_blocked = tier["overage_blocked"]

            # 2. Count usage this month for this agent
            month_count = await self._get_month_count(db, agent_id, year_month)

            # 3. Determine billing status
            if actions_included == -1:
                # Unlimited (enterprise)
                record_status = "free_tier"
                amount_cents = 0
                remaining_free = -1  # Unlimited
            elif month_count < actions_included:
                # Within included actions
                record_status = "free_tier"
                amount_cents = 0
                remaining_free = actions_included - month_count - 1
            else:
                # Over limit
                if overage_blocked:
                    record_status = "blocked"
                    amount_cents = 0
                    remaining_free = 0
                    # Still record but mark as blocked
                    await self._insert_record(
                        db, usage_id, agent_id, user_id, skill_name,
                        action, amount_cents, "blocked", now,
                    )
                    await self._update_summary(
                        db, agent_id, year_month, 0, 0, 0, now,
                    )
                    await db.commit()
                    return {
                        "usage_id": usage_id,
                        "status": "blocked",
                        "amount_cents": 0,
                        "remaining_free": 0,
                        "plan": plan,
                    }
                else:
                    record_status = "recorded"
                    amount_cents = tier["overage_cents"] if tier["overage_cents"] > 0 else self._price_per_action_cents
                    remaining_free = 0

            # 4. Insert usage record
            await self._insert_record(
                db, usage_id, agent_id, user_id, skill_name,
                action, amount_cents, record_status, now,
            )

            # 5. Update monthly summary
            is_free = 1 if record_status == "free_tier" else 0
            is_billed = 1 if record_status == "recorded" else 0
            await self._update_summary(
                db, agent_id, year_month,
                total_incr=1,
                free_incr=is_free,
                billed_incr=is_billed,
                now=now,
                amount_incr=amount_cents,
            )

            await db.commit()

            # 6. Fire-and-forget Stripe reporting for billable actions
            if record_status == "recorded" and self._stripe is not None:
                stripe_customer_id = sub.get("stripe_customer_id", "") if sub else ""
                if stripe_customer_id:
                    asyncio.create_task(
                        self._report_to_stripe_safe(usage_id, stripe_customer_id)
                    )

            return {
                "usage_id": usage_id,
                "status": record_status,
                "amount_cents": amount_cents,
                "remaining_free": remaining_free if remaining_free != -1 else -1,
                "plan": plan,
            }

        finally:
            await db.close()

    # ------------------------------------------------------------------
    # Summary queries
    # ------------------------------------------------------------------

    async def get_usage_summary(
        self,
        agent_id: str,
        year_month: str | None = None,
    ) -> dict[str, Any]:
        """Get usage summary for an agent for a given month.

        Returns
        -------
        dict
            Contains ``total_actions``, ``free_actions``, ``billed_actions``,
            ``total_amount_cents``, ``remaining_free``, ``plan``.
        """
        if year_month is None:
            year_month = _current_year_month()

        db = await self._get_db()
        try:
            row = await db.execute_fetchall(
                "SELECT * FROM usage_summary WHERE agent_id = ? AND year_month = ?",
                (agent_id, year_month),
            )

            if row:
                r = row[0]
                total_actions = r["total_actions"]
                free_actions = r["free_actions"]
                billed_actions = r["billed_actions"]
                total_amount_cents = r["total_amount_cents"]
            else:
                total_actions = 0
                free_actions = 0
                billed_actions = 0
                total_amount_cents = 0

            # Determine plan and remaining
            # Find any active subscription for this agent
            sub_rows = await db.execute_fetchall(
                """SELECT plan FROM usage_subscriptions
                   WHERE agent_id = ? AND is_active = 1
                   ORDER BY updated_at DESC LIMIT 1""",
                (agent_id,),
            )
            has_subscription = bool(sub_rows)
            plan = sub_rows[0]["plan"] if has_subscription else "free"
            tier = PRICING_TIERS.get(plan, PRICING_TIERS["free"])

            # Use constructor's free_tier_limit for users without a subscription
            if has_subscription:
                actions_included = tier["actions_included"]
            else:
                actions_included = self._free_tier_limit

            if actions_included == -1:
                remaining_free = -1
            else:
                remaining_free = max(0, actions_included - total_actions)

            return {
                "total_actions": total_actions,
                "free_actions": free_actions,
                "billed_actions": billed_actions,
                "total_amount_cents": total_amount_cents,
                "remaining_free": remaining_free,
                "plan": plan,
                "year_month": year_month,
                "actions_included": actions_included,
            }

        finally:
            await db.close()

    async def get_usage_history(
        self,
        agent_id: str,
        months: int = 6,
    ) -> list[dict[str, Any]]:
        """Get usage history for past N months.

        Returns a list of monthly summaries sorted most recent first.
        """
        db = await self._get_db()
        try:
            rows = await db.execute_fetchall(
                """SELECT * FROM usage_summary
                   WHERE agent_id = ?
                   ORDER BY year_month DESC
                   LIMIT ?""",
                (agent_id, months),
            )
            return [
                {
                    "year_month": r["year_month"],
                    "total_actions": r["total_actions"],
                    "free_actions": r["free_actions"],
                    "billed_actions": r["billed_actions"],
                    "total_amount_cents": r["total_amount_cents"],
                }
                for r in rows
            ]
        finally:
            await db.close()

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def get_user_subscription(
        self,
        agent_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Get active subscription for a user/agent combo."""
        db = await self._get_db()
        try:
            row = await self._get_subscription_row(db, agent_id, user_id)
            if row is None:
                return None
            return dict(row)
        finally:
            await db.close()

    async def create_subscription(
        self,
        agent_id: str,
        user_id: str,
        plan: str,
        stripe_customer_id: str = "",
        stripe_subscription_id: str = "",
    ) -> dict[str, Any]:
        """Create or update a subscription record.

        Returns the subscription record as a dict.
        """
        if plan not in PRICING_TIERS:
            raise ValueError(f"Invalid plan: {plan!r}. Must be one of {list(PRICING_TIERS.keys())}")

        tier = PRICING_TIERS[plan]
        now = _utc_now_iso()
        sub_id = str(uuid.uuid4())

        # Period: current month start to end
        today = datetime.now(timezone.utc)
        period_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month = today.replace(month=today.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = next_month.isoformat()

        db = await self._get_db()
        try:
            # Upsert: insert or replace
            await db.execute(
                """INSERT INTO usage_subscriptions
                   (id, agent_id, user_id, stripe_customer_id, stripe_subscription_id,
                    plan, actions_included, current_period_start, current_period_end,
                    is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(agent_id, user_id)
                   DO UPDATE SET
                       plan = excluded.plan,
                       actions_included = excluded.actions_included,
                       stripe_customer_id = excluded.stripe_customer_id,
                       stripe_subscription_id = excluded.stripe_subscription_id,
                       current_period_start = excluded.current_period_start,
                       current_period_end = excluded.current_period_end,
                       is_active = 1,
                       updated_at = excluded.updated_at
                """,
                (
                    sub_id, agent_id, user_id,
                    stripe_customer_id, stripe_subscription_id,
                    plan, tier["actions_included"],
                    period_start, period_end,
                    now, now,
                ),
            )
            await db.commit()

            return {
                "id": sub_id,
                "agent_id": agent_id,
                "user_id": user_id,
                "plan": plan,
                "actions_included": tier["actions_included"],
                "price_cents_monthly": tier["price_cents_monthly"],
                "current_period_start": period_start,
                "current_period_end": period_end,
                "is_active": True,
            }
        finally:
            await db.close()

    async def is_event_processed(self, event_id: str) -> bool:
        """Return True if this Stripe event_id has already been processed.

        Used for webhook idempotency — Stripe may deliver the same event
        more than once on network errors or timeouts.
        """
        db = await self._get_db()
        try:
            rows = await db.execute_fetchall(
                "SELECT event_id FROM processed_webhook_events WHERE event_id = ?",
                (event_id,),
            )
            return bool(rows)
        finally:
            await db.close()

    async def mark_event_processed(self, event_id: str, event_type: str) -> None:
        """Record a Stripe event_id as processed.

        INSERT OR IGNORE so concurrent workers don't raise a UNIQUE error.
        """
        now = _utc_now_iso()
        db = await self._get_db()
        try:
            await db.execute(
                """INSERT OR IGNORE INTO processed_webhook_events
                   (event_id, event_type, processed_at)
                   VALUES (?, ?, ?)""",
                (event_id, event_type, now),
            )
            await db.commit()
        finally:
            await db.close()

    async def update_subscription_plan_by_stripe_id(
        self,
        stripe_subscription_id: str,
        new_plan: str,
        stripe_customer_id: str = "",
    ) -> bool:
        """Update the plan and actions_included for a subscription by Stripe ID.

        Called when Stripe fires ``customer.subscription.updated`` — e.g., when
        the customer upgrades or downgrades their plan.  The subscription row is
        updated in-place so existing agent_id/user_id associations are preserved.

        Parameters
        ----------
        stripe_subscription_id:
            The Stripe subscription ID (``sub_...``).
        new_plan:
            The new plan name (must be a key in PRICING_TIERS).
        stripe_customer_id:
            Optional Stripe customer ID — updated on the row if provided.

        Returns
        -------
        bool
            ``True`` if one or more rows were updated, ``False`` otherwise.
        """
        if not stripe_subscription_id:
            return False

        if new_plan not in PRICING_TIERS:
            logger.warning(
                "update_subscription_plan_by_stripe_id: unknown plan %r for sub=%s",
                new_plan,
                stripe_subscription_id,
            )
            return False

        tier = PRICING_TIERS[new_plan]
        now = _utc_now_iso()
        db = await self._get_db()
        try:
            if stripe_customer_id:
                cursor = await db.execute(
                    """UPDATE usage_subscriptions
                       SET plan = ?, actions_included = ?, stripe_customer_id = ?,
                           is_active = 1, updated_at = ?
                       WHERE stripe_subscription_id = ?""",
                    (
                        new_plan,
                        tier["actions_included"],
                        stripe_customer_id,
                        now,
                        stripe_subscription_id,
                    ),
                )
            else:
                cursor = await db.execute(
                    """UPDATE usage_subscriptions
                       SET plan = ?, actions_included = ?, is_active = 1, updated_at = ?
                       WHERE stripe_subscription_id = ?""",
                    (new_plan, tier["actions_included"], now, stripe_subscription_id),
                )
            await db.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info(
                    "Subscription plan updated: stripe_subscription_id=%s new_plan=%s",
                    stripe_subscription_id,
                    new_plan,
                )
            else:
                logger.warning(
                    "update_subscription_plan_by_stripe_id: no row found for sub=%s",
                    stripe_subscription_id,
                )
            return updated
        finally:
            await db.close()

    async def reactivate_subscription_by_stripe_id(
        self,
        stripe_subscription_id: str,
    ) -> bool:
        """Re-activate a subscription that was deactivated during dunning.

        Called when Stripe fires ``invoice.paid`` after a previously failed
        payment — the dunning cycle succeeded and access should be restored.

        Returns
        -------
        bool
            ``True`` if one or more rows were updated, ``False`` otherwise.
        """
        if not stripe_subscription_id:
            return False

        now = _utc_now_iso()
        db = await self._get_db()
        try:
            cursor = await db.execute(
                """UPDATE usage_subscriptions
                   SET is_active = 1, updated_at = ?
                   WHERE stripe_subscription_id = ? AND is_active = 0""",
                (now, stripe_subscription_id),
            )
            await db.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info(
                    "Subscription re-activated after dunning recovery: "
                    "stripe_subscription_id=%s",
                    stripe_subscription_id,
                )
            return updated
        finally:
            await db.close()

    async def deactivate_subscription_by_stripe_id(
        self,
        stripe_subscription_id: str,
    ) -> bool:
        """Mark a subscription inactive by its Stripe subscription ID.

        Called when Stripe fires ``invoice.payment_failed`` or
        ``customer.subscription.deleted`` so the DB matches Stripe's truth.

        Returns
        -------
        bool
            ``True`` if one or more rows were updated, ``False`` otherwise.
        """
        if not stripe_subscription_id:
            return False

        now = _utc_now_iso()
        db = await self._get_db()
        try:
            cursor = await db.execute(
                """UPDATE usage_subscriptions
                   SET is_active = 0, updated_at = ?
                   WHERE stripe_subscription_id = ? AND is_active = 1""",
                (now, stripe_subscription_id),
            )
            await db.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info(
                    "Subscription deactivated in DB: stripe_subscription_id=%s",
                    stripe_subscription_id,
                )
            else:
                logger.warning(
                    "deactivate_subscription_by_stripe_id: no active row found for %s",
                    stripe_subscription_id,
                )
            return updated
        finally:
            await db.close()

    # ------------------------------------------------------------------
    # Stripe reporting
    # ------------------------------------------------------------------

    async def report_to_stripe(
        self,
        usage_id: str,
        stripe_customer_id: str,
    ) -> dict[str, Any]:
        """Report a usage event to Stripe metered billing.

        Uses Stripe's meter events API for usage-based billing.
        Falls back to recording locally if Stripe is not configured.

        Returns
        -------
        dict
            Contains ``reported`` (bool) and ``stripe_record_id`` (str).
        """
        if self._stripe is None:
            return {"reported": False, "reason": "stripe_not_configured"}

        try:
            # Use Stripe's billing meter events API
            meter_event = stripe.billing.MeterEvent.create(
                event_name="skill_execution",
                payload={
                    "stripe_customer_id": stripe_customer_id,
                    "value": "1",
                },
            )

            stripe_record_id = getattr(meter_event, "identifier", str(uuid.uuid4()))

            # Update the usage record with Stripe reference
            db = await self._get_db()
            try:
                await db.execute(
                    """UPDATE usage_records
                       SET stripe_usage_record_id = ?, status = 'billed'
                       WHERE id = ?""",
                    (stripe_record_id, usage_id),
                )
                await db.commit()
            finally:
                await db.close()

            logger.info(
                "Usage %s reported to Stripe for customer %s",
                usage_id, stripe_customer_id,
            )
            return {"reported": True, "stripe_record_id": stripe_record_id}

        except Exception as exc:
            logger.warning(
                "Failed to report usage %s to Stripe: %s",
                usage_id, exc,
            )
            return {"reported": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _report_to_stripe_safe(
        self,
        usage_id: str,
        stripe_customer_id: str,
    ) -> None:
        """Fire-and-forget wrapper for Stripe reporting.

        Never raises — logs warnings on failure.
        """
        try:
            await self.report_to_stripe(usage_id, stripe_customer_id)
        except Exception as exc:
            logger.warning("Stripe usage report failed (non-blocking): %s", exc)

    async def _get_subscription_row(
        self,
        db: aiosqlite.Connection,
        agent_id: str,
        user_id: str,
    ) -> Optional[aiosqlite.Row]:
        """Fetch the active subscription for an agent/user pair."""
        rows = await db.execute_fetchall(
            """SELECT * FROM usage_subscriptions
               WHERE agent_id = ? AND user_id = ? AND is_active = 1
               ORDER BY updated_at DESC LIMIT 1""",
            (agent_id, user_id),
        )
        return rows[0] if rows else None

    async def _get_month_count(
        self,
        db: aiosqlite.Connection,
        agent_id: str,
        year_month: str,
    ) -> int:
        """Get total action count for an agent this month."""
        rows = await db.execute_fetchall(
            """SELECT total_actions FROM usage_summary
               WHERE agent_id = ? AND year_month = ?""",
            (agent_id, year_month),
        )
        return rows[0]["total_actions"] if rows else 0

    async def _insert_record(
        self,
        db: aiosqlite.Connection,
        usage_id: str,
        agent_id: str,
        user_id: str,
        skill_name: str,
        action: str,
        amount_cents: int,
        status: str,
        created_at: str,
    ) -> None:
        """Insert a usage record row."""
        await db.execute(
            """INSERT INTO usage_records
               (id, agent_id, user_id, skill_name, action,
                amount_cents, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (usage_id, agent_id, user_id, skill_name, action,
             amount_cents, status, created_at),
        )

    async def _update_summary(
        self,
        db: aiosqlite.Connection,
        agent_id: str,
        year_month: str,
        total_incr: int,
        free_incr: int,
        billed_incr: int,
        now: str,
        amount_incr: int = 0,
    ) -> None:
        """Insert or update the monthly summary row."""
        summary_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO usage_summary
               (id, agent_id, year_month, total_actions, free_actions,
                billed_actions, total_amount_cents, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id, year_month)
               DO UPDATE SET
                   total_actions = total_actions + excluded.total_actions,
                   free_actions = free_actions + excluded.free_actions,
                   billed_actions = billed_actions + excluded.billed_actions,
                   total_amount_cents = total_amount_cents + excluded.total_amount_cents,
                   updated_at = excluded.updated_at
            """,
            (summary_id, agent_id, year_month,
             total_incr, free_incr, billed_incr, amount_incr,
             now, now),
        )
