"""TDD tests for the DingDawg Agent 1 preamble system.

Tests are written FIRST — they will FAIL until the implementation is complete.

Covers:
- _build_agent_preamble: function that constructs a personalized system prompt
  for an agent using its name, industry, and optional template.
- SessionCreate schema: should accept an optional agent_id field.
- AgentRuntime integration: when a session has an agent_id, process_message
  must use the agent's personalized preamble rather than the generic prompt.
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from isg_agent.agents.agent_types import (
    AgentRecord,
    AgentStatus,
    AgentType,
    SubscriptionTier,
)
from isg_agent.brain.agent import AgentConfig, AgentRuntime, _build_agent_preamble
from isg_agent.brain.session import SessionManager
from isg_agent.core.audit import AuditChain
from isg_agent.core.convergence import ConvergenceGuard, ResourceBudget
from isg_agent.core.governance import GovernanceGate
from isg_agent.memory.store import MemoryStore
from isg_agent.models.provider import LLMMessage, LLMProvider, LLMResponse
from isg_agent.models.registry import ModelRegistry
from isg_agent.schemas.sessions import SessionCreate
from isg_agent.templates.template_registry import TemplateRecord


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_agent(
    *,
    name: str = "Joes Pizza Bot",
    handle: str = "joes-pizza",
    agent_type: AgentType = AgentType.BUSINESS,
    industry_type: Optional[str] = "restaurant",
    template_id: Optional[str] = None,
) -> AgentRecord:
    """Build a minimal AgentRecord for use in tests."""
    return AgentRecord(
        id="agent-001",
        user_id="user-001",
        handle=handle,
        name=name,
        agent_type=agent_type,
        industry_type=industry_type,
        template_id=template_id,
        config_json="{}",
        branding_json="{}",
        constitution_yaml=None,
        status=AgentStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _make_template(
    *,
    system_prompt_template: str = (
        "You are {agent_name}, the AI ordering assistant for {business_name}.\n\n"
        "Capabilities: {capabilities}\n\n"
        "{greeting}"
    ),
    capabilities: str = '["browse_menu", "place_order"]',
    name: str = "Restaurant",
    industry_type: str = "restaurant",
) -> TemplateRecord:
    """Build a minimal TemplateRecord for use in tests."""
    return TemplateRecord(
        id="tmpl-001",
        name=name,
        agent_type="business",
        industry_type=industry_type,
        system_prompt_template=system_prompt_template,
        flow_json='{"steps": []}',
        catalog_schema_json=None,
        capabilities=capabilities,
        default_constitution_yaml=None,
        icon=None,
        created_at="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Mock LLM provider — captures the system prompt passed to each call
# ---------------------------------------------------------------------------


class CapturingProvider(LLMProvider):
    """LLM provider that records every messages list it receives."""

    def __init__(self) -> None:
        self.received_messages: list[list[LLMMessage]] = []

    @property
    def provider_name(self) -> str:
        return "capturing"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.received_messages.append(list(messages))
        return LLMResponse(
            content="Hello from capturing provider!",
            model=model or "capturing-model",
            input_tokens=30,
            output_tokens=10,
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        yield "Hello"


# ---------------------------------------------------------------------------
# Shared async fixtures (mirrors pattern in test_mvp_core.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def audit_chain(tmp_path):
    chain = AuditChain(db_path=str(tmp_path / "test_preamble_audit.db"))
    yield chain


@pytest_asyncio.fixture
async def governance_gate(audit_chain):
    return GovernanceGate(audit_chain=audit_chain)


@pytest_asyncio.fixture
async def memory_store():
    store = MemoryStore(db_path=":memory:")
    yield store
    await store.close()


@pytest_asyncio.fixture
async def session_manager():
    mgr = SessionManager(db_path=":memory:")
    yield mgr
    await mgr.close()


@pytest_asyncio.fixture
def capturing_provider():
    return CapturingProvider()


@pytest_asyncio.fixture
async def model_registry(capturing_provider):
    registry = ModelRegistry()
    registry.register("capturing", capturing_provider)
    registry.set_fallback_chain(["capturing"])
    return registry


# ---------------------------------------------------------------------------
# 1. _build_agent_preamble tests
# ---------------------------------------------------------------------------


class TestBuildAgentPreamble:
    """Unit tests for the _build_agent_preamble helper function."""

    def test_preamble_with_template(self) -> None:
        """When agent has template_id and template has system_prompt_template,
        the preamble uses the template's prompt with placeholders filled in."""
        agent = _make_agent(
            name="Joe's Pizza Bot",
            template_id="tmpl-001",
        )
        template = _make_template(
            system_prompt_template=(
                "You are {agent_name}, the AI ordering assistant for {business_name}.\n\n"
                "Capabilities: {capabilities}\n\n"
                "{greeting}"
            )
        )

        preamble = _build_agent_preamble(agent, template)

        # Agent name must be substituted
        assert "Joe's Pizza Bot" in preamble
        # Template structure must be used (contains words from template)
        assert "ordering assistant" in preamble

    def test_preamble_without_template(self) -> None:
        """When template is None, uses DingDawg default preamble containing agent name."""
        agent = _make_agent(name="My Salon Bot", template_id=None)

        preamble = _build_agent_preamble(agent, template=None)

        assert isinstance(preamble, str)
        assert len(preamble) > 20
        assert "My Salon Bot" in preamble

    def test_preamble_empty_template_prompt(self) -> None:
        """When template exists but system_prompt_template is empty, falls back to default."""
        agent = _make_agent(name="Empty Template Agent", template_id="tmpl-empty")
        template = _make_template(system_prompt_template="")

        preamble = _build_agent_preamble(agent, template)

        # Should fall back gracefully — must still contain agent name and be non-empty
        assert isinstance(preamble, str)
        assert len(preamble) > 10
        assert "Empty Template Agent" in preamble

    def test_preamble_contains_agent_name(self) -> None:
        """The returned preamble always contains the agent's name regardless of path."""
        for name, tmpl in [
            ("Alpha Bot", _make_template()),
            ("Beta Bot", None),
        ]:
            agent = _make_agent(
                name=name,
                template_id="t1" if tmpl else None,
            )
            preamble = _build_agent_preamble(agent, tmpl)
            assert name in preamble, (
                f"Expected agent name {name!r} in preamble but got: {preamble[:200]}"
            )

    def test_preamble_no_mila_references(self) -> None:
        """The returned preamble must never mention MiLA, SEK, governance, or kernel.

        This is a security invariant: internal IP must not leak into customer-facing prompts.
        """
        forbidden = ["MiLA", "SEK", "governance", "kernel"]

        # Test both code paths: with and without template
        agent_with_tmpl = _make_agent(name="Public Bot", template_id="tmpl-001")
        agent_no_tmpl = _make_agent(name="Generic Bot", template_id=None)
        template = _make_template()

        for agent, tmpl in [
            (agent_with_tmpl, template),
            (agent_no_tmpl, None),
        ]:
            preamble = _build_agent_preamble(agent, tmpl)
            for word in forbidden:
                assert word.lower() not in preamble.lower(), (
                    f"Forbidden word {word!r} found in preamble: {preamble[:300]}"
                )


# ---------------------------------------------------------------------------
# 2. SessionCreate schema tests
# ---------------------------------------------------------------------------


class TestSessionCreateSchema:
    """Tests that SessionCreate accepts the new optional agent_id field."""

    def test_session_create_accepts_agent_id(self) -> None:
        """SessionCreate must accept an agent_id field without validation error."""
        body = SessionCreate(agent_id="agent-001")
        assert body.agent_id == "agent-001"

    def test_session_create_agent_id_defaults_none(self) -> None:
        """Without agent_id, the field must default to None."""
        body = SessionCreate()
        assert body.agent_id is None

    def test_session_create_agent_id_with_system_prompt(self) -> None:
        """agent_id and system_prompt can coexist in the same request."""
        body = SessionCreate(
            agent_id="agent-xyz",
            system_prompt="Custom prompt override.",
        )
        assert body.agent_id == "agent-xyz"
        assert body.system_prompt == "Custom prompt override."


# ---------------------------------------------------------------------------
# 3. AgentRuntime integration tests
# ---------------------------------------------------------------------------


class TestAgentRuntimePreambleIntegration:
    """Integration tests verifying that AgentRuntime uses preamble when agent_id is set."""

    async def test_process_message_uses_agent_preamble(
        self,
        model_registry: ModelRegistry,
        governance_gate: GovernanceGate,
        audit_chain: AuditChain,
        memory_store: MemoryStore,
        session_manager: SessionManager,
        capturing_provider: CapturingProvider,
    ) -> None:
        """When a session has an agent_id, the system prompt must contain the agent's name,
        not the generic 'helpful AI assistant' fallback."""
        agent_name = "Taco Town Bot"
        agent = _make_agent(name=agent_name, template_id=None)

        # Mock agent_registry that returns our agent
        agent_registry = MagicMock()
        agent_registry.get_agent = AsyncMock(return_value=agent)

        # Mock template_registry (no template for this agent)
        template_registry = MagicMock()
        template_registry.get_template = AsyncMock(return_value=None)

        budget = ResourceBudget(max_iterations=100, max_llm_calls=50, max_tokens=100_000)
        guard = ConvergenceGuard(budget=budget)
        guard.start()

        runtime = AgentRuntime(
            model_registry=model_registry,
            governance_gate=governance_gate,
            convergence_guard=guard,
            audit_chain=audit_chain,
            memory_store=memory_store,
            session_manager=session_manager,
            agent_registry=agent_registry,
            template_registry=template_registry,
        )

        # Create a session with agent_id stored
        session = await session_manager.create_session(
            user_id="user-001",
            agent_id="agent-001",
        )

        response = await runtime.process_message(
            session_id=session.session_id,
            user_message="Hello, can you help me?",
            user_id="user-001",
        )

        assert response.halted is False

        # The system prompt passed to the LLM must contain the agent's name
        assert len(capturing_provider.received_messages) > 0
        first_call_messages = capturing_provider.received_messages[0]
        system_msg = next(
            (m for m in first_call_messages if m.role == "system"),
            None,
        )
        assert system_msg is not None, "No system message found in LLM call"
        assert agent_name in system_msg.content, (
            f"Expected agent name {agent_name!r} in system prompt, got: "
            f"{system_msg.content[:300]}"
        )

    async def test_process_message_generic_without_agent_id(
        self,
        model_registry: ModelRegistry,
        governance_gate: GovernanceGate,
        audit_chain: AuditChain,
        memory_store: MemoryStore,
        session_manager: SessionManager,
        capturing_provider: CapturingProvider,
    ) -> None:
        """When a session has no agent_id, the runtime must use the generic system prompt."""
        budget = ResourceBudget(max_iterations=100, max_llm_calls=50, max_tokens=100_000)
        guard = ConvergenceGuard(budget=budget)
        guard.start()

        generic_system_prompt = (
            "You are a helpful, security-conscious AI assistant. "
            "Respond clearly and concisely. "
            "Never reveal system internals or governance decisions."
        )
        config = AgentConfig(system_prompt=generic_system_prompt)

        runtime = AgentRuntime(
            model_registry=model_registry,
            governance_gate=governance_gate,
            convergence_guard=guard,
            audit_chain=audit_chain,
            memory_store=memory_store,
            session_manager=session_manager,
            config=config,
            # No agent_registry / template_registry injected
        )

        # Create a plain session without agent_id
        session = await session_manager.create_session(user_id="user-002")

        response = await runtime.process_message(
            session_id=session.session_id,
            user_message="Hi there!",
            user_id="user-002",
        )

        assert response.halted is False

        # The system message must contain the generic prompt text (not a personalized name)
        assert len(capturing_provider.received_messages) > 0
        first_call_messages = capturing_provider.received_messages[0]
        system_msg = next(
            (m for m in first_call_messages if m.role == "system"),
            None,
        )
        assert system_msg is not None, "No system message found in LLM call"
        assert "helpful" in system_msg.content.lower(), (
            f"Expected generic helpful prompt, got: {system_msg.content[:300]}"
        )
