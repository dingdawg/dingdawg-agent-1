"""Idempotent database schema creation (CREATE TABLE IF NOT EXISTS).

Defines all tables for the ISG Agent 1 gateway:

- ``audit_chain``         — SHA-256 hash-chained tamper-evident log
- ``sessions``            — Agent chat sessions
- ``messages``            — Per-session message history
- ``memory_entries``      — Long-term memory store
- ``memory_fts``          — FTS5 virtual table for keyword search
- ``skills``              — Installed skill registry
- ``auth_tokens``         — API authentication tokens
- ``user_allowlist``      — Allowed users / device pairings
- ``heartbeat_tasks``     — Periodic background task registry
- ``convergence_log``     — Per-iteration convergence tracking
- ``trust_ledger``        — Transparent trust score journal
- ``time_lock_queue``     — Pending time-locked actions
- ``constitution_checks`` — Constitution enforcement audit log
- ``agents``              — Core agent registry (personal + business)
- ``agent_templates``     — Industry/purpose agent templates
- ``agent_handles``       — Handle reservation + history
- ``agent_tasks``         — Personal agent task tracking
- ``agent_messages``      — Inter-agent communication log
- ``usage_tracking``      — Per-agent usage for billing
- ``marketplace_templates`` — Community-authored marketplace templates
- ``template_ratings``    — One rating per user per marketplace template
- ``template_installs``   — Records every marketplace template install
- ``creator_profiles``    — Creator metadata and Stripe Connect info
- ``agent_webhooks``      — Per-agent outbound webhook subscriptions
- ``token_revocations``  — STOA Layer 2 revocation list (TokenRevocationGuard)
- ``comm_pair_secrets``  — Per-pair random encryption secrets for inter-agent comms

All statements are ``CREATE TABLE IF NOT EXISTS`` so they are safe to
execute on every startup (idempotent).
"""

from __future__ import annotations

import aiosqlite

from isg_agent.agents.agent_types import VALID_AGENT_TYPES

__all__ = [
    "create_tables",
    "SCHEMA_VERSION",
]

SCHEMA_VERSION: str = "2.0.0"

# SQL CHECK expression built from VALID_AGENT_TYPES — single source of truth.
_AGENT_TYPE_SQL_VALUES: str = ", ".join(
    f"'{t}'" for t in sorted(VALID_AGENT_TYPES)
)

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

_AUDIT_CHAIN = """
CREATE TABLE IF NOT EXISTS audit_chain (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    actor       TEXT    NOT NULL,
    action      TEXT    NOT NULL DEFAULT '',
    details     TEXT    NOT NULL DEFAULT '{}',
    entry_hash  TEXT    NOT NULL,
    prev_hash   TEXT    NOT NULL,
    session_id  TEXT
);
"""

_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT    PRIMARY KEY,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'active',
    metadata    TEXT    NOT NULL DEFAULT '{}'
);
"""

_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL,
    metadata    TEXT    NOT NULL DEFAULT '{}',
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""

_MEMORY_ENTRIES = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT    NOT NULL,
    embedding_hash  TEXT,
    created_at      TEXT    NOT NULL,
    metadata        TEXT    NOT NULL DEFAULT '{}'
);
"""

_MEMORY_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    content_rowid='id',
    tokenize='porter unicode61'
);
"""

_SKILLS = """
CREATE TABLE IF NOT EXISTS skills (
    id              TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,
    version         TEXT    NOT NULL DEFAULT '0.1.0',
    manifest        TEXT    NOT NULL DEFAULT '{}',
    status          TEXT    NOT NULL DEFAULT 'quarantined',
    reputation_score REAL   NOT NULL DEFAULT 0.0,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
"""

_AUTH_TOKENS = """
CREATE TABLE IF NOT EXISTS auth_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT    NOT NULL UNIQUE,
    tier        TEXT    NOT NULL DEFAULT 'USER',
    user_id     TEXT,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT,
    revoked     INTEGER NOT NULL DEFAULT 0
);
"""

_USER_ALLOWLIST = """
CREATE TABLE IF NOT EXISTS user_allowlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier  TEXT    NOT NULL UNIQUE,
    tier        TEXT    NOT NULL DEFAULT 'USER',
    created_at  TEXT    NOT NULL
);
"""

_HEARTBEAT_TASKS = """
CREATE TABLE IF NOT EXISTS heartbeat_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    interval_seconds INTEGER NOT NULL DEFAULT 60,
    last_run        TEXT,
    status          TEXT    NOT NULL DEFAULT 'active'
);
"""

_CONVERGENCE_LOG = """
CREATE TABLE IF NOT EXISTS convergence_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    iteration       INTEGER NOT NULL,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    budget_remaining TEXT   NOT NULL DEFAULT '{}',
    timestamp       TEXT    NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""

_TRUST_LEDGER = """
CREATE TABLE IF NOT EXISTS trust_ledger (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    action_type         TEXT    NOT NULL,
    score_delta         REAL    NOT NULL,
    running_total       REAL    NOT NULL,
    audit_chain_entry_id INTEGER,
    FOREIGN KEY (audit_chain_entry_id) REFERENCES audit_chain(id)
);
"""

_TIME_LOCK_QUEUE = """
CREATE TABLE IF NOT EXISTS time_lock_queue (
    id                  TEXT    PRIMARY KEY,
    action_description  TEXT    NOT NULL,
    risk_tier           TEXT    NOT NULL,
    execute_at          TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'pending',
    cancellable_until   TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    callback_data       TEXT
);
"""

_CONSTITUTION_CHECKS = """
CREATE TABLE IF NOT EXISTS constitution_checks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    rule_id             TEXT    NOT NULL,
    action              TEXT    NOT NULL,
    decision            TEXT    NOT NULL,
    reason              TEXT    NOT NULL DEFAULT '',
    audit_chain_entry_id INTEGER,
    FOREIGN KEY (audit_chain_entry_id) REFERENCES audit_chain(id)
);
"""

# ---------------------------------------------------------------------------
# New agent platform tables (v2.0.0)
# ---------------------------------------------------------------------------

_AGENTS = f"""
CREATE TABLE IF NOT EXISTS agents (
    id                  TEXT    PRIMARY KEY,
    user_id             TEXT    NOT NULL,
    handle              TEXT    UNIQUE NOT NULL,
    name                TEXT    NOT NULL,
    agent_type          TEXT    NOT NULL CHECK(agent_type IN ({_AGENT_TYPE_SQL_VALUES})),
    industry_type       TEXT,
    template_id         TEXT,
    config_json         TEXT    NOT NULL DEFAULT '{{}}',
    branding_json       TEXT    NOT NULL DEFAULT '{{}}',
    constitution_yaml   TEXT,
    status              TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'archived')),
    subscription_tier   TEXT    NOT NULL DEFAULT 'free' CHECK(subscription_tier IN ('free', 'starter', 'pro', 'enterprise')),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
"""

_AGENT_TEMPLATES = f"""
CREATE TABLE IF NOT EXISTS agent_templates (
    id                      TEXT    PRIMARY KEY,
    name                    TEXT    NOT NULL,
    agent_type              TEXT    NOT NULL CHECK(agent_type IN ({_AGENT_TYPE_SQL_VALUES})),
    industry_type           TEXT,
    system_prompt_template  TEXT    NOT NULL DEFAULT '',
    flow_json               TEXT    NOT NULL DEFAULT '{{}}',
    catalog_schema_json     TEXT,
    capabilities            TEXT    NOT NULL DEFAULT '[]',
    default_constitution_yaml TEXT,
    icon                    TEXT,
    created_at              TEXT    NOT NULL
);
"""

_AGENT_HANDLES = """
CREATE TABLE IF NOT EXISTS agent_handles (
    handle              TEXT    PRIMARY KEY,
    agent_id            TEXT,
    claimed_at          TEXT,
    reserved_at         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'released', 'suspended'))
);
"""

_AGENT_TASKS = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    id                  TEXT    PRIMARY KEY,
    agent_id            TEXT    NOT NULL,
    user_id             TEXT    NOT NULL,
    task_type           TEXT    NOT NULL CHECK(task_type IN ('errand', 'purchase', 'booking', 'reminder', 'email', 'research', 'other')),
    description         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')),
    delegated_to        TEXT,
    result_json         TEXT,
    tokens_used         INTEGER NOT NULL DEFAULT 0,
    cost_cents          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    completed_at        TEXT
);
"""

_AGENT_MESSAGES = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id                  TEXT    PRIMARY KEY,
    from_agent          TEXT    NOT NULL,
    to_agent            TEXT    NOT NULL,
    message_type        TEXT    NOT NULL CHECK(message_type IN ('request', 'response', 'confirmation', 'receipt')),
    payload_encrypted   TEXT    NOT NULL,
    governance_hash     TEXT,
    proof_hash          TEXT,
    status              TEXT    NOT NULL DEFAULT 'sent' CHECK(status IN ('sent', 'delivered', 'read', 'expired')),
    created_at          TEXT    NOT NULL
);
"""

_USAGE_TRACKING = """
CREATE TABLE IF NOT EXISTS usage_tracking (
    id                  TEXT    PRIMARY KEY,
    agent_id            TEXT    NOT NULL,
    period              TEXT    NOT NULL,
    llm_tokens          INTEGER NOT NULL DEFAULT 0,
    api_calls           INTEGER NOT NULL DEFAULT 0,
    tasks_completed     INTEGER NOT NULL DEFAULT 0,
    transactions        INTEGER NOT NULL DEFAULT 0,
    cost_cents          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    UNIQUE(agent_id, period)
);
"""

# ---------------------------------------------------------------------------
# Marketplace tables (v2.1.0)
# ---------------------------------------------------------------------------

_MARKETPLACE_TEMPLATES = """
CREATE TABLE IF NOT EXISTS marketplace_templates (
    id                      TEXT    PRIMARY KEY,
    base_template_id        TEXT    NOT NULL,
    author_user_id          TEXT    NOT NULL,
    forked_from_id          TEXT,
    display_name            TEXT    NOT NULL,
    tagline                 TEXT    NOT NULL DEFAULT '',
    description_md          TEXT    NOT NULL DEFAULT '',
    preview_json            TEXT    NOT NULL DEFAULT '{}',
    tags                    TEXT    NOT NULL DEFAULT '[]',
    agent_type              TEXT    NOT NULL,
    industry_type           TEXT,
    status                  TEXT    NOT NULL DEFAULT 'draft'
                            CHECK(status IN ('draft','submitted','under_review','approved','rejected','withdrawn')),
    rejection_reason        TEXT,
    reviewed_by             TEXT,
    reviewed_at             TEXT,
    submitted_at            TEXT,
    published_at            TEXT,
    price_cents             INTEGER NOT NULL DEFAULT 0,
    stripe_price_id         TEXT,
    revenue_share_pct       INTEGER NOT NULL DEFAULT 70,
    install_count           INTEGER NOT NULL DEFAULT 0,
    fork_count              INTEGER NOT NULL DEFAULT 0,
    avg_rating              REAL    NOT NULL DEFAULT 0.0,
    rating_count            INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL
);
"""

_TEMPLATE_RATINGS = """
CREATE TABLE IF NOT EXISTS template_ratings (
    id                      TEXT    PRIMARY KEY,
    marketplace_template_id TEXT    NOT NULL,
    user_id                 TEXT    NOT NULL,
    stars                   INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
    review_text             TEXT,
    helpful_count           INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL,
    UNIQUE(marketplace_template_id, user_id)
);
"""

_TEMPLATE_INSTALLS = """
CREATE TABLE IF NOT EXISTS template_installs (
    id                      TEXT    PRIMARY KEY,
    marketplace_template_id TEXT    NOT NULL,
    base_template_id        TEXT    NOT NULL,
    installer_user_id       TEXT    NOT NULL,
    agent_id                TEXT    NOT NULL,
    payment_intent_id       TEXT,
    amount_paid_cents       INTEGER NOT NULL DEFAULT 0,
    platform_fee_cents      INTEGER NOT NULL DEFAULT 0,
    creator_payout_cents    INTEGER NOT NULL DEFAULT 0,
    payout_status           TEXT    NOT NULL DEFAULT 'not_applicable'
                            CHECK(payout_status IN ('pending','paid','failed','not_applicable')),
    installed_at            TEXT    NOT NULL
);
"""

_CREATOR_PROFILES = """
CREATE TABLE IF NOT EXISTS creator_profiles (
    user_id                 TEXT    PRIMARY KEY,
    display_name            TEXT    NOT NULL DEFAULT '',
    bio                     TEXT    NOT NULL DEFAULT '',
    stripe_connect_id       TEXT,
    connect_verified        INTEGER NOT NULL DEFAULT 0,
    total_earned_cents      INTEGER NOT NULL DEFAULT 0,
    template_count          INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL
);
"""

_AGENT_WEBHOOKS = """
CREATE TABLE IF NOT EXISTS agent_webhooks (
    id          TEXT    PRIMARY KEY,
    agent_id    TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    events      TEXT    NOT NULL DEFAULT '[]',
    auth_type   TEXT    NOT NULL DEFAULT 'none' CHECK(auth_type IN ('none', 'bearer', 'basic')),
    auth_value  TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# WebAuthn/Passkey tables
# ---------------------------------------------------------------------------

_WEBAUTHN_CREDENTIALS = """
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    credential_id TEXT NOT NULL UNIQUE,
    public_key   BLOB NOT NULL,
    sign_count   INTEGER NOT NULL DEFAULT 0,
    device_name  TEXT,
    transports   TEXT,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
"""

_WEBAUTHN_CHALLENGES = """
CREATE TABLE IF NOT EXISTS webauthn_challenges (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    challenge     TEXT NOT NULL,
    ceremony_type TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Token revocation table (STOA Layer 2 — TokenRevocationGuard middleware)
# ---------------------------------------------------------------------------
# This table lives in the main agent.db alongside all other tables.
# It is separate from `auth_tokens` which stores token *metadata*.
# `token_revocations` stores the revocation list: tokens that have been
# explicitly invalidated (e.g. on logout) and must be rejected on every
# subsequent request regardless of JWT expiry.
#
# The TokenRevocationGuard middleware queries this table on every Bearer
# request. If the table does not exist the middleware logs a warning and
# fails open (the request proceeds). Creating it here during DB init
# eliminates that per-request warning entirely.
_TOKEN_REVOCATIONS = """
CREATE TABLE IF NOT EXISTS token_revocations (
    token_hash  TEXT    PRIMARY KEY,
    revoked     INTEGER NOT NULL DEFAULT 0,
    revoked_at  TEXT
);
"""

# ---------------------------------------------------------------------------
# Usage metering tables (payments/usage_meter.py)
#
# Previously created only by UsageMeter.init_tables() at runtime, which meant
# a fresh Database.init() had no usage tables until the lifespan hook ran.
# Self-healing checks and admin queries both depend on these tables existing
# as part of the core schema, so they are declared here alongside all other
# tables.  UsageMeter.init_tables() remains idempotent — it uses
# CREATE TABLE IF NOT EXISTS and will no-op on databases that already have
# these tables from this schema path.
# ---------------------------------------------------------------------------

_USAGE_RECORDS = """
CREATE TABLE IF NOT EXISTS usage_records (
    id                      TEXT    PRIMARY KEY,
    agent_id                TEXT    NOT NULL,
    user_id                 TEXT    NOT NULL,
    skill_name              TEXT    NOT NULL,
    action                  TEXT    NOT NULL DEFAULT '',
    amount_cents            INTEGER NOT NULL DEFAULT 0,
    status                  TEXT    NOT NULL DEFAULT 'recorded',
    stripe_usage_record_id  TEXT    NOT NULL DEFAULT '',
    created_at              TEXT    NOT NULL
);
"""

_USAGE_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS usage_subscriptions (
    id                          TEXT    PRIMARY KEY,
    agent_id                    TEXT    NOT NULL,
    user_id                     TEXT    NOT NULL,
    stripe_customer_id          TEXT    NOT NULL DEFAULT '',
    stripe_subscription_id      TEXT    NOT NULL DEFAULT '',
    plan                        TEXT    NOT NULL DEFAULT 'free',
    actions_included            INTEGER NOT NULL DEFAULT 50,
    current_period_start        TEXT    NOT NULL,
    current_period_end          TEXT    NOT NULL,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    created_at                  TEXT    NOT NULL,
    updated_at                  TEXT    NOT NULL,
    UNIQUE(agent_id, user_id)
);
"""

_USAGE_SUMMARY = """
CREATE TABLE IF NOT EXISTS usage_summary (
    id                  TEXT    PRIMARY KEY,
    agent_id            TEXT    NOT NULL,
    year_month          TEXT    NOT NULL,
    total_actions       INTEGER NOT NULL DEFAULT 0,
    free_actions        INTEGER NOT NULL DEFAULT 0,
    billed_actions      INTEGER NOT NULL DEFAULT 0,
    total_amount_cents  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    UNIQUE(agent_id, year_month)
);
"""

# ---------------------------------------------------------------------------
# Skill notifications table (skills/builtin/notifications.py)
#
# Previously created only by notifications.init_tables() at runtime.
# The notification_worker polls this table on startup and admin/health
# queries reference it — so it must exist as part of core schema init.
# notifications.init_tables() remains idempotent (CREATE IF NOT EXISTS).
# ---------------------------------------------------------------------------

_SKILL_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS skill_notifications (
    id              TEXT    PRIMARY KEY,
    agent_id        TEXT    NOT NULL,
    channel         TEXT    NOT NULL,
    recipient       TEXT    NOT NULL,
    subject         TEXT,
    body            TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'queued',
    priority        TEXT    NOT NULL DEFAULT 'normal',
    scheduled_for   TEXT,
    sent_at         TEXT,
    error           TEXT,
    metadata        TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Client-side error collection table
#
# Stores JS errors, unhandled rejections, API failures, and render errors
# reported by the frontend errorReporter service via POST /admin/client-errors.
# Kept separate from audit_chain so client errors can be cleared independently
# without affecting the tamper-evident server-side audit log.
# ---------------------------------------------------------------------------

_CLIENT_ERRORS = """
CREATE TABLE IF NOT EXISTS client_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message     TEXT    NOT NULL,
    stack       TEXT,
    url         TEXT    NOT NULL DEFAULT '',
    error_type  TEXT    NOT NULL DEFAULT 'js_error',
    component   TEXT,
    extra       TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Inter-agent comm pair secrets — per-pair random 32-byte shared secrets
#
# Replaces the handle-derived deterministic key (SHA-256 of public handles)
# with a server-generated random secret stored here.  The canonical pair key
# is keyed on the lexicographically sorted handle pair so key(A→B)==key(B→A).
# ---------------------------------------------------------------------------

_COMM_PAIR_SECRETS = """
CREATE TABLE IF NOT EXISTS comm_pair_secrets (
    pair_key    TEXT    PRIMARY KEY,
    secret_b64  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Zapier webhook subscriptions — stores Zapier REST Hook callback URLs
# ---------------------------------------------------------------------------

_ZAPIER_WEBHOOK_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS zapier_webhook_subscriptions (
    id          TEXT    PRIMARY KEY,
    user_id     TEXT    NOT NULL,
    agent_id    TEXT,
    event_type  TEXT    NOT NULL,
    target_url  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Customer management — Sprint 1
# ---------------------------------------------------------------------------

_CUSTOMERS = """
CREATE TABLE IF NOT EXISTS customers (
    id                      TEXT PRIMARY KEY,
    user_id                 TEXT NOT NULL UNIQUE,
    email                   TEXT NOT NULL,
    full_name               TEXT,
    company                 TEXT,
    role                    TEXT,
    stripe_customer_id      TEXT UNIQUE,
    signup_source           TEXT NOT NULL DEFAULT 'web',
    subscription_status     TEXT NOT NULL DEFAULT 'free'
                            CHECK(subscription_status IN ('free','trialing','active','past_due','cancelled','churned','suspended')),
    subscription_tier       TEXT NOT NULL DEFAULT 'free',
    stripe_subscription_id  TEXT,
    current_period_start    TEXT,
    current_period_end      TEXT,
    trial_ends_at           TEXT,
    cancelled_at            TEXT,
    cancellation_reason     TEXT,
    churned_at              TEXT,
    reactivated_at          TEXT,
    ltv_cents               INTEGER NOT NULL DEFAULT 0,
    notes                   TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
"""

_BILLING_EVENTS = """
CREATE TABLE IF NOT EXISTS billing_events (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    stripe_event_id     TEXT UNIQUE,
    amount_cents        INTEGER NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'usd',
    invoice_id          TEXT,
    failure_reason      TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    metadata            TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
"""

_REFUNDS = """
CREATE TABLE IF NOT EXISTS refunds (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    stripe_refund_id    TEXT UNIQUE,
    amount_cents        INTEGER NOT NULL,
    reason              TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','succeeded','failed','cancelled')),
    initiated_by        TEXT NOT NULL DEFAULT 'admin',
    notes               TEXT,
    created_at          TEXT NOT NULL,
    resolved_at         TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
"""

_DUNNING_EVENTS = """
CREATE TABLE IF NOT EXISTS dunning_events (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    stage               INTEGER NOT NULL,
    invoice_id          TEXT,
    action_taken        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
"""

_SUPPORT_TICKETS = """
CREATE TABLE IF NOT EXISTS support_tickets (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    subject             TEXT NOT NULL,
    body                TEXT,
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','in_progress','resolved','closed')),
    priority            TEXT NOT NULL DEFAULT 'normal'
                        CHECK(priority IN ('low','normal','high','urgent')),
    category            TEXT DEFAULT 'general',
    assigned_to         TEXT,
    resolved_at         TEXT,
    csat_score          INTEGER CHECK(csat_score BETWEEN 1 AND 5),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
"""

_EMAIL_LOG = """
CREATE TABLE IF NOT EXISTS email_log (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT,
    user_id             TEXT,
    template_id         TEXT NOT NULL,
    to_email            TEXT NOT NULL,
    subject             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued'
                        CHECK(status IN ('queued','sent','delivered','opened','clicked','bounced','failed')),
    provider_message_id TEXT,
    opened_at           TEXT,
    clicked_at          TEXT,
    bounced_at          TEXT,
    metadata            TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL
);
"""

_PASSWORD_RESET_TOKENS = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash          TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    expires_at          TEXT NOT NULL,
    used                INTEGER NOT NULL DEFAULT 0,
    used_at             TEXT,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

_MFA_BACKUP_CODES = """
CREATE TABLE IF NOT EXISTS mfa_backup_codes (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    code_hash           TEXT NOT NULL,
    used                INTEGER NOT NULL DEFAULT 0,
    used_at             TEXT,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

# ---------------------------------------------------------------------------
# Index definitions
# ---------------------------------------------------------------------------

_INDEXES: list[str] = [
    # audit_chain
    "CREATE INDEX IF NOT EXISTS idx_audit_chain_event_type ON audit_chain(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_audit_chain_timestamp ON audit_chain(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_audit_chain_session_id ON audit_chain(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_chain_actor ON audit_chain(actor);",

    # sessions
    "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);",

    # messages
    "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);",

    # memory_entries
    "CREATE INDEX IF NOT EXISTS idx_memory_entries_created_at ON memory_entries(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_memory_entries_embedding_hash ON memory_entries(embedding_hash);",

    # skills
    "CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);",
    "CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);",

    # auth_tokens
    "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens(expires_at);",

    # convergence_log
    "CREATE INDEX IF NOT EXISTS idx_convergence_log_session_id ON convergence_log(session_id);",

    # trust_ledger
    "CREATE INDEX IF NOT EXISTS idx_trust_ledger_timestamp ON trust_ledger(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_trust_ledger_action_type ON trust_ledger(action_type);",

    # time_lock_queue
    "CREATE INDEX IF NOT EXISTS idx_time_lock_queue_status ON time_lock_queue(status);",
    "CREATE INDEX IF NOT EXISTS idx_time_lock_queue_execute_at ON time_lock_queue(execute_at);",

    # constitution_checks
    "CREATE INDEX IF NOT EXISTS idx_constitution_checks_rule_id ON constitution_checks(rule_id);",
    "CREATE INDEX IF NOT EXISTS idx_constitution_checks_timestamp ON constitution_checks(timestamp);",

    # agents
    "CREATE INDEX IF NOT EXISTS idx_agents_handle ON agents(handle);",
    "CREATE INDEX IF NOT EXISTS idx_agents_user ON agents(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type);",
    "CREATE INDEX IF NOT EXISTS idx_agents_industry ON agents(industry_type);",

    # agent_handles
    "CREATE INDEX IF NOT EXISTS idx_agent_handles_agent ON agent_handles(agent_id);",

    # agent_tasks
    "CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent ON agent_tasks(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);",

    # agent_messages
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_from ON agent_messages(from_agent);",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_to ON agent_messages(to_agent);",

    # usage_tracking
    "CREATE INDEX IF NOT EXISTS idx_usage_tracking_agent ON usage_tracking(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_usage_tracking_period ON usage_tracking(period);",

    # agent_id columns on existing tables
    "CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_chain_agent_id ON audit_chain(agent_id);",

    # marketplace_templates
    "CREATE INDEX IF NOT EXISTS idx_mktpl_status ON marketplace_templates(status);",
    "CREATE INDEX IF NOT EXISTS idx_mktpl_agent_type ON marketplace_templates(agent_type);",
    "CREATE INDEX IF NOT EXISTS idx_mktpl_industry ON marketplace_templates(industry_type);",
    "CREATE INDEX IF NOT EXISTS idx_mktpl_author ON marketplace_templates(author_user_id);",
    "CREATE INDEX IF NOT EXISTS idx_mktpl_rating ON marketplace_templates(avg_rating);",

    # agent_webhooks
    "CREATE INDEX IF NOT EXISTS idx_agent_webhooks_agent ON agent_webhooks(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_webhooks_active ON agent_webhooks(active);",

    # usage_records
    "CREATE INDEX IF NOT EXISTS idx_usage_records_agent ON usage_records(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_usage_records_user ON usage_records(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_usage_records_created ON usage_records(created_at);",

    # usage_subscriptions
    "CREATE INDEX IF NOT EXISTS idx_usage_subs_agent_user ON usage_subscriptions(agent_id, user_id);",

    # usage_summary
    "CREATE INDEX IF NOT EXISTS idx_usage_summary_agent_month ON usage_summary(agent_id, year_month);",

    # skill_notifications
    "CREATE INDEX IF NOT EXISTS idx_notifications_agent ON skill_notifications(agent_id, status, channel);",

    # webauthn_credentials
    "CREATE INDEX IF NOT EXISTS idx_webauthn_creds_user ON webauthn_credentials(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_webauthn_creds_credential ON webauthn_credentials(credential_id);",

    # webauthn_challenges
    "CREATE INDEX IF NOT EXISTS idx_webauthn_challenges_user ON webauthn_challenges(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_webauthn_challenges_expires ON webauthn_challenges(expires_at);",

    # client_errors
    "CREATE INDEX IF NOT EXISTS idx_client_errors_created ON client_errors(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_client_errors_type ON client_errors(error_type);",

    # zapier_webhook_subscriptions
    "CREATE INDEX IF NOT EXISTS idx_zapier_webhook_subs_event ON zapier_webhook_subscriptions(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_zapier_webhook_subs_user ON zapier_webhook_subscriptions(user_id);",

    # comm_pair_secrets — pair_key is PRIMARY KEY (already indexed); created_at for TTL queries
    "CREATE INDEX IF NOT EXISTS idx_comm_pair_secrets_created ON comm_pair_secrets(created_at);",
]

# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

_TABLE_STATEMENTS: list[str] = [
    _AUDIT_CHAIN,
    _SESSIONS,
    _MESSAGES,
    _MEMORY_ENTRIES,
    _MEMORY_FTS,
    _SKILLS,
    _AUTH_TOKENS,
    _USER_ALLOWLIST,
    _HEARTBEAT_TASKS,
    _CONVERGENCE_LOG,
    _TRUST_LEDGER,
    _TIME_LOCK_QUEUE,
    _CONSTITUTION_CHECKS,
    _AGENTS,
    _AGENT_TEMPLATES,
    _AGENT_HANDLES,
    _AGENT_TASKS,
    _AGENT_MESSAGES,
    _USAGE_TRACKING,
    _MARKETPLACE_TEMPLATES,
    _TEMPLATE_RATINGS,
    _TEMPLATE_INSTALLS,
    _CREATOR_PROFILES,
    _AGENT_WEBHOOKS,
    # STOA Layer 2: must exist before any request hits TokenRevocationGuard
    _TOKEN_REVOCATIONS,
    # Usage metering — must exist before admin queries and self-healing checks
    _USAGE_RECORDS,
    _USAGE_SUBSCRIPTIONS,
    _USAGE_SUMMARY,
    # Skill notifications — must exist before notification_worker polls
    _SKILL_NOTIFICATIONS,
    # WebAuthn/Passkey — must exist before any passkey endpoint is called
    _WEBAUTHN_CREDENTIALS,
    _WEBAUTHN_CHALLENGES,
    # Client-side error collection — must exist before POST /admin/client-errors
    _CLIENT_ERRORS,
    # Zapier webhook subscriptions — REST Hook callback URLs
    _ZAPIER_WEBHOOK_SUBSCRIPTIONS,
    # Inter-agent comms encryption — per-pair random shared secrets
    _COMM_PAIR_SECRETS,
    # Customer management — master record, billing, refunds, dunning, support
    _CUSTOMERS,
    _BILLING_EVENTS,
    _REFUNDS,
    _DUNNING_EVENTS,
    _SUPPORT_TICKETS,
    # Transactional email log — every outbound email tracked
    _EMAIL_LOG,
    # Auth recovery — password reset tokens + MFA backup codes
    _PASSWORD_RESET_TOKENS,
    _MFA_BACKUP_CODES,
]


async def _add_column_if_not_exists(
    db: aiosqlite.Connection,
    table: str,
    column: str,
    col_type: str,
) -> None:
    """Add a column to an existing table, ignoring if it already exists.

    SQLite raises an error on duplicate ``ALTER TABLE ADD COLUMN``.
    This helper catches that error so the migration is idempotent.

    Parameters
    ----------
    db:
        An open aiosqlite connection.
    table:
        Target table name.
    column:
        New column name.
    col_type:
        SQL type expression (e.g. ``"TEXT"``).
    """
    try:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass  # Column already exists — safe to ignore


async def _migrate_agent_type_check(db: aiosqlite.Connection) -> None:
    """Expand the agent_type CHECK constraint on existing SQLite databases.

    SQLite cannot ALTER CHECK constraints.  When we detect that an existing
    ``agents`` or ``agent_templates`` table is missing any value from
    ``VALID_AGENT_TYPES`` we recreate the table with the full constraint
    and copy all data across.  Everything is wrapped in a single transaction
    so the operation is atomic.

    This migration is idempotent: if the table already carries the expanded
    constraint (or if the table does not yet exist) it exits without changes.

    Parameters
    ----------
    db:
        An open aiosqlite connection.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    for table in ("agents", "agent_templates"):
        # Fetch the current CREATE TABLE SQL from sqlite_master.
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        row = await cursor.fetchone()
        if row is None:
            # Table doesn't exist yet — create_tables will handle it.
            continue

        existing_sql: str = row[0] or ""

        # Check if every type in VALID_AGENT_TYPES is already present.
        # If so, the constraint is fully up to date — nothing to do.
        all_present = all(
            f"'{t}'" in existing_sql for t in VALID_AGENT_TYPES
        )
        if all_present:
            continue

        # Only migrate tables that have an agent_type CHECK constraint.
        if "'personal'" not in existing_sql:
            continue

        _log.info(
            "schema.migrate: expanding agent_type CHECK on table '%s'", table
        )

        # Build the replacement CREATE TABLE SQL by substituting any
        # existing agent_type IN (...) constraint with the full set.
        new_check = f"agent_type IN ({_AGENT_TYPE_SQL_VALUES})"

        # Match any existing agent_type IN (...) pattern via regex.
        import re as _re
        pattern = r"agent_type\s+IN\s*\([^)]+\)"
        new_sql = _re.sub(pattern, f"agent_type IN ({_AGENT_TYPE_SQL_VALUES})", existing_sql)

        if new_sql == existing_sql:
            # Constraint text doesn't match known patterns — skip to be safe.
            _log.warning(
                "schema.migrate: could not find old CHECK in '%s' — skipping", table
            )
            continue

        # Rename the old table, recreate with the new constraint, copy data,
        # then drop the backup — all inside the caller's transaction.
        backup = f"_bak_{table}_agent_type_expand"
        await db.execute(f"ALTER TABLE {table} RENAME TO {backup}")
        # The new_sql still starts with 'CREATE TABLE <table_name> ...'
        # but the table name was renamed, so we create fresh from new_sql.
        # new_sql already references the original table name, so this works.
        await db.execute(new_sql)
        await db.execute(f"INSERT INTO {table} SELECT * FROM {backup}")
        await db.execute(f"DROP TABLE {backup}")

        _log.info(
            "schema.migrate: table '%s' upgraded to expanded agent_type CHECK", table
        )


async def create_tables(db: aiosqlite.Connection) -> None:
    """Execute all CREATE TABLE and CREATE INDEX statements.

    All statements are idempotent (``IF NOT EXISTS``).  Safe to call on
    every application startup.

    Also runs the agent_type CHECK constraint migration for existing Railway
    SQLite databases that were created before the 7-type expansion.

    Parameters
    ----------
    db:
        An open aiosqlite connection.  The caller is responsible for
        committing the transaction after this function returns.
    """
    # Enable foreign key support
    await db.execute("PRAGMA foreign_keys=ON")

    # Migrate existing agent_type CHECK constraints before creating tables
    # (CREATE TABLE IF NOT EXISTS will skip already-existing tables, so the
    # migration must run first to upgrade the CHECK on existing tables).
    await _migrate_agent_type_check(db)

    # Create tables
    for stmt in _TABLE_STATEMENTS:
        await db.execute(stmt)

    # Add agent_id columns to existing tables (idempotent)
    await _add_column_if_not_exists(db, "sessions", "agent_id", "TEXT")
    await _add_column_if_not_exists(db, "messages", "agent_id", "TEXT")
    await _add_column_if_not_exists(db, "memory_entries", "agent_id", "TEXT")
    await _add_column_if_not_exists(db, "audit_chain", "agent_id", "TEXT")
    await _add_column_if_not_exists(db, "trust_ledger", "agent_id", "TEXT")

    # User profile + security fields (Sprint 1)
    await _add_column_if_not_exists(db, "users", "full_name", "TEXT")
    await _add_column_if_not_exists(db, "users", "suspended", "INTEGER NOT NULL DEFAULT 0")
    await _add_column_if_not_exists(db, "users", "suspended_at", "TEXT")
    await _add_column_if_not_exists(db, "users", "suspended_by", "TEXT")
    await _add_column_if_not_exists(db, "users", "suspension_reason", "TEXT")
    await _add_column_if_not_exists(db, "users", "last_login_at", "TEXT")
    await _add_column_if_not_exists(db, "users", "last_login_ip", "TEXT")
    await _add_column_if_not_exists(db, "users", "failed_login_count", "INTEGER NOT NULL DEFAULT 0")
    await _add_column_if_not_exists(db, "users", "mfa_locked", "INTEGER NOT NULL DEFAULT 0")
    await _add_column_if_not_exists(db, "users", "mfa_locked_at", "TEXT")

    # Create indexes
    for idx_stmt in _INDEXES:
        await db.execute(idx_stmt)

    # Store schema version in a pragma
    await db.execute(f"PRAGMA user_version={SCHEMA_VERSION.replace('.', '')[:4]}")
