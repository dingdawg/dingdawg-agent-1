.PHONY: install test lint format docker-up docker-down clean help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (gateway + bridges + dashboard)
	cd gateway && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
	npm install

test: ## Run all tests (gateway + security gauntlet)
	cd gateway && . .venv/bin/activate && python -m pytest tests/ -v --timeout=30
	cd gateway && . .venv/bin/activate && python -m pytest tests/security/ -v

lint: ## Run linters (ruff + mypy)
	cd gateway && . .venv/bin/activate && ruff check isg_agent/ tests/
	cd gateway && . .venv/bin/activate && mypy isg_agent/

format: ## Auto-format code
	cd gateway && . .venv/bin/activate && ruff format isg_agent/ tests/

docker-up: ## Start local dev stack with Docker Compose
	docker compose up -d --build

docker-down: ## Stop local dev stack
	docker compose down

clean: ## Remove build artifacts, caches, and virtual environments
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf gateway/.venv
	rm -rf node_modules bridges/node_modules dashboard/node_modules
