"""Contract tests for the AX discovery surfaces (/llms.txt, /.well-known/agents.json).

These endpoints are the platform's front door for autonomous agents: the
content contract below IS the public promise. The deny-leak assertions
enforce R3 (no internal infrastructure details in any public document),
and the no-price assertion enforces the single-source-of-truth law
(pricing lives only in the Stripe-backed ACP catalog).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes import ax_discovery

BASE = "https://api.dingdawg.com"

DENY_MARKERS = (
    "localhost",
    "127.0.0.1",
    "railway.internal",
    "/home/",
    "joe-rangel",
)


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Bare app with only the AX router; base URL pinned for determinism."""
    monkeypatch.setattr(ax_discovery, "_get_base_url", lambda _request: BASE)
    test_app = FastAPI()
    test_app.include_router(ax_discovery.router)
    return test_app


async def _get(app: FastAPI, path: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


class TestLlmsTxt:
    @pytest.mark.asyncio
    async def test_returns_200_markdown(self, app):
        r = await _get(app, "/llms.txt")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")

    @pytest.mark.asyncio
    async def test_links_every_core_surface(self, app):
        body = (await _get(app, "/llms.txt")).text
        for url in (
            f"{BASE}/.well-known/agents.json",
            f"{BASE}/api/v1/acp/products",
            # ACP manifest lives under the router prefix — a root-level
            # /.well-known/acp-manifest link would 404 (live-verified).
            f"{BASE}/api/v1/acp/.well-known/acp-manifest",
            # The full agent loop must be discoverable: onboard → key → buy.
            f"{BASE}/api/v1/agents/self-onboard",
            f"{BASE}/.well-known/mcp.json",
            f"{BASE}/.well-known/did.json",
            f"{BASE}/openapi.json",
        ):
            assert url in body, f"llms.txt missing {url}"

    @pytest.mark.asyncio
    async def test_no_hardcoded_prices(self, app):
        body = (await _get(app, "/llms.txt")).text
        assert "$" not in body, "pricing must live only in /api/v1/acp/products"

    @pytest.mark.asyncio
    async def test_post_rejected_at_boundary(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post("/llms.txt")
        assert r.status_code == 405


class TestAgentsJson:
    @pytest.mark.asyncio
    async def test_returns_200_with_all_entrypoint_groups(self, app):
        r = await _get(app, "/.well-known/agents.json")
        assert r.status_code == 200
        doc = r.json()
        assert set(doc["entrypoints"]) >= {"mcp", "acp", "identity", "trust", "docs"}
        assert doc["schema_version"]
        assert doc["platform"]["operator"] == "Innovative Systems Global LLC"

    @pytest.mark.asyncio
    async def test_every_url_is_absolute_on_canonical_base(self, app):
        doc = (await _get(app, "/.well-known/agents.json")).json()

        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    yield from walk(value)
            elif isinstance(node, str) and node.startswith("http"):
                yield node

        urls = list(walk(doc["entrypoints"]))
        assert urls, "entrypoints contain no URLs"
        for url in urls:
            assert url.startswith(BASE), f"non-canonical URL: {url}"


class TestProtocols:
    @pytest.mark.asyncio
    async def test_protocols_block_with_vaporware_guard(self, app):
        """Wave 7a: the protocols block tells buyer agents which payment rails
        are real TODAY. The vaporware guard is load-bearing: a protocol may
        claim "live" ONLY if its code serves on this API — a false "live"
        cached by an agent kills platform trust permanently."""
        doc = (await _get(app, "/.well-known/agents.json")).json()
        protocols = doc["protocols"]
        assert protocols["acp"]["status"] == "live"
        assert protocols["acp"]["entrypoint"].startswith(BASE)
        for name, meta in protocols.items():
            assert meta["status"] in {"live", "planned"}, f"{name}: invalid status"
            if meta["status"] == "live":
                assert name == "acp", f"{name} claims live without shipped code"


class TestDenyLeak:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/llms.txt", "/.well-known/agents.json"])
    async def test_no_internal_infrastructure_leaks(self, app, path):
        body = (await _get(app, path)).text
        for marker in DENY_MARKERS:
            assert marker not in body, f"R3 leak: {marker!r} in {path}"
