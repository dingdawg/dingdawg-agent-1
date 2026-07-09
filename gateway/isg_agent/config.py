"""Application configuration via Pydantic BaseSettings with YAML config loading.

Environment variables take precedence over YAML values. All settings have
sensible defaults for local development. YAML loading is optional -- the
system works with env vars alone if pyyaml is not installed.

Environment variable prefixes: ISG_AGENT_ or DINGDAWG_
"""

from __future__ import annotations

import functools
import os
import secrets
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

__all__ = [
    "Settings",
    "get_settings",
]

# ---------------------------------------------------------------------------
# YAML config loader (graceful when pyyaml is missing)
# ---------------------------------------------------------------------------

def _load_yaml_config() -> dict[str, Any]:
    """Load configuration from a YAML file if it exists.

    Checks for config file path in this order:
    1. ISG_AGENT_CONFIG_FILE environment variable
    2. ./config/agent.yaml (relative to cwd)
    3. ../config/agent.yaml (relative to gateway/)

    Returns an empty dict if no config file is found or if pyyaml
    is not installed (YAML support is optional).
    """
    try:
        import yaml  # noqa: F811 — optional dependency
    except ImportError:
        return {}

    candidates: list[str] = [
        os.environ.get("ISG_AGENT_CONFIG_FILE", ""),
        str(Path.cwd() / "config" / "agent.yaml"),
        str(Path.cwd().parent / "config" / "agent.yaml"),
    ]

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            with open(candidate, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    return data
    return {}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """ISG Agent 1 gateway configuration.

    Environment variables use the ``ISG_AGENT_`` or ``DINGDAWG_`` prefix and
    take precedence over YAML config values.  Defaults are safe for local
    development.

    Attributes
    ----------
    db_path:
        Filesystem path to the SQLite database file.
    log_level:
        Python-standard logging level name.
    host:
        Network interface to bind to.
    port:
        TCP port for the HTTP / WebSocket server.
    secret_key:
        HMAC key for token signing. Auto-generated if not set.
    max_sessions:
        Maximum number of concurrent agent sessions.
    convergence_max_iterations:
        Hard cap on agent loop iterations.
    convergence_max_tokens:
        Hard cap on total LLM tokens per session.
    time_lock_delays:
        Risk tier -> cooling period (seconds) mapping.
    trust_score_initial:
        Starting trust score for new agents.
    constitution_path:
        Path to the agent constitution YAML file.
    workspace_root:
        Root directory for agent file operations (sandbox boundary).
    enable_remote:
        If False (default), only localhost connections are accepted.
    openai_api_key:
        OpenAI API key for GPT models (from env only).
    anthropic_api_key:
        Anthropic API key for Claude models (from env only).
    """

    # -- Server -----------------------------------------------------------
    host: str = Field(
        default="127.0.0.1",
        description="Host to bind the gateway server to.",
    )
    port: int = Field(
        default=8420,
        ge=1,
        le=65535,
        description="Port for the gateway HTTP/WebSocket server.",
    )
    enable_remote: bool = Field(
        default=False,
        description="If False, only localhost connections are accepted.",
    )

    # -- Security ---------------------------------------------------------
    secret_key: str = Field(
        default="",
        description="Secret key for signing tokens. Auto-generated if empty.",
    )

    # -- Database ---------------------------------------------------------
    db_path: str = Field(
        default="data/agent.db",
        description="Path to the SQLite database file.",
    )

    # -- Logging ----------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )

    # -- Sessions ---------------------------------------------------------
    max_sessions: int = Field(
        default=10,
        ge=1,
        description="Maximum number of concurrent agent sessions.",
    )

    # -- Convergence ------------------------------------------------------
    convergence_max_iterations: int = Field(
        default=100,
        ge=1,
        description="Maximum agent loop iterations per session.",
    )
    convergence_max_tokens: int = Field(
        default=100_000,
        ge=1,
        description="Maximum total LLM tokens per session.",
    )

    # -- Time-Lock --------------------------------------------------------
    time_lock_delays: dict[str, float] = Field(
        default_factory=lambda: {
            "LOW": 0.0,
            "MEDIUM": 0.0,
            "HIGH": 30.0,
            "CRITICAL": 60.0,
        },
        description="Risk tier -> cooling period in seconds.",
    )

    # -- Trust ------------------------------------------------------------
    trust_score_initial: float = Field(
        default=50.0,
        ge=0.0,
        description="Starting trust score for new agents.",
    )

    # -- Constitution -----------------------------------------------------
    constitution_path: str = Field(
        default="config/constitution.yaml",
        description="Path to the agent constitution YAML file.",
    )

    # -- Workspace --------------------------------------------------------
    workspace_root: str = Field(
        default="",
        description="Root directory for agent file operations (sandbox boundary). Defaults to cwd.",
    )

    # -- LLM API keys (env-only, never from YAML) -------------------------
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for GPT models.",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="Default OpenAI model to use (e.g. gpt-4o-mini, gpt-5-mini).",
    )
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key for Claude models.",
    )
    inception_api_key: str = Field(
        default="",
        description="Inception Labs API key for Mercury 2 diffusion model.",
    )
    inception_model: str = Field(
        default="mercury-2",
        description="Default Inception model to use (mercury-2).",
    )
    google_api_key: str = Field(
        default="",
        description="Google AI API key for Gemini multimodal models.",
    )
    google_model: str = Field(
        default="gemini-2.0-flash",
        description="Default Google Gemini model (e.g. gemini-2.0-flash, gemini-2.5-pro).",
    )

    # -- Stripe (env-only, never from YAML) --------------------------------
    stripe_secret_key: str = Field(
        default="",
        description="Stripe secret API key (sk_test_... or sk_live_...).",
    )
    stripe_webhook_secret: str = Field(
        default="",
        description="Stripe webhook endpoint secret for signature verification.",
    )

    # -- Google Calendar OAuth2 (env-only) ----------------------------------
    google_client_id: str = Field(
        default="",
        description="Google OAuth2 client ID for Calendar integration.",
    )
    google_client_secret: str = Field(
        default="",
        description="Google OAuth2 client secret for Calendar integration.",
    )
    google_redirect_uri: str = Field(
        default="",
        description="Google OAuth2 redirect URI (e.g. https://your-domain/api/v1/oauth/google/callback).",
    )

    # -- SendGrid (env-only, never from YAML) ------------------------------
    sendgrid_api_key: str = Field(
        default="",
        description="SendGrid API key for email delivery.",
    )
    sendgrid_from_email: str = Field(
        default="noreply@dingdawg.com",
        description="Default sender email address for SendGrid.",
    )

    # -- Twilio (env-only, never from YAML) --------------------------------
    twilio_account_sid: str = Field(
        default="",
        description="Twilio account SID for SMS delivery.",
    )
    twilio_auth_token: str = Field(
        default="",
        description="Twilio auth token for SMS delivery.",
    )
    twilio_from_number: str = Field(
        default="",
        description="Twilio phone number for outbound SMS (E.164 format).",
    )

    # -- Vapi Voice (env-only, never from YAML) ----------------------------
    vapi_api_key: str = Field(
        default="",
        description="Vapi API key for voice agent integration.",
    )

    # -- Frontend URL (used for email links) --------------------------------
    frontend_url: str = Field(
        default="https://app.dingdawg.com",
        description="Public frontend URL used in email links (password reset, verification).",
    )

    # -- Public API URL (used in all outward-facing URL construction) -------
    public_url: str = Field(
        default="https://api.dingdawg.com",
        description=(
            "Canonical public-facing backend URL. Set to the custom domain "
            "(e.g. https://api.dingdawg.com) so agent cards, MCP discovery "
            "documents, widget configs, and OAuth redirect URIs never expose "
            "the internal Railway hostname. "
            "Env var: ISG_AGENT_PUBLIC_URL"
        ),
    )

    # -- ATR API Key (optional, for receipt endpoint auth) -----------------
    atr_api_key: str = Field(
        default="",
        description=(
            "Optional API key for ATR v1.0 receipt endpoints. "
            "If set, clients must provide X-API-Key header matching this value "
            "to create or read receipts. If empty, endpoints remain public. "
            "Env var: ISG_AGENT_ATR_API_KEY"
        ),
    )

    # -- Deployment environment -------------------------------------------
    deployment_env: str = Field(
        default="development",
        description=(
            "Deployment environment identifier. "
            "Accepted values: development, staging, production. "
            "Controls error detail exposure and strict security gates."
        ),
    )

    # -- CORS allowed origins ---------------------------------------------
    allowed_origins: str = Field(
        default="http://localhost:3002",
        description=(
            "Comma-separated list of allowed CORS origins. "
            "Example: 'http://localhost:3002,https://app.dingdawg.com'. "
            "Use the parsed property ``allowed_origins_list`` for list access."
        ),
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        """Return ``allowed_origins`` as a list of stripped origin strings.

        Parses the comma-separated ``allowed_origins`` field and returns each
        non-empty origin as a separate list element.

        Example
        -------
        >>> s = Settings(allowed_origins="http://localhost:3002, https://app.example.com")
        >>> s.allowed_origins_list
        ['http://localhost:3002', 'https://app.example.com']
        """
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # -- Pydantic-settings configuration ----------------------------------
    model_config = {
        "env_prefix": "ISG_AGENT_",
        "env_nested_delimiter": "__",
        "populate_by_name": True,
        "extra": "ignore",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    # -- Validators -------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        """Normalise log level to uppercase."""
        normalised = v.upper().strip()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalised not in valid_levels:
            raise ValueError(
                f"Invalid log_level {v!r}; must be one of {sorted(valid_levels)}"
            )
        return normalised

    @field_validator("secret_key")
    @classmethod
    def _ensure_secret_key(cls, v: str) -> str:
        """Generate a secure random key if none is provided; reject weak keys in production.

        When running with multiple uvicorn workers, each worker forks its own
        process and gets its own ``lru_cache`` — so a purely random fallback
        would give every worker a *different* key, breaking JWT verification.

        Fix: persist the generated key to ``data/.secret_key`` so all workers
        converge on the same value.  The file is created with mode 0o600.

        Production hardening
        --------------------
        In production (``ISG_AGENT_DEPLOYMENT_ENV=production``) a key is
        considered weak if it:

        - is the literal placeholder ``"CHANGE-ME-IN-PRODUCTION"``
        - is shorter than 32 characters
        - starts with ``"local-"`` (a common dev-time prefix)

        Weak keys in production raise :class:`ValueError` so the process
        refuses to start with an insecure configuration.  Development and
        staging environments log a warning but continue.
        """
        import logging as _logging
        _cfg_log = _logging.getLogger(__name__)

        # Determine deployment environment without triggering full Settings
        # validation (we're inside a field validator).
        deploy_env = (
            os.environ.get("ISG_AGENT_DEPLOYMENT_ENV", "")
            or os.environ.get("DINGDAWG_DEPLOYMENT_ENV", "")
            or "development"
        ).lower().strip()
        is_production = deploy_env == "production"

        # Keys that are always invalid
        _KNOWN_PLACEHOLDERS = {"CHANGE-ME-IN-PRODUCTION", ""}

        def _is_weak(key: str) -> bool:
            return (
                key in _KNOWN_PLACEHOLDERS
                or len(key) < 32
                or key.startswith("local-")
            )

        if v and v not in _KNOWN_PLACEHOLDERS:
            # A key was explicitly supplied — validate entropy in production.
            if is_production and _is_weak(v):
                raise ValueError(
                    "secret_key is too weak for production: must be at least 32 "
                    "characters and must not start with 'local-'. "
                    "Set ISG_AGENT_SECRET_KEY to a high-entropy random string "
                    "(e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`)."
                )
            if not is_production and _is_weak(v):
                _cfg_log.warning(
                    "config: secret_key looks weak (len=%d, starts_with_local=%s). "
                    "This would be rejected in production.",
                    len(v),
                    v.startswith("local-"),
                )
            return v

        # No key supplied (empty or placeholder) — auto-generate and persist.
        secret_file = Path("data/.secret_key")
        if secret_file.exists():
            stored = secret_file.read_text().strip()
            if stored:
                if is_production and _is_weak(stored):
                    raise ValueError(
                        "Persisted secret_key in data/.secret_key is too weak for "
                        "production. Delete the file and set ISG_AGENT_SECRET_KEY "
                        "to a high-entropy random string."
                    )
                return stored

        # Generate, persist, and return a strong random key.
        generated = secrets.token_hex(32)
        try:
            secret_file.parent.mkdir(parents=True, exist_ok=True)
            secret_file.write_text(generated)
            secret_file.chmod(0o600)
        except OSError:
            pass  # non-fatal — single-worker mode still works
        return generated

    @field_validator("workspace_root")
    @classmethod
    def _default_workspace_root(cls, v: str) -> str:
        """Default to the current working directory if empty."""
        if not v:
            return str(Path.cwd())
        return str(Path(v).resolve())


# ---------------------------------------------------------------------------
# Bare-name fallback mapping
# ---------------------------------------------------------------------------
# Users sometimes set env vars without the ISG_AGENT_ prefix (e.g.
# STRIPE_SECRET_KEY instead of ISG_AGENT_STRIPE_SECRET_KEY).  These are
# silently ignored by pydantic-settings because env_prefix="ISG_AGENT_"
# controls which env vars are read.
#
# Railway's dashboard makes this worse: it shows bare names as "green"
# (set) even though the app ignores them.  The map below provides a
# fallback — if the prefixed name is empty, we check the bare name.
#
# Keys are Settings field names; values are bare env var names to fall
# back to.  A startup warning is emitted for every bare-name fallback
# that triggers, so operators know to fix their Railway dashboard.
_BARE_VAR_FALLBACKS: dict[str, str] = {
    "stripe_secret_key": "STRIPE_SECRET_KEY",
    "stripe_webhook_secret": "STRIPE_WEBHOOK_SECRET",
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "google_api_key": "GOOGLE_API_KEY",
    "inception_api_key": "INCEPTION_API_KEY",
    "sendgrid_api_key": "SENDGRID_API_KEY",
    "sendgrid_from_email": "SENDGRID_FROM_EMAIL",
    "twilio_account_sid": "TWILIO_ACCOUNT_SID",
    "twilio_auth_token": "TWILIO_AUTH_TOKEN",
    "twilio_from_number": "TWILIO_FROM_NUMBER",
    "vapi_api_key": "VAPI_API_KEY",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "google_redirect_uri": "GOOGLE_REDIRECT_URI",
    "secret_key": "SECRET_KEY",
    "db_path": "DATABASE_URL",
    "atr_api_key": "ATR_API_KEY",
}


def _warn_bare_env_vars() -> None:
    """Log a warning for every bare env var that exists but is ignored.

    A bare env var is one that IS set in the environment without the
    ``ISG_AGENT_`` prefix.  pydantic-settings ignores these.  We detect
    them here so operators can fix their Railway / hosting dashboard.

    Also logs a warning if a bare name AND the prefixed name are both set,
    since the prefixed value takes precedence (which may be unexpected).
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    prefix = "ISG_AGENT_"
    for settings_key, bare_var in _BARE_VAR_FALLBACKS.items():
        prefixed_var = f"{prefix}{settings_key.upper()}"
        bare_value = os.environ.get(bare_var, "")
        prefixed_value = os.environ.get(prefixed_var, "")

        if bare_value and not prefixed_value:
            _log.warning(
                "ENV_PREFIX: %s is set (%d chars) but pydantic-settings "
                "requires %s (env_prefix='ISG_AGENT_'). "
                "Railway dashboard MUST show %s, not bare %s. "
                "Bare names appear green in the dashboard but are "
                "silently ignored by pydantic-settings.",
                bare_var,
                len(bare_value),
                prefixed_var,
                prefixed_var,
                bare_var,
            )

        if prefixed_value and bare_value:
            _log.debug(
                "ENV_PREFIX: both %s and %s are set — %s takes precedence.",
                prefixed_var,
                bare_var,
                prefixed_var,
            )


def _env_var_diagnostics() -> dict[str, Any]:
    """Return diagnostic info about env var prefix mapping.

    Returns a dict with two keys:
    - ``prefixed_set``: list of ISG_AGENT_ prefixed env vars that are set
    - ``bare_ignored``: list of bare env vars that exist but are NOT being
      read by pydantic-settings (because the ISG_AGENT_ prefixed equivalent
      IS NOT set — so we fall back)
    - ``bare_fallback_active``: list of bare env vars that ARE being used
      as fallbacks (because the ISG_AGENT_ prefixed equivalent is not set)
    - ``mapped``: dict of settings field name → final value source

    This is safe to call at any time (no side effects) and is wired into
    the system health endpoint for remote verification.
    """
    prefix = "ISG_AGENT_"
    prefixed_set: list[str] = []
    bare_ignored: list[str] = []
    bare_fallback_active: list[str] = []
    mapped: dict[str, str] = {}

    for settings_key, bare_var in _BARE_VAR_FALLBACKS.items():
        prefixed_var = f"{prefix}{settings_key.upper()}"
        bare_value = os.environ.get(bare_var, "")
        prefixed_value = os.environ.get(prefixed_var, "")

        if prefixed_value:
            prefixed_set.append(prefixed_var)
            mapped[settings_key] = prefixed_var
        elif bare_value:
            bare_fallback_active.append(bare_var)
            mapped[settings_key] = f"{bare_var} (FALLBACK — rename to {prefixed_var})"
        else:
            mapped[settings_key] = "(not set)"

    # Detect bare env vars that exist but are silently ignored by pydantic-settings.
    #
    # A bare var is "ignored" when:
    #   a) It is one of the env vars we explicitly track in _BARE_VAR_FALLBACKS, AND
    #   b) The ISG_AGENT_ prefixed equivalent is NOT set (so the bare name would be
    #      needed but pydantic-settings won't read it), AND
    #   c) It is NOT already in bare_fallback_active (meaning it IS empty/unset).
    #
    # This catches the dangerous case where an operator set the bare name in
    # Railway dashboard but left the prefixed name empty.  The bare name shows
    # green in the Railway UI but pydantic-settings silently ignores it.
    #
    # Also catch bare vars that exist but have NO mapping in _BARE_VAR_FALLBACKS
    # at all — these are also silently ignored and may indicate environment drift.
    _fallback_values = {v.upper() for v in _BARE_VAR_FALLBACKS.values()}
    for bare_var, bare_value in sorted(os.environ.items()):
        bare_upper = bare_var.upper().strip()
        if not bare_value:
            continue

        # Determine the ISG_AGENT_ prefixed equivalent for this bare var.
        prefixed_candidate = f"{prefix}{bare_upper}"
        prefixed_value = os.environ.get(prefixed_candidate, "")

        if bare_upper in _fallback_values:
            # This bare var has a known fallback mapping.
            # It should be in bare_fallback_active if it was used as a fallback.
            # It's "ignored" if the prefixed version is ALSO set (because prefixed
            # takes precedence, making the bare name redundant but confusing).
            if prefixed_value and bare_value:
                bare_ignored.append(bare_var)
        else:
            # This bare var has NO mapping in _BARE_VAR_FALLBACKS.
            # It is silently ignored by pydantic-settings regardless.
            # If no prefixed equivalent exists either, note it as ignored.
            if not prefixed_value:
                bare_ignored.append(bare_var)

    return {
        "prefixed_set": sorted(prefixed_set),
        "bare_ignored": sorted(bare_ignored),
        "bare_fallback_active": sorted(bare_fallback_active),
        "mapped": dict(sorted(mapped.items())),
    }


# ---------------------------------------------------------------------------
# Cached singleton accessor
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Create a Settings instance, merging YAML config with environment variables.

    The result is cached so subsequent calls return the same instance.
    Environment variables always take precedence over YAML values.

    The cache can be cleared for testing via ``get_settings.cache_clear()``.
    """
    yaml_data = _load_yaml_config()

    # Also check for DINGDAWG_ prefixed env vars and translate them
    env_overrides: dict[str, str] = {}
    dingdawg_prefix = "DINGDAWG_"
    for key, value in os.environ.items():
        if key.startswith(dingdawg_prefix):
            settings_key = key[len(dingdawg_prefix):].lower()
            env_overrides[settings_key] = value

    # ---- Bare-name fallback: if a prefixed var is not set but a bare -----
    # env var exists, inject it as an override so settings still work.
    # This is a safety net for operators who set STRIPE_SECRET_KEY (bare)
    # instead of ISG_AGENT_STRIPE_SECRET_KEY (prefixed) in their Railway
    # dashboard.  We also warn so they can fix the naming.
    isg_prefix = "ISG_AGENT_"
    for settings_key, bare_var in _BARE_VAR_FALLBACKS.items():
        prefixed_var = f"{isg_prefix}{settings_key.upper()}"
        bare_value = os.environ.get(bare_var, "")
        prefixed_value = os.environ.get(prefixed_var, "")

        if bare_value and not prefixed_value:
            # Bare name exists but prefixed doesn't — use bare as fallback.
            # This ensures the app works even when Railway dashboard has the
            # wrong (bare) name.  A warning is logged so operators fix it.
            env_overrides[settings_key] = bare_value

    # Warn about bare-name mismatches (log-level: WARNING).
    _warn_bare_env_vars()

    # Merge: yaml_data is the base, env_overrides layer on top.
    # Pydantic-settings handles ISG_AGENT_ prefixed env vars automatically.
    # For DINGDAWG_ prefixed vars and bare-name fallbacks, we inject them
    # as initial data.
    init_data: dict[str, Any] = {}
    init_data.update(yaml_data)
    init_data.update(env_overrides)

    return Settings(**init_data)
