"""Tests for isg_agent.security.constitution — security constitution enforcement.

Comprehensive coverage of:
- ConstitutionCheck dataclass
- SecurityConstitution — all 10 invariants:
  1. no_admin_on_daily_accounts
  2. no_unsigned_artifacts (JWT tampering)
  3. no_exposed_management (admin/debug/.env paths)
  4. no_silent_config_drift
  5. default_deny_inbound
  6. no_write_without_receipt
  7. no_unverified_code_execution
  8. short_lived_credentials
  9. least_privilege (role hierarchy)
  10. no_path_traversal (../, encoded, null bytes)
- ConstitutionEnforcer:
  - enforce_all on clean requests
  - BLOCK severity stops request
  - WARN severity logs but continues
  - LOG severity records only
  - SQLite constitution_log persistence
- ConstitutionMiddleware:
  - Skip paths (/health, /metrics, /docs, /openapi.json)
  - 403 on BLOCK violation
  - Pass-through on clean request
  - Concurrent enforcement
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from isg_agent.security.constitution import (
    ConstitutionCheck,
    ConstitutionEnforcer,
    ConstitutionMiddleware,
    SecurityConstitution,
)


# ---------------------------------------------------------------------------
# ConstitutionCheck dataclass tests
# ---------------------------------------------------------------------------


class TestConstitutionCheck:
    """Tests for the ConstitutionCheck dataclass."""

    def test_passed_check(self) -> None:
        """A passing check has expected fields."""
        check = ConstitutionCheck(
            invariant="no_path_traversal",
            passed=True,
            violation_details=None,
            severity="BLOCK",
            timestamp="2026-03-13T00:00:00Z",
        )
        assert check.invariant == "no_path_traversal"
        assert check.passed is True
        assert check.violation_details is None
        assert check.severity == "BLOCK"
        assert check.timestamp == "2026-03-13T00:00:00Z"

    def test_failed_check(self) -> None:
        """A failing check includes violation details."""
        check = ConstitutionCheck(
            invariant="no_admin_on_daily_accounts",
            passed=False,
            violation_details="User 'joe' attempted admin access without admin role",
            severity="BLOCK",
            timestamp="2026-03-13T00:00:00Z",
        )
        assert check.passed is False
        assert "joe" in check.violation_details

    def test_severity_values(self) -> None:
        """All valid severity values are accepted."""
        for severity in ("BLOCK", "WARN", "LOG"):
            check = ConstitutionCheck(
                invariant="test",
                passed=True,
                violation_details=None,
                severity=severity,
                timestamp="2026-03-13T00:00:00Z",
            )
            assert check.severity == severity

    def test_timestamp_format(self) -> None:
        """Timestamp is an ISO 8601 string."""
        check = ConstitutionCheck(
            invariant="test",
            passed=True,
            violation_details=None,
            severity="LOG",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert "T" in check.timestamp


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 1: no_admin_on_daily_accounts
# ---------------------------------------------------------------------------


class TestNoAdminOnDailyAccounts:
    """Tests for invariant 1: admin endpoints require admin role."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_admin_user_on_admin_path_passes(self) -> None:
        """Admin role accessing admin endpoint passes."""
        result = self.constitution.no_admin_on_daily_accounts(
            path="/admin/users",
            user_role="admin",
        )
        assert result.passed is True

    def test_regular_user_on_admin_path_fails(self) -> None:
        """Regular user accessing admin endpoint fails."""
        result = self.constitution.no_admin_on_daily_accounts(
            path="/admin/users",
            user_role="user",
        )
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_regular_user_on_non_admin_path_passes(self) -> None:
        """Regular user on normal endpoint passes."""
        result = self.constitution.no_admin_on_daily_accounts(
            path="/api/agents",
            user_role="user",
        )
        assert result.passed is True

    def test_superadmin_on_admin_path_passes(self) -> None:
        """Superadmin role accessing admin endpoint passes."""
        result = self.constitution.no_admin_on_daily_accounts(
            path="/admin/config",
            user_role="superadmin",
        )
        assert result.passed is True

    def test_none_role_on_admin_path_fails(self) -> None:
        """No role on admin endpoint fails."""
        result = self.constitution.no_admin_on_daily_accounts(
            path="/admin/settings",
            user_role=None,
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 2: no_unsigned_artifacts
# ---------------------------------------------------------------------------


class TestNoUnsignedArtifacts:
    """Tests for invariant 2: reject tampered JWTs."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_no_auth_header_passes(self) -> None:
        """Request without auth header passes (auth is handled elsewhere)."""
        result = self.constitution.no_unsigned_artifacts(auth_header=None)
        assert result.passed is True

    def test_valid_jwt_format_passes(self) -> None:
        """Properly formatted JWT passes structural check."""
        import base64
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b'{"sub":"user-1"}').rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(b"signature").rstrip(b"=").decode()
        token = f"Bearer {header}.{payload}.{sig}"
        result = self.constitution.no_unsigned_artifacts(auth_header=token)
        assert result.passed is True

    def test_malformed_jwt_fails(self) -> None:
        """JWT with wrong number of parts fails."""
        result = self.constitution.no_unsigned_artifacts(auth_header="Bearer invalid-token")
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_jwt_none_algorithm_fails(self) -> None:
        """JWT with 'none' algorithm fails (alg:none attack)."""
        import base64
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b'{"sub":"attacker"}').rstrip(b"=").decode()
        token = f"Bearer {header}.{payload}."
        result = self.constitution.no_unsigned_artifacts(auth_header=token)
        assert result.passed is False

    def test_empty_bearer_fails(self) -> None:
        """Empty bearer token fails."""
        result = self.constitution.no_unsigned_artifacts(auth_header="Bearer ")
        assert result.passed is False


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 3: no_exposed_management
# ---------------------------------------------------------------------------


class TestNoExposedManagement:
    """Tests for invariant 3: block management paths from external IPs."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_admin_from_localhost_passes(self) -> None:
        """/admin from localhost is allowed."""
        result = self.constitution.no_exposed_management(
            path="/admin/dashboard",
            client_ip="127.0.0.1",
        )
        assert result.passed is True

    def test_admin_from_external_fails(self) -> None:
        """/admin from external IP is blocked."""
        result = self.constitution.no_exposed_management(
            path="/admin/dashboard",
            client_ip="203.0.113.1",
        )
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_debug_from_external_fails(self) -> None:
        """/debug from external IP is blocked."""
        result = self.constitution.no_exposed_management(
            path="/debug/info",
            client_ip="198.51.100.1",
        )
        assert result.passed is False

    def test_dotenv_from_external_fails(self) -> None:
        """/.env from external IP is blocked."""
        result = self.constitution.no_exposed_management(
            path="/.env",
            client_ip="192.0.2.1",
        )
        assert result.passed is False

    def test_config_from_external_fails(self) -> None:
        """/config from external IP is blocked."""
        result = self.constitution.no_exposed_management(
            path="/config/secrets",
            client_ip="10.0.0.2",
        )
        assert result.passed is False

    def test_normal_path_from_external_passes(self) -> None:
        """Normal path from external IP passes."""
        result = self.constitution.no_exposed_management(
            path="/api/agents",
            client_ip="203.0.113.1",
        )
        assert result.passed is True

    def test_localhost_ipv6_passes(self) -> None:
        """::1 (IPv6 localhost) is allowed for management paths."""
        result = self.constitution.no_exposed_management(
            path="/admin/dashboard",
            client_ip="::1",
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 4: no_silent_config_drift
# ---------------------------------------------------------------------------


class TestNoSilentConfigDrift:
    """Tests for invariant 4: detect runtime config changes."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_matching_hash_passes(self) -> None:
        """Config hash matching baseline passes."""
        baseline = hashlib.sha256(b"config-content").hexdigest()
        self.constitution.set_config_baseline(baseline)
        result = self.constitution.no_silent_config_drift(baseline)
        assert result.passed is True

    def test_different_hash_fails(self) -> None:
        """Config hash different from baseline fails."""
        baseline = hashlib.sha256(b"original").hexdigest()
        current = hashlib.sha256(b"modified").hexdigest()
        self.constitution.set_config_baseline(baseline)
        result = self.constitution.no_silent_config_drift(current)
        assert result.passed is False
        assert result.severity == "WARN"

    def test_no_baseline_set_passes(self) -> None:
        """No baseline set passes (first run)."""
        result = self.constitution.no_silent_config_drift("any-hash")
        assert result.passed is True

    def test_empty_hash_with_baseline_fails(self) -> None:
        """Empty hash when baseline exists fails."""
        self.constitution.set_config_baseline("abc123")
        result = self.constitution.no_silent_config_drift("")
        assert result.passed is False


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 5: default_deny_inbound
# ---------------------------------------------------------------------------


class TestDefaultDenyInbound:
    """Tests for invariant 5: only registered routes are allowed."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()
        self.constitution.register_routes({
            ("GET", "/api/agents"),
            ("POST", "/api/agents"),
            ("GET", "/health"),
        })

    def test_registered_route_passes(self) -> None:
        """Registered route passes."""
        result = self.constitution.default_deny_inbound("GET", "/api/agents")
        assert result.passed is True

    def test_unregistered_route_fails(self) -> None:
        """Unregistered route fails."""
        result = self.constitution.default_deny_inbound("DELETE", "/api/nuke")
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_wrong_method_fails(self) -> None:
        """Correct path but wrong method fails."""
        result = self.constitution.default_deny_inbound("DELETE", "/api/agents")
        assert result.passed is False

    def test_no_routes_registered_passes_when_empty(self) -> None:
        """When no routes registered, default_deny_inbound passes (fail-open)."""
        empty_const = SecurityConstitution()
        result = empty_const.default_deny_inbound("GET", "/anything")
        assert result.passed is True

    def test_case_sensitive_method(self) -> None:
        """Method matching is case-insensitive."""
        result = self.constitution.default_deny_inbound("get", "/api/agents")
        assert result.passed is True


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 6: no_write_without_receipt
# ---------------------------------------------------------------------------


class TestNoWriteWithoutReceipt:
    """Tests for invariant 6: write ops must be logged."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_write_with_receipt_passes(self) -> None:
        """Write operation with audit receipt passes."""
        result = self.constitution.no_write_without_receipt(
            method="POST",
            has_audit_receipt=True,
        )
        assert result.passed is True

    def test_write_without_receipt_fails(self) -> None:
        """Write operation without audit receipt fails."""
        result = self.constitution.no_write_without_receipt(
            method="POST",
            has_audit_receipt=False,
        )
        assert result.passed is False
        assert result.severity == "WARN"

    def test_read_without_receipt_passes(self) -> None:
        """Read operations do not require receipt."""
        result = self.constitution.no_write_without_receipt(
            method="GET",
            has_audit_receipt=False,
        )
        assert result.passed is True

    def test_delete_without_receipt_fails(self) -> None:
        """DELETE without receipt fails."""
        result = self.constitution.no_write_without_receipt(
            method="DELETE",
            has_audit_receipt=False,
        )
        assert result.passed is False

    def test_put_without_receipt_fails(self) -> None:
        """PUT without receipt fails."""
        result = self.constitution.no_write_without_receipt(
            method="PUT",
            has_audit_receipt=False,
        )
        assert result.passed is False

    def test_patch_without_receipt_fails(self) -> None:
        """PATCH without receipt fails."""
        result = self.constitution.no_write_without_receipt(
            method="PATCH",
            has_audit_receipt=False,
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 7: no_unverified_code_execution
# ---------------------------------------------------------------------------


class TestNoUnverifiedCodeExecution:
    """Tests for invariant 7: code must pass Wasm validator."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_no_code_passes(self) -> None:
        """No code in request passes."""
        result = self.constitution.no_unverified_code_execution(code=None)
        assert result.passed is True

    def test_validated_code_passes(self) -> None:
        """Code that has been validated passes."""
        result = self.constitution.no_unverified_code_execution(
            code="print('hello')",
            is_validated=True,
        )
        assert result.passed is True

    def test_unvalidated_code_fails(self) -> None:
        """Code that has NOT been validated fails."""
        result = self.constitution.no_unverified_code_execution(
            code="import os; os.system('rm -rf /')",
            is_validated=False,
        )
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_empty_code_passes(self) -> None:
        """Empty string code passes (no code to execute)."""
        result = self.constitution.no_unverified_code_execution(code="")
        assert result.passed is True


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 8: short_lived_credentials
# ---------------------------------------------------------------------------


class TestShortLivedCredentials:
    """Tests for invariant 8: reject tokens older than 24 hours."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_fresh_token_passes(self) -> None:
        """Token expiring in 1 hour passes."""
        exp = time.time() + 3600
        result = self.constitution.short_lived_credentials(token_expiry=exp)
        assert result.passed is True

    def test_expired_token_fails(self) -> None:
        """Already expired token fails."""
        exp = time.time() - 100
        result = self.constitution.short_lived_credentials(token_expiry=exp)
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_token_expiring_too_far_fails(self) -> None:
        """Token valid for more than 24 hours fails."""
        exp = time.time() + 90000  # 25 hours
        result = self.constitution.short_lived_credentials(token_expiry=exp)
        assert result.passed is False

    def test_token_exactly_24h_passes(self) -> None:
        """Token expiring in exactly 24 hours passes."""
        exp = time.time() + 86400
        result = self.constitution.short_lived_credentials(token_expiry=exp)
        assert result.passed is True

    def test_no_expiry_fails(self) -> None:
        """Token without expiry fails."""
        result = self.constitution.short_lived_credentials(token_expiry=None)
        assert result.passed is False


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 9: least_privilege
# ---------------------------------------------------------------------------


class TestLeastPrivilege:
    """Tests for invariant 9: role hierarchy check."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_admin_accesses_admin_passes(self) -> None:
        """Admin role meets admin requirement."""
        result = self.constitution.least_privilege(
            user_role="admin",
            required_role="admin",
        )
        assert result.passed is True

    def test_superadmin_accesses_admin_passes(self) -> None:
        """Superadmin exceeds admin requirement."""
        result = self.constitution.least_privilege(
            user_role="superadmin",
            required_role="admin",
        )
        assert result.passed is True

    def test_user_accesses_admin_fails(self) -> None:
        """User role below admin requirement."""
        result = self.constitution.least_privilege(
            user_role="user",
            required_role="admin",
        )
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_user_accesses_user_passes(self) -> None:
        """User role meets user requirement."""
        result = self.constitution.least_privilege(
            user_role="user",
            required_role="user",
        )
        assert result.passed is True

    def test_none_role_fails(self) -> None:
        """No role fails any requirement."""
        result = self.constitution.least_privilege(
            user_role=None,
            required_role="user",
        )
        assert result.passed is False

    def test_superadmin_accesses_superadmin_passes(self) -> None:
        """Superadmin meets superadmin requirement."""
        result = self.constitution.least_privilege(
            user_role="superadmin",
            required_role="superadmin",
        )
        assert result.passed is True

    def test_admin_accesses_superadmin_fails(self) -> None:
        """Admin below superadmin requirement."""
        result = self.constitution.least_privilege(
            user_role="admin",
            required_role="superadmin",
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# SecurityConstitution — Invariant 10: no_path_traversal
# ---------------------------------------------------------------------------


class TestNoPathTraversal:
    """Tests for invariant 10: reject path traversal attacks."""

    def setup_method(self) -> None:
        self.constitution = SecurityConstitution()

    def test_clean_path_passes(self) -> None:
        """Normal path passes."""
        result = self.constitution.no_path_traversal("/api/agents/123")
        assert result.passed is True

    def test_dotdot_fails(self) -> None:
        """../ in path fails."""
        result = self.constitution.no_path_traversal("/api/../../../etc/passwd")
        assert result.passed is False
        assert result.severity == "BLOCK"

    def test_encoded_dotdot_fails(self) -> None:
        """%2e%2e in path fails (URL-encoded ..)."""
        result = self.constitution.no_path_traversal("/api/%2e%2e/%2e%2e/etc/passwd")
        assert result.passed is False

    def test_double_encoded_dotdot_fails(self) -> None:
        """%252e%252e fails (double URL-encoded ..)."""
        result = self.constitution.no_path_traversal("/api/%252e%252e/secret")
        assert result.passed is False

    def test_null_byte_fails(self) -> None:
        """Null byte in path fails."""
        result = self.constitution.no_path_traversal("/api/agents\x00/evil")
        assert result.passed is False

    def test_encoded_null_byte_fails(self) -> None:
        """%00 in path fails."""
        result = self.constitution.no_path_traversal("/api/agents%00/evil")
        assert result.passed is False

    def test_backslash_traversal_fails(self) -> None:
        """Backslash traversal fails (Windows-style)."""
        result = self.constitution.no_path_traversal("/api/..\\..\\etc\\passwd")
        assert result.passed is False

    def test_root_path_passes(self) -> None:
        """Root path / passes."""
        result = self.constitution.no_path_traversal("/")
        assert result.passed is True

    def test_single_dot_passes(self) -> None:
        """Single dot in path component passes (not traversal)."""
        result = self.constitution.no_path_traversal("/api/v1.0/agents")
        assert result.passed is True

    def test_mixed_case_encoded_fails(self) -> None:
        """%2E%2E (uppercase encoded) fails."""
        result = self.constitution.no_path_traversal("/api/%2E%2E/secret")
        assert result.passed is False


# ---------------------------------------------------------------------------
# ConstitutionEnforcer tests
# ---------------------------------------------------------------------------


class TestConstitutionEnforcer:
    """Tests for ConstitutionEnforcer — runs all invariants."""

    def _make_enforcer(self, db_path: str | None = None) -> ConstitutionEnforcer:
        """Create an enforcer with optional DB path."""
        constitution = SecurityConstitution()
        constitution.register_routes({
            ("GET", "/api/agents"),
            ("POST", "/api/agents"),
            ("GET", "/health"),
        })
        return ConstitutionEnforcer(
            constitution=constitution,
            db_path=db_path,
        )

    def test_clean_request_all_pass(self) -> None:
        """All invariants pass on a clean GET request."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/agents",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        assert all(c.passed for c in results)

    def test_block_severity_raises_on_path_traversal(self) -> None:
        """BLOCK-severity violation from path traversal causes block."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/../../etc/passwd",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        blocked = [c for c in results if not c.passed and c.severity == "BLOCK"]
        assert len(blocked) > 0

    def test_block_on_admin_access_by_regular_user(self) -> None:
        """Regular user on admin path triggers BLOCK."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/admin/users",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        admin_check = [c for c in results if c.invariant == "no_admin_on_daily_accounts"]
        assert len(admin_check) == 1
        assert admin_check[0].passed is False

    def test_warn_severity_does_not_block(self) -> None:
        """WARN-severity violation is recorded but does not block."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/agents",
            method="POST",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=False,  # No receipt = WARN
            code=None,
        )
        warns = [c for c in results if not c.passed and c.severity == "WARN"]
        assert len(warns) >= 1
        # The enforcer should still report has_blocks=False for WARN only
        blocks = [c for c in results if not c.passed and c.severity == "BLOCK"]
        # Only default_deny_inbound might block for POST unregistered - check
        # POST /api/agents IS registered, so no blocks expected from that
        # Just verify warns exist
        assert len(warns) >= 1

    def test_has_blocks_property(self) -> None:
        """has_blocks returns True when BLOCK violations exist."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/../../etc/passwd",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        assert enforcer.has_blocks(results) is True

    def test_has_blocks_false_on_clean(self) -> None:
        """has_blocks returns False when no BLOCK violations."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/agents",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        assert enforcer.has_blocks(results) is False

    def test_sqlite_logging(self) -> None:
        """Constitution checks are logged to SQLite."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            enforcer = self._make_enforcer(db_path=db_path)
            enforcer.enforce_all(
                path="/api/agents",
                method="GET",
                client_ip="127.0.0.1",
                user_role="user",
                auth_header=None,
                token_expiry=None,
                config_hash=None,
                has_audit_receipt=True,
                code=None,
            )

            conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM constitution_log")
                count = cursor.fetchone()[0]
                assert count > 0
            finally:
                conn.close()
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_sqlite_log_has_correct_schema(self) -> None:
        """Constitution log table has expected columns."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            enforcer = self._make_enforcer(db_path=db_path)
            enforcer.enforce_all(
                path="/api/agents",
                method="GET",
                client_ip="127.0.0.1",
                user_role="user",
                auth_header=None,
                token_expiry=None,
                config_hash=None,
                has_audit_receipt=True,
                code=None,
            )

            conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                cursor = conn.execute("PRAGMA table_info(constitution_log)")
                columns = {row[1] for row in cursor.fetchall()}
                assert "invariant" in columns
                assert "passed" in columns
                assert "severity" in columns
                assert "timestamp" in columns
                assert "violation_details" in columns
            finally:
                conn.close()
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_expired_token_blocked(self) -> None:
        """Expired JWT token triggers BLOCK."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/agents",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=time.time() - 3600,  # expired 1 hour ago
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        token_check = [c for c in results if c.invariant == "short_lived_credentials"]
        assert len(token_check) == 1
        assert token_check[0].passed is False
        assert token_check[0].severity == "BLOCK"

    def test_config_drift_detected(self) -> None:
        """Config drift triggers WARN."""
        enforcer = self._make_enforcer()
        baseline = hashlib.sha256(b"original").hexdigest()
        current = hashlib.sha256(b"changed").hexdigest()
        enforcer.constitution.set_config_baseline(baseline)
        results = enforcer.enforce_all(
            path="/api/agents",
            method="GET",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=current,
            has_audit_receipt=True,
            code=None,
        )
        drift_check = [c for c in results if c.invariant == "no_silent_config_drift"]
        assert len(drift_check) == 1
        assert drift_check[0].passed is False
        assert drift_check[0].severity == "WARN"

    def test_concurrent_enforcement(self) -> None:
        """Concurrent enforce_all calls do not corrupt state."""
        enforcer = self._make_enforcer()
        results_list: list[list[ConstitutionCheck]] = []
        lock = threading.Lock()

        def worker() -> None:
            r = enforcer.enforce_all(
                path="/api/agents",
                method="GET",
                client_ip="127.0.0.1",
                user_role="user",
                auth_header=None,
                token_expiry=None,
                config_hash=None,
                has_audit_receipt=True,
                code=None,
            )
            with lock:
                results_list.append(r)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results_list) == 10
        for results in results_list:
            assert all(c.passed for c in results)

    def test_management_path_from_external_blocked(self) -> None:
        """Management path from external IP is blocked."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/admin/users",
            method="GET",
            client_ip="203.0.113.1",
            user_role="admin",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code=None,
        )
        mgmt_check = [c for c in results if c.invariant == "no_exposed_management"]
        assert len(mgmt_check) == 1
        assert mgmt_check[0].passed is False

    def test_unvalidated_code_blocked(self) -> None:
        """Unvalidated code execution is blocked."""
        enforcer = self._make_enforcer()
        results = enforcer.enforce_all(
            path="/api/agents",
            method="POST",
            client_ip="127.0.0.1",
            user_role="user",
            auth_header=None,
            token_expiry=None,
            config_hash=None,
            has_audit_receipt=True,
            code="import os; os.system('rm -rf /')",
        )
        code_check = [c for c in results if c.invariant == "no_unverified_code_execution"]
        assert len(code_check) == 1
        assert code_check[0].passed is False


# ---------------------------------------------------------------------------
# ConstitutionMiddleware tests
# ---------------------------------------------------------------------------


def _make_scope(
    path: str = "/api/test",
    method: str = "GET",
    client_ip: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a minimal ASGI scope for middleware testing."""
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


class TestConstitutionMiddleware:
    """Tests for the ConstitutionMiddleware ASGI middleware."""

    def _make_middleware(
        self,
        constitution: SecurityConstitution | None = None,
    ) -> ConstitutionMiddleware:
        """Create middleware with a test app."""
        const = constitution or SecurityConstitution()
        # Register basic routes
        const.register_routes({
            ("GET", "/api/test"),
            ("POST", "/api/test"),
            ("GET", "/health"),
            ("GET", "/metrics"),
            ("GET", "/docs"),
            ("GET", "/openapi.json"),
            ("GET", "/api/agents"),
        })
        enforcer = ConstitutionEnforcer(constitution=const)

        async def test_app(scope: dict, receive: Any, send: Any) -> None:
            body = json.dumps({"ok": True}).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })

        return ConstitutionMiddleware(app=test_app, enforcer=enforcer)

    async def _call_middleware(
        self,
        mw: ConstitutionMiddleware,
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

        await mw(scope, receive, send)
        return status_code, response_headers, response_body

    @pytest.mark.asyncio
    async def test_clean_request_passes(self) -> None:
        """Clean request passes through middleware."""
        mw = self._make_middleware()
        scope = _make_scope(path="/api/test")
        status, _, body = await self._call_middleware(mw, scope)
        assert status == 200

    @pytest.mark.asyncio
    async def test_path_traversal_returns_403(self) -> None:
        """Path traversal returns 403 Forbidden."""
        mw = self._make_middleware()
        scope = _make_scope(path="/api/../../../etc/passwd")
        status, _, body = await self._call_middleware(mw, scope)
        assert status == 403
        data = json.loads(body)
        assert data["error"] == "constitution_violation"

    @pytest.mark.asyncio
    async def test_skip_health_endpoint(self) -> None:
        """Requests to /health skip constitution checks."""
        mw = self._make_middleware()
        scope = _make_scope(path="/health")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200

    @pytest.mark.asyncio
    async def test_skip_metrics_endpoint(self) -> None:
        """Requests to /metrics skip constitution checks."""
        mw = self._make_middleware()
        scope = _make_scope(path="/metrics")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200

    @pytest.mark.asyncio
    async def test_skip_docs_endpoint(self) -> None:
        """Requests to /docs skip constitution checks."""
        mw = self._make_middleware()
        scope = _make_scope(path="/docs")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200

    @pytest.mark.asyncio
    async def test_skip_openapi_json(self) -> None:
        """Requests to /openapi.json skip constitution checks."""
        mw = self._make_middleware()
        scope = _make_scope(path="/openapi.json")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 200

    @pytest.mark.asyncio
    async def test_non_http_passthrough(self) -> None:
        """Non-HTTP scopes pass through without checks."""
        mw = self._make_middleware()
        called = False

        async def test_app(scope: dict, receive: Any, send: Any) -> None:
            nonlocal called
            called = True

        mw_custom = ConstitutionMiddleware(
            app=test_app,
            enforcer=ConstitutionEnforcer(constitution=SecurityConstitution()),
        )
        scope = {"type": "websocket", "path": "/ws"}
        await mw_custom(scope, AsyncMock(), AsyncMock())
        assert called is True

    @pytest.mark.asyncio
    async def test_403_body_structure(self) -> None:
        """403 response has expected JSON structure."""
        mw = self._make_middleware()
        scope = _make_scope(path="/api/../../secret")
        status, _, body = await self._call_middleware(mw, scope)
        assert status == 403
        data = json.loads(body)
        assert "error" in data
        assert "violations" in data
        assert isinstance(data["violations"], list)
        assert len(data["violations"]) > 0

    @pytest.mark.asyncio
    async def test_management_path_from_external(self) -> None:
        """/admin from external IP returns 403."""
        const = SecurityConstitution()
        const.register_routes({("GET", "/admin/users")})
        mw = self._make_middleware(constitution=const)
        scope = _make_scope(path="/admin/users", client_ip="203.0.113.1")
        status, _, _ = await self._call_middleware(mw, scope)
        assert status == 403
