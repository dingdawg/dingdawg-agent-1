# Security Policy

## Reporting a Vulnerability

We take security seriously. ISG Agent 1 is built with governance from day one.

### How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email: **security@innovativesystemsglobal.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Any suggested fixes

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 7 days
- **Critical fix**: Within 14 days
- **High severity fix**: Within 30 days

### Scope

In scope:
- Authentication and authorization bypass
- Prompt injection attacks that bypass governance
- Path traversal or sandbox escape in skill execution
- Audit trail tampering or hash chain corruption
- Secret/credential exposure in agent output
- Time-lock bypass mechanisms
- Trust ledger manipulation
- Constitution enforcement bypass

Out of scope:
- Denial of service against locally-hosted instances
- Social engineering
- Third-party dependency issues (report to maintainer)
- Physical access attacks

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Architecture

1. **Localhost-only by default** -- No remote access without explicit configuration
2. **Governance gate** -- Every action assessed for risk (PROCEED/REVIEW/HALT)
3. **Constitution enforcement** -- Machine-verified behavioral contracts
4. **Time-locked actions** -- Mandatory delays on dangerous operations
5. **Skill sandboxing** -- Untrusted skills run in isolated containers
6. **Hash-chained audit** -- Tamper-evident logging of every action
7. **Trust ledger** -- Transparent reputation tracking
8. **Separation of powers** -- Critical actions require independent approval
