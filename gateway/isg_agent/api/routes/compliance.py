"""Regulatory pre-clearance router — maps agent compliance events to regulation articles.

Endpoints:
  POST /api/v1/compliance/classify    — classify an event, get regulations triggered
  GET  /api/v1/compliance/regulations — list all supported event types
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

# ---------------------------------------------------------------------------
# Regulation mapping
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = ["low", "medium", "high", "critical"]

REGULATION_MAP: Dict[str, List[Dict[str, str]]] = {
    "user_data_access": [
        {"regulation": "GDPR", "article": "Art.15", "description": "Right of Access",
         "severity": "high", "action_required": "log_and_notify"},
        {"regulation": "EU AI Act", "article": "Art.12", "description": "Record-Keeping for High-Risk AI",
         "severity": "medium", "action_required": "retain_90d"},
    ],
    "user_data_deletion": [
        {"regulation": "GDPR", "article": "Art.17", "description": "Right to Erasure",
         "severity": "high", "action_required": "delete_and_confirm"},
        {"regulation": "CCPA", "article": "§1798.105", "description": "Right to Delete",
         "severity": "high", "action_required": "delete_and_confirm"},
    ],
    "model_output_logging": [
        {"regulation": "EU AI Act", "article": "Art.12", "description": "Record-Keeping for High-Risk AI",
         "severity": "medium", "action_required": "retain_90d"},
        {"regulation": "SOC2", "article": "CC7.2", "description": "System Monitoring",
         "severity": "medium", "action_required": "log_and_alert"},
    ],
    "high_risk_decision": [
        {"regulation": "EU AI Act", "article": "Art.9", "description": "Risk Management for High-Risk AI",
         "severity": "critical", "action_required": "human_review_required"},
        {"regulation": "US EO 14110", "article": "§4.1", "description": "AI Safety Standards",
         "severity": "high", "action_required": "log_and_escalate"},
    ],
    "pii_processing": [
        {"regulation": "GDPR", "article": "Art.6", "description": "Lawfulness of Processing",
         "severity": "critical", "action_required": "verify_legal_basis"},
        {"regulation": "HIPAA", "article": "§164.502", "description": "Minimum Necessary Standard",
         "severity": "critical", "action_required": "verify_minimum_necessary"},
    ],
    "cross_border_transfer": [
        {"regulation": "GDPR", "article": "Art.46", "description": "Transfers Subject to Appropriate Safeguards",
         "severity": "high", "action_required": "verify_transfer_mechanism"},
        {"regulation": "US-EU Privacy Framework", "article": "Principle 3",
         "description": "Data Integrity and Purpose Limitation",
         "severity": "high", "action_required": "document_transfer"},
    ],
    "agent_capability_change": [
        {"regulation": "EU AI Act", "article": "Art.16",
         "description": "Obligations of Providers of High-Risk AI Systems",
         "severity": "medium", "action_required": "notify_authority"},
        {"regulation": "SOC2", "article": "CC8.1", "description": "Change Management",
         "severity": "medium", "action_required": "change_record_required"},
    ],
    "financial_transaction": [
        {"regulation": "MAS TRM", "article": "§12.3", "description": "AI Governance in Financial Services",
         "severity": "high", "action_required": "audit_trail_required"},
        {"regulation": "SOC2", "article": "CC6.1", "description": "Logical and Physical Access Controls",
         "severity": "high", "action_required": "access_log_required"},
    ],
}

# ISO 42001 / SOC2 filing templates per severity
_FILING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "critical": {
        "iso_42001": {"clause": "9.1", "status": "requires_immediate_action",
                      "evidence_required": ["event_log", "impact_assessment", "remediation_plan"]},
        "soc2":     {"category": "CC3.2", "status": "requires_review",
                     "evidence_required": ["control_log", "stakeholder_notification"]},
    },
    "high": {
        "iso_42001": {"clause": "9.1", "status": "compliant_with_evidence",
                      "evidence_required": ["event_log", "notification_record"]},
        "soc2":     {"category": "CC7.2", "status": "compliant", "evidence_required": ["event_log"]},
    },
    "medium": {
        "iso_42001": {"clause": "8.4", "status": "compliant", "evidence_required": ["event_log"]},
        "soc2":     {"category": "CC7.2", "status": "compliant", "evidence_required": []},
    },
    "low": {
        "iso_42001": {"clause": "8.4", "status": "compliant", "evidence_required": []},
        "soc2":     {"category": "CC7.1", "status": "compliant", "evidence_required": []},
    },
}


def _highest_severity(regulations: List[Dict[str, str]]) -> str:
    if not regulations:
        return "low"
    levels = [r.get("severity", "low") for r in regulations]
    return max(levels, key=lambda s: _SEVERITY_ORDER.index(s) if s in _SEVERITY_ORDER else -1)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ClassifyRequest(BaseModel):
    event_type: str
    agent_id: str
    payload: Optional[Dict[str, Any]] = None


class ClassifyResponse(BaseModel):
    event_type: str
    agent_id: str
    regulations_triggered: List[Dict[str, str]]
    pre_clearance_status: str
    highest_severity: str
    actions_required: List[str]
    filing_ready: Dict[str, Any]
    classified_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/classify", response_model=ClassifyResponse, summary="Classify compliance event")
async def classify_event(body: ClassifyRequest) -> ClassifyResponse:
    """Map a compliance event to its triggered regulations and return pre-clearance status."""
    regulations = REGULATION_MAP.get(body.event_type, [])
    highest     = _highest_severity(regulations)
    actions     = list({r["action_required"] for r in regulations})
    status      = "REQUIRES_REVIEW" if highest == "critical" else "APPROVED"
    filing      = _FILING_TEMPLATES.get(highest, _FILING_TEMPLATES["low"])

    logger.info(
        "Compliance classify event=%s agent=%s severity=%s status=%s",
        body.event_type, body.agent_id, highest, status,
    )

    return ClassifyResponse(
        event_type=body.event_type,
        agent_id=body.agent_id,
        regulations_triggered=regulations,
        pre_clearance_status=status,
        highest_severity=highest,
        actions_required=actions,
        filing_ready=filing,
        classified_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/regulations", summary="List all supported compliance event types")
async def list_regulations() -> Dict[str, Any]:
    """Return all supported event types and their regulation mappings."""
    return {
        "supported_event_types": list(REGULATION_MAP.keys()),
        "count": len(REGULATION_MAP),
        "regulations": REGULATION_MAP,
    }
