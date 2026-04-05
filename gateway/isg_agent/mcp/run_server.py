#!/usr/bin/env python3
"""Standalone MCP server runner for DingDawg Agent 1.

Run this script to start the MCP server as a standalone process that
Claude Desktop, Claude Code, or any MCP client can connect to.

Usage (stdio transport — default for Claude Desktop):
    python -m isg_agent.mcp.run_server

Usage (SSE transport — for remote/HTTP connections):
    python -m isg_agent.mcp.run_server --transport sse --port 8765

The server exposes 25 tools (12 platform + 13 business skills) and
3 resources for full DingDawg Agent 1 interaction.

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
        "mcpServers": {
            "dingdawg": {
                "command": "python",
                "args": ["-m", "isg_agent.mcp.run_server"],
                "cwd": "/path/to/DingDawg-Agent-1/gateway"
            }
        }
    }

Claude Code config (~/.claude/settings.json):
    {
        "mcpServers": {
            "dingdawg": {
                "command": "python",
                "args": ["-m", "isg_agent.mcp.run_server"],
                "cwd": "/path/to/DingDawg-Agent-1/gateway"
            }
        }
    }
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _initialize_app_state():
    """Initialize the minimal app state needed for the MCP server.

    Creates the database, agent registry, session manager, skill executor,
    and usage meter — the same components used by the full FastAPI app.
    """
    from types import SimpleNamespace

    from isg_agent.config import get_settings

    settings = get_settings()
    db_path = settings.db_path

    # Initialize database schema
    from isg_agent.db import ensure_schema
    await ensure_schema(db_path)

    # Agent Registry
    from isg_agent.agents.registry import AgentRegistry
    agent_registry = AgentRegistry(db_path=db_path)

    # Session Manager
    from isg_agent.brain.session import SessionManager
    session_manager = SessionManager(db_path=db_path)

    # Skill Executor with builtin skills
    from isg_agent.skills.executor import SkillExecutor
    skill_executor = SkillExecutor(workspace_root=".")

    # Register builtin skills
    from isg_agent.skills.builtin import register_builtin_skills
    registered = await register_builtin_skills(skill_executor, db_path)
    logger.info("Registered %d builtin skills for MCP", len(registered))

    # Usage Meter (best-effort)
    usage_meter = None
    try:
        from isg_agent.finance.usage import UsageMeter
        usage_meter = UsageMeter(db_path=db_path)
    except Exception as exc:
        logger.warning("UsageMeter not available: %s", exc)

    # MCP API keys table
    from isg_agent.mcp.auth import ensure_mcp_keys_table
    await ensure_mcp_keys_table(db_path)

    state = SimpleNamespace(
        agent_registry=agent_registry,
        session_manager=session_manager,
        skill_executor=skill_executor,
        usage_meter=usage_meter,
        settings=settings,
    )

    return state


def main():
    parser = argparse.ArgumentParser(description="DingDawg Agent 1 MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio for Claude Desktop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    args = parser.parse_args()

    # Import and wire the MCP server
    from isg_agent.mcp.server import mcp, wire_app_state

    # Initialize app state
    state = asyncio.run(_initialize_app_state())
    wire_app_state(state)

    logger.info(
        "Starting DingDawg MCP server (transport=%s, tools=25, resources=3)",
        args.transport,
    )

    # Run the MCP server
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", port=args.port)


if __name__ == "__main__":
    main()
