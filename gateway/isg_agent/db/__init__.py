"""Database module: SQLite WAL engine, schema management, and query helpers.

Public API
----------
Engine:
    ``Database``        — async SQLite engine with WAL mode and serialised writes
    ``init_db``         — initialise the module-level database singleton
    ``get_db``          — return the singleton (for FastAPI ``Depends()``)
    ``close_db``        — shutdown the singleton

Schema:
    ``create_tables``   — idempotent schema creation
    ``SCHEMA_VERSION``  — current schema version string

Queries:
    All named query functions from ``isg_agent.db.queries``.
"""

from isg_agent.db.engine import Database, close_db, get_db, init_db
from isg_agent.db.queries import (
    cancel_lock,
    create_session,
    execute_lock,
    get_audit_chain,
    get_checks_for_rule,
    get_convergence_log,
    get_pending_locks,
    get_session,
    get_session_messages,
    get_skill,
    get_trust_history,
    get_trust_score,
    insert_audit_entry,
    insert_constitution_check,
    insert_convergence_entry,
    insert_memory_entry,
    insert_message,
    insert_skill,
    insert_time_lock,
    insert_token,
    insert_trust_entry,
    list_sessions,
    list_skills,
    revoke_token,
    search_memory_fts,
    update_session,
    update_skill_reputation,
    verify_chain_integrity,
    verify_token,
)
from isg_agent.db.schema import SCHEMA_VERSION, create_tables

__all__ = [
    # Engine
    "Database",
    "init_db",
    "get_db",
    "close_db",
    # Schema
    "create_tables",
    "SCHEMA_VERSION",
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
