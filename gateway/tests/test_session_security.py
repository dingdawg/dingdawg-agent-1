"""Tests for session hardening and secret rotation security modules.

Covers:
- SessionHardener: create, validate, rotate, revoke, cleanup, replay detection,
  fingerprint binding, access tracking, concurrent creation, thread safety
- SecretRotator: register, check status, record rotation, verify strength,
  generate reports, rotation history, hash-only storage, persistence
- generate_fingerprint: determinism, /24 tolerance, different subnets

Test count target: 90-110 tests
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from isg_agent.security.session_hardening import (
    SecureSession,
    SessionHardener,
    SessionValidation,
    generate_fingerprint,
)
from isg_agent.security.secret_rotation import (
    RotationAlert,
    RotationReport,
    SecretRecord,
    SecretRotator,
    SecretStrength,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hardener() -> SessionHardener:
    """Provide an in-memory SessionHardener instance."""
    return SessionHardener(db_path=":memory:")


@pytest.fixture()
def rotator() -> SecretRotator:
    """Provide an in-memory SecretRotator instance."""
    return SecretRotator(db_path=":memory:")


@pytest.fixture()
def tmp_db() -> Generator[str, None, None]:
    """Provide a temporary SQLite database path for persistence tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    p = Path(db_path)
    if p.exists():
        p.unlink()
    for suffix in ("-wal", "-shm"):
        wal = Path(db_path + suffix)
        if wal.exists():
            wal.unlink()


SAMPLE_UA = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"
SAMPLE_LANG = "en-US,en;q=0.9"
SAMPLE_IP = "192.168.1.42"


def _fp(
    ua: str = SAMPLE_UA,
    lang: str = SAMPLE_LANG,
    ip: str = SAMPLE_IP,
) -> str:
    """Shortcut for generate_fingerprint."""
    return generate_fingerprint(ua, lang, ip)


# ===========================================================================
# Part 1: Fingerprint generation tests
# ===========================================================================


class TestGenerateFingerprint:
    """Tests for the generate_fingerprint utility function."""

    def test_deterministic(self) -> None:
        """Same inputs produce the same fingerprint."""
        fp1 = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, SAMPLE_IP)
        fp2 = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, SAMPLE_IP)
        assert fp1 == fp2

    def test_returns_32_hex_chars(self) -> None:
        """Fingerprint is exactly 32 hex characters."""
        fp = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, SAMPLE_IP)
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)

    def test_ip_24_tolerance_same_subnet(self) -> None:
        """IPs in the same /24 produce the same fingerprint."""
        fp1 = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, "192.168.1.1")
        fp2 = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, "192.168.1.254")
        assert fp1 == fp2

    def test_different_subnet_different_fingerprint(self) -> None:
        """IPs in different /24 subnets produce different fingerprints."""
        fp1 = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, "192.168.1.1")
        fp2 = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, "192.168.2.1")
        assert fp1 != fp2

    def test_different_user_agent(self) -> None:
        """Different User-Agent produces different fingerprint."""
        fp1 = generate_fingerprint("Chrome/120", SAMPLE_LANG, SAMPLE_IP)
        fp2 = generate_fingerprint("Firefox/119", SAMPLE_LANG, SAMPLE_IP)
        assert fp1 != fp2

    def test_different_accept_language(self) -> None:
        """Different Accept-Language produces different fingerprint."""
        fp1 = generate_fingerprint(SAMPLE_UA, "en-US", SAMPLE_IP)
        fp2 = generate_fingerprint(SAMPLE_UA, "fr-FR", SAMPLE_IP)
        assert fp1 != fp2

    def test_ipv6_fallback(self) -> None:
        """IPv6 addresses use the full address as prefix (no split)."""
        fp = generate_fingerprint(SAMPLE_UA, SAMPLE_LANG, "::1")
        assert len(fp) == 32  # Should not crash

    def test_empty_inputs_produce_fingerprint(self) -> None:
        """Empty strings still produce a valid fingerprint."""
        fp = generate_fingerprint("", "", "")
        assert len(fp) == 32


# ===========================================================================
# Part 2: Session hardening tests
# ===========================================================================


class TestCreateSecureSession:
    """Tests for SessionHardener.create_secure_session."""

    def test_creates_session_with_all_fields(self, hardener: SessionHardener) -> None:
        """Created session has all expected fields populated."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        assert session.session_id
        assert session.user_id == "user-1"
        assert session.agent_id == "agent-1"
        assert session.fingerprint_hash == fp
        assert session.is_active is True
        assert session.access_count == 0

    def test_session_id_is_cryptographically_random(self, hardener: SessionHardener) -> None:
        """Each session gets a unique cryptographic ID."""
        fp = _fp()
        s1 = hardener.create_secure_session("user-1", "agent-1", fp)
        s2 = hardener.create_secure_session("user-1", "agent-1", fp)
        assert s1.session_id != s2.session_id

    def test_session_id_length(self, hardener: SessionHardener) -> None:
        """Session ID is a URL-safe base64 string of at least 32 bytes entropy."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        # secrets.token_urlsafe(32) produces ~43 chars
        assert len(session.session_id) >= 40

    def test_created_at_is_utc_iso(self, hardener: SessionHardener) -> None:
        """created_at is a valid ISO 8601 UTC timestamp."""
        session = hardener.create_secure_session("user-1", "agent-1", _fp())
        dt = datetime.fromisoformat(session.created_at)
        assert dt.tzinfo is not None

    def test_expires_at_is_15_minutes_after_creation(self, hardener: SessionHardener) -> None:
        """Default access TTL is 15 minutes."""
        session = hardener.create_secure_session("user-1", "agent-1", _fp())
        created = datetime.fromisoformat(session.created_at)
        expires = datetime.fromisoformat(session.expires_at)
        delta = expires - created
        assert 14 * 60 <= delta.total_seconds() <= 16 * 60

    def test_custom_ttl(self) -> None:
        """Custom access TTL is respected."""
        h = SessionHardener(db_path=":memory:", access_ttl_minutes=30)
        session = h.create_secure_session("user-1", "agent-1", _fp())
        created = datetime.fromisoformat(session.created_at)
        expires = datetime.fromisoformat(session.expires_at)
        delta = expires - created
        assert 29 * 60 <= delta.total_seconds() <= 31 * 60

    def test_empty_agent_id(self, hardener: SessionHardener) -> None:
        """Empty agent_id is stored as None."""
        session = hardener.create_secure_session("user-1", "", _fp())
        assert session.agent_id is None


class TestValidateSession:
    """Tests for SessionHardener.validate_session."""

    def test_valid_session_passes(self, hardener: SessionHardener) -> None:
        """Active, non-expired session with matching fingerprint passes."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        result = hardener.validate_session(session.session_id, fp)
        assert result.valid is True
        assert result.reason == "ok"
        assert result.session is not None

    def test_expired_session_fails(self) -> None:
        """Expired session returns valid=False with reason 'expired'."""
        h = SessionHardener(db_path=":memory:", access_ttl_minutes=0)
        fp = _fp()
        session = h.create_secure_session("user-1", "agent-1", fp)
        # Session expires immediately (0 min TTL), but let's make it definitely expired
        # by patching time
        future = datetime.now(timezone.utc) + timedelta(minutes=1)
        with patch.object(h, "_now_utc", return_value=future):
            result = h.validate_session(session.session_id, fp)
        assert result.valid is False
        assert result.reason == "expired"

    def test_fingerprint_mismatch_fails(self, hardener: SessionHardener) -> None:
        """Different fingerprint returns valid=False with reason 'fingerprint_mismatch'."""
        fp_original = _fp(ip="10.0.0.1")
        session = hardener.create_secure_session("user-1", "agent-1", fp_original)
        fp_different = _fp(ip="10.0.1.1")  # Different /24
        result = hardener.validate_session(session.session_id, fp_different)
        assert result.valid is False
        assert result.reason == "fingerprint_mismatch"

    def test_not_found_session(self, hardener: SessionHardener) -> None:
        """Non-existent session returns valid=False with reason 'not_found'."""
        result = hardener.validate_session("nonexistent-id", _fp())
        assert result.valid is False
        assert result.reason == "not_found"
        assert result.session is None

    def test_revoked_session_fails(self, hardener: SessionHardener) -> None:
        """Revoked session returns valid=False with reason 'revoked'."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        hardener.revoke_session(session.session_id)
        result = hardener.validate_session(session.session_id, fp)
        assert result.valid is False
        assert result.reason == "revoked"

    def test_access_count_increments(self, hardener: SessionHardener) -> None:
        """Each successful validation increments the access count."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        r1 = hardener.validate_session(session.session_id, fp)
        assert r1.session is not None
        assert r1.session.access_count == 1
        r2 = hardener.validate_session(session.session_id, fp)
        assert r2.session is not None
        assert r2.session.access_count == 2

    def test_last_accessed_updates(self, hardener: SessionHardener) -> None:
        """Each validation updates last_accessed timestamp."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        original_accessed = session.last_accessed
        result = hardener.validate_session(session.session_id, fp)
        assert result.session is not None
        assert result.session.last_accessed >= original_accessed


class TestReplayDetection:
    """Tests for anti-replay protection."""

    def test_same_ip_no_replay(self, hardener: SessionHardener) -> None:
        """Same IP within window does not trigger replay detection."""
        fp = _fp(ip="10.0.0.5")
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        r1 = hardener.validate_session(session.session_id, fp, client_ip="10.0.0.5")
        assert r1.valid is True
        r2 = hardener.validate_session(session.session_id, fp, client_ip="10.0.0.5")
        assert r2.valid is True

    def test_different_ip_triggers_replay(self, hardener: SessionHardener) -> None:
        """Different /24 IP within window triggers replay detection."""
        fp = _fp(ip="10.0.0.5")
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        # First access from 10.0.0.x
        r1 = hardener.validate_session(session.session_id, fp, client_ip="10.0.0.5")
        assert r1.valid is True
        # Second access from 10.0.1.x — different /24
        r2 = hardener.validate_session(session.session_id, fp, client_ip="10.0.1.5")
        assert r2.valid is False
        assert r2.reason == "replay_detected"

    def test_same_subnet_different_host_no_replay(self, hardener: SessionHardener) -> None:
        """Different host within same /24 does not trigger replay."""
        fp = _fp(ip="10.0.0.5")
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        r1 = hardener.validate_session(session.session_id, fp, client_ip="10.0.0.5")
        assert r1.valid is True
        r2 = hardener.validate_session(session.session_id, fp, client_ip="10.0.0.99")
        assert r2.valid is True

    def test_no_ip_skips_replay_check(self, hardener: SessionHardener) -> None:
        """When no client_ip provided, replay check is skipped."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        r1 = hardener.validate_session(session.session_id, fp)  # no IP
        assert r1.valid is True


class TestSessionRotation:
    """Tests for SessionHardener.rotate_session."""

    def test_rotation_creates_new_session(self, hardener: SessionHardener) -> None:
        """Rotation creates a new session with a different ID."""
        fp = _fp()
        old = hardener.create_secure_session("user-1", "agent-1", fp)
        new = hardener.rotate_session(old.session_id)
        assert new is not None
        assert new.session_id != old.session_id

    def test_rotation_invalidates_old_session(self, hardener: SessionHardener) -> None:
        """Old session is inactive after rotation."""
        fp = _fp()
        old = hardener.create_secure_session("user-1", "agent-1", fp)
        hardener.rotate_session(old.session_id)
        result = hardener.validate_session(old.session_id, fp)
        assert result.valid is False
        assert result.reason == "revoked"

    def test_rotation_preserves_identity(self, hardener: SessionHardener) -> None:
        """New session has same user_id, agent_id, fingerprint."""
        fp = _fp()
        old = hardener.create_secure_session("user-1", "agent-1", fp)
        new = hardener.rotate_session(old.session_id)
        assert new is not None
        assert new.user_id == old.user_id
        assert new.agent_id == old.agent_id
        assert new.fingerprint_hash == old.fingerprint_hash

    def test_rotation_resets_access_count(self, hardener: SessionHardener) -> None:
        """New session starts with access_count = 0."""
        fp = _fp()
        old = hardener.create_secure_session("user-1", "agent-1", fp)
        hardener.validate_session(old.session_id, fp)  # increment count
        new = hardener.rotate_session(old.session_id)
        assert new is not None
        assert new.access_count == 0

    def test_rotation_nonexistent_returns_none(self, hardener: SessionHardener) -> None:
        """Rotating a nonexistent session returns None."""
        result = hardener.rotate_session("nonexistent")
        assert result is None

    def test_new_session_is_valid_after_rotation(self, hardener: SessionHardener) -> None:
        """The new rotated session passes validation."""
        fp = _fp()
        old = hardener.create_secure_session("user-1", "agent-1", fp)
        new = hardener.rotate_session(old.session_id)
        assert new is not None
        result = hardener.validate_session(new.session_id, fp)
        assert result.valid is True


class TestRevokeSession:
    """Tests for session revocation."""

    def test_revoke_single_session(self, hardener: SessionHardener) -> None:
        """Revoking a session makes it invalid."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        assert hardener.revoke_session(session.session_id) is True
        result = hardener.validate_session(session.session_id, fp)
        assert result.valid is False
        assert result.reason == "revoked"

    def test_revoke_nonexistent_returns_false(self, hardener: SessionHardener) -> None:
        """Revoking a nonexistent session returns False."""
        assert hardener.revoke_session("nonexistent") is False

    def test_revoke_already_revoked_returns_false(self, hardener: SessionHardener) -> None:
        """Revoking an already-revoked session returns False."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        assert hardener.revoke_session(session.session_id) is True
        assert hardener.revoke_session(session.session_id) is False

    def test_revoke_all_sessions(self, hardener: SessionHardener) -> None:
        """Revoking all sessions for a user invalidates them all."""
        fp = _fp()
        s1 = hardener.create_secure_session("user-1", "agent-1", fp)
        s2 = hardener.create_secure_session("user-1", "agent-2", fp)
        s3 = hardener.create_secure_session("user-2", "agent-1", fp)  # different user

        count = hardener.revoke_all_sessions("user-1")
        assert count == 2

        assert hardener.validate_session(s1.session_id, fp).valid is False
        assert hardener.validate_session(s2.session_id, fp).valid is False
        # user-2's session is unaffected
        assert hardener.validate_session(s3.session_id, fp).valid is True

    def test_revoke_all_returns_zero_when_no_sessions(self, hardener: SessionHardener) -> None:
        """Revoking all for a user with no sessions returns 0."""
        count = hardener.revoke_all_sessions("nonexistent-user")
        assert count == 0


class TestCleanupExpired:
    """Tests for expired session cleanup."""

    def test_cleanup_removes_expired_sessions(self) -> None:
        """Expired sessions are removed by cleanup."""
        h = SessionHardener(db_path=":memory:", access_ttl_minutes=0)
        fp = _fp()
        session = h.create_secure_session("user-1", "agent-1", fp)
        # Force expiry by advancing time
        future = datetime.now(timezone.utc) + timedelta(minutes=1)
        with patch.object(h, "_now_utc", return_value=future):
            count = h.cleanup_expired()
        assert count == 1
        assert h.get_session(session.session_id) is None

    def test_cleanup_preserves_active_sessions(self, hardener: SessionHardener) -> None:
        """Active sessions are not removed by cleanup."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        count = hardener.cleanup_expired()
        assert count == 0
        assert hardener.get_session(session.session_id) is not None

    def test_cleanup_returns_zero_when_empty(self, hardener: SessionHardener) -> None:
        """Cleanup on empty database returns 0."""
        assert hardener.cleanup_expired() == 0


class TestConcurrentSessions:
    """Tests for thread safety and concurrent access."""

    def test_concurrent_session_creation(self, hardener: SessionHardener) -> None:
        """Multiple threads can create sessions concurrently without collision."""
        fp = _fp()
        sessions: list[SecureSession] = []
        errors: list[Exception] = []

        def create_session(idx: int) -> None:
            try:
                s = hardener.create_secure_session(f"user-{idx}", "agent-1", fp)
                sessions.append(s)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_session, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Errors during concurrent creation: {errors}"
        assert len(sessions) == 10
        session_ids = {s.session_id for s in sessions}
        assert len(session_ids) == 10  # all unique

    def test_concurrent_validate_and_revoke(self, hardener: SessionHardener) -> None:
        """Concurrent validation and revocation does not crash."""
        fp = _fp()
        session = hardener.create_secure_session("user-1", "agent-1", fp)
        errors: list[Exception] = []

        def validate() -> None:
            try:
                for _ in range(5):
                    hardener.validate_session(session.session_id, fp)
            except Exception as e:
                errors.append(e)

        def revoke() -> None:
            try:
                hardener.revoke_session(session.session_id)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=validate)
        t2 = threading.Thread(target=revoke)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert not errors


class TestGetSessionHelpers:
    """Tests for helper/utility methods on SessionHardener."""

    def test_get_session_returns_session(self, hardener: SessionHardener) -> None:
        """get_session returns the session object."""
        fp = _fp()
        created = hardener.create_secure_session("user-1", "agent-1", fp)
        fetched = hardener.get_session(created.session_id)
        assert fetched is not None
        assert fetched.session_id == created.session_id

    def test_get_session_returns_none_for_missing(self, hardener: SessionHardener) -> None:
        """get_session returns None for nonexistent ID."""
        assert hardener.get_session("nonexistent") is None

    def test_active_session_count(self, hardener: SessionHardener) -> None:
        """get_active_session_count tracks active sessions per user."""
        fp = _fp()
        hardener.create_secure_session("user-1", "agent-1", fp)
        hardener.create_secure_session("user-1", "agent-2", fp)
        s3 = hardener.create_secure_session("user-1", "agent-3", fp)
        hardener.revoke_session(s3.session_id)
        assert hardener.get_active_session_count("user-1") == 2

    def test_session_persists_in_file_db(self, tmp_db: str) -> None:
        """Sessions persist across SessionHardener instances with file-based DB."""
        fp = _fp()
        h1 = SessionHardener(db_path=tmp_db)
        session = h1.create_secure_session("user-1", "agent-1", fp)
        # New instance pointing to same DB
        h2 = SessionHardener(db_path=tmp_db)
        fetched = h2.get_session(session.session_id)
        assert fetched is not None
        assert fetched.user_id == "user-1"


# ===========================================================================
# Part 3: Secret rotation tests
# ===========================================================================


class TestRegisterSecret:
    """Tests for SecretRotator.register_secret."""

    def test_register_returns_record(self, rotator: SecretRotator) -> None:
        """Registering a secret returns a valid SecretRecord."""
        record = rotator.register_secret("JWT_SECRET", "my-super-secret-key-123")
        assert record.name == "JWT_SECRET"
        assert record.rotation_days == 90
        assert record.rotation_count == 0
        assert record.status == "CURRENT"

    def test_stores_hash_not_plaintext(self, rotator: SecretRotator) -> None:
        """Stored value is a SHA-256 hash, NOT the plaintext."""
        plaintext = "sk-abc123-very-secret"
        record = rotator.register_secret("OPENAI_API_KEY", plaintext)
        expected_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        assert record.value_hash == expected_hash
        assert plaintext not in record.value_hash

    def test_custom_rotation_days(self, rotator: SecretRotator) -> None:
        """Custom rotation_days is stored correctly."""
        record = rotator.register_secret("SHORT_LIVED", "val", rotation_days=30)
        assert record.rotation_days == 30

    def test_next_rotation_date(self, rotator: SecretRotator) -> None:
        """next_rotation is rotation_days after registration."""
        record = rotator.register_secret("KEY", "val", rotation_days=60)
        last_dt = datetime.fromisoformat(record.last_rotated)
        next_dt = datetime.fromisoformat(record.next_rotation)
        delta = (next_dt - last_dt).days
        assert delta == 60

    def test_register_same_name_replaces(self, rotator: SecretRotator) -> None:
        """Re-registering the same name replaces the record."""
        rotator.register_secret("KEY", "value-1")
        record2 = rotator.register_secret("KEY", "value-2")
        expected_hash = hashlib.sha256("value-2".encode()).hexdigest()
        assert record2.value_hash == expected_hash

    def test_multiple_secrets_independent(self, rotator: SecretRotator) -> None:
        """Multiple secrets are tracked independently."""
        r1 = rotator.register_secret("KEY_A", "val-a", rotation_days=30)
        r2 = rotator.register_secret("KEY_B", "val-b", rotation_days=90)
        assert r1.name != r2.name
        assert r1.rotation_days != r2.rotation_days
        assert r1.value_hash != r2.value_hash


class TestCheckRotationStatus:
    """Tests for SecretRotator.check_rotation_status."""

    def test_new_secret_status_info(self, rotator: SecretRotator) -> None:
        """Newly registered secret has INFO severity."""
        rotator.register_secret("KEY", "value", rotation_days=90)
        alerts = rotator.check_rotation_status()
        assert len(alerts) == 1
        assert alerts[0].severity == "INFO"
        assert alerts[0].days_until_due > 0

    def test_due_secret_status_warning(self, rotator: SecretRotator) -> None:
        """Secret within 30 days of rotation has WARNING severity."""
        rotator.register_secret("KEY", "value", rotation_days=90)
        # Simulate 70 days passing (within 30-day warning window)
        future = datetime.now(timezone.utc) + timedelta(days=70)
        with patch.object(rotator, "_now_utc", return_value=future):
            alerts = rotator.check_rotation_status()
        assert len(alerts) == 1
        assert alerts[0].severity == "WARNING"

    def test_overdue_secret_status_critical(self, rotator: SecretRotator) -> None:
        """Secret past rotation_days has CRITICAL severity."""
        rotator.register_secret("KEY", "value", rotation_days=90)
        future = datetime.now(timezone.utc) + timedelta(days=100)
        with patch.object(rotator, "_now_utc", return_value=future):
            alerts = rotator.check_rotation_status()
        assert len(alerts) == 1
        assert alerts[0].severity == "CRITICAL"

    def test_emergency_secret_status(self, rotator: SecretRotator) -> None:
        """Secret past 2x rotation_days has EMERGENCY severity."""
        rotator.register_secret("KEY", "value", rotation_days=90)
        future = datetime.now(timezone.utc) + timedelta(days=200)
        with patch.object(rotator, "_now_utc", return_value=future):
            alerts = rotator.check_rotation_status()
        assert len(alerts) == 1
        assert alerts[0].severity == "EMERGENCY"

    def test_multiple_secrets_sorted_by_severity(self, rotator: SecretRotator) -> None:
        """Alerts are sorted from most to least severe."""
        rotator.register_secret("CURRENT_KEY", "val1", rotation_days=365)
        rotator.register_secret("OVERDUE_KEY", "val2", rotation_days=1)
        # OVERDUE_KEY has 1-day rotation, so it's immediately overdue after a day
        future = datetime.now(timezone.utc) + timedelta(days=5)
        with patch.object(rotator, "_now_utc", return_value=future):
            alerts = rotator.check_rotation_status()
        assert len(alerts) == 2
        severity_order = {"EMERGENCY": 0, "CRITICAL": 1, "WARNING": 2, "INFO": 3}
        for i in range(len(alerts) - 1):
            assert severity_order[alerts[i].severity] <= severity_order[alerts[i + 1].severity]

    def test_empty_returns_empty_list(self, rotator: SecretRotator) -> None:
        """No registered secrets returns empty alert list."""
        alerts = rotator.check_rotation_status()
        assert alerts == []


class TestRecordRotation:
    """Tests for SecretRotator.record_rotation."""

    def test_record_rotation_success(self, rotator: SecretRotator) -> None:
        """Recording a rotation updates the secret record."""
        rotator.register_secret("KEY", "old-value")
        new_hash = hashlib.sha256("new-value".encode()).hexdigest()
        result = rotator.record_rotation("KEY", new_hash)
        assert result is True

    def test_record_rotation_updates_hash(self, rotator: SecretRotator) -> None:
        """After rotation, the stored hash is the new one."""
        rotator.register_secret("KEY", "old-value")
        new_hash = hashlib.sha256("new-value".encode()).hexdigest()
        rotator.record_rotation("KEY", new_hash)
        record = rotator.get_secret_record("KEY")
        assert record is not None
        assert record.value_hash == new_hash

    def test_record_rotation_increments_count(self, rotator: SecretRotator) -> None:
        """Rotation count increments after each rotation."""
        rotator.register_secret("KEY", "v1")
        rotator.record_rotation("KEY", hashlib.sha256(b"v2").hexdigest())
        rotator.record_rotation("KEY", hashlib.sha256(b"v3").hexdigest())
        record = rotator.get_secret_record("KEY")
        assert record is not None
        assert record.rotation_count == 2

    def test_record_rotation_nonexistent_returns_false(self, rotator: SecretRotator) -> None:
        """Recording rotation for nonexistent secret returns False."""
        result = rotator.record_rotation("NONEXISTENT", "somehash")
        assert result is False

    def test_rotation_history_preserved(self, rotator: SecretRotator) -> None:
        """Old hashes are preserved in rotation history."""
        rotator.register_secret("KEY", "v1")
        old_hash = hashlib.sha256("v1".encode()).hexdigest()
        rotator.record_rotation("KEY", hashlib.sha256(b"v2").hexdigest())
        history = rotator.get_rotation_history("KEY")
        assert len(history) == 1
        assert history[0]["old_value_hash"] == old_hash

    def test_multiple_rotations_in_history(self, rotator: SecretRotator) -> None:
        """Multiple rotations create multiple history entries."""
        rotator.register_secret("KEY", "v1")
        rotator.record_rotation("KEY", hashlib.sha256(b"v2").hexdigest())
        rotator.record_rotation("KEY", hashlib.sha256(b"v3").hexdigest())
        history = rotator.get_rotation_history("KEY")
        assert len(history) == 2
        # Most recent first
        assert history[0]["old_value_hash"] == hashlib.sha256(b"v2").hexdigest()
        assert history[1]["old_value_hash"] == hashlib.sha256("v1".encode()).hexdigest()

    def test_rotation_updates_next_rotation(self, rotator: SecretRotator) -> None:
        """After rotation, next_rotation is reset to rotation_days from now."""
        rotator.register_secret("KEY", "v1", rotation_days=60)
        rotator.record_rotation("KEY", hashlib.sha256(b"v2").hexdigest())
        record = rotator.get_secret_record("KEY")
        assert record is not None
        last_dt = datetime.fromisoformat(record.last_rotated)
        next_dt = datetime.fromisoformat(record.next_rotation)
        delta = (next_dt - last_dt).days
        assert delta == 60


class TestVerifySecretStrength:
    """Tests for SecretRotator.verify_secret_strength."""

    def test_weak_short_secret(self, rotator: SecretRotator) -> None:
        """Short secret (< 8 chars) is rated WEAK."""
        result = rotator.verify_secret_strength("abc")
        assert result.strength == "WEAK"
        assert len(result.issues) > 0

    def test_weak_sequential_secret(self, rotator: SecretRotator) -> None:
        """Sequential pattern is flagged."""
        result = rotator.verify_secret_strength("abcdefghijklmnop")
        assert any("sequential" in issue.lower() for issue in result.issues)

    def test_weak_password_pattern(self, rotator: SecretRotator) -> None:
        """Common dictionary words are flagged."""
        result = rotator.verify_secret_strength("password123456789")
        assert any("dictionary" in issue.lower() or "common" in issue.lower() for issue in result.issues)

    def test_weak_repeated_chars(self, rotator: SecretRotator) -> None:
        """Excessively repeated characters are flagged."""
        result = rotator.verify_secret_strength("aaaaaaaaaaaaaaaa")
        assert any("repeated" in issue.lower() for issue in result.issues)

    def test_strong_high_entropy(self, rotator: SecretRotator) -> None:
        """High-entropy 256-bit key is rated STRONG or EXCELLENT."""
        # Generate a truly random 32-byte key
        key = secrets.token_hex(32)  # 64 hex chars = 256 bits
        result = rotator.verify_secret_strength(key)
        assert result.strength in ("STRONG", "EXCELLENT")
        assert result.entropy_bits >= 128

    def test_excellent_secret(self, rotator: SecretRotator) -> None:
        """A long, high-entropy, mixed-charset secret is EXCELLENT."""
        # 64 bytes of random URL-safe base64
        key = secrets.token_urlsafe(64)
        result = rotator.verify_secret_strength(key)
        assert result.strength in ("STRONG", "EXCELLENT")
        assert result.entropy_bits > 200

    def test_entropy_calculation_positive(self, rotator: SecretRotator) -> None:
        """Entropy is always non-negative."""
        result = rotator.verify_secret_strength("x")
        assert result.entropy_bits >= 0.0

    def test_empty_string_weak(self, rotator: SecretRotator) -> None:
        """Empty string has zero entropy and is WEAK."""
        result = rotator.verify_secret_strength("")
        assert result.strength == "WEAK"
        assert result.entropy_bits == 0.0

    def test_fair_medium_secret(self, rotator: SecretRotator) -> None:
        """A medium-length secret with some issues is FAIR."""
        result = rotator.verify_secret_strength("Test12345678")
        assert result.strength in ("WEAK", "FAIR")

    def test_single_category_flagged(self, rotator: SecretRotator) -> None:
        """Secret using only one character category is flagged."""
        result = rotator.verify_secret_strength("abcdefghijklmnopqrstuvwxyz1234")
        has_category_issue = any("character category" in issue.lower() or "category" in issue.lower() for issue in result.issues)
        # The lowercase-only case would trigger this; with digits it uses 2 categories
        # so test a true single-category:
        result2 = rotator.verify_secret_strength("abcdefghijklmnopqrstuvwxyz")
        assert any("category" in issue.lower() for issue in result2.issues)


class TestRotationReport:
    """Tests for SecretRotator.generate_rotation_report."""

    def test_report_structure(self, rotator: SecretRotator) -> None:
        """Report has all expected fields."""
        rotator.register_secret("KEY", "val")
        report = rotator.generate_rotation_report()
        assert isinstance(report, RotationReport)
        assert report.total_secrets == 1
        assert report.generated_at
        assert isinstance(report.alerts, list)
        assert isinstance(report.records, list)
        assert isinstance(report.recommendations, list)

    def test_report_counts(self, rotator: SecretRotator) -> None:
        """Report counts match the actual secret statuses."""
        rotator.register_secret("CURRENT_1", "v1", rotation_days=365)
        rotator.register_secret("CURRENT_2", "v2", rotation_days=365)
        report = rotator.generate_rotation_report()
        assert report.total_secrets == 2
        assert report.current_count == 2
        assert report.due_count == 0
        assert report.overdue_count == 0
        assert report.emergency_count == 0

    def test_report_with_overdue(self, rotator: SecretRotator) -> None:
        """Report includes overdue secrets."""
        rotator.register_secret("OLD_KEY", "val", rotation_days=1)
        future = datetime.now(timezone.utc) + timedelta(days=5)
        with patch.object(rotator, "_now_utc", return_value=future):
            report = rotator.generate_rotation_report()
        assert report.overdue_count + report.emergency_count >= 1

    def test_report_recommendations(self, rotator: SecretRotator) -> None:
        """Report includes actionable recommendations."""
        rotator.register_secret("KEY", "val", rotation_days=365)
        report = rotator.generate_rotation_report()
        assert len(report.recommendations) >= 1

    def test_empty_report(self, rotator: SecretRotator) -> None:
        """Report with no secrets has zero counts."""
        report = rotator.generate_rotation_report()
        assert report.total_secrets == 0
        assert report.current_count == 0

    def test_report_alerts_match_records(self, rotator: SecretRotator) -> None:
        """Number of alerts matches number of records."""
        rotator.register_secret("A", "v1")
        rotator.register_secret("B", "v2")
        report = rotator.generate_rotation_report()
        assert len(report.alerts) == len(report.records)


class TestSecretPersistence:
    """Tests for SQLite persistence across instances."""

    def test_persistence_across_instances(self, tmp_db: str) -> None:
        """Secrets persist across SecretRotator instances with file-based DB."""
        r1 = SecretRotator(db_path=tmp_db)
        r1.register_secret("PERSISTENT_KEY", "my-secret-val")
        # Create new instance pointing to same DB
        r2 = SecretRotator(db_path=tmp_db)
        record = r2.get_secret_record("PERSISTENT_KEY")
        assert record is not None
        assert record.name == "PERSISTENT_KEY"

    def test_rotation_history_persists(self, tmp_db: str) -> None:
        """Rotation history persists across instances."""
        r1 = SecretRotator(db_path=tmp_db)
        r1.register_secret("KEY", "v1")
        r1.record_rotation("KEY", hashlib.sha256(b"v2").hexdigest())
        r2 = SecretRotator(db_path=tmp_db)
        history = r2.get_rotation_history("KEY")
        assert len(history) == 1

    def test_plaintext_never_in_database(self, tmp_db: str) -> None:
        """Verify plaintext secret value is NEVER stored in the SQLite file."""
        plaintext = "super-secret-value-that-must-not-appear"
        r = SecretRotator(db_path=tmp_db)
        r.register_secret("SENSITIVE", plaintext)
        # Read the raw database file content
        with open(tmp_db, "rb") as f:
            raw = f.read()
        assert plaintext.encode() not in raw


class TestSecretRecordDataclass:
    """Tests for dataclass integrity."""

    def test_secret_record_fields(self) -> None:
        """SecretRecord has all expected fields."""
        record = SecretRecord(
            name="TEST",
            value_hash="abc123",
            rotation_days=90,
            last_rotated="2026-01-01T00:00:00+00:00",
            next_rotation="2026-04-01T00:00:00+00:00",
            rotation_count=0,
            status="CURRENT",
        )
        assert record.name == "TEST"
        assert record.rotation_days == 90

    def test_rotation_alert_fields(self) -> None:
        """RotationAlert has all expected fields."""
        alert = RotationAlert(
            secret_name="TEST",
            severity="INFO",
            days_since_rotation=10,
            days_until_due=80,
            recommendation="All good.",
        )
        assert alert.severity == "INFO"

    def test_secret_strength_fields(self) -> None:
        """SecretStrength has all expected fields."""
        strength = SecretStrength(
            strength="STRONG",
            entropy_bits=256.0,
            issues=[],
        )
        assert strength.entropy_bits == 256.0

    def test_secure_session_fields(self) -> None:
        """SecureSession has all expected fields."""
        session = SecureSession(
            session_id="abc",
            user_id="user-1",
            agent_id="agent-1",
            fingerprint_hash="fp123",
            created_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-01-01T00:15:00+00:00",
            last_accessed="2026-01-01T00:00:00+00:00",
            access_count=0,
            is_active=True,
        )
        assert session.user_id == "user-1"

    def test_session_validation_fields(self) -> None:
        """SessionValidation has all expected fields."""
        val = SessionValidation(valid=True, reason="ok", session=None)
        assert val.valid is True
        assert val.reason == "ok"
