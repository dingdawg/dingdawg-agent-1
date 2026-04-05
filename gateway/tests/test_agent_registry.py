"""Tests for isg_agent.agents.agent_registry."""

from __future__ import annotations

import pytest

from isg_agent.agents.agent_registry import AgentRegistry
from isg_agent.agents.agent_types import AgentType, AgentStatus


class TestCreateAgent:
    """Tests for AgentRegistry.create_agent."""

    async def test_create_personal_agent(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            agent = await reg.create_agent(
                user_id="user-1", handle="my-assistant",
                name="My Assistant", agent_type="personal",
            )
            assert agent.id
            assert agent.user_id == "user-1"
            assert agent.handle == "my-assistant"
            assert agent.agent_type == AgentType.PERSONAL
            assert agent.status == AgentStatus.ACTIVE
        finally:
            await reg.close()

    async def test_create_business_agent(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            agent = await reg.create_agent(
                user_id="user-1", handle="joes-pizza",
                name="Joes Pizza", agent_type="business",
                industry_type="restaurant",
            )
            assert agent.agent_type == AgentType.BUSINESS
            assert agent.industry_type == "restaurant"
        finally:
            await reg.close()

class TestGetAgent:
    """Tests for get_agent and get_agent_by_handle."""

    async def test_get_agent_by_id(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            created = await reg.create_agent(
                user_id="u1", handle="test-agent",
                name="Test", agent_type="personal",
            )
            fetched = await reg.get_agent(created.id)
            assert fetched is not None
            assert fetched.id == created.id
            assert fetched.handle == "test-agent"
        finally:
            await reg.close()

    async def test_get_agent_by_handle(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            created = await reg.create_agent(
                user_id="u1", handle="find-me",
                name="FindMe", agent_type="business",
            )
            fetched = await reg.get_agent_by_handle("find-me")
            assert fetched is not None
            assert fetched.id == created.id
        finally:
            await reg.close()

    async def test_get_nonexistent_returns_none(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            assert await reg.get_agent("no-such-id") is None
        finally:
            await reg.close()

class TestListAgents:
    """Tests for list_agents."""

    async def test_list_agents_by_user(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            await reg.create_agent(user_id="u1", handle="agent-a", name="A", agent_type="personal")
            await reg.create_agent(user_id="u1", handle="agent-b", name="B", agent_type="business")
            await reg.create_agent(user_id="u2", handle="agent-c", name="C", agent_type="personal")
            agents = await reg.list_agents("u1")
            assert len(agents) == 2
        finally:
            await reg.close()

    async def test_list_agents_by_type(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            await reg.create_agent(user_id="u1", handle="pa1", name="PA1", agent_type="personal")
            await reg.create_agent(user_id="u1", handle="ba1", name="BA1", agent_type="business")
            personal = await reg.list_agents("u1", agent_type="personal")
            assert len(personal) == 1
            assert personal[0].agent_type == AgentType.PERSONAL
        finally:
            await reg.close()

class TestUpdateDeleteAgent:
    """Tests for update_agent and delete_agent."""

    async def test_update_agent(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            agent = await reg.create_agent(
                user_id="u1", handle="upd-me",
                name="Old Name", agent_type="personal",
            )
            ok = await reg.update_agent(agent.id, name="New Name")
            assert ok is True
            updated = await reg.get_agent(agent.id)
            assert updated is not None
            assert updated.name == "New Name"
        finally:
            await reg.close()

    async def test_update_immutable_field_raises(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            agent = await reg.create_agent(
                user_id="u1", handle="imm-test",
                name="Test", agent_type="personal",
            )
            with pytest.raises(ValueError, match="immutable"):
                await reg.update_agent(agent.id, id="new-id")
        finally:
            await reg.close()

    async def test_delete_agent(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            agent = await reg.create_agent(
                user_id="u1", handle="del-me",
                name="Delete Me", agent_type="personal",
            )
            ok = await reg.delete_agent(agent.id)
            assert ok is True
            archived = await reg.get_agent(agent.id)
            assert archived is not None
            assert archived.status == AgentStatus.ARCHIVED
        finally:
            await reg.close()

    async def test_count_agents(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            assert await reg.count_agents("u1") == 0
            await reg.create_agent(user_id="u1", handle="cnt1", name="C1", agent_type="personal")
            await reg.create_agent(user_id="u1", handle="cnt2", name="C2", agent_type="business")
            assert await reg.count_agents("u1") == 2
        finally:
            await reg.close()

    async def test_duplicate_handle_fails(self) -> None:
        reg = AgentRegistry(db_path=":memory:")
        try:
            await reg.create_agent(user_id="u1", handle="taken", name="First", agent_type="personal")
            with pytest.raises(ValueError, match="already taken"):
                await reg.create_agent(user_id="u2", handle="taken", name="Second", agent_type="personal")
        finally:
            await reg.close()
