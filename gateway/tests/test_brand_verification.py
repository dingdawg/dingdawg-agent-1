"""Tests for the multi-signal brand verification engine.

Categories
----------
1.  Pattern blocking expanded            (~10 tests)
2.  Request lifecycle                    (~10 tests)
3.  Free-email domain detection          (~6 tests)
4.  Email verification                   (~8 tests)
5.  DNS verification                     (~5 tests)
6.  Meta tag verification                (~5 tests)
7.  Social proof                         (~3 tests)
8.  Auto-approval scoring                (~5 tests)
9.  Admin approve / deny                 (~4 tests)
10. API routes                           (~10 tests)
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.agents.brand_verification import BrandVerificationService
from isg_agent.agents.handle_service import HandleService
from isg_agent.agents.reserved_handles import (
    BLOCKED_SUBSTRINGS,
    BRAND_PATTERN_SUBSTRINGS,
    is_blocked_by_pattern,
    is_brand_pattern_blocked,
)
from isg_agent.config import get_settings

_SECRET = "test-secret-brand-suite"


# ===========================================================================
# 1. Pattern blocking — expanded BRAND_PATTERN_SUBSTRINGS
# ===========================================================================


class TestBrandPatternSubstrings:
    """BRAND_PATTERN_SUBSTRINGS covers major recognisable brands."""

    def test_brand_pattern_substrings_is_tuple(self) -> None:
        assert isinstance(BRAND_PATTERN_SUBSTRINGS, tuple)

    def test_brand_pattern_substrings_minimum_count(self) -> None:
        assert len(BRAND_PATTERN_SUBSTRINGS) >= 80, (
            f"Expected >= 80 brand patterns, got {len(BRAND_PATTERN_SUBSTRINGS)}"
        )

    @pytest.mark.parametrize(
        "brand",
        [
            "walmart", "mcdonalds", "starbucks", "nike", "tesla",
            "doordash", "netflix", "spotify", "instagram", "tiktok",
            "youtube", "facebook", "microsoft", "amazon", "google",
            "paypal", "coinbase", "robinhood", "fortnite", "roblox",
            "minecraft", "playstation", "nintendo", "peloton", "fitbit",
            "strava", "verizon", "comcast", "shopify", "salesforce",
            "hubspot", "figma", "canva", "adobe",
        ],
    )
    def test_major_brand_in_pattern_list(self, brand: str) -> None:
        assert brand in BRAND_PATTERN_SUBSTRINGS, (
            f"Brand {brand!r} should be in BRAND_PATTERN_SUBSTRINGS"
        )

    @pytest.mark.parametrize(
        "handle",
        [
            "walmart-official",
            "my-nike-store",
            "tesla-fan-club",
            "doordash-delivery",
            "starbucks-lover",
            "instagram-marketing",
            "tiktok-creator",
            "youtube-channel",
            "microsoft-partner",
            "google-workspace",
        ],
    )
    def test_brand_handles_are_blocked(self, handle: str) -> None:
        valid, reason = HandleService.validate_handle(handle)
        assert valid is False, f"Expected {handle!r} to be rejected"

    @pytest.mark.parametrize(
        "handle",
        [
            "joes-pizza",
            "cool-bot-123",
            "my-restaurant-agent",
            "downtown-barber",
            "fresh-bakery-co",
            "river-guide-tours",
            "sunset-photography",
            "peak-fitness-pro",
        ],
    )
    def test_legitimate_handles_are_allowed(self, handle: str) -> None:
        valid, _ = HandleService.validate_handle(handle)
        assert valid is True, f"Expected {handle!r} to be allowed"

    def test_brand_block_returns_verification_message(self) -> None:
        valid, reason = HandleService.validate_handle("my-nike-outlet")
        assert valid is False
        assert "brand verification" in reason.lower() or "verify-brand" in reason.lower()

    def test_core_brand_block_returns_reserved_message(self) -> None:
        valid, reason = HandleService.validate_handle("my-dingdawg-agent")
        assert valid is False
        assert "reserved" in reason.lower()

    def test_is_brand_pattern_blocked_true_for_third_party(self) -> None:
        assert is_brand_pattern_blocked("nike-store") is True

    def test_is_brand_pattern_blocked_false_for_core_brand(self) -> None:
        assert is_brand_pattern_blocked("my-dingdawg-bot") is False

    def test_is_brand_pattern_blocked_false_for_clean_handle(self) -> None:
        assert is_brand_pattern_blocked("joes-pizza") is False

    def test_blocked_substrings_unchanged(self) -> None:
        for term in ("dingdawg", "ding-dawg", "dingdog", "openai", "chatgpt", "anthropic"):
            assert term in BLOCKED_SUBSTRINGS


# ===========================================================================
# 2. Verification request lifecycle
# ===========================================================================


class TestBrandVerificationLifecycle:
    """BrandVerificationService submit / get / list lifecycle."""

    async def test_submit_request_returns_tokens_and_instructions(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.submit_request(
                handle="nike-downtown-store",
                requester_email="legal@nike.com",
                company_name="Nike Inc.",
                company_domain="nike.com",
            )
            assert result["status"] == "pending"
            assert len(result["request_id"]) == 36
            assert result["dns_token"]
            assert result["meta_token"]
            assert result["email_verification_available"] is True
            assert "nike.com" in result["dns_instructions"]
            assert "dingdawg-verify" in result["meta_instructions"]
        finally:
            await svc.close()

    async def test_submit_without_domain_has_no_instructions(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            assert result["email_verification_available"] is False
            assert result["dns_instructions"] is None
            assert result["meta_instructions"] is None
        finally:
            await svc.close()

    async def test_submit_invalid_email_raises(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="Invalid email"):
                await svc.submit_request(
                    handle="nike-store",
                    requester_email="not-an-email",
                    company_name="Nike",
                )
        finally:
            await svc.close()

    async def test_submit_non_brand_handle_raises(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="not brand-protected"):
                await svc.submit_request(
                    handle="joes-pizza",
                    requester_email="joe@example.com",
                    company_name="Joe's Pizza",
                )
        finally:
            await svc.close()

    async def test_submit_core_brand_block_raises(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="core DingDawg term"):
                await svc.submit_request(
                    handle="my-dingdawg-bot",
                    requester_email="someone@example.com",
                    company_name="Someone",
                )
        finally:
            await svc.close()

    async def test_duplicate_pending_request_raises(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            with pytest.raises(ValueError, match="already exists"):
                await svc.submit_request(
                    handle="nike-store",
                    requester_email="legal@nike.com",
                    company_name="Nike",
                )
        finally:
            await svc.close()

    async def test_get_request_by_id(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            record = await svc.get_request(submitted["request_id"])
            assert record is not None
            assert record["handle"] == "nike-store"
            assert record["status"] == "pending"
            assert record["company_domain"] == "nike.com"
        finally:
            await svc.close()

    async def test_get_request_not_found_returns_none(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.get_request("00000000-0000-0000-0000-000000000000")
            assert result is None
        finally:
            await svc.close()

    async def test_list_requests_returns_submitted(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            await svc.submit_request("nike-store", "a@nike.com", "Nike")
            await svc.submit_request("walmart-official", "b@walmart.com", "Walmart")
            records = await svc.list_requests(status="pending")
            assert len(records) == 2
        finally:
            await svc.close()

    async def test_get_status_excludes_tokens(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike Inc.",
                company_domain="nike.com",
            )
            public = await svc.get_status(submitted["request_id"])
            assert public is not None
            assert "dns_token" not in public
            assert "meta_token" not in public
            assert "email_code" not in public
            assert public["request_id"] == submitted["request_id"]
            assert "Nike" in public["company_name_masked"]
        finally:
            await svc.close()


# ===========================================================================
# 3. Free-email domain detection
# ===========================================================================


class TestFreeEmailDetection:
    """BrandVerificationService._is_free_email and initiate_email_verification rejection."""

    @pytest.mark.parametrize(
        "email",
        [
            "user@gmail.com",
            "user@yahoo.com",
            "user@hotmail.com",
            "user@outlook.com",
            "user@icloud.com",
            "user@protonmail.com",
            "user@proton.me",
        ],
    )
    def test_is_free_email_true(self, email: str) -> None:
        assert BrandVerificationService._is_free_email(email) is True

    @pytest.mark.parametrize(
        "email",
        [
            "legal@nike.com",
            "ops@walmart.com",
            "info@tesla.com",
        ],
    )
    def test_is_free_email_false_for_corporate(self, email: str) -> None:
        assert BrandVerificationService._is_free_email(email) is False

    async def test_initiate_email_rejects_gmail(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            with pytest.raises(ValueError, match="Free email providers"):
                await svc.initiate_email_verification(
                    request_id=submitted["request_id"],
                    target_email="someone@gmail.com",
                )
        finally:
            await svc.close()

    async def test_initiate_email_rejects_domain_mismatch(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            with pytest.raises(ValueError, match="does not match"):
                await svc.initiate_email_verification(
                    request_id=submitted["request_id"],
                    target_email="someone@otherdomain.com",
                )
        finally:
            await svc.close()


# ===========================================================================
# 4. Email verification
# ===========================================================================


class TestEmailVerification:
    """Email code send / verify lifecycle."""

    async def test_initiate_email_returns_masked_email(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            result = await svc.initiate_email_verification(
                request_id=submitted["request_id"]
            )
            assert result["sent"] is True
            assert result["email_masked"] == "l***@nike.com"
            assert result["expires_in"] == 600
        finally:
            await svc.close()

    async def test_verify_correct_code_adds_30_pts(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)

            # Read the code directly from DB to simulate correct entry
            record = await svc.get_request(rid)
            code = record["email_code"]

            result = await svc.verify_email_code(request_id=rid, code=code)
            assert result["verified"] is True
            assert result["score"] == 30
            assert result["auto_approved"] is False  # 30 < 60 threshold
        finally:
            await svc.close()

    async def test_verify_wrong_code_fails(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)

            result = await svc.verify_email_code(request_id=rid, code="000000")
            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_expired_code_rejected(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)

            # Backdate expiry to the past
            from datetime import datetime, timedelta, timezone
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            async with svc._db() as db:
                record = await svc.get_request(rid)
                code = record["email_code"]
                await db.execute(
                    "UPDATE brand_verifications SET email_code_expires = ? WHERE id = ?",
                    (past, rid),
                )
                await db.commit()

            result = await svc.verify_email_code(request_id=rid, code=code)
            assert result["verified"] is False
            assert "expired" in result.get("error", "").lower()
        finally:
            await svc.close()

    async def test_max_attempts_enforced(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            # Exhaust attempts by calling 5 times
            for _ in range(5):
                try:
                    await svc.initiate_email_verification(request_id=rid)
                except ValueError:
                    break

            with pytest.raises(ValueError, match="Maximum email verification attempts"):
                await svc.initiate_email_verification(request_id=rid)
        finally:
            await svc.close()

    async def test_email_signal_is_idempotent(self) -> None:
        """Verifying email twice does not double-count points."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)
            code = record["email_code"]

            r1 = await svc.verify_email_code(request_id=rid, code=code)
            assert r1["score"] == 30

            # Second verify attempt — already completed
            r2 = await svc.verify_email_code(request_id=rid, code=code)
            assert r2["verified"] is False
            assert r2["score"] == 30  # no double-counting
        finally:
            await svc.close()

    async def test_initiate_without_domain_raises(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                # No company_domain
            )
            with pytest.raises(ValueError, match="company_domain is required"):
                await svc.initiate_email_verification(
                    request_id=submitted["request_id"]
                )
        finally:
            await svc.close()

    async def test_verify_on_approved_request_returns_unverified(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.admin_approve(rid)

            result = await svc.verify_email_code(request_id=rid, code="123456")
            assert result["verified"] is False
            assert result["status"] == "approved"
        finally:
            await svc.close()


# ===========================================================================
# 5. DNS verification
# ===========================================================================


class TestDnsVerification:
    """DNS TXT record checking with mocked subprocess."""

    async def test_dns_check_success_adds_30_pts(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            record = await svc.get_request(rid)
            dns_token = record["dns_token"]

            mock_result = MagicMock()
            mock_result.stdout = f'"{dns_token}"\n'
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result):
                result = await svc.check_dns_verification(request_id=rid)

            assert result["verified"] is True
            assert result["score"] == 30
            assert result["record_found"] is True
            assert result["auto_approved"] is False
        finally:
            await svc.close()

    async def test_dns_check_no_record_returns_false(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result):
                result = await svc.check_dns_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
            assert result["record_found"] is False
        finally:
            await svc.close()

    async def test_dns_check_timeout_handled_gracefully(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            import subprocess as _sp
            with patch("subprocess.run", side_effect=_sp.TimeoutExpired("dig", 5)):
                result = await svc.check_dns_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_dns_check_dig_not_found_handled(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            with patch("subprocess.run", side_effect=FileNotFoundError):
                result = await svc.check_dns_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_dns_check_without_domain_returns_error(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                # No company_domain
            )
            rid = submitted["request_id"]
            result = await svc.check_dns_verification(request_id=rid)
            assert result["verified"] is False
            assert "error" in result
        finally:
            await svc.close()


# ===========================================================================
# 6. Meta tag verification
# ===========================================================================


class TestMetaTagVerification:
    """Website meta tag checking with mocked urllib."""

    async def test_meta_check_success_adds_20_pts(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            record = await svc.get_request(rid)
            meta_token = record["meta_token"]

            html = (
                f'<html><head>'
                f'<meta name="dingdawg-verify" content="{meta_token}">'
                f'</head><body>Nike</body></html>'
            )

            mock_response = MagicMock()
            mock_response.read.return_value = html.encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is True
            assert result["score"] == 20
            assert result["auto_approved"] is False
        finally:
            await svc.close()

    async def test_meta_check_tag_not_found_returns_false(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            html = "<html><head><title>Nike</title></head><body></body></html>"
            mock_response = MagicMock()
            mock_response.read.return_value = html.encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_meta_check_timeout_handled_gracefully(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            import socket
            with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_meta_check_wrong_token_returns_false(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Page has wrong token value
            html = '<meta name="dingdawg-verify" content="wrong-token-here">'
            mock_response = MagicMock()
            mock_response.read.return_value = html.encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
        finally:
            await svc.close()

    async def test_meta_check_without_domain_returns_error(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                # No company_domain
            )
            rid = submitted["request_id"]
            result = await svc.check_meta_verification(request_id=rid)
            assert result["verified"] is False
            assert "error" in result
        finally:
            await svc.close()


# ===========================================================================
# 7. Social proof
# ===========================================================================


class TestSocialProof:
    """Social media link submission and scoring."""

    async def test_two_or_more_links_adds_10_pts(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            result = await svc.check_social_proof(
                request_id=rid,
                social_links={
                    "twitter": "https://twitter.com/nike",
                    "instagram": "https://instagram.com/nike",
                },
            )
            assert result["recorded"] is True
            assert result["score"] == 10
            assert result["links_count"] == 2
        finally:
            await svc.close()

    async def test_one_link_adds_0_pts(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            result = await svc.check_social_proof(
                request_id=rid,
                social_links={"twitter": "https://twitter.com/nike"},
            )
            assert result["recorded"] is True
            assert result["score"] == 0
            assert result["links_count"] == 1
        finally:
            await svc.close()

    async def test_empty_links_adds_0_pts(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            result = await svc.check_social_proof(
                request_id=rid,
                social_links={},
            )
            assert result["recorded"] is True
            assert result["score"] == 0
            assert result["links_count"] == 0
        finally:
            await svc.close()


# ===========================================================================
# 8. Auto-approval scoring
# ===========================================================================


class TestAutoApproval:
    """Score-based auto-approval logic."""

    async def test_email_plus_dns_equals_60_auto_approves(self) -> None:
        """30 (email) + 30 (DNS) = 60 → auto-approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Simulate email verification
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)
            code = record["email_code"]
            email_result = await svc.verify_email_code(request_id=rid, code=code)
            assert email_result["score"] == 30
            assert email_result["auto_approved"] is False

            # Simulate DNS verification
            dns_token = record["dns_token"]
            mock_result = MagicMock()
            mock_result.stdout = f'"{dns_token}"\n'
            with patch("subprocess.run", return_value=mock_result):
                dns_result = await svc.check_dns_verification(request_id=rid)

            assert dns_result["score"] == 60
            assert dns_result["auto_approved"] is True

            # Confirm status is approved
            final = await svc.get_request(rid)
            assert final["status"] == "approved"
        finally:
            await svc.close()

    async def test_email_plus_meta_plus_social_equals_60_auto_approves(self) -> None:
        """30 (email) + 20 (meta) + 10 (social) = 60 → auto-approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            record = await svc.get_request(rid)

            # Email signal
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)
            await svc.verify_email_code(request_id=rid, code=record["email_code"])

            # Meta signal
            meta_token = record["meta_token"]
            html = f'<meta name="dingdawg-verify" content="{meta_token}">'
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                meta_result = await svc.check_meta_verification(request_id=rid)
            assert meta_result["score"] == 50
            assert meta_result["auto_approved"] is False

            # Social signal — pushes to 60
            social_result = await svc.check_social_proof(
                request_id=rid,
                social_links={
                    "twitter": "https://twitter.com/nike",
                    "linkedin": "https://linkedin.com/company/nike",
                },
            )
            assert social_result["score"] == 60

            final = await svc.get_request(rid)
            assert final["status"] == "approved"
        finally:
            await svc.close()

    async def test_email_alone_is_30_pending_review(self) -> None:
        """30 pts alone → pending review, NOT auto-approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)

            result = await svc.verify_email_code(request_id=rid, code=record["email_code"])
            assert result["score"] == 30
            assert result["auto_approved"] is False

            final = await svc.get_request(rid)
            assert final["status"] != "approved"
        finally:
            await svc.close()

    async def test_dns_alone_is_30_pending_review(self) -> None:
        """30 pts DNS alone → pending review, NOT auto-approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            record = await svc.get_request(rid)
            dns_token = record["dns_token"]

            mock_result = MagicMock()
            mock_result.stdout = f'"{dns_token}"\n'
            with patch("subprocess.run", return_value=mock_result):
                result = await svc.check_dns_verification(request_id=rid)

            assert result["score"] == 30
            assert result["auto_approved"] is False
        finally:
            await svc.close()

    async def test_admin_approve_always_approves(self) -> None:
        """Admin override awards 100 pts and sets status to approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            rid = submitted["request_id"]
            result = await svc.admin_approve(rid, admin_notes="Verified via legal docs")
            assert result["approved"] is True
            assert result["handle"] == "nike-store"

            final = await svc.get_request(rid)
            assert final["status"] == "approved"
            assert final["admin_notes"] == "Verified via legal docs"
            assert final["verification_score"] >= 100
        finally:
            await svc.close()


# ===========================================================================
# 9. Admin approve / deny
# ===========================================================================


class TestAdminActions:
    """Admin approve and deny operations."""

    async def test_admin_approve_sets_status(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            rid = submitted["request_id"]
            result = await svc.admin_approve(
                rid,
                admin_notes="Approved after review",
                reviewed_by="admin-42",
            )
            assert result["approved"] is True
            record = await svc.get_request(rid)
            assert record["status"] == "approved"
            assert record["reviewed_by"] == "admin-42"
            assert record["approved_at"] is not None
        finally:
            await svc.close()

    async def test_admin_deny_sets_status(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            rid = submitted["request_id"]
            result = await svc.admin_deny(
                rid,
                admin_notes="Cannot verify identity",
                reviewed_by="admin-42",
            )
            assert result["denied"] is True
            record = await svc.get_request(rid)
            assert record["status"] == "denied"
            assert record["admin_notes"] == "Cannot verify identity"
        finally:
            await svc.close()

    async def test_admin_deny_nonexistent_returns_false(self) -> None:
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.admin_deny("00000000-0000-0000-0000-000000000000")
            assert result["denied"] is False
        finally:
            await svc.close()

    async def test_compat_approve_request_returns_bool(self) -> None:
        """approve_request() backwards-compat alias returns bool."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            ok = await svc.approve_request(submitted["request_id"])
            assert ok is True
        finally:
            await svc.close()


# ===========================================================================
# 10. API routes — fixture with full lifespan
# ===========================================================================


@pytest_asyncio.fixture
async def bv_client(tmp_path):
    """Async HTTP client with full app lifespan (app.state populated)."""
    db_file = str(tmp_path / "test_bv.db")
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    get_settings.cache_clear()


class TestBrandVerificationAPI:
    """HTTP-level tests for the brand verification endpoints."""

    async def test_post_verify_brand_returns_201_with_tokens(self, bv_client) -> None:
        response = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "nike-downtown",
                "requester_email": "legal@nike.com",
                "company_name": "Nike Inc.",
                "company_domain": "nike.com",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "pending"
        assert "request_id" in data
        assert data["dns_token"]
        assert data["meta_token"]
        assert data["email_verification_available"] is True
        assert "nike.com" in data["dns_instructions"]

    async def test_post_verify_brand_invalid_email_returns_400(self, bv_client) -> None:
        response = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "nike-downtown",
                "requester_email": "not-an-email",
                "company_name": "Nike",
            },
        )
        assert response.status_code == 400, response.text

    async def test_post_verify_brand_missing_company_name_returns_422(self, bv_client) -> None:
        response = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "nike-downtown",
                "requester_email": "legal@nike.com",
            },
        )
        assert response.status_code == 422, response.text

    async def test_post_verify_brand_non_brand_handle_returns_400(self, bv_client) -> None:
        response = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "joes-pizza",
                "requester_email": "joe@example.com",
                "company_name": "Joe's Pizza",
            },
        )
        assert response.status_code == 400, response.text

    async def test_post_email_sends_code(self, bv_client) -> None:
        submit = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "nike-downtown",
                "requester_email": "legal@nike.com",
                "company_name": "Nike Inc.",
                "company_domain": "nike.com",
            },
        )
        assert submit.status_code == 201
        rid = submit.json()["request_id"]

        response = await bv_client.post(
            f"/api/v1/handles/verify-brand/{rid}/email",
            json={},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["sent"] is True
        assert "***" in data["email_masked"]
        assert data["expires_in"] == 600

    async def test_post_email_verify_correct_code(self, bv_client) -> None:
        submit = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "walmart-store",
                "requester_email": "legal@walmart.com",
                "company_name": "Walmart Inc.",
                "company_domain": "walmart.com",
            },
        )
        assert submit.status_code == 201
        rid = submit.json()["request_id"]

        await bv_client.post(f"/api/v1/handles/verify-brand/{rid}/email", json={})

        # Read code from the service directly for test verification
        svc = bv_client._transport.app.state.brand_verification_service
        record = await svc.get_request(rid)
        code = record["email_code"]

        response = await bv_client.post(
            f"/api/v1/handles/verify-brand/{rid}/email/verify",
            json={"code": code},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["verified"] is True
        assert data["score"] == 30

    async def test_post_dns_check_returns_result(self, bv_client) -> None:
        submit = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "tesla-fan",
                "requester_email": "fan@tesla.com",
                "company_name": "Tesla Inc.",
                "company_domain": "tesla.com",
            },
        )
        assert submit.status_code == 201
        rid = submit.json()["request_id"]

        mock_run = MagicMock()
        mock_run.stdout = ""
        with patch("subprocess.run", return_value=mock_run):
            response = await bv_client.post(
                f"/api/v1/handles/verify-brand/{rid}/dns/check"
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "verified" in data
        assert "score" in data

    async def test_get_status_returns_public_safe_info(self, bv_client) -> None:
        submit = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "walmart-store",
                "requester_email": "legal@walmart.com",
                "company_name": "Walmart Inc.",
                "company_domain": "walmart.com",
            },
        )
        assert submit.status_code == 201
        rid = submit.json()["request_id"]

        response = await bv_client.get(
            f"/api/v1/handles/verify-brand/{rid}/status"
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["request_id"] == rid
        assert data["status"] == "pending"
        assert "dns_token" not in data
        assert "meta_token" not in data
        assert "email_code" not in data
        assert "signals_completed" in data
        assert "verification_score" in data

    async def test_get_status_not_found_returns_404(self, bv_client) -> None:
        response = await bv_client.get(
            "/api/v1/handles/verify-brand/00000000-0000-0000-0000-000000000000/status"
        )
        assert response.status_code == 404, response.text

    async def test_post_duplicate_returns_400(self, bv_client) -> None:
        payload = {
            "handle": "spotify-artist",
            "requester_email": "legal@spotify.com",
            "company_name": "Spotify AB",
        }
        r1 = await bv_client.post("/api/v1/handles/verify-brand", json=payload)
        assert r1.status_code == 201
        r2 = await bv_client.post("/api/v1/handles/verify-brand", json=payload)
        assert r2.status_code == 400

    async def test_admin_list_without_auth_returns_401(self, bv_client) -> None:
        response = await bv_client.get("/api/v1/admin/brand-verifications")
        assert response.status_code == 401, response.text

    async def test_admin_approve_with_admin_returns_200(self, bv_client) -> None:
        post = await bv_client.post(
            "/api/v1/handles/verify-brand",
            json={
                "handle": "tesla-fan",
                "requester_email": "fan@example.com",
                "company_name": "Tesla Fans",
            },
        )
        assert post.status_code == 201
        request_id = post.json()["request_id"]

        await bv_client.post(
            "/auth/register",
            json={"email": "admin2@dingdawg.com", "password": "AdminPass2!", "terms_accepted": True},
        )
        # Auto-verify email so login succeeds (email verification gate)
        import aiosqlite as _aiosqlite
        _db_path = os.environ.get("ISG_AGENT_DB_PATH", "")
        if _db_path:
            async with _aiosqlite.connect(_db_path) as _db:
                await _db.execute("UPDATE users SET email_verified=1 WHERE email=?", ("admin2@dingdawg.com",))
                await _db.commit()
        login = await bv_client.post(
            "/auth/login",
            json={"email": "admin2@dingdawg.com", "password": "AdminPass2!"},
        )
        token = login.json()["access_token"]

        old = os.environ.get("ISG_AGENT_ADMIN_EMAIL")
        os.environ["ISG_AGENT_ADMIN_EMAIL"] = "admin2@dingdawg.com"
        try:
            resp = await bv_client.post(
                f"/api/v1/admin/brand-verifications/{request_id}/approve",
                json={"admin_notes": "Verified"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["approved"] is True
            assert data["handle"] == "tesla-fan"
        finally:
            if old is None:
                os.environ.pop("ISG_AGENT_ADMIN_EMAIL", None)
            else:
                os.environ["ISG_AGENT_ADMIN_EMAIL"] = old


# ===========================================================================
# 11. Security — SQL injection attempts
# ===========================================================================


class TestSQLInjectionAttempts:
    """Parameterised queries must neutralise SQL injection payloads."""

    @pytest.mark.parametrize(
        "malicious_handle",
        [
            "nike-store'; DROP TABLE brand_verifications;--",
            "nike-store' OR '1'='1",
            "nike-store' UNION SELECT * FROM brand_verifications--",
            'nike-store"; DROP TABLE brand_verifications;--',
        ],
    )
    async def test_sqli_in_handle_is_safe(self, malicious_handle: str) -> None:
        """SQL injection payloads in handle field are stored as literal text.

        The handle contains 'nike' which triggers brand-pattern blocking,
        so submit_request accepts it. The injection payload is neutralised
        by parameterised queries — the malicious string is stored verbatim
        as data, not executed as SQL.
        """
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.submit_request(
                handle=malicious_handle,
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            # The injection payload was stored safely as literal text
            record = await svc.get_request(result["request_id"])
            assert record is not None
            assert record["handle"] == malicious_handle

            # DB is still healthy — tables not dropped, data intact
            records = await svc.list_requests()
            assert isinstance(records, list)
            assert len(records) == 1
        finally:
            await svc.close()

    @pytest.mark.parametrize(
        "malicious_name",
        [
            "Nike'; DROP TABLE brand_verifications;--",
            "Nike' OR '1'='1",
            "Nike' UNION SELECT * FROM users--",
        ],
    )
    async def test_sqli_in_company_name_stored_safely(self, malicious_name: str) -> None:
        """SQL injection in company_name is stored as literal text via parameterised queries."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name=malicious_name,
                company_domain="nike.com",
            )
            record = await svc.get_request(result["request_id"])
            assert record is not None
            # The malicious string is stored verbatim — not executed as SQL
            assert record["company_name"] == malicious_name.strip()
            # DB is still functional
            records = await svc.list_requests()
            assert len(records) == 1
        finally:
            await svc.close()

    @pytest.mark.parametrize(
        "malicious_evidence",
        [
            "'; DELETE FROM brand_verifications WHERE '1'='1",
            "Robert'); DROP TABLE brand_verifications;--",
        ],
    )
    async def test_sqli_in_evidence_text_stored_safely(self, malicious_evidence: str) -> None:
        """SQL injection in evidence_text is stored as literal text."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
                evidence_text=malicious_evidence,
            )
            record = await svc.get_request(result["request_id"])
            assert record is not None
            assert record["evidence_text"] == malicious_evidence.strip()
        finally:
            await svc.close()


# ===========================================================================
# 12. Long input handling (>1000 chars)
# ===========================================================================


class TestLongInputs:
    """Very long strings must not crash the service or corrupt the DB."""

    async def test_long_company_name_accepted(self) -> None:
        """Company name of 2000 chars is stored without truncation or crash."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            long_name = "A" * 2000
            result = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name=long_name,
                company_domain="nike.com",
            )
            record = await svc.get_request(result["request_id"])
            assert record is not None
            assert record["company_name"] == long_name
        finally:
            await svc.close()

    async def test_long_evidence_text_accepted(self) -> None:
        """Evidence text of 5000 chars is stored without crash."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            long_evidence = "This is evidence. " * 300  # ~5400 chars
            result = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
                evidence_text=long_evidence,
            )
            record = await svc.get_request(result["request_id"])
            assert record is not None
            assert len(record["evidence_text"]) > 1000
        finally:
            await svc.close()

    async def test_long_admin_notes_accepted(self) -> None:
        """Admin notes of 3000 chars stored safely."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            long_notes = "Review note. " * 250  # ~3250 chars
            result = await svc.admin_approve(
                submitted["request_id"],
                admin_notes=long_notes,
                reviewed_by="admin-1",
            )
            assert result["approved"] is True
            record = await svc.get_request(submitted["request_id"])
            assert len(record["admin_notes"]) > 1000
        finally:
            await svc.close()

    async def test_long_social_links_accepted(self) -> None:
        """Social links with very long URLs stored without crash."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            long_url = "https://twitter.com/" + "a" * 1500
            result = await svc.check_social_proof(
                request_id=submitted["request_id"],
                social_links={
                    "twitter": long_url,
                    "linkedin": "https://linkedin.com/company/nike",
                },
            )
            assert result["recorded"] is True
            assert result["links_count"] == 2
        finally:
            await svc.close()


# ===========================================================================
# 13. Concurrent verification requests
# ===========================================================================


class TestConcurrentRequests:
    """Concurrent operations on the same handle must not corrupt data."""

    async def test_multiple_submits_for_different_emails(self) -> None:
        """Two different emails can request verification for the same brand handle.

        Note: truly concurrent writes to in-memory SQLite with shared
        cache hit table-level locks. File-backed SQLite in production
        uses WAL for concurrency. We test rapid sequential submissions.
        """
        svc = BrandVerificationService(db_path=":memory:")
        try:
            r1 = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike Legal",
            )
            r2 = await svc.submit_request(
                handle="nike-store",
                requester_email="marketing@nike.com",
                company_name="Nike Marketing",
            )
            assert r1["request_id"] != r2["request_id"]

            # Both should exist
            records = await svc.list_requests()
            assert len(records) == 2
        finally:
            await svc.close()

    async def test_sequential_signal_additions_maintain_consistency(self) -> None:
        """Multiple signal additions in rapid sequence must not lose data.

        Note: true concurrent writes to in-memory SQLite shared cache
        hit 'table is locked' even with busy_timeout — this is an SQLite
        limitation, not a service bug. File-backed SQLite in production
        handles concurrency via WAL. We test rapid sequential operations
        to verify data consistency.
        """
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Add social proof (10 pts), then initiate email immediately after
            social_result = await svc.check_social_proof(
                request_id=rid,
                social_links={
                    "twitter": "https://twitter.com/nike",
                    "linkedin": "https://linkedin.com/company/nike",
                },
            )
            email_result = await svc.initiate_email_verification(request_id=rid)

            assert social_result["recorded"] is True
            assert social_result["score"] == 10
            assert email_result["sent"] is True

            # DB should be consistent — both operations recorded
            record = await svc.get_request(rid)
            assert record is not None
            assert record["verification_score"] == 10
            assert record["email_code"] is not None
        finally:
            await svc.close()


# ===========================================================================
# 14. Email verification — expired codes with correct code value
# ===========================================================================


class TestEmailExpiredCodes:
    """Expired email codes must be rejected even if the code value is correct."""

    async def test_expired_code_with_correct_value_rejected(self) -> None:
        """Even the correct 6-digit code is rejected after TTL expiry."""
        from datetime import datetime, timedelta, timezone

        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)

            record = await svc.get_request(rid)
            correct_code = record["email_code"]

            # Expire the code by backdating 2 hours
            past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            async with svc._db() as db:
                await db.execute(
                    "UPDATE brand_verifications SET email_code_expires = ? WHERE id = ?",
                    (past, rid),
                )
                await db.commit()

            result = await svc.verify_email_code(request_id=rid, code=correct_code)
            assert result["verified"] is False
            assert "expired" in result.get("error", "").lower()
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_expired_code_does_not_award_points(self) -> None:
        """An expired code must not increment the verification score."""
        from datetime import datetime, timedelta, timezone

        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)

            record = await svc.get_request(rid)
            correct_code = record["email_code"]

            # Expire it
            past = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
            async with svc._db() as db:
                await db.execute(
                    "UPDATE brand_verifications SET email_code_expires = ? WHERE id = ?",
                    (past, rid),
                )
                await db.commit()

            await svc.verify_email_code(request_id=rid, code=correct_code)

            # Score must still be 0
            final = await svc.get_request(rid)
            assert final["verification_score"] == 0
        finally:
            await svc.close()

    async def test_malformed_expiry_timestamp_handled(self) -> None:
        """A corrupted email_code_expires value must not crash the service."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.initiate_email_verification(request_id=rid)

            record = await svc.get_request(rid)
            correct_code = record["email_code"]

            # Corrupt the timestamp
            async with svc._db() as db:
                await db.execute(
                    "UPDATE brand_verifications SET email_code_expires = ? WHERE id = ?",
                    ("NOT-A-TIMESTAMP", rid),
                )
                await db.commit()

            result = await svc.verify_email_code(request_id=rid, code=correct_code)
            assert result["verified"] is False
            assert "invalid" in result.get("error", "").lower() or "expiry" in result.get("error", "").lower()
        finally:
            await svc.close()


# ===========================================================================
# 15. DNS verification — malformed domain edge cases
# ===========================================================================


class TestDnsMalformedDomain:
    """DNS verification with edge-case domain values."""

    async def test_invalid_domain_format_rejected_at_submit(self) -> None:
        """Malformed domain like '!!!.com' is rejected at submit time."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="Invalid company_domain"):
                await svc.submit_request(
                    handle="nike-store",
                    requester_email="legal@nike.com",
                    company_name="Nike",
                    company_domain="!!!.com",
                )
        finally:
            await svc.close()

    async def test_domain_with_spaces_rejected(self) -> None:
        """Domain with spaces is rejected."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="Invalid company_domain"):
                await svc.submit_request(
                    handle="nike-store",
                    requester_email="legal@nike.com",
                    company_name="Nike",
                    company_domain="nike .com",
                )
        finally:
            await svc.close()

    async def test_domain_with_underscore_rejected(self) -> None:
        """Domain with underscores is rejected."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="Invalid company_domain"):
                await svc.submit_request(
                    handle="nike-store",
                    requester_email="legal@nike.com",
                    company_name="Nike",
                    company_domain="nike_store.com",
                )
        finally:
            await svc.close()

    async def test_domain_with_protocol_rejected(self) -> None:
        """Domain with https:// prefix is rejected."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="Invalid company_domain"):
                await svc.submit_request(
                    handle="nike-store",
                    requester_email="legal@nike.com",
                    company_name="Nike",
                    company_domain="https://nike.com",
                )
        finally:
            await svc.close()

    async def test_dns_generic_exception_handled(self) -> None:
        """A generic exception in DNS lookup returns False, not a crash."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            with patch("subprocess.run", side_effect=OSError("Permission denied")):
                result = await svc.check_dns_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
            assert result["record_found"] is False
        finally:
            await svc.close()


# ===========================================================================
# 16. Meta verification — HTTP error scenarios
# ===========================================================================


class TestMetaHttpErrors:
    """Meta tag verification with HTTP error responses."""

    async def test_meta_check_http_404_returns_false(self) -> None:
        """HTTP 404 response returns verified=False, not a crash."""
        import urllib.error

        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    "https://nike.com", 404, "Not Found", {}, None
                ),
            ):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_meta_check_http_500_returns_false(self) -> None:
        """HTTP 500 response returns verified=False, not a crash."""
        import urllib.error

        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    "https://nike.com", 500, "Internal Server Error", {}, None
                ),
            ):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_meta_check_connection_refused_returns_false(self) -> None:
        """ConnectionRefusedError returns verified=False, not a crash."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            with patch(
                "urllib.request.urlopen",
                side_effect=ConnectionRefusedError("Connection refused"),
            ):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()

    async def test_meta_check_ssl_error_returns_false(self) -> None:
        """SSL certificate error returns verified=False, not a crash."""
        import ssl

        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            with patch(
                "urllib.request.urlopen",
                side_effect=ssl.SSLCertVerificationError("certificate verify failed"),
            ):
                result = await svc.check_meta_verification(request_id=rid)

            assert result["verified"] is False
            assert result["score"] == 0
        finally:
            await svc.close()


# ===========================================================================
# 17. Admin actions on non-existent requests
# ===========================================================================


class TestAdminNonexistentRequests:
    """Admin approve/deny on request IDs that do not exist."""

    async def test_admin_approve_nonexistent_returns_not_found(self) -> None:
        """admin_approve on a missing ID returns approved=False with error."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.admin_approve(
                "00000000-0000-0000-0000-000000000000",
                admin_notes="Should not work",
                reviewed_by="admin-1",
            )
            assert result["approved"] is False
            assert "not found" in result.get("error", "").lower()
        finally:
            await svc.close()

    async def test_admin_deny_nonexistent_returns_not_found(self) -> None:
        """admin_deny on a missing ID returns denied=False with error."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.admin_deny(
                "00000000-0000-0000-0000-000000000000",
                admin_notes="Should not work",
                reviewed_by="admin-1",
            )
            assert result["denied"] is False
            assert "not found" in result.get("error", "").lower()
        finally:
            await svc.close()

    async def test_admin_approve_already_denied_still_approves(self) -> None:
        """Admin can override a denied request to approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            rid = submitted["request_id"]

            await svc.admin_deny(rid, admin_notes="Initial deny")
            # admin_approve sets status directly — it awards 100 pts
            result = await svc.admin_approve(rid, admin_notes="Override to approve")
            assert result["approved"] is True

            record = await svc.get_request(rid)
            assert record["status"] == "approved"
        finally:
            await svc.close()

    async def test_admin_deny_already_approved_does_not_flip(self) -> None:
        """Once approved, admin_deny should not flip status."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
            )
            rid = submitted["request_id"]

            await svc.admin_approve(rid)
            result = await svc.admin_deny(rid, admin_notes="Try to deny after approve")
            # The SQL has WHERE status NOT IN ('approved', 'denied')
            assert result["denied"] is False

            record = await svc.get_request(rid)
            assert record["status"] == "approved"
        finally:
            await svc.close()

    async def test_deny_request_compat_nonexistent_returns_false(self) -> None:
        """deny_request() backwards-compat alias returns False for missing ID."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            ok = await svc.deny_request("00000000-0000-0000-0000-000000000000")
            assert ok is False
        finally:
            await svc.close()


# ===========================================================================
# 18. Score calculation edge cases
# ===========================================================================


class TestScoreEdgeCases:
    """Edge cases in the scoring and auto-approval logic."""

    async def test_all_four_signals_at_once(self) -> None:
        """Email(30) + DNS(30) + Meta(20) + Social(10) = 90 pts, approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Email signal (30 pts)
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)
            await svc.verify_email_code(request_id=rid, code=record["email_code"])

            # DNS signal (30 pts) — total 60, auto-approved
            dns_token = record["dns_token"]
            mock_dns = MagicMock()
            mock_dns.stdout = f'"{dns_token}"\n'
            with patch("subprocess.run", return_value=mock_dns):
                await svc.check_dns_verification(request_id=rid)

            # Already approved at 60 — meta and social on approved request
            meta_token = record["meta_token"]
            html = f'<meta name="dingdawg-verify" content="{meta_token}">'
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                meta_result = await svc.check_meta_verification(request_id=rid)
            # Request is already approved — meta returns verified=False
            assert meta_result["verified"] is False

            final = await svc.get_request(rid)
            assert final["status"] == "approved"
            # Score should be at least 60 from email + DNS
            assert final["verification_score"] >= 60
        finally:
            await svc.close()

    async def test_zero_signals_status_is_pending(self) -> None:
        """A request with no signals completed remains pending with score 0."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            record = await svc.get_request(submitted["request_id"])
            assert record["verification_score"] == 0
            assert record["status"] == "pending"
            assert json.loads(record["signals_completed"]) == {}
        finally:
            await svc.close()

    async def test_admin_override_awards_100_pts(self) -> None:
        """Admin approval adds exactly 100 pts to whatever the current score is."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # First add email signal (30 pts)
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)
            await svc.verify_email_code(request_id=rid, code=record["email_code"])

            pre_approve = await svc.get_request(rid)
            assert pre_approve["verification_score"] == 30

            # Admin approve adds 100
            await svc.admin_approve(rid)
            final = await svc.get_request(rid)
            assert final["verification_score"] == 130  # 30 + 100
            assert final["status"] == "approved"
        finally:
            await svc.close()

    async def test_signal_idempotency_across_all_types(self) -> None:
        """Adding the same signal twice does not double-count for any signal type."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Manually add social signal twice via _add_signal
            score1 = await svc._add_signal(rid, "social", 10)
            assert score1 == 10
            score2 = await svc._add_signal(rid, "social", 10)
            assert score2 == 10  # idempotent, no double-count

            # Manually add email signal twice
            score3 = await svc._add_signal(rid, "email", 30)
            assert score3 == 40  # 10 + 30
            score4 = await svc._add_signal(rid, "email", 30)
            assert score4 == 40  # idempotent
        finally:
            await svc.close()

    async def test_score_below_threshold_stays_verifying(self) -> None:
        """Score of 50 (email+meta) stays in 'verifying' status, not auto-approved."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Email (30)
            await svc.initiate_email_verification(request_id=rid)
            record = await svc.get_request(rid)
            await svc.verify_email_code(request_id=rid, code=record["email_code"])

            # Meta (20) — total 50
            meta_token = record["meta_token"]
            html = f'<meta name="dingdawg-verify" content="{meta_token}">'
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                meta_result = await svc.check_meta_verification(request_id=rid)

            assert meta_result["score"] == 50
            assert meta_result["auto_approved"] is False

            final = await svc.get_request(rid)
            assert final["status"] == "verifying"
        finally:
            await svc.close()


# ===========================================================================
# 19. Rate limiting simulation — many requests from same email
# ===========================================================================


class TestRateLimitingPatterns:
    """Simulate rapid-fire requests to verify service stability."""

    async def test_many_different_brand_handles_from_same_email(self) -> None:
        """Same email can submit verification for multiple different brand handles."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            handles = [
                "nike-store", "walmart-outlet", "starbucks-cafe",
                "tesla-showroom", "mcdonalds-drive",
            ]
            for handle in handles:
                await svc.submit_request(
                    handle=handle,
                    requester_email="legal@nike.com",
                    company_name="Multi-Brand Corp",
                )
            records = await svc.list_requests()
            assert len(records) == 5
        finally:
            await svc.close()

    async def test_rapid_email_verification_attempts_capped(self) -> None:
        """Rapid-fire email verification attempts are capped at MAX_EMAIL_ATTEMPTS."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            # Send 5 codes (the max)
            for i in range(5):
                result = await svc.initiate_email_verification(request_id=rid)
                assert result["sent"] is True

            # 6th attempt should raise
            with pytest.raises(ValueError, match="Maximum email verification attempts"):
                await svc.initiate_email_verification(request_id=rid)

            # Confirm the DB count matches
            record = await svc.get_request(rid)
            assert record["email_attempts"] == 5
        finally:
            await svc.close()

    async def test_many_status_checks_are_safe(self) -> None:
        """Repeated status checks do not mutate or corrupt data."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]

            for _ in range(20):
                status = await svc.get_status(rid)
                assert status is not None
                assert status["status"] == "pending"
                assert status["verification_score"] == 0

            # Data unchanged
            record = await svc.get_request(rid)
            assert record["verification_score"] == 0
        finally:
            await svc.close()


# ===========================================================================
# 20. Utility method edge cases
# ===========================================================================


class TestUtilityEdgeCases:
    """Edge cases in mask_email, is_free_email, and other helpers."""

    def test_mask_email_no_at_sign(self) -> None:
        """Email without @ returns '***'."""
        assert BrandVerificationService._mask_email("nope") == "***"

    def test_mask_email_empty_local_part(self) -> None:
        """Email with empty local part returns '***@domain'."""
        assert BrandVerificationService._mask_email("@nike.com") == "***@nike.com"

    def test_mask_email_single_char_local(self) -> None:
        """Email with single-char local returns 'a***@domain'."""
        assert BrandVerificationService._mask_email("a@nike.com") == "a***@nike.com"

    def test_is_free_email_no_at_returns_false(self) -> None:
        """Email without @ is not considered free."""
        assert BrandVerificationService._is_free_email("nodomain") is False

    def test_is_free_email_empty_string(self) -> None:
        """Empty string is not considered free."""
        assert BrandVerificationService._is_free_email("") is False

    def test_generate_token_is_url_safe(self) -> None:
        """Generated tokens contain only URL-safe characters."""
        import re
        token = BrandVerificationService._generate_token()
        assert len(token) > 10
        assert re.match(r"^[A-Za-z0-9_\-]+$", token)

    def test_generate_code_is_six_digits(self) -> None:
        """Generated codes are exactly 6-digit strings."""
        for _ in range(50):
            code = BrandVerificationService._generate_code()
            assert len(code) == 6
            assert code.isdigit()
            assert 100000 <= int(code) <= 999999

    async def test_get_status_not_found_returns_none(self) -> None:
        """get_status on nonexistent request returns None."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            result = await svc.get_status("00000000-0000-0000-0000-000000000000")
            assert result is None
        finally:
            await svc.close()

    async def test_get_requests_for_handle_returns_all(self) -> None:
        """get_requests_for_handle returns all requests for a given handle."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            await svc.submit_request("nike-store", "a@nike.com", "Nike A")
            await svc.submit_request("nike-store", "b@nike.com", "Nike B")
            await svc.submit_request("walmart-store", "c@walmart.com", "Walmart")

            nike_requests = await svc.get_requests_for_handle("nike-store")
            assert len(nike_requests) == 2

            walmart_requests = await svc.get_requests_for_handle("walmart-store")
            assert len(walmart_requests) == 1

            empty_requests = await svc.get_requests_for_handle("nonexistent-handle")
            assert len(empty_requests) == 0
        finally:
            await svc.close()

    async def test_social_proof_on_approved_request_not_recorded(self) -> None:
        """Social proof submission on an approved request returns recorded=False."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.admin_approve(rid)

            result = await svc.check_social_proof(
                request_id=rid,
                social_links={"twitter": "https://twitter.com/nike", "linkedin": "https://linkedin.com/nike"},
            )
            assert result["recorded"] is False
        finally:
            await svc.close()

    async def test_initiate_email_on_terminal_status_raises(self) -> None:
        """Cannot initiate email verification on an approved/denied/expired request."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.admin_deny(rid)

            with pytest.raises(ValueError, match="terminal status"):
                await svc.initiate_email_verification(request_id=rid)
        finally:
            await svc.close()

    async def test_dns_check_on_approved_request_returns_unverified(self) -> None:
        """DNS check on an approved request returns verified=False (no re-verification)."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            await svc.admin_approve(rid)

            result = await svc.check_dns_verification(request_id=rid)
            assert result["verified"] is False
        finally:
            await svc.close()

    async def test_list_requests_with_limit(self) -> None:
        """list_requests respects the limit parameter."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            for i in range(5):
                await svc.submit_request(
                    f"nike-store-{i}",
                    f"user{i}@nike.com",
                    f"Nike {i}",
                )
            limited = await svc.list_requests(limit=3)
            assert len(limited) == 3
        finally:
            await svc.close()

    async def test_social_proof_with_empty_string_values_ignored(self) -> None:
        """Social links with empty string values are not counted."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            result = await svc.check_social_proof(
                request_id=rid,
                social_links={
                    "twitter": "",
                    "linkedin": "   ",
                    "facebook": "https://facebook.com/nike",
                },
            )
            assert result["links_count"] == 1  # only facebook is valid
            assert result["score"] == 0  # need 2+ for 10 pts
        finally:
            await svc.close()

    async def test_social_proof_with_non_string_values_ignored(self) -> None:
        """Social links with non-string values (int, None) are not counted."""
        svc = BrandVerificationService(db_path=":memory:")
        try:
            submitted = await svc.submit_request(
                handle="nike-store",
                requester_email="legal@nike.com",
                company_name="Nike",
                company_domain="nike.com",
            )
            rid = submitted["request_id"]
            result = await svc.check_social_proof(
                request_id=rid,
                social_links={
                    "twitter": 12345,
                    "linkedin": None,
                    "facebook": "https://facebook.com/nike",
                },
            )
            assert result["links_count"] == 1
        finally:
            await svc.close()
