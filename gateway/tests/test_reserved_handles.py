"""Tests for the reserved handles registry and its integration with HandleService.

This file verifies:
- RESERVED_HANDLES is a frozenset with no duplicates (frozenset guarantees this)
- All handles obey the 3-30 char length constraint
- Key brand handles are present
- Typosquatting handles are present
- System handles (admin, root, api, etc.) are present
- HandleService.validate_handle() rejects every handle in RESERVED_HANDLES
- The set contains at least 200 entries (sanity guard)
- DINGDAWG_OWNED_HANDLES is a strict subset of RESERVED_HANDLES
"""

from __future__ import annotations

import re

import pytest

from isg_agent.agents.handle_service import HandleService
from isg_agent.agents.reserved_handles import RESERVED_HANDLES
from isg_agent.scripts.seed_reserved_handles import DINGDAWG_OWNED_HANDLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HANDLE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
_CONSECUTIVE_HYPHENS = re.compile(r"--")

_MIN_LEN = 3
_MAX_LEN = 30


def _is_format_valid(handle: str) -> bool:
    """Return True if handle passes all format rules (ignoring the reserved check)."""
    if len(handle) < _MIN_LEN or len(handle) > _MAX_LEN:
        return False
    if not handle[0].isalpha():
        return False
    if handle.endswith("-"):
        return False
    if _CONSECUTIVE_HYPHENS.search(handle):
        return False
    if not _HANDLE_PATTERN.match(handle):
        return False
    return True


# ---------------------------------------------------------------------------
# Basic structural tests
# ---------------------------------------------------------------------------

class TestReservedHandlesStructure:
    """RESERVED_HANDLES set structure and size invariants."""

    def test_is_frozenset(self) -> None:
        assert isinstance(RESERVED_HANDLES, frozenset)

    def test_minimum_size(self) -> None:
        """Sanity guard: must have at least 200 entries."""
        count = len(RESERVED_HANDLES)
        assert count >= 200, (
            f"RESERVED_HANDLES has only {count} entries — expected >= 200. "
            "Add more handles to reserved_handles.py."
        )

    def test_no_duplicates(self) -> None:
        # frozenset deduplicates automatically; confirm list version has same count
        as_list = list(RESERVED_HANDLES)
        as_set = set(as_list)
        assert len(as_list) == len(as_set), (
            "Duplicate handles detected — frozenset collapsed them."
        )

    def test_no_handle_exceeds_max_length(self) -> None:
        too_long = [h for h in RESERVED_HANDLES if len(h) > _MAX_LEN]
        assert not too_long, (
            f"Handles exceeding {_MAX_LEN} chars: {too_long}"
        )

    def test_no_handle_below_min_length(self) -> None:
        too_short = [h for h in RESERVED_HANDLES if len(h) < _MIN_LEN]
        assert not too_short, (
            f"Handles below {_MIN_LEN} chars: {too_short}"
        )

    def test_all_handles_are_lowercase(self) -> None:
        not_lower = [h for h in RESERVED_HANDLES if h != h.lower()]
        assert not not_lower, (
            f"Non-lowercase handles found: {not_lower}"
        )

    def test_all_handles_are_strings(self) -> None:
        non_strings = [h for h in RESERVED_HANDLES if not isinstance(h, str)]
        assert not non_strings, (
            f"Non-string entries found: {non_strings}"
        )


# ---------------------------------------------------------------------------
# Brand coverage tests
# ---------------------------------------------------------------------------

class TestBrandHandlesPresent:
    """Key brand handles must be reserved."""

    @pytest.mark.parametrize("handle", [
        "dingdawg",
        "dingdawg-support",
        "dingdawg-sales",
        "dingdawg-ai",
        "dingdawg-pro",
        "dingdawg-enterprise",
        "dingdawg-business",
        "dingdawg-team",
        "dingdawg-dev",
        "dingdawg-labs",
        "dingdawg-beta",
        "dingdawg-alpha",
        "dingdawg-official",
        "dingdawg-help",
        "dingdawg-billing",
        "dingdawg-legal",
        "dingdawg-hr",
        "dingdawg-ops",
        "dingdawg-security",
        "dingdawg-admin",
        "dingdawg-bot",
        "dingdawg-agent",
        "dingdawg-api",
        "dingdawg-app",
        "dingdawg-web",
        "dingdawg-mobile",
        "dingdawg-cloud",
        "dingdawg-data",
        "dingdawg-health",
        "dingdawg-gaming",
        "dingdawg-community",
        "dingdawg-partner",
        "dingdawg-affiliate",
        "dingdawg-ambassador",
        "dingdawg-vip",
        "dingdawg-premium",
        "dingdawg-plus",
        "dingdawg-starter",
        "dingdawg-basic",
        "dingdawg-free",
        "dingdawg-demo",
        "dingdawg-test",
        "dingdawg-staging",
        "dingdawg-internal",
        "dingdawg-status",
        "dingdawg-news",
        "dingdawg-blog",
        "dingdawg-docs",
        "dingdawg-sdk",
        "dingdawg-cli",
        "dingdawg-mcp",
    ])
    def test_brand_handle_present(self, handle: str) -> None:
        assert handle in RESERVED_HANDLES, (
            f"Brand handle {handle!r} is missing from RESERVED_HANDLES"
        )


# ---------------------------------------------------------------------------
# Typosquatting handles
# ---------------------------------------------------------------------------

class TestTyposquattingHandlesPresent:
    """Common typosquat variants must be blocked."""

    @pytest.mark.parametrize("handle", [
        "ding-dawg",
        "dingdog",
        "ding-dog",
        "dingdawgai",
        "dingdawg-io",
        "dawg",
        "dawgai",
        "dd-agent",
        "dd-ai",
        "dd-bot",
        "dd-support",
        "dd-sales",
        "dd-help",
        "dd-app",
        "dd-api",
    ])
    def test_typosquat_handle_present(self, handle: str) -> None:
        assert handle in RESERVED_HANDLES, (
            f"Typosquat handle {handle!r} is missing from RESERVED_HANDLES"
        )


# ---------------------------------------------------------------------------
# System / Infrastructure handles
# ---------------------------------------------------------------------------

class TestSystemHandlesPresent:
    """Core system handles must be blocked."""

    @pytest.mark.parametrize("handle", [
        "admin",
        "administrator",
        "system",
        "sysadmin",
        "root",
        "superuser",
        "sudo",
        "api",
        "api-v1",
        "api-v2",
        "webhook",
        "webhooks",
        "oauth",
        "auth",
        "login",
        "signup",
        "register",
        "www",
        "web",
        "app",
        "mobile",
        "null",
        "undefined",
        "test",
        "debug",
        "staging",
        "production",
        "dev",
        "status",
        "health",
        "ping",
        "heartbeat",
        "metrics",
        "monitor",
        "support",
        "help",
        "helpdesk",
        "feedback",
        "contact",
        "abuse",
        "spam",
        "billing",
        "payments",
        "pay",
        "invoice",
        "checkout",
        "security",
        "docs",
        "documentation",
        "wiki",
        "faq",
        "bot",
        "bots",
        "agent",
        "agents",
        "assistant",
        "copilot",
        "mail",
        "email",
        "notify",
        "notification",
        "notifications",
        "alert",
        "assets",
        "static",
        "media",
        "upload",
        "uploads",
        "files",
        "storage",
        "config",
        "settings",
        "account",
        "profile",
        "dashboard",
        "console",
        "marketplace",
        "store",
        "shop",
        "search",
        "explore",
        "discover",
    ])
    def test_system_handle_present(self, handle: str) -> None:
        assert handle in RESERVED_HANDLES, (
            f"System handle {handle!r} is missing from RESERVED_HANDLES"
        )


# ---------------------------------------------------------------------------
# Role handles
# ---------------------------------------------------------------------------

class TestRoleHandlesPresent:
    @pytest.mark.parametrize("handle", [
        "ceo", "cto", "cfo", "coo", "founder", "cofounder",
        "owner", "manager", "staff", "legal", "compliance",
        "finance", "marketing", "sales", "engineering", "product",
        "design", "devops", "ops", "intern",
    ])
    def test_role_handle_present(self, handle: str) -> None:
        assert handle in RESERVED_HANDLES, (
            f"Role handle {handle!r} is missing from RESERVED_HANDLES"
        )


# ---------------------------------------------------------------------------
# Competitor handles
# ---------------------------------------------------------------------------

class TestCompetitorHandlesPresent:
    @pytest.mark.parametrize("handle", [
        "openai", "chatgpt", "gpt", "claude", "anthropic",
        "google", "gemini", "alexa", "siri", "cortana", "copilot",
        "stripe", "twilio", "sendgrid", "vercel", "railway",
        "heroku", "aws", "azure", "gcloud",
    ])
    def test_competitor_handle_present(self, handle: str) -> None:
        assert handle in RESERVED_HANDLES, (
            f"Competitor handle {handle!r} is missing from RESERVED_HANDLES"
        )


# ---------------------------------------------------------------------------
# HandleService integration: validate_handle must reject every reserved handle
# ---------------------------------------------------------------------------

class TestHandleServiceRejectsReserved:
    """HandleService.validate_handle must reject every handle in RESERVED_HANDLES."""

    def test_validate_rejects_all_reserved(self) -> None:
        failures: list[str] = []
        for handle in sorted(RESERVED_HANDLES):
            valid, reason = HandleService.validate_handle(handle)
            if valid:
                failures.append(handle)
        assert not failures, (
            f"HandleService.validate_handle() ACCEPTED {len(failures)} reserved "
            f"handle(s) — they must be rejected: {failures[:20]}"
        )

    @pytest.mark.parametrize("handle", [
        "admin", "root", "dingdawg", "dingdawg-ai", "dingdawg-support",
        "api", "support", "bot", "openai", "stripe",
    ])
    def test_validate_rejects_key_reserved(self, handle: str) -> None:
        valid, reason = HandleService.validate_handle(handle)
        assert valid is False, (
            f"Expected validate_handle({handle!r}) to return False but got True"
        )
        assert "reserved" in reason.lower(), (
            f"Expected 'reserved' in rejection reason for {handle!r}, got: {reason!r}"
        )


# ---------------------------------------------------------------------------
# DINGDAWG_OWNED_HANDLES subset check
# ---------------------------------------------------------------------------

class TestDingdawgOwnedHandles:
    """DINGDAWG_OWNED_HANDLES must be a proper subset of RESERVED_HANDLES."""

    def test_owned_is_subset_of_reserved(self) -> None:
        not_in_reserved = [
            h for h in DINGDAWG_OWNED_HANDLES if h not in RESERVED_HANDLES
        ]
        assert not not_in_reserved, (
            f"DINGDAWG_OWNED_HANDLES entries not found in RESERVED_HANDLES: "
            f"{not_in_reserved}"
        )

    def test_owned_handles_all_start_with_dingdawg(self) -> None:
        non_brand = [
            h for h in DINGDAWG_OWNED_HANDLES
            if not h.startswith("dingdawg")
        ]
        assert not non_brand, (
            f"DINGDAWG_OWNED_HANDLES should only contain 'dingdawg*' handles, "
            f"but found: {non_brand}"
        )

    def test_owned_handles_no_duplicates(self) -> None:
        assert len(DINGDAWG_OWNED_HANDLES) == len(set(DINGDAWG_OWNED_HANDLES)), (
            "DINGDAWG_OWNED_HANDLES contains duplicate entries"
        )

    def test_owned_handles_minimum_count(self) -> None:
        count = len(DINGDAWG_OWNED_HANDLES)
        assert count >= 40, (
            f"Expected at least 40 company-owned handles, found {count}"
        )

    def test_owned_handles_are_format_valid(self) -> None:
        """All DINGDAWG_OWNED_HANDLES must pass format validation (not just block)."""
        invalid = [h for h in DINGDAWG_OWNED_HANDLES if not _is_format_valid(h)]
        assert not invalid, (
            f"DINGDAWG_OWNED_HANDLES contains format-invalid handles "
            f"(can't be inserted into DB): {invalid}"
        )


# ---------------------------------------------------------------------------
# Format coverage: handles that are valid format should individually satisfy
# length and character rules
# ---------------------------------------------------------------------------

class TestFormatValidHandlesInReserved:
    """Every format-valid handle in RESERVED_HANDLES must meet length rules."""

    def test_format_valid_handles_meet_length_rules(self) -> None:
        format_valid = [h for h in RESERVED_HANDLES if _is_format_valid(h)]
        violations: list[str] = []
        for h in format_valid:
            if len(h) < _MIN_LEN or len(h) > _MAX_LEN:
                violations.append(h)
        assert not violations, (
            f"Format-valid handles violating length rules: {violations}"
        )

    def test_reserved_set_contains_format_valid_handles(self) -> None:
        """Confirm at least half the reserved set passes format validation,
        showing the set is real handle-shaped strings."""
        format_valid_count = sum(
            1 for h in RESERVED_HANDLES if _is_format_valid(h)
        )
        total = len(RESERVED_HANDLES)
        assert format_valid_count >= total // 2, (
            f"Less than half the reserved handles are format-valid: "
            f"{format_valid_count}/{total}"
        )
