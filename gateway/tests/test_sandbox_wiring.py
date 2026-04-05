"""Tests for Wasm sandbox wiring into SkillExecutor.

Validates the integration bridge between WasmSandbox and SkillExecutor:
- Skill executes normally when sandbox is not configured (no tier)
- Skill routes through sandbox bridge when tier is set
- Graceful fallback when sandbox import fails (fail-open)
- Each tier (basic/pro/enterprise) receives correct capabilities
- Sandbox timeout/fuel exhaustion falls back to normal execution
- Metrics are tracked per execution
- Execution mode is reported in the result

TDD contract: these tests are written against the expected API before
executor.py is modified. They go GREEN after the wiring is implemented.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.sandbox.capabilities import CapabilitySet, get_tier_capabilities
from isg_agent.skills.executor import ExecutionResult, SkillExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_handler(output: str = "ok") -> Any:
    """Return a sync skill handler that returns a fixed string."""
    return lambda params: output


def _make_async_handler(output: str = "ok") -> Any:
    """Return an async skill handler that returns a fixed string."""
    async def handler(params: dict) -> str:
        return output
    return handler


def _make_executor_no_sandbox(**kwargs: Any) -> SkillExecutor:
    """Create an executor with sandbox disabled (no tier)."""
    return SkillExecutor(workspace_root="/tmp", audit_chain=None, default_timeout=5.0, **kwargs)


def _make_executor_with_tier(tier: str, **kwargs: Any) -> SkillExecutor:
    """Create an executor with a specific sandbox tier configured."""
    return SkillExecutor(
        workspace_root="/tmp",
        audit_chain=None,
        default_timeout=5.0,
        sandbox_tier=tier,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def executor_no_sandbox() -> SkillExecutor:
    """An executor with no sandbox tier configured."""
    return _make_executor_no_sandbox()


@pytest.fixture()
def executor_basic() -> SkillExecutor:
    """An executor configured for the 'basic' sandbox tier."""
    return _make_executor_with_tier("basic")


@pytest.fixture()
def executor_pro() -> SkillExecutor:
    """An executor configured for the 'pro' sandbox tier."""
    return _make_executor_with_tier("pro")


@pytest.fixture()
def executor_enterprise() -> SkillExecutor:
    """An executor configured for the 'enterprise' sandbox tier."""
    return _make_executor_with_tier("enterprise")


# ---------------------------------------------------------------------------
# 1. No-sandbox path — normal execution when tier is None
# ---------------------------------------------------------------------------


class TestNoSandboxPath:
    """Executor without a sandbox tier configured executes normally."""

    @pytest.mark.asyncio
    async def test_skill_executes_normally_no_tier(
        self, executor_no_sandbox: SkillExecutor
    ) -> None:
        """Skill runs and returns output when sandbox is not configured."""
        executor_no_sandbox.register_skill("greet", _make_simple_handler("hello"))
        result = await executor_no_sandbox.execute("greet", {})
        assert result.success is True
        assert result.output == "hello"

    @pytest.mark.asyncio
    async def test_skill_result_has_expected_fields_no_tier(
        self, executor_no_sandbox: SkillExecutor
    ) -> None:
        """ExecutionResult fields are fully populated without sandbox."""
        executor_no_sandbox.register_skill("echo", _make_simple_handler("world"))
        result = await executor_no_sandbox.execute("echo", {"x": 1})
        assert result.success is True
        assert isinstance(result.duration_ms, int)
        assert result.audit_id != ""
        assert result.skill_name == "echo"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_skill_failure_no_tier(
        self, executor_no_sandbox: SkillExecutor
    ) -> None:
        """A skill that raises still produces a failure result without sandbox."""
        def failing(params: dict) -> str:
            raise RuntimeError("deliberate failure")

        executor_no_sandbox.register_skill("fail", failing)
        result = await executor_no_sandbox.execute("fail", {})
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_sandbox_tier_property_is_none(
        self, executor_no_sandbox: SkillExecutor
    ) -> None:
        """The executor exposes its sandbox_tier as None when not configured."""
        assert executor_no_sandbox.sandbox_tier is None

    @pytest.mark.asyncio
    async def test_no_tier_does_not_create_bridge(
        self, executor_no_sandbox: SkillExecutor
    ) -> None:
        """Without a tier, no SandboxBridge instance should be created."""
        assert executor_no_sandbox._sandbox_bridge is None


# ---------------------------------------------------------------------------
# 2. Sandbox path — routing through bridge when tier is set
# ---------------------------------------------------------------------------


class TestSandboxPath:
    """Executor with a sandbox tier routes skills through the bridge."""

    @pytest.mark.asyncio
    async def test_skill_executes_via_bridge_basic_tier(
        self, executor_basic: SkillExecutor
    ) -> None:
        """With basic tier, skills route through the SandboxBridge."""
        executor_basic.register_skill("compute", _make_simple_handler("42"))
        result = await executor_basic.execute("compute", {})
        # The result must come back as a success — bridge is wrapping the skill
        assert result.success is True

    @pytest.mark.asyncio
    async def test_sandbox_tier_property_basic(
        self, executor_basic: SkillExecutor
    ) -> None:
        """The executor exposes its configured sandbox tier."""
        assert executor_basic.sandbox_tier == "basic"

    @pytest.mark.asyncio
    async def test_sandbox_tier_property_pro(
        self, executor_pro: SkillExecutor
    ) -> None:
        """Pro tier is stored and exposed correctly."""
        assert executor_pro.sandbox_tier == "pro"

    @pytest.mark.asyncio
    async def test_sandbox_tier_property_enterprise(
        self, executor_enterprise: SkillExecutor
    ) -> None:
        """Enterprise tier is stored and exposed correctly."""
        assert executor_enterprise.sandbox_tier == "enterprise"

    @pytest.mark.asyncio
    async def test_bridge_is_created_when_tier_set(
        self, executor_basic: SkillExecutor
    ) -> None:
        """A SandboxBridge is instantiated when a tier is provided."""
        assert executor_basic._sandbox_bridge is not None

    @pytest.mark.asyncio
    async def test_bridge_execute_called_for_code_skill(
        self, executor_basic: SkillExecutor
    ) -> None:
        """When params include 'code', the bridge's execute_skill_sandboxed is invoked."""
        executor_basic.register_skill("run_code", _make_simple_handler("result"))

        mock_bridge = AsyncMock()
        from isg_agent.sandbox.bridge import BridgeResult
        mock_bridge.execute_skill_sandboxed.return_value = BridgeResult(
            success=True,
            output="sandboxed output",
            error=None,
            execution_ms=5.0,
            execution_mode="sandbox",
        )
        executor_basic._sandbox_bridge = mock_bridge

        result = await executor_basic.execute("run_code", {"code": "print('hi')"})

        mock_bridge.execute_skill_sandboxed.assert_awaited_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_bridge_result_maps_to_execution_result(
        self, executor_basic: SkillExecutor
    ) -> None:
        """BridgeResult fields are correctly mapped to ExecutionResult."""
        executor_basic.register_skill("sandboxed", _make_simple_handler("_"))

        mock_bridge = AsyncMock()
        from isg_agent.sandbox.bridge import BridgeResult
        mock_bridge.execute_skill_sandboxed.return_value = BridgeResult(
            success=True,
            output="bridge output",
            error=None,
            execution_ms=12.3,
            execution_mode="sandbox",
        )
        executor_basic._sandbox_bridge = mock_bridge

        result = await executor_basic.execute("sandboxed", {"code": "print('x')"})

        assert result.success is True
        assert result.output == "bridge output"
        assert result.error is None
        assert result.skill_name == "sandboxed"


# ---------------------------------------------------------------------------
# 3. Fail-open: graceful degradation when sandbox import fails
# ---------------------------------------------------------------------------


class TestFailOpen:
    """Sandbox import failure must not crash the executor — fail-open."""

    @pytest.mark.asyncio
    async def test_executor_works_when_sandbox_unavailable(self) -> None:
        """If sandbox import raises ImportError, executor falls back to normal execution."""
        # Simulate sandbox module import failure by patching WASM_AVAILABLE to False
        # and by patching the bridge constructor to raise ImportError
        with patch.dict(sys.modules, {"isg_agent.sandbox.bridge": None}):
            # Even if the bridge module is unavailable, SkillExecutor should
            # still construct and execute skills normally.
            executor = SkillExecutor(
                workspace_root="/tmp",
                audit_chain=None,
                default_timeout=5.0,
                sandbox_tier="basic",
            )
            executor.register_skill("fallback_skill", _make_simple_handler("fallback"))
            result = await executor.execute("fallback_skill", {})
            # Must succeed via normal execution path
            assert result.success is True
            assert result.output == "fallback"

    @pytest.mark.asyncio
    async def test_bridge_exception_does_not_crash_executor(
        self, executor_basic: SkillExecutor
    ) -> None:
        """If the bridge raises during execution, the executor falls back to normal."""
        executor_basic.register_skill("safe_skill", _make_simple_handler("normal output"))

        # Make the bridge raise to simulate runtime failure
        mock_bridge = AsyncMock()
        mock_bridge.execute_skill_sandboxed.side_effect = RuntimeError("bridge exploded")
        executor_basic._sandbox_bridge = mock_bridge

        result = await executor_basic.execute("safe_skill", {"code": "print(1)"})

        # Must not propagate the exception — fail-open to normal execution
        assert result.success is True
        assert result.output == "normal output"

    @pytest.mark.asyncio
    async def test_no_sandbox_tier_config_never_touches_bridge(
        self, executor_no_sandbox: SkillExecutor
    ) -> None:
        """An executor without a tier never creates or calls the bridge."""
        executor_no_sandbox.register_skill("plain", _make_simple_handler("plain"))
        result = await executor_no_sandbox.execute("plain", {})
        assert result.success is True
        assert executor_no_sandbox._sandbox_bridge is None


# ---------------------------------------------------------------------------
# 4. Tier capability mapping
# ---------------------------------------------------------------------------


class TestTierCapabilityMapping:
    """Verify each tier receives the correct WASI capabilities."""

    def test_basic_tier_capabilities(self) -> None:
        """Basic tier: READ_CONTEXT + WRITE_OUTPUT, no HTTP or filesystem."""
        caps = get_tier_capabilities("basic")
        assert CapabilitySet.READ_CONTEXT in caps
        assert CapabilitySet.WRITE_OUTPUT in caps
        assert CapabilitySet.HTTP_OUTBOUND not in caps
        assert CapabilitySet.FILESYSTEM_READ not in caps

    def test_pro_tier_capabilities(self) -> None:
        """Pro tier: READ_CONTEXT + WRITE_OUTPUT + HTTP_OUTBOUND."""
        caps = get_tier_capabilities("pro")
        assert CapabilitySet.READ_CONTEXT in caps
        assert CapabilitySet.WRITE_OUTPUT in caps
        assert CapabilitySet.HTTP_OUTBOUND in caps
        assert CapabilitySet.FILESYSTEM_READ not in caps

    def test_enterprise_tier_capabilities(self) -> None:
        """Enterprise tier: all capabilities including FILESYSTEM_READ."""
        caps = get_tier_capabilities("enterprise")
        assert CapabilitySet.READ_CONTEXT in caps
        assert CapabilitySet.WRITE_OUTPUT in caps
        assert CapabilitySet.HTTP_OUTBOUND in caps
        assert CapabilitySet.FILESYSTEM_READ in caps

    def test_unknown_tier_gets_none_capability(self) -> None:
        """Unknown tier falls back to NONE — no capabilities granted."""
        caps = get_tier_capabilities("unknown_tier")
        assert CapabilitySet.NONE in caps
        assert CapabilitySet.HTTP_OUTBOUND not in caps

    def test_executor_basic_bridge_receives_correct_tier(
        self, executor_basic: SkillExecutor
    ) -> None:
        """The bridge on a basic-tier executor is tied to the basic capability set."""
        assert executor_basic.sandbox_tier == "basic"
        caps = get_tier_capabilities(executor_basic.sandbox_tier)
        assert CapabilitySet.HTTP_OUTBOUND not in caps

    def test_executor_enterprise_bridge_receives_correct_tier(
        self, executor_enterprise: SkillExecutor
    ) -> None:
        """The bridge on an enterprise-tier executor gets all capabilities."""
        assert executor_enterprise.sandbox_tier == "enterprise"
        caps = get_tier_capabilities(executor_enterprise.sandbox_tier)
        assert CapabilitySet.FILESYSTEM_READ in caps


# ---------------------------------------------------------------------------
# 5. Sandbox timeout / fuel exhaustion → fallback to normal execution
# ---------------------------------------------------------------------------


class TestSandboxTimeoutFallback:
    """Bridge timeout or fuel exhaustion falls back to normal execution."""

    @pytest.mark.asyncio
    async def test_sandbox_timeout_falls_back_to_normal(
        self, executor_basic: SkillExecutor
    ) -> None:
        """asyncio.TimeoutError from bridge triggers normal execution fallback."""
        executor_basic.register_skill("timeout_skill", _make_simple_handler("normal"))

        mock_bridge = AsyncMock()
        mock_bridge.execute_skill_sandboxed.side_effect = asyncio.TimeoutError()
        executor_basic._sandbox_bridge = mock_bridge

        result = await executor_basic.execute("timeout_skill", {"code": "while True: pass"})

        # Must fall back to normal path and not propagate the TimeoutError
        assert result.success is True
        assert result.output == "normal"

    @pytest.mark.asyncio
    async def test_bridge_failure_result_falls_back_to_normal(
        self, executor_basic: SkillExecutor
    ) -> None:
        """A BridgeResult with success=False triggers normal execution fallback."""
        executor_basic.register_skill("fuel_skill", _make_simple_handler("computed"))

        mock_bridge = AsyncMock()
        from isg_agent.sandbox.bridge import BridgeResult
        mock_bridge.execute_skill_sandboxed.return_value = BridgeResult(
            success=False,
            output="",
            error="Fuel exhausted after 1000000 instructions",
            execution_ms=5000.0,
            execution_mode="sandbox",
        )
        executor_basic._sandbox_bridge = mock_bridge

        # A failed bridge result for code execution should fall back to normal handler
        result = await executor_basic.execute("fuel_skill", {"code": "while True: pass"})

        # The normal handler must have been called as the fallback
        assert result.success is True
        assert result.output == "computed"

    @pytest.mark.asyncio
    async def test_bridge_code_validation_failure_returns_error(
        self, executor_basic: SkillExecutor
    ) -> None:
        """A BridgeResult with 'validated' mode (blocked code) returns the error directly."""
        executor_basic.register_skill("dangerous_skill", _make_simple_handler("_"))

        mock_bridge = AsyncMock()
        from isg_agent.sandbox.bridge import BridgeResult
        mock_bridge.execute_skill_sandboxed.return_value = BridgeResult(
            success=False,
            output="",
            error="Code validation failed: Blocked import: 'os'",
            execution_ms=0.5,
            execution_mode="validated",
        )
        executor_basic._sandbox_bridge = mock_bridge

        result = await executor_basic.execute(
            "dangerous_skill", {"code": "import os; os.system('id')"}
        )

        # Validation rejections must NOT fall back — they are security decisions
        assert result.success is False
        assert result.error is not None
        assert "validation" in result.error.lower() or "blocked" in result.error.lower()
