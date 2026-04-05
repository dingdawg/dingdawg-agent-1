"""Comprehensive tests for the FinancialLedger and finance API routes.

Covers:
- Integer arithmetic precision (no float rounding)
- All transaction types (revenue + cost)
- Summary aggregation correctness
- Margin calculations
- Daily trend
- Cost rate management
- Transaction pagination and filtering
- Period boundaries (today, week, month, year, all)
- Multi-sector, multi-tier breakdowns
- Stripe fee math: 2.9% of $1.00 = 2 cents (NOT 2.9), + 30 = 32 total
- Admin access enforcement
- API route tests (auth required, 503 when ledger absent, correct JSON shapes)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from isg_agent.finance.ledger import (
    FinancialLedger,
    TXTYPE_ACTION_REVENUE,
    TXTYPE_API_COST,
    TXTYPE_INFRA_COST,
    TXTYPE_MARKETPLACE_PAYOUT,
    TXTYPE_MARKETPLACE_SALE,
    TXTYPE_PLATFORM_FEE,
    TXTYPE_REFUND,
    TXTYPE_STRIPE_FEE,
    TXTYPE_SUBSCRIPTION,
    TXTYPE_TTS_COST,
    TXTYPE_VOICE_COST,
    _stripe_fee_cents,
)


# ===========================================================================
# Integer arithmetic precision tests
# ===========================================================================


class TestStripeFeeArithmetic:
    """Verify that Stripe fee calculations use integer math, never floats."""

    def test_stripe_fee_one_dollar(self):
        """$1.00: 2.9% = 2 cents (integer division), + 30 = 32 cents total."""
        fee = _stripe_fee_cents(100)
        assert fee == 32
        # Explicit: (100 * 290) // 10000 = 29000 // 10000 = 2, + 30 = 32
        pct = (100 * 290) // 10000
        assert pct == 2
        assert fee == pct + 30

    def test_stripe_fee_zero(self):
        """Zero amount has only the fixed fee."""
        fee = _stripe_fee_cents(0)
        # 0 * 290 // 10000 = 0 + 30 = 30
        assert fee == 30

    def test_stripe_fee_twenty_nine_dollars(self):
        """$29.00 (2900 cents): 2.9% = 84 cents (integer), + 30 = 114 cents."""
        fee = _stripe_fee_cents(2900)
        pct = (2900 * 290) // 10000  # 841000 // 10000 = 84
        assert pct == 84
        assert fee == 84 + 30
        assert fee == 114

    def test_stripe_fee_fifty_nine_dollars(self):
        """$59.00 (5900 cents): 2.9% = 171 cents, + 30 = 201 cents."""
        fee = _stripe_fee_cents(5900)
        pct = (5900 * 290) // 10000  # 1711000 // 10000 = 171
        assert pct == 171
        assert fee == 171 + 30
        assert fee == 201

    def test_stripe_fee_is_integer_type(self):
        """Stripe fee must return an int, never float."""
        fee = _stripe_fee_cents(100)
        assert isinstance(fee, int)
        assert not isinstance(fee, float)

    def test_stripe_fee_no_rounding_error(self):
        """Classic float trap: 2.9 / 100 * 100 in float = 2.9000...001.
        Integer math must give exactly 2.
        """
        # Float would give: 100 * 0.029 = 2.9 (not a whole number!)
        float_pct = 100 * 0.029
        assert float_pct == pytest.approx(2.9)  # not 2!
        # Integer math gives: (100 * 290) // 10000 = 2
        int_pct = (100 * 290) // 10000
        assert int_pct == 2


# ===========================================================================
# FinancialLedger — Table Initialisation
# ===========================================================================


class TestFinancialLedgerInit:
    """Tests for table creation and idempotency."""

    @pytest.mark.asyncio
    async def test_init_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "finance.db")
        ledger = FinancialLedger(db_path=db_path)
        await ledger.init_tables()

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            for table in ("financial_ledger", "financial_daily_summary", "cost_rates"):
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                assert await cursor.fetchone() is not None, f"Table {table} not created"

    @pytest.mark.asyncio
    async def test_init_idempotent(self, tmp_path):
        db_path = str(tmp_path / "finance_idem.db")
        ledger = FinancialLedger(db_path=db_path)
        await ledger.init_tables()
        await ledger.init_tables()  # Must not raise

    @pytest.mark.asyncio
    async def test_indexes_created(self, tmp_path):
        db_path = str(tmp_path / "finance_idx.db")
        ledger = FinancialLedger(db_path=db_path)
        await ledger.init_tables()

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='financial_ledger'"
            )
            index_names = {row[0] for row in await cursor.fetchall()}
            assert "idx_ledger_created" in index_names
            assert "idx_ledger_type" in index_names
            assert "idx_ledger_agent" in index_names


# ===========================================================================
# FinancialLedger — Revenue Recording
# ===========================================================================


class TestRevenueRecording:
    """Tests for recording revenue transactions."""

    @pytest.mark.asyncio
    async def test_record_revenue_returns_id(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        tx_id = await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        assert isinstance(tx_id, str)
        assert len(tx_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_record_revenue_amount_stored(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100, sector="business")

        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] == 100

    @pytest.mark.asyncio
    async def test_record_multiple_revenues_sum(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        # 3 x $1 actions + 1 x $29 subscription
        for _ in range(3):
            await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_revenue(TXTYPE_SUBSCRIPTION, 2900)

        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] == 300 + 2900
        assert result["total_revenue_cents"] == 3200

    @pytest.mark.asyncio
    async def test_record_revenue_with_full_context(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        tx_id = await ledger.record_revenue(
            TXTYPE_ACTION_REVENUE,
            100,
            agent_id="agent_abc",
            user_id="user_xyz",
            subscription_tier="pro",
            sector="business",
            industry="restaurant",
            external_ref="ch_abc123",
            description="Test action",
            metadata={"action": "send_email"},
        )
        assert tx_id

        # Verify it appears in transactions
        txs = await ledger.get_transactions(agent_id="agent_abc")
        assert txs["total"] >= 1
        item = txs["items"][0]
        assert item["amount_cents"] == 100
        assert item["direction"] == "revenue"
        assert item["sector"] == "business"
        assert item["subscription_tier"] == "pro"

    @pytest.mark.asyncio
    async def test_all_revenue_types_accepted(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        for tx_type in (
            TXTYPE_ACTION_REVENUE,
            TXTYPE_SUBSCRIPTION,
            TXTYPE_MARKETPLACE_SALE,
            TXTYPE_PLATFORM_FEE,
        ):
            tx_id = await ledger.record_revenue(tx_type, 100)
            assert tx_id


# ===========================================================================
# FinancialLedger — Cost Recording
# ===========================================================================


class TestCostRecording:
    """Tests for recording cost transactions."""

    @pytest.mark.asyncio
    async def test_record_cost_direction(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        result = await ledger.get_summary(period="all")
        assert result["total_cost_cents"] == 32
        assert result["total_revenue_cents"] == 0

    @pytest.mark.asyncio
    async def test_cost_reduces_profit(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)
        await ledger.record_cost(TXTYPE_API_COST, 10)

        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] == 100
        assert result["total_cost_cents"] == 42
        assert result["net_profit_cents"] == 58
        # Margin: 58 / 100 = 58%
        assert result["margin_pct"] == 58.0

    @pytest.mark.asyncio
    async def test_all_cost_types_accepted(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        for tx_type in (
            TXTYPE_STRIPE_FEE,
            TXTYPE_API_COST,
            TXTYPE_INFRA_COST,
            TXTYPE_TTS_COST,
            TXTYPE_VOICE_COST,
            TXTYPE_MARKETPLACE_PAYOUT,
            TXTYPE_REFUND,
        ):
            tx_id = await ledger.record_cost(tx_type, 10)
            assert tx_id

    @pytest.mark.asyncio
    async def test_zero_cost_allowed(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        tx_id = await ledger.record_cost(TXTYPE_TTS_COST, 0, description="Free browser TTS")
        assert tx_id


# ===========================================================================
# FinancialLedger — Append-Only Audit Trail
# ===========================================================================


class TestAppendOnly:
    """Verify the ledger is append-only (no UPDATE/DELETE on ledger rows)."""

    @pytest.mark.asyncio
    async def test_transactions_never_deleted(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        tx_id = await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)

        # Record a second tx — first should still exist
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 200)
        txs = await ledger.get_transactions()
        assert txs["total"] == 2
        ids = {item["id"] for item in txs["items"]}
        assert tx_id in ids

    @pytest.mark.asyncio
    async def test_running_total_accumulates(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        amounts = [100, 200, 150, 50, 75]
        for a in amounts:
            await ledger.record_revenue(TXTYPE_ACTION_REVENUE, a)

        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] == sum(amounts)


# ===========================================================================
# FinancialLedger — record_action
# ===========================================================================


class TestRecordAction:
    """Tests for the convenience record_action method."""

    @pytest.mark.asyncio
    async def test_record_action_creates_revenue(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        revenue_id = await ledger.record_action(
            agent_id="agent1",
            user_id="user1",
            action_name="send_email",
        )
        assert revenue_id

        # Must have $1 revenue recorded
        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] >= 100

    @pytest.mark.asyncio
    async def test_record_action_creates_stripe_fee(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        await ledger.record_action("agent1", "user1", "send_email")

        # Stripe fee should be 32 cents for $1.00
        txs = await ledger.get_transactions(tx_type=TXTYPE_STRIPE_FEE, direction="cost")
        assert txs["total"] >= 1
        stripe_row = txs["items"][0]
        assert stripe_row["amount_cents"] == 32

    @pytest.mark.asyncio
    async def test_record_action_creates_api_cost(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        # Seed a cost rate first
        await ledger.update_cost_rate("openai_api", 10, "per_1k_tokens")
        await ledger.record_action("agent1", "user1", "chat_response")

        txs = await ledger.get_transactions(tx_type=TXTYPE_API_COST, direction="cost")
        assert txs["total"] >= 1
        api_row = txs["items"][0]
        assert api_row["amount_cents"] == 10

    @pytest.mark.asyncio
    async def test_record_action_default_api_cost_when_no_rate(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        # No cost rates seeded

        await ledger.record_action("agent1", "user1", "some_skill")

        # Default is 10 cents API cost
        txs = await ledger.get_transactions(tx_type=TXTYPE_API_COST, direction="cost")
        assert txs["total"] >= 1
        assert txs["items"][0]["amount_cents"] == 10

    @pytest.mark.asyncio
    async def test_record_action_with_sector_and_tier(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        await ledger.record_action(
            agent_id="agent1",
            user_id="user1",
            action_name="book_appointment",
            sector="health",
            industry="dental",
            subscription_tier="pro",
        )

        txs = await ledger.get_transactions(tx_type=TXTYPE_ACTION_REVENUE)
        assert txs["total"] >= 1
        item = txs["items"][0]
        assert item["sector"] == "health"
        assert item["industry"] == "dental"
        assert item["subscription_tier"] == "pro"

    @pytest.mark.asyncio
    async def test_record_action_net_profit_calculation(self, tmp_path):
        """Verify net profit for a $1 action with known costs."""
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.update_cost_rate("openai_api", 10, "per_1k_tokens")

        await ledger.record_action("agent1", "user1", "do_thing")

        result = await ledger.get_summary(period="all")
        # Revenue: 100 cents
        assert result["total_revenue_cents"] == 100
        # Costs: 32 (Stripe) + 10 (API) = 42 cents
        assert result["total_cost_cents"] == 42
        # Net profit: 100 - 42 = 58 cents
        assert result["net_profit_cents"] == 58
        # Margin: 58%
        assert result["margin_pct"] == 58.0


# ===========================================================================
# FinancialLedger — record_subscription
# ===========================================================================


class TestRecordSubscription:
    """Tests for recording subscription payments."""

    @pytest.mark.asyncio
    async def test_record_subscription_revenue(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        await ledger.record_subscription("user1", "starter", 2900, "ch_abc")

        txs = await ledger.get_transactions(tx_type=TXTYPE_SUBSCRIPTION, direction="revenue")
        assert txs["total"] == 1
        item = txs["items"][0]
        assert item["amount_cents"] == 2900
        assert item["subscription_tier"] == "starter"
        assert item["external_ref"] == "ch_abc"

    @pytest.mark.asyncio
    async def test_record_subscription_stripe_fee(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        await ledger.record_subscription("user1", "pro", 7900, "ch_xyz")

        # Stripe fee for $79.00: (7900 * 290) // 10000 = 229100 // 10000 = 22, + 30 = 52... wait
        # Recalculate: 7900 * 290 = 2291000, // 10000 = 229, + 30 = 259
        expected_fee = (7900 * 290) // 10000 + 30
        txs = await ledger.get_transactions(tx_type=TXTYPE_STRIPE_FEE, direction="cost")
        assert txs["total"] == 1
        assert txs["items"][0]["amount_cents"] == expected_fee

    @pytest.mark.asyncio
    async def test_subscription_stripe_fee_precision(self):
        """Verify $29.00 subscription Stripe fee is integer-exact."""
        # $29.00 = 2900 cents
        fee = _stripe_fee_cents(2900)
        pct = (2900 * 290) // 10000  # 841000 // 10000 = 84
        assert pct == 84
        assert fee == 84 + 30
        assert fee == 114
        # float would give: 2900 * 0.029 = 84.1 (not 84!)
        float_pct = 2900 * 0.029
        assert float_pct != 84  # confirms float gives wrong answer


# ===========================================================================
# FinancialLedger — get_summary
# ===========================================================================


class TestGetSummary:
    """Tests for summary aggregation across periods, sectors, and tiers."""

    @pytest.mark.asyncio
    async def test_empty_summary(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] == 0
        assert result["total_cost_cents"] == 0
        assert result["net_profit_cents"] == 0
        assert result["margin_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_summary_period_today(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        result = await ledger.get_summary(period="today")
        assert result["total_revenue_cents"] == 100
        assert result["period"] == "today"

    @pytest.mark.asyncio
    async def test_summary_period_all(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 500)
        await ledger.record_revenue(TXTYPE_SUBSCRIPTION, 2900)
        result = await ledger.get_summary(period="all")
        assert result["total_revenue_cents"] == 3400

    @pytest.mark.asyncio
    async def test_summary_margin_calculation(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        # 1000 cents revenue, 200 cents costs
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 1000)
        await ledger.record_cost(TXTYPE_API_COST, 200)
        result = await ledger.get_summary(period="all")
        # Margin: (1000 - 200) / 1000 * 100 = 80%
        assert result["net_profit_cents"] == 800
        assert result["margin_pct"] == 80.0

    @pytest.mark.asyncio
    async def test_summary_by_sector(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 500, sector="business")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 300, sector="personal")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 200, sector="health")

        result = await ledger.get_summary(period="all")
        by_sector = result["by_sector"]

        assert "business" in by_sector
        assert "personal" in by_sector
        assert "health" in by_sector
        assert by_sector["business"]["revenue"] == 500
        assert by_sector["personal"]["revenue"] == 300
        assert by_sector["health"]["revenue"] == 200

    @pytest.mark.asyncio
    async def test_summary_by_tier(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 400, subscription_tier="free")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 1200, subscription_tier="pro")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 800, subscription_tier="starter")

        result = await ledger.get_summary(period="all")
        by_tier = result["by_tier"]

        assert "free" in by_tier
        assert "pro" in by_tier
        assert "starter" in by_tier
        assert by_tier["free"]["revenue"] == 400
        assert by_tier["pro"]["revenue"] == 1200
        assert by_tier["starter"]["revenue"] == 800

    @pytest.mark.asyncio
    async def test_summary_sector_filter(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 500, sector="business")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 300, sector="personal")

        # Filter to business only
        result = await ledger.get_summary(period="all", sector="business")
        assert result["total_revenue_cents"] == 500

    @pytest.mark.asyncio
    async def test_summary_tier_filter(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 700, subscription_tier="pro")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 200, subscription_tier="free")

        result = await ledger.get_summary(period="all", tier="pro")
        assert result["total_revenue_cents"] == 700

    @pytest.mark.asyncio
    async def test_summary_breakdown_by_type(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 200)
        await ledger.record_revenue(TXTYPE_SUBSCRIPTION, 2900)

        result = await ledger.get_summary(period="all")
        breakdown = result["breakdown"]
        assert TXTYPE_ACTION_REVENUE in breakdown
        assert TXTYPE_SUBSCRIPTION in breakdown
        assert breakdown[TXTYPE_ACTION_REVENUE]["revenue"]["total_cents"] == 300
        assert breakdown[TXTYPE_ACTION_REVENUE]["revenue"]["count"] == 2
        assert breakdown[TXTYPE_SUBSCRIPTION]["revenue"]["total_cents"] == 2900


# ===========================================================================
# FinancialLedger — get_margins
# ===========================================================================


class TestGetMargins:
    """Tests for margin analysis."""

    @pytest.mark.asyncio
    async def test_margins_empty(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        margins = await ledger.get_margins()
        assert margins["overall"]["total_revenue_cents"] == 0
        assert margins["overall"]["net_profit_cents"] == 0

    @pytest.mark.asyncio
    async def test_margins_overall(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 10000)
        await ledger.record_cost(TXTYPE_API_COST, 1000)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 320)

        margins = await ledger.get_margins()
        overall = margins["overall"]
        assert overall["total_revenue_cents"] == 10000
        assert overall["total_cost_cents"] == 1320
        assert overall["net_profit_cents"] == 8680
        # Margin: 8680 / 10000 * 100 = 86.8%
        assert overall["margin_pct"] == 86.8

    @pytest.mark.asyncio
    async def test_margins_by_sector(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 5000, sector="business")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 2000, sector="personal")

        margins = await ledger.get_margins()
        by_sector = margins["by_sector"]
        assert "business" in by_sector
        assert "personal" in by_sector
        assert by_sector["business"]["revenue"] == 5000
        assert by_sector["personal"]["revenue"] == 2000
        # No costs, so margin = 100%
        assert by_sector["business"]["margin_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_margins_by_tier(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 3000, subscription_tier="starter")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 8000, subscription_tier="pro")

        margins = await ledger.get_margins()
        by_tier = margins["by_tier"]
        assert "starter" in by_tier
        assert "pro" in by_tier
        assert by_tier["pro"]["revenue"] == 8000
        assert by_tier["starter"]["revenue"] == 3000

    @pytest.mark.asyncio
    async def test_margins_cost_breakdown(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 320)
        await ledger.record_cost(TXTYPE_API_COST, 100)
        await ledger.record_cost(TXTYPE_INFRA_COST, 2000)

        margins = await ledger.get_margins()
        cost_breakdown = margins["cost_breakdown"]
        assert TXTYPE_STRIPE_FEE in cost_breakdown
        assert TXTYPE_API_COST in cost_breakdown
        assert TXTYPE_INFRA_COST in cost_breakdown
        assert cost_breakdown[TXTYPE_INFRA_COST]["total_cents"] == 2000
        assert cost_breakdown[TXTYPE_STRIPE_FEE]["total_cents"] == 320


# ===========================================================================
# FinancialLedger — get_daily_trend
# ===========================================================================


class TestDailyTrend:
    """Tests for daily trend data."""

    @pytest.mark.asyncio
    async def test_trend_empty(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        trend = await ledger.get_daily_trend(days=30)
        assert trend == []

    @pytest.mark.asyncio
    async def test_trend_today(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        trend = await ledger.get_daily_trend(days=1)
        assert len(trend) == 1
        day = trend[0]
        assert day["revenue_cents"] == 100
        assert day["cost_cents"] == 32
        assert day["profit_cents"] == 68

    @pytest.mark.asyncio
    async def test_trend_margin_zero_revenue(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_cost(TXTYPE_INFRA_COST, 2000)

        trend = await ledger.get_daily_trend(days=1)
        assert len(trend) == 1
        day = trend[0]
        # No revenue, so margin = 0%
        assert day["margin_pct"] == 0.0
        assert day["profit_cents"] == -2000

    @pytest.mark.asyncio
    async def test_trend_has_required_keys(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 500)

        trend = await ledger.get_daily_trend()
        assert len(trend) >= 1
        day = trend[0]
        assert "date" in day
        assert "revenue_cents" in day
        assert "cost_cents" in day
        assert "profit_cents" in day
        assert "margin_pct" in day


# ===========================================================================
# FinancialLedger — Cost Rate Management
# ===========================================================================


class TestCostRates:
    """Tests for cost rate CRUD."""

    @pytest.mark.asyncio
    async def test_update_cost_rate_insert(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.update_cost_rate("openai_api", 10, "per_1k_tokens", "GPT-4o-mini")

        rates = await ledger.get_cost_rates()
        assert len(rates) == 1
        assert rates[0]["cost_type"] == "openai_api"
        assert rates[0]["rate_cents"] == 10
        assert rates[0]["unit"] == "per_1k_tokens"
        assert rates[0]["description"] == "GPT-4o-mini"

    @pytest.mark.asyncio
    async def test_update_cost_rate_upsert(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.update_cost_rate("openai_api", 10, "per_1k_tokens")
        # Update to new rate
        await ledger.update_cost_rate("openai_api", 15, "per_1k_tokens", "Updated rate")

        rates = await ledger.get_cost_rates()
        assert len(rates) == 1  # Still one entry (upserted)
        assert rates[0]["rate_cents"] == 15
        assert rates[0]["description"] == "Updated rate"

    @pytest.mark.asyncio
    async def test_all_default_rates_can_be_seeded(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        default_rates = [
            ("openai_api", 10, "per_1k_tokens", "GPT-4o-mini API cost estimate"),
            ("stripe_percentage", 290, "per_10k_basis", "Stripe 2.9%"),
            ("stripe_fixed", 30, "per_transaction", "Stripe $0.30 fixed"),
            ("hosting", 2000, "per_month", "Railway hosting"),
            ("browser_tts", 0, "per_request", "Free browser TTS"),
            ("kokoro_tts", 1, "per_request", "Kokoro TTS"),
            ("elevenlabs_tts", 5, "per_request", "ElevenLabs TTS"),
            ("vapi_telephony", 10, "per_minute", "Vapi telephony"),
        ]

        for cost_type, rate, unit, desc in default_rates:
            await ledger.update_cost_rate(cost_type, rate, unit, desc)

        rates = await ledger.get_cost_rates()
        assert len(rates) == 8
        rate_map = {r["cost_type"]: r for r in rates}
        assert rate_map["hosting"]["rate_cents"] == 2000
        assert rate_map["browser_tts"]["rate_cents"] == 0
        assert rate_map["vapi_telephony"]["rate_cents"] == 10

    @pytest.mark.asyncio
    async def test_get_cost_rates_ordered_by_type(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.update_cost_rate("z_type", 5, "unit")
        await ledger.update_cost_rate("a_type", 10, "unit")
        await ledger.update_cost_rate("m_type", 1, "unit")

        rates = await ledger.get_cost_rates()
        types = [r["cost_type"] for r in rates]
        assert types == sorted(types)


# ===========================================================================
# FinancialLedger — Transaction Pagination and Filtering
# ===========================================================================


class TestTransactions:
    """Tests for get_transactions pagination and filtering."""

    @pytest.mark.asyncio
    async def test_transactions_empty(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        result = await ledger.get_transactions()
        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_transactions_all(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        for _ in range(5):
            await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        for _ in range(3):
            await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        result = await ledger.get_transactions()
        assert result["total"] == 8

    @pytest.mark.asyncio
    async def test_transactions_filter_by_direction(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        rev_result = await ledger.get_transactions(direction="revenue")
        cost_result = await ledger.get_transactions(direction="cost")
        assert rev_result["total"] == 1
        assert cost_result["total"] == 1
        assert rev_result["items"][0]["direction"] == "revenue"
        assert cost_result["items"][0]["direction"] == "cost"

    @pytest.mark.asyncio
    async def test_transactions_filter_by_type(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_revenue(TXTYPE_SUBSCRIPTION, 2900)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        result = await ledger.get_transactions(tx_type=TXTYPE_SUBSCRIPTION)
        assert result["total"] == 1
        assert result["items"][0]["amount_cents"] == 2900

    @pytest.mark.asyncio
    async def test_transactions_filter_by_agent(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100, agent_id="agent_a")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 200, agent_id="agent_b")
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 150, agent_id="agent_a")

        result = await ledger.get_transactions(agent_id="agent_a")
        assert result["total"] == 2
        assert all(item["agent_id"] == "agent_a" for item in result["items"])

    @pytest.mark.asyncio
    async def test_transactions_pagination(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        for i in range(25):
            await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100 + i)

        # Page 1 (limit=10, offset=0)
        page1 = await ledger.get_transactions(limit=10, offset=0)
        assert page1["total"] == 25
        assert len(page1["items"]) == 10
        assert page1["limit"] == 10
        assert page1["offset"] == 0

        # Page 2 (limit=10, offset=10)
        page2 = await ledger.get_transactions(limit=10, offset=10)
        assert len(page2["items"]) == 10

        # Page 3 (limit=10, offset=20) — only 5 items
        page3 = await ledger.get_transactions(limit=10, offset=20)
        assert len(page3["items"]) == 5

    @pytest.mark.asyncio
    async def test_transactions_limit_max_enforced(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        # Requesting more than 1000 should be capped at 1000
        result = await ledger.get_transactions(limit=9999)
        assert result["limit"] == 1000

    @pytest.mark.asyncio
    async def test_transactions_date_filter(self, tmp_path):
        """Date filtering returns rows within the specified range."""
        from datetime import datetime, timezone
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = await ledger.get_transactions(start_date=today, end_date=today)
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_transactions_items_have_required_fields(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(
            TXTYPE_ACTION_REVENUE, 100,
            agent_id="ag1", user_id="u1",
            sector="business", subscription_tier="pro",
        )
        result = await ledger.get_transactions()
        assert result["total"] >= 1
        item = result["items"][0]
        required = {
            "id", "created_at", "tx_type", "amount_cents", "direction",
            "agent_id", "user_id", "subscription_tier", "sector",
        }
        for field in required:
            assert field in item, f"Missing field: {field}"


# ===========================================================================
# FinancialLedger — get_health_snapshot
# ===========================================================================


class TestHealthSnapshot:
    """Tests for the quick P&L snapshot."""

    @pytest.mark.asyncio
    async def test_health_snapshot_empty(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        snap = await ledger.get_health_snapshot()
        assert "today" in snap
        assert "mtd" in snap
        assert "all_time" in snap
        assert snap["all_time"]["revenue_cents"] == 0

    @pytest.mark.asyncio
    async def test_health_snapshot_with_data(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 500)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        snap = await ledger.get_health_snapshot()
        all_time = snap["all_time"]
        assert all_time["revenue_cents"] == 500
        assert all_time["cost_cents"] == 32
        assert all_time["profit_cents"] == 468
        assert all_time["margin_pct"] == pytest.approx(93.6, abs=0.1)

    @pytest.mark.asyncio
    async def test_health_snapshot_keys(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        snap = await ledger.get_health_snapshot()
        for bucket in ("today", "mtd", "all_time"):
            assert bucket in snap
            b = snap[bucket]
            assert "revenue_cents" in b
            assert "cost_cents" in b
            assert "profit_cents" in b
            assert "margin_pct" in b


# ===========================================================================
# Multi-sector and Multi-tier Breakdown Tests
# ===========================================================================


class TestMultiDimensional:
    """Tests for multi-sector and multi-tier breakdown accuracy."""

    @pytest.mark.asyncio
    async def test_seven_sectors(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        sectors = ["personal", "business", "b2b", "a2a", "compliance", "enterprise", "health"]
        for i, sector in enumerate(sectors):
            await ledger.record_revenue(TXTYPE_ACTION_REVENUE, (i + 1) * 100, sector=sector)

        result = await ledger.get_summary(period="all")
        by_sector = result["by_sector"]
        for sector in sectors:
            assert sector in by_sector

    @pytest.mark.asyncio
    async def test_sector_margin_with_costs(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        # Business: 1000 revenue
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 1000, sector="business")
        # Personal: 2000 revenue
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 2000, sector="personal")

        margins = await ledger.get_margins()
        by_sector = margins["by_sector"]

        assert by_sector["business"]["revenue"] == 1000
        assert by_sector["personal"]["revenue"] == 2000
        # No sector-specific costs in this test, margin = 100%
        assert by_sector["business"]["margin_pct"] == 100.0
        assert by_sector["personal"]["margin_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_four_tiers(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        tier_revenues = {"free": 500, "starter": 2900, "pro": 7900, "enterprise": 19900}
        for tier, amount in tier_revenues.items():
            await ledger.record_revenue(TXTYPE_SUBSCRIPTION, amount, subscription_tier=tier)

        margins = await ledger.get_margins()
        by_tier = margins["by_tier"]
        for tier, expected_rev in tier_revenues.items():
            assert tier in by_tier
            assert by_tier[tier]["revenue"] == expected_rev


# ===========================================================================
# API Routes — Finance Endpoints
# ===========================================================================


def _create_test_app(
    *,
    auth_user_id: str = "",
    auth_email: str = "",
    ledger: "FinancialLedger | None" = None,
    admin_users: "str | None" = None,
):
    """Create a minimal FastAPI app with only the finance router for testing."""
    import os
    from fastapi import FastAPI
    from isg_agent.api.deps import CurrentUser, require_auth
    from isg_agent.api.routes.finance import router as finance_router

    # Override FINANCE_ADMIN_USERS for testing
    if admin_users is not None:
        os.environ["FINANCE_ADMIN_USERS"] = admin_users
    else:
        os.environ.pop("FINANCE_ADMIN_USERS", None)
        os.environ.pop("MARKETPLACE_ADMIN_USERS", None)

    app = FastAPI()
    app.include_router(finance_router)

    if ledger is not None:
        app.state.ledger = ledger

    if auth_user_id:
        user = CurrentUser(user_id=auth_user_id, email=auth_email)

        async def _override_auth() -> CurrentUser:
            return user

        app.dependency_overrides[require_auth] = _override_auth

    return app


class TestFinanceApiAuth:
    """Tests for authentication requirements on finance endpoints."""

    @pytest.mark.asyncio
    async def test_summary_requires_auth(self):
        app = _create_test_app()  # No auth
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_margins_requires_auth(self):
        app = _create_test_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/margins")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_trend_requires_auth(self):
        app = _create_test_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/trend")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_transactions_requires_auth(self):
        app = _create_test_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/transactions")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cost_rates_requires_auth(self):
        app = _create_test_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/cost-rates")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_health_requires_auth(self):
        app = _create_test_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/health")
            assert resp.status_code == 401


class TestFinanceApiNoLedger:
    """Tests for 503 responses when ledger is not initialised."""

    @pytest.mark.asyncio
    async def test_summary_503_no_ledger(self):
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com")
        # No ledger set on app.state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary")
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_margins_503_no_ledger(self):
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/margins")
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_health_503_no_ledger(self):
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/health")
            assert resp.status_code == 503


class TestFinanceApiSummary:
    """Tests for GET /api/v1/finance/summary endpoint."""

    @pytest.mark.asyncio
    async def test_summary_success(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 500)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary?period=all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_revenue_cents"] == 500
            assert data["total_cost_cents"] == 32
            assert data["net_profit_cents"] == 468
            assert data["period"] == "all"

    @pytest.mark.asyncio
    async def test_summary_invalid_period(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary?period=invalid_period")
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_summary_response_shape(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary")
            assert resp.status_code == 200
            data = resp.json()
            required_keys = {
                "period", "total_revenue_cents", "total_cost_cents",
                "net_profit_cents", "margin_pct", "breakdown",
                "by_sector", "by_tier",
            }
            for key in required_keys:
                assert key in data, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_summary_all_valid_periods(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for period in ("today", "week", "month", "year", "all"):
                resp = await c.get(f"/api/v1/finance/summary?period={period}")
                assert resp.status_code == 200, f"Period {period} failed: {resp.text}"


class TestFinanceApiMargins:
    """Tests for GET /api/v1/finance/margins endpoint."""

    @pytest.mark.asyncio
    async def test_margins_success(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 1000, sector="business")

        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/margins")
            assert resp.status_code == 200
            data = resp.json()
            assert "overall" in data
            assert "by_sector" in data
            assert "by_tier" in data
            assert "cost_breakdown" in data
            assert data["overall"]["total_revenue_cents"] == 1000


class TestFinanceApiTrend:
    """Tests for GET /api/v1/finance/trend endpoint."""

    @pytest.mark.asyncio
    async def test_trend_success(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)

        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/trend?days=7")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_trend_day_param_validation(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # days > 365 should be rejected (Query max=365)
            resp = await c.get("/api/v1/finance/trend?days=999")
            assert resp.status_code == 422  # FastAPI validation error


class TestFinanceApiTransactions:
    """Tests for GET /api/v1/finance/transactions endpoint."""

    @pytest.mark.asyncio
    async def test_transactions_success(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/transactions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert "items" in data
            assert "offset" in data
            assert "limit" in data

    @pytest.mark.asyncio
    async def test_transactions_filter_by_direction_via_api(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 100)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/transactions?direction=revenue")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["items"][0]["direction"] == "revenue"

    @pytest.mark.asyncio
    async def test_transactions_invalid_direction(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/transactions?direction=sideways")
            assert resp.status_code == 400


class TestFinanceApiCostRates:
    """Tests for cost-rates endpoints."""

    @pytest.mark.asyncio
    async def test_list_cost_rates_empty(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/cost-rates")
            assert resp.status_code == 200
            assert resp.json() == []

    @pytest.mark.asyncio
    async def test_update_cost_rate_via_api(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/v1/finance/cost-rates/openai_api",
                json={"rate_cents": 15, "unit": "per_1k_tokens", "description": "Updated"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["cost_type"] == "openai_api"
            assert data["rate_cents"] == 15
            assert data["unit"] == "per_1k_tokens"

    @pytest.mark.asyncio
    async def test_update_cost_rate_negative_rejected(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/v1/finance/cost-rates/test_rate",
                json={"rate_cents": -5, "unit": "per_request"},
            )
            assert resp.status_code == 422  # FastAPI validation (ge=0)

    @pytest.mark.asyncio
    async def test_cost_rate_list_after_update(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Add two rates
            await c.put(
                "/api/v1/finance/cost-rates/openai_api",
                json={"rate_cents": 10, "unit": "per_1k_tokens"},
            )
            await c.put(
                "/api/v1/finance/cost-rates/hosting",
                json={"rate_cents": 2000, "unit": "per_month"},
            )
            resp = await c.get("/api/v1/finance/cost-rates")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2


class TestFinanceApiHealth:
    """Tests for GET /api/v1/finance/health endpoint."""

    @pytest.mark.asyncio
    async def test_health_success(self, tmp_path):
        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.record_revenue(TXTYPE_ACTION_REVENUE, 300)
        await ledger.record_cost(TXTYPE_STRIPE_FEE, 32)

        app = _create_test_app(auth_user_id="user1", auth_email="a@b.com", ledger=ledger)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "today" in data
            assert "mtd" in data
            assert "all_time" in data
            assert data["all_time"]["revenue_cents"] == 300
            assert data["all_time"]["cost_cents"] == 32
            assert data["all_time"]["profit_cents"] == 268


class TestFinanceApiAdminGate:
    """Tests for admin access enforcement."""

    @pytest.mark.asyncio
    async def test_admin_gate_blocks_non_admin(self, tmp_path, monkeypatch):
        """When FINANCE_ADMIN_USERS is set, non-admin users get 403."""
        import os
        monkeypatch.setenv("FINANCE_ADMIN_USERS", "admin_user_id")

        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        # Reload the module to pick up the new env var
        import importlib
        import isg_agent.api.routes.finance as finance_module
        importlib.reload(finance_module)

        from fastapi import FastAPI
        from isg_agent.api.deps import CurrentUser, require_auth

        app = FastAPI()
        app.include_router(finance_module.router)
        app.state.ledger = ledger

        non_admin = CurrentUser(user_id="regular_user", email="user@test.com")

        async def _override() -> CurrentUser:
            return non_admin

        app.dependency_overrides[require_auth] = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary")
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_gate_allows_admin(self, tmp_path, monkeypatch):
        """Admin user should have access."""
        monkeypatch.setenv("FINANCE_ADMIN_USERS", "admin_user_id")

        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        import importlib
        import isg_agent.api.routes.finance as finance_module
        importlib.reload(finance_module)

        from fastapi import FastAPI
        from isg_agent.api.deps import CurrentUser, require_auth

        app = FastAPI()
        app.include_router(finance_module.router)
        app.state.ledger = ledger

        admin_user = CurrentUser(user_id="admin_user_id", email="admin@test.com")

        async def _override() -> CurrentUser:
            return admin_user

        app.dependency_overrides[require_auth] = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_admin_list_allows_any_user(self, tmp_path, monkeypatch):
        """When no admin users configured, any authenticated user can access."""
        monkeypatch.delenv("FINANCE_ADMIN_USERS", raising=False)
        monkeypatch.delenv("MARKETPLACE_ADMIN_USERS", raising=False)

        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()

        import importlib
        import isg_agent.api.routes.finance as finance_module
        importlib.reload(finance_module)

        from fastapi import FastAPI
        from isg_agent.api.deps import CurrentUser, require_auth

        app = FastAPI()
        app.include_router(finance_module.router)
        app.state.ledger = ledger

        any_user = CurrentUser(user_id="any_user", email="any@test.com")

        async def _override() -> CurrentUser:
            return any_user

        app.dependency_overrides[require_auth] = _override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/finance/summary")
            assert resp.status_code == 200


# ===========================================================================
# Integration: SkillExecutor → FinancialLedger
# ===========================================================================


class TestSkillExecutorLedgerIntegration:
    """Integration test: verify the ledger hook wires correctly to SkillExecutor."""

    @pytest.mark.asyncio
    async def test_action_recorded_on_skill_execution(self, tmp_path):
        """Simulate the app.py hook: after skill execution, record_action is called."""
        from isg_agent.skills.executor import SkillExecutor

        ledger = FinancialLedger(str(tmp_path / "f.db"))
        await ledger.init_tables()
        await ledger.update_cost_rate("openai_api", 10, "per_1k_tokens")

        executor = SkillExecutor()
        executor.register_skill("send_email", lambda params: "sent!")

        async def _combined_hook(skill_name, parameters, result):
            agent_id = parameters.get("agent_id", "default")
            user_id = parameters.get("user_id", "system")
            # Non-blocking best-effort
            try:
                await ledger.record_action(
                    agent_id=agent_id,
                    user_id=user_id,
                    action_name=skill_name,
                    sector=parameters.get("sector"),
                )
            except Exception:
                pass

        executor.set_post_execute_hook(_combined_hook)

        # Execute 3 skill calls
        for _ in range(3):
            result = await executor.execute(
                "send_email",
                {"agent_id": "agent_biz", "user_id": "user_a", "sector": "business"},
            )
            assert result.success

        # Ledger should have 3 revenue + 3 Stripe fees + 3 API costs = 9 rows
        txs = await ledger.get_transactions()
        assert txs["total"] == 9

        summary = await ledger.get_summary(period="all")
        # 3 x $1 = 300 cents revenue
        assert summary["total_revenue_cents"] == 300
        # 3 x 32 Stripe + 3 x 10 API = 96 + 30 = 126 cents costs
        assert summary["total_cost_cents"] == 126
        assert summary["net_profit_cents"] == 174

    @pytest.mark.asyncio
    async def test_hook_failure_does_not_break_execution(self, tmp_path):
        """If ledger.record_action raises, the skill execution must still succeed."""
        from isg_agent.skills.executor import SkillExecutor

        executor = SkillExecutor()
        executor.register_skill("my_skill", lambda params: "output")

        async def _failing_hook(skill_name, parameters, result):
            raise RuntimeError("Ledger is down!")

        executor.set_post_execute_hook(_failing_hook)

        result = await executor.execute("my_skill", {"agent_id": "ag1"})
        # Execution must succeed even if ledger hook fails
        assert result.success
        assert result.output == "output"
