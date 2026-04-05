"""Tests for config.py (Settings + YAML loading) and db/ package.

Covers:
- Config loading with defaults
- Config with ENV var overrides
- DB engine creation (temp SQLite file)
- Schema creation (all tables exist after create_tables)
- Basic query functions (insert + retrieve for audit_chain, sessions, messages)
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from isg_agent.config import Settings, get_settings
from isg_agent.db.engine import Database
from isg_agent.db.queries import (
    create_session,
    get_audit_chain,
    get_session,
    get_session_messages,
    get_trust_score,
    insert_audit_entry,
    insert_message,
    insert_skill,
    insert_token,
    insert_trust_entry,
    list_skills,
    revoke_token,
    verify_chain_integrity,
    verify_token,
)
from isg_agent.db.schema import SCHEMA_VERSION, create_tables


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    """Test that Settings has correct default values."""

    def test_default_host(self) -> None:
        s = Settings()
        assert s.host == "127.0.0.1"

    def test_default_port(self) -> None:
        s = Settings()
        assert s.port == 8420

    def test_default_db_path(self) -> None:
        s = Settings(_env_file=None)
        assert s.db_path == "data/agent.db"

    def test_default_log_level_normalised(self) -> None:
        s = Settings()
        assert s.log_level == "INFO"

    def test_default_max_sessions(self) -> None:
        s = Settings()
        assert s.max_sessions == 10

    def test_default_convergence_max_iterations(self) -> None:
        s = Settings()
        assert s.convergence_max_iterations == 100

    def test_default_convergence_max_tokens(self) -> None:
        s = Settings()
        assert s.convergence_max_tokens == 100_000

    def test_default_time_lock_delays(self) -> None:
        s = Settings()
        assert s.time_lock_delays["HIGH"] == 30.0
        assert s.time_lock_delays["CRITICAL"] == 60.0
        assert s.time_lock_delays["LOW"] == 0.0

    def test_default_trust_score_initial(self) -> None:
        s = Settings()
        assert s.trust_score_initial == 50.0

    def test_default_enable_remote_is_false(self) -> None:
        s = Settings(_env_file=None)
        assert s.enable_remote is False

    def test_secret_key_auto_generated(self) -> None:
        """Secret key is auto-generated when empty."""
        s = Settings(_env_file=None)
        assert len(s.secret_key) == 64  # hex-encoded 32 bytes
        assert s.secret_key != "CHANGE-ME-IN-PRODUCTION"

    def test_workspace_root_defaults_to_cwd(self) -> None:
        s = Settings()
        assert s.workspace_root == str(Path.cwd())


class TestSettingsEnvOverrides:
    """Test that environment variables override defaults."""

    def test_env_override_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ISG_AGENT_PORT", "9999")
        s = Settings()
        assert s.port == 9999

    def test_env_override_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ISG_AGENT_LOG_LEVEL", "debug")
        s = Settings()
        assert s.log_level == "DEBUG"  # normalised to uppercase

    def test_env_override_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ISG_AGENT_HOST", "0.0.0.0")
        s = Settings()
        assert s.host == "0.0.0.0"

    def test_env_override_db_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ISG_AGENT_DB_PATH", "/tmp/test.db")
        s = Settings()
        assert s.db_path == "/tmp/test.db"

    def test_env_override_secret_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ISG_AGENT_SECRET_KEY", "my-custom-secret-key-here")
        s = Settings()
        assert s.secret_key == "my-custom-secret-key-here"


class TestSettingsValidation:
    """Test validation logic."""

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(Exception):
            Settings(log_level="INVALID_LEVEL")

    def test_log_level_case_insensitive(self) -> None:
        s = Settings(log_level="warning")
        assert s.log_level == "WARNING"


class TestGetSettings:
    """Test the cached get_settings() function."""

    def test_get_settings_returns_settings_instance(self) -> None:
        # Clear cache from any prior test
        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_is_cached(self) -> None:
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_get_settings_cache_clearable(self) -> None:
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # After cache clear, new instance is created
        # Secret key is random, so they will differ
        assert isinstance(s2, Settings)


# ---------------------------------------------------------------------------
# Database engine tests
# ---------------------------------------------------------------------------


class TestDatabaseEngine:
    """Test the Database engine lifecycle and connection management."""

    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "test.db")

    async def test_init_creates_database_file(self, db_path: str) -> None:
        db = Database(db_path)
        await db.init()
        assert Path(db_path).exists()
        await db.close()

    async def test_init_idempotent(self, db_path: str) -> None:
        db = Database(db_path)
        await db.init()
        await db.init()  # Should not raise
        await db.close()

    async def test_connection_requires_init(self, db_path: str) -> None:
        db = Database(db_path)
        with pytest.raises(RuntimeError, match="not initialized"):
            async with db.connection():
                pass

    async def test_write_connection_serialises(self, db_path: str) -> None:
        db = Database(db_path)
        await db.init()

        async with db.write_connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM sessions")
            row = await cursor.fetchone()
            assert row[0] == 0

        await db.close()

    async def test_memory_database(self) -> None:
        db = Database(":memory:")
        await db.init()

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row["name"] for row in await cursor.fetchall()]

        assert "audit_chain" in tables
        assert "sessions" in tables
        assert "messages" in tables
        await db.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "audit_chain",
    "sessions",
    "messages",
    "memory_entries",
    "memory_fts",
    "skills",
    "auth_tokens",
    "user_allowlist",
    "heartbeat_tasks",
    "convergence_log",
    "trust_ledger",
    "time_lock_queue",
    "constitution_checks",
    # STOA Layer 2: TokenRevocationGuard requires this table at startup.
    # If it is missing every Bearer request logs a SQLite error.
    "token_revocations",
]


class TestSchema:
    """Test that all tables are created correctly."""

    async def test_all_tables_created(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            rows = await cursor.fetchall()
            table_names = [row["name"] for row in rows]

        for expected in EXPECTED_TABLES:
            assert expected in table_names, f"Missing table: {expected}"

    async def test_schema_version_set(self) -> None:
        assert SCHEMA_VERSION == "2.0.0"

    async def test_idempotent_creation(self) -> None:
        """Running create_tables twice should not raise."""
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()
            await create_tables(db)  # Second run
            await db.commit()

    async def test_foreign_keys_enforced(self) -> None:
        """Inserting a message with a non-existent session_id should fail."""
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await create_tables(db)
            await db.commit()

            with pytest.raises(aiosqlite.IntegrityError):
                await db.execute(
                    """
                    INSERT INTO messages (session_id, role, content, timestamp)
                    VALUES ('nonexistent', 'user', 'hello', '2026-01-01T00:00:00Z')
                    """
                )
                await db.commit()


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestAuditQueries:
    """Test audit chain query functions."""

    async def test_insert_and_retrieve_audit_entry(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            entry = await insert_audit_entry(
                db,
                event_type="test_event",
                actor="test_actor",
                details={"key": "value"},
            )
            await db.commit()

            assert entry["event_type"] == "test_event"
            assert entry["actor"] == "test_actor"
            assert entry["entry_hash"]  # Not empty
            assert entry["id"] == 1

    async def test_audit_chain_links_correctly(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            e1 = await insert_audit_entry(db, event_type="first", actor="sys")
            await db.commit()
            e2 = await insert_audit_entry(db, event_type="second", actor="sys")
            await db.commit()

            # Second entry's prev_hash should equal first entry's entry_hash
            assert e2["prev_hash"] == e1["entry_hash"]

    async def test_verify_chain_integrity_valid(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_audit_entry(db, event_type="a", actor="sys")
            await db.commit()
            await insert_audit_entry(db, event_type="b", actor="sys")
            await db.commit()

            assert await verify_chain_integrity(db) is True

    async def test_verify_chain_integrity_detects_tampering(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_audit_entry(db, event_type="a", actor="sys")
            await db.commit()
            await insert_audit_entry(db, event_type="b", actor="sys")
            await db.commit()

            # Tamper with an entry
            await db.execute(
                "UPDATE audit_chain SET details = '{\"tampered\":true}' WHERE id = 1"
            )
            await db.commit()

            assert await verify_chain_integrity(db) is False

    async def test_get_audit_chain_with_filter(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_audit_entry(db, event_type="type_a", actor="sys")
            await db.commit()
            await insert_audit_entry(db, event_type="type_b", actor="sys")
            await db.commit()
            await insert_audit_entry(db, event_type="type_a", actor="sys")
            await db.commit()

            results = await get_audit_chain(db, event_type="type_a")
            assert len(results) == 2


class TestSessionQueries:
    """Test session query functions."""

    async def test_create_and_get_session(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            session = await create_session(db, metadata={"test": True})
            await db.commit()

            retrieved = await get_session(db, session["id"])
            assert retrieved is not None
            assert retrieved["id"] == session["id"]
            assert retrieved["status"] == "active"

    async def test_get_nonexistent_session_returns_none(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            result = await get_session(db, "nonexistent-id")
            assert result is None


class TestMessageQueries:
    """Test message query functions."""

    async def test_insert_and_retrieve_messages(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            session = await create_session(db)
            await db.commit()

            msg1 = await insert_message(
                db, session_id=session["id"], role="user", content="Hello"
            )
            await db.commit()
            msg2 = await insert_message(
                db, session_id=session["id"], role="assistant", content="Hi there"
            )
            await db.commit()

            messages = await get_session_messages(db, session["id"])
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[1]["role"] == "assistant"


class TestTrustQueries:
    """Test trust ledger query functions."""

    async def test_initial_trust_score(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            score = await get_trust_score(db)
            assert score == 50.0  # Default initial

    async def test_trust_score_changes(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_trust_entry(db, action_type="success", score_delta=1.0)
            await db.commit()

            score = await get_trust_score(db)
            assert score == 51.0

            await insert_trust_entry(db, action_type="violation", score_delta=-10.0)
            await db.commit()

            score = await get_trust_score(db)
            assert score == 41.0


class TestSkillQueries:
    """Test skill query functions."""

    async def test_insert_and_list_skills(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_skill(db, name="web-search", version="1.0.0")
            await db.commit()
            await insert_skill(db, name="file-manager", version="0.5.0")
            await db.commit()

            skills = await list_skills(db)
            assert len(skills) == 2
            names = [s["name"] for s in skills]
            assert "web-search" in names
            assert "file-manager" in names

    async def test_list_skills_with_status_filter(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_skill(db, name="skill-a", status="quarantined")
            await db.commit()
            await insert_skill(db, name="skill-b", status="active")
            await db.commit()

            quarantined = await list_skills(db, status="quarantined")
            assert len(quarantined) == 1
            assert quarantined[0]["name"] == "skill-a"


class TestAuthTokenQueries:
    """Test auth token query functions."""

    async def test_insert_and_verify_token(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_token(db, token_hash="abc123hash", tier="OWNER")
            await db.commit()

            result = await verify_token(db, "abc123hash")
            assert result is not None
            assert result["tier"] == "OWNER"

    async def test_revoke_token(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            await insert_token(db, token_hash="def456hash")
            await db.commit()

            revoked = await revoke_token(db, "def456hash")
            assert revoked is True

            # Verify it is no longer valid
            result = await verify_token(db, "def456hash")
            assert result is None

    async def test_verify_nonexistent_token(self) -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_tables(db)
            await db.commit()

            result = await verify_token(db, "nonexistent")
            assert result is None


class TestDatabaseFullIntegration:
    """Test the full Database engine with queries end-to-end."""

    async def test_engine_with_queries(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "integration.db")
        engine = Database(db_path)
        await engine.init()

        # Insert via write connection
        async with engine.write_connection() as conn:
            session = await create_session(conn, metadata={"source": "test"})
            await conn.commit()

        # Read via regular connection
        async with engine.connection() as conn:
            retrieved = await get_session(conn, session["id"])

        assert retrieved is not None
        assert retrieved["status"] == "active"

        await engine.close()
