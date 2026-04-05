"""Tests for DID identity wiring into the DingDawg Agent 1 API.

Covers:
- GET /.well-known/did.json — platform DID document
- GET /.well-known/did/{handle}.json — agent-specific DID document
- GET /api/v1/agents/handle/{handle}/did — public DID resolution endpoint
- Agent creation auto-creates DID
- Agent creation succeeds even if DID creation raises (fail-open)
- Non-existent handle returns 404
- DID manager unavailable returns 503 (well-known) or 503 (api endpoint)
- W3C DID document structure validation
"""

from __future__ import annotations

import os
from typing import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-did-wiring-suite"
_PLATFORM_DID_PATH = "/.well-known/did.json"
_W3C_CONTEXT_BASE = "https://www.w3.org/ns/did/v1"
_DID_PREFIX = "did:web:app.dingdawg.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the full app with lifespan."""
    db_file = str(tmp_path / "test_did_wiring.db")
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest_asyncio.fixture
async def auth_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Async HTTP client pre-loaded with a registered + logged-in user token."""
    db_file = str(tmp_path / "test_did_wiring_auth.db")
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            # Register a user
            reg_resp = await c.post(
                "/auth/register",
                json={
                    "email": "did-test@example.com",
                    "password": "SecurePass123!",
                    "name": "DID Test User",
                    "terms_accepted": True,
                },
            )
            assert reg_resp.status_code in (200, 201), f"Register failed: {reg_resp.text}"

            # Auto-verify email so login succeeds (email verification gate)
            import aiosqlite as _aiosqlite
            async with _aiosqlite.connect(db_file) as _db:
                await _db.execute("UPDATE users SET email_verified=1 WHERE email=?", ("did-test@example.com",))
                await _db.commit()

            # Log in to get token
            login_resp = await c.post(
                "/auth/login",
                json={"email": "did-test@example.com", "password": "SecurePass123!"},
            )
            assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
            token = login_resp.json()["access_token"]
            c.headers.update({"Authorization": f"Bearer {token}"})
            yield c


# ---------------------------------------------------------------------------
# 1. Platform DID document — /.well-known/did.json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_did_returns_200(client):
    """GET /.well-known/did.json returns HTTP 200."""
    resp = await client.get(_PLATFORM_DID_PATH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_platform_did_no_auth_required(client):
    """Platform DID endpoint is public — no token needed."""
    resp = await client.get(_PLATFORM_DID_PATH)
    assert resp.status_code not in (401, 403)


@pytest.mark.asyncio
async def test_platform_did_response_is_json(client):
    """Response body is valid JSON."""
    resp = await client.get(_PLATFORM_DID_PATH)
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_platform_did_has_context(client):
    """DID document contains @context with W3C DID v1."""
    resp = await client.get(_PLATFORM_DID_PATH)
    data = resp.json()
    assert "@context" in data
    ctx = data["@context"]
    # context may be a string or list
    if isinstance(ctx, list):
        assert any(_W3C_CONTEXT_BASE in c for c in ctx)
    else:
        assert _W3C_CONTEXT_BASE in ctx


@pytest.mark.asyncio
async def test_platform_did_has_id_field(client):
    """DID document contains 'id' field with the platform DID."""
    resp = await client.get(_PLATFORM_DID_PATH)
    data = resp.json()
    assert "id" in data
    assert data["id"] == _DID_PREFIX


@pytest.mark.asyncio
async def test_platform_did_has_controller(client):
    """DID document contains 'controller' field."""
    resp = await client.get(_PLATFORM_DID_PATH)
    data = resp.json()
    assert "controller" in data


@pytest.mark.asyncio
async def test_platform_did_cors_header(client):
    """Platform DID endpoint has CORS wildcard header."""
    resp = await client.get(_PLATFORM_DID_PATH)
    assert resp.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_platform_did_has_service_list(client):
    """DID document contains 'service' field as a list."""
    resp = await client.get(_PLATFORM_DID_PATH)
    data = resp.json()
    assert "service" in data
    assert isinstance(data["service"], list)


# ---------------------------------------------------------------------------
# 2. Agent-specific DID — /.well-known/did/{handle}.json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_did_nonexistent_handle_returns_404(client):
    """/.well-known/did/nonexistent.json returns 404."""
    resp = await client.get("/.well-known/did/nonexistent-handle-xyz.json")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_did_404_body_has_detail(client):
    """404 response includes a 'detail' key."""
    resp = await client.get("/.well-known/did/ghost-agent.json")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_agent_did_no_auth_required(client):
    """Agent DID endpoint is public — no auth header needed."""
    resp = await client.get("/.well-known/did/some-handle.json")
    # 404 is expected (handle doesn't exist) but not 401/403
    assert resp.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# 3. Agent creation auto-creates DID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_creation_auto_creates_did(auth_client):
    """Creating an agent automatically creates a DID retrievable via the API."""
    handle = "test-did-auto-create"

    # Create the agent
    create_resp = await auth_client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "DID Auto Test Agent",
            "agent_type": "business",
        },
    )
    assert create_resp.status_code == 201, f"Agent creation failed: {create_resp.text}"

    # Verify DID was created via the well-known endpoint
    did_resp = await auth_client.get(f"/.well-known/did/{handle}.json")
    assert did_resp.status_code == 200, f"Expected DID doc, got: {did_resp.text}"


@pytest.mark.asyncio
async def test_agent_did_document_format_after_creation(auth_client):
    """DID document returned after agent creation has correct W3C structure."""
    handle = "test-did-format-check"

    create_resp = await auth_client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "DID Format Test",
            "agent_type": "business",
        },
    )
    assert create_resp.status_code == 201

    did_resp = await auth_client.get(f"/.well-known/did/{handle}.json")
    assert did_resp.status_code == 200
    data = did_resp.json()

    # W3C required fields
    assert "id" in data
    assert "controller" in data
    assert "verificationMethod" in data
    assert isinstance(data["verificationMethod"], list)
    assert "authentication" in data
    assert "assertionMethod" in data
    assert "service" in data


@pytest.mark.asyncio
async def test_agent_did_id_matches_did_web_format(auth_client):
    """DID document 'id' is the expected did:web DID."""
    handle = "test-did-id-format"

    create_resp = await auth_client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "DID ID Format Test",
            "agent_type": "business",
        },
    )
    assert create_resp.status_code == 201

    did_resp = await auth_client.get(f"/.well-known/did/{handle}.json")
    assert did_resp.status_code == 200
    data = did_resp.json()

    expected_did = f"did:web:app.dingdawg.com:agents:{handle}"
    assert data["id"] == expected_did


@pytest.mark.asyncio
async def test_agent_did_has_ed25519_verification_method(auth_client):
    """DID document has an Ed25519VerificationKey2020 verification method."""
    handle = "test-did-ed25519"

    create_resp = await auth_client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "DID Ed25519 Test",
            "agent_type": "business",
        },
    )
    assert create_resp.status_code == 201

    did_resp = await auth_client.get(f"/.well-known/did/{handle}.json")
    assert did_resp.status_code == 200
    data = did_resp.json()

    vms = data["verificationMethod"]
    assert len(vms) >= 1
    assert vms[0]["type"] == "Ed25519VerificationKey2020"
    assert "publicKeyMultibase" in vms[0]
    # multibase base58btc starts with 'z'
    assert vms[0]["publicKeyMultibase"].startswith("z")


# ---------------------------------------------------------------------------
# 4. Fail-open: agent creation succeeds even if DID creation fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_creation_succeeds_when_did_manager_raises(auth_client):
    """Agent creation completes normally even if DIDManager.create_did raises."""
    handle = "test-did-fail-open"

    # Patch DIDManager.create_did to raise an unexpected error
    with patch(
        "isg_agent.identity.did_manager.DIDManager.create_did",
        side_effect=RuntimeError("Simulated DID failure"),
    ):
        create_resp = await auth_client.post(
            "/api/v1/agents",
            json={
                "handle": handle,
                "name": "Fail-Open Test",
                "agent_type": "business",
            },
        )

    # Agent creation must succeed despite DID failure
    assert create_resp.status_code == 201, (
        f"Expected 201 with fail-open DID, got {create_resp.status_code}: {create_resp.text}"
    )
    data = create_resp.json()
    assert data["handle"] == handle


# ---------------------------------------------------------------------------
# 5. /api/v1/agents/handle/{handle}/did endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_did_endpoint_returns_404_for_unknown(client):
    """GET /api/v1/agents/handle/{handle}/did returns 404 for unknown handle."""
    resp = await client.get("/api/v1/agents/handle/unknown-handle-xyz/did")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_handle_did_endpoint_no_auth_required(client):
    """DID resolution endpoint is public."""
    resp = await client.get("/api/v1/agents/handle/no-such-handle/did")
    assert resp.status_code not in (401, 403)


@pytest.mark.asyncio
async def test_handle_did_endpoint_returns_did_doc_after_creation(auth_client):
    """After agent creation, /api/v1/agents/handle/{handle}/did returns the DID doc."""
    handle = "test-api-did-endpoint"

    create_resp = await auth_client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "API DID Endpoint Test",
            "agent_type": "business",
        },
    )
    assert create_resp.status_code == 201

    did_resp = await auth_client.get(f"/api/v1/agents/handle/{handle}/did")
    assert did_resp.status_code == 200

    data = did_resp.json()
    assert data["id"] == f"did:web:app.dingdawg.com:agents:{handle}"


@pytest.mark.asyncio
async def test_handle_did_endpoint_cors_header(auth_client):
    """DID API endpoint has CORS wildcard header."""
    handle = "test-api-did-cors"

    await auth_client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "CORS DID Test",
            "agent_type": "business",
        },
    )

    resp = await auth_client.get(f"/api/v1/agents/handle/{handle}/did")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# 6. Platform root DID seeded at startup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_did_seeded_at_startup_has_verification_methods(client):
    """After lifespan startup, /.well-known/did.json returns a DID document
    that contains at least one Ed25519 verification method — not the empty
    static fallback that existed before seeding was wired in."""
    resp = await client.get(_PLATFORM_DID_PATH)
    assert resp.status_code == 200
    data = resp.json()
    vms = data.get("verificationMethod", [])
    assert len(vms) >= 1, (
        "Platform DID must have at least one verification method after startup seeding"
    )
    assert vms[0]["type"] == "Ed25519VerificationKey2020"
    assert vms[0]["publicKeyMultibase"].startswith("z")


@pytest.mark.asyncio
async def test_platform_did_seeded_at_startup_is_idempotent(tmp_path):
    """Starting the application twice against the same database does not fail.

    The second lifespan startup encounters an already-seeded platform DID and
    must log + continue rather than raising an exception.
    """
    db_file = str(tmp_path / "test_did_idempotent.db")
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    # First startup — seeds the DID
    app = create_app()
    async with lifespan(app):
        pass

    # Second startup against the same DB — must not raise
    get_settings.cache_clear()
    app2 = create_app()
    async with lifespan(app2):
        transport = ASGITransport(app=app2)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get(_PLATFORM_DID_PATH)
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == _DID_PREFIX


@pytest.mark.asyncio
async def test_platform_did_seeded_at_startup_has_correct_id(client):
    """Platform DID document returned from /.well-known/did.json has
    ``id == 'did:web:app.dingdawg.com'`` — the platform root DID, not an
    agent sub-path DID."""
    resp = await client.get(_PLATFORM_DID_PATH)
    data = resp.json()
    assert data["id"] == _DID_PREFIX


@pytest.mark.asyncio
async def test_startup_succeeds_when_seed_platform_did_raises(tmp_path):
    """Lifespan startup completes successfully even if seed_platform_did raises
    an unexpected non-ValueError exception.  The fail-open guard must absorb
    the error and continue normal startup."""
    db_file = str(tmp_path / "test_did_seed_fail.db")
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan
    from isg_agent.identity.did_manager import DIDManager

    app = create_app()
    with patch.object(
        DIDManager,
        "seed_platform_did",
        side_effect=RuntimeError("Simulated seed failure"),
    ):
        # Must not raise — lifespan is fail-open for DID seeding
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as c:
                # Health endpoint must still be reachable
                resp = await c.get("/health")
                assert resp.status_code == 200


@pytest.mark.asyncio
async def test_platform_did_resolve_returns_document_with_service(client):
    """The seeded platform DID document includes at least one service entry
    describing the agent platform endpoint."""
    resp = await client.get(_PLATFORM_DID_PATH)
    assert resp.status_code == 200
    data = resp.json()
    services = data.get("service", [])
    assert len(services) >= 1, "Platform DID must have at least one service endpoint"
    # The service must have the required W3C fields
    svc = services[0]
    assert "id" in svc
    assert "type" in svc
    assert "serviceEndpoint" in svc
