"""FastAPI application factory for ISG Agent 1 gateway.

Creates and configures the FastAPI application with lifespan management,
middleware registration, and route mounting.  Initialises the AgentRuntime
with governance, audit, convergence, memory, session, and model components.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
from fastapi import FastAPI

from isg_agent import __app_name__, __version__
from isg_agent.config import get_settings

# -- Sentry error tracking ---------------------------------------------------
if sentry_sdk is not None:
    sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN", ""), traces_sample_rate=0.1)

# -- Structured JSON logging -------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON with request_id when available."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    else:
        for h in root.handlers:
            h.setFormatter(_JsonFormatter())
    log_level = os.environ.get("ISG_AGENT_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, log_level, logging.INFO))


_configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    On startup: initialises settings, database, audit chain, governance gate,
    convergence guard, memory store, session manager, model registry, and
    wires them all into the AgentRuntime stored on ``app.state``.

    On shutdown: closes database connections and releases resources.
    """
    settings = get_settings()
    app.state.settings = settings

    # -- Import components (deferred to avoid circular imports) ---------------
    from isg_agent.api.routes.auth import _set_auth_config
    from isg_agent.brain.agent import AgentRuntime
    from isg_agent.brain.session import SessionManager
    from isg_agent.core.audit import AuditChain
    from isg_agent.core.capability_bridge import CapabilityBridge
    from isg_agent.core.convergence import ConvergenceGuard, ResourceBudget
    from isg_agent.core.governance import GovernanceGate
    from isg_agent.memory.store import MemoryStore
    from isg_agent.models.registry import ModelRegistry

    # -- Database path -------------------------------------------------------
    db_path = settings.db_path

    # -- Audit chain ---------------------------------------------------------
    audit_chain = AuditChain(db_path=db_path)

    # -- Capability Bridge (MiLA distiller integration) ----------------------
    # Created early so it can be wired into the skill executor hook chain
    # alongside _usage_hook below.  Fail-open: if MiLA distiller is absent
    # the bridge silently becomes a no-op and Agent 1 continues normally.
    capability_bridge = CapabilityBridge()
    app.state.capability_bridge = capability_bridge

    # -- Governance gate -----------------------------------------------------
    governance_gate = GovernanceGate(audit_chain=audit_chain)

    # -- Convergence guard ---------------------------------------------------
    # max_duration_seconds=86400 (24h) because the guard is shared across
    # the entire server lifetime, not per-request.  The default 300s would
    # cause every response to report BUDGET_EXCEEDED after 5 min of uptime.
    budget = ResourceBudget(
        max_iterations=settings.convergence_max_iterations,
        max_tokens=settings.convergence_max_tokens,
        max_duration_seconds=86400.0,
    )
    convergence_guard = ConvergenceGuard(budget=budget, audit_chain=audit_chain)
    convergence_guard.start()

    # -- Memory store --------------------------------------------------------
    memory_store = MemoryStore(db_path=db_path)

    # -- Session manager -----------------------------------------------------
    session_manager = SessionManager(db_path=db_path)
    await session_manager.init()  # Eagerly create agent_sessions table

    # -- Model registry (providers registered if API keys are set) -----------
    registry = ModelRegistry()

    if settings.openai_api_key:
        from isg_agent.models.openai_provider import OpenAIProvider
        oai = OpenAIProvider(
            api_key=settings.openai_api_key,
            default_model=settings.openai_model,
        )
        registry.register("openai", oai)
        logger.info("OpenAI provider registered (model=%s)", settings.openai_model)

    if settings.anthropic_api_key:
        from isg_agent.models.anthropic_provider import AnthropicProvider
        anth = AnthropicProvider(api_key=settings.anthropic_api_key)
        registry.register("anthropic", anth)
        logger.info("Anthropic provider registered")

    if settings.inception_api_key:
        from isg_agent.models.mercury_provider import MercuryProvider
        mercury = MercuryProvider(
            api_key=settings.inception_api_key,
            default_model=settings.inception_model,
        )
        registry.register("mercury", mercury)
        logger.info("Mercury provider registered (model=%s)", settings.inception_model)

    if settings.google_api_key:
        from isg_agent.models.google_provider import GoogleProvider
        google = GoogleProvider(
            api_key=settings.google_api_key,
            default_model=settings.google_model,
        )
        registry.register("google", google)
        logger.info("Google provider registered (model=%s)", settings.google_model)

    # Set fallback chain from registered providers
    providers = registry.list_providers()
    if providers:
        registry.set_fallback_chain(providers)
        logger.info("LLM fallback chain: %s", providers)

    # -- IntelligentRouter (fail-open: skip if providers missing or import fails) --
    intelligent_router = None
    try:
        from isg_agent.models.router import IntelligentRouter as AgentRouter

        _speed_provider = registry._providers.get("mercury")
        _creative_provider = registry._providers.get("openai")
        _reasoning_provider = registry._providers.get("anthropic")

        if _speed_provider and _creative_provider and _reasoning_provider:
            intelligent_router = AgentRouter(
                speed_provider=_speed_provider,
                creative_provider=_creative_provider,
                reasoning_provider=_reasoning_provider,
            )
            logger.info(
                "IntelligentRouter activated (speed=mercury, creative=openai, reasoning=anthropic)"
            )
        else:
            _missing = [
                name for name, prov in [
                    ("mercury", _speed_provider),
                    ("openai", _creative_provider),
                    ("anthropic", _reasoning_provider),
                ]
                if not prov
            ]
            logger.warning(
                "IntelligentRouter NOT activated — missing providers: %s. "
                "Falling back to ModelRegistry.",
                _missing,
            )
    except Exception as _router_init_exc:
        logger.warning(
            "IntelligentRouter init failed (fail-open): %s — "
            "using ModelRegistry fallback",
            _router_init_exc,
        )

    # -- Skill execution pipeline ---------------------------------------------
    from isg_agent.skills.executor import SkillExecutor
    from isg_agent.skills.reputation import SkillReputation
    from isg_agent.skills.quarantine import QuarantineManager

    skill_executor = SkillExecutor(
        workspace_root=str(settings.db_path).rsplit("/", 1)[0] if "/" in str(settings.db_path) else ".",
        audit_chain=audit_chain,
    )
    skill_reputation = SkillReputation()
    quarantine_manager = QuarantineManager()

    app.state.skill_executor = skill_executor
    app.state.skill_reputation = skill_reputation
    app.state.quarantine_manager = quarantine_manager
    app.state.governance_gate = governance_gate
    logger.info("Skill execution pipeline initialised")

    # -- Explain engine ------------------------------------------------------
    from isg_agent.core.explain import ExplainEngine

    explain_engine = ExplainEngine(max_traces=1000)
    app.state.explain_engine = explain_engine

    # -- Agent runtime -------------------------------------------------------
    runtime = AgentRuntime(
        model_registry=registry,
        governance_gate=governance_gate,
        convergence_guard=convergence_guard,
        audit_chain=audit_chain,
        memory_store=memory_store,
        session_manager=session_manager,
        skill_executor=skill_executor,
        explain_engine=explain_engine,
        intelligent_router=intelligent_router,
    )

    app.state.runtime = runtime
    app.state.audit_chain = audit_chain
    app.state.memory_store = memory_store
    app.state.session_manager = session_manager

    # -- Trust ledger --------------------------------------------------------
    from isg_agent.core.trust_ledger import TrustLedger

    trust_ledger = TrustLedger(
        autonomous_threshold=settings.trust_score_initial / 100.0,
    )
    app.state.trust_ledger = trust_ledger

    # -- Stripe payment (OPTIONAL — works without keys) ----------------------
    stripe_client = None
    if settings.stripe_secret_key:
        from isg_agent.payments.stripe_client import StripeClient

        stripe_client = StripeClient(
            api_key=settings.stripe_secret_key,
            webhook_secret=settings.stripe_webhook_secret,
        )
        logger.info("Stripe payment client initialised")

    from isg_agent.payments.middleware import PaymentGate

    payment_gate = PaymentGate(stripe_client=stripe_client)
    app.state.stripe_client = stripe_client
    app.state.payment_gate = payment_gate

    # -- Usage metering ($1/action, 50 free/month) ----------------------------
    from isg_agent.payments.usage_meter import UsageMeter

    usage_meter = UsageMeter(
        db_path=db_path,
        stripe_client=stripe_client,
        price_per_action=1.00,
        free_tier_limit=50,
    )
    await usage_meter.init_tables()
    app.state.usage_meter = usage_meter

    # Wire usage metering + financial ledger into skill executor
    from isg_agent.core.flywheel_emitter import FlywheelEmitter as _FlywheelEmitter

    _flywheel_emitter = _FlywheelEmitter()

    async def _usage_hook(skill_name: str, parameters: dict, result: object) -> None:
        agent_id = parameters.get("agent_id", "default")
        user_id = parameters.get("user_id", "system")
        await usage_meter.record_usage(
            agent_id=agent_id,
            user_id=user_id,
            skill_name=skill_name,
            action=parameters.get("action", ""),
        )
        # Best-effort: record in financial ledger (non-blocking, never raises)
        _fin_ledger = getattr(app.state, "ledger", None)
        if _fin_ledger is not None:
            try:
                await _fin_ledger.record_action(
                    agent_id=agent_id,
                    user_id=user_id,
                    action_name=skill_name,
                    sector=parameters.get("sector"),
                    industry=parameters.get("industry"),
                    subscription_tier=parameters.get("subscription_tier"),
                )
            except Exception as _exc:
                logger.warning(
                    "Financial ledger record_action failed (non-blocking): %s", _exc
                )

        # Fire-and-forget: emit flywheel telemetry — NEVER blocks or fails the executor.
        # result.success is always True here (SkillExecutor gates this hook behind success).
        try:
            _duration_ms = getattr(result, "duration_ms", 0)
            asyncio.ensure_future(
                _flywheel_emitter.emit_skill_execution(
                    agent_id=agent_id,
                    skill_name=skill_name,
                    industry=parameters.get("industry", "unknown"),
                    success=True,
                    execution_time_ms=_duration_ms,
                )
            )
        except Exception as _fw_exc:
            logger.warning(
                "FlywheelEmitter.ensure_future failed (non-blocking): %s", _fw_exc
            )

    skill_executor.add_post_execute_hook(_usage_hook)
    skill_executor.add_post_execute_hook(capability_bridge.post_execute_hook)

    # Wire trust ledger into skill execution hook chain — records per-skill
    # and per-agent trust scores on every execution for autonomous gating.
    from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

    _trust_hook = make_trust_ledger_hook(trust_ledger)
    skill_executor.add_post_execute_hook(_trust_hook)
    logger.info("Trust ledger wired into skill executor hook chain")

    logger.info("Usage metering: $%.2f/action, %d free/month", 1.00, 50)

    # -- DID identity system (fail-open: if secret missing, DID is disabled) -----
    from isg_agent.identity.did_manager import DIDManager

    _did_secret = settings.secret_key  # reuse the platform secret key
    did_manager: Optional[DIDManager] = None
    try:
        did_manager = DIDManager(db_path=str(db_path), platform_secret=_did_secret)
        app.state.did_manager = did_manager
        logger.info("DID identity system initialised (db=%s)", db_path)

        # -- Seed platform root DID (idempotent — already-exists is expected) --
        try:
            did_manager.seed_platform_did()
            logger.info("Platform root DID seeded successfully")
        except ValueError as _did_seed_val_err:
            # "already exists" is the expected case on every restart after first boot
            _msg = str(_did_seed_val_err)
            if "already exists" in _msg:
                logger.debug("Platform root DID already present — skipping seed")
            else:
                logger.warning("Platform root DID seed ValueError (fail-open): %s", _did_seed_val_err)
        except Exception as _did_seed_err:
            logger.warning(
                "Platform root DID seeding failed (fail-open): %s", _did_seed_err
            )
    except Exception as _did_init_err:
        logger.warning(
            "DID identity system failed to initialise (fail-open): %s", _did_init_err
        )
        app.state.did_manager = None

    # -- Agent registry (agent CRUD) -----------------------------------------
    from isg_agent.agents.agent_registry import AgentRegistry
    from isg_agent.agents.handle_service import HandleService
    from isg_agent.templates.template_registry import TemplateRegistry
    from isg_agent.templates.marketplace_registry import MarketplaceRegistry

    from isg_agent.agents.brand_verification import BrandVerificationService

    agent_registry = AgentRegistry(db_path=db_path)
    handle_service = HandleService(db_path=db_path)
    template_registry = TemplateRegistry(db_path=db_path)
    marketplace_registry = MarketplaceRegistry(db_path=db_path)
    brand_verification_service = BrandVerificationService(db_path=str(db_path))

    # Seed the 36 default templates on every startup (idempotent) — 28 original + 8 gaming
    await template_registry.seed_defaults()

    # Seed the Mario's Italian Kitchen demo agent (idempotent — skips if already present)
    try:
        from isg_agent.scripts.seed_demo_agent import seed as _seed_demo, _load_template_json as _load_demo_tpl
        _demo_tpl = _load_demo_tpl()
        await _seed_demo(str(db_path), _demo_tpl, dry_run=False, force=False)
        logger.info("Demo agent @marios-italian seeded (or already present)")
    except Exception as _demo_seed_err:
        logger.warning("Demo agent seed failed (fail-open): %s", _demo_seed_err)

    app.state.agent_registry = agent_registry
    app.state.handle_service = handle_service
    app.state.template_registry = template_registry
    app.state.marketplace_registry = marketplace_registry
    app.state.brand_verification_service = brand_verification_service

    # Wire registries into AgentRuntime for personalized agent preambles
    runtime._agent_registry = agent_registry
    runtime._template_registry = template_registry
    logger.info(
        "Agent registry, handle service, template registry, and marketplace registry initialised"
    )

    # -- DD Main integration bridge -------------------------------------------
    from isg_agent.integrations.ddmain_bridge import DDMainBridge

    ddmain_bridge = DDMainBridge(
        agent_registry=agent_registry,
        handle_service=handle_service,
        template_registry=template_registry,
        db_path=str(db_path),
    )
    app.state.ddmain_bridge = ddmain_bridge
    logger.info("DD Main integration bridge initialised")

    # -- Inter-agent communications -------------------------------------------
    from isg_agent.comms.agent_protocol import AgentProtocol
    from isg_agent.comms.transaction import TransactionManager

    agent_protocol = AgentProtocol(db_path=db_path)
    transaction_manager = TransactionManager(db_path=db_path)

    app.state.agent_protocol = agent_protocol
    app.state.transaction_manager = transaction_manager
    logger.info("Agent protocol and transaction manager initialised")

    # -- Personal agent features (task management + life services) -----------
    from isg_agent.personal.task_manager import TaskManager
    from isg_agent.personal.life_services import LifeServices

    task_manager = TaskManager(db_path=db_path)
    life_services = LifeServices(db_path=db_path)

    app.state.task_manager = task_manager
    app.state.life_services = life_services
    logger.info("Task manager and life services initialised")

    # -- Heartbeat scheduler --------------------------------------------------
    from isg_agent.brain.heartbeat import HeartbeatScheduler

    heartbeat = HeartbeatScheduler(audit_chain=audit_chain)
    app.state.heartbeat = heartbeat
    heartbeat.register(
        name="capability_health_check",
        callback=capability_bridge.health_check_task,
        interval_seconds=300.0,  # every 5 minutes
        timeout_seconds=15.0,
    )

    # Register trust_ledger_decay: periodic decay toward neutral for inactive entities
    from isg_agent.hooks.heartbeat_tasks import (
        make_trust_ledger_decay_task,
        make_stale_session_cleanup_task,
    )

    heartbeat.register(
        name="trust_ledger_decay",
        callback=make_trust_ledger_decay_task(trust_ledger),
        interval_seconds=3600.0,  # every 1 hour
        timeout_seconds=30.0,
    )

    # Register stale_session_cleanup: close sessions inactive >24h
    heartbeat.register(
        name="stale_session_cleanup",
        callback=make_stale_session_cleanup_task(session_manager, max_age_hours=24),
        interval_seconds=1800.0,  # every 30 minutes
        timeout_seconds=30.0,
    )

    await heartbeat.start()
    logger.info(
        "Heartbeat scheduler started with %d tasks: %s",
        len(heartbeat.task_names),
        heartbeat.task_names,
    )

    # -- Email + SMS delivery connectors ----------------------------------------
    from isg_agent.integrations.email_sendgrid import SendGridConnector
    from isg_agent.integrations.sms_twilio import TwilioConnector
    from isg_agent.integrations.notification_worker import NotificationWorker

    sendgrid = SendGridConnector(
        db_path=db_path,
        default_api_key=settings.sendgrid_api_key,
        default_from_email=settings.sendgrid_from_email,
    )
    await sendgrid.init_tables()

    twilio = TwilioConnector(
        db_path=db_path,
        default_account_sid=settings.twilio_account_sid,
        default_auth_token=settings.twilio_auth_token,
        default_from_number=settings.twilio_from_number,
    )
    await twilio.init_tables()

    notification_worker = NotificationWorker(
        db_path=db_path,
        sendgrid=sendgrid if settings.sendgrid_api_key else None,
        twilio=twilio if settings.twilio_account_sid else None,
    )
    await notification_worker.start()

    app.state.sendgrid = sendgrid
    app.state.twilio = twilio
    app.state.notification_worker = notification_worker
    logger.info(
        "Notification delivery: email=%s sms=%s",
        "enabled" if settings.sendgrid_api_key else "disabled",
        "enabled" if settings.twilio_account_sid else "disabled",
    )

    # -- Google Calendar connector ---------------------------------------------
    from isg_agent.integrations.google_calendar import GoogleCalendarConnector

    google_calendar = GoogleCalendarConnector(db_path=db_path)
    await google_calendar.init_tables()
    app.state.google_calendar = google_calendar
    logger.info("Google Calendar connector initialised")

    # -- Register built-in universal skills (business + gaming) ----------------
    # Registered here (after google_calendar) so the appointments skill
    # can be wired to the Google Calendar connector at startup.
    # Gaming skills (match_tracker, tournament, game_session, loot_tracker)
    # are registered in the same call via the unified _SKILL_REGISTRY.
    from isg_agent.skills.builtin import register_builtin_skills

    registered_skills = await register_builtin_skills(
        skill_executor, db_path, google_calendar=google_calendar
    )
    logger.info("Built-in skills registered: %s", registered_skills)

    # -- Voice integration (Vapi) -----------------------------------------------
    from isg_agent.integrations.voice_vapi import VapiConnector

    vapi = VapiConnector(db_path=db_path, api_key=settings.vapi_api_key)
    await vapi.init_tables()
    app.state.vapi = vapi
    logger.info(
        "Voice integration: %s",
        "enabled" if settings.vapi_api_key else "disabled (no API key)",
    )

    # -- Configure auth module -----------------------------------------------
    _set_auth_config(db_path=db_path, secret_key=settings.secret_key)

    # -- Initialise MFA schema (backup codes, device trusts, phone columns) ---
    from isg_agent.api.routes.auth_mfa import _ensure_mfa_schema as _init_mfa_schema
    try:
        await _init_mfa_schema(str(db_path))
        logger.info("MFA schema initialised")
    except Exception as _mfa_schema_err:
        logger.warning("MFA schema init failed (fail-open): %s", _mfa_schema_err)

    # -- Configure social OAuth module (Google + Apple Sign-In) ---------------
    from isg_agent.api.routes.auth_social import _set_social_auth_config
    _set_social_auth_config(
        db_path=str(db_path),
        secret_key=settings.secret_key,
        frontend_url=settings.frontend_url,
    )

    # -- Configure passkey auth module ----------------------------------------
    from isg_agent.api.routes.auth_passkey import _set_passkey_config
    _set_passkey_config(db_path=str(db_path), secret_key=settings.secret_key)

    # -- Configure auth_extended module (password reset + email verification) --
    from isg_agent.api.routes.auth_extended import _set_auth_extended_config
    _set_auth_extended_config(
        db_path=str(db_path),
        frontend_url=settings.frontend_url,
    )

    # -- Configure CLI invoke module (API key + device code auth) -----------
    from isg_agent.api.routes.cli_invoke import _set_cli_config
    _set_cli_config(
        db_path=str(db_path),
        secret_key=settings.secret_key,
        frontend_url=settings.frontend_url,
    )

    # -- Configure OAuth server module (Zapier OAuth flow) ------------------
    from isg_agent.api.routes.oauth_server import _set_oauth_server_config
    _set_oauth_server_config(db_path=str(db_path), secret_key=settings.secret_key)

    # -- Initialise email verification tables (adds email_verified column) ----
    from isg_agent.auth.email_verification import EmailVerificationManager
    _email_verification_manager = EmailVerificationManager(db_path=str(db_path))
    await _email_verification_manager.init_tables()
    app.state.email_verification_manager = _email_verification_manager

    # -- Initialise password reset tables ------------------------------------
    from isg_agent.auth.password_reset import PasswordResetManager
    _password_reset_manager = PasswordResetManager(db_path=str(db_path))
    await _password_reset_manager.init_tables()
    app.state.password_reset_manager = _password_reset_manager

    # -- Analytics tables -------------------------------------------------------
    from isg_agent.api.routes.analytics import init_analytics_tables
    await init_analytics_tables(db_path)

    # -- Financial ledger -------------------------------------------------------
    from isg_agent.finance.ledger import FinancialLedger

    ledger = FinancialLedger(db_path=str(db_path))
    await ledger.init_tables()
    app.state.ledger = ledger

    # Seed default cost rates (idempotent — upserts on each startup)
    await ledger.update_cost_rate(
        "openai_api", 10, "per_1k_tokens",
        "GPT-4o-mini API cost estimate per action",
    )
    await ledger.update_cost_rate(
        "stripe_percentage", 290, "per_10k_basis",
        "Stripe 2.9% processing fee",
    )
    await ledger.update_cost_rate(
        "stripe_fixed", 30, "per_transaction",
        "Stripe $0.30 fixed fee per charge",
    )
    await ledger.update_cost_rate(
        "hosting", 2000, "per_month",
        "Railway hosting ~$20/month",
    )
    await ledger.update_cost_rate(
        "browser_tts", 0, "per_request",
        "Browser Web Speech API (free)",
    )
    await ledger.update_cost_rate(
        "kokoro_tts", 1, "per_request",
        "Kokoro cached TTS ~$0.01/request",
    )
    await ledger.update_cost_rate(
        "elevenlabs_tts", 5, "per_request",
        "ElevenLabs ~$0.05/request",
    )
    await ledger.update_cost_rate(
        "vapi_telephony", 10, "per_minute",
        "Vapi telephony ~$0.10/minute",
    )
    logger.info("Financial ledger initialised with default cost rates")

    logger.info(
        "ISG Agent 1 gateway started — version=%s db=%s providers=%s stripe=%s skills=%s",
        __version__,
        db_path,
        providers,
        "enabled" if stripe_client else "disabled",
        "enabled",
    )

    # -- MCP server: wire app state (fail-open) --------------------------------
    try:
        from isg_agent.mcp.server import wire_app_state
        wire_app_state(app.state)
        logger.info("MCP server wired to app state")
    except Exception as e:
        logger.warning(f"MCP server not available: {e}")

    yield

    # -- Shutdown: release resources -----------------------------------------
    await notification_worker.stop()
    await heartbeat.stop()
    await memory_store.close()
    await session_manager.close()
    await agent_registry.close()
    await handle_service.close()
    await template_registry.close()
    await marketplace_registry.close()
    await brand_verification_service.close()
    await agent_protocol.close()
    await transaction_manager.close()
    await task_manager.close()
    await life_services.close()
    await ddmain_bridge.close()
    logger.info("ISG Agent 1 gateway shut down")


_is_production = os.environ.get("ISG_AGENT_DEPLOYMENT_ENV", "").lower() == "production"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance with health endpoint, middleware,
        and all route modules registered.
    """
    app = FastAPI(
        title=__app_name__,
        description="Security-hardened, governance-first autonomous AI agent platform",
        version=__version__,
        docs_url=None if _is_production else "/docs",
        redoc_url=None if _is_production else "/redoc",
        openapi_url=None if _is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # -- STOA Layer 1: Error sanitization (register first — exception handlers) --
    from isg_agent.middleware.error_sanitizer import register_error_handlers

    register_error_handlers(app)

    # -- CORS (must be outermost middleware for preflight requests) -----------
    from starlette.middleware.cors import CORSMiddleware
    from isg_agent.middleware.widget_cors import WidgetCORSMiddleware

    _settings = get_settings()
    _origins = _settings.allowed_origins_list

    # Production allowlist — never use wildcard for authenticated endpoints.
    # Widget endpoints (/api/v1/widget/*) allow any origin via WidgetCORSMiddleware.
    _PRODUCTION_ORIGINS = [
        "https://app.dingdawg.com",
        "https://dingdawg.com",
    ]
    _DEV_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3002",
    ]
    # Use configured origins if they don't contain wildcard; otherwise use allowlist
    if "*" in _origins:
        logger.warning("CORS wildcard detected — replacing with explicit allowlist")
        _origins = _PRODUCTION_ORIGINS + _DEV_ORIGINS
    # Widget CORS: allow any origin for /api/v1/widget/* (embeddable widget)
    app.add_middleware(WidgetCORSMiddleware)
    # Main CORS: explicit allowlist only, with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # -- Register middleware (LIFO — last registered = first to execute) ------
    #    Execution order: RequestId → SecurityHeaders → InputSanitizer
    #                     → LocalhostGuard → BotPrevention → TokenGuard
    #                     → TierIsolation → RateLimiter → GranularRateLimiter
    #                     → Constitution → Audit
    from isg_agent.middleware.request_id import RequestIdMiddleware
    from isg_agent.middleware.security_headers import SecurityHeadersMiddleware
    from isg_agent.middleware.input_sanitizer import InputSanitizerMiddleware
    from isg_agent.middleware.localhost_guard import LocalhostGuardMiddleware
    from isg_agent.middleware.audit_middleware import AuditMiddleware
    from isg_agent.middleware.token_guard import TokenRevocationGuard
    from isg_agent.middleware.tier_isolation import TierIsolationMiddleware
    from isg_agent.security.constitution import (
        ConstitutionEnforcer,
        ConstitutionMiddleware,
        SecurityConstitution,
    )
    from isg_agent.security.rate_limiter import (
        GranularRateLimiter,
        RateLimitMiddleware as GranularRateLimitMiddleware,
    )

    # Innermost (executes last) — audit every request
    app.add_middleware(AuditMiddleware)

    # Security constitution — enforces hard invariants on every request.
    # Inbound webhook paths are excluded from Constitution enforcement because
    # each endpoint manages its own auth scheme (SendGrid → Basic Auth,
    # Twilio → HMAC-SHA1 signature, Google Calendar → header validation).
    # Applying the no_unsigned_artifacts JWT invariant to these paths would
    # block requests that send non-JWT credentials with a 403 before the
    # endpoint's own auth logic (which correctly returns 401) can execute.
    _constitution = SecurityConstitution()
    _constitution_enforcer = ConstitutionEnforcer(constitution=_constitution)
    _constitution_skip_paths = ConstitutionMiddleware.SKIP_PATHS | frozenset({
        "/api/v1/webhooks/sendgrid/inbound",
        "/api/v1/webhooks/twilio/inbound",
        "/api/v1/webhooks/google-calendar/push",
        "/auth/oauth/token",
        "/auth/oauth/refresh",
        "/auth/oauth/authorize",
        "/auth/oauth/login-and-authorize",
    })
    app.add_middleware(
        ConstitutionMiddleware,
        enforcer=_constitution_enforcer,
        skip_paths=_constitution_skip_paths,
    )

    # Granular per-IP/per-user/per-agent rate limiter (supplementary)
    _granular_limiter = GranularRateLimiter()
    app.add_middleware(GranularRateLimitMiddleware, limiter=_granular_limiter)

    # STOA Layer 3: Rate limiting (via slowapi — separate setup)
    from isg_agent.middleware.rate_limiter_middleware import setup_rate_limiting
    setup_rate_limiting(app)

    # STOA Layer 4: Tier isolation — fail-closed for ungoverned routes
    app.add_middleware(TierIsolationMiddleware)

    # STOA Layer 2: Token revocation guard — checks before route handlers
    app.add_middleware(TokenRevocationGuard)

    # STOA Layer 0: Bot prevention — invisible, no user friction
    from isg_agent.middleware.bot_prevention import BotPreventionMiddleware
    app.add_middleware(BotPreventionMiddleware)

    # Existing middleware
    app.add_middleware(LocalhostGuardMiddleware, enabled=not _settings.enable_remote)

    # Input sanitizer — validates and sanitizes all incoming request bodies
    app.add_middleware(InputSanitizerMiddleware)

    _is_prod = _settings.deployment_env not in ("development", "dev", "local", "test", "testing")
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=_is_prod)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, Any]:
        """Return gateway health status."""
        return {"status": "healthy"}

    # -- Mount route modules -------------------------------------------------
    from isg_agent.api.routes.auth import router as auth_router
    from isg_agent.api.routes.auth_social import router as auth_social_router
    from isg_agent.api.routes.agent import router as agent_router
    from isg_agent.api.routes.agents import router as agents_router
    from isg_agent.api.routes.templates import router as templates_router
    from isg_agent.api.routes.marketplace import router as marketplace_router
    from isg_agent.api.routes.payments import router as payments_router
    from isg_agent.api.routes.audit import router as audit_router
    from isg_agent.api.routes.trust import router as trust_router
    from isg_agent.api.routes.explain import router as explain_router
    from isg_agent.api.routes.config import router as config_router
    from isg_agent.api.routes.skills import router as skills_router
    from isg_agent.api.routes.channels import router as channels_router
    from isg_agent.api.routes.comms import router as comms_router
    from isg_agent.api.routes.tasks import router as tasks_router
    from isg_agent.api.routes.integrations import router as integrations_router
    from isg_agent.api.routes.notify_integrations import router as notify_integrations_router
    from isg_agent.api.routes.oauth import router as oauth_router
    from isg_agent.api.routes.widget import router as widget_router
    from isg_agent.api.routes.public import router as public_router
    from isg_agent.api.routes.analytics import router as analytics_router
    from isg_agent.api.routes.voice import router as voice_router
    from isg_agent.api.routes.finance import router as finance_router
    from isg_agent.api.routes.onboarding import router as onboarding_router
    from isg_agent.api.routes.auth_extended import router as auth_extended_router
    from isg_agent.api.routes.streaming import router as streaming_router
    from isg_agent.api.routes.cli_invoke import router as cli_router
    from isg_agent.api.routes.webhooks_inbound import router as webhooks_inbound_router
    from isg_agent.api.routes.well_known import router as well_known_router
    from isg_agent.api.routes.acp_routes import router as acp_router
    from isg_agent.api.routes.brand_verification import router as brand_verification_router
    from isg_agent.api.routes.admin import router as admin_router
    from isg_agent.api.routes.system_health import router as system_health_router
    from isg_agent.api.routes.auth_passkey import router as auth_passkey_router
    from isg_agent.api.routes.auth_mfa import router as auth_mfa_router
    from isg_agent.api.routes.openapi_gpt import router as openapi_gpt_router
    from isg_agent.capabilities.api_routes import router as business_ops_router
    from isg_agent.api.routes.gpt_actions import router as gpt_actions_router
    from isg_agent.api.routes.zapier import router as zapier_router
    from isg_agent.api.routes.zapier_webhooks import router as zapier_webhooks_router
    from isg_agent.api.routes.nango_connect import router as nango_router
    from isg_agent.api.routes.oauth_server import router as oauth_server_router
    from isg_agent.api.routes.files import router as files_router
    from isg_agent.api.routes.notifications import router as notifications_router
    from isg_agent.api.routes.health import router as health_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(auth_social_router)
    app.include_router(agent_router)
    app.include_router(agents_router)
    app.include_router(templates_router)
    app.include_router(marketplace_router)
    app.include_router(payments_router)
    app.include_router(audit_router)
    app.include_router(trust_router)
    app.include_router(explain_router)
    app.include_router(config_router)
    app.include_router(skills_router)
    app.include_router(channels_router)
    app.include_router(comms_router)
    app.include_router(tasks_router)
    app.include_router(integrations_router)
    app.include_router(notify_integrations_router)
    app.include_router(oauth_router)
    app.include_router(widget_router)
    app.include_router(public_router)
    app.include_router(analytics_router)
    app.include_router(voice_router)
    app.include_router(finance_router)
    app.include_router(onboarding_router)
    app.include_router(auth_extended_router)
    app.include_router(streaming_router)
    app.include_router(cli_router)
    app.include_router(webhooks_inbound_router)
    app.include_router(well_known_router)
    app.include_router(acp_router)
    app.include_router(brand_verification_router)
    app.include_router(admin_router)
    app.include_router(system_health_router)
    app.include_router(auth_passkey_router)
    app.include_router(auth_mfa_router)
    app.include_router(openapi_gpt_router)
    app.include_router(business_ops_router)
    app.include_router(gpt_actions_router)
    app.include_router(zapier_router)
    app.include_router(zapier_webhooks_router)
    app.include_router(nango_router)
    app.include_router(oauth_server_router)
    app.include_router(files_router)
    app.include_router(notifications_router)

    # -- Mount MCP ASGI app (fail-open) ---------------------------------------
    try:
        from isg_agent.mcp.server import mcp
        mcp_asgi = mcp.get_asgi_app()
        app.mount("/mcp", mcp_asgi)
        logger.info("MCP server mounted at /mcp")
    except Exception as e:
        logger.warning(f"MCP mount failed: {e}")

    # -- Mount WebSocket endpoint ---------------------------------------------
    from isg_agent.api.websocket import websocket_handler

    app.websocket("/ws")(websocket_handler)

    # -- STOA Layer 5: Route validation at startup ----------------------------
    from isg_agent.core.route_validator import validate_routes

    _is_strict = _settings.deployment_env in ("production", "staging")
    ungated = validate_routes(app, strict=_is_strict, log_only=not _is_strict)
    if ungated and not _is_strict:
        logger.warning("Route validator found %d ungated routes (dev mode — warnings only)", len(ungated))

    return app
