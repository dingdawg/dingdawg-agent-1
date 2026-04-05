"""Seed all DingDawg-owned @handles into the agent_handles table.

This script pre-reserves every handle that DingDawg operates as the company so
that no end-user can claim them through the normal registration flow.

The reserved-handles validation layer (HandleService.validate_handle) already
BLOCKS these handles from being claimed by users.  This script goes one step
further by inserting rows into the ``agent_handles`` table with a synthetic
``dingdawg-system`` owner, making the unavailability explicit in the database
as well.

Usage (from the gateway/ root directory)
-----------------------------------------
    python -m isg_agent.scripts.seed_reserved_handles

    # Override database path:
    ISG_AGENT_DB_PATH=data/agent.db python -m isg_agent.scripts.seed_reserved_handles

    # Dry-run (shows what would be reserved without writing):
    python -m isg_agent.scripts.seed_reserved_handles --dry-run

    # Force re-seed (re-inserts any released rows):
    python -m isg_agent.scripts.seed_reserved_handles --force

Idempotency
-----------
Handles that already exist in the database with status 'active' are silently
skipped.  The script prints a summary table at the end.

Scope
-----
Only DINGDAWG_OWNED_HANDLES (the @dingdawg-* ones) are written to the database.
The wider RESERVED_HANDLES set is enforced at the validation layer and does not
need database rows to be effective.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("seed_reserved_handles")

# ---------------------------------------------------------------------------
# Synthetic owner for all company-owned handles
# ---------------------------------------------------------------------------

_SYSTEM_OWNER_ID = "dingdawg-system"

# ---------------------------------------------------------------------------
# Handles DingDawg owns as a company.
# These are inserted into the database so they appear unavailable even before
# the validation layer is consulted.
# Every entry here MUST also be present in RESERVED_HANDLES.
# ---------------------------------------------------------------------------

DINGDAWG_OWNED_HANDLES: list[str] = [
    # Root brand
    "dingdawg",
    # Functional
    "dingdawg-ai",
    "dingdawg-pro",
    "dingdawg-enterprise",
    "dingdawg-business",
    "dingdawg-team",
    "dingdawg-dev",
    "dingdawg-labs",
    "dingdawg-beta",
    "dingdawg-alpha",
    "dingdawg-official",
    "dingdawg-help",
    "dingdawg-support",
    "dingdawg-sales",
    "dingdawg-billing",
    "dingdawg-legal",
    "dingdawg-hr",
    "dingdawg-ops",
    "dingdawg-security",
    "dingdawg-admin",
    "dingdawg-bot",
    "dingdawg-agent",
    "dingdawg-api",
    "dingdawg-app",
    "dingdawg-web",
    "dingdawg-mobile",
    "dingdawg-cloud",
    "dingdawg-data",
    "dingdawg-health",
    "dingdawg-gaming",
    "dingdawg-community",
    "dingdawg-partner",
    "dingdawg-affiliate",
    "dingdawg-ambassador",
    "dingdawg-vip",
    "dingdawg-premium",
    "dingdawg-plus",
    "dingdawg-starter",
    "dingdawg-basic",
    "dingdawg-free",
    "dingdawg-demo",
    "dingdawg-test",
    "dingdawg-staging",
    "dingdawg-internal",
    "dingdawg-status",
    "dingdawg-news",
    "dingdawg-blog",
    "dingdawg-docs",
    "dingdawg-sdk",
    "dingdawg-cli",
    "dingdawg-mcp",
    "dingdawg-store",
    "dingdawg-pay",
    "dingdawg-checkout",
    "dingdawg-notify",
    "dingdawg-alerts",
    "dingdawg-insights",
    "dingdawg-analytics",
    "dingdawg-reports",
    "dingdawg-platform",
    "dingdawg-core",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_db_path() -> str:
    for env_var in ("ISG_AGENT_DB_PATH", "DINGDAWG_DB_PATH", "DB_PATH"):
        val = os.environ.get(env_var, "").strip()
        if val:
            log.info("Database path from env (%s): %s", env_var, val)
            return val
    default = str(Path.cwd() / "data" / "agent.db")
    log.info("Using default database path: %s", default)
    return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Core seeding logic
# ---------------------------------------------------------------------------

async def seed(db_path: str, *, dry_run: bool, force: bool) -> None:
    """Reserve all DINGDAWG_OWNED_HANDLES in the database.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database.
    dry_run:
        If True, print what would be done but make no writes.
    force:
        If True, update any 'released' rows back to 'active'.
    """
    # Validate that DINGDAWG_OWNED_HANDLES is a subset of RESERVED_HANDLES
    # This is a defensive integrity check, not a silent swallow.
    from isg_agent.agents.reserved_handles import RESERVED_HANDLES
    not_in_reserved = [h for h in DINGDAWG_OWNED_HANDLES if h not in RESERVED_HANDLES]
    if not_in_reserved:
        log.error(
            "INTEGRITY ERROR: The following handles are in DINGDAWG_OWNED_HANDLES "
            "but NOT in RESERVED_HANDLES — fix reserved_handles.py before seeding: %s",
            not_in_reserved,
        )
        sys.exit(1)

    if dry_run:
        log.info("[DRY-RUN] Would reserve %d handles as owner=%s",
                 len(DINGDAWG_OWNED_HANDLES), _SYSTEM_OWNER_ID)
        for h in DINGDAWG_OWNED_HANDLES:
            print(f"  would reserve: @{h}")
        return

    import aiosqlite

    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    reserved_count = 0
    skipped_count = 0
    updated_count = 0
    error_count = 0

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        # Ensure the table exists (mirrors handle_service._ensure_initialized)
        await db.execute(
            "CREATE TABLE IF NOT EXISTS agent_handles ("
            "handle TEXT PRIMARY KEY, "
            "agent_id TEXT, "
            "claimed_at TEXT, "
            "reserved_at TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'active' "
            "CHECK(status IN ('active', 'released', 'suspended')))"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_handles_agent "
            "ON agent_handles(agent_id)"
        )
        await db.commit()

        now = _now_iso()

        for handle in DINGDAWG_OWNED_HANDLES:
            try:
                cursor = await db.execute(
                    "SELECT status FROM agent_handles WHERE handle = ?", (handle,)
                )
                existing = await cursor.fetchone()

                if existing is None:
                    await db.execute(
                        "INSERT INTO agent_handles "
                        "(handle, agent_id, claimed_at, reserved_at, status) "
                        "VALUES (?, ?, ?, ?, 'active')",
                        (handle, _SYSTEM_OWNER_ID, now, now),
                    )
                    reserved_count += 1
                    log.debug("Reserved @%s", handle)
                elif existing[0] == "released" and force:
                    await db.execute(
                        "UPDATE agent_handles "
                        "SET status = 'active', agent_id = ?, claimed_at = ?, reserved_at = ? "
                        "WHERE handle = ?",
                        (_SYSTEM_OWNER_ID, now, now, handle),
                    )
                    updated_count += 1
                    log.debug("Re-activated @%s", handle)
                else:
                    skipped_count += 1
                    log.debug("Skipped @%s (already %s)", handle, existing[0])

            except Exception as exc:
                error_count += 1
                log.error(
                    "Failed to reserve @%s: %s: %s",
                    handle, type(exc).__name__, exc,
                )

        await db.commit()

    # Summary
    total = len(DINGDAWG_OWNED_HANDLES)
    log.info("=" * 60)
    log.info("seed_reserved_handles complete")
    log.info("  Total handles : %d", total)
    log.info("  Reserved (new): %d", reserved_count)
    log.info("  Re-activated  : %d", updated_count)
    log.info("  Skipped       : %d", skipped_count)
    log.info("  Errors        : %d", error_count)
    log.info("  Database      : %s", db_path)
    log.info("=" * 60)

    if error_count > 0:
        log.error("%d handle(s) failed to reserve — check logs above", error_count)
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-reserve all DingDawg-owned @handles in the database."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be reserved without writing to the database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-activate any 'released' handles back to 'active'.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="",
        help=(
            "Override the database path. "
            "Defaults to ISG_AGENT_DB_PATH env var or data/agent.db."
        ),
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    db_path = args.db_path.strip() if args.db_path else _resolve_db_path()
    log.info("Starting seed_reserved_handles (dry_run=%s, force=%s)",
             args.dry_run, args.force)
    await seed(db_path, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    asyncio.run(main())
