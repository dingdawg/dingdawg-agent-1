"""Behavioral contract for agent self-onboarding (Wave 2, AGENT_NATIVE_EMPIRE).

The approval-layer inversion: an anonymous agent requests access, a human
approves via an emailed link, and only then does a key come into existence —
collected by the agent exactly once via its poll token. No key material is
ever stored raw; no key exists before human approval.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes import agent_onboard


class _Settings:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.public_url = "https://api.dingdawg.com"


@pytest.fixture()
def app(tmp_path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Bare app + temp DB + captured (not sent) approval emails."""
    sent: list[dict] = []

    async def _capture_email(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(agent_onboard, "_send_approval_email", _capture_email)
    test_app = FastAPI()
    test_app.state.settings = _Settings(str(tmp_path / "onboard-test.db"))
    test_app.include_router(agent_onboard.router)
    test_app.state.sent_emails = sent
    return test_app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


VALID = {"handle": "night-buyer-7", "contact_email": "owner@example.com", "purpose": "procurement agent for acme retail"}


class TestRequestBoundary:
    @pytest.mark.asyncio
    async def test_valid_request_returns_pending_with_poll_token(self, app):
        """SCENARIO: An autonomous procurement agent, acting for a business
                   owner, requests platform access at 3am with no human online.
        GIVEN:    A fresh handle, a reachable owner email, and a stated purpose.
        WHEN:     The agent POSTs the self-onboard request to the public
                  endpoint exactly as documented in llms.txt.
        THEN:     It receives 201 with request_id + poll_token + pending status,
                  and an approval email is queued to the human owner.
        """
        async with await _client(app) as c:
            r = await c.post("/api/v1/agents/self-onboard", json=VALID)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending"
        assert body["request_id"] and body["poll_token"]
        assert "api_key" not in body
        assert len(app.state.sent_emails) == 1
        assert "/approve?token=" in app.state.sent_emails[0]["html_body"]

    @pytest.mark.asyncio
    async def test_invalid_handle_rejected_422_at_boundary(self, app):
        """SCENARIO: A misconfigured agent submits a handle with illegal
                   characters scraped from a display name somewhere upstream.
        GIVEN:    A handle containing spaces and uppercase punctuation noise.
        WHEN:     The agent POSTs the malformed self-onboard request payload.
        THEN:     The boundary rejects it with 422 before any row or email
                  side effect happens anywhere in the system.
        """
        async with await _client(app) as c:
            r = await c.post(
                "/api/v1/agents/self-onboard",
                json={**VALID, "handle": "Not A Handle!!"},
            )
        assert r.status_code == 422
        assert app.state.sent_emails == []

    @pytest.mark.asyncio
    async def test_duplicate_handle_rejected_409(self, app):
        """SCENARIO: Two competing agents race to claim the same @handle
                   minutes apart during an automated onboarding sweep.
        GIVEN:    The first request already holds the handle in pending state.
        WHEN:     The second agent POSTs the identical handle for itself.
        THEN:     It receives 409 conflict and no second approval email fires.
        """
        async with await _client(app) as c:
            first = await c.post("/api/v1/agents/self-onboard", json=VALID)
            second = await c.post("/api/v1/agents/self-onboard", json=VALID)
        assert first.status_code == 201
        assert second.status_code == 409
        assert len(app.state.sent_emails) == 1


class TestApprovalAndDelivery:
    async def _request(self, c):
        r = await c.post("/api/v1/agents/self-onboard", json=VALID)
        return r.json()

    def _approval_token(self, app) -> str:
        html = app.state.sent_emails[0]["html_body"]
        return html.split("/approve?token=")[1].split('"')[0]

    @pytest.mark.asyncio
    async def test_full_flow_key_delivered_exactly_once(self, app):
        """SCENARIO: The business owner clicks the emailed approval link from
                   their phone; the waiting agent polls for its credential.
        GIVEN:    A pending request, the emailed approval token, and the
                  agent-held poll token from the original 201 response.
        WHEN:     The human approves, then the agent polls twice in a row.
        THEN:     First poll returns the dd_ key exactly once; the second poll
                  returns delivered-status with no key material present.
        """
        async with await _client(app) as c:
            body = await self._request(c)
            rid, poll = body["request_id"], body["poll_token"]
            a = await c.get(
                f"/api/v1/agents/self-onboard/{rid}/approve",
                params={"token": self._approval_token(app)},
            )
            assert a.status_code == 200
            p1 = await c.get(f"/api/v1/agents/self-onboard/{rid}", params={"poll_token": poll})
            p2 = await c.get(f"/api/v1/agents/self-onboard/{rid}", params={"poll_token": poll})
        assert p1.json()["status"] == "approved"
        assert p1.json()["api_key"].startswith("dd_")
        assert p2.json()["status"] == "delivered"
        assert "api_key" not in p2.json()

    @pytest.mark.asyncio
    async def test_wrong_tokens_rejected(self, app):
        """SCENARIO: An attacker who sniffed a request_id from logs tries to
                   approve it and to poll the credential without the tokens.
        GIVEN:    A pending request whose real tokens never left email/agent.
        WHEN:     The attacker calls approve and poll with forged token values.
        THEN:     Both attempts fail 403 and the request stays pending with no
                  key ever created for it.
        """
        async with await _client(app) as c:
            body = await self._request(c)
            rid, poll = body["request_id"], body["poll_token"]
            bad_a = await c.get(f"/api/v1/agents/self-onboard/{rid}/approve", params={"token": "forged"})
            bad_p = await c.get(f"/api/v1/agents/self-onboard/{rid}", params={"poll_token": "forged"})
            ok_p = await c.get(f"/api/v1/agents/self-onboard/{rid}", params={"poll_token": poll})
        assert bad_a.status_code == 403
        assert bad_p.status_code == 403
        assert ok_p.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_unknown_request_id_404(self, app):
        """SCENARIO: An agent retries a poll after its state store was wiped
                   and reconstructs a request_id that never existed here.
        GIVEN:    No request row matching the fabricated identifier.
        WHEN:     The agent polls status for that unknown request identifier.
        THEN:     The boundary answers 404 without leaking whether ids exist.
        """
        async with await _client(app) as c:
            r = await c.get("/api/v1/agents/self-onboard/does-not-exist", params={"poll_token": "x"})
        assert r.status_code == 404
