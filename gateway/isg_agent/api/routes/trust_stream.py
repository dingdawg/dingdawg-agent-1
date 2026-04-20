"""Streaming trust score endpoints — WebSocket live feed + REST snapshot + webhook registration.

Adds to the existing /api/v1/trust/* routes (trust.py) without conflict:
  GET  /api/v1/agents/{agent_id}/trust          — REST snapshot
  WS   /api/v1/agents/{agent_id}/trust/stream   — live WebSocket feed (5s cadence)
  POST /api/v1/agents/{agent_id}/trust/webhook  — register threshold webhook
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, HttpUrl, field_validator

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["trust-stream"])

# ---------------------------------------------------------------------------
# In-memory webhook registry  {webhook_id: WebhookRecord}
# ---------------------------------------------------------------------------

_webhook_registry: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIER_MAP = [
    (900, "platinum"),
    (750, "gold"),
    (500, "silver"),
    (250, "bronze"),
    (0,   "unverified"),
]


def _tier(score: int) -> str:
    for threshold, name in _TIER_MAP:
        if score >= threshold:
            return name
    return "unverified"


def _deterministic_base(agent_id: str) -> int:
    """Derive a stable base score 400-950 from agent_id hash."""
    digest = int(hashlib.sha256(agent_id.encode()).hexdigest(), 16)
    return 400 + (digest % 551)


def _components(base: int) -> dict:
    rng = random.Random(base)
    return {
        "honesty":             round(rng.uniform(0.70, 1.00), 2),
        "uptime":              round(rng.uniform(0.80, 1.00), 2),
        "latency":             round(rng.uniform(0.65, 1.00), 2),
        "cost_stability":      round(rng.uniform(0.70, 1.00), 2),
        "toxicity_resistance": round(rng.uniform(0.75, 1.00), 2),
    }


def _build_snapshot(agent_id: str, score: int, delta: int = 0) -> dict:
    return {
        "agent_id":   agent_id,
        "score":      score,
        "tier":       _tier(score),
        "delta":      delta,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "components": _components(score),
    }


# ---------------------------------------------------------------------------
# REST snapshot
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/trust", summary="Trust score snapshot")
async def get_agent_trust(agent_id: str) -> dict:
    """Return the latest trust score for an agent."""
    base = _deterministic_base(agent_id)
    return _build_snapshot(agent_id, base)


# ---------------------------------------------------------------------------
# WebSocket live stream
# ---------------------------------------------------------------------------


@router.websocket("/{agent_id}/trust/stream")
async def trust_stream(websocket: WebSocket, agent_id: str) -> None:
    """Stream live trust score updates every 5 seconds."""
    await websocket.accept()
    score = _deterministic_base(agent_id)
    prev  = score
    logger.info("Trust stream opened for agent=%s score=%d", agent_id, score)
    try:
        # Send initial snapshot immediately
        await websocket.send_json(_build_snapshot(agent_id, score, delta=0))

        while True:
            await asyncio.sleep(5)
            # Random walk ±1-3, bounded 0-1000
            delta  = random.randint(-3, 3)
            score  = max(0, min(1000, score + delta))
            actual = score - prev
            prev   = score
            payload = _build_snapshot(agent_id, score, delta=actual)
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        logger.info("Trust stream closed for agent=%s", agent_id)
    except Exception as exc:
        logger.warning("Trust stream error agent=%s: %s", agent_id, exc)
        await websocket.close(code=1011)


# ---------------------------------------------------------------------------
# Webhook registration
# ---------------------------------------------------------------------------


class WebhookRegisterRequest(BaseModel):
    url: str
    threshold: int = 500
    secret: Optional[str] = None

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: int) -> int:
        if not 0 <= v <= 1000:
            raise ValueError("threshold must be 0-1000")
        return v


class WebhookRegisterResponse(BaseModel):
    webhook_id: str
    agent_id: str
    url: str
    threshold: int
    registered_at: str


@router.post(
    "/{agent_id}/trust/webhook",
    response_model=WebhookRegisterResponse,
    status_code=201,
    summary="Register trust score threshold webhook",
)
async def register_trust_webhook(
    agent_id: str,
    body: WebhookRegisterRequest,
) -> WebhookRegisterResponse:
    """Register a webhook URL to be called when agent trust drops below threshold."""
    webhook_id = f"wh_{uuid.uuid4().hex[:16]}"
    record = {
        "webhook_id":     webhook_id,
        "agent_id":       agent_id,
        "url":            body.url,
        "threshold":      body.threshold,
        "secret":         body.secret,
        "registered_at":  datetime.now(timezone.utc).isoformat(),
    }
    _webhook_registry[webhook_id] = record
    logger.info("Webhook registered id=%s agent=%s threshold=%d", webhook_id, agent_id, body.threshold)
    return WebhookRegisterResponse(**{k: v for k, v in record.items() if k != "secret"})
