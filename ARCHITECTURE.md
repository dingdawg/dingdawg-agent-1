# ISG Agent 1 -- Architecture Overview

## System Components

ISG Agent 1 is a monorepo with three main components:

```
ISG-Agent-1/
+-- gateway/       Python/FastAPI -- brain, governance, and control plane
+-- bridges/       TypeScript -- messaging platform connectors
+-- dashboard/     TypeScript/React -- web-based administration UI
```

## Gateway (Control Plane)

The gateway is the core of ISG Agent 1. It contains the governance engine, agent brain, memory system, skill execution, and all security enforcement.

### Core Modules

| Module | Purpose |
|--------|---------|
| `governance.py` | Risk assessment gate: PROCEED / REVIEW / HALT |
| `audit.py` | SHA-256 hash-chained tamper-evident audit trail |
| `convergence.py` | Resource budgets and bounded execution loops |
| `constitution.py` | Machine-enforced agent behavioral contracts |
| `time_lock.py` | Mandatory cooling periods for dangerous actions |
| `trust_ledger.py` | Transparent cryptographic reputation scoring |
| `explain.py` | Full decision trace with audit chain linkage |
| `separation.py` | Multi-agent approval for critical actions |
| `rbac.py` | Role-based access control (OWNER/OPERATOR/USER/PUBLIC) |
| `security.py` | Workspace jailing, command filtering, secret detection |
| `sandbox.py` | Docker-based skill isolation |
| `rate_limiter.py` | Token bucket rate limiting |

### Data Flow

```
Incoming Message
  -> Rate limiter (flood protection)
  -> RBAC check (authorization)
  -> Constitution check (behavioral contract)
  -> Governance gate (risk assessment)
  -> Audit record (hash-chained)
  -> Brain processing
     -> Session + memory context
     -> LLM call (with fallback chain)
     -> Tool/skill execution (if requested)
        -> Governance gate (tool-level)
        -> Time-lock check (HIGH/CRITICAL delay)
        -> Skill security scan + quarantine check
        -> Sandboxed execution
        -> Output security scan
        -> Trust ledger update
        -> Convergence guard
     -> Loop until response OR convergence limit
  -> Explain trace recorded
  -> Response returned
```

### Security Boundaries

| Boundary | Protection |
|----------|-----------|
| Network -> Gateway | Localhost-only default, rate limiting |
| Bridge -> Gateway | Pairing token authentication |
| Gateway -> LLM | Prompt injection defense, output scanning |
| Gateway -> Skill | Governance + constitution + sandbox |
| Skill -> Filesystem | `os.path.realpath()` workspace jailing |
| Skill -> Network | Docker `network=none` default |
| Dangerous actions | Time-lock delay (configurable 30-60s) |
| Audit trail | SHA-256 hash chain tamper detection |

## Bridges (Messaging Connectors)

Bridges connect external messaging platforms to the gateway via WebSocket RPC. Each bridge normalizes platform-specific messages into a unified format.

Supported: Web, Discord, Telegram.

## Dashboard (Admin UI)

React-based web dashboard for monitoring and managing the agent: trust score, audit trail, constitution viewer, skill management, time-lock queue, decision trace explorer.

## Database

SQLite in WAL mode. Key tables: `audit_chain`, `sessions`, `messages`, `memory_entries` (FTS5), `skills`, `trust_ledger`, `time_lock_queue`, `constitution_checks`.

## Configuration

YAML files with environment variable overrides: `config/agent.yaml`, `config/identity.md`, `config/constitution.yaml`.
