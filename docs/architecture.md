# Architecture Overview

## System Components

ISG Agent 1 is composed of three main services:

### Gateway (Python)
The core agent engine. Handles LLM communication, skill execution, memory
management, constitution enforcement, and API endpoints.

### Bridges (TypeScript)
Platform connectors that relay messages between messaging platforms (Discord,
Telegram) and the gateway via WebSocket.

### Dashboard (TypeScript/React)
A web-based monitoring and management interface for the agent.

## Communication Flow

```
User -> [Platform] -> Bridge -> WebSocket -> Gateway -> LLM Provider
                                                 |
                                           Constitution
                                           Enforcement
                                                 |
                                              Skills
                                              Engine
```

## Data Flow

1. User sends a message via a messaging platform or the dashboard.
2. The bridge relays the message to the gateway over WebSocket.
3. The gateway loads conversation context from memory.
4. The constitution engine validates the request against behavioral rules.
5. The brain module sends the contextualized prompt to the LLM provider.
6. The LLM response is checked against constitution rules.
7. If the response includes skill invocations, they are executed in sandbox.
8. The final response is sent back through the bridge to the user.

## Database

SQLite with WAL mode for concurrent read access. Stores:
- Conversation history
- Agent sessions
- Skill execution logs
- Reminders and scheduled tasks
- Constitution audit trail

## Security Layers

See [security-model.md](security-model.md) for complete documentation.
