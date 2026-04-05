"""Shared test fixtures for ISG Agent 1 test suite."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import AsyncIterator, Generator

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.app import create_app
from isg_agent.config import Settings


@pytest.fixture()
def tmp_db_path() -> Generator[Path, None, None]:
    """Provide a temporary database path that is cleaned up after the test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    yield db_path

    if db_path.exists():
        db_path.unlink()
    # Also clean up WAL and SHM files
    for suffix in ("-wal", "-shm"):
        wal_path = Path(str(db_path) + suffix)
        if wal_path.exists():
            wal_path.unlink()


@pytest.fixture()
def test_settings(tmp_db_path: Path) -> Settings:
    """Create test-specific settings with temporary database."""
    return Settings(
        secret_key="test-secret-do-not-use-in-production",
        db_path=str(tmp_db_path),
        host="127.0.0.1",
        port=8900,
        log_level="debug",
        workspace_root=str(tmp_db_path.parent),
    )


@pytest.fixture()
def env_override(tmp_db_path: Path) -> Generator[dict[str, str], None, None]:
    """Set environment variables for testing, then restore originals."""
    overrides = {
        "ISG_AGENT_DB_PATH": str(tmp_db_path),
        "ISG_AGENT_SECRET_KEY": "test-secret-do-not-use-in-production",
    }
    originals: dict[str, str | None] = {}

    for key, value in overrides.items():
        originals[key] = os.environ.get(key)
        os.environ[key] = value

    yield overrides

    for key, original in originals.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Provide an async HTTP client bound to the test application."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def verify_user_email(db_path: str, email: str) -> None:
    """Auto-verify a user's email directly in the test DB.

    Use this in test fixtures after registration to bypass the email
    verification gate so login calls succeed.

    Args:
        db_path: Path to the SQLite database file.
        email: The user's email address to mark as verified.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE users SET email_verified=1 WHERE email=?", (email,))
        await db.commit()


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> Generator[None, None, None]:
    """Reset the in-memory rate limiter storage before each test.

    The rate limiter is a module-level singleton using in-memory storage.
    Without a reset, state accumulates across tests and triggers 429 errors
    in tests that call rate-limited endpoints many times within a session.
    """
    from isg_agent.middleware.rate_limiter_middleware import limiter
    limiter._storage.reset()
    yield
