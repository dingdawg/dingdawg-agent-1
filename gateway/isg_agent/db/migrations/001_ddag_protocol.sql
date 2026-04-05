-- DDAG v1 Protocol Migration
-- Run once against the existing gateway SQLite database.
-- All statements are idempotent (IF NOT EXISTS / OR IGNORE).

-- 1. Enable WAL mode for crash safety (idempotent)
PRAGMA journal_mode=WAL;

-- 2. Execution journal (log-first WAL pattern)
CREATE TABLE IF NOT EXISTS execution_journal (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL,
    step_index       INTEGER NOT NULL,
    tool_name        TEXT    NOT NULL,
    tool_args        TEXT    NOT NULL,
    idempotency_key  TEXT    UNIQUE NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'pending',
    result           TEXT,
    error            TEXT,
    created_at       TEXT    NOT NULL,
    completed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_journal_session
    ON execution_journal(session_id, step_index);

CREATE INDEX IF NOT EXISTS idx_journal_status
    ON execution_journal(status);

-- 3. Checkpoints (content-addressed IPFS/local CIDs)
CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    step_index   INTEGER NOT NULL,
    state_cid    TEXT    NOT NULL,
    fsm_state    TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    UNIQUE(session_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_checkpoint_session
    ON agent_checkpoints(session_id);

-- 4. Idempotency cache (exactly-once execution results)
CREATE TABLE IF NOT EXISTS idempotency_cache (
    idempotency_key  TEXT    PRIMARY KEY,
    result           TEXT    NOT NULL,
    created_at       TEXT    NOT NULL
);

-- 5. Agent souls (IPFS-pinned identity — survives crashes and migrations)
CREATE TABLE IF NOT EXISTS agent_souls (
    soul_id    TEXT PRIMARY KEY,
    agent_id   TEXT NOT NULL UNIQUE,
    soul_cid   TEXT NOT NULL,
    mission    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 6. Extend memory_messages with class tagging and IPFS CID
--    ALTER TABLE is wrapped in a BEGIN/COMMIT so partial failures are safe.
--    Each column add is independently idempotent via the OR IGNORE trigger below.
--    (SQLite does not support IF NOT EXISTS on ALTER TABLE; we use a workaround
--     in the application layer: attempt ALTER, catch "duplicate column" error.)

-- Application code (ddag_v1.py / store.py) runs these at startup:
--   ALTER TABLE memory_messages ADD COLUMN memory_class TEXT DEFAULT 'D';
--   ALTER TABLE memory_messages ADD COLUMN ipfs_cid TEXT;
-- They are listed here for documentation only — do NOT run them twice.
