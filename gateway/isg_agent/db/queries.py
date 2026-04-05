"""Named query functions (no raw SQL in route handlers).

Provides parameterized query functions for all database operations. Route
handlers call these functions instead of constructing SQL directly. Every
query uses ``?`` placeholders — never string interpolation.

All functions take an ``aiosqlite.Connection`` as their first parameter so
they can participate in the caller's transaction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

__all__ = [
    # Audit
    "insert_audit_entry",
    "get_audit_chain",
    "verify_chain_integrity",
    # Sessions
    "create_session",
    "get_session",
    "update_session",
    "list_sessions",
    # Messages
    "insert_message",
    "get_session_messages",
    # Trust
    "insert_trust_entry",
    "get_trust_score",
    "get_trust_history",
    # Time Lock
    "insert_time_lock",
    "get_pending_locks",
    "cancel_lock",
    "execute_lock",
    # Constitution
    "insert_constitution_check",
    "get_checks_for_rule",
    # Skills
    "insert_skill",
    "get_skill",
    "update_skill_reputation",
    "list_skills",
    # Auth
    "insert_token",
    "verify_token",
    "revoke_token",
    # Memory
    "insert_memory_entry",
    "search_memory_fts",
    # Convergence
    "insert_convergence_entry",
    "get_convergence_log",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an aiosqlite.Row to a plain dictionary."""
    return dict(row)


def _compute_audit_hash(
    entry_id: int,
    timestamp: str,
    event_type: str,
    actor: str,
    details: str,
    prev_hash: str,
) -> str:
    """Compute SHA-256 hash for an audit entry."""
    payload = f"{entry_id}|{timestamp}|{event_type}|{actor}|{details}|{prev_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Audit Chain
# ---------------------------------------------------------------------------

async def insert_audit_entry(
    db: aiosqlite.Connection,
    *,
    event_type: str,
    actor: str,
    action: str = "",
    details: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Append a new entry to the audit hash chain.

    Automatically computes the hash linking this entry to the previous one.

    Returns the newly created entry as a dictionary.
    """
    details_str = json.dumps(details or {}, separators=(",", ":"), sort_keys=True)
    ts = _now_iso()

    # Fetch the hash of the latest entry
    cursor = await db.execute(
        "SELECT id, entry_hash FROM audit_chain ORDER BY id DESC LIMIT 1"
    )
    last_row = await cursor.fetchone()

    if last_row is not None:
        prev_hash: str = last_row["entry_hash"]
        next_id: int = last_row["id"] + 1
    else:
        # Genesis case
        prev_hash = hashlib.sha256(b"GENESIS").hexdigest()
        next_id = 1

    entry_hash = _compute_audit_hash(
        entry_id=next_id,
        timestamp=ts,
        event_type=event_type,
        actor=actor,
        details=details_str,
        prev_hash=prev_hash,
    )

    await db.execute(
        """
        INSERT INTO audit_chain
            (timestamp, event_type, actor, action, details, entry_hash, prev_hash, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ts, event_type, actor, action, details_str, entry_hash, prev_hash, session_id),
    )

    return {
        "id": next_id,
        "timestamp": ts,
        "event_type": event_type,
        "actor": actor,
        "action": action,
        "details": details_str,
        "entry_hash": entry_hash,
        "prev_hash": prev_hash,
        "session_id": session_id,
    }


async def get_audit_chain(
    db: aiosqlite.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve audit entries with optional filtering and pagination.

    Returns entries ordered by ``id`` ascending.
    """
    if event_type is not None:
        cursor = await db.execute(
            """
            SELECT id, timestamp, event_type, actor, action, details,
                   entry_hash, prev_hash, session_id
            FROM audit_chain
            WHERE event_type = ?
            ORDER BY id ASC
            LIMIT ? OFFSET ?
            """,
            (event_type, limit, offset),
        )
    else:
        cursor = await db.execute(
            """
            SELECT id, timestamp, event_type, actor, action, details,
                   entry_hash, prev_hash, session_id
            FROM audit_chain
            ORDER BY id ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def verify_chain_integrity(db: aiosqlite.Connection) -> bool:
    """Verify the integrity of the entire audit hash chain.

    Recomputes every entry hash and checks that each ``prev_hash`` matches
    the preceding entry's ``entry_hash``.

    Returns ``True`` if the chain is intact, ``False`` if any entry has
    been tampered with.
    """
    cursor = await db.execute(
        """
        SELECT id, timestamp, event_type, actor, details, entry_hash, prev_hash
        FROM audit_chain
        ORDER BY id ASC
        """
    )
    rows = await cursor.fetchall()

    if not rows:
        return True  # Empty chain is trivially valid

    # Verify first entry
    first = rows[0]
    expected = _compute_audit_hash(
        entry_id=first["id"],
        timestamp=first["timestamp"],
        event_type=first["event_type"],
        actor=first["actor"],
        details=first["details"],
        prev_hash=first["prev_hash"],
    )
    if expected != first["entry_hash"]:
        return False

    # Walk the rest of the chain
    prev_entry_hash = first["entry_hash"]
    for row in rows[1:]:
        if row["prev_hash"] != prev_entry_hash:
            return False

        recomputed = _compute_audit_hash(
            entry_id=row["id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            actor=row["actor"],
            details=row["details"],
            prev_hash=row["prev_hash"],
        )
        if recomputed != row["entry_hash"]:
            return False

        prev_entry_hash = row["entry_hash"]

    return True


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

async def create_session(
    db: aiosqlite.Connection,
    *,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new session and return it as a dictionary."""
    sid = session_id or str(uuid.uuid4())
    now = _now_iso()
    meta_str = json.dumps(metadata or {}, separators=(",", ":"))

    await db.execute(
        """
        INSERT INTO sessions (id, created_at, updated_at, status, metadata)
        VALUES (?, ?, ?, 'active', ?)
        """,
        (sid, now, now, meta_str),
    )

    return {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "metadata": meta_str,
    }


async def get_session(
    db: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Retrieve a session by its ID. Returns ``None`` if not found."""
    cursor = await db.execute(
        "SELECT id, created_at, updated_at, status, metadata FROM sessions WHERE id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


async def update_session(
    db: aiosqlite.Connection,
    session_id: str,
    *,
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Update a session's status and/or metadata.

    Returns ``True`` if the session was found and updated.
    """
    now = _now_iso()
    parts: list[str] = ["updated_at = ?"]
    params: list[Any] = [now]

    if status is not None:
        parts.append("status = ?")
        params.append(status)

    if metadata is not None:
        parts.append("metadata = ?")
        params.append(json.dumps(metadata, separators=(",", ":")))

    params.append(session_id)
    set_clause = ", ".join(parts)

    cursor = await db.execute(
        f"UPDATE sessions SET {set_clause} WHERE id = ?",  # noqa: S608
        params,
    )
    return cursor.rowcount > 0


async def list_sessions(
    db: aiosqlite.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List sessions with optional status filtering."""
    if status is not None:
        cursor = await db.execute(
            """
            SELECT id, created_at, updated_at, status, metadata
            FROM sessions
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (status, limit, offset),
        )
    else:
        cursor = await db.execute(
            """
            SELECT id, created_at, updated_at, status, metadata
            FROM sessions
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def insert_message(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a message into a session. Returns the new message dict."""
    ts = _now_iso()
    meta_str = json.dumps(metadata or {}, separators=(",", ":"))

    cursor = await db.execute(
        """
        INSERT INTO messages (session_id, role, content, timestamp, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, role, content, ts, meta_str),
    )

    return {
        "id": cursor.lastrowid,
        "session_id": session_id,
        "role": role,
        "content": content,
        "timestamp": ts,
        "metadata": meta_str,
    }


async def get_session_messages(
    db: aiosqlite.Connection,
    session_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Retrieve messages for a session in chronological order."""
    cursor = await db.execute(
        """
        SELECT id, session_id, role, content, timestamp, metadata
        FROM messages
        WHERE session_id = ?
        ORDER BY id ASC
        LIMIT ? OFFSET ?
        """,
        (session_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Trust Ledger
# ---------------------------------------------------------------------------

async def insert_trust_entry(
    db: aiosqlite.Connection,
    *,
    action_type: str,
    score_delta: float,
    audit_chain_entry_id: int | None = None,
) -> dict[str, Any]:
    """Record a trust event and compute the new running total.

    Reads the current running total from the latest entry and adds
    ``score_delta`` to produce the new total.
    """
    ts = _now_iso()

    # Get the current running total
    cursor = await db.execute(
        "SELECT running_total FROM trust_ledger ORDER BY id DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    current_total: float = row["running_total"] if row else 50.0  # default initial score
    new_total = current_total + score_delta

    await db.execute(
        """
        INSERT INTO trust_ledger
            (timestamp, action_type, score_delta, running_total, audit_chain_entry_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ts, action_type, score_delta, new_total, audit_chain_entry_id),
    )

    return {
        "timestamp": ts,
        "action_type": action_type,
        "score_delta": score_delta,
        "running_total": new_total,
        "audit_chain_entry_id": audit_chain_entry_id,
    }


async def get_trust_score(db: aiosqlite.Connection) -> float:
    """Return the current trust score (latest running_total).

    Returns the default initial score (50.0) if no entries exist.
    """
    cursor = await db.execute(
        "SELECT running_total FROM trust_ledger ORDER BY id DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if row is None:
        return 50.0
    return float(row["running_total"])


async def get_trust_history(
    db: aiosqlite.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Retrieve trust ledger entries in reverse chronological order."""
    cursor = await db.execute(
        """
        SELECT id, timestamp, action_type, score_delta, running_total, audit_chain_entry_id
        FROM trust_ledger
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Time Lock
# ---------------------------------------------------------------------------

async def insert_time_lock(
    db: aiosqlite.Connection,
    *,
    lock_id: str,
    action_description: str,
    risk_tier: str,
    execute_at: str,
    cancellable_until: str,
    created_at: str | None = None,
    callback_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new time-locked action entry."""
    ts = created_at or _now_iso()
    cb_str = json.dumps(callback_data) if callback_data else None

    await db.execute(
        """
        INSERT INTO time_lock_queue
            (id, action_description, risk_tier, execute_at, status,
             cancellable_until, created_at, callback_data)
        VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (lock_id, action_description, risk_tier, execute_at, cancellable_until, ts, cb_str),
    )

    return {
        "id": lock_id,
        "action_description": action_description,
        "risk_tier": risk_tier,
        "execute_at": execute_at,
        "status": "pending",
        "cancellable_until": cancellable_until,
        "created_at": ts,
        "callback_data": callback_data,
    }


async def get_pending_locks(
    db: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Return all pending time-lock entries ordered by execution time."""
    cursor = await db.execute(
        """
        SELECT id, action_description, risk_tier, execute_at, status,
               cancellable_until, created_at, callback_data
        FROM time_lock_queue
        WHERE status = 'pending'
        ORDER BY execute_at ASC
        """
    )
    rows = await cursor.fetchall()
    result: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        # Parse callback_data JSON if present
        if d.get("callback_data"):
            d["callback_data"] = json.loads(d["callback_data"])
        return_val = d
        result.append(return_val)
    return result


async def cancel_lock(
    db: aiosqlite.Connection,
    lock_id: str,
) -> bool:
    """Cancel a pending time-lock entry. Returns ``True`` if successful."""
    cursor = await db.execute(
        "UPDATE time_lock_queue SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
        (lock_id,),
    )
    return cursor.rowcount > 0


async def execute_lock(
    db: aiosqlite.Connection,
    lock_id: str,
) -> bool:
    """Mark a time-lock entry as executed. Returns ``True`` if successful."""
    cursor = await db.execute(
        "UPDATE time_lock_queue SET status = 'executed' WHERE id = ? AND status = 'pending'",
        (lock_id,),
    )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Constitution Checks
# ---------------------------------------------------------------------------

async def insert_constitution_check(
    db: aiosqlite.Connection,
    *,
    rule_id: str,
    action: str,
    decision: str,
    reason: str = "",
    audit_chain_entry_id: int | None = None,
) -> dict[str, Any]:
    """Record a constitution check result."""
    ts = _now_iso()

    await db.execute(
        """
        INSERT INTO constitution_checks
            (timestamp, rule_id, action, decision, reason, audit_chain_entry_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ts, rule_id, action, decision, reason, audit_chain_entry_id),
    )

    return {
        "timestamp": ts,
        "rule_id": rule_id,
        "action": action,
        "decision": decision,
        "reason": reason,
        "audit_chain_entry_id": audit_chain_entry_id,
    }


async def get_checks_for_rule(
    db: aiosqlite.Connection,
    rule_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Retrieve constitution check entries for a specific rule."""
    cursor = await db.execute(
        """
        SELECT id, timestamp, rule_id, action, decision, reason, audit_chain_entry_id
        FROM constitution_checks
        WHERE rule_id = ?
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (rule_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

async def insert_skill(
    db: aiosqlite.Connection,
    *,
    skill_id: str | None = None,
    name: str,
    version: str = "0.1.0",
    manifest: dict[str, Any] | None = None,
    status: str = "quarantined",
    reputation_score: float = 0.0,
) -> dict[str, Any]:
    """Register a new skill. Returns the skill dict."""
    sid = skill_id or str(uuid.uuid4())
    now = _now_iso()
    manifest_str = json.dumps(manifest or {}, separators=(",", ":"))

    await db.execute(
        """
        INSERT INTO skills
            (id, name, version, manifest, status, reputation_score, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (sid, name, version, manifest_str, status, reputation_score, now, now),
    )

    return {
        "id": sid,
        "name": name,
        "version": version,
        "manifest": manifest_str,
        "status": status,
        "reputation_score": reputation_score,
        "created_at": now,
        "updated_at": now,
    }


async def get_skill(
    db: aiosqlite.Connection,
    skill_id: str,
) -> dict[str, Any] | None:
    """Retrieve a skill by its ID. Returns ``None`` if not found."""
    cursor = await db.execute(
        """
        SELECT id, name, version, manifest, status, reputation_score, created_at, updated_at
        FROM skills
        WHERE id = ?
        """,
        (skill_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


async def update_skill_reputation(
    db: aiosqlite.Connection,
    skill_id: str,
    reputation_delta: float,
) -> float | None:
    """Update a skill's reputation score by a delta value.

    Returns the new reputation score, or ``None`` if the skill was not found.
    """
    now = _now_iso()

    # Get current reputation
    cursor = await db.execute(
        "SELECT reputation_score FROM skills WHERE id = ?",
        (skill_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    new_score = float(row["reputation_score"]) + reputation_delta

    await db.execute(
        "UPDATE skills SET reputation_score = ?, updated_at = ? WHERE id = ?",
        (new_score, now, skill_id),
    )

    return new_score


async def list_skills(
    db: aiosqlite.Connection,
    *,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List skills with optional status filtering."""
    if status is not None:
        cursor = await db.execute(
            """
            SELECT id, name, version, manifest, status, reputation_score, created_at, updated_at
            FROM skills
            WHERE status = ?
            ORDER BY name ASC
            LIMIT ? OFFSET ?
            """,
            (status, limit, offset),
        )
    else:
        cursor = await db.execute(
            """
            SELECT id, name, version, manifest, status, reputation_score, created_at, updated_at
            FROM skills
            ORDER BY name ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Auth Tokens
# ---------------------------------------------------------------------------

async def insert_token(
    db: aiosqlite.Connection,
    *,
    token_hash: str,
    tier: str = "USER",
    user_id: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Insert a new auth token. Returns the token entry dict."""
    now = _now_iso()

    cursor = await db.execute(
        """
        INSERT INTO auth_tokens (token_hash, tier, user_id, created_at, expires_at, revoked)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (token_hash, tier, user_id, now, expires_at),
    )

    return {
        "id": cursor.lastrowid,
        "token_hash": token_hash,
        "tier": tier,
        "user_id": user_id,
        "created_at": now,
        "expires_at": expires_at,
        "revoked": 0,
    }


async def verify_token(
    db: aiosqlite.Connection,
    token_hash: str,
) -> dict[str, Any] | None:
    """Verify a token by its hash.

    Returns the token entry if valid (not revoked and not expired),
    or ``None`` otherwise.
    """
    now = _now_iso()

    cursor = await db.execute(
        """
        SELECT id, token_hash, tier, user_id, created_at, expires_at, revoked
        FROM auth_tokens
        WHERE token_hash = ?
          AND revoked = 0
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (token_hash, now),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


async def revoke_token(
    db: aiosqlite.Connection,
    token_hash: str,
) -> bool:
    """Revoke a token by its hash. Returns ``True`` if a token was revoked."""
    cursor = await db.execute(
        "UPDATE auth_tokens SET revoked = 1 WHERE token_hash = ? AND revoked = 0",
        (token_hash,),
    )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Memory Entries
# ---------------------------------------------------------------------------

async def insert_memory_entry(
    db: aiosqlite.Connection,
    *,
    content: str,
    embedding_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new memory entry and update the FTS index."""
    now = _now_iso()
    meta_str = json.dumps(metadata or {}, separators=(",", ":"))

    cursor = await db.execute(
        """
        INSERT INTO memory_entries (content, embedding_hash, created_at, metadata)
        VALUES (?, ?, ?, ?)
        """,
        (content, embedding_hash, now, meta_str),
    )
    entry_id = cursor.lastrowid

    # Update FTS index
    await db.execute(
        "INSERT INTO memory_fts (rowid, content) VALUES (?, ?)",
        (entry_id, content),
    )

    return {
        "id": entry_id,
        "content": content,
        "embedding_hash": embedding_hash,
        "created_at": now,
        "metadata": meta_str,
    }


async def search_memory_fts(
    db: aiosqlite.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search memory entries using FTS5 keyword matching.

    Parameters
    ----------
    query:
        FTS5 query string (supports boolean operators like AND, OR, NOT).
    limit:
        Maximum number of results to return.
    """
    cursor = await db.execute(
        """
        SELECT me.id, me.content, me.embedding_hash, me.created_at, me.metadata,
               rank
        FROM memory_fts
        JOIN memory_entries me ON memory_fts.rowid = me.id
        WHERE memory_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Convergence Log
# ---------------------------------------------------------------------------

async def insert_convergence_entry(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    iteration: int,
    tokens_used: int = 0,
    budget_remaining: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a convergence log entry for a session iteration."""
    ts = _now_iso()
    budget_str = json.dumps(budget_remaining or {}, separators=(",", ":"))

    await db.execute(
        """
        INSERT INTO convergence_log
            (session_id, iteration, tokens_used, budget_remaining, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, iteration, tokens_used, budget_str, ts),
    )

    return {
        "session_id": session_id,
        "iteration": iteration,
        "tokens_used": tokens_used,
        "budget_remaining": budget_str,
        "timestamp": ts,
    }


async def get_convergence_log(
    db: aiosqlite.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """Retrieve all convergence log entries for a session."""
    cursor = await db.execute(
        """
        SELECT id, session_id, iteration, tokens_used, budget_remaining, timestamp
        FROM convergence_log
        WHERE session_id = ?
        ORDER BY iteration ASC
        """,
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]
