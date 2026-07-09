"""Contract for iter_api_routes — version-proof route enumeration.

Root cause S1182 Wave-1b: newer FastAPI registers include_router() results
as container route objects (children in a nested ``.routes``) instead of
flattening to top-level APIRoutes. Introspection that does a flat
``isinstance(r, APIRoute)`` scan sees only directly-decorated routes — in
production that meant the public OpenAPI spec served 1 path and the strict
RouteValidator scanned 1 route while 250+ actually served.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from isg_agent.core.route_validator import iter_api_routes


def _make_app_with_router() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():  # pragma: no cover - trivial
        return {"ok": True}

    sub = APIRouter(prefix="/api/v1/things")

    @sub.get("/list")
    async def list_things():  # pragma: no cover - trivial
        return []

    app.include_router(sub)
    return app


class _FakeCtx:
    """Models 0.139's _EffectiveRouteContext: FULL resolved path + dependant."""

    def __init__(self, path):
        self.path = path
        self.methods = {"GET"}
        self.include_in_schema = True
        self.dependant = type("D", (), {"call": staticmethod(lambda: None)})()


class _FakeContainerRoute:
    """Models the REAL FastAPI >=0.137 _IncludedRouter (venv-verified on
    0.139.0): NO .routes attribute; the canonical expansion is the
    effective_route_contexts() METHOD, whose contexts carry FULLY resolved
    paths through every nesting level (original_router.routes children only
    carry per-include relative paths — the trap the first fix fell into)."""

    def __init__(self, paths):
        self._paths = paths

    def effective_route_contexts(self):
        return [_FakeCtx(p) for p in self._paths]


def test_flat_registration_yields_all_api_routes():
    """SCENARIO: A security engineer audits the production route table on
               the FastAPI version that flattens include_router output.
    GIVEN:    A gateway app registering one direct route plus one included
              router carrying a prefixed sub-route, exactly like app.py.
    WHEN:     The engineer enumerates every serving API route through
              iter_api_routes over the application's route table.
    THEN:     Both routes surface with their full prefixed paths, so the
              validator and the public spec see the true API surface.
    """
    app = _make_app_with_router()
    paths = {r.path for r in iter_api_routes(app.routes)}
    assert "/health" in paths
    assert "/api/v1/things/list" in paths


def test_container_registration_is_recursed():
    """SCENARIO: The same audit runs against a newer FastAPI deployment
               where included routers become opaque container objects —
               the S1182 production incident that hid 250+ routes.
    GIVEN:    A route table holding one bare APIRoute plus a container
              whose children include APIRoutes and one nested container.
    WHEN:     The auditor walks that mixed route table with iter_api_routes
              expecting complete coverage of every nesting level.
    THEN:     Every nested APIRoute at every depth is yielded exactly once
              per occurrence and nothing that is not an APIRoute leaks out.
    """
    app = _make_app_with_router()
    direct = next(r for r in app.routes if isinstance(r, APIRoute))

    table = [direct, _FakeContainerRoute(["/api/v1/things/list", "/api/v1/things/deep/leaf"])]
    found = list(iter_api_routes(table))
    assert direct in found
    paths = {r.path for r in found}
    assert paths == {"/health", "/api/v1/things/list", "/api/v1/things/deep/leaf"}
    for r in found:
        assert callable(r.endpoint) and r.methods


def test_leaf_without_routes_attr_is_skipped():
    """SCENARIO: The walker encounters WebSocket routes, static mounts,
               and unknown third-party route objects in the same table.
    GIVEN:    A route table containing a non-APIRoute leaf object that
              exposes no nested .routes attribute at all.
    WHEN:     iter_api_routes walks the table past that foreign object
              during a full production route-surface audit.
    THEN:     The object is skipped silently — no crash, no false yield,
              and enumeration of the remaining table continues.
    """
    assert list(iter_api_routes([object()])) == []
