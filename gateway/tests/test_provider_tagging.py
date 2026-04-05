"""Tests for LLM provider tagging in audit trail entries.

TDD — these tests were written BEFORE the implementation.

Covers:
1. agent_response audit entry includes provider field for known models
2. agent_response audit entry includes provider=unknown for unrecognised models
3. agent_response_halted audit entry does not include provider (no LLM called)
4. agent_stream_response audit entry includes provider field
5. system_health per-provider error_rate_1h uses provider field from details JSON
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.core.audit import AuditChain
from isg_agent.models.provider import LLMMessage, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_response(model: str, provider: str = "openai") -> LLMResponse:
    """Build a minimal LLMResponse fixture."""
    return LLMResponse(
        content="Hello from the assistant.",
        model=model,
        input_tokens=10,
        output_tokens=20,
        finish_reason="stop",
    )


def _make_runtime(
    audit_chain: AuditChain,
    model_used: str = "gpt-4o-mini",
    *,
    llm_error: bool = False,
) -> Any:
    """Build a minimal AgentRuntime-like object with mocked dependencies."""
    from isg_agent.brain.agent import AgentConfig, AgentRuntime
    from isg_agent.core.convergence import ConvergenceGuard
    from isg_agent.core.governance import GovernanceGate
    from isg_agent.memory.store import MemoryStore
    from isg_agent.models.registry import ModelRegistry
    from isg_agent.brain.session import SessionManager

    # Governance → PROCEED
    gov = MagicMock()
    gov_result = MagicMock()
    gov_result.decision.value = "PROCEED"
    gov_result.reason = "test"
    from isg_agent.core.governance import GovernanceDecision
    gov_result.decision = GovernanceDecision.PROCEED
    gov.evaluate = AsyncMock(return_value=gov_result)

    # Session manager → returns a minimal session
    session = MagicMock()
    session.agent_id = None
    session_mgr = MagicMock()
    session_mgr.get_session = AsyncMock(return_value=session)
    session_mgr.update_token_count = AsyncMock()

    # Memory → empty history
    memory = MagicMock()
    memory.get_messages = AsyncMock(return_value=[])
    memory.save_message = AsyncMock()

    # Convergence guard (real instance, default limits)
    convergence = ConvergenceGuard()

    # Model registry
    registry = MagicMock()
    if llm_error:
        from isg_agent.models.registry import RegistryError
        registry.complete_with_fallback = AsyncMock(
            side_effect=RegistryError("forced failure")
        )
    else:
        registry.complete_with_fallback = AsyncMock(
            return_value=_make_llm_response(model_used)
        )

    runtime = AgentRuntime(
        model_registry=registry,
        governance_gate=gov,
        convergence_guard=convergence,
        audit_chain=audit_chain,
        memory_store=memory,
        session_manager=session_mgr,
        config=AgentConfig(default_model=model_used),
    )
    return runtime


# ---------------------------------------------------------------------------
# 1. agent_response audit entry carries provider for known models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_response_audit_includes_provider_openai(
    tmp_path: Path,
) -> None:
    """agent_response audit entry must include provider=openai for GPT models."""
    chain = AuditChain(db_path=str(tmp_path / "audit.db"))
    runtime = _make_runtime(chain, model_used="gpt-4o-mini")

    await runtime.process_message(
        session_id="sess-001",
        user_message="Hello",
    )

    entries = await chain.get_entries(event_type_filter="agent_response")
    assert entries, "Expected at least one agent_response audit entry"

    details = json.loads(entries[-1].details)
    assert "provider" in details, f"provider missing from details: {details}"
    assert details["provider"] == "openai"


@pytest.mark.asyncio
async def test_agent_response_audit_includes_provider_anthropic(
    tmp_path: Path,
) -> None:
    """agent_response audit entry must include provider=anthropic for Claude models."""
    chain = AuditChain(db_path=str(tmp_path / "audit.db"))
    runtime = _make_runtime(chain, model_used="claude-sonnet-4-6")

    await runtime.process_message(
        session_id="sess-002",
        user_message="Analyse this",
    )

    entries = await chain.get_entries(event_type_filter="agent_response")
    assert entries

    details = json.loads(entries[-1].details)
    assert details.get("provider") == "anthropic"


# ---------------------------------------------------------------------------
# 2. Unknown model → provider=unknown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_response_audit_unknown_model_provider_unknown(
    tmp_path: Path,
) -> None:
    """An unrecognised model name must produce provider=unknown — never crash."""
    chain = AuditChain(db_path=str(tmp_path / "audit.db"))
    runtime = _make_runtime(chain, model_used="some-future-model-xyz")

    await runtime.process_message(
        session_id="sess-003",
        user_message="Test",
    )

    entries = await chain.get_entries(event_type_filter="agent_response")
    assert entries

    details = json.loads(entries[-1].details)
    assert "provider" in details
    assert details["provider"] == "unknown"


# ---------------------------------------------------------------------------
# 3. LLM error path — provider still recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_response_audit_llm_error_records_provider(
    tmp_path: Path,
) -> None:
    """Even when the LLM call fails, the audit entry must include provider."""
    chain = AuditChain(db_path=str(tmp_path / "audit.db"))
    runtime = _make_runtime(chain, model_used="gpt-4o-mini", llm_error=True)

    await runtime.process_message(
        session_id="sess-004",
        user_message="This will fail",
    )

    entries = await chain.get_entries(event_type_filter="agent_response")
    assert entries

    details = json.loads(entries[-1].details)
    assert "provider" in details


# ---------------------------------------------------------------------------
# 4. Streaming audit entry carries provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_stream_usage_audit_includes_provider(
    tmp_path: Path,
) -> None:
    """_record_stream_usage must write provider into the agent_stream_response entry."""
    from isg_agent.api.routes.streaming import _record_stream_usage

    chain = AuditChain(db_path=str(tmp_path / "stream_audit.db"))

    # Build a minimal request mock that exposes the necessary app.state attributes
    mock_memory = MagicMock()
    mock_memory.save_message = AsyncMock()

    mock_session_mgr = MagicMock()
    mock_session_mgr.update_token_count = AsyncMock()

    mock_provider = MagicMock()
    mock_provider.provider_name = "openai"

    mock_registry = MagicMock()
    mock_registry.list_providers = MagicMock(return_value=["openai"])
    mock_registry.get = MagicMock(return_value=mock_provider)

    mock_state = MagicMock()
    mock_state.memory_store = mock_memory
    mock_state.session_manager = mock_session_mgr
    mock_state.audit_chain = chain
    mock_state.runtime = MagicMock()
    mock_state.runtime._registry = mock_registry

    mock_app = MagicMock()
    mock_app.state = mock_state

    mock_request = MagicMock()
    mock_request.app = mock_app

    await _record_stream_usage(
        request=mock_request,
        session_id="sess-stream-001",
        user_id="widget:visitor-abc",
        user_message="Hello stream",
        full_response="Hi there",
        input_tokens=5,
        output_tokens=10,
        provider_name="openai",
    )

    entries = await chain.get_entries(event_type_filter="agent_stream_response")
    assert entries, "Expected agent_stream_response audit entry"

    details = json.loads(entries[-1].details)
    assert "provider" in details, f"provider missing from stream audit: {details}"
    assert details["provider"] == "openai"


# ---------------------------------------------------------------------------
# 5. system_health per-provider error_rate query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_health_per_provider_error_rate(tmp_path: Path) -> None:
    """system_health must compute per-provider error_rate_1h from audit details.provider."""
    import aiosqlite
    from datetime import datetime, timezone

    db_path = str(tmp_path / "health.db")

    # Seed audit entries — two openai errors, one anthropic error, and two successes
    now_ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    async with aiosqlite.connect(db_path) as db:
        # Create table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '{}',
                entry_hash TEXT NOT NULL DEFAULT '',
                prev_hash TEXT NOT NULL DEFAULT '',
                session_id TEXT,
                agent_id TEXT
            )
        """)
        rows = [
            # openai errors
            ("agent_response", json.dumps({"provider": "openai", "llm_error": "rate limit"})),
            ("agent_response", json.dumps({"provider": "openai", "llm_error": "timeout"})),
            # anthropic error
            ("agent_response", json.dumps({"provider": "anthropic", "llm_error": "overload"})),
            # successes (no llm_error key)
            ("agent_response", json.dumps({"provider": "openai", "model_used": "gpt-4o-mini"})),
            ("agent_response", json.dumps({"provider": "anthropic", "model_used": "claude-sonnet-4-6"})),
        ]
        for event_type, details in rows:
            await db.execute(
                "INSERT INTO audit_chain (timestamp, event_type, actor, details, entry_hash, prev_hash) "
                "VALUES (?, ?, 'test', ?, 'h', 'p')",
                (now_ts, event_type, details),
            )
        await db.commit()

    from isg_agent.api.routes.system_health import _compute_per_provider_error_rates

    rates = await _compute_per_provider_error_rates(db_path, cutoff_iso=now_ts)

    # openai: 2 errors out of 3 total → 0.6667
    assert "openai" in rates
    assert rates["openai"] > 0.0

    # anthropic: 1 error out of 2 total → 0.5
    assert "anthropic" in rates
    assert rates["anthropic"] > 0.0

    # openai error rate should be higher than anthropic's
    assert rates["openai"] > rates["anthropic"]
