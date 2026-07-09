"""Co-located smoke spec for ax_discovery (module contract).

The full behavioral contract (status codes, content, deny-leak, negative
paths) lives in ``gateway/tests/test_ax_discovery.py`` — the repo's test
home. This file pins the module-level promises: it imports cleanly, exposes
exactly the two AX routes, and both are GET-only.
"""
from __future__ import annotations


def test_module_imports_and_exposes_router():
    """SCENARIO: An autonomous buyer agent (acting for a small-business owner
               shopping for a governed AI agent platform) crawls our API.
    GIVEN:    The gateway boots on Railway with ax_discovery wired in.
    WHEN:     The app factory imports the module to register its routes.
    THEN:     The import succeeds and the router + schema version exist, so
              the agent's first fetch can ever be answered at all.
    """
    from isg_agent.api.routes import ax_discovery

    assert hasattr(ax_discovery, "router")
    assert ax_discovery.AX_SCHEMA_VERSION


def test_router_registers_exactly_the_two_ax_routes_get_only():
    """SCENARIO: A security reviewer (and the tier-isolation middleware)
               audits what surface this module adds to the public API.
    GIVEN:    The AX module is included in the production app.
    WHEN:     They enumerate the routes the router registers.
    THEN:     Exactly /llms.txt and /.well-known/agents.json exist, GET-only —
              no accidental write surface was added to the public front door.
    """
    from isg_agent.api.routes.ax_discovery import router

    paths = {route.path: route.methods for route in router.routes}
    assert set(paths) == {"/llms.txt", "/.well-known/agents.json"}
    for methods in paths.values():
        assert methods == {"GET"}
