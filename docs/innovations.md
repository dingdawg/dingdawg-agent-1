# ISG Agent 1 Innovations

## Innovation #1: Agent Constitution

A YAML-defined behavioral contract that governs all agent actions. The
constitution is evaluated before every action and cannot be overridden
by user instructions or LLM outputs.

Three tiers of rules:
- **Absolute Rules**: Never violated (hard block)
- **Behavioral Guidelines**: Enforced with escalation path
- **Preferences**: Soft guidance, user-overridable

See [constitution-guide.md](constitution-guide.md) for details.

## Innovation #2: Multi-Provider Brain

The agent brain abstracts across multiple LLM providers (OpenAI, Anthropic,
Google) with automatic fallback. If the primary provider is unavailable or
rate-limited, the agent seamlessly switches to the fallback provider.

## Innovation #3: Time-Lock Safety

Critical operations (code execution, file deletion, external API calls)
require a configurable delay before execution. During the delay window,
the user can cancel the operation. This prevents impulsive or unauthorized
actions by providing a human-in-the-loop safety net.

## Innovation #4: Pluggable Skill Architecture

Skills are self-contained packages with JSON manifests that declare their
capabilities, parameters, and security requirements. The skill engine
validates permissions before execution and enforces sandboxing.

## Innovation #5: Bridge-Gateway Architecture

A clean separation between messaging platforms and the agent core. Adding
a new platform requires only a new bridge implementation -- the gateway
and all its capabilities remain unchanged.
