"""Multi-LLM Intelligent Router -- IP-compartmentalized model routing.

Routes requests to the optimal model tier based on heuristic task classification:
- SPEED  (Mercury 2 / fast inference) -- greetings, FAQs, status, lookups, acks
- CREATIVE (GPT-4o / conversational)  -- writing, brainstorming, personality, marketing
- REASONING (Claude / complex logic)  -- code, analysis, planning, multi-step, tool use

Key design principles:
1. Zero LLM calls in the routing path -- pure keyword/heuristic O(1) classification
2. IP compartmentalization -- each tier only sees sanitized context
3. SQLite-backed analytics -- track routing decisions, costs, latency
4. Thread-safe -- all mutable state guarded by threading.Lock
5. Standalone -- no imports from other internal modules (brain, api, etc.)

This module sits alongside the existing router.py and provides a
higher-level routing abstraction with persistent metrics and IP protection.
"""

from __future__ import annotations

import enum
import hashlib
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "ModelTier",
    "TaskType",
    "TASK_TIER_MAP",
    "RoutingDecision",
    "RoutingResult",
    "TaskClassifier",
    "ContextSanitizer",
    "RoutingMetrics",
    "IntelligentRouter",
    "MODEL_CONFIGS",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ModelTier(enum.Enum):
    """Model tier for routing decisions."""

    SPEED = "speed"        # Mercury 2 / fast inference
    CREATIVE = "creative"  # GPT-4o / conversational
    REASONING = "reasoning"  # Claude / complex logic


class TaskType(enum.Enum):
    """Classification of user tasks for model routing.

    Each task type maps to exactly one ModelTier via TASK_TIER_MAP.
    5 types per tier, 15 total.
    """

    # SPEED tier
    GREETING = "greeting"
    FAQ = "faq"
    STATUS_CHECK = "status_check"
    SIMPLE_LOOKUP = "simple_lookup"
    ACKNOWLEDGMENT = "acknowledgment"

    # CREATIVE tier
    CONVERSATION = "conversation"
    CREATIVE_WRITING = "creative_writing"
    BRAINSTORM = "brainstorm"
    PERSONALITY = "personality"
    MARKETING_COPY = "marketing_copy"

    # REASONING tier
    CODE_GENERATION = "code_generation"
    MULTI_STEP = "multi_step"
    TOOL_USE = "tool_use"
    ANALYSIS = "analysis"
    PLANNING = "planning"


# Map each task type to its default tier
TASK_TIER_MAP: dict[TaskType, ModelTier] = {
    TaskType.GREETING: ModelTier.SPEED,
    TaskType.FAQ: ModelTier.SPEED,
    TaskType.STATUS_CHECK: ModelTier.SPEED,
    TaskType.SIMPLE_LOOKUP: ModelTier.SPEED,
    TaskType.ACKNOWLEDGMENT: ModelTier.SPEED,
    TaskType.CONVERSATION: ModelTier.CREATIVE,
    TaskType.CREATIVE_WRITING: ModelTier.CREATIVE,
    TaskType.BRAINSTORM: ModelTier.CREATIVE,
    TaskType.PERSONALITY: ModelTier.CREATIVE,
    TaskType.MARKETING_COPY: ModelTier.CREATIVE,
    TaskType.CODE_GENERATION: ModelTier.REASONING,
    TaskType.MULTI_STEP: ModelTier.REASONING,
    TaskType.TOOL_USE: ModelTier.REASONING,
    TaskType.ANALYSIS: ModelTier.REASONING,
    TaskType.PLANNING: ModelTier.REASONING,
}


# ---------------------------------------------------------------------------
# Data classes (frozen)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable record of a routing decision.

    Attributes
    ----------
    tier:
        The model tier selected.
    task_type:
        The classified task type.
    confidence:
        Confidence in classification (0.0 to 1.0).
    model_id:
        Specific model identifier (e.g. "mercury-2", "gpt-4o").
    fallback_chain:
        Ordered list of fallback model IDs.
    latency_estimate_ms:
        Estimated latency in milliseconds.
    cost_estimate_usd:
        Estimated cost per request in USD.
    context_sanitized:
        Whether context was stripped for IP protection.
    """

    tier: ModelTier
    task_type: TaskType
    confidence: float
    model_id: str
    fallback_chain: list
    latency_estimate_ms: int
    cost_estimate_usd: float
    context_sanitized: bool


@dataclass(frozen=True)
class RoutingResult:
    """Immutable record of a completed routing with actual metrics.

    Attributes
    ----------
    decision:
        The original routing decision.
    actual_latency_ms:
        Actual latency observed.
    actual_tokens:
        Actual tokens consumed.
    actual_cost_usd:
        Actual cost in USD.
    tier_used:
        The tier actually used (may differ from decision if fallback fired).
    fallback_used:
        Whether a fallback model was used.
    """

    decision: RoutingDecision
    actual_latency_ms: float
    actual_tokens: int
    actual_cost_usd: float
    tier_used: ModelTier
    fallback_used: bool


# ---------------------------------------------------------------------------
# TaskClassifier -- keyword-based heuristic, no LLM calls
# ---------------------------------------------------------------------------


class TaskClassifier:
    """Classifies user messages into TaskType using keyword + pattern matching.

    No LLM needed -- pure heuristic classification with O(1) amortized cost.
    Classification priority: REASONING > CREATIVE > SPEED > fallback heuristics.
    """

    SPEED_PATTERNS: list[dict] = [
        # Greetings
        {
            "keywords": [
                "hello", "hi", "hey", "good morning", "good afternoon",
                "good evening", "howdy", "sup", "yo",
            ],
            "type": TaskType.GREETING,
        },
        # FAQ
        {
            "keywords": [
                "what is", "how does", "where is", "when does",
                "who is", "faq", "help",
            ],
            "type": TaskType.FAQ,
        },
        # Status
        {
            "keywords": ["status", "health", "uptime", "ping", "alive", "running"],
            "type": TaskType.STATUS_CHECK,
        },
        # Lookup
        {
            "keywords": ["find", "look up", "search for", "get me", "show me", "list"],
            "type": TaskType.SIMPLE_LOOKUP,
        },
        # Acknowledgment
        {
            "keywords": [
                "ok", "okay", "thanks", "thank you", "got it",
                "understood", "cool", "great", "sure", "yes", "no",
                "yep", "nope",
            ],
            "type": TaskType.ACKNOWLEDGMENT,
        },
    ]

    CREATIVE_PATTERNS: list[dict] = [
        {
            "keywords": [
                "write", "draft", "compose", "create a story", "poem", "creative",
            ],
            "type": TaskType.CREATIVE_WRITING,
        },
        {
            "keywords": ["brainstorm", "ideas for", "suggest", "what if", "imagine"],
            "type": TaskType.BRAINSTORM,
        },
        {
            "keywords": [
                "marketing", "ad copy", "headline", "slogan", "tagline", "campaign",
            ],
            "type": TaskType.MARKETING_COPY,
        },
        {
            "keywords": [
                "personality", "tone", "voice", "character", "roleplay", "pretend",
            ],
            "type": TaskType.PERSONALITY,
        },
    ]

    REASONING_PATTERNS: list[dict] = [
        {
            "keywords": [
                "code", "implement", "function", "class", "debug",
                "fix bug", "program", "script",
            ],
            "type": TaskType.CODE_GENERATION,
        },
        {
            "keywords": [
                "analyze", "compare", "evaluate", "assess", "review", "audit",
            ],
            "type": TaskType.ANALYSIS,
        },
        {
            "keywords": [
                "plan", "strategy", "roadmap", "architecture", "design system",
            ],
            "type": TaskType.PLANNING,
        },
        {
            "keywords": [
                "step by step", "multi-step", "chain", "sequence", "workflow",
            ],
            "type": TaskType.MULTI_STEP,
        },
        {
            "keywords": [
                "use tool", "call api", "invoke", "execute", "run command",
                "tool_use",
            ],
            "type": TaskType.TOOL_USE,
        },
    ]

    # Short keywords (<=3 chars) that need word-boundary matching to avoid
    # false positives like "hi" matching "shipping", "yo" matching "your"
    _BOUNDARY_KEYWORDS: frozenset = frozenset([
        "hi", "hey", "yo", "sup", "ok", "yes", "no", "yep",
        "cool", "sure", "great", "list", "find",
    ])

    @staticmethod
    def _keyword_in_text(keyword: str, text: str) -> bool:
        """Check if keyword appears in text with word-boundary awareness.

        Multi-word keywords (e.g. "good morning") use simple substring match.
        Short single-word keywords (<=4 chars) use word-boundary regex to
        prevent false positives like "hi" matching inside "shipping".
        Longer single-word keywords use simple substring match.
        """
        if " " in keyword:
            # Multi-word phrases: substring match is fine
            return keyword in text
        if len(keyword) <= 4:
            # Short keywords: require word boundaries
            return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
        # Longer keywords: substring match
        return keyword in text

    def classify(
        self,
        message: str,
        has_tool_calls: bool = False,
        conversation_depth: int = 0,
    ) -> tuple[TaskType, float]:
        """Classify a message into a TaskType with confidence score.

        Parameters
        ----------
        message:
            The user message to classify.
        has_tool_calls:
            Whether the message includes tool call requests.
        conversation_depth:
            Number of conversation turns so far.

        Returns
        -------
        tuple[TaskType, float]
            The classified task type and confidence (0.0-1.0).
        """
        if not message or not message.strip():
            return TaskType.ACKNOWLEDGMENT, 0.5

        msg_lower = message.lower().strip()
        word_count = len(msg_lower.split())

        # Tool use is always REASONING with high confidence
        if has_tool_calls:
            return TaskType.TOOL_USE, 0.95

        # Very short messages (1-3 words) are likely greetings/acks
        if word_count <= 3:
            for pattern in self.SPEED_PATTERNS:
                for kw in pattern["keywords"]:
                    if self._keyword_in_text(kw, msg_lower):
                        return pattern["type"], 0.85
            return TaskType.ACKNOWLEDGMENT, 0.6

        # Check REASONING first (highest value -- complex tasks take priority)
        best_reasoning = self._match_patterns(msg_lower, self.REASONING_PATTERNS)
        if best_reasoning and best_reasoning[1] > 0.6:
            return best_reasoning

        # Check CREATIVE
        best_creative = self._match_patterns(msg_lower, self.CREATIVE_PATTERNS)
        if best_creative and best_creative[1] > 0.5:
            return best_creative

        # Check SPEED (lower priority than CREATIVE for longer messages)
        best_speed = self._match_patterns(msg_lower, self.SPEED_PATTERNS)
        if best_speed and best_speed[1] > 0.5:
            # Deep conversations override SPEED-tier matches
            if conversation_depth >= 5:
                return TaskType.CONVERSATION, 0.5
            return best_speed

        # Deep conversations (5+ turns) tend to be more conversational
        if conversation_depth >= 5:
            return TaskType.CONVERSATION, 0.5

        # Long messages (50+ words) are likely analytical
        if word_count >= 50:
            return TaskType.ANALYSIS, 0.45

        # Default to CONVERSATION (creative tier)
        return TaskType.CONVERSATION, 0.4

    def _match_patterns(
        self,
        msg_lower: str,
        patterns: list[dict],
    ) -> Optional[tuple[TaskType, float]]:
        """Match message against a list of keyword patterns.

        Returns the best match (highest score) or None if no match.
        Uses word-boundary matching for short keywords.

        Parameters
        ----------
        msg_lower:
            Lowercased message text.
        patterns:
            List of pattern dicts with "keywords" and "type" keys.

        Returns
        -------
        Optional[tuple[TaskType, float]]
            Best matching (TaskType, confidence) or None.
        """
        best_match: Optional[tuple[TaskType, float]] = None
        best_score = 0.0

        for pattern in patterns:
            matches = sum(
                1 for kw in pattern["keywords"]
                if self._keyword_in_text(kw, msg_lower)
            )
            if matches > 0:
                score = min(0.95, 0.5 + matches * 0.15)
                if score > best_score:
                    best_score = score
                    best_match = (pattern["type"], score)

        return best_match


# ---------------------------------------------------------------------------
# ContextSanitizer -- IP compartmentalization
# ---------------------------------------------------------------------------


class ContextSanitizer:
    """Strips sensitive context before sending to external LLMs.

    Each tier only sees what it needs -- enforces IP compartmentalization
    so no single LLM provider sees the full system architecture.

    Sanitization layers:
    - ALL tiers: strip system internals (MiLA, ISG, governance, trust_ledger, etc.)
    - SPEED tier: additionally strip architecture terms (circuit_breaker, drift_detect, etc.)
    """

    # System internals NEVER sent to any external model
    STRIP_PATTERNS: list[str] = [
        "mila_", "MiLA", "MILA",
        "isg_agent", "ISG",
        "governance", "sovereign",
        "trust_ledger", "claim_ledger",
        "process_patch", "ProcessPatch",
    ]

    # Architecture terms stripped from SPEED tier only
    ARCHITECTURE_TERMS: list[str] = [
        "circuit_breaker", "drift_detect",
        "capability_distiller", "flywheel",
        "executor", "heartbeat",
    ]

    def sanitize_for_tier(self, context: Optional[str], tier: ModelTier) -> Optional[str]:
        """Strip context based on tier sensitivity level.

        Parameters
        ----------
        context:
            Text to sanitize. None and empty string pass through unchanged.
        tier:
            Target model tier determining sanitization depth.

        Returns
        -------
        Optional[str]
            Sanitized text with sensitive terms replaced by [REDACTED].
        """
        if context is None:
            return None
        if not context:
            return context

        result = context

        # All tiers: strip system internals
        for pattern in self.STRIP_PATTERNS:
            result = result.replace(pattern, "[REDACTED]")

        # SPEED tier: also strip architecture terms
        if tier == ModelTier.SPEED:
            for term in self.ARCHITECTURE_TERMS:
                result = result.replace(term, "[REDACTED]")

        return result

    def sanitize_system_prompt(self, prompt: Optional[str], tier: ModelTier) -> Optional[str]:
        """Create tier-appropriate system prompt.

        Delegates to sanitize_for_tier -- same rules apply.

        Parameters
        ----------
        prompt:
            System prompt to sanitize.
        tier:
            Target model tier.

        Returns
        -------
        Optional[str]
            Sanitized system prompt.
        """
        if prompt is None:
            return None
        return self.sanitize_for_tier(prompt, tier)


# ---------------------------------------------------------------------------
# RoutingMetrics -- SQLite-backed routing analytics
# ---------------------------------------------------------------------------


class RoutingMetrics:
    """SQLite-backed routing analytics for tracking decisions, costs, and latency.

    Thread-safe: all writes and reads guarded by threading.Lock.
    Uses PRAGMA busy_timeout=5000 to handle write contention gracefully.
    Uses WAL journal mode for file-backed databases.

    Parameters
    ----------
    db_path:
        SQLite database path. Defaults to ":memory:" for in-memory storage.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")

        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS routing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                task_type TEXT NOT NULL,
                tier TEXT NOT NULL,
                model_id TEXT NOT NULL,
                confidence REAL NOT NULL,
                latency_ms REAL NOT NULL,
                tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 1
            )
        """)
        self._conn.commit()

    def record(self, result: RoutingResult) -> None:
        """Record a completed routing result.

        Parameters
        ----------
        result:
            The completed routing result with actual metrics.
        """
        with self._lock:
            self._conn.execute(
                """INSERT INTO routing_log
                   (timestamp, task_type, tier, model_id, confidence,
                    latency_ms, tokens, cost_usd, fallback_used, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    result.decision.task_type.value,
                    result.tier_used.value,
                    result.decision.model_id,
                    result.decision.confidence,
                    result.actual_latency_ms,
                    result.actual_tokens,
                    result.actual_cost_usd,
                    1 if result.fallback_used else 0,
                    1,
                ),
            )
            self._conn.commit()

    def get_tier_stats(self, days: int = 30) -> dict:
        """Get per-tier routing statistics.

        Parameters
        ----------
        days:
            Look-back period in days.

        Returns
        -------
        dict
            Per-tier stats with count, avg_latency, total_cost, etc.
        """
        with self._lock:
            cursor = self._conn.execute(
                """SELECT tier,
                          COUNT(*) as count,
                          AVG(latency_ms) as avg_latency,
                          SUM(cost_usd) as total_cost,
                          SUM(tokens) as total_tokens,
                          AVG(confidence) as avg_confidence,
                          SUM(fallback_used) as fallback_count
                   FROM routing_log
                   WHERE timestamp >= datetime('now', ?)
                   GROUP BY tier""",
                (f"-{days} days",),
            )
            stats: dict[str, dict] = {}
            for row in cursor.fetchall():
                stats[row[0]] = {
                    "count": row[1],
                    "avg_latency_ms": round(row[2], 1),
                    "total_cost_usd": round(row[3], 6),
                    "total_tokens": row[4],
                    "avg_confidence": round(row[5], 3),
                    "fallback_count": row[6],
                }
            return stats

    def get_cost_savings(self, days: int = 30) -> dict:
        """Estimate cost savings vs sending everything to REASONING tier.

        Parameters
        ----------
        days:
            Look-back period in days.

        Returns
        -------
        dict
            Actual cost, baseline cost, savings in USD, and savings percentage.
        """
        stats = self.get_tier_stats(days)
        reasoning_cost_per_1k = 0.015  # Claude pricing baseline

        actual_cost = sum(s.get("total_cost_usd", 0) for s in stats.values())
        total_tokens = sum(s.get("total_tokens", 0) for s in stats.values())
        baseline_cost = (total_tokens / 1000) * reasoning_cost_per_1k

        savings_pct = 0.0
        if baseline_cost > 0:
            savings_pct = round((1 - actual_cost / baseline_cost) * 100, 1)

        return {
            "actual_cost_usd": round(actual_cost, 4),
            "baseline_cost_usd": round(baseline_cost, 4),
            "savings_usd": round(baseline_cost - actual_cost, 4),
            "savings_pct": savings_pct,
        }

    def get_task_distribution(self, days: int = 30) -> dict:
        """Get task type distribution.

        Parameters
        ----------
        days:
            Look-back period in days.

        Returns
        -------
        dict
            Mapping of task_type string to count, ordered by count desc.
        """
        with self._lock:
            cursor = self._conn.execute(
                """SELECT task_type, COUNT(*) as count
                   FROM routing_log
                   WHERE timestamp >= datetime('now', ?)
                   GROUP BY task_type
                   ORDER BY count DESC""",
                (f"-{days} days",),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}


# ---------------------------------------------------------------------------
# Model configurations
# ---------------------------------------------------------------------------


MODEL_CONFIGS: dict[ModelTier, dict] = {
    ModelTier.SPEED: {
        "primary": {
            "id": "mercury-2",
            "cost_per_1k_input": 0.00025,
            "cost_per_1k_output": 0.00075,
            "avg_latency_ms": 50,
        },
        "fallbacks": [
            {
                "id": "gpt-4o-mini",
                "cost_per_1k_input": 0.00015,
                "cost_per_1k_output": 0.0006,
                "avg_latency_ms": 200,
            },
        ],
    },
    ModelTier.CREATIVE: {
        "primary": {
            "id": "gpt-4o",
            "cost_per_1k_input": 0.005,
            "cost_per_1k_output": 0.015,
            "avg_latency_ms": 400,
        },
        "fallbacks": [
            {
                "id": "claude-sonnet-4-6",
                "cost_per_1k_input": 0.003,
                "cost_per_1k_output": 0.015,
                "avg_latency_ms": 500,
            },
        ],
    },
    ModelTier.REASONING: {
        "primary": {
            "id": "claude-sonnet-4-6",
            "cost_per_1k_input": 0.003,
            "cost_per_1k_output": 0.015,
            "avg_latency_ms": 500,
        },
        "fallbacks": [
            {
                "id": "gpt-4o",
                "cost_per_1k_input": 0.005,
                "cost_per_1k_output": 0.015,
                "avg_latency_ms": 400,
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# IntelligentRouter -- main entry point
# ---------------------------------------------------------------------------


class IntelligentRouter:
    """Main router -- classifies tasks, sanitizes context, routes to optimal model.

    Combines TaskClassifier, ContextSanitizer, and RoutingMetrics into a
    single cohesive routing pipeline. Thread-safe for concurrent use.

    Parameters
    ----------
    db_path:
        SQLite path for routing metrics. Defaults to ":memory:".
    model_configs:
        Override default MODEL_CONFIGS. Useful for testing or custom deployments.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        model_configs: Optional[dict] = None,
    ) -> None:
        self.classifier = TaskClassifier()
        self.sanitizer = ContextSanitizer()
        self.metrics = RoutingMetrics(db_path)
        self._configs = model_configs or MODEL_CONFIGS

    def route(
        self,
        message: str,
        has_tool_calls: bool = False,
        conversation_depth: int = 0,
        system_prompt: Optional[str] = None,
    ) -> RoutingDecision:
        """Route a message to the optimal model tier.

        Parameters
        ----------
        message:
            The user message to route.
        has_tool_calls:
            Whether the message includes tool call requests.
        conversation_depth:
            Number of conversation turns so far.
        system_prompt:
            Optional system prompt (triggers context_sanitized=True).

        Returns
        -------
        RoutingDecision
            Immutable routing decision with tier, model, cost, and latency.
        """
        task_type, confidence = self.classifier.classify(
            message, has_tool_calls, conversation_depth,
        )
        tier = TASK_TIER_MAP[task_type]

        config = self._configs.get(tier, self._configs[ModelTier.REASONING])
        primary = config["primary"]
        fallback_ids = [f["id"] for f in config.get("fallbacks", [])]

        # Estimate cost (assume ~500 tokens per message, average of input+output)
        est_cost = (
            (500 / 1000)
            * (primary["cost_per_1k_input"] + primary["cost_per_1k_output"])
            / 2
        )

        # Context is sanitized when a system_prompt is provided
        context_sanitized = system_prompt is not None

        return RoutingDecision(
            tier=tier,
            task_type=task_type,
            confidence=confidence,
            model_id=primary["id"],
            fallback_chain=fallback_ids,
            latency_estimate_ms=primary["avg_latency_ms"],
            cost_estimate_usd=round(est_cost, 6),
            context_sanitized=context_sanitized,
        )

    def sanitize_context(self, context: str, tier: ModelTier) -> str:
        """Sanitize context for the target tier.

        Parameters
        ----------
        context:
            Raw context string.
        tier:
            Target model tier.

        Returns
        -------
        str
            Sanitized context with sensitive terms redacted.
        """
        return self.sanitizer.sanitize_for_tier(context, tier)

    def sanitize_prompt(self, prompt: str, tier: ModelTier) -> str:
        """Sanitize system prompt for the target tier.

        Parameters
        ----------
        prompt:
            Raw system prompt.
        tier:
            Target model tier.

        Returns
        -------
        str
            Sanitized system prompt.
        """
        return self.sanitizer.sanitize_system_prompt(prompt, tier)

    def record_result(
        self,
        decision: RoutingDecision,
        latency_ms: float,
        tokens: int,
        cost_usd: float,
        fallback_used: bool = False,
        tier_used: Optional[ModelTier] = None,
    ) -> RoutingResult:
        """Record the result of a completed routing.

        Parameters
        ----------
        decision:
            The original routing decision.
        latency_ms:
            Actual latency in milliseconds.
        tokens:
            Actual tokens consumed.
        cost_usd:
            Actual cost in USD.
        fallback_used:
            Whether a fallback model was used.
        tier_used:
            The tier actually used (defaults to decision.tier).

        Returns
        -------
        RoutingResult
            Immutable result record. Also recorded to metrics DB.
        """
        result = RoutingResult(
            decision=decision,
            actual_latency_ms=latency_ms,
            actual_tokens=tokens,
            actual_cost_usd=cost_usd,
            tier_used=tier_used or decision.tier,
            fallback_used=fallback_used,
        )
        self.metrics.record(result)
        return result

    def get_stats(self, days: int = 30) -> dict:
        """Get routing statistics.

        Parameters
        ----------
        days:
            Look-back period in days.

        Returns
        -------
        dict
            Combined tier stats, cost savings, and task distribution.
        """
        return {
            "tier_stats": self.metrics.get_tier_stats(days),
            "cost_savings": self.metrics.get_cost_savings(days),
            "task_distribution": self.metrics.get_task_distribution(days),
        }
