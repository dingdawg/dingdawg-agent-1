"""API smoke tests for task management and usage tracking endpoints.

Tests cover:
- POST /api/v1/tasks/      — create task (201, 401 no auth, 422 invalid type)
- GET  /api/v1/tasks/      — list tasks (200, filters, user isolation)
- GET  /api/v1/tasks/{id}  — get task (200, 404 not found, 404 wrong user)
- PATCH /api/v1/tasks/{id} — update task (200, 400 no fields, 404 not found)
- DELETE /api/v1/tasks/{id} — cancel task (204, 404 not found)
- GET /api/v1/tasks/usage/{agent_id}          — current usage (200, zeros when none)
- GET /api/v1/tasks/usage/{agent_id}/history  — usage history (200)

Auth headers are forged via the same _create_token utility as test_api_agents.py.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-tasks-suite"
_USER_A = "user-tasks-alpha"
_USER_B = "user-tasks-beta"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "test@example.com") -> str:
    """Create a valid JWT for test requests."""
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth_headers(user_id: str) -> dict[str, str]:
    """Return Authorization Bearer headers for the given user."""
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Provide an async HTTP client with a running app lifespan.

    Sets env vars, clears the settings cache, then triggers the FastAPI
    lifespan context so that all app.state services are initialised before
    requests are made.
    """
    db_file = str(tmp_path / "test_tasks.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET

    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# POST /api/v1/tasks — create task
# ---------------------------------------------------------------------------


class TestCreateTaskEndpoint:
    """Tests for POST /api/v1/tasks."""

    @pytest.mark.asyncio
    async def test_create_task_returns_201(self, client):
        """Creating a valid task returns 201 with correct fields."""
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "task_type": "errand",
                "description": "Pick up dry cleaning",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["task_type"] == "errand"
        assert data["description"] == "Pick up dry cleaning"
        assert data["status"] == "pending"
        assert data["user_id"] == _USER_A
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_task_requires_auth(self, client):
        """Creating a task without a token returns 401."""
        resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "errand", "description": "No auth task"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_task_invalid_type_returns_422(self, client):
        """Invalid task_type returns 422."""
        resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "teleportation", "description": "Beam me up"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_task_all_valid_types(self, client):
        """All six valid task types can be created via the API."""
        for t in ["errand", "purchase", "booking", "reminder", "email", "research"]:
            resp = await client.post(
                "/api/v1/tasks",
                json={"task_type": t, "description": f"A {t} task"},
                headers=_auth_headers(_USER_A),
            )
            assert resp.status_code == 201, f"Failed for type={t}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_task_with_explicit_agent_id(self, client):
        """task_type with explicit agent_id is accepted."""
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "task_type": "research",
                "description": "Research market rates",
                "agent_id": "custom-agent-uuid-123",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["agent_id"] == "custom-agent-uuid-123"


# ---------------------------------------------------------------------------
# GET /api/v1/tasks — list tasks
# ---------------------------------------------------------------------------


class TestListTasksEndpoint:
    """Tests for GET /api/v1/tasks."""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_200(self, client):
        """List tasks returns 200 with tasks and count."""
        await client.post(
            "/api/v1/tasks",
            json={"task_type": "email", "description": "Send invoice"},
            headers=_auth_headers(_USER_A),
        )
        resp = await client.get(
            "/api/v1/tasks",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "tasks" in data
        assert "count" in data
        assert data["count"] >= 1

    @pytest.mark.asyncio
    async def test_list_tasks_requires_auth(self, client):
        """Listing tasks without a token returns 401."""
        resp = await client.get("/api/v1/tasks")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_tasks_status_filter(self, client):
        """task_status query param filters results."""
        # Create a task and immediately verify status=pending filter works
        resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "booking", "description": "Book dentist"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201

        resp = await client.get(
            "/api/v1/tasks?task_status=pending",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200
        data = resp.json()
        for task in data["tasks"]:
            assert task["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_tasks_invalid_status_returns_422(self, client):
        """Invalid task_status filter returns 422."""
        resp = await client.get(
            "/api/v1/tasks?task_status=nonexistent",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/tasks/{task_id} — get task
# ---------------------------------------------------------------------------


class TestGetTaskEndpoint:
    """Tests for GET /api/v1/tasks/{task_id}."""

    @pytest.mark.asyncio
    async def test_get_task_returns_200(self, client):
        """Get task returns 200 with task data."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "reminder", "description": "Call mom"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/tasks/{task_id}",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == task_id
        assert data["description"] == "Call mom"

    @pytest.mark.asyncio
    async def test_get_task_not_found_returns_404(self, client):
        """Get task with unknown ID returns 404."""
        resp = await client.get(
            "/api/v1/tasks/ghost-task-id-00000",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_wrong_user_returns_404(self, client):
        """Get task owned by another user returns 404 (not 403)."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "errand", "description": "User A task"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/tasks/{task_id}",
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/tasks/{task_id} — update task
# ---------------------------------------------------------------------------


class TestUpdateTaskEndpoint:
    """Tests for PATCH /api/v1/tasks/{task_id}."""

    @pytest.mark.asyncio
    async def test_update_task_status_returns_200(self, client):
        """Updating task status returns 200 with updated data."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "purchase", "description": "Buy laptop"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"status": "in_progress"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_task_no_fields_returns_400(self, client):
        """Updating with no fields returns 400."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "errand", "description": "Empty update"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/tasks/{task_id}",
            json={},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_task_not_found_returns_404(self, client):
        """Updating a non-existent task returns 404."""
        resp = await client.patch(
            "/api/v1/tasks/ghost-task-xxxx",
            json={"status": "cancelled"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_task_wrong_user_returns_404(self, client):
        """Updating another user's task returns 404."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "email", "description": "Owner A email"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"status": "cancelled"},
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/tasks/{task_id} — cancel task
# ---------------------------------------------------------------------------


class TestCancelTaskEndpoint:
    """Tests for DELETE /api/v1/tasks/{task_id}."""

    @pytest.mark.asyncio
    async def test_cancel_task_returns_204(self, client):
        """Cancelling a task returns 204 No Content."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "research", "description": "Analyse competitors"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/tasks/{task_id}",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_cancel_task_verifies_ownership(self, client):
        """Cancelling another user's task returns 404."""
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "errand", "description": "A task"},
            headers=_auth_headers(_USER_A),
        )
        task_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/tasks/{task_id}",
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_task_not_found_returns_404(self, client):
        """Cancelling a non-existent task returns 404."""
        resp = await client.delete(
            "/api/v1/tasks/no-such-task-99",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/tasks/usage/{agent_id} — current usage
# ---------------------------------------------------------------------------


class TestUsageEndpoints:
    """Tests for usage endpoints."""

    @pytest.mark.asyncio
    async def test_get_current_usage_returns_200(self, client):
        """Current usage returns 200 with zeroed response when no data."""
        resp = await client.get(
            "/api/v1/tasks/usage/agent-with-no-data",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["agent_id"] == "agent-with-no-data"
        assert data["llm_tokens"] == 0
        assert data["tasks_completed"] == 0

    @pytest.mark.asyncio
    async def test_get_current_usage_requires_auth(self, client):
        """Usage endpoint requires authentication."""
        resp = await client.get("/api/v1/tasks/usage/some-agent")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_usage_history_returns_200(self, client):
        """Usage history returns 200 with empty list when no data."""
        resp = await client.get(
            "/api/v1/tasks/usage/agent-empty/history",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["agent_id"] == "agent-empty"
        assert data["periods"] == []
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_get_usage_history_invalid_limit_returns_422(self, client):
        """Usage history with limit=0 returns 422."""
        resp = await client.get(
            "/api/v1/tasks/usage/any-agent/history?limit=0",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422
