# ISG Agent 1

[![CI](https://github.com/InnovativeSystemsGlobal/isg-agent-1/actions/workflows/ci.yml/badge.svg)](https://github.com/InnovativeSystemsGlobal/isg-agent-1/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Governance from Day 1.** A security-hardened, governance-first autonomous AI agent platform.

ISG Agent 1 proves that autonomous AI agents can be both powerful and safe. While other agent platforms bolt on security as an afterthought, ISG Agent 1 bakes governance into every layer from the start.

## 7 Innovations No Other Agent Has

| Innovation | What It Does |
|-----------|-------------|
| **Agent Constitution** | Machine-enforced behavioral contract -- not guidelines, a verified contract |
| **Adversarial Self-Testing** | The agent red-teams itself in production on a schedule |
| **Time-Locked Actions** | Mandatory cooling period before dangerous operations (30-60s) |
| **Trust Ledger** | Transparent, cryptographic reputation tracking for every action |
| **Explain Mode** | Cryptographic proof of why every decision was made |
| **Skill Reputation** | Community-verified trust scores for agent skills |
| **Separation of Powers** | Critical actions require approval from independent agent or human |

## Security Comparison

ISG Agent 1 was built as a direct response to the security failures in existing agent platforms. Where others have exposed instances, malicious skills, and no audit trails, ISG Agent 1 has localhost-only defaults, skill quarantine, and hash-chained audit logs.

## Quickstart

```bash
git clone https://github.com/InnovativeSystemsGlobal/isg-agent-1.git
cd isg-agent-1

cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env
cp ../config/agent.example.yaml ../config/agent.yaml

python -m isg_agent
```

The gateway starts on `http://localhost:8900` by default (localhost-only).

## Architecture

```
User (Discord/Telegram/Web)
  -> Bridge (TypeScript, normalizes messages)
  -> Gateway (Python/FastAPI, governance engine)
     -> Constitution check
     -> Governance gate (PROCEED/REVIEW/HALT)
     -> Audit trail (SHA-256 hash chain)
     -> Brain (LLM + convergence guarantees)
     -> Skills (sandboxed, quarantined, reputation-scored)
  -> Response (governed, explained, audited)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full architecture overview.

## Documentation

- [Quickstart Guide](docs/quickstart.md)
- [Architecture Overview](docs/architecture.md)
- [Security Model](docs/security-model.md)
- [The 7 Innovations](docs/innovations.md)
- [Constitution Guide](docs/constitution-guide.md)
- [Skill Development](docs/skill-development.md)
- [Deployment Guide](docs/deployment.md)
- [API Reference](docs/api-reference.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## Security

See [SECURITY.md](SECURITY.md) for our responsible disclosure policy.

## License

MIT License. See [LICENSE](LICENSE) for details.

**Innovative Systems Global. The name is not aspirational. It is a statement of fact.**
