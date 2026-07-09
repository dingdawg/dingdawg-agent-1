"""ATR v1.0 receipt persistence — the single writer (Wave 3).

Extracted from the public POST /receipt handler so the ACP checkout flow
and any future emitter share ONE implementation. Two callers, one writer:
dual writers drift, and a drifted receipt trail is worse than none.

Error surface: raises ValueError on invalid decision (callers validate at
their own boundary; this is the last line of defense) and propagates
sqlite errors — the PUBLIC route translates to 5xx, while the CHECKOUT
hook catches and logs (a receipt failure must never fail a payment).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

VALID_DECISIONS = ("APPROVE", "DECLINE", "REVIEW")


async def persist_receipt(
    *,
    db_path: str,
    base_url: str,
    agent_id: str,
    decision: str,
    decision_reason: str,
    subject_id: str,
    policy_version: Optional[str] = None,
    confidence_score: Optional[int] = None,
    parent_receipt_id: Optional[str] = None,
) -> dict[str, Any]:
    """Insert one ATR receipt row and return the full receipt document."""
    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}")

    receipt_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verification_endpoint = f"{base_url}/api/v1/public/receipt/{receipt_id}"

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO atr_receipts
            (receipt_id, agent_id, decision, decision_reason,
             timestamp, subject_id, policy_version, confidence_score,
             parent_receipt_id, verification_endpoint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (receipt_id, agent_id, decision, decision_reason, timestamp,
             subject_id, policy_version, confidence_score,
             parent_receipt_id, verification_endpoint),
        )
        await db.commit()

    return {
        "receipt_id": receipt_id,
        "agent_id": agent_id,
        "decision": decision,
        "decision_reason": decision_reason,
        "timestamp": timestamp,
        "subject_id": subject_id,
        "policy_version": policy_version,
        "confidence_score": confidence_score,
        "parent_receipt_id": parent_receipt_id,
        "verification_endpoint": verification_endpoint,
    }


async def trust_summary(*, db_path: str, agent_id: str) -> dict[str, Any]:
    """Aggregate an agent's receipt trail into a public, PII-free summary.

    score is APPROVE share (0-100) and is ``None`` when no receipts exist —
    an absent trail must read as "unknown", never as 0 or 100.
    """
    counts = {"APPROVE": 0, "DECLINE": 0, "REVIEW": 0}
    last: Optional[str] = None
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT decision, COUNT(*), MAX(timestamp) FROM atr_receipts "
            "WHERE agent_id = ? GROUP BY decision",
            (agent_id,),
        ) as cur:
            async for decision, n, ts in cur:
                if decision in counts:
                    counts[decision] = n
                if ts and (last is None or ts > last):
                    last = ts

    total = sum(counts.values())
    return {
        "agent_id": agent_id,
        "receipts": total,
        "approve": counts["APPROVE"],
        "decline": counts["DECLINE"],
        "review": counts["REVIEW"],
        "score": round(100 * counts["APPROVE"] / total) if total else None,
        "last_receipt_at": last,
    }
