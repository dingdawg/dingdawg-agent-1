# DingDawg Agent 1

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Governance receipts for AI agents.**

Every action a governed agent takes generates a cryptographically-signed receipt: what it decided, why, which model, which version, at what time. Built toward EU AI Act Art. 12, Colorado AI Act (SB 24-205), and NIST AI RMF requirements.

The receipt is what turns a policy document into evidence.

## What's live today

| Capability | Endpoint |
|---|---|
| Developer signup — issues a scoped API key | `POST /v1/developers/signup` |
| Governed execution — routes agent calls through metering + audit | `POST /v1/govern/execute` |
| Compliance classification | `POST /api/v1/compliance/classify` |
| Regulation lookup | `GET /api/v1/compliance/regulations` |
| Agent trust score + live stream | `GET /api/v1/agents/{id}/trust`, `WS .../trust/stream` |
| Billing (Stripe) | `POST /api/v1/payments/create-checkout-session` |

Backed by 10 governed-agent npm packages (compliance, legal, healthcare, finance, devops, marketing, sales, support, code-review, planning).

## Quickstart

```bash
curl -X POST https://api.dingdawg.com/v1/developers/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","name":"Your Name","role":"consumer"}'
# -> {"api_key": "dd_...", ...}  store it — shown once
```

```bash
export DINGDAWG_API_KEY=dd_your_key
npx dingdawg-compliance quick-check
```

## Architecture

```
Client (npm package / your agent) --auth: DINGDAWG_API_KEY-->
  api.dingdawg.com (FastAPI, Railway)
    -> Tier isolation + rate limiting
    -> Governance gate (score, log, decide)
    -> Audit trail (signed receipt)
    -> Stripe metering / billing
  -> Response (governed, scored, receipted)
```

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
