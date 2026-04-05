# Contributing to ISG Agent 1

Thank you for your interest in contributing. ISG Agent 1 is a security-hardened agent platform, and contributions must meet our quality and security standards.

## Getting Started

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes
4. Run the full test suite including the security gauntlet
5. Submit a pull request

## Development Setup

```bash
# Gateway (Python)
cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Bridges (TypeScript)
cd bridges && npm install

# Dashboard (TypeScript)
cd dashboard && npm install
```

## Running Tests

```bash
make test          # Full test suite
make lint          # Linting
cd gateway && pytest tests/security/ -v   # Security gauntlet
```

## Code Standards

### Python (Gateway)
- Python 3.11+ required
- Type hints on all public functions
- Docstrings on all public modules, classes, and functions
- No `eval()`, `exec()`, or `__import__()` without governance review
- Parameterized queries only
- Files under 500 lines preferred, 1000 lines hard limit
- Ruff for formatting and linting, mypy for type checking

### TypeScript (Bridges, Dashboard)
- Strict mode enabled
- ESLint + Prettier for formatting

### Security Requirements
- No hardcoded secrets
- Input validation at all system boundaries
- Fail-closed error handling
- All new routes must have appropriate RBAC guards

## Pull Request Process

1. Fill out the PR template completely
2. Ensure all CI checks pass
3. Include test coverage for new functionality
4. Update documentation if the public API changes

## Commit Messages

Use conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`

## Reporting Issues

Use GitHub issue templates for bugs and feature requests.
For security vulnerabilities, see [SECURITY.md](SECURITY.md).
