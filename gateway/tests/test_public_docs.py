"""Tests for the curated public API docs surface + ATR receipt endpoints.

Covers:
1. GET /openapi.json  — 200, contains ONLY the curated public surface,
   ZERO admin/internal paths (IP protection).
2. GET /docs          — 200, HTML documentation page.
3. GET /.well-known/security.txt — 200, RFC 9116 fields.
4. ATR v1.0 receipt endpoints — sample, schema, create (happy path),
   retrieve round-trip, and rejection paths (422 validation, 401 auth
   boundary when ISG_AGENT_ATR_API_KEY is configured).

The docs tests use a plain (no-lifespan) client because the docs routes
are registered in ``create_app()``.  The receipt persistence tests run
the app lifespan AND the production schema init (``Database.init()`` —
the same step ``scripts/start.sh`` runs on every boot) so the
``atr_receipts`` table exists.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _init_schema(db_file: str) -> None:
    """Run the same idempotent schema init production uses (start.sh Step 2)."""
    from isg_agent.db.engine import Database

    db = Database(db_path=db_file)
    await db.init()
    await db.close()


@pytest_asyncio.fixture
async def lifespan_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Full-lifespan async client — DB schema is created on startup."""
    from isg_agent.config import get_settings

    db_file = str(tmp_path / "public_docs_test.db")
    old_env = {
        k: os.environ.get(k)
        for k in ("ISG_AGENT_DB_PATH", "ISG_AGENT_SECRET_KEY", "ISG_AGENT_DEPLOYMENT_ENV", "ISG_AGENT_ATR_API_KEY")
    }
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = "public-docs-test-secret-do-not-use"
    os.environ["ISG_AGENT_DEPLOYMENT_ENV"] = "test"
    os.environ.pop("ISG_AGENT_ATR_API_KEY", None)
    get_settings.cache_clear()
    await _init_schema(db_file)

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def keyed_lifespan_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Lifespan client with ISG_AGENT_ATR_API_KEY configured (auth boundary)."""
    from isg_agent.config import get_settings

    db_file = str(tmp_path / "public_docs_keyed_test.db")
    old_env = {
        k: os.environ.get(k)
        for k in ("ISG_AGENT_DB_PATH", "ISG_AGENT_SECRET_KEY", "ISG_AGENT_DEPLOYMENT_ENV", "ISG_AGENT_ATR_API_KEY")
    }
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = "public-docs-test-secret-do-not-use"
    os.environ["ISG_AGENT_DEPLOYMENT_ENV"] = "test"
    os.environ["ISG_AGENT_ATR_API_KEY"] = "test-atr-key-42"
    get_settings.cache_clear()
    await _init_schema(db_file)

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. /openapi.json — curated public spec, zero internal leakage
# ---------------------------------------------------------------------------

#: Substrings that must NEVER appear in any path of the public spec.
_FORBIDDEN_PATH_MARKERS = (
    "admin",
    "internal",
    "console",
    "mfa",
    "passkey",
    "webauthn",
    "cli/",
    "zapier",
    "nango",
    "webhook",
    "comms",
    "finance",
    "audit",
    "trust",
    "attest",
    "compliance",
    "system",
)


class TestPublicOpenAPISpec:
    async def test_openapi_json_returns_200(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("openapi", "").startswith("3.")
        assert "paths" in body and body["paths"], "public spec must not be empty"

    async def test_openapi_json_has_zero_admin_or_internal_paths(
        self, async_client: AsyncClient
    ) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json()["paths"]
        leaked = [
            p
            for p in paths
            if any(marker in p.lower() for marker in _FORBIDDEN_PATH_MARKERS)
        ]
        assert leaked == [], f"internal/admin paths leaked into public spec: {leaked}"

    async def test_openapi_json_contains_expected_public_surface(
        self, async_client: AsyncClient
    ) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        paths = set(resp.json()["paths"])
        expected = {
            "/health",
            "/api/v1/public/agents",
            "/api/v1/public/receipt/sample",
            "/api/v1/public/receipt/schema",
            "/api/v1/public/receipt",
            "/api/v1/public/receipt/{receipt_id}",
            "/api/v1/templates",
            "/.well-known/security.txt",
        }
        missing = expected - paths
        assert not missing, f"expected public paths missing from spec: {missing}"

    async def test_openapi_json_never_exposes_railway_hosts(
        self, async_client: AsyncClient
    ) -> None:
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        assert "railway" not in resp.text.lower(), "internal Railway URL leaked"


# ---------------------------------------------------------------------------
# 2. /docs — human-readable docs page
# ---------------------------------------------------------------------------


class TestPublicDocsPage:
    async def test_docs_returns_200_html(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/docs")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "/openapi.json" in resp.text


# ---------------------------------------------------------------------------
# 3. /.well-known/security.txt — RFC 9116
# ---------------------------------------------------------------------------


class TestSecurityTxt:
    async def test_security_txt_returns_200_with_required_fields(
        self, async_client: AsyncClient
    ) -> None:
        resp = await async_client.get("/.well-known/security.txt")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        assert "Contact: mailto:hello@dingdawg.com" in resp.text
        assert "Expires: " in resp.text

    async def test_security_txt_expires_is_in_the_future(
        self, async_client: AsyncClient
    ) -> None:
        resp = await async_client.get("/.well-known/security.txt")
        assert resp.status_code == 200
        expires_line = next(
            line for line in resp.text.splitlines() if line.startswith("Expires: ")
        )
        expires = _dt.datetime.fromisoformat(
            expires_line.removeprefix("Expires: ").replace("Z", "+00:00")
        )
        assert expires > _dt.datetime.now(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# 4. ATR v1.0 receipt endpoints
# ---------------------------------------------------------------------------


class TestReceiptEndpoints:
    async def test_receipt_sample_returns_200(self, lifespan_client: AsyncClient) -> None:
        resp = await lifespan_client.get("/api/v1/public/receipt/sample")
        assert resp.status_code == 200
        body = resp.json()
        for field in ("receipt_id", "agent_id", "decision", "timestamp", "subject_id"):
            assert field in body

    async def test_receipt_schema_returns_200(self, lifespan_client: AsyncClient) -> None:
        resp = await lifespan_client.get("/api/v1/public/receipt/schema")
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "ATR v1.0 Receipt"
        assert set(body["required"]) == {
            "receipt_id",
            "agent_id",
            "decision",
            "timestamp",
            "subject_id",
        }

    async def test_create_receipt_happy_path_and_roundtrip(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        """Creating a receipt is a WRITE to the compliance ledger -- it must
        always require a real API key (see TestReceiptAuthBoundary below for
        why an unconfigured key must NOT fall back to open access). Reads
        stay public by design (third-party receipt verification)."""
        payload = {
            "agent_id": "@compliance-bot",
            "decision": "DECLINE",
            "decision_reason": "Exceeds single-payment threshold",
            "subject_id": "a" * 64,
            "policy_version": "1.4.2",
            "confidence_score": 94,
        }
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json=payload,
            headers={"X-API-Key": "test-atr-key-42"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["agent_id"] == "@compliance-bot"
        assert body["decision"] == "DECLINE"
        assert body["receipt_id"]

        # Timestamp must be real (not a hardcoded placeholder)
        ts = _dt.datetime.fromisoformat(body["timestamp"].replace("Z", "+00:00"))
        now = _dt.datetime.now(_dt.timezone.utc)
        assert abs((now - ts).total_seconds()) < 60, (
            f"receipt timestamp {body['timestamp']} is not current — "
            "hardcoded placeholder?"
        )

        # Round-trip: the receipt must be retrievable. get_receipt's own
        # auth behavior is unchanged by this fix -- once a key IS configured
        # (as it is on this fixture), reads require it too, same as before.
        resp2 = await keyed_lifespan_client.get(
            f"/api/v1/public/receipt/{body['receipt_id']}",
            headers={"X-API-Key": "test-atr-key-42"},
        )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["receipt_id"] == body["receipt_id"]
        assert resp2.json()["decision"] == "DECLINE"

    async def test_create_receipt_rejects_bad_decision(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json={"agent_id": "@x", "decision": "MAYBE", "subject_id": "s"},
            headers={"X-API-Key": "test-atr-key-42"},
        )
        assert resp.status_code == 422

    async def test_create_receipt_rejects_missing_agent_id(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json={"decision": "APPROVE", "subject_id": "s"},
            headers={"X-API-Key": "test-atr-key-42"},
        )
        assert resp.status_code == 422

    async def test_create_receipt_rejects_out_of_range_confidence(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json={
                "agent_id": "@x",
                "decision": "APPROVE",
                "subject_id": "s",
                "confidence_score": 150,
            },
            headers={"X-API-Key": "test-atr-key-42"},
        )
        assert resp.status_code == 422

    async def test_get_unknown_receipt_returns_404(
        self, lifespan_client: AsyncClient
    ) -> None:
        resp = await lifespan_client.get(
            "/api/v1/public/receipt/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404


class TestReceiptAuthBoundary:
    """Negative-path boundary: ISG_AGENT_ATR_API_KEY configured."""

    async def test_create_receipt_with_no_key_configured_at_all_returns_401(
        self, lifespan_client: AsyncClient
    ) -> None:
        """Regression: _verify_atr_api_key's documented 'no key configured ==
        open access' fallback was applied identically to writes and reads.
        In production, ISG_AGENT_ATR_API_KEY was never configured, so ANY
        caller could mint a fake compliance receipt for ANY agent_id with
        zero credentials -- found live via a real unauthenticated POST that
        returned 201 against api.dingdawg.com. Reads (GET /receipt/{id})
        are intentionally public for third-party verification; writes never
        should be, regardless of whether ops remembered to set a key."""
        resp = await lifespan_client.post(
            "/api/v1/public/receipt",
            json={"agent_id": "@forged-agent", "decision": "APPROVE", "subject_id": "s"},
        )
        assert resp.status_code == 401, (
            f"expected 401 (no ATR key configured must deny writes), got "
            f"{resp.status_code}: {resp.text} -- if this is 201, the "
            f"unauthenticated-receipt-forgery bug is back"
        )

    async def test_create_receipt_without_key_returns_401(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json={"agent_id": "@x", "decision": "APPROVE", "subject_id": "s"},
        )
        assert resp.status_code == 401

    async def test_create_receipt_with_wrong_key_returns_401(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json={"agent_id": "@x", "decision": "APPROVE", "subject_id": "s"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    async def test_create_receipt_with_correct_key_returns_201(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.post(
            "/api/v1/public/receipt",
            json={"agent_id": "@x", "decision": "APPROVE", "subject_id": "s"},
            headers={"X-API-Key": "test-atr-key-42"},
        )
        assert resp.status_code == 201, resp.text

    async def test_receipt_sample_stays_public_even_with_key(
        self, keyed_lifespan_client: AsyncClient
    ) -> None:
        resp = await keyed_lifespan_client.get("/api/v1/public/receipt/sample")
        assert resp.status_code == 200
