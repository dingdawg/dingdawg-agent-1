"""Tests for SkillExecutor post-execute hook chain.

Covers the hook registration API that Agent I is adding to executor.py:
- add_post_execute_hook (multi-hook list API)
- set_post_execute_hook (backward-compat single-hook API)
- Hook dispatch: order, success-only guard, exception isolation, async/sync support
- Hook removal API

The existing set_post_execute_hook path already exists in executor.py.
The multi-hook list additions (add_post_execute_hook, remove_post_execute_hook,
_post_execute_hooks list) are written by Agent I concurrently.  Tests are written
against the expected API contract; they will go GREEN once Agent I finishes wiring.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from isg_agent.skills.executor import ExecutionResult, SkillExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success_result(skill_name: str = "test-skill", duration_ms: int = 10) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        output="ok",
        error=None,
        duration_ms=duration_ms,
        audit_id="audit-000",
        skill_name=skill_name,
    )


def _make_failure_result(skill_name: str = "test-skill") -> ExecutionResult:
    return ExecutionResult(
        success=False,
        output="",
        error="something went wrong",
        duration_ms=5,
        audit_id="audit-001",
        skill_name=skill_name,
    )


def _make_executor() -> SkillExecutor:
    """Create a minimal SkillExecutor with no dependencies."""
    return SkillExecutor(workspace_root="/tmp", audit_chain=None, default_timeout=5.0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def executor() -> SkillExecutor:
    """Provide a fresh SkillExecutor for each test."""
    return _make_executor()


# ---------------------------------------------------------------------------
# 1. Hook registration — add_post_execute_hook
# ---------------------------------------------------------------------------


class TestAddPostExecuteHook:
    """Tests for the multi-hook list registration API."""

    def test_add_post_execute_hook_accepts_callable(self, executor: SkillExecutor) -> None:
        """add_post_execute_hook stores the callable in the hook list."""
        hook = AsyncMock()
        executor.add_post_execute_hook(hook)

        assert hook in executor._post_execute_hooks

    def test_add_multiple_hooks_both_stored(self, executor: SkillExecutor) -> None:
        """Adding two hooks stores both in the list."""
        hook_a = AsyncMock()
        hook_b = AsyncMock()
        executor.add_post_execute_hook(hook_a)
        executor.add_post_execute_hook(hook_b)

        assert hook_a in executor._post_execute_hooks
        assert hook_b in executor._post_execute_hooks
        assert len(executor._post_execute_hooks) == 2

    def test_add_multiple_hooks_preserves_order(self, executor: SkillExecutor) -> None:
        """Hooks are stored in insertion order."""
        hooks = [AsyncMock() for _ in range(3)]
        for h in hooks:
            executor.add_post_execute_hook(h)

        assert executor._post_execute_hooks == hooks

    def test_hooks_list_empty_on_fresh_executor(self, executor: SkillExecutor) -> None:
        """A fresh executor starts with an empty hook list."""
        assert executor._post_execute_hooks == []


# ---------------------------------------------------------------------------
# 2. Backward-compat: set_post_execute_hook
# ---------------------------------------------------------------------------


class TestSetPostExecuteHookBackwardCompat:
    """set_post_execute_hook must still work after the multi-hook refactor."""

    def test_set_post_execute_hook_backward_compat_single(
        self, executor: SkillExecutor
    ) -> None:
        """set_post_execute_hook replaces any previously registered hooks with one."""
        first = AsyncMock()
        second = AsyncMock()
        executor.add_post_execute_hook(first)
        executor.set_post_execute_hook(second)

        # Only the new hook should remain
        assert len(executor._post_execute_hooks) == 1
        assert second in executor._post_execute_hooks
        assert first not in executor._post_execute_hooks

    def test_set_post_execute_hook_on_empty_executor(
        self, executor: SkillExecutor
    ) -> None:
        """set_post_execute_hook on a fresh executor registers exactly one hook."""
        hook = AsyncMock()
        executor.set_post_execute_hook(hook)

        assert len(executor._post_execute_hooks) == 1
        assert hook in executor._post_execute_hooks

    def test_set_post_execute_hook_replaces_multiple_hooks(
        self, executor: SkillExecutor
    ) -> None:
        """set_post_execute_hook clears all prior hooks, leaving only the new one."""
        for _ in range(5):
            executor.add_post_execute_hook(AsyncMock())
        replacement = AsyncMock()
        executor.set_post_execute_hook(replacement)

        assert executor._post_execute_hooks == [replacement]


# ---------------------------------------------------------------------------
# 3. Hook dispatch behaviour during execute()
# ---------------------------------------------------------------------------


class TestHookDispatchOnExecute:
    """Tests that hooks are called correctly during execute()."""

    async def test_hooks_fire_in_order_on_success(self, executor: SkillExecutor) -> None:
        """Hooks fire in insertion order after a successful skill execution."""
        call_order: list[str] = []

        async def hook_first(skill_name: str, params: dict, result: ExecutionResult) -> None:
            call_order.append("first")

        async def hook_second(skill_name: str, params: dict, result: ExecutionResult) -> None:
            call_order.append("second")

        executor.add_post_execute_hook(hook_first)
        executor.add_post_execute_hook(hook_second)
        executor.register_skill("noop", lambda p: "done")

        await executor.execute("noop", {})

        assert call_order == ["first", "second"]

    async def test_hook_receives_correct_args(self, executor: SkillExecutor) -> None:
        """Hook is called with (skill_name, params, result)."""
        received: list[tuple] = []

        async def capturing_hook(
            skill_name: str, params: dict, result: ExecutionResult
        ) -> None:
            received.append((skill_name, params, result))

        executor.add_post_execute_hook(capturing_hook)
        executor.register_skill("echo", lambda p: p.get("msg", ""))

        await executor.execute("echo", {"msg": "hello"})

        assert len(received) == 1
        skill_name, params, result = received[0]
        assert skill_name == "echo"
        assert params == {"msg": "hello"}
        assert result.success is True
        assert result.skill_name == "echo"

    async def test_hooks_only_fire_on_success(self, executor: SkillExecutor) -> None:
        """Hooks must NOT fire when skill execution fails."""
        hook = AsyncMock()
        executor.add_post_execute_hook(hook)

        # Execute a skill that is not registered — produces a failure result
        result = await executor.execute("nonexistent-skill", {})

        assert result.success is False
        hook.assert_not_awaited()

    async def test_hooks_only_fire_on_success_runtime_exception(
        self, executor: SkillExecutor
    ) -> None:
        """Hooks must NOT fire when a skill raises an exception."""
        hook = AsyncMock()
        executor.add_post_execute_hook(hook)

        def exploding_skill(params: dict) -> str:
            raise RuntimeError("boom")

        executor.register_skill("explode", exploding_skill)
        result = await executor.execute("explode", {})

        assert result.success is False
        hook.assert_not_awaited()

    async def test_first_hook_exception_does_not_block_second(
        self, executor: SkillExecutor
    ) -> None:
        """If the first hook raises, the second hook still runs."""
        second_hook = AsyncMock()

        async def failing_hook(
            skill_name: str, params: dict, result: ExecutionResult
        ) -> None:
            raise ValueError("hook error")

        executor.add_post_execute_hook(failing_hook)
        executor.add_post_execute_hook(second_hook)
        executor.register_skill("noop", lambda p: "ok")

        await executor.execute("noop", {})

        second_hook.assert_awaited_once()

    async def test_hook_exception_is_caught_not_raised(
        self, executor: SkillExecutor
    ) -> None:
        """A hook that raises must not propagate the exception to the caller."""
        async def always_raises(
            skill_name: str, params: dict, result: ExecutionResult
        ) -> None:
            raise RuntimeError("hook blew up")

        executor.add_post_execute_hook(always_raises)
        executor.register_skill("safe", lambda p: "safe result")

        # This must not raise — the result is still a success
        result = await executor.execute("safe", {})
        assert result.success is True
        assert result.output == "safe result"

    async def test_hook_exception_is_logged(
        self, executor: SkillExecutor, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Hook exceptions must be logged (not silently swallowed)."""
        async def bad_hook(
            skill_name: str, params: dict, result: ExecutionResult
        ) -> None:
            raise ValueError("logged error")

        executor.add_post_execute_hook(bad_hook)
        executor.register_skill("log-test", lambda p: "ok")

        with caplog.at_level(logging.WARNING, logger="isg_agent.skills.executor"):
            await executor.execute("log-test", {})

        # A warning or error about the hook failure should have been emitted
        assert any(
            "hook" in record.message.lower() or "log-test" in record.message.lower()
            for record in caplog.records
        )

    async def test_async_hook_is_awaited(self, executor: SkillExecutor) -> None:
        """Coroutine hooks are awaited properly (not just called)."""
        hook = AsyncMock()
        executor.add_post_execute_hook(hook)
        executor.register_skill("ping", lambda p: "pong")

        await executor.execute("ping", {})

        hook.assert_awaited_once()

    async def test_sync_hook_works(self, executor: SkillExecutor) -> None:
        """Regular (non-async) functions are also accepted as hooks."""
        called_with: list[tuple] = []

        def sync_hook(skill_name: str, params: dict, result: ExecutionResult) -> None:
            called_with.append((skill_name, params))

        executor.add_post_execute_hook(sync_hook)
        executor.register_skill("sync-skill", lambda p: "done")

        await executor.execute("sync-skill", {"key": "value"})

        assert len(called_with) == 1
        assert called_with[0] == ("sync-skill", {"key": "value"})

    async def test_empty_hooks_list_no_error(self, executor: SkillExecutor) -> None:
        """An executor with no hooks registered executes without errors."""
        executor.register_skill("plain", lambda p: "plain result")
        result = await executor.execute("plain", {})

        assert result.success is True
        assert result.output == "plain result"


# ---------------------------------------------------------------------------
# 4. Hook removal API
# ---------------------------------------------------------------------------


class TestRemovePostExecuteHook:
    """Tests for the remove_post_execute_hook API."""

    def test_remove_hook_returns_true(self, executor: SkillExecutor) -> None:
        """Removing a registered hook returns True."""
        hook = AsyncMock()
        executor.add_post_execute_hook(hook)

        result = executor.remove_post_execute_hook(hook)

        assert result is True
        assert hook not in executor._post_execute_hooks

    def test_remove_nonexistent_hook_returns_false(self, executor: SkillExecutor) -> None:
        """Attempting to remove a hook that was never added returns False."""
        hook = AsyncMock()

        result = executor.remove_post_execute_hook(hook)

        assert result is False

    def test_remove_hook_leaves_others_intact(self, executor: SkillExecutor) -> None:
        """Removing one hook does not affect other registered hooks."""
        hook_a = AsyncMock()
        hook_b = AsyncMock()
        executor.add_post_execute_hook(hook_a)
        executor.add_post_execute_hook(hook_b)

        executor.remove_post_execute_hook(hook_a)

        assert hook_a not in executor._post_execute_hooks
        assert hook_b in executor._post_execute_hooks

    async def test_removed_hook_does_not_fire(self, executor: SkillExecutor) -> None:
        """A hook removed before execution does not fire."""
        hook = AsyncMock()
        executor.add_post_execute_hook(hook)
        executor.remove_post_execute_hook(hook)
        executor.register_skill("noop", lambda p: "ok")

        await executor.execute("noop", {})

        hook.assert_not_awaited()
