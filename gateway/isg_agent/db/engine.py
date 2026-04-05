"""SQLite WAL mode database engine management.

Handles database connection lifecycle, WAL mode configuration, and
serialised async access via an ``asyncio.Lock``. Uses aiosqlite for
non-blocking IO.

Design decisions:
- WAL mode enables concurrent reads while a write is in progress.
- Foreign keys are enabled on every connection (SQLite default is OFF).
- A single-writer lock prevents ``SQLITE_BUSY`` under concurrent writes.
- ``get_connection()`` returns a fresh connection each time (lightweight
  with aiosqlite); callers are responsible for closing via ``async with``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from isg_agent.db.schema import create_tables

__all__ = [
    "Database",
    "get_db",
    "init_db",
    "close_db",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------


class Database:
    """Async SQLite database engine with WAL mode and serialised writes.

    Parameters
    ----------
    db_path:
        Filesystem path for the SQLite database.  Parent directories are
        created automatically.  Use ``:memory:`` for an in-memory database
        (useful in tests).

    Notes
    -----
    For ``:memory:`` databases, a shared-cache URI is used so that
    multiple connections see the same in-memory database.  This avoids the
    SQLite default behaviour where each ``connect(":memory:")`` creates a
    completely separate database.
    """

    _memory_counter: int = 0  # unique per-instance in-memory DB name

    def __init__(self, db_path: str = "data/agent.db") -> None:
        self._db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._write_lock = asyncio.Lock()
        self._initialized = False
        self._keepalive: aiosqlite.Connection | None = None

        # For :memory: databases, generate a unique shared-cache URI so
        # that all connections from THIS engine instance share one DB.
        if self._is_memory:
            Database._memory_counter += 1
            self._connect_path = (
                f"file:isg_mem_{Database._memory_counter}?mode=memory&cache=shared"
            )
            self._connect_uri = True
        else:
            self._connect_path = db_path
            self._connect_uri = False

    @property
    def path(self) -> str:
        """The configured database file path."""
        return self._db_path

    @property
    def is_initialized(self) -> bool:
        """Whether ``init()`` has been called successfully."""
        return self._initialized

    # -- lifecycle ----------------------------------------------------------

    async def init(self) -> None:
        """Create the database file, enable WAL mode, and run schema creation.

        Safe to call multiple times — schema creation uses
        ``CREATE TABLE IF NOT EXISTS``.
        """
        if self._initialized:
            return

        # Ensure parent directory exists (skip for :memory:)
        if not self._is_memory:
            parent = Path(self._db_path).parent
            parent.mkdir(parents=True, exist_ok=True)

        async with self._connect() as db:
            if not self._is_memory:
                # WAL mode only meaningful for file-backed databases
                await db.execute("PRAGMA journal_mode=WAL")
            # Enable foreign key enforcement
            await db.execute("PRAGMA foreign_keys=ON")
            # Set a busy timeout (5 seconds) to avoid immediate SQLITE_BUSY
            await db.execute("PRAGMA busy_timeout=5000")
            await db.commit()

        # For in-memory databases, hold a keep-alive connection so that
        # the shared-cache database survives between connection() calls.
        if self._is_memory and self._keepalive is None:
            self._keepalive = await aiosqlite.connect(
                self._connect_path, uri=self._connect_uri
            )

        # Create all tables
        async with self._connect() as db:
            await create_tables(db)
            await db.commit()

        self._initialized = True
        logger.info("Database initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close the engine and release resources.

        For in-memory databases, closes the keep-alive connection which
        allows the shared-cache database to be destroyed.  Resets the
        initialised flag so that ``init()`` can be called again.
        """
        if self._keepalive is not None:
            await self._keepalive.close()
            self._keepalive = None
        self._initialized = False
        logger.info("Database engine closed")

    # -- connection management ---------------------------------------------

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Open a raw aiosqlite connection with pragmas applied."""
        db = await aiosqlite.connect(self._connect_path, uri=self._connect_uri)
        try:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            await db.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Provide an async context-managed database connection.

        Enables foreign keys and WAL pragmas on each connection.
        Callers should use this for **read** operations.

        Example::

            async with db.connection() as conn:
                cursor = await conn.execute("SELECT ...")
                rows = await cursor.fetchall()
        """
        if not self._initialized:
            raise RuntimeError(
                "Database not initialized. Call await db.init() first."
            )
        async with self._connect() as conn:
            yield conn

    @asynccontextmanager
    async def write_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Provide a write-serialised database connection.

        Acquires the write lock before yielding the connection, ensuring
        only one write transaction is in progress at a time.  The caller
        must explicitly ``await conn.commit()`` on success.

        Example::

            async with db.write_connection() as conn:
                await conn.execute("INSERT INTO ...")
                await conn.commit()
        """
        if not self._initialized:
            raise RuntimeError(
                "Database not initialized. Call await db.init() first."
            )
        async with self._write_lock:
            async with self._connect() as conn:
                yield conn


# ---------------------------------------------------------------------------
# Module-level singleton and helpers
# ---------------------------------------------------------------------------

_db_instance: Database | None = None


async def init_db(db_path: str = "data/agent.db") -> Database:
    """Initialise the module-level database singleton.

    Parameters
    ----------
    db_path:
        Path for the SQLite file.

    Returns
    -------
    Database
        The initialised engine singleton.
    """
    global _db_instance  # noqa: PLW0603
    _db_instance = Database(db_path)
    await _db_instance.init()
    return _db_instance


async def close_db() -> None:
    """Close the module-level database singleton."""
    global _db_instance  # noqa: PLW0603
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None


def get_db() -> Database:
    """Return the module-level database singleton.

    Intended for FastAPI ``Depends()`` injection::

        @app.get("/items")
        async def list_items(db: Database = Depends(get_db)):
            ...

    Raises
    ------
    RuntimeError
        If ``init_db()`` has not been called.
    """
    if _db_instance is None:
        raise RuntimeError(
            "Database not initialized. Call await init_db() during app startup."
        )
    return _db_instance
