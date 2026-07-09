"""Co-located smoke spec for agent_onboard (module contract).

Full behavioral contract lives in ``gateway/tests/test_agent_onboard.py``.
This file pins the module surface: import cleanly, expose exactly the
three self-onboarding routes, correct methods.
"""
from __future__ import annotations


def test_module_imports_and_exposes_router():
    """SCENARIO: An autonomous buyer agent discovers /api/v1/agents/self-onboard
               via llms.txt and attempts programmatic onboarding overnight.
    GIVEN:    The gateway boots on Railway with agent_onboard wired into app.py.
    WHEN:     The application factory imports this module to register its routes
              during production startup on a fresh deployment.
    THEN:     The import succeeds and the router exists, so the agent's first
              self-onboarding request can be answered at all.
    """
    from isg_agent.api.routes import agent_onboard

    assert hasattr(agent_onboard, "router")


def test_router_registers_exactly_three_routes():
    """SCENARIO: A security reviewer inventories the anonymous surface this
               module adds before it ships to the public internet.
    GIVEN:    The agent_onboard module is included in the production app.
    WHEN:     The reviewer enumerates every route and method the router
              registers as part of the pre-deploy surface reconciliation.
    THEN:     Exactly three routes exist — request (POST), status poll (GET),
              approve (GET) — and no accidental extra write surface.
    """
    from isg_agent.api.routes.agent_onboard import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert paths == {
        ("/api/v1/agents/self-onboard", ("POST",)),
        ("/api/v1/agents/self-onboard/{request_id}", ("GET",)),
        ("/api/v1/agents/self-onboard/{request_id}/approve", ("GET",)),
    }
