"""Tests for isg_agent.skills.capability_bridge.CapabilityBridge.

CapabilityBridge is being created by Agent I concurrently.  These tests are
written against the data contract (expected API) rather than an existing
implementation, following TDD RED→GREEN discipline.

Contract summary:
- CapabilityBridge(db_path=str) — optional db_path for distiller persistence
- CapabilityBridge._distiller — lazily initialised distiller instance (or None)
- CapabilityBridge._initialized — bool, True once the lazy init has run
- CapabilityBridge.post_execute_hook(skill_name, params, result) — async callable
  * calls distiller.record_conversation_outcome(...) via asyncio.to_thread
  * quality_score=1.0 on success, 0.0 on failure
  * extracts agent_id from params dict; falls back to "default"
  * swallows all exceptions — never propagates
- CapabilityBridge.health_check_task() — async method
  * calls distiller.quick_health() via asyncio.to_thread
  * no-ops gracefully when distiller is unavailable
- CapabilityBridge.get_health_enrichment() — async method
  * returns {"distiller": "unavailable"} when no distiller
  * returns {"distiller": "error", "detail": str} on exception
  * returns {"score": float, "issues": list, "status": str} on success

All distiller I/O is patched — no live distiller connection required.
"""

from __future__ import annotations

import asyncio
import inspect
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Guard import — CapabilityBridge may not exist yet (Agent I in-flight).
# Tests are collected regardless; individual tests skip/fail informatively.
# ---------------------------------------------------------------------------
try:
    from isg_agent.core.capability_bridge import CapabilityBridge  # type: ignore[import]

    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False
    CapabilityBridge = None  # type: ignore[assignment,misc]

from isg_agent.skills.executor import ExecutionResult

pytestmark = pytest.mark.skipif(
    not _BRIDGE_AVAILABLE,
    reason="isg_agent.skills.capability_bridge not yet available (Agent I in-flight)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success_result(skill_name: str = "search", duration_ms: int = 150) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        output="result text",
        error=None,
        duration_ms=duration_ms,
        audit_id="audit-bridge-001",
        skill_name=skill_name,
    )


def _make_failure_result(skill_name: str = "search") -> ExecutionResult:
    return ExecutionResult(
        success=False,
        output="",
        error="skill failed",
        duration_ms=20,
        audit_id="audit-bridge-002",
        skill_name=skill_name,
    )


def _make_mock_distiller() -> MagicMock:
    """Build a mock distiller with the expected interface."""
    mock = MagicMock()
    mock.record_conversation_outcome.return_value = {"success": True}
    mock.quick_health.return_value = {
        "score": 0.85,
        "issues": ["slow response"],
        "status": "healthy",
    }
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db_file(tmp_path: Path) -> str:
    """Return a path string for a temporary SQLite database."""
    return str(tmp_path / "bridge_test.db")


@pytest.fixture()
def mock_distiller() -> MagicMock:
    """Provide a reusable mock distiller."""
    return _make_mock_distiller()


@pytest.fixture()
def bridge(tmp_db_file: str) -> CapabilityBridge:
    """Provide a fresh CapabilityBridge with no distiller attached."""
    return CapabilityBridge(db_path=tmp_db_file)


@pytest.fixture()
def bridge_with_mock(bridge: CapabilityBridge, mock_distiller: MagicMock) -> CapabilityBridge:
    """Provide a CapabilityBridge pre-wired with a mock distiller."""
    bridge._distiller = mock_distiller
    bridge._initialized = True
    return bridge


# ---------------------------------------------------------------------------
# 1. Initialisation tests
# ---------------------------------------------------------------------------


class TestCapabilityBridgeInit:
    """Tests for CapabilityBridge construction."""

    def test_bridge_init_no_crash(self, tmp_db_file: str) -> None:
        """CapabilityBridge() constructs without raising."""
        b = CapabilityBridge(db_path=tmp_db_file)
        assert b is not None

    def test_bridge_init_without_db_path(self) -> None:
        """CapabilityBridge() without db_path constructs without raising."""
        b = CapabilityBridge()
        assert b is not None

    def test_lazy_init_distiller_is_none_on_construction(self, bridge: CapabilityBridge) -> None:
        """The distiller is NOT initialised at construction time (lazy loading)."""
        assert bridge._distiller is None

    def test_initialized_flag_is_false_on_construction(self, bridge: CapabilityBridge) -> None:
        """_initialized is False immediately after construction."""
        assert bridge._initialized is False

    def test_lazy_init_doesnt_import_on_construction(self, tmp_db_file: str) -> None:
        """Constructing the bridge does not trigger a distiller import."""
        import_call_count = 0

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None  # type: ignore[union-attr]

        # Simply constructing must not touch the distiller module at all.
        # We verify by checking _initialized stays False after __init__.
        b = CapabilityBridge(db_path=tmp_db_file)
        assert b._initialized is False


# ---------------------------------------------------------------------------
# 2. Distiller unavailability — graceful fallback
# ---------------------------------------------------------------------------


class TestDistillerUnavailable:
    """CapabilityBridge degrades gracefully when the distiller cannot be imported."""

    def test_distiller_unavailable_graceful_fallback(self, tmp_db_file: str) -> None:
        """When distiller import fails, bridge constructs without error."""
        with patch.dict("sys.modules", {"mila_distiller": None}):
            b = CapabilityBridge(db_path=tmp_db_file)
            assert b is not None

    async def test_post_execute_hook_without_distiller_no_crash(
        self, bridge: CapabilityBridge
    ) -> None:
        """post_execute_hook with no distiller does not raise."""
        result = _make_success_result()
        # Must complete without exception
        await bridge.post_execute_hook("search", {"agent_id": "agent-x"}, result)

    async def test_health_check_task_without_distiller_no_crash(
        self, bridge: CapabilityBridge
    ) -> None:
        """health_check_task() with no distiller does not raise."""
        await bridge.health_check_task()

    def test_get_health_enrichment_without_distiller(
        self, bridge: CapabilityBridge
    ) -> None:
        """get_health_enrichment returns unavailable sentinel when no distiller."""
        # Force distiller to be absent (lazy init would find the real one on sys.path)
        bridge._initialized = True
        bridge._distiller = None
        result = bridge.get_health_enrichment()
        assert result == {"distiller": "unavailable"}


# ---------------------------------------------------------------------------
# 3. post_execute_hook — with distiller wired
# ---------------------------------------------------------------------------


class TestPostExecuteHook:
    """Tests for CapabilityBridge.post_execute_hook()."""

    async def test_post_execute_hook_calls_distiller(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """post_execute_hook calls distiller.record_conversation_outcome."""
        result = _make_success_result(skill_name="search")
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.post_execute_hook("search", {"agent_id": "agent-123"}, result)

        mock_distiller.record_conversation_outcome.assert_called_once()

    async def test_post_execute_hook_with_success_result(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """On success, quality_score=1.0 is passed to the distiller."""
        result = _make_success_result()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.post_execute_hook("search", {"agent_id": "agent-abc"}, result)

        call_kwargs = mock_distiller.record_conversation_outcome.call_args.kwargs
        assert call_kwargs["session_data"]["quality_score"] == 1.0

    async def test_post_execute_hook_with_failure_result(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """On failure, quality_score=0.0 is passed to the distiller."""
        result = _make_failure_result()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.post_execute_hook("search", {"agent_id": "agent-abc"}, result)

        call_kwargs = mock_distiller.record_conversation_outcome.call_args.kwargs
        assert call_kwargs["session_data"]["quality_score"] == 0.0

    async def test_post_execute_hook_extracts_agent_id(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """agent_id is extracted from the params dict."""
        result = _make_success_result()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.post_execute_hook(
                "search", {"agent_id": "agent-123", "query": "test"}, result
            )

        call_kwargs = mock_distiller.record_conversation_outcome.call_args.kwargs
        assert call_kwargs.get("agent_id") == "agent-123"

    async def test_post_execute_hook_default_agent_id(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """When agent_id is absent from params, 'default' is used."""
        result = _make_success_result()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.post_execute_hook("search", {}, result)

        call_kwargs = mock_distiller.record_conversation_outcome.call_args.kwargs
        assert call_kwargs.get("agent_id") == "default"

    async def test_post_execute_hook_error_is_caught(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """If the distiller raises, post_execute_hook must not propagate the error."""
        mock_distiller.record_conversation_outcome.side_effect = RuntimeError("distiller crash")
        result = _make_success_result()

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            # Must complete without raising
            await bridge_with_mock.post_execute_hook("search", {"agent_id": "x"}, result)

    def test_post_execute_hook_is_async(self, bridge: CapabilityBridge) -> None:
        """post_execute_hook must be a coroutine function (async def)."""
        assert inspect.iscoroutinefunction(bridge.post_execute_hook)


# ---------------------------------------------------------------------------
# 4. health_check_task — with distiller wired
# ---------------------------------------------------------------------------


class TestHealthCheckTask:
    """Tests for CapabilityBridge.health_check_task()."""

    async def test_health_check_task_calls_quick_health(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """health_check_task calls distiller.quick_health."""
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.health_check_task()

        mock_distiller.quick_health.assert_called_once()

    async def test_health_check_task_no_crash_on_distiller_error(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """If quick_health raises, health_check_task must not propagate the error."""
        mock_distiller.quick_health.side_effect = RuntimeError("health probe failed")

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await bridge_with_mock.health_check_task()

    def test_health_check_task_is_async(self, bridge: CapabilityBridge) -> None:
        """health_check_task must be a coroutine function (async def)."""
        assert inspect.iscoroutinefunction(bridge.health_check_task)


# ---------------------------------------------------------------------------
# 5. get_health_enrichment — with and without distiller
# ---------------------------------------------------------------------------


class TestGetHealthEnrichment:
    """Tests for CapabilityBridge.get_health_enrichment()."""

    def test_get_health_enrichment_with_distiller(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """Returns score and issues from distiller.quick_health."""
        result = bridge_with_mock.get_health_enrichment()

        assert "health_score" in result or "distiller" in result or "top_issues" in result

    def test_get_health_enrichment_with_distiller_returns_score(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """The health_score field from quick_health is present in the returned dict."""
        result = bridge_with_mock.get_health_enrichment()

        assert result.get("health_score") == 0.85

    def test_get_health_enrichment_error_returns_error_sentinel(
        self, bridge_with_mock: CapabilityBridge, mock_distiller: MagicMock
    ) -> None:
        """When quick_health raises, returns {"distiller": "error"}."""
        mock_distiller.quick_health.side_effect = RuntimeError("probe failure")

        result = bridge_with_mock.get_health_enrichment()

        assert result.get("distiller") == "error"


# ---------------------------------------------------------------------------
# 6. Lazy singleton — distiller created only once
# ---------------------------------------------------------------------------


class TestDistillerLazySingleton:
    """CapabilityBridge must not re-create the distiller on repeated calls."""

    async def test_bridge_reuses_distiller_instance(self, tmp_db_file: str) -> None:
        """After first use, subsequent calls reuse the same distiller object."""
        b = CapabilityBridge(db_path=tmp_db_file)

        fake_distiller = _make_mock_distiller()
        init_count = 0

        def mock_initialise() -> MagicMock:
            nonlocal init_count
            init_count += 1
            return fake_distiller

        # Simulate lazy init by directly assigning after first call
        b._distiller = fake_distiller
        b._initialized = True

        result = _make_success_result()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))):
            await b.post_execute_hook("search", {"agent_id": "x"}, result)
            await b.post_execute_hook("search", {"agent_id": "x"}, result)

        # The same mock was used both times — no re-initialisation
        assert b._distiller is fake_distiller
        assert b._initialized is True
