"""Routing analytics — SQLite-backed metrics for the intelligent router.

Tracks routing decisions, latency, cost, fallback rates, and quality
correlations. All data persisted to SQLite with WAL mode and busy_timeout
for safe concurrent access.

Used by IntelligentRouter for persistent analytics and by the operator
dashboard for routing insights.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from typing import Optional

from isg_agent.models.router import ModelTier, RoutingDecision

__all__ = ["RoutingMetrics"]

logger = logging.getLogger(__name__)

# Baseline cost per request (all-Claude) for savings calculation
# Assumes 500 tokens avg at Claude Sonnet rates ($3.00/M in, $15.00/M out)
_BASELINE_COST_PER_REQUEST = (
    (300 / 1_000_000) * 3.00 + (200 / 1_000_000) * 15.00  # 300 input tokens  # 200 output tokens
)


class RoutingMetrics:
    """SQLite-backed routing analytics.

    Records routing decisions with actual cost and latency, and provides
    aggregate queries for tier distribution, cost savings, latency
    percentiles, fallback rates, and quality correlation.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file. Created if it does not exist.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    @property
    def db_path(self) -> str:
        """Return the database file path."""
        return self._db_path

    def _get_conn(self) -> sqlite3.Connection:
        """Create a connection with busy_timeout and WAL mode."""
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """Initialize the routing_decisions table if it does not exist."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS routing_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    tier TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    model TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    estimated_cost REAL NOT NULL,
                    actual_cost REAL NOT NULL,
                    estimated_latency REAL NOT NULL,
                    actual_latency REAL NOT NULL,
                    success INTEGER NOT NULL DEFAULT 1,
                    fallback_used INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Index for time-range queries
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_routing_timestamp
                ON routing_decisions (timestamp)
                """
            )
            # Index for tier-based queries
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_routing_tier
                ON routing_decisions (tier)
                """
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.error("Failed to initialize routing_decisions table: %s", exc)
            raise
        finally:
            conn.close()

    # -- Recording --

    def record_routing(
        self,
        decision: RoutingDecision,
        actual_latency_ms: float,
        actual_cost_usd: float,
        success: bool,
        *,
        fallback_used: bool = False,
    ) -> None:
        """Record a routing decision with actual metrics.

        Parameters
        ----------
        decision:
            The routing decision that was made.
        actual_latency_ms:
            Actual request latency in milliseconds.
        actual_cost_usd:
            Actual cost in USD.
        success:
            Whether the request completed successfully.
        fallback_used:
            Whether a fallback provider was used.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO routing_decisions
                    (timestamp, tier, classification, model, confidence,
                     estimated_cost, actual_cost, estimated_latency,
                     actual_latency, success, fallback_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    decision.tier.value,
                    decision.classification.value,
                    decision.model_name,
                    decision.confidence,
                    decision.estimated_cost_usd,
                    actual_cost_usd,
                    float(decision.estimated_latency_ms),
                    actual_latency_ms,
                    1 if success else 0,
                    1 if fallback_used else 0,
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.error("Failed to record routing decision: %s", exc)
            raise
        finally:
            conn.close()

    # -- Aggregate queries --

    def get_tier_distribution(self, days: int = 30) -> dict[str, float]:
        """Return percentage of traffic per tier within the time window.

        Parameters
        ----------
        days:
            Number of days to look back.

        Returns
        -------
        dict[str, float]
            Mapping of tier name to percentage (0-100).
            Empty dict if no data.
        """
        cutoff = time.time() - (days * 86400)
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT tier, COUNT(*) as cnt
                FROM routing_decisions
                WHERE timestamp >= ?
                GROUP BY tier
                """,
                (cutoff,),
            )
            rows = cursor.fetchall()
            if not rows:
                return {}

            total = sum(row[1] for row in rows)
            return {row[0]: round((row[1] / total) * 100, 2) for row in rows}
        finally:
            conn.close()

    def get_cost_savings(self, days: int = 30) -> dict[str, float]:
        """Calculate cost savings vs an all-Claude baseline.

        Parameters
        ----------
        days:
            Number of days to look back.

        Returns
        -------
        dict[str, float]
            Keys: total_actual_cost, total_baseline_cost, savings_usd,
            savings_percent.
        """
        cutoff = time.time() - (days * 86400)
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT SUM(actual_cost), COUNT(*)
                FROM routing_decisions
                WHERE timestamp >= ?
                """,
                (cutoff,),
            )
            row = cursor.fetchone()
            actual_cost = row[0] or 0.0
            request_count = row[1] or 0

            baseline_cost = request_count * _BASELINE_COST_PER_REQUEST
            savings = baseline_cost - actual_cost
            savings_pct = (savings / baseline_cost * 100) if baseline_cost > 0 else 0.0

            return {
                "total_actual_cost": round(actual_cost, 8),
                "total_baseline_cost": round(baseline_cost, 8),
                "savings_usd": round(max(savings, 0.0), 8),
                "savings_percent": round(max(savings_pct, 0.0), 2),
            }
        finally:
            conn.close()

    def get_latency_percentiles(
        self, tier: ModelTier
    ) -> dict[str, float]:
        """Return p50, p95, and p99 latency percentiles for a tier.

        Parameters
        ----------
        tier:
            The model tier to query.

        Returns
        -------
        dict[str, float]
            Keys: p50, p95, p99. Values in milliseconds.
            Returns all zeros if no data.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT actual_latency
                FROM routing_decisions
                WHERE tier = ?
                ORDER BY actual_latency ASC
                """,
                (tier.value,),
            )
            latencies = [row[0] for row in cursor.fetchall()]

            if not latencies:
                return {"p50": 0.0, "p95": 0.0, "p99": 0.0}

            return {
                "p50": self._percentile(latencies, 50),
                "p95": self._percentile(latencies, 95),
                "p99": self._percentile(latencies, 99),
            }
        finally:
            conn.close()

    def get_fallback_rate(self, days: int = 30) -> float:
        """Return the percentage of requests that used a fallback provider.

        Parameters
        ----------
        days:
            Number of days to look back.

        Returns
        -------
        float
            Fallback rate as a percentage (0-100). Returns 0.0 if no data.
        """
        cutoff = time.time() - (days * 86400)
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN fallback_used = 1 THEN 1 ELSE 0 END) as fb_count,
                    COUNT(*) as total
                FROM routing_decisions
                WHERE timestamp >= ?
                """,
                (cutoff,),
            )
            row = cursor.fetchone()
            fb_count = row[0] or 0
            total = row[1] or 0

            if total == 0:
                return 0.0
            return round((fb_count / total) * 100, 2)
        finally:
            conn.close()

    def get_quality_correlation(self, tier: ModelTier) -> dict[str, float]:
        """Return quality metrics for a tier based on success rates.

        If user feedback is available in the future, this can be extended
        to correlate routing decisions with satisfaction scores.

        Parameters
        ----------
        tier:
            The model tier to query.

        Returns
        -------
        dict[str, float]
            Keys: total_requests, success_count, success_rate,
            avg_latency_ms, avg_cost_usd.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                    AVG(actual_latency) as avg_latency,
                    AVG(actual_cost) as avg_cost
                FROM routing_decisions
                WHERE tier = ?
                """,
                (tier.value,),
            )
            row = cursor.fetchone()
            total = row[0] or 0
            successes = row[1] or 0
            avg_latency = row[2] or 0.0
            avg_cost = row[3] or 0.0

            success_rate = (successes / total * 100) if total > 0 else 0.0

            return {
                "total_requests": total,
                "success_count": successes,
                "success_rate": round(success_rate, 2),
                "avg_latency_ms": round(avg_latency, 2),
                "avg_cost_usd": round(avg_cost, 8),
            }
        finally:
            conn.close()

    # -- Helpers --

    @staticmethod
    def _percentile(sorted_values: list[float], pct: float) -> float:
        """Calculate a percentile from a sorted list of values.

        Uses linear interpolation between data points.

        Parameters
        ----------
        sorted_values:
            A sorted list of numeric values.
        pct:
            The percentile to compute (0-100).

        Returns
        -------
        float
            The interpolated percentile value.
        """
        if not sorted_values:
            return 0.0

        n = len(sorted_values)
        if n == 1:
            return sorted_values[0]

        # Compute rank using the C = 1 method (inclusive)
        rank = (pct / 100) * (n - 1)
        lower = int(math.floor(rank))
        upper = int(math.ceil(rank))

        if lower == upper:
            return sorted_values[lower]

        # Linear interpolation
        weight = rank - lower
        return sorted_values[lower] + weight * (sorted_values[upper] - sorted_values[lower])
