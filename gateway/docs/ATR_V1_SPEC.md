# ##LLM:FILE: PRODUCT=dingdawg-platform SYSTEM=agent1-api ENTRY=no PART_OF=atr_v1
# ##LLM:FILE: CONNECTS_TO=isg_agent/api/routes/public.py, <public-receipt-endpoints>
# ##LLM:FILE: BACK_REF=no (additive — first ATR spec draft, nothing references it yet)
# ##LLM:FILE: WAVE=genesis PHASE=DRAFT
#
# ATR v1.0 — Agent Threat Response Open Standard

> **Status:** Draft v0.1 — Pre-OpenWallet filing
> **Last updated:** 2026-05-28
> **Authors:** DingDawg Enterprise (ISG)

---

## 1. Purpose

ATR defines a minimal, verifiable receipt format for agent-driven decisions.
Any system — human or automated — can verify that "agent X made decision Y at
time Z under policy P" without requiring access to the agent's internal state.

### Why this matters

- **Fintech compliance:** Bank partner questionnaires now ask about agent
  decision audit trails. A standard receipt format pre-empts 40+ field-level
  questions.
- **Agent-to-agent trust:** Agent-A needs to know Agent-B's decision was made
  under a known policy version before acting on it.
- **Acquirer diligence:** Stripe, Chainalysis, and Circle all need to verify
  underwriting quality before acquisition. ATR receipts are their evidence
  layer.

---

## 2. Receipt Schema (v1.0)

### JSON Schema

```json
{
  "title": "ATR v1.0 Receipt",
  "type": "object",
  "required": [
    "receipt_id",
    "agent_id",
    "decision",
    "timestamp",
    "subject_id"
  ],
  "properties": {
    "receipt_id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique receipt identifier (UUIDv4)"
    },
    "agent_id": {
      "type": "string",
      "description": "Issuing agent identifier (dingdawg handle or DID)"
    },
    "decision": {
      "type": "string",
      "enum": ["APPROVE", "DECLINE", "REVIEW"],
      "description": "The agent's decision"
    },
    "decision_reason": {
      "type": "string",
      "description": "Human-readable policy rule that fired"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 UTC timestamp of the decision"
    },
    "subject_id": {
      "type": "string",
      "description": "SHA-256 hash of the subject identifier (PII-safe)"
    },
    "policy_version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$",
      "description": "Semantic version of the policy that governed this decision"
    },
    "confidence_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 100,
      "description": "Agent's confidence in the decision (0-100)"
    },
    "parent_receipt_id": {
      "type": "string",
      "format": "uuid",
      "description": "Chain-of-custody link to parent receipt (null if root)"
    },
    "verification_endpoint": {
      "type": "string",
      "format": "uri",
      "description": "Self-referential URL for verifying this receipt"
    }
  }
}
```

### Field rationale

| Field | Required | Why it's in MVP |
|-------|----------|-----------------|
| receipt_id | Yes | Uniquely identifies every decision |
| agent_id | Yes | Attribution -- who decided |
| decision | Yes | The atomic outcome (APPROVE/DECLINE/REVIEW) |
| decision_reason | No | Audit trail -- which rule fired |
| timestamp | Yes | When -- anchors the decision in time |
| subject_id | Yes | What was decided about (PII-safe hash) |
| policy_version | No | Which policy governed (semver) |
| confidence_score | No | Decision quality signal |
| parent_receipt_id | No | Chain-of-custody linking |
| verification_endpoint | No | Self-referential verifier URL |

---

## 3. Verifier Architecture

### Free Public Verifier

```
GET /api/v1/public/receipt/sample       -> static sample receipt
GET /api/v1/public/receipt/{receipt_id} -> verify a receipt
GET /api/v1/public/receipt/schema       -> JSON Schema spec
```

- No authentication required
- No rate limit (basic flood prevention only)
- Returns Access-Control-Allow-Origin: *

### Monetized Telemetry Feed

| Data Product | Price | Description |
|-------------|-------|-------------|
| Decision distribution | $5k/mo | APPROVE/DECLINE/REVIEW rates by policy, agent, time window |
| Confidence heatmaps | $15k/mo | When verifiers disagree or confidence flips |
| Policy drift signals | $25k/mo | Which rules fire most, which age poorly |
| Cross-agent consensus | $50k/mo | How often agent decisions converge/diverge |
| Verifier SLO + latency | $10k/mo | Uptime and performance guarantees |

---

## 4. Ship-Blocker Resolutions

| Blocker | MVP Path (Now) | Ideal Path (Future) |
|---------|---------------|---------------------|
| Stewardship | GitHub strawman spec; self-hosted governance | OpenWallet Foundation filing after 3+ adopters |
| JCS | Omit signatures from MVP; trust via TLS | RS256 + JCS canonicalization for offline verification |
| FIPS | Railway infrastructure (FedRAMP adjacent); no FIPS claims | AWS GovCloud if customer mandates |
| OFAC/Sanctions | Chainalysis API integration | Cached blocklists + fallback provider |
| SDKs | OpenAPI spec + curl examples | Python/Go/TypeScript SDKs after 50+ signups |
| parent_receipt_id | SQL foreign key on receipts table | Merkle tree or append-only ledger |

---

## 5. Sample Receipt

```json
{
  "receipt_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "agent_id": "@compliance-bot",
  "decision": "DECLINE",
  "decision_reason": "Transaction exceeds single-payment threshold (USD 9,500 of USD 10,000 limit)",
  "timestamp": "2026-05-28T14:30:00Z",
  "subject_id": "a3f2b8c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0",
  "policy_version": "1.4.2",
  "confidence_score": 94,
  "parent_receipt_id": null,
  "verification_endpoint": "/api/v1/public/receipt/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```
