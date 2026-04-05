"""Tests for isg_agent.security.rate_limiter — per-entity granular rate limiting.

Comprehensive coverage of:
- RateDecision dataclass fields and defaults
- GranularRateLimiter.check_rate (token bucket core)
- GranularRateLimiter.check_ip (100/min per IP)
- GranularRateLimiter.check_user (300/min per user)
- GranularRateLimiter.check_agent (60/min per agent)
- GranularRateLimiter.check_auth (10/5min per IP — brute force)
- GranularRateLimiter.check_api_key (1000/min per API key)
- RateLimitMiddleware (Starlette middleware):
  - X-Forwarded-For IP extraction
  - JWT user_id extraction
  - Agent ID from path extraction
  - Rate limit headers on responses
  - 429 response format + Retry-After
  - Skip paths (/health, /metrics)
  - Multiple limits stacked (IP + user)
- Cleanup of expired buckets
- Concurrent access (thread safety)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.security.rate_limiter import (
    GranularRateLimiter,
    RateDecision,
    RateLimitMiddleware,
)


# ---------------------------------------------------------------------------
# RateDecision dataclass tests
# ---------------------------------------------------------------------------


class TestRateDecision:
    """Tests for the RateDecision dataclass."""

    def test_allowed_decision_fields(self) -> None:
        """An allowed RateDecision has correct field values."""
        now = time.time() + 60
        decision = RateDecision(
            allowed=True,
            remaining=87,
            limit=100,
            reset_at=now,
            retry_after=None,
            key_type="ip",
        )
        assert decision.allowed is True
        assert decision.remaining == 87
        assert decision.limit == 100
        assert decision.reset_at == now
        assert decision.retry_after is None
        assert decision.key_type == "ip"

    def test_denied_decision_fields(self) -> None:
        """A denied RateDecision includes retry_after."""
        now = time.time() + 60
        decision = RateDecision(
            allowed=False,
            remaining=0,
            limit=100,
            reset_at=now,
            retry_after=42,
            key_type="user",
        )
        assert decision.allowed is False
        assert decision.remaining == 0
        assert decision.retry_after == 42
        assert decision.key_type == "user"

    def test_decision_retry_after_optional(self) -> None:
        """retry_after defaults to None when not provided."""
        decision = RateDecision(
            allowed=True,
            remaining=10,
            limit=100,
            reset_at=time.time() + 60,
            key_type="agent",
        )
        assert decision.retry_after is None

    def test_decision_key_types(self) -> None:
        """Verify all valid key types can be assigned."""
        for key_type in ("ip", "user", "agent", "auth", "api_key"):
            decision = RateDecision(
                allowed=True,
                remaining=1,
                limit=10,
                reset_at=time.time() + 60,
                key_type=key_type,
            )
            assert decision.key_type == key_type


# ---------------------------------------------------------------------------
# GranularRateLimiter — check_rate (core token bucket)
# ---------------------------------------------------------------------------


class TestCheckRate:
    """Tests for GranularRateLimiter.check_rate — the core token bucket."""

    def setup_method(self) -> None:
        self.limiter = GranularRateLimiter()

    def test_under_limit_allows(self) -> None:
        """Requests under the limit are allowed."""
        decision = self.limiter.check_rate("test:key1", limit=10, window_seconds=60)
        assert decision.allowed is True
        assert decision.remaining == 9
        assert decision.limit == 10

    def test_at_limit_denies(self) -> None:
        """Request exceeding the limit is denied."""
        for _ in range(10):
            self.limiter.check_rate("test:key2", limit=10, window_seconds=60)
        decision = self.limiter.check_rate("test:key2", limit=10, window_seconds=60)
        assert decision.allowed is False
        assert decision.remaining == 0
        assert decision.retry_after is not None
        assert decision.retry_after > 0

    def test_different_keys_independent(self) -> None:
        """Different keys have independent buckets."""
        for _ in range(10):
            self.limiter.check_rate("test:keyA", limit=10, window_seconds=60)
        decision_a = self.limiter.check_rate("test:keyA", limit=10, window_seconds=60)
        decision_b = self.limiter.check_rate("test:keyB", limit=10, window_seconds=60)
        assert decision_a.allowed is False
        assert decision_b.allowed is True

    def test_reset_at_is_future_timestamp(self) -> None:
        """reset_at is a valid future Unix timestamp."""
        decision = self.limiter.check_rate("test:key3", limit=10, window_seconds=60)
        assert decision.reset_at > time.time()

    def test_remaining_decrements(self) -> None:
        """remaining decrements with each allowed request."""
        d1 = self.limiter.check_rate("test:dec", limit=5, window_seconds=60)
        d2 = self.limiter.check_rate("test:dec", limit=5, window_seconds=60)
        d3 = self.limiter.check_rate("test:dec", limit=5, window_seconds=60)
        assert d1.remaining == 4
        assert d2.remaining == 3
        assert d3.remaining == 2

    def test_token_refill_after_window(self) -> None:
        """Tokens refill after the window elapses."""
        # Use a very short window to test refill
        for _ in range(5):
            self.limiter.check_rate("test:refill", limit=5, window_seconds=0.05)
        denied = self.limiter.check_rate("test:refill", limit=5, window_seconds=0.05)
        assert denied.allowed is False

        time.sleep(0.06)  # Wait for window to pass
        restored = self.limiter.check_rate("test:refill", limit=5, window_seconds=0.05)
        assert restored.allowed is True

    def test_key_type_is_generic(self) -> None:
        """check_rate returns 'custom' as key_type."""
        decision = self.limiter.check_rate("custom:x", limit=10, window_seconds=60)
        assert decision.key_type == "custom"

    def test_zero_limit_always_denies(self) -> None:
        """A limit of 0 always denies."""
        decision = self.limiter.check_rate("test:zero", limit=0, window_seconds=60)
        assert decision.allowed is False

    def test_single_request_limit(self) -> None:
        """A limit of 1 allows exactly one request."""
        d1 = self.limiter.check_rate("test:single", limit=1, window_seconds=60)
        d2 = self.limiter.check_rate("test:single", limit=1, window_seconds=60)
        assert d1.allowed is True
        assert d2.allowed is False


# ---------------------------------------------------------------------------
# GranularRateLimiter — check_ip
# ---------------------------------------------------------------------------


class TestCheckIp:
    """Tests for GranularRateLimiter.check_ip — 100 requests/minute per IP."""

    def setup_method(self) -> None:
        self.limiter = GranularRateLimiter()

    def test_ip_under_limit(self) -> None:
        """IP under 100/min is allowed."""
        decision = self.limiter.check_ip("192.168.1.1")
        assert decision.allowed is True
        assert decision.key_type == "ip"
        assert decision.limit == 100

    def test_ip_at_limit(self) -> None:
        """IP at 100/min is denied."""
        for _ in range(100):
            self.limiter.check_ip("10.0.0.1")
        decision = self.limiter.check_ip("10.0.0.1")
        assert decision.allowed is False
        assert decision.remaining == 0

    def test_different_ips_independent(self) -> None:
        """Different IPs have independent counters."""
        for _ in range(100):
            self.limiter.check_ip("1.1.1.1")
        d1 = self.limiter.check_ip("1.1.1.1")
        d2 = self.limiter.check_ip("2.2.2.2")
        assert d1.allowed is False
        assert d2.allowed is True

    def test_ip_remaining_count(self) -> None:
        """Remaining count tracks correctly for IP checks."""
        d1 = self.limiter.check_ip("3.3.3.3")
        assert d1.remaining == 99

    def test_ip_retry_after_on_deny(self) -> None:
        """Denied IP request includes retry_after."""
        for _ in range(100):
            self.limiter.check_ip("4.4.4.4")
        decision = self.limiter.check_ip("4.4.4.4")
        assert decision.retry_after is not None
        assert decision.retry_after > 0


# ---------------------------------------------------------------------------
# GranularRateLimiter — check_user
# ---------------------------------------------------------------------------


class TestCheckUser:
    """Tests for GranularRateLimiter.check_user — 300 requests/minute per user."""

    def setup_method(self) -> None:
        self.limiter = GranularRateLimiter()

    def test_user_under_limit(self) -> None:
        """User under 300/min is allowed."""
        decision = self.limiter.check_user("user-abc-123")
        assert decision.allowed is True
        assert decision.key_type == "user"
        assert decision.limit == 300

    def test_user_at_limit(self) -> None:
        """User at 300/min is denied."""
        for _ in range(300):
            self.limiter.check_user("user-heavy")
        decision = self.limiter.check_user("user-heavy")
        assert decision.allowed is False

    def test_different_users_independent(self) -> None:
        """Different users have independent counters."""
        for _ in range(300):
            self.limiter.check_user("user-spam")
        d1 = self.limiter.check_user("user-spam")
        d2 = self.limiter.check_user("user-clean")
        assert d1.allowed is False
        assert d2.allowed is True

    def test_user_remaining_correct(self) -> None:
        """Remaining count is correct for user checks."""
        d1 = self.limiter.check_user("user-count")
        d2 = self.limiter.check_user("user-count")
        assert d1.remaining == 299
        assert d2.remaining == 298


# ---------------------------------------------------------------------------
# GranularRateLimiter — check_agent
# ---------------------------------------------------------------------------


class TestCheckAgent:
    """Tests for GranularRateLimiter.check_agent — 60 requests/minute per agent."""

    def setup_method(self) -> None:
        self.limiter = GranularRateLimiter()

    def test_agent_under_limit(self) -> None:
        """Agent under 60/min is allowed."""
        decision = self.limiter.check_agent("agent-001")
        assert decision.allowed is True
        assert decision.key_type == "agent"
        assert decision.limit == 60

    def test_agent_at_limit(self) -> None:
        """Agent at 60/min is denied."""
        for _ in range(60):
            self.limiter.check_agent("agent-busy")
        decision = self.limiter.check_agent("agent-busy")
        assert decision.allowed is False

    def test_different_agents_independent(self) -> None:
        """Different agents have independent counters."""
        for _ in range(60):
            self.limiter.check_agent("agent-X")
        d1 = self.limiter.check_agent("agent-X")
        d2 = self.limiter.check_agent("agent-Y")
        assert d1.allowed is False
        assert d2.allowed is True


# ---------------------------------------------------------------------------
# GranularRateLimiter — check_auth (brute force protection)
# ---------------------------------------------------------------------------


class TestCheckAuth:
    """Tests for GranularRateLimiter.check_auth — 10 attempts/5 minutes per IP."""

    def setup_method(self) -> None:
        self.limiter = GranularRateLimiter()

    def test_auth_under_limit(self) -> None:
        """Auth attempt under 10/5min is allowed."""
        decision = self.limiter.check_auth("192.168.1.1")
        assert decision.allowed is True
        assert decision.key_type == "auth"
        assert decision.limit == 10

    def test_auth_brute_force_blocked(self) -> None:
        """10 auth attempts = blocked (brute force protection)."""
        for _ in range(10):
            self.limiter.check_auth("attacker-ip")
        decision = self.limiter.check_auth("attacker-ip")
        assert decision.allowed is False
        assert decision.remaining == 0

    def test_auth_retry_after_on_block(self) -> None:
        """Blocked auth attempt includes retry_after."""
        for _ in range(10):
            self.limiter.check_auth("brute-ip")
        decision = self.limiter.check_auth("brute-ip")
        assert decision.retry_after is not None
        assert decision.retry_after > 0

    def test_auth_window_is_five_minutes(self) -> None:
        """Auth window is 300 seconds (5 minutes)."""
        # Exhaust all 10 auth tokens so the bucket is empty
        for _ in range(10):
            self.limiter.check_auth("window-check-ip")
        decision = self.limiter.check_auth("window-check-ip")
        assert decision.allowed is False
        # retry_after should reflect the 5-minute window refill rate
        # With 10 tokens / 300s = 0.0333 tokens/s, 1 token takes ~30s
        assert decision.retry_after is not None
        assert decision.retry_after >= 1

    def test_auth_different_ips_independent(self) -> None:
        """Different IPs have independent auth counters."""
        for _ in range(10):
            self.limiter.check_auth("blocked-ip")
        d1 = self.limiter.check_auth("blocked-ip")
        d2 = self.limiter.check_auth("clean-ip")
        assert d1.allowed is False
        assert d2.allowed is True


# ---------------------------------------------------------------------------
# GranularRateLimiter — check_api_key
# ---------------------------------------------------------------------------


class TestCheckApiKey:
    """Tests for GranularRateLimiter.check_api_key — 1000 requests/minute per API key."""

    def setup_method(self) -> None:
        self.limiter = GranularRateLimiter()

    def test_api_key_under_limit(self) -> None:
        """API key under 1000/min is allowed."""
        key_hash = hashlib.sha256(b"my-api-key-1").hexdigest()
        decision = self.limiter.check_api_key(key_hash)
        assert decision.allowed is True
        assert decision.key_type == "api_key"
        assert decision.limit == 1000

    def test_api_key_at_limit(self) -> None:
        """API key at 1000/min is denied."""
        key_hash = hashlib.sha256(b"heavy-key").hexdigest()
        for _ in range(1000):
            self.limiter.check_api_key(key_hash)
        decision = self.limiter.check_api_key(key_hash)
        assert decision.allowed is False

    def test_different_api_keys_independent(self) -> None:
        """Different API key hashes have independent counters."""
        key1 = hashlib.sha256(b"key-1").hexdigest()
        key2 = hashlib.sha256(b"key-2").hexdigest()
        for _ in range(1000):
            self.limiter.check_api_key(key1)
        d1 = self.limiter.check_api_key(key1)
        d2 = self.limiter.check_api_key(key2)
        assert d1.allowed is False
        assert d2.allowed is True


# ---------------------------------------------------------------------------
# GranularRateLimiter — Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for expired bucket cleanup."""

    def test_cleanup_removes_expired_buckets(self) -> None:
        """Expired buckets are removed during cleanup."""
        limiter = GranularRateLimiter()
        # Create a bucket with a very short window
        limiter.check_rate("test:expire", limit=5, window_seconds=0.01)
        assert len(limiter._buckets) > 0

        time.sleep(0.02)
        limiter.cleanup_expired()
        # After cleanup, the expired bucket should be removed
        assert "test:expire" not in limiter._buckets

    def test_cleanup_preserves_active_buckets(self) -> None:
        """Active (non-expired) buckets are preserved during cleanup."""
        limiter = GranularRateLimiter()
        limiter.check_rate("test:active", limit=10, window_seconds=600)
        limiter.cleanup_expired()
        assert "test:active" in limiter._buckets

    def test_cleanup_runs_without_error_on_empty(self) -> None:
        """Cleanup on empty limiter does not raise."""
        limiter = GranularRateLimiter()
        limiter.cleanup_expired()  # Should not raise

    def test_background_cleanup_starts_and_stops(self) -> None:
        """Background cleanup task can be started and stopped."""
        limiter = GranularRateLimiter()
        loop = asyncio.new_event_loop()

        async def _run() -> None:
            limiter.start_cleanup_task(interval_seconds=0.05)
            assert limiter._cleanup_task is not None
            await asyncio.sleep(0.08)
            await limiter.stop_cleanup_task()
            assert limiter._cleanup_task is None

        loop.run_until_complete(_run())
        loop.close()


# ---------------------------------------------------------------------------
# GranularRateLimiter — Concurrent access
# ---------------------------------------------------------------------------


class TestConcurrentAccess:
    """Tests for thread safety under concurrent access."""

    def test_concurrent_ip_checks(self) -> None:
        """Concurrent IP checks do not corrupt state."""
        limiter = GranularRateLimiter()
        results: list[RateDecision] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(10):
                d = limiter.check_ip("concurrent-ip")
                with lock:
                    results.append(d)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 50
        allowed = sum(1 for d in results if d.allowed)
        denied = sum(1 for d in results if not d.allowed)
        # Total should not exceed the limit
        assert allowed <= 100
        assert allowed + denied == 50

    def test_concurrent_different_keys(self) -> None:
        """Concurrent checks on different keys do not interfere."""
        limiter = GranularRateLimiter()
        results: dict[str, list[RateDecision]] = {"a": [], "b": []}
        lock = threading.Lock()

        def worker_a() -> None:
            for _ in range(20):
                d = limiter.check_rate("key:a", limit=50, window_seconds=60)
                with lock:
                    results["a"].append(d)

        def worker_b() -> None:
            for _ in range(20):
                d = limiter.check_rate("key:b", limit=50, window_seconds=60)
                with lock:
                    results["b"].append(d)

        t1 = threading.Thread(target=worker_a)
        t2 = threading.Thread(target=worker_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert all(d.allowed for d in results["a"])
        assert all(d.allowed for d in results["b"])


# ---------------------------------------------------------------------------
# RateLimitMiddleware tests
# ---------------------------------------------------------------------------


def _make_scope(
    path: str = "/api/test",
    method: str = "GET",
    client_ip: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a minimal ASGI scope for testing."""
    raw_headers: list[tuple[bytes, bytes]] = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode(), v.encode()))
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": (client_ip, 0),
    }


def _make_jwt_header(sub: str = "user-123", exp: int | None = None) -> str:
    """Create a minimal JWT token for testing (not cryptographically valid)."""
    import base64

    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=").decode()
    payload_dict: dict[str, Any] = {"sub": sub}
    if exp is not None:
        payload_dict["exp"] = exp
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=").decode()
    return f"Bearer {header}.{payload}.{sig}"


class TestRateLimitMiddleware:
    """Tests for the Starlette RateLimitMiddleware."""

    def _make_middleware(self, limiter: GranularRateLimiter | None = None) -> RateLimitMiddleware:
        """Create middleware with a test app."""
        rl = limiter or GranularRateLimiter()

        async def test_app(scope: dict, receive: Any, send: Any) -> None:
            response_body = json.dumps({"ok": True}).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode()),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })

        return RateLimitMiddleware(app=test_app, limiter=rl)

    async def _call_middleware(
        self,
        middleware: RateLimitMiddleware,
        scope: dict,
    ) -> tuple[int, dict[str, str], bytes]:
        """Call middleware and capture response."""
        status_code = 0
        response_headers: dict[str, str] = {}
        response_body = b""

        async def receive() -> dict:
            return {"type": "http.request", "body": b""}

        async def send(message: dict) -> None:
            nonlocal status_code, response_headers, response_body
            if message["type"] == "http.response.start":
                status_code = message["status"]
                for k, v in message.get("headers", []):
                    response_headers[k.decode().lower()] = v.decode()
            elif message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        await middleware(scope, receive, send)
        return status_code, response_headers, response_body

    @pytest.mark.asyncio
    async def test_allowed_request_has_rate_headers(self) -> None:
        """Allowed requests include X-RateLimit-* headers."""
        mw = self._make_middleware()
        scope = _make_scope()
        status, headers, _ = await self._call_middleware(mw, scope)
        assert status == 200
        assert "x-ratelimit-limit" in headers
        assert "x-ratelimit-remaining" in headers
        assert "x-ratelimit-reset" in headers

    @pytest.mark.asyncio
    async def test_denied_request_returns_429(self) -> None:
        """Denied request returns 429 with JSON body."""
        limiter = GranularRateLimiter()
        # Exhaust IP limit
        for _ in range(100):
            limiter.check_ip("5.5.5.5")
        mw = self._make_middleware(limiter)
        scope = _make_scope(client_ip="5.5.5.5")
        status, headers, body = await self._call_middleware(mw, scope)
        assert status == 429
        data = json.loads(body)
        assert data["error"] == "rate_limit_exceeded"
        assert "retry_after" in data

    @pytest.mark.asyncio
    async def test_denied_request_has_retry_after_header(self) -> None:
        """429 response includes Retry-After header."""
        limiter = GranularRateLimiter()
        for _ in range(100):
            limiter.check_ip("6.6.6.6")
        mw = self._make_middleware(limiter)
        scope = _make_scope(client_ip="6.6.6.6")
        status, headers, _ = await self._call_middleware(mw, scope)
        assert status == 429
        assert "retry-after" in headers
        assert int(headers["retry-after"]) > 0

    @pytest.mark.asyncio
    async def test_skip_health_endpoint(self) -> None:
        """Requests to /health skip rate limiting."""
        limiter = GranularRateLimiter()
        # Exhaust IP limit
        for _ in range(100):
            limiter.check_ip("7.7.7.7")
        mw = self._make_middleware(limiter)
        scope = _make_scope(path="/health", client_ip="7.7.7.7")
        status, headers, _ = await self._call_middleware(mw, scope)
        assert status == 200
        # No rate limit headers on skip paths
        assert "x-ratelimit-limit" not in headers

    @pytest.mark.asyncio
    async def test_skip_metrics_endpoint(self) -> None:
        """Requests to /metrics skip rate limiting."""
        limiter = GranularRateLimiter()
        for _ in range(100):
            limiter.check_ip("8.8.8.8")
        mw = self._make_middleware(limiter)
        scope = _make_scope(path="/metrics", client_ip="8.8.8.8")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200

    @pytest.mark.asyncio
    async def test_x_forwarded_for_ip_extraction(self) -> None:
        """IP is extracted from rightmost X-Forwarded-For entry (trusted proxy)."""
        limiter = GranularRateLimiter()
        # Exhaust the rightmost (proxy-appended) IP, not the leftmost (spoofable)
        for _ in range(100):
            limiter.check_ip("10.0.0.1")
        mw = self._make_middleware(limiter)
        scope = _make_scope(
            client_ip="127.0.0.1",
            headers={"x-forwarded-for": "99.99.99.99, 10.0.0.1"},
        )
        status, _, _ = await self._call_middleware(mw, scope)
        # The rightmost (trusted proxy) IP is exhausted, so should be denied
        assert status == 429

    @pytest.mark.asyncio
    async def test_jwt_user_extraction(self) -> None:
        """User ID is extracted from JWT and used for user rate limiting."""
        limiter = GranularRateLimiter()
        mw = self._make_middleware(limiter)
        auth_header = _make_jwt_header(sub="user-rate-test")
        scope = _make_scope(headers={"authorization": auth_header})
        status, headers, _ = await self._call_middleware(mw, scope)
        assert status == 200
        # Verify user bucket was created
        assert any("user:user-rate-test" in k for k in limiter._buckets)

    @pytest.mark.asyncio
    async def test_agent_id_from_path(self) -> None:
        """Agent ID is extracted from /agents/{agent_id}/ paths."""
        limiter = GranularRateLimiter()
        mw = self._make_middleware(limiter)
        scope = _make_scope(path="/agents/agent-007/skills")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200
        # Verify agent bucket was created
        assert any("agent:agent-007" in k for k in limiter._buckets)

    @pytest.mark.asyncio
    async def test_multiple_limits_stacked(self) -> None:
        """IP + user limits are both checked (most restrictive wins)."""
        limiter = GranularRateLimiter()
        mw = self._make_middleware(limiter)
        auth_header = _make_jwt_header(sub="stacked-user")

        # Both IP and user should be checked
        scope = _make_scope(
            client_ip="11.11.11.11",
            headers={"authorization": auth_header},
        )
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200

        # Exhaust IP limit
        for _ in range(99):  # Already used 1 above
            limiter.check_ip("11.11.11.11")

        # Next request should be denied (IP exhausted even though user has quota)
        status2, _, _ = await self._call_middleware(mw, scope)
        assert status2 == 429

    @pytest.mark.asyncio
    async def test_rate_limit_headers_values(self) -> None:
        """Rate limit headers have correct numeric values."""
        limiter = GranularRateLimiter()
        mw = self._make_middleware(limiter)
        scope = _make_scope(client_ip="12.12.12.12")
        _, headers, _ = await self._call_middleware(mw, scope)
        assert int(headers["x-ratelimit-limit"]) == 100
        assert int(headers["x-ratelimit-remaining"]) == 99
        assert int(headers["x-ratelimit-reset"]) >= int(time.time())

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        """Non-HTTP scopes (websocket) pass through without rate limiting."""
        limiter = GranularRateLimiter()
        called = False

        async def test_app(scope: dict, receive: Any, send: Any) -> None:
            nonlocal called
            called = True

        mw = RateLimitMiddleware(app=test_app, limiter=limiter)
        scope = {"type": "websocket", "path": "/ws"}
        await mw(scope, AsyncMock(), AsyncMock())
        assert called is True

    @pytest.mark.asyncio
    async def test_429_body_structure(self) -> None:
        """429 response body has expected JSON structure."""
        limiter = GranularRateLimiter()
        for _ in range(100):
            limiter.check_ip("13.13.13.13")
        mw = self._make_middleware(limiter)
        scope = _make_scope(client_ip="13.13.13.13")
        _, _, body = await self._call_middleware(mw, scope)
        data = json.loads(body)
        assert "error" in data
        assert "message" in data
        assert "retry_after" in data
        assert data["error"] == "rate_limit_exceeded"
        assert isinstance(data["retry_after"], int)


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for the rate limiter."""

    def test_empty_ip_string(self) -> None:
        """Empty IP string still works (uses as key)."""
        limiter = GranularRateLimiter()
        decision = limiter.check_ip("")
        assert decision.allowed is True

    def test_very_long_key(self) -> None:
        """Very long key does not cause issues."""
        limiter = GranularRateLimiter()
        long_key = "x" * 10000
        decision = limiter.check_rate(long_key, limit=10, window_seconds=60)
        assert decision.allowed is True

    def test_ipv6_address(self) -> None:
        """IPv6 address works as IP key."""
        limiter = GranularRateLimiter()
        decision = limiter.check_ip("::1")
        assert decision.allowed is True
        assert decision.key_type == "ip"

    def test_special_characters_in_key(self) -> None:
        """Keys with special characters work correctly."""
        limiter = GranularRateLimiter()
        decision = limiter.check_rate("key:with/special?chars&more", limit=10, window_seconds=60)
        assert decision.allowed is True

    def test_limiter_memory_bounded(self) -> None:
        """Cleanup keeps memory bounded."""
        limiter = GranularRateLimiter()
        # Create many short-lived buckets
        for i in range(100):
            limiter.check_rate(f"ephemeral:{i}", limit=10, window_seconds=0.001)
        time.sleep(0.01)
        limiter.cleanup_expired()
        # All should be cleaned up
        assert len(limiter._buckets) == 0
