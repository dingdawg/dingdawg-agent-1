# Security Model

## Defense in Depth

ISG Agent 1 implements multiple security layers:

### Layer 1: Constitution Enforcement
Immutable behavioral rules that cannot be overridden by user input or LLM output.

### Layer 2: Input Validation
All inputs are validated using Pydantic schemas before processing.

### Layer 3: Filesystem Sandboxing
All file operations are restricted to the configured workspace directory.
Path traversal is prevented via real-path resolution.

### Layer 4: Execution Sandboxing
Code execution runs in isolated subprocesses with CPU, memory, and timeout limits.

### Layer 5: Authentication
- Gateway secret for bridge-to-gateway pairing
- Remote secret for API-based agent arming
- Per-session tokens for dashboard access

### Layer 6: Rate Limiting
Configurable per-client rate limits to prevent abuse.

## Threat Model

| Threat                     | Mitigation                                  |
|----------------------------|---------------------------------------------|
| Prompt injection           | Constitution enforcement, output filtering  |
| Credential leakage         | No secrets in output, ENV-only storage      |
| Path traversal             | Realpath resolution, workspace jailing      |
| Code execution escape      | Subprocess isolation, resource limits       |
| Unauthorized access        | Secret-based auth, rate limiting            |
| Denial of service          | Rate limits, request size limits, timeouts  |

## Responsible Disclosure

See [SECURITY.md](../SECURITY.md) in the project root for our disclosure policy.
