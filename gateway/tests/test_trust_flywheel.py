"""Behavioral contract for the trust flywheel (Wave 3, AGENT_NATIVE_EMPIRE).

Single receipt writer shared by the public API and the ACP checkout hook;
public trust-score aggregation with the empty-trail edge case (score null,
never 0 or 100 by default).
"""
from __future__ import annotations

import aiosqlite
import pytest

from isg_agent.db.receipts import persist_receipt, trust_summary

_DDL = """
CREATE TABLE IF NOT EXISTS atr_receipts (
    receipt_id TEXT PRIMARY KEY, agent_id TEXT, decision TEXT,
    decision_reason TEXT, timestamp TEXT, subject_id TEXT,
    policy_version TEXT, confidence_score INTEGER,
    parent_receipt_id TEXT, verification_endpoint TEXT
);
"""


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "flywheel-test.db")


async def _init(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_DDL)
        await db.commit()


BASE = "https://api.dingdawg.com"


class TestSingleWriter:
    @pytest.mark.asyncio
    async def test_persist_returns_verifiable_receipt(self, db_path):
        """SCENARIO: A compliance auditor pulls the verification URL from a
                   receipt produced during an automated agent purchase.
        GIVEN:    An initialized receipts table on a production-shaped DB.
        WHEN:     The single writer persists an APPROVE decision for an
                  agent completing an ACP checkout order.
        THEN:     The returned document carries a public verification URL
                  and the row is queryable by the same receipt_id.
        """
        await _init(db_path)
        r = await persist_receipt(
            db_path=db_path, base_url=BASE, agent_id="@night-buyer",
            decision="APPROVE", decision_reason="ACP order within limits",
            subject_id="order_123",
        )
        assert r["verification_endpoint"] == f"{BASE}/api/v1/public/receipt/{r['receipt_id']}"
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT decision FROM atr_receipts WHERE receipt_id=?",
                (r["receipt_id"],),
            ) as cur:
                row = await cur.fetchone()
        assert row == ("APPROVE",)

    @pytest.mark.asyncio
    async def test_invalid_decision_rejected_at_writer_boundary(self, db_path):
        """SCENARIO: A future caller wires the writer with a typo'd decision
                   value during a refactor nobody reviewed closely enough.
        GIVEN:    An initialized receipts table ready to accept rows.
        WHEN:     The writer is invoked with decision='APPROVED' (invalid).
        THEN:     ValueError raises before any row is written anywhere.
        """
        await _init(db_path)
        with pytest.raises(ValueError):
            await persist_receipt(
                db_path=db_path, base_url=BASE, agent_id="@x",
                decision="APPROVED", decision_reason="typo", subject_id="s",
            )


class TestTrustSummary:
    @pytest.mark.asyncio
    async def test_empty_trail_scores_null_not_zero(self, db_path):
        """SCENARIO: A buyer agent evaluates a brand-new agent with no
                   transaction history before recommending it to its owner.
        GIVEN:    A receipts table containing no rows for that handle.
        WHEN:     The public trust summary is computed for the fresh handle.
        THEN:     receipts is 0 and score is null — unknown must never
                  masquerade as either perfect or terrible.
        """
        await _init(db_path)
        s = await trust_summary(db_path=db_path, agent_id="@fresh")
        assert s["receipts"] == 0
        assert s["score"] is None

    @pytest.mark.asyncio
    async def test_mixed_trail_aggregates_and_scores(self, db_path):
        """SCENARIO: A PSP risk analyst reviews an agent with a mixed
                   history before raising its spend threshold.
        GIVEN:    Two APPROVE receipts and one DECLINE for the same handle,
                  plus an unrelated receipt for a different handle.
        WHEN:     The trust summary is computed for the first handle only.
        THEN:     Counts are 2/1/0, score is 67, and the other handle's
                  history does not bleed into the numbers.
        """
        await _init(db_path)
        for decision in ("APPROVE", "APPROVE", "DECLINE"):
            await persist_receipt(
                db_path=db_path, base_url=BASE, agent_id="@mixed",
                decision=decision, decision_reason="t", subject_id="s",
            )
        await persist_receipt(
            db_path=db_path, base_url=BASE, agent_id="@other",
            decision="DECLINE", decision_reason="t", subject_id="s",
        )
        s = await trust_summary(db_path=db_path, agent_id="@mixed")
        assert (s["approve"], s["decline"], s["review"]) == (2, 1, 0)
        assert s["score"] == 67
        assert s["receipts"] == 3
        assert s["last_receipt_at"] is not None
