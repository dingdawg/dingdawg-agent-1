# =============================================================================
# DingDawg Agent 1 — Multi-stage Production Dockerfile
# =============================================================================
# Stage 1 (builder): Install Python dependencies from pyproject.toml
# Stage 2 (runtime): Minimal image with only installed packages + source
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install Python dependencies into a clean prefix
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build-time system dependencies for C extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for layer caching
COPY pyproject.toml ./
COPY isg_agent/__init__.py ./isg_agent/__init__.py

# Install project dependencies into /install prefix
# The __init__.py is needed for setuptools to find the package metadata
RUN pip install --no-cache-dir --prefix=/install .

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image with only what's needed to run
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Install curl for health checks (small addition to slim image)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl tini && \
    rm -rf /var/lib/apt/lists/*

# NOTE: Running as root for Railway volume compatibility.
# Railway persistent volumes are mounted as root-owned on new containers.
# A non-root user (UID 1000) cannot chmod or write to root-owned volume mounts,
# causing sqlite3.OperationalError: attempt to write a readonly database.
# Railway's container-level isolation replaces the need for in-container non-root.
# STOA compliance maintained via Railway's platform-level isolation.

WORKDIR /app

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source code
COPY isg_agent/ ./isg_agent/

# Copy startup and health check scripts
COPY scripts/start.sh scripts/healthcheck.sh ./scripts/
RUN chmod +x ./scripts/start.sh ./scripts/healthcheck.sh

# Create data directory for SQLite database
RUN mkdir -p /app/data

# Environment defaults — all overridable at deploy time
ENV ISG_AGENT_HOST=0.0.0.0 \
    ISG_AGENT_PORT=8900 \
    ISG_AGENT_DB_PATH=/app/data/agent.db \
    ISG_AGENT_LOG_LEVEL=info \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8900

# Health check — verify the app responds on /health every 30s
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/scripts/healthcheck.sh"]

# Use tini as init process for proper signal handling (PID 1 reaping)
ENTRYPOINT ["tini", "--"]

# Default command — production startup via start.sh
CMD ["/app/scripts/start.sh"]
