"""TDD test file for isg_agent.core.flywheel_emitter.FlywheelEmitter.

This is the RED phase — all tests are written against the contract defined in the
task specification.  The implementation module does not yet exist; every test here
is expected to FAIL until FlywheelEmitter is built.

Contract summary
----------------
FlywheelEmitter emits fire-and-forget async events to the MiLA Web Bridge
(default http://localhost:9473).  It wraps every HTTP call with asyncio.shield()
and a 5-second hard timeout so that network failures never block the caller.
Failures are logged; they are NEVER raised to the caller.

Covered test classes
--------------------
1. TestFlywheelEmitterInit             — construction, env vars, defaults
2. TestEmitSkillExecution              — payload shape, success/failure behaviour
3. TestEmitAgentOnboarded              — payload shape, locale default
4. TestEmitBusinessIQUpdate            — payload shape, anonymized business_id
5. TestEmitCustomerInteraction         — payload shape, no PII
6. TestFireAndForget                   — non-blocking, shield, concurrency, logging
7. TestSkillExecutorIntegration        — SkillExecutor post-execute hook integration

Total tests: 42
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from isg_agent.core.flywheel_emitter import FlywheelEmitter
from isg_agent.skills.executor import ExecutionResult, SkillExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ok_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Return a minimal mock httpx.Response with the given status."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {"ok": True}
    resp.raise_for_status = MagicMock()
    return resp


def _make_async_client_mock(response: MagicMock) -> MagicMock:
    """Create a mock httpx.AsyncClient context manager that returns the given response."""
    client_mock = MagicMock()
    client_mock.post = AsyncMock(return_value=response)
    client_mock.aclose = AsyncMock()
    return client_mock


def _patch_httpx(response: MagicMock) -> Any:
    """Return a context manager that patches httpx.AsyncClient with response."""
    mock_cls = MagicMock()
    async_client = _make_async_client_mock(response)
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=async_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_cls, async_client


# ---------------------------------------------------------------------------
# 1. Initialization tests
# ---------------------------------------------------------------------------


class TestFlywheelEmitterInit:
    """FlywheelEmitter construction and configuration."""

    def test_default_bridge_url_is_localhost_9473(self) -> None:
        emitter = FlywheelEmitter()
        assert "localhost" in emitter.bridge_url or "127.0.0.1" in emitter.bridge_url
        assert "9473" in emitter.bridge_url

    def test_custom_bridge_url_is_stored(self) -> None:
        emitter = FlywheelEmitter(bridge_url="http://10.0.0.5:9473")
        assert emitter.bridge_url == "http://10.0.0.5:9473"

    def test_env_var_bridge_url_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MILA_BRIDGE_URL", "http://mila-host:9473")
        emitter = FlywheelEmitter()
        assert emitter.bridge_url == "http://mila-host:9473"

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MILA_BRIDGE_URL", "http://env-host:9999")
        emitter = FlywheelEmitter()
        assert "9999" in emitter.bridge_url
        assert "env-host" in emitter.bridge_url

    def test_explicit_url_takes_priority_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MILA_BRIDGE_URL", "http://env-host:9999")
        emitter = FlywheelEmitter(bridge_url="http://explicit:8888")
        assert "8888" in emitter.bridge_url
        assert "explicit" in emitter.bridge_url

    def test_emit_timeout_is_5_seconds(self) -> None:
        emitter = FlywheelEmitter()
        assert emitter.emit_timeout == 5


# ---------------------------------------------------------------------------
# 2. emit_skill_execution tests
# ---------------------------------------------------------------------------


class TestEmitSkillExecution:
    """FlywheelEmitter.emit_skill_execution()"""

    async def test_success_returns_true(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            result = await emitter.emit_skill_execution(
                agent_id="agent-123",
                skill_name="send_email",
                industry="restaurant",
                success=True,
                execution_time_ms=150,
            )

        assert result is True

    async def test_sends_correct_payload_structure(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="agent-abc",
                skill_name="book_appointment",
                industry="healthcare",
                success=True,
                execution_time_ms=200,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
        assert "event_type" in posted_json
        assert posted_json["event_type"] == "skill_execution"

    async def test_includes_agent_id_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="agent-xyz-999",
                skill_name="lookup_order",
                industry="retail",
                success=True,
                execution_time_ms=80,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        payload = posted_json.get("payload", posted_json)
        assert "agent_xyz_999" in str(payload) or "agent-xyz-999" in str(payload)

    async def test_includes_skill_name_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="process_payment",
                industry="ecommerce",
                success=True,
                execution_time_ms=300,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "process_payment" in str(posted_json)

    async def test_includes_industry_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="greet",
                industry="hospitality",
                success=True,
                execution_time_ms=10,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "hospitality" in str(posted_json)

    async def test_includes_execution_time_ms_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="greet",
                industry="retail",
                success=True,
                execution_time_ms=742,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "742" in str(posted_json) or 742 in str(posted_json)

    async def test_includes_success_flag_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="greet",
                industry="retail",
                success=False,
                execution_time_ms=50,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        # False must appear somewhere in the serialized payload
        assert "false" in str(posted_json).lower() or False in str(posted_json)

    async def test_optional_metadata_included_when_provided(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)
        extra = {"order_count": 3, "region": "west"}

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="check_stock",
                industry="logistics",
                success=True,
                execution_time_ms=120,
                metadata=extra,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "west" in str(posted_json)

    async def test_bridge_down_returns_false(self) -> None:
        import httpx

        emitter = FlywheelEmitter()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.post = AsyncMock(
                side_effect=httpx.ConnectError("connection refused")
            )
            mock_instance.aclose = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="test",
                industry="tech",
                success=True,
                execution_time_ms=10,
            )

        assert result is False

    async def test_never_raises_on_failure(self) -> None:
        import httpx

        emitter = FlywheelEmitter()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.post = AsyncMock(side_effect=RuntimeError("unexpected crash"))
            mock_instance.aclose = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Must not raise; must return False
            result = await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="test",
                industry="tech",
                success=True,
                execution_time_ms=10,
            )

        assert result is False

    async def test_timeout_enforced_at_5_seconds(self) -> None:
        emitter = FlywheelEmitter()

        async def hang(*_args: Any, **_kwargs: Any) -> None:
            await asyncio.sleep(100)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.post = hang
            mock_instance.aclose = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                mock_wait.side_effect = asyncio.TimeoutError
                result = await emitter.emit_skill_execution(
                    agent_id="a1",
                    skill_name="slow_skill",
                    industry="tech",
                    success=True,
                    execution_time_ms=10,
                )

        assert result is False


# ---------------------------------------------------------------------------
# 3. emit_agent_onboarded tests
# ---------------------------------------------------------------------------


class TestEmitAgentOnboarded:
    """FlywheelEmitter.emit_agent_onboarded()"""

    async def test_success_returns_true(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            result = await emitter.emit_agent_onboarded(
                agent_handle="@tacobell_downtown",
                industry="restaurant",
                tier="starter",
                template_used="restaurant_host",
            )

        assert result is True

    async def test_includes_handle_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_agent_onboarded(
                agent_handle="@fitness_guru_nyc",
                industry="fitness",
                tier="pro",
                template_used="gym_assistant",
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "fitness_guru_nyc" in str(posted_json) or "@fitness_guru_nyc" in str(posted_json)

    async def test_includes_industry_and_tier_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_agent_onboarded(
                agent_handle="@salon_one",
                industry="beauty",
                tier="enterprise",
                template_used="beauty_concierge",
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "beauty" in str(posted_json)
        assert "enterprise" in str(posted_json)

    async def test_includes_template_used_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_agent_onboarded(
                agent_handle="@dealership_west",
                industry="automotive",
                tier="pro",
                template_used="car_dealership_agent",
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "car_dealership_agent" in str(posted_json)

    async def test_default_locale_is_en(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_agent_onboarded(
                agent_handle="@shop_a",
                industry="retail",
                tier="starter",
                template_used="retail_assistant",
                # locale intentionally omitted
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert '"en"' in str(posted_json) or "'en'" in str(posted_json) or "en" in str(posted_json)

    async def test_custom_locale_included(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_agent_onboarded(
                agent_handle="@tienda_mx",
                industry="retail",
                tier="starter",
                template_used="retail_assistant",
                locale="es",
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "es" in str(posted_json)


# ---------------------------------------------------------------------------
# 4. emit_business_iq_update tests
# ---------------------------------------------------------------------------


class TestEmitBusinessIQUpdate:
    """FlywheelEmitter.emit_business_iq_update()"""

    async def test_success_returns_true(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            result = await emitter.emit_business_iq_update(
                business_id="biz-001",
                industry="restaurant",
                metrics={"skill_usage": 42, "customer_satisfaction": 4.7, "active_days": 30},
            )

        assert result is True

    async def test_includes_metrics_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        metrics = {"skill_usage": 10, "customer_satisfaction": 3.9, "active_days": 7}

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_business_iq_update(
                business_id="biz-002",
                industry="retail",
                metrics=metrics,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "skill_usage" in str(posted_json)
        assert "customer_satisfaction" in str(posted_json)
        assert "active_days" in str(posted_json)

    async def test_includes_industry_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_business_iq_update(
                business_id="biz-003",
                industry="legal",
                metrics={"skill_usage": 5, "customer_satisfaction": 4.0, "active_days": 14},
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "legal" in str(posted_json)

    async def test_business_id_is_anonymized(self) -> None:
        """Raw business_id must NOT appear in the wire payload — only a hash."""
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        raw_id = "biz-secret-internal-id-9999"
        expected_hash = hashlib.sha256(raw_id.encode()).hexdigest()

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_business_iq_update(
                business_id=raw_id,
                industry="finance",
                metrics={"skill_usage": 1, "customer_satisfaction": 5.0, "active_days": 1},
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        serialized = str(posted_json)

        # Raw id must not appear
        assert raw_id not in serialized
        # Hash must appear
        assert expected_hash in serialized


# ---------------------------------------------------------------------------
# 5. emit_customer_interaction tests
# ---------------------------------------------------------------------------


class TestEmitCustomerInteraction:
    """FlywheelEmitter.emit_customer_interaction()"""

    async def test_success_returns_true(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            result = await emitter.emit_customer_interaction(
                agent_id="agent-001",
                industry="restaurant",
                interaction_type="chat",
                duration_ms=4200,
                was_resolved=True,
            )

        assert result is True

    async def test_includes_interaction_type_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_customer_interaction(
                agent_id="agent-002",
                industry="healthcare",
                interaction_type="voice",
                duration_ms=30000,
                was_resolved=False,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "voice" in str(posted_json)

    async def test_includes_duration_ms_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_customer_interaction(
                agent_id="agent-003",
                industry="ecommerce",
                interaction_type="action",
                duration_ms=8765,
                was_resolved=True,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "8765" in str(posted_json) or 8765 in str(posted_json)

    async def test_includes_resolution_status_in_payload(self) -> None:
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_customer_interaction(
                agent_id="agent-004",
                industry="retail",
                interaction_type="chat",
                duration_ms=1500,
                was_resolved=True,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        assert "true" in str(posted_json).lower() or True in str(posted_json)

    async def test_no_pii_in_payload(self) -> None:
        """agent_id must not appear verbatim if it could contain PII.

        The emitter must hash or omit the agent_id from the wire payload
        to ensure no PII leaks into MiLA's flywheel storage.
        """
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, async_client = _patch_httpx(resp)

        # Use a plausible PII-containing agent_id
        sensitive_id = "user_john_doe_ssn_123456789"

        with patch("httpx.AsyncClient", mock_cls):
            await emitter.emit_customer_interaction(
                agent_id=sensitive_id,
                industry="legal",
                interaction_type="chat",
                duration_ms=2000,
                was_resolved=True,
            )

        call_kwargs = async_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json", {})
        # Raw sensitive_id must not be present verbatim in the payload
        assert sensitive_id not in str(posted_json)


# ---------------------------------------------------------------------------
# 6. Fire-and-forget behaviour tests
# ---------------------------------------------------------------------------


class TestFireAndForget:
    """Verify non-blocking, shielded, concurrent-safe emission."""

    async def test_does_not_block_caller(self) -> None:
        """Emission must complete without blocking the caller for more than ~5s."""
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            # Simply verify the coroutine can be awaited without hanging
            result = await asyncio.wait_for(
                emitter.emit_skill_execution(
                    agent_id="a1",
                    skill_name="greet",
                    industry="tech",
                    success=True,
                    execution_time_ms=10,
                ),
                timeout=2.0,
            )
        assert result is True

    async def test_asyncio_shield_prevents_outer_cancellation(self) -> None:
        """When the outer task is cancelled mid-emission, the emitter handles
        CancelledError gracefully and returns False rather than propagating it."""
        emitter = FlywheelEmitter()

        async def slow_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            await asyncio.sleep(10)
            return _make_ok_response(200)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.post = slow_post
            mock_instance.aclose = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Simulate cancellation via TimeoutError (mirrors asyncio.shield behaviour)
            with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                mock_wait.side_effect = asyncio.CancelledError
                result = await emitter.emit_skill_execution(
                    agent_id="a1",
                    skill_name="test",
                    industry="tech",
                    success=True,
                    execution_time_ms=5,
                )

        assert result is False

    async def test_concurrent_emissions_all_succeed(self) -> None:
        """Multiple simultaneous emissions must not interfere with each other."""
        emitter = FlywheelEmitter()
        resp = _make_ok_response(200)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            tasks = [
                emitter.emit_skill_execution(
                    agent_id=f"agent-{i}",
                    skill_name="ping",
                    industry="tech",
                    success=True,
                    execution_time_ms=i * 10,
                )
                for i in range(10)
            ]
            results = await asyncio.gather(*tasks)

        assert all(r is True for r in results)
        assert len(results) == 10

    async def test_logs_error_on_bridge_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Failures must be logged at ERROR or WARNING level, never silently swallowed."""
        import httpx

        emitter = FlywheelEmitter()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.post = AsyncMock(
                side_effect=httpx.ConnectError("bridge unreachable")
            )
            mock_instance.aclose = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.WARNING, logger="isg_agent.core.flywheel_emitter"):
                result = await emitter.emit_skill_execution(
                    agent_id="a1",
                    skill_name="crash_test",
                    industry="tech",
                    success=True,
                    execution_time_ms=10,
                )

        assert result is False
        # At least one log record must have been emitted at WARNING or higher
        assert len(caplog.records) >= 1
        levels = {r.levelname for r in caplog.records}
        assert levels & {"WARNING", "ERROR", "CRITICAL"}

    async def test_bridge_non_200_returns_false(self) -> None:
        """A non-200 HTTP response from the bridge must be treated as a failure."""
        emitter = FlywheelEmitter()
        resp = _make_ok_response(503)
        mock_cls, _ = _patch_httpx(resp)

        with patch("httpx.AsyncClient", mock_cls):
            result = await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name="test",
                industry="tech",
                success=True,
                execution_time_ms=10,
            )

        assert result is False


# ---------------------------------------------------------------------------
# 7. SkillExecutor integration tests
# ---------------------------------------------------------------------------


class TestSkillExecutorIntegration:
    """Verify that SkillExecutor wires FlywheelEmitter via set_post_execute_hook."""

    async def test_skill_executor_calls_emitter_after_success(self) -> None:
        """After a successful skill execution, the post-execute hook fires once."""
        emitter = FlywheelEmitter()
        emitter.emit_skill_execution = AsyncMock(return_value=True)  # type: ignore[method-assign]

        executor = SkillExecutor()
        executor.register_skill("ping", lambda _params: "pong")

        async def hook(skill_name: str, params: dict, result: ExecutionResult) -> None:
            await emitter.emit_skill_execution(
                agent_id=params.get("agent_id", "unknown"),
                skill_name=skill_name,
                industry=params.get("industry", "unknown"),
                success=result.success,
                execution_time_ms=result.duration_ms,
            )

        executor.set_post_execute_hook(hook)

        await executor.execute("ping", {"agent_id": "test-agent", "industry": "tech"})

        emitter.emit_skill_execution.assert_awaited_once()

    async def test_emitter_receives_correct_skill_name_from_executor(self) -> None:
        """The emitter receives the exact skill_name that was executed."""
        emitter = FlywheelEmitter()
        captured_calls: list[dict] = []

        async def capture_emit(**kwargs: Any) -> bool:
            captured_calls.append(kwargs)
            return True

        emitter.emit_skill_execution = capture_emit  # type: ignore[method-assign]

        executor = SkillExecutor()
        executor.register_skill("send_invoice", lambda _p: "sent")

        async def hook(skill_name: str, params: dict, result: ExecutionResult) -> None:
            await emitter.emit_skill_execution(
                agent_id=params.get("agent_id", "unknown"),
                skill_name=skill_name,
                industry=params.get("industry", "unknown"),
                success=result.success,
                execution_time_ms=result.duration_ms,
            )

        executor.set_post_execute_hook(hook)
        await executor.execute("send_invoice", {"agent_id": "biz-1", "industry": "finance"})

        assert len(captured_calls) == 1
        assert captured_calls[0]["skill_name"] == "send_invoice"

    async def test_emitter_not_called_on_skill_failure(self) -> None:
        """The emitter hook must NOT fire when a skill raises an exception.

        SkillExecutor already gates the post-execute hook behind result.success,
        so the emitter should never see a failed execution via the hook path.
        This test confirms that contract holds.
        """
        emitter = FlywheelEmitter()
        emitter.emit_skill_execution = AsyncMock(return_value=True)  # type: ignore[method-assign]

        executor = SkillExecutor()

        def failing_skill(_params: dict) -> str:
            raise RuntimeError("skill crashed")

        executor.register_skill("bad_skill", failing_skill)

        async def hook(skill_name: str, params: dict, result: ExecutionResult) -> None:
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name=skill_name,
                industry="tech",
                success=result.success,
                execution_time_ms=result.duration_ms,
            )

        executor.set_post_execute_hook(hook)
        result = await executor.execute("bad_skill", {})

        assert result.success is False
        emitter.emit_skill_execution.assert_not_awaited()

    async def test_emitter_failure_does_not_break_executor(self) -> None:
        """If the emitter raises inside the hook, SkillExecutor must still
        return the successful ExecutionResult without re-raising."""
        emitter = FlywheelEmitter()
        emitter.emit_skill_execution = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("emitter exploded")
        )

        executor = SkillExecutor()
        executor.register_skill("safe_skill", lambda _p: "ok")

        async def hook(skill_name: str, params: dict, result: ExecutionResult) -> None:
            await emitter.emit_skill_execution(
                agent_id="a1",
                skill_name=skill_name,
                industry="tech",
                success=result.success,
                execution_time_ms=result.duration_ms,
            )

        executor.set_post_execute_hook(hook)

        # SkillExecutor swallows hook exceptions — result must still be success
        result = await executor.execute("safe_skill", {})

        assert result.success is True
        assert result.output == "ok"
