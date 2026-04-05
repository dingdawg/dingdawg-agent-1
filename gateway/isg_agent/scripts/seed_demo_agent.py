"""Seed the Mario's Italian Kitchen demo agent into the live database.

Usage (from gateway/ root directory):

    python -m isg_agent.scripts.seed_demo_agent

    # Override the database path:
    ISG_AGENT_DB_PATH=data/agent.db python -m isg_agent.scripts.seed_demo_agent

    # Dry-run (prints what would be inserted without writing to DB):
    python -m isg_agent.scripts.seed_demo_agent --dry-run

    # Force re-seed even if agent already exists:
    python -m isg_agent.scripts.seed_demo_agent --force

This script is fully idempotent: if @marios-italian already exists in the
database it exits immediately with a success message, unless --force is passed.

What it creates:
  1. An ``agent_templates`` row for the "Italian Restaurant Demo" template,
     with the full system prompt as ``system_prompt_template``.
  2. An ``agents`` row for @marios-italian, linked to that template via
     ``template_id``.  The ``config_json`` carries the knowledge base (menu,
     hours, location, FAQs) and conversation flow strings so the runtime
     can use them directly.
  3. An ``agent_handles`` row reserving the @marios-italian handle.

The demo agent is owned by a synthetic ``demo-system`` user so it never
conflicts with real user accounts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("seed_demo_agent")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Directory containing this script
_SCRIPTS_DIR = Path(__file__).parent

# Root of the isg_agent package
_PKG_DIR = _SCRIPTS_DIR.parent

# JSON template source
_TEMPLATE_JSON = (
    _PKG_DIR / "templates" / "demo_agents" / "marios_italian.json"
)

# Synthetic owner — never a real user, never shows up in user-facing APIs
_DEMO_OWNER_ID = "demo-system"

# Handle (without @)
_HANDLE = "@marios-italian"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_template_json() -> dict:
    """Load and parse the marios_italian.json definition file."""
    if not _TEMPLATE_JSON.exists():
        log.error("Template JSON not found: %s", _TEMPLATE_JSON)
        sys.exit(1)

    with open(_TEMPLATE_JSON, encoding="utf-8") as fh:
        data = json.load(fh)

    log.info("Loaded template JSON from %s", _TEMPLATE_JSON)
    return data


def _resolve_db_path() -> str:
    """Return the database path from env or default."""
    # Check ISG_AGENT_DB_PATH first, then ISG_AGENT_DB_PATH variant, then default
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

async def seed(db_path: str, tpl: dict, *, dry_run: bool, force: bool) -> None:
    """Insert the demo agent and its template into the database.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database.
    tpl:
        Parsed content of ``marios_italian.json``.
    dry_run:
        If True, print what would be done but make no writes.
    force:
        If True, delete existing @marios-italian rows before re-inserting.
    """
    import aiosqlite

    if dry_run:
        log.info("[DRY-RUN] Would seed @marios-italian to %s", db_path)
        _print_summary(tpl)
        return

    # Ensure DB directory exists
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA journal_mode=WAL")

        # ------------------------------------------------------------------
        # Check if @marios-italian already exists
        # ------------------------------------------------------------------
        cursor = await db.execute(
            "SELECT id FROM agents WHERE handle = ?", (_HANDLE,)
        )
        existing = await cursor.fetchone()

        if existing is not None and not force:
            log.info(
                "Agent %s already exists (id=%s). Use --force to re-seed.",
                _HANDLE, existing["id"],
            )
            return

        if existing is not None and force:
            agent_id = existing["id"]
            log.info("--force: removing existing agent %s (id=%s)", _HANDLE, agent_id)
            await db.execute("DELETE FROM agent_handles WHERE handle = ?", (_HANDLE,))
            await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            # Remove old template rows named "Italian Restaurant Demo"
            await db.execute(
                "DELETE FROM agent_templates WHERE name = ?",
                ("Italian Restaurant Demo",),
            )
            await db.commit()
            log.info("Removed existing rows — re-seeding now.")

        # ------------------------------------------------------------------
        # 1. Insert agent_templates row
        # ------------------------------------------------------------------
        template_id = str(uuid.uuid4())
        now = _now_iso()

        # Build capabilities list from skills
        capabilities = json.dumps(tpl.get("skills", []))

        # Build the flow JSON for the template (greeting/farewell etc.)
        flow_json = json.dumps(tpl.get("flow", {}))

        # Build catalog schema JSON from knowledge base (menu structure)
        catalog_schema = json.dumps({
            "menu": tpl["knowledge_base"]["menu"],
            "hours": tpl["knowledge_base"]["hours"],
            "location": tpl["knowledge_base"]["location"],
            "faq": tpl["knowledge_base"]["faq"],
        })

        await db.execute(
            """
            INSERT INTO agent_templates
                (id, name, agent_type, industry_type,
                 system_prompt_template, flow_json, catalog_schema_json,
                 capabilities, icon, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                "Italian Restaurant Demo",
                tpl["agent_type"],        # "business"
                tpl["industry"],          # "restaurant"
                tpl["system_prompt"],     # full ~500-word prompt
                flow_json,
                catalog_schema,
                capabilities,
                tpl["branding"]["avatar_emoji"],
                now,
            ),
        )
        log.info("Inserted agent_templates row (id=%s)", template_id)

        # ------------------------------------------------------------------
        # 2. Insert agents row
        # ------------------------------------------------------------------
        agent_id = str(uuid.uuid4())

        # config_json: skills, branding, flow, knowledge base — everything
        # the runtime needs at chat time
        config_json = json.dumps({
            "description": (
                "Hi! I'm Sofia, the AI assistant for Mario's Italian Kitchen. "
                "I can help you with our menu, hours, reservations, "
                "and placing orders."
            ),
            "skills": tpl.get("skills", []),
            "branding": tpl["branding"],
            "flow": tpl["flow"],
            "knowledge_base": tpl["knowledge_base"],
            "is_demo": True,
        })

        branding_json = json.dumps(tpl["branding"])

        await db.execute(
            """
            INSERT INTO agents
                (id, user_id, handle, name, agent_type, industry_type,
                 template_id, config_json, branding_json, status,
                 subscription_tier, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'pro', ?, ?)
            """,
            (
                agent_id,
                _DEMO_OWNER_ID,
                _HANDLE,
                tpl["display_name"],       # "Mario's Italian Kitchen"
                tpl["agent_type"],         # "business"
                tpl["industry"],           # "restaurant"
                template_id,
                config_json,
                branding_json,
                now,
                now,
            ),
        )
        log.info(
            "Inserted agents row (id=%s, handle=%s)", agent_id, _HANDLE
        )

        # ------------------------------------------------------------------
        # 3. Insert agent_handles row
        # ------------------------------------------------------------------
        await db.execute(
            """
            INSERT OR IGNORE INTO agent_handles
                (handle, agent_id, claimed_at, reserved_at, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            (_HANDLE, agent_id, now, now),
        )
        log.info("Inserted agent_handles row (handle=%s)", _HANDLE)

        await db.commit()

    log.info("=" * 60)
    log.info("Demo agent seeded successfully!")
    log.info("  Handle      : %s", _HANDLE)
    log.info("  Name        : %s", tpl["display_name"])
    log.info("  Agent ID    : %s", agent_id)
    log.info("  Template ID : %s", template_id)
    log.info("  Database    : %s", db_path)
    log.info("=" * 60)
    log.info(
        "To chat with the agent, send a POST to /api/v1/agents/%s/chat",
        _HANDLE,
    )


def _print_summary(tpl: dict) -> None:
    """Print a readable summary of what would be seeded."""
    print("\n--- DRY-RUN SUMMARY ---")
    print(f"Handle      : {tpl['handle']}")
    print(f"Name        : {tpl['display_name']}")
    print(f"Agent type  : {tpl['agent_type']}")
    print(f"Industry    : {tpl['industry']}")
    print(f"Skills      : {', '.join(tpl.get('skills', []))}")
    print(f"Branding    : {tpl['branding']}")
    print(f"Menu items  : {sum(len(v) for v in tpl['knowledge_base']['menu'].values())} items across {len(tpl['knowledge_base']['menu'])} categories")
    print(f"FAQ entries : {len(tpl['knowledge_base']['faq'])}")
    print(f"System prompt length: {len(tpl['system_prompt'])} chars")
    print("-----------------------\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed the Mario's Italian Kitchen demo agent into the Agent 1 database."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be seeded without writing to the database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-seed even if @marios-italian already exists. "
            "Removes and re-inserts the existing rows."
        ),
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
    tpl = _load_template_json()

    log.info("Starting demo agent seed for %s", _HANDLE)

    await seed(db_path, tpl, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    asyncio.run(main())
