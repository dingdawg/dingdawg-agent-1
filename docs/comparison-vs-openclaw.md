# ISG Agent 1 vs. Open-Source Alternatives

## Architecture Comparison

| Feature                     | ISG Agent 1              | Typical Open-Source Agent |
|-----------------------------|--------------------------|---------------------------|
| Constitution enforcement    | Built-in, 3-tier YAML    | Not included              |
| Multi-provider LLM support  | OpenAI + Anthropic + Google | Usually single provider |
| Time-lock safety            | Configurable delay + cancel | Not included            |
| Platform bridges            | Discord, Telegram, WebSocket | Platform-specific       |
| Skill sandboxing            | Process isolation + limits | Varies                   |
| Memory management           | Configurable pruning strategies | Basic FIFO            |
| Dashboard                   | Built-in React dashboard  | CLI only                  |
| Docker deployment           | Full docker-compose       | Varies                    |

## Key Differentiators

### 1. Governance-First Design
ISG Agent 1 enforces behavioral rules before every action. This is not an
afterthought -- it is the core architectural principle.

### 2. Multi-Platform by Design
The bridge-gateway separation means adding a new platform is a single bridge
implementation. The core agent logic is platform-agnostic.

### 3. Safety Defaults
Time-lock safety, skill confirmation, and filesystem sandboxing are all
enabled by default. Security is not opt-in.

### 4. Production-Ready Packaging
Docker Compose, CI/CD workflows, structured logging, health checks, and
monitoring are included from day one.
