"""Tests for the MVP vertical slice: schemas, agent routes, runtime wiring, and app factory.

Tests cover:
- MessageRequest / MessageResponse schemas
- SessionCreate / SessionResponse / SessionList schemas
- AgentRuntime.process_message with mocked LLM provider
- Agent API routes via HTTPX/TestClient (sessions CRUD + message send)
- App factory wiring and health endpoint
- Auth route integration (register + login + token usage)

All LLM calls are mocked — no real API keys required.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from isg_agent.brain.agent import AgentConfig, AgentResponse, AgentRuntime
from isg_agent.brain.session import SessionManager, SessionNotFoundError, SessionState
from isg_agent.core.audit import AuditChain
from isg_agent.core.convergence import ConvergenceGuard, ConvergenceStatus, ResourceBudget
from isg_agent.core.governance import GovernanceDecision, GovernanceGate, GovernanceResult, RiskTier
from isg_agent.memory.store import MemoryStore
from isg_agent.models.provider import LLMMessage, LLMProvider, LLMResponse, ProviderError, RateLimitError
from isg_agent.models.registry import ModelRegistry, ProviderNotFoundError, RegistryError
from isg_agent.schemas.messages import MessageRequest, MessageResponse
from isg_agent.schemas.sessions import SessionCreate, SessionList, SessionResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockProvider(LLMProvider):
    """A mock LLM provider that returns canned responses without API calls."""

    def __init__(self, response_content: str = "Hello from mock LLM!") -> None:
        self._response_content = response_content
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content=self._response_content,
            model=model or "mock-model",
            input_tokens=50,
            output_tokens=20,
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
        for word in self._response_content.split():
            yield word + " "


class FailingProvider(LLMProvider):
    """A mock provider that always raises ProviderError."""

    @property
    def provider_name(self) -> str:
        return "failing"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        raise ProviderError(message="Mock failure", provider="failing")

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        raise ProviderError(message="Mock failure", provider="failing")
        yield  # noqa: unreachable — makes this an async generator


@pytest_asyncio.fixture
async def audit_chain(tmp_path):
    """Create a temporary audit chain."""
    chain = AuditChain(db_path=str(tmp_path / "test_audit.db"))
    yield chain


@pytest_asyncio.fixture
async def governance_gate(audit_chain):
    """Create a governance gate with audit chain."""
    return GovernanceGate(audit_chain=audit_chain)


@pytest_asyncio.fixture
async def memory_store():
    """Create an in-memory memory store."""
    store = MemoryStore(db_path=":memory:")
    yield store
    await store.close()


@pytest_asyncio.fixture
async def session_manager():
    """Create an in-memory session manager."""
    mgr = SessionManager(db_path=":memory:")
    yield mgr
    await mgr.close()


@pytest_asyncio.fixture
async def model_registry():
    """Create a model registry with a mock provider."""
    registry = ModelRegistry()
    registry.register("mock", MockProvider())
    registry.set_fallback_chain(["mock"])
    return registry


@pytest_asyncio.fixture
async def agent_runtime(
    model_registry,
    governance_gate,
    audit_chain,
    memory_store,
    session_manager,
):
    """Create a fully wired AgentRuntime with mock LLM."""
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
    )
    return runtime


# ===========================================================================
# Schema tests
# ===========================================================================


class TestMessageSchemas:
    """Tests for MessageRequest and MessageResponse Pydantic models."""

    def test_message_request_valid(self):
        req = MessageRequest(content="Hello world")
        assert req.content == "Hello world"

    def test_message_request_min_length(self):
        with pytest.raises(Exception):
            MessageRequest(content="")

    def test_message_request_max_length(self):
        long_msg = "x" * 10_001
        with pytest.raises(Exception):
            MessageRequest(content=long_msg)

    def test_message_request_at_max_boundary(self):
        msg = "x" * 10_000
        req = MessageRequest(content=msg)
        assert len(req.content) == 10_000

    def test_message_response_defaults(self):
        resp = MessageResponse(
            content="Hi", session_id="s1", model_used="gpt-4o"
        )
        assert resp.content == "Hi"
        assert resp.governance_decision == "PROCEED"
        assert resp.convergence_status == "WITHIN_BUDGET"
        assert resp.halted is False
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0

    def test_message_response_all_fields(self):
        resp = MessageResponse(
            content="response",
            session_id="s2",
            model_used="claude-3",
            input_tokens=100,
            output_tokens=50,
            governance_decision="REVIEW",
            convergence_status="WARNING",
            halted=False,
        )
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50
        assert resp.governance_decision == "REVIEW"

    def test_message_response_halted(self):
        resp = MessageResponse(
            content="blocked",
            session_id="s3",
            model_used="none",
            halted=True,
            governance_decision="HALT",
        )
        assert resp.halted is True
        assert resp.governance_decision == "HALT"


class TestSessionSchemas:
    """Tests for SessionCreate, SessionResponse, and SessionList models."""

    def test_session_create_empty(self):
        sc = SessionCreate()
        assert sc.system_prompt is None

    def test_session_create_with_prompt(self):
        sc = SessionCreate(system_prompt="Be helpful")
        assert sc.system_prompt == "Be helpful"

    def test_session_create_prompt_too_long(self):
        with pytest.raises(Exception):
            SessionCreate(system_prompt="x" * 5_001)

    def test_session_response_defaults(self):
        sr = SessionResponse(
            session_id="s1",
            user_id="u1",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert sr.message_count == 0
        assert sr.total_tokens == 0
        assert sr.status == "active"

    def test_session_response_all_fields(self):
        sr = SessionResponse(
            session_id="s2",
            user_id="u2",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T01:00:00Z",
            message_count=10,
            total_tokens=500,
            status="closed",
        )
        assert sr.message_count == 10
        assert sr.total_tokens == 500
        assert sr.status == "closed"

    def test_session_list(self):
        items = [
            SessionResponse(
                session_id=f"s{i}",
                user_id="u1",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
            for i in range(3)
        ]
        sl = SessionList(sessions=items, count=3)
        assert sl.count == 3
        assert len(sl.sessions) == 3

    def test_session_list_empty(self):
        sl = SessionList(sessions=[], count=0)
        assert sl.count == 0
        assert sl.sessions == []


# ===========================================================================
# AgentRuntime tests (with mock LLM)
# ===========================================================================


class TestAgentRuntime:
    """Tests for AgentRuntime.process_message with mocked LLM."""

    @pytest.mark.asyncio
    async def test_process_message_happy_path(self, agent_runtime, session_manager):
        session = await session_manager.create_session(user_id="test_user")

        response = await agent_runtime.process_message(
            session_id=session.session_id,
            user_message="Hello!",
            user_id="test_user",
        )

        assert isinstance(response, AgentResponse)
        assert response.content == "Hello from mock LLM!"
        assert response.model_used == "mock-model"
        assert response.governance_decision == "PROCEED"
        assert response.halted is False
        assert response.input_tokens == 50
        assert response.output_tokens == 20

    @pytest.mark.asyncio
    async def test_process_message_audit_hash(self, agent_runtime, session_manager):
        session = await session_manager.create_session(user_id="test_user")

        response = await agent_runtime.process_message(
            session_id=session.session_id,
            user_message="Test audit",
        )

        # Audit hash should be a 64-character hex SHA-256
        assert len(response.audit_hash) == 64
        assert all(c in "0123456789abcdef" for c in response.audit_hash)

    @pytest.mark.asyncio
    async def test_process_message_session_not_found(self, agent_runtime):
        with pytest.raises(SessionNotFoundError):
            await agent_runtime.process_message(
                session_id="nonexistent-session",
                user_message="Hello!",
            )

    @pytest.mark.asyncio
    async def test_process_message_saves_to_memory(
        self, agent_runtime, session_manager, memory_store
    ):
        session = await session_manager.create_session(user_id="test_user")

        await agent_runtime.process_message(
            session_id=session.session_id,
            user_message="Test memory",
        )

        messages = await memory_store.get_messages(session.session_id)
        assert len(messages) == 2  # user + assistant
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Test memory"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hello from mock LLM!"

    @pytest.mark.asyncio
    async def test_process_message_updates_session_stats(
        self, agent_runtime, session_manager
    ):
        session = await session_manager.create_session(user_id="test_user")

        await agent_runtime.process_message(
            session_id=session.session_id,
            user_message="Test stats",
        )

        updated = await session_manager.get_session(session.session_id)
        assert updated is not None
        assert updated.total_tokens == 70  # 50 input + 20 output
        assert updated.message_count == 2

    @pytest.mark.asyncio
    async def test_process_message_governance_halt(
        self,
        session_manager,
        memory_store,
        audit_chain,
    ):
        """Governance HALT should block LLM call and return rejection."""
        # Create a registry with mock provider to confirm it is NOT called
        mock_provider = MockProvider()
        registry = ModelRegistry()
        registry.register("mock", mock_provider)
        registry.set_fallback_chain(["mock"])

        # Create a governance gate that always returns HALT
        gate = GovernanceGate(audit_chain=audit_chain)

        budget = ResourceBudget(max_iterations=100)
        guard = ConvergenceGuard(budget=budget)
        guard.start()

        runtime = AgentRuntime(
            model_registry=registry,
            governance_gate=gate,
            convergence_guard=guard,
            audit_chain=audit_chain,
            memory_store=memory_store,
            session_manager=session_manager,
        )

        session = await session_manager.create_session(user_id="test_user")

        # Use keywords that trigger CRITICAL -> HALT
        response = await runtime.process_message(
            session_id=session.session_id,
            user_message="Please delete all data in production and deploy",
        )

        assert response.halted is True
        assert response.governance_decision == "HALT"
        assert response.model_used == "none"
        assert mock_provider.call_count == 0

    @pytest.mark.asyncio
    async def test_process_message_governance_review(
        self,
        session_manager,
        memory_store,
        audit_chain,
    ):
        """Governance REVIEW should prepend review notice.

        The AgentRuntime passes ``risk_tier=RiskTier.LOW`` to the gate, so auto-
        classification is overridden.  However the gate's keyword escalation
        still fires for HIGH-tier keywords (e.g. "delete").  We use "delete" here
        because the escalation logic requires ``found_high`` to be non-empty for
        the tier to be bumped from LOW → HIGH → REVIEW.
        """
        mock_provider = MockProvider(response_content="Normal response")
        registry = ModelRegistry()
        registry.register("mock", mock_provider)
        registry.set_fallback_chain(["mock"])

        gate = GovernanceGate(audit_chain=audit_chain)

        budget = ResourceBudget(max_iterations=100)
        guard = ConvergenceGuard(budget=budget)
        guard.start()

        config = AgentConfig(review_notice="[REVIEWED] ")

        runtime = AgentRuntime(
            model_registry=registry,
            governance_gate=gate,
            convergence_guard=guard,
            audit_chain=audit_chain,
            memory_store=memory_store,
            session_manager=session_manager,
            config=config,
        )

        session = await session_manager.create_session(user_id="test_user")

        # "delete" is a HIGH keyword — escalates LOW override → HIGH → REVIEW
        response = await runtime.process_message(
            session_id=session.session_id,
            user_message="Please delete all temporary files",
        )

        assert response.governance_decision == "REVIEW"
        assert response.halted is False
        assert response.content.startswith("[REVIEWED]")

    @pytest.mark.asyncio
    async def test_process_message_llm_error_graceful(
        self,
        session_manager,
        memory_store,
        audit_chain,
    ):
        """LLM provider error should return graceful error message."""
        failing = FailingProvider()
        registry = ModelRegistry()
        registry.register("failing", failing)
        registry.set_fallback_chain(["failing"])

        gate = GovernanceGate(audit_chain=audit_chain)
        budget = ResourceBudget(max_iterations=100)
        guard = ConvergenceGuard(budget=budget)
        guard.start()

        runtime = AgentRuntime(
            model_registry=registry,
            governance_gate=gate,
            convergence_guard=guard,
            audit_chain=audit_chain,
            memory_store=memory_store,
            session_manager=session_manager,
        )

        session = await session_manager.create_session(user_id="test_user")

        response = await runtime.process_message(
            session_id=session.session_id,
            user_message="Hello!",
        )

        assert "temporarily unable" in response.content.lower()
        assert response.model_used == "none"

    @pytest.mark.asyncio
    async def test_convergence_tracking(self, agent_runtime, session_manager):
        """Multiple messages should increment convergence counters."""
        session = await session_manager.create_session(user_id="test_user")

        for i in range(3):
            await agent_runtime.process_message(
                session_id=session.session_id,
                user_message=f"Message {i}",
            )

        assert agent_runtime._convergence.iterations_used == 3
        assert agent_runtime._convergence.llm_calls_made == 3
        assert agent_runtime._convergence.tokens_used == 210  # 3 * 70

    @pytest.mark.asyncio
    async def test_message_history_builds_up(
        self, agent_runtime, session_manager, memory_store
    ):
        """Message history should accumulate across turns."""
        session = await session_manager.create_session(user_id="test_user")

        await agent_runtime.process_message(
            session_id=session.session_id, user_message="First"
        )
        await agent_runtime.process_message(
            session_id=session.session_id, user_message="Second"
        )

        messages = await memory_store.get_messages(session.session_id)
        assert len(messages) == 4  # 2 user + 2 assistant


# ===========================================================================
# ModelRegistry tests (with mocks)
# ===========================================================================


class TestModelRegistryIntegration:
    """Integration tests for ModelRegistry with mock providers."""

    @pytest.mark.asyncio
    async def test_fallback_chain_success(self):
        registry = ModelRegistry()
        mock = MockProvider(response_content="Success!")
        registry.register("mock", mock)
        registry.set_fallback_chain(["mock"])

        messages = [LLMMessage(role="user", content="Hi")]
        resp = await registry.complete_with_fallback(messages)
        assert resp.content == "Success!"

    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self):
        registry = ModelRegistry()
        failing = FailingProvider()
        mock = MockProvider(response_content="Fallback!")
        registry.register("primary", failing)
        registry.register("secondary", mock)
        registry.set_fallback_chain(["primary", "secondary"])

        messages = [LLMMessage(role="user", content="Hi")]
        resp = await registry.complete_with_fallback(messages)
        assert resp.content == "Fallback!"

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        registry = ModelRegistry()
        f1 = FailingProvider()
        f2 = FailingProvider()
        registry.register("f1", f1)
        registry.register("f2", f2)
        registry.set_fallback_chain(["f1", "f2"])

        messages = [LLMMessage(role="user", content="Hi")]
        with pytest.raises(RegistryError, match="All providers exhausted"):
            await registry.complete_with_fallback(messages)

    @pytest.mark.asyncio
    async def test_no_providers_raises(self):
        registry = ModelRegistry()
        messages = [LLMMessage(role="user", content="Hi")]
        with pytest.raises(RegistryError, match="No providers available"):
            await registry.complete_with_fallback(messages)

    @pytest.mark.asyncio
    async def test_preferred_provider(self):
        registry = ModelRegistry()
        mock1 = MockProvider(response_content="Primary")
        mock2 = MockProvider(response_content="Preferred")
        registry.register("primary", mock1)
        registry.register("preferred", mock2)
        registry.set_fallback_chain(["primary"])

        messages = [LLMMessage(role="user", content="Hi")]
        resp = await registry.complete_with_fallback(
            messages, preferred_provider="preferred"
        )
        assert resp.content == "Preferred"


# ===========================================================================
# MemoryStore integration tests
# ===========================================================================


class TestMemoryStoreIntegration:
    """Integration tests for MemoryStore with in-memory SQLite."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, memory_store):
        await memory_store.save_message("s1", "user", "Hello")
        await memory_store.save_message("s1", "assistant", "Hi there")

        messages = await memory_store.get_messages("s1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_get_messages_empty_session(self, memory_store):
        messages = await memory_store.get_messages("nonexistent")
        assert messages == []

    @pytest.mark.asyncio
    async def test_clear_session(self, memory_store):
        await memory_store.save_message("s1", "user", "Hello")
        await memory_store.save_message("s1", "assistant", "Hi")

        deleted = await memory_store.clear_session("s1")
        assert deleted == 2

        messages = await memory_store.get_messages("s1")
        assert messages == []

    @pytest.mark.asyncio
    async def test_message_count(self, memory_store):
        await memory_store.save_message("s1", "user", "A")
        await memory_store.save_message("s1", "assistant", "B")
        await memory_store.save_message("s1", "user", "C")

        count = await memory_store.message_count("s1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_messages_are_session_scoped(self, memory_store):
        await memory_store.save_message("s1", "user", "Session 1")
        await memory_store.save_message("s2", "user", "Session 2")

        s1_msgs = await memory_store.get_messages("s1")
        s2_msgs = await memory_store.get_messages("s2")
        assert len(s1_msgs) == 1
        assert len(s2_msgs) == 1
        assert s1_msgs[0]["content"] == "Session 1"
        assert s2_msgs[0]["content"] == "Session 2"

    @pytest.mark.asyncio
    async def test_get_messages_limit(self, memory_store):
        for i in range(10):
            await memory_store.save_message("s1", "user", f"msg {i}")

        messages = await memory_store.get_messages("s1", limit=3)
        assert len(messages) == 3
        # Should be the most recent 3 in chronological order
        assert messages[0]["content"] == "msg 7"
        assert messages[2]["content"] == "msg 9"


# ===========================================================================
# SessionManager integration tests
# ===========================================================================


class TestSessionManagerIntegration:
    """Integration tests for SessionManager with in-memory SQLite."""

    @pytest.mark.asyncio
    async def test_create_and_get(self, session_manager):
        session = await session_manager.create_session(user_id="u1")
        assert session.user_id == "u1"
        assert session.status == "active"

        fetched = await session_manager.get_session(session.session_id)
        assert fetched is not None
        assert fetched.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, session_manager):
        result = await session_manager.get_session("does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, session_manager):
        await session_manager.create_session(user_id="u1")
        await session_manager.create_session(user_id="u1")
        await session_manager.create_session(user_id="u2")

        u1_sessions = await session_manager.list_sessions(user_id="u1")
        assert len(u1_sessions) == 2

        u2_sessions = await session_manager.list_sessions(user_id="u2")
        assert len(u2_sessions) == 1

    @pytest.mark.asyncio
    async def test_delete_session(self, session_manager):
        session = await session_manager.create_session(user_id="u1")
        deleted = await session_manager.delete_session(session.session_id)
        assert deleted is True

        fetched = await session_manager.get_session(session.session_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, session_manager):
        deleted = await session_manager.delete_session("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_update_token_count(self, session_manager):
        session = await session_manager.create_session(user_id="u1")

        await session_manager.update_token_count(
            session.session_id, tokens=100, message_delta=2
        )

        updated = await session_manager.get_session(session.session_id)
        assert updated is not None
        assert updated.total_tokens == 100
        assert updated.message_count == 2

    @pytest.mark.asyncio
    async def test_update_token_count_nonexistent(self, session_manager):
        with pytest.raises(SessionNotFoundError):
            await session_manager.update_token_count("nonexistent", tokens=10)

    @pytest.mark.asyncio
    async def test_close_session(self, session_manager):
        session = await session_manager.create_session(user_id="u1")
        closed = await session_manager.close_session(session.session_id)
        assert closed is True

        updated = await session_manager.get_session(session.session_id)
        assert updated is not None
        assert updated.status == "closed"


# ===========================================================================
# Agent API route tests (via TestClient)
# ===========================================================================


class TestAgentRoutes:
    """Tests for the agent API endpoints using FastAPI TestClient."""

    @pytest.fixture
    def app(self):
        """Create a test app with mocked runtime."""
        from isg_agent.app import create_app
        return create_app()

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "version" in data
        assert "database" in data

    @pytest.mark.asyncio
    async def test_create_session_requires_auth(self, client):
        resp = await client.post("/api/v1/sessions", json={})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_sessions_requires_auth(self, client):
        resp = await client.get("/api/v1/sessions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_send_message_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/sessions/fake-id/message",
            json={"content": "Hello"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_session_requires_auth(self, client):
        resp = await client.delete("/api/v1/sessions/fake-id")
        assert resp.status_code == 401


# ===========================================================================
# Auth route tests
# ===========================================================================


class TestAuthRoutes:
    """Tests for auth endpoints: register and login.

    The auth module uses a module-level ``_db_path`` variable set by
    ``_set_auth_config()``.  Each test gets its own temporary file-based
    SQLite database so that multiple ``aiosqlite.connect()`` calls within
    a single request can see the same ``users`` table (plain ``:memory:``
    would create a separate database on each connect call).
    """

    @pytest.fixture(autouse=True)
    def _configure_auth(self, tmp_path):
        """Pre-configure the auth module with a temp-file DB and test secret."""
        from isg_agent.api.routes.auth import _set_auth_config
        db_file = str(tmp_path / "test_auth.db")
        _set_auth_config(db_path=db_file, secret_key="test-secret-for-auth-routes")

    @pytest.fixture
    def app(self):
        from isg_agent.app import create_app
        return create_app()

    @pytest.fixture
    def client(self, app):
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    @pytest.mark.asyncio
    async def test_register_success(self, client):
        resp = await client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "SecurePass123!", "terms_accepted": True},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        resp = await client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "short"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client):
        resp = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "doesnotmatter"},
        )
        assert resp.status_code == 401


# ===========================================================================
# Auth token utility tests
# ===========================================================================


class TestAuthTokenUtils:
    """Tests for JWT token creation and verification."""

    def test_create_and_verify_token(self):
        from isg_agent.api.routes.auth import _create_token, verify_token

        token = _create_token(
            user_id="u1",
            email="test@example.com",
            secret_key="test-secret",
        )
        payload = verify_token(token, "test-secret")
        assert payload is not None
        assert payload["sub"] == "u1"
        assert payload["email"] == "test@example.com"

    def test_verify_expired_token(self):
        from isg_agent.api.routes.auth import _create_token, verify_token

        token = _create_token(
            user_id="u1",
            email="test@example.com",
            secret_key="test-secret",
            expires_in=-1,  # Already expired
        )
        payload = verify_token(token, "test-secret")
        assert payload is None

    def test_verify_wrong_secret(self):
        from isg_agent.api.routes.auth import _create_token, verify_token

        token = _create_token(
            user_id="u1",
            email="test@example.com",
            secret_key="correct-secret",
        )
        payload = verify_token(token, "wrong-secret")
        assert payload is None

    def test_verify_malformed_token(self):
        from isg_agent.api.routes.auth import verify_token

        assert verify_token("not.a.valid.token", "secret") is None
        assert verify_token("", "secret") is None
        assert verify_token("onlyonepart", "secret") is None

    def test_password_hashing(self):
        from isg_agent.api.routes.auth import _hash_password, _verify_password

        pw_hash, salt = _hash_password("mypassword123")
        assert _verify_password("mypassword123", pw_hash, salt) is True
        assert _verify_password("wrongpassword", pw_hash, salt) is False

    def test_password_hash_deterministic_with_salt(self):
        from isg_agent.api.routes.auth import _hash_password

        hash1, salt = _hash_password("test")
        hash2, _ = _hash_password("test", salt)
        assert hash1 == hash2

    def test_password_hash_different_salts(self):
        from isg_agent.api.routes.auth import _hash_password

        hash1, salt1 = _hash_password("test")
        hash2, salt2 = _hash_password("test")
        # Different salts should produce different hashes (with high probability)
        if salt1 != salt2:
            assert hash1 != hash2


# ===========================================================================
# AgentConfig tests
# ===========================================================================


class TestAgentConfig:
    """Tests for AgentConfig defaults and overrides."""

    def test_defaults(self):
        config = AgentConfig()
        assert "helpful" in config.system_prompt.lower()
        assert config.max_history_messages == 20
        assert config.temperature == 0.7
        assert config.max_tokens == 1024
        assert config.default_model is None

    def test_custom_values(self):
        config = AgentConfig(
            system_prompt="Custom prompt",
            max_history_messages=10,
            temperature=0.5,
            max_tokens=512,
            default_model="gpt-4",
        )
        assert config.system_prompt == "Custom prompt"
        assert config.max_history_messages == 10
        assert config.temperature == 0.5
        assert config.max_tokens == 512
        assert config.default_model == "gpt-4"


# ===========================================================================
# MockProvider tests
# ===========================================================================


class TestMockProvider:
    """Tests to verify our MockProvider works correctly as a test double."""

    @pytest.mark.asyncio
    async def test_complete(self):
        provider = MockProvider(response_content="Test response")
        messages = [LLMMessage(role="user", content="Hi")]
        resp = await provider.complete(messages)
        assert resp.content == "Test response"
        assert resp.model == "mock-model"
        assert resp.input_tokens == 50
        assert resp.output_tokens == 20
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_stream(self):
        provider = MockProvider(response_content="Hello world test")
        messages = [LLMMessage(role="user", content="Hi")]
        chunks = []
        async for chunk in provider.stream(messages):
            chunks.append(chunk)
        assert len(chunks) == 3
        assert "".join(chunks).strip() == "Hello world test"

    @pytest.mark.asyncio
    async def test_failing_provider(self):
        provider = FailingProvider()
        messages = [LLMMessage(role="user", content="Hi")]
        with pytest.raises(ProviderError):
            await provider.complete(messages)


# ===========================================================================
# LLMMessage / LLMResponse tests
# ===========================================================================


class TestLLMDataModels:
    """Tests for LLMMessage and LLMResponse dataclasses."""

    def test_llm_message(self):
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_llm_response(self):
        resp = LLMResponse(
            content="Hi",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=5,
            finish_reason="stop",
        )
        assert resp.content == "Hi"
        assert resp.model == "gpt-4o"
        assert resp.extra == {}

    def test_llm_response_with_extra(self):
        resp = LLMResponse(
            content="Hi",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=5,
            finish_reason="stop",
            extra={"temperature": 0.7},
        )
        assert resp.extra["temperature"] == 0.7

    def test_provider_error(self):
        err = ProviderError(message="Something failed", provider="test", status_code=500)
        assert err.provider == "test"
        assert err.status_code == 500
        assert "test" in str(err)

    def test_rate_limit_error(self):
        err = RateLimitError(provider="openai", retry_after=5.0)
        assert err.provider == "openai"
        assert err.retry_after == 5.0
        assert err.status_code == 429
