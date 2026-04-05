# =============================================================================
# DingDawg Agent 1 — Developer Makefile
# =============================================================================
# Usage:
#   make install    — Create venv and install dependencies
#   make dev        — Run development server with auto-reload
#   make test       — Run full test suite
#   make lint       — Run linter (ruff)
#   make build      — Build Docker image
#   make up         — Start via docker-compose
#   make down       — Stop docker-compose
#   make clean      — Remove build artifacts
# =============================================================================

.PHONY: install dev test lint build up down clean help

PYTHON   := python3
VENV     := .venv
PIP      := $(VENV)/bin/pip
PYTEST   := $(VENV)/bin/python -m pytest
RUFF     := $(VENV)/bin/ruff
UVICORN  := $(VENV)/bin/uvicorn
IMAGE    := dingdawg-agent
TAG      := dev

# Default target
help:
	@echo "DingDawg Agent 1 — Available targets:"
	@echo ""
	@echo "  make install    Create venv and install all dependencies"
	@echo "  make dev        Run dev server with auto-reload on port 8900"
	@echo "  make test       Run full test suite (pytest)"
	@echo "  make lint       Run ruff linter"
	@echo "  make build      Build Docker image ($(IMAGE):$(TAG))"
	@echo "  make up         Start via docker-compose"
	@echo "  make down       Stop docker-compose"
	@echo "  make clean      Remove __pycache__, .pytest_cache, etc."
	@echo ""

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "Venv created. Activate with: source $(VENV)/bin/activate"

dev:
	ISG_AGENT_HOST=127.0.0.1 ISG_AGENT_PORT=8900 \
	$(UVICORN) isg_agent.app:create_app \
		--factory \
		--host 127.0.0.1 \
		--port 8900 \
		--reload \
		--log-level info

test:
	$(PYTEST) tests/ -q --tb=short

lint:
	$(RUFF) check isg_agent/ tests/

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

build:
	docker build -t $(IMAGE):$(TAG) .

up:
	docker compose up -d

down:
	docker compose down

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ htmlcov/ .coverage coverage.xml
	@echo "Cleaned build artifacts."
