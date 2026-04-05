"""MCP API key authentication for DingDawg Agent 1.

Manages the ``mcp_api_keys`` table in SQLite and provides the
``validate_api_key`` coroutine used by every MCP tool before execution.

Key design decisions
--------------------
- Keys are stored as SHA-256 hashes — the plaintext key is never persisted.
- Each key is *scoped* to a specific agent_id (``None`` = global/admin key).
- ``last_used_at`` is updated on every successful validation for audit purposes.
- ``is_active`` allows instant revocation without deleting the row (preserves
  the audit trail).

Table schema (mcp_api_keys)
---------------------------
::

    id           TEXT PRIMARY KEY          — UUID
    user_id      TEXT NOT NULL             — owner of the key
    agent_id     TEXT                      — scoped agent (NULL = global)
    key_hash     TEXT NOT NULL UNIQUE      — SHA-256(raw_key)
    name         TEXT NOT NULL             — human label (e.g. "prod-key-1")
    created_at   TEXT NOT NULL             — ISO 8601 UTC
    last_used_at TEXT                      — ISO 8601 UTC, NULL until first use
    is_active    INTEGER NOT NULL DEFAULT 1

Usage
-----
::

    from isg_agent.mcp.auth import ensure_mcp_keys_table, validate_api_key

    # At startup — idempotent
    await ensure_mcp_keys_table(db_path)

    # In a tool handler
    key_info = await validate_api_key(raw_key, db_path=db_path)
    if key_info is None:
        raise PermissionError("Invalid or inactive API key")
    if key_info["agent_id"] and key_info["agent_id"] != requested_agent_id:
        raise PermissionError("Key not scoped for this agent")
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

__all__ = [
    "ensure_mcp_keys_table",
    "validate_api_key",
    "create_api_key",
    "revoke_api_key",
    "hash_key",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_MCP_KEYS_TABLE = """
CREATE TABLE IF NOT EXISTS mcp_api_keys (
    id           TEXT    PRIMARY KEY,
    user_id      TEXT    NOT NULL,
    agent_id     TEXT,
    key_hash     TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    last_used_at TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1
);
"""

_CREATE_MCP_KEYS_IDX_HASH = (
    "CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_hash "
    "ON mcp_api_keys(key_hash);"
)

_CREATE_MCP_KEYS_IDX_USER = (
    "CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_user "
    "ON mcp_api_keys(user_id);"
)

_CREATE_MCP_KEYS_IDX_AGENT = (
    "CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_agent "
    "ON mcp_api_keys(agent_id);"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key* (UTF-8 encoded).

    This is the value stored in the ``key_hash`` column — the plaintext key
    never touches the database.

    Parameters
    ----------
    raw_key:
        The raw API key string as provided by the caller.

    Returns
    -------
    str
        64-character lowercase SHA-256 hex digest.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Table lifecycle
# ---------------------------------------------------------------------------


async def ensure_mcp_keys_table(db_path: str) -> None:
    """Create the ``mcp_api_keys`` table and indexes if they do not exist.

    Safe to call on every application startup — all DDL statements use
    ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_MCP_KEYS_TABLE)
        await db.execute(_CREATE_MCP_KEYS_IDX_HASH)
        await db.execute(_CREATE_MCP_KEYS_IDX_USER)
        await db.execute(_CREATE_MCP_KEYS_IDX_AGENT)
        await db.commit()

    logger.debug("mcp_api_keys table ensured (db=%s)", db_path)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


async def validate_api_key(
    raw_key: str,
    *,
    db_path: str,
    agent_id: Optional[str] = None,
) -> Optional[dict]:
    """Validate an MCP API key and return its metadata if valid.

    Steps:
    1. Hash the raw key.
    2. Look up the hash in ``mcp_api_keys``.
    3. Confirm the key is active (``is_active = 1``).
    4. If ``agent_id`` is provided, confirm the key is scoped to that agent
       OR the key has no agent scope (global key).
    5. Update ``last_used_at`` on success.

    Parameters
    ----------
    raw_key:
        The plaintext API key from the request header / bearer token.
    db_path:
        Path to the SQLite database.
    agent_id:
        If supplied, the key must either be global (``agent_id IS NULL``)
        or explicitly scoped to this agent.

    Returns
    -------
    dict or None
        Key metadata dict with keys ``id``, ``user_id``, ``agent_id``,
        ``name``, ``created_at``, ``last_used_at`` on success.
        ``None`` if the key is not found, inactive, or out of scope.
    """
    if not raw_key:
        return None

    key_hash = hash_key(raw_key)
    now = _utc_now()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT id, user_id, agent_id, name, created_at, last_used_at, is_active "
            "FROM mcp_api_keys WHERE key_hash = ?",
            (key_hash,),
        )
        row = await cursor.fetchone()

        if row is None:
            logger.warning("validate_api_key: key hash not found")
            return None

        if not row["is_active"]:
            logger.warning("validate_api_key: key %s is inactive", row["id"])
            return None

        # Scope check: key may be global (agent_id IS NULL) or explicitly
        # scoped to the requested agent.
        stored_agent_id = row["agent_id"]
        if agent_id is not None and stored_agent_id is not None:
            if stored_agent_id != agent_id:
                logger.warning(
                    "validate_api_key: key %s scoped to agent %s, "
                    "but requested agent is %s",
                    row["id"],
                    stored_agent_id,
                    agent_id,
                )
                return None

        # Update last_used_at (fire-and-forget style; non-critical)
        try:
            await db.execute(
                "UPDATE mcp_api_keys SET last_used_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            await db.commit()
        except Exception as _exc:  # noqa: BLE001
            logger.warning(
                "validate_api_key: failed to update last_used_at: %s", _exc
            )

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "agent_id": row["agent_id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "last_used_at": now,
        }


async def create_api_key(
    raw_key: str,
    user_id: str,
    name: str,
    *,
    db_path: str,
    agent_id: Optional[str] = None,
) -> dict:
    """Insert a new MCP API key record (stores hash only).

    Parameters
    ----------
    raw_key:
        The plaintext API key to register.  Only its SHA-256 hash is stored.
    user_id:
        Owner of the key.
    name:
        Human-readable label (e.g. ``"prod-key-1"``).
    db_path:
        Path to the SQLite database.
    agent_id:
        Scope the key to a specific agent.  ``None`` = global/admin key.

    Returns
    -------
    dict
        New key metadata (``id``, ``user_id``, ``agent_id``, ``name``,
        ``created_at``).

    Raises
    ------
    ValueError
        If the key hash already exists (duplicate key).
    """
    key_id = str(uuid.uuid4())
    key_hash = hash_key(raw_key)
    now = _utc_now()

    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO mcp_api_keys "
                "(id, user_id, agent_id, key_hash, name, created_at, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (key_id, user_id, agent_id, key_hash, name, now),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise ValueError("API key already exists (duplicate hash)") from exc

    logger.info(
        "create_api_key: id=%s user=%s agent=%s name=%r",
        key_id,
        user_id,
        agent_id,
        name,
    )

    return {
        "id": key_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "name": name,
        "created_at": now,
    }


async def revoke_api_key(
    key_id: str,
    *,
    db_path: str,
) -> bool:
    """Deactivate an MCP API key by ID (sets ``is_active = 0``).

    The row is kept for the audit trail — it is never hard-deleted.

    Parameters
    ----------
    key_id:
        UUID of the key to revoke.
    db_path:
        Path to the SQLite database.

    Returns
    -------
    bool
        ``True`` if a row was updated, ``False`` if not found.
    """
    now = _utc_now()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE mcp_api_keys SET is_active = 0, last_used_at = ? WHERE id = ?",
            (now, key_id),
        )
        await db.commit()
        updated = (cursor.rowcount or 0) > 0

    if updated:
        logger.info("revoke_api_key: key %s deactivated", key_id)
    else:
        logger.warning("revoke_api_key: key %s not found", key_id)

    return updated
