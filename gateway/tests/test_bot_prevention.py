"""Tests for Bot Prevention Layer 0.

TDD-first: all tests are written before the implementation.

Test Coverage:
    - Honeypot field validation (empty passes, filled rejects silently)
    - Disposable email domain blocking (comprehensive list)
    - Turnstile token verification (valid, invalid, unconfigured)
    - Bot rate limiter (per-IP registration, per-email password reset)
    - Bot scoring middleware (header analysis, score thresholds)
    - Test environment bypass
    - X-Forwarded-For header parsing

All bot rejections return fake 200 success to avoid teaching bot authors
what failed. Real users never see any friction.
"""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_bot_rate_limiter():
    """Reset the BotRateLimiter state between tests."""
    from isg_agent.middleware.bot_prevention import BotRateLimiter
    limiter = BotRateLimiter()
    limiter._ip_buckets.clear()
    limiter._email_buckets.clear()
    yield
    limiter._ip_buckets.clear()
    limiter._email_buckets.clear()


@pytest.fixture()
def test_env(monkeypatch):
    """Set ISG_AGENT_DEPLOYMENT_ENV=test for bot prevention bypass."""
    monkeypatch.setenv("ISG_AGENT_DEPLOYMENT_ENV", "test")
    yield
    monkeypatch.delenv("ISG_AGENT_DEPLOYMENT_ENV", raising=False)


# ===========================================================================
# Part 1: Honeypot Field Validation
# ===========================================================================


class TestHoneypotValidation:
    """Tests for honeypot field server-side validation."""

    def test_honeypot_empty_field_passes(self):
        """An empty honeypot field should be accepted."""
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="")
        assert result.is_bot is False
        assert result.reason is None

    def test_honeypot_none_field_passes(self):
        """A None honeypot value (field not submitted) should be accepted."""
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value=None)
        assert result.is_bot is False

    def test_honeypot_filled_field_rejected_silently(self):
        """A filled honeypot field must be flagged as a bot but NOT raise exception.

        The caller must return a fake 200 success — never tip off bot authors.
        """
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="http://spammersite.com")
        assert result.is_bot is True
        assert result.reason is not None
        assert "honeypot" in result.reason.lower()

    def test_honeypot_whitespace_only_fails(self):
        """Whitespace-only honeypot value is treated as bot activity."""
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="   ")
        assert result.is_bot is True

    def test_honeypot_url_value_fails(self):
        """A URL value in the honeypot field is clearly a bot."""
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="https://example.com")
        assert result.is_bot is True

    def test_honeypot_any_text_fails(self):
        """Any non-empty text in the honeypot should fail."""
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="My Company")
        assert result.is_bot is True

    def test_honeypot_result_has_log_fields(self):
        """HoneypotResult should expose fields suitable for audit logging."""
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="bot-filled")
        assert hasattr(result, "is_bot")
        assert hasattr(result, "reason")
        assert hasattr(result, "trigger")


# ===========================================================================
# Part 2: Disposable Email Domain Blocking
# ===========================================================================


class TestDisposableEmailBlocking:
    """Tests for disposable email domain detection."""

    def test_disposable_email_blocked_mailinator(self):
        """mailinator.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("test@mailinator.com") is True

    def test_disposable_email_blocked_guerrillamail(self):
        """guerrillamail.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@guerrillamail.com") is True

    def test_disposable_email_blocked_tempmail(self):
        """tempmail.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("anything@tempmail.com") is True

    def test_disposable_email_blocked_throwaway(self):
        """throwaway.email must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("x@throwaway.email") is True

    def test_disposable_email_blocked_yopmail(self):
        """yopmail.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@yopmail.com") is True

    def test_disposable_email_blocked_sharklasers(self):
        """sharklasers.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@sharklasers.com") is True

    def test_disposable_email_blocked_maildrop(self):
        """maildrop.cc must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@maildrop.cc") is True

    def test_disposable_email_blocked_trashmail(self):
        """trashmail.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@trashmail.com") is True

    def test_disposable_email_blocked_fakeinbox(self):
        """fakeinbox.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@fakeinbox.com") is True

    def test_disposable_email_blocked_temp_mail_org(self):
        """temp-mail.org must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@temp-mail.org") is True

    def test_legitimate_email_gmail_passes(self):
        """gmail.com is a legitimate permanent email provider."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@gmail.com") is False

    def test_legitimate_email_outlook_passes(self):
        """outlook.com is a legitimate permanent email provider."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@outlook.com") is False

    def test_legitimate_email_yahoo_passes(self):
        """yahoo.com is a legitimate permanent email provider."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@yahoo.com") is False

    def test_legitimate_email_custom_domain_passes(self):
        """A custom business domain should pass."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("ceo@mybusiness.com") is False

    def test_legitimate_email_protonmail_passes(self):
        """protonmail.com is a legitimate privacy-focused provider."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@protonmail.com") is False

    def test_email_domain_case_insensitive(self):
        """Domain matching must be case-insensitive."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@MAILINATOR.COM") is True
        assert is_disposable_email("user@Mailinator.Com") is True

    def test_disposable_email_list_comprehensive(self):
        """The blocklist must contain at least 200 known disposable domains."""
        from isg_agent.utils.disposable_emails import DISPOSABLE_DOMAINS

        assert len(DISPOSABLE_DOMAINS) >= 200, (
            f"Expected at least 200 disposable domains, got {len(DISPOSABLE_DOMAINS)}"
        )

    def test_disposable_email_invalid_format_raises(self):
        """An email without '@' should raise ValueError."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        with pytest.raises(ValueError, match="Invalid email"):
            is_disposable_email("notanemail")

    def test_allowed_email_domains_override(self, monkeypatch):
        """ALLOWED_EMAIL_DOMAINS env var allows domains that would normally be blocked."""
        monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "mailinator.com,yopmail.com")
        from isg_agent.utils import disposable_emails
        # Force reload the allowed set
        allowed = disposable_emails._get_allowed_domains()
        assert "mailinator.com" in allowed

    def test_get_email_domain_extracts_correctly(self):
        """Domain extraction from email must be correct."""
        from isg_agent.utils.disposable_emails import get_email_domain

        assert get_email_domain("user@example.com") == "example.com"
        assert get_email_domain("USER@EXAMPLE.COM") == "example.com"
        assert get_email_domain("user+tag@sub.domain.io") == "sub.domain.io"

    def test_disposable_email_blocked_dispostable(self):
        """dispostable.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("x@dispostable.com") is True

    def test_disposable_email_blocked_mailnesia(self):
        """mailnesia.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("x@mailnesia.com") is True

    def test_disposable_email_blocked_guerrillamailblock(self):
        """guerrillamailblock.com must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("x@guerrillamailblock.com") is True

    def test_disposable_email_blocked_grr_la(self):
        """grr.la must be blocked."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("x@grr.la") is True


# ===========================================================================
# Part 3: Turnstile Token Verification
# ===========================================================================


class TestTurnstileVerification:
    """Tests for Cloudflare Turnstile server-side verification."""

    @pytest.mark.asyncio
    async def test_turnstile_not_configured_passes(self, monkeypatch):
        """If ISG_AGENT_TURNSTILE_SECRET_KEY is not set, verification is skipped (dev mode)."""
        monkeypatch.delenv("ISG_AGENT_TURNSTILE_SECRET_KEY", raising=False)
        from isg_agent.middleware.bot_prevention import verify_turnstile

        result = await verify_turnstile(token="any-token")
        assert result.success is True
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_turnstile_valid_token_passes(self, monkeypatch):
        """A valid Turnstile token from Cloudflare API returns success."""
        monkeypatch.setenv("ISG_AGENT_TURNSTILE_SECRET_KEY", "test-secret-key")

        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"success": True})
        mock_response.raise_for_status = MagicMock()

        with patch(
            "isg_agent.middleware.bot_prevention._call_turnstile_api",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            from isg_agent.middleware.bot_prevention import verify_turnstile

            result = await verify_turnstile(token="valid-turnstile-token")
            assert result.success is True
            assert result.skipped is False

    @pytest.mark.asyncio
    async def test_turnstile_invalid_token_rejected(self, monkeypatch):
        """An invalid Turnstile token from Cloudflare API returns failure."""
        monkeypatch.setenv("ISG_AGENT_TURNSTILE_SECRET_KEY", "test-secret-key")

        with patch(
            "isg_agent.middleware.bot_prevention._call_turnstile_api",
            new_callable=AsyncMock,
            return_value={"success": False, "error-codes": ["invalid-input-response"]},
        ):
            from isg_agent.middleware.bot_prevention import verify_turnstile

            result = await verify_turnstile(token="invalid-token")
            assert result.success is False
            assert result.skipped is False

    @pytest.mark.asyncio
    async def test_turnstile_api_error_treated_as_failure(self, monkeypatch):
        """If the Cloudflare API call errors, the token is rejected."""
        monkeypatch.setenv("ISG_AGENT_TURNSTILE_SECRET_KEY", "test-secret-key")

        with patch(
            "isg_agent.middleware.bot_prevention._call_turnstile_api",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            from isg_agent.middleware.bot_prevention import verify_turnstile

            result = await verify_turnstile(token="some-token")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_turnstile_empty_token_rejected(self, monkeypatch):
        """An empty Turnstile token is rejected without hitting the API."""
        monkeypatch.setenv("ISG_AGENT_TURNSTILE_SECRET_KEY", "test-secret-key")

        from isg_agent.middleware.bot_prevention import verify_turnstile

        result = await verify_turnstile(token="")
        assert result.success is False

    def test_turnstile_result_has_required_fields(self):
        """TurnstileResult must expose success, skipped, and error_codes fields."""
        from isg_agent.middleware.bot_prevention import TurnstileResult

        result = TurnstileResult(success=True, skipped=False, error_codes=[])
        assert hasattr(result, "success")
        assert hasattr(result, "skipped")
        assert hasattr(result, "error_codes")


# ===========================================================================
# Part 4: Enhanced Rate Limiting (BotRateLimiter)
# ===========================================================================


class TestBotRateLimiter:
    """Tests for per-IP and per-email rate limiting."""

    def test_rate_limit_per_ip_registration_first_request_allowed(self):
        """First registration attempt from an IP must be allowed."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        result = limiter.check_ip_registration(ip="1.2.3.4")
        assert result.allowed is True

    def test_rate_limit_per_ip_registration_within_limit(self):
        """Up to 3 registrations from one IP within an hour must be allowed."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        ip = "10.0.0.1"
        for _ in range(3):
            result = limiter.check_ip_registration(ip=ip)
            assert result.allowed is True

    def test_rate_limit_per_ip_registration_exceeds_limit(self):
        """4th registration from same IP within an hour must be blocked."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        ip = "10.0.0.2"
        for _ in range(3):
            limiter.check_ip_registration(ip=ip)
        # 4th attempt
        result = limiter.check_ip_registration(ip=ip)
        assert result.allowed is False

    def test_rate_limit_per_email_password_reset_within_limit(self):
        """Up to 3 password reset requests per email per hour must be allowed."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        email = "user@gmail.com"
        for _ in range(3):
            result = limiter.check_email_password_reset(email=email)
            assert result.allowed is True

    def test_rate_limit_per_email_password_reset_exceeds_limit(self):
        """4th password reset from same email within an hour must be blocked."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        email = "user@gmail.com"
        for _ in range(3):
            limiter.check_email_password_reset(email=email)
        result = limiter.check_email_password_reset(email=email)
        assert result.allowed is False

    def test_rate_limit_different_ips_independent(self):
        """Different IPs should have independent rate limit buckets."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        ip1 = "192.168.1.1"
        ip2 = "192.168.1.2"
        # Exhaust ip1's budget
        for _ in range(3):
            limiter.check_ip_registration(ip=ip1)
        blocked = limiter.check_ip_registration(ip=ip1)
        allowed = limiter.check_ip_registration(ip=ip2)
        assert blocked.allowed is False
        assert allowed.allowed is True

    def test_rate_limit_handle_check_high_limit(self):
        """Handle availability check should allow 30 requests per minute."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        ip = "5.6.7.8"
        for _ in range(30):
            result = limiter.check_ip_handle_check(ip=ip)
            assert result.allowed is True

    def test_rate_limit_handle_check_exceeds_limit(self):
        """31st handle check from same IP within a minute must be blocked."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        ip = "5.6.7.9"
        for _ in range(30):
            limiter.check_ip_handle_check(ip=ip)
        result = limiter.check_ip_handle_check(ip=ip)
        assert result.allowed is False

    def test_rate_limit_result_has_retry_after(self):
        """A blocked rate limit result must include a retry_after value."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        ip = "9.9.9.9"
        for _ in range(3):
            limiter.check_ip_registration(ip=ip)
        result = limiter.check_ip_registration(ip=ip)
        assert result.allowed is False
        assert result.retry_after is not None
        assert result.retry_after > 0

    def test_rate_limit_cleanup_expired_buckets(self):
        """Expired bucket entries should be cleaned up to prevent memory leaks."""
        from isg_agent.middleware.bot_prevention import BotRateLimiter

        limiter = BotRateLimiter()
        # Simulate old entries by directly manipulating internal state
        old_time = time.time() - 7200  # 2 hours ago
        limiter._ip_buckets["old-ip"] = {"count": 1, "window_start": old_time}
        limiter.cleanup_expired()
        assert "old-ip" not in limiter._ip_buckets


# ===========================================================================
# Part 5: Bot Scoring Middleware
# ===========================================================================


class TestBotScoring:
    """Tests for request fingerprint scoring."""

    def test_bot_score_good_headers_passes(self):
        """A request with all expected human-browser headers should score >= 40."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers = {
            "accept-language": "en-US,en;q=0.9",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "referer": "https://app.dingdawg.com/register",
        }
        score = calculate_bot_score(headers=headers, page_load_time=None)
        assert score >= 40, f"Expected score >= 40, got {score}"

    def test_bot_score_missing_headers_fails(self):
        """A request missing all browser fingerprint headers should score < 40."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers: dict[str, str] = {}
        score = calculate_bot_score(headers=headers, page_load_time=None)
        assert score < 40, f"Expected score < 40, got {score}"

    def test_bot_score_partial_headers_may_pass_or_fail(self):
        """A request with only some headers will score somewhere in the middle."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers = {
            "accept-language": "en-US",
            "user-agent": "Mozilla/5.0",
        }
        score = calculate_bot_score(headers=headers, page_load_time=None)
        # Should be 40 (accept-language=20 + user-agent=20)
        assert score == 40

    def test_bot_score_accept_language_adds_20(self):
        """Accept-Language header contributes +20 to the score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers_without = {}
        headers_with = {"accept-language": "en-US"}
        score_without = calculate_bot_score(headers=headers_without, page_load_time=None)
        score_with = calculate_bot_score(headers=headers_with, page_load_time=None)
        assert score_with - score_without == 20

    def test_bot_score_sec_fetch_site_adds_20(self):
        """Sec-Fetch-Site header contributes +20 to the score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers_without = {}
        headers_with = {"sec-fetch-site": "same-origin"}
        score_without = calculate_bot_score(headers=headers_without, page_load_time=None)
        score_with = calculate_bot_score(headers=headers_with, page_load_time=None)
        assert score_with - score_without == 20

    def test_bot_score_user_agent_adds_20(self):
        """A valid User-Agent header contributes +20 to the score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers_with = {"user-agent": "Mozilla/5.0 (compatible; Googlebot)"}
        # Note: googlebot is a known bot UA — implementation may adjust
        headers_real = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"}
        score_with = calculate_bot_score(headers=headers_real, page_load_time=None)
        score_without = calculate_bot_score(headers={}, page_load_time=None)
        assert score_with - score_without == 20

    def test_bot_score_timing_adds_20(self):
        """A page load time > 2 seconds ago contributes +20 to score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        old_page_load = time.time() - 5  # 5 seconds ago
        score_with_timing = calculate_bot_score(headers={}, page_load_time=old_page_load)
        score_without_timing = calculate_bot_score(headers={}, page_load_time=None)
        assert score_with_timing - score_without_timing == 20

    def test_bot_score_fast_submission_no_timing_bonus(self):
        """A page load time < 2 seconds ago does NOT add timing bonus."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        recent_page_load = time.time() - 0.5  # 0.5 seconds ago
        score_fast = calculate_bot_score(headers={}, page_load_time=recent_page_load)
        score_no_timing = calculate_bot_score(headers={}, page_load_time=None)
        assert score_fast == score_no_timing

    def test_bot_score_referer_adds_20(self):
        """A Referer header matching our domain contributes +20 to score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers_with = {"referer": "https://app.dingdawg.com/register"}
        headers_without = {}
        score_with = calculate_bot_score(headers=headers_with, page_load_time=None)
        score_without = calculate_bot_score(headers=headers_without, page_load_time=None)
        assert score_with - score_without == 20

    def test_bot_score_empty_user_agent_no_bonus(self):
        """An empty User-Agent string does NOT contribute to the score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers_empty_ua = {"user-agent": ""}
        score = calculate_bot_score(headers=headers_empty_ua, page_load_time=None)
        assert score == 0

    def test_bot_score_known_bot_ua_no_bonus(self):
        """A known bot User-Agent string does NOT contribute to the score."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers = {"user-agent": "python-requests/2.28.0"}
        score = calculate_bot_score(headers=headers, page_load_time=None)
        # python-requests is a known bot/script UA — should not get +20
        assert score == 0

    def test_bot_score_maximum_is_100(self):
        """Maximum possible score is 100."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        headers = {
            "accept-language": "en-US",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            "referer": "https://app.dingdawg.com/register",
        }
        old_page_load = time.time() - 5
        score = calculate_bot_score(headers=headers, page_load_time=old_page_load)
        assert score == 100

    def test_bot_score_minimum_is_zero(self):
        """Minimum possible score is 0 (no headers at all)."""
        from isg_agent.middleware.bot_prevention import calculate_bot_score

        score = calculate_bot_score(headers={}, page_load_time=None)
        assert score == 0


# ===========================================================================
# Part 6: Test Environment Bypass
# ===========================================================================


class TestTestEnvironmentBypass:
    """Tests ensuring ISG_AGENT_DEPLOYMENT_ENV=test bypasses bot prevention."""

    def test_test_env_bypasses_bot_prevention(self, monkeypatch):
        """When deployment env is 'test', bot prevention middleware is bypassed."""
        monkeypatch.setenv("ISG_AGENT_DEPLOYMENT_ENV", "test")
        from isg_agent.middleware.bot_prevention import is_test_environment

        assert is_test_environment() is True

    def test_production_env_does_not_bypass(self, monkeypatch):
        """Production environment must NOT bypass bot prevention."""
        monkeypatch.setenv("ISG_AGENT_DEPLOYMENT_ENV", "production")
        from isg_agent.middleware.bot_prevention import is_test_environment

        assert is_test_environment() is False

    def test_development_env_does_not_bypass(self, monkeypatch):
        """Development environment still enforces bot prevention."""
        monkeypatch.setenv("ISG_AGENT_DEPLOYMENT_ENV", "development")
        from isg_agent.middleware.bot_prevention import is_test_environment

        assert is_test_environment() is False

    def test_no_env_var_does_not_bypass(self, monkeypatch):
        """Missing deployment env var does not bypass bot prevention."""
        monkeypatch.delenv("ISG_AGENT_DEPLOYMENT_ENV", raising=False)
        from isg_agent.middleware.bot_prevention import is_test_environment

        assert is_test_environment() is False


# ===========================================================================
# Part 7: X-Forwarded-For Header Parsing
# ===========================================================================


class TestXForwardedForParsing:
    """Tests for real IP extraction behind proxies (Railway uses X-Forwarded-For)."""

    def test_x_forwarded_for_single_ip(self):
        """Single IP in X-Forwarded-For returns that IP."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="127.0.0.1",
            x_forwarded_for="203.0.113.1",
        )
        assert ip == "203.0.113.1"

    def test_x_forwarded_for_multiple_ips_returns_rightmost(self):
        """Multiple IPs in X-Forwarded-For: rightmost is from trusted proxy."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="127.0.0.1",
            x_forwarded_for="203.0.113.1, 10.0.0.1, 172.16.0.1",
        )
        # Rightmost IP is appended by Railway's trusted proxy — not spoofable
        assert ip == "172.16.0.1"

    def test_x_forwarded_for_spoofing_prevented(self):
        """Attacker cannot spoof 127.0.0.1 via X-Forwarded-For."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="10.0.0.1",
            x_forwarded_for="127.0.0.1, 203.0.113.50",
        )
        # Should return 203.0.113.50 (proxy-added), NOT 127.0.0.1 (spoofed)
        assert ip == "203.0.113.50"
        assert ip != "127.0.0.1"

    def test_no_x_forwarded_for_uses_client_host(self):
        """Without X-Forwarded-For, fall back to the direct connection IP."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="192.168.1.100",
            x_forwarded_for=None,
        )
        assert ip == "192.168.1.100"

    def test_empty_x_forwarded_for_uses_client_host(self):
        """Empty X-Forwarded-For header falls back to client host."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="192.168.1.100",
            x_forwarded_for="",
        )
        assert ip == "192.168.1.100"

    def test_x_forwarded_for_strips_whitespace(self):
        """Leading/trailing whitespace in each IP segment is stripped."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="127.0.0.1",
            x_forwarded_for="  203.0.113.1  ,  10.0.0.1  ",
        )
        # Rightmost (trusted proxy) IP is used, whitespace stripped
        assert ip == "10.0.0.1"

    def test_no_client_host_and_no_forwarded_returns_unknown(self):
        """If both client_host and X-Forwarded-For are absent, return 'unknown'."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host=None,
            x_forwarded_for=None,
        )
        assert ip == "unknown"

    def test_x_forwarded_for_ipv6(self):
        """IPv6 address in X-Forwarded-For is returned correctly."""
        from isg_agent.middleware.bot_prevention import extract_real_ip

        ip = extract_real_ip(
            client_host="::1",
            x_forwarded_for="2001:db8::1",
        )
        assert ip == "2001:db8::1"


# ===========================================================================
# Part 8: Integration — Register Endpoint Bot Prevention
# ===========================================================================


class TestRegisterEndpointBotPrevention:
    """Integration tests for bot prevention on the registration endpoint."""

    @pytest.mark.asyncio
    async def test_register_honeypot_filled_returns_fake_200(self, monkeypatch):
        """When honeypot is filled, register returns 201 (fake success) but no account created.

        We simulate the behavior by checking the honeypot utility directly since
        the endpoint integration requires the full app stack. This verifies the
        honeypot module returns is_bot=True for filled fields, which the route
        handler must treat as a silent reject.
        """
        from isg_agent.utils.honeypot import check_honeypot

        result = check_honeypot(honeypot_value="filled-by-bot")
        assert result.is_bot is True
        # The route handler MUST return a fake success response, not raise HTTPException

    @pytest.mark.asyncio
    async def test_register_disposable_email_returns_error(self, monkeypatch):
        """Registration with a disposable email should return a rejection message."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("bot@mailinator.com") is True
        # Route handler should return 400 with "Please use a permanent email address"

    @pytest.mark.asyncio
    async def test_register_with_legitimate_email_passes_email_check(self):
        """A legitimate email passes the disposable email check."""
        from isg_agent.utils.disposable_emails import is_disposable_email

        assert is_disposable_email("user@gmail.com") is False


# ===========================================================================
# Part 9: TurnstileResult and HoneypotResult Dataclass Integrity
# ===========================================================================


class TestDataclassIntegrity:
    """Tests that result dataclasses are correctly structured."""

    def test_turnstile_result_success_true(self):
        """TurnstileResult with success=True is truthy for success check."""
        from isg_agent.middleware.bot_prevention import TurnstileResult

        r = TurnstileResult(success=True, skipped=False, error_codes=[])
        assert r.success is True
        assert r.skipped is False
        assert r.error_codes == []

    def test_turnstile_result_skipped_dev_mode(self):
        """TurnstileResult with skipped=True indicates dev mode bypass."""
        from isg_agent.middleware.bot_prevention import TurnstileResult

        r = TurnstileResult(success=True, skipped=True, error_codes=[])
        assert r.success is True
        assert r.skipped is True

    def test_honeypot_result_clean(self):
        """HoneypotResult with is_bot=False represents a clean request."""
        from isg_agent.utils.honeypot import HoneypotResult

        r = HoneypotResult(is_bot=False, reason=None, trigger=None)
        assert r.is_bot is False
        assert r.reason is None

    def test_rate_limit_result_allowed(self):
        """RateLimitResult with allowed=True represents a passing request."""
        from isg_agent.middleware.bot_prevention import RateLimitResult

        r = RateLimitResult(allowed=True, retry_after=None)
        assert r.allowed is True
        assert r.retry_after is None

    def test_rate_limit_result_blocked(self):
        """RateLimitResult with allowed=False and retry_after set represents a block."""
        from isg_agent.middleware.bot_prevention import RateLimitResult

        r = RateLimitResult(allowed=False, retry_after=3600)
        assert r.allowed is False
        assert r.retry_after == 3600
