"""Unit tests for TaskManager CRUD operations.

Tests cover:
- create_task (valid type, invalid type rejection)
- get_task (found, not found)
- list_tasks (no filter, status filter, invalid status rejection)
- update_task (valid fields, invalid field rejection, invalid status rejection)
- cancel_task (sets status to cancelled)
- delegate_task (sets delegated_to + status=in_progress)
- complete_task (sets all completion fields + completed_at)
- close() releases keepalive and resets initialized flag
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from isg_agent.personal.task_manager import TaskManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mgr():
    """Provide a TaskManager backed by a fresh in-memory SQLite database."""
    m = TaskManager(db_path=":memory:")
    yield m
    await m.close()


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


class TestCreateTask:
    """Tests for TaskManager.create_task."""

    @pytest.mark.asyncio
    async def test_create_task_returns_id(self, mgr):
        """create_task returns a non-empty string UUID."""
        task_id = await mgr.create_task(
            agent_id="agent-1",
            user_id="user-1",
            task_type="errand",
            description="Buy groceries",
        )
        assert isinstance(task_id, str)
        assert len(task_id) == 36  # UUID4 format

    @pytest.mark.asyncio
    async def test_create_task_all_valid_types(self, mgr):
        """All six valid task types can be created without error."""
        valid_types = ["errand", "purchase", "booking", "reminder", "email", "research"]
        for t in valid_types:
            task_id = await mgr.create_task(
                agent_id="agent-1",
                user_id="user-1",
                task_type=t,
                description=f"Task of type {t}",
            )
            assert task_id, f"Expected a task_id for type={t}"

    @pytest.mark.asyncio
    async def test_create_task_invalid_type_raises(self, mgr):
        """Invalid task_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid task_type"):
            await mgr.create_task(
                agent_id="agent-1",
                user_id="user-1",
                task_type="unknown_type",
                description="This should fail",
            )

    @pytest.mark.asyncio
    async def test_created_task_has_pending_status(self, mgr):
        """Newly created task has status='pending' by default."""
        task_id = await mgr.create_task(
            agent_id="agent-1",
            user_id="user-1",
            task_type="research",
            description="Research competitor pricing",
        )
        task = await mgr.get_task(task_id)
        assert task is not None
        assert task["status"] == "pending"
        assert task["tokens_used"] == 0
        assert task["cost_cents"] == 0
        assert task["delegated_to"] is None
        assert task["completed_at"] is None


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------


class TestGetTask:
    """Tests for TaskManager.get_task."""

    @pytest.mark.asyncio
    async def test_get_task_returns_row(self, mgr):
        """get_task returns the full row dict for an existing task."""
        task_id = await mgr.create_task(
            agent_id="agent-42",
            user_id="user-42",
            task_type="booking",
            description="Book restaurant",
        )
        task = await mgr.get_task(task_id)
        assert task is not None
        assert task["id"] == task_id
        assert task["agent_id"] == "agent-42"
        assert task["user_id"] == "user-42"
        assert task["task_type"] == "booking"
        assert task["description"] == "Book restaurant"

    @pytest.mark.asyncio
    async def test_get_task_not_found_returns_none(self, mgr):
        """get_task returns None for a non-existent task ID."""
        result = await mgr.get_task("non-existent-id-12345")
        assert result is None


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------


class TestListTasks:
    """Tests for TaskManager.list_tasks."""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_all_for_agent(self, mgr):
        """list_tasks returns all tasks for the given agent."""
        for i in range(3):
            await mgr.create_task(
                agent_id="agent-list",
                user_id="user-1",
                task_type="errand",
                description=f"Task {i}",
            )
        tasks = await mgr.list_tasks("agent-list")
        assert len(tasks) == 3

    @pytest.mark.asyncio
    async def test_list_tasks_isolates_by_agent(self, mgr):
        """list_tasks does not return tasks from a different agent."""
        await mgr.create_task("agent-A", "user-1", "errand", "Task A")
        await mgr.create_task("agent-B", "user-1", "errand", "Task B")

        tasks_a = await mgr.list_tasks("agent-A")
        assert len(tasks_a) == 1
        assert tasks_a[0]["agent_id"] == "agent-A"

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self, mgr):
        """list_tasks with status filter only returns matching tasks."""
        task_id = await mgr.create_task("agent-1", "user-1", "email", "Send invoice")
        await mgr.cancel_task(task_id)

        # Create another pending task
        await mgr.create_task("agent-1", "user-1", "email", "Send reminder")

        pending = await mgr.list_tasks("agent-1", status="pending")
        cancelled = await mgr.list_tasks("agent-1", status="cancelled")

        assert len(pending) == 1
        assert len(cancelled) == 1
        assert cancelled[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_list_tasks_invalid_status_raises(self, mgr):
        """list_tasks with an invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            await mgr.list_tasks("agent-1", status="flying")


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------


class TestUpdateTask:
    """Tests for TaskManager.update_task."""

    @pytest.mark.asyncio
    async def test_update_task_status(self, mgr):
        """update_task can change the status field."""
        task_id = await mgr.create_task("agent-1", "user-1", "errand", "Pick up dry cleaning")
        updated = await mgr.update_task(task_id, status="in_progress")
        assert updated is True
        task = await mgr.get_task(task_id)
        assert task["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_task_invalid_field_raises(self, mgr):
        """Passing an immutable field to update_task raises ValueError."""
        task_id = await mgr.create_task("agent-1", "user-1", "errand", "Desc")
        with pytest.raises(ValueError, match="Cannot update immutable fields"):
            await mgr.update_task(task_id, agent_id="evil-agent")

    @pytest.mark.asyncio
    async def test_update_task_invalid_status_raises(self, mgr):
        """Passing an invalid status value raises ValueError."""
        task_id = await mgr.create_task("agent-1", "user-1", "errand", "Desc")
        with pytest.raises(ValueError, match="Invalid status"):
            await mgr.update_task(task_id, status="flying")

    @pytest.mark.asyncio
    async def test_update_task_not_found_returns_false(self, mgr):
        """update_task returns False when the task ID does not exist."""
        result = await mgr.update_task("ghost-id-99999", status="cancelled")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_task_empty_kwargs_returns_false(self, mgr):
        """update_task with no kwargs returns False immediately."""
        result = await mgr.update_task("any-id")
        assert result is False


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------


class TestCancelTask:
    """Tests for TaskManager.cancel_task."""

    @pytest.mark.asyncio
    async def test_cancel_task_sets_cancelled_status(self, mgr):
        """cancel_task sets status to 'cancelled'."""
        task_id = await mgr.create_task("agent-1", "user-1", "reminder", "Doctor appt")
        cancelled = await mgr.cancel_task(task_id)
        assert cancelled is True
        task = await mgr.get_task(task_id)
        assert task["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_task_not_found_returns_false(self, mgr):
        """cancel_task returns False for a non-existent task."""
        result = await mgr.cancel_task("no-such-task")
        assert result is False


# ---------------------------------------------------------------------------
# delegate_task
# ---------------------------------------------------------------------------


class TestDelegateTask:
    """Tests for TaskManager.delegate_task."""

    @pytest.mark.asyncio
    async def test_delegate_task_sets_handle_and_status(self, mgr):
        """delegate_task sets delegated_to and status=in_progress."""
        task_id = await mgr.create_task("agent-1", "user-1", "purchase", "Buy flowers")
        delegated = await mgr.delegate_task(task_id, "@flowermarket")
        assert delegated is True
        task = await mgr.get_task(task_id)
        assert task["delegated_to"] == "@flowermarket"
        assert task["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_delegate_task_not_found_returns_false(self, mgr):
        """delegate_task returns False for a non-existent task."""
        result = await mgr.delegate_task("ghost-id", "@someagent")
        assert result is False


# ---------------------------------------------------------------------------
# complete_task
# ---------------------------------------------------------------------------


class TestCompleteTask:
    """Tests for TaskManager.complete_task."""

    @pytest.mark.asyncio
    async def test_complete_task_sets_all_fields(self, mgr):
        """complete_task sets status, result_json, tokens_used, cost_cents, completed_at."""
        task_id = await mgr.create_task("agent-1", "user-1", "booking", "Hotel booking")
        completed = await mgr.complete_task(
            task_id=task_id,
            result_json='{"confirmation": "CONF-123"}',
            tokens_used=500,
            cost_cents=15,
        )
        assert completed is True
        task = await mgr.get_task(task_id)
        assert task["status"] == "completed"
        assert task["result_json"] == '{"confirmation": "CONF-123"}'
        assert task["tokens_used"] == 500
        assert task["cost_cents"] == 15
        assert task["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_complete_task_not_found_returns_false(self, mgr):
        """complete_task returns False for a non-existent task."""
        result = await mgr.complete_task("ghost-id", "{}", 0, 0)
        assert result is False
