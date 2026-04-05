"""Tests for isg_agent.api.websocket -- WebSocket handler + ConnectionManager.

Covers:
- MessageType enum (all values present, string enum)
- BridgeConnection dataclass (defaults, field assignment)
- ConnectionManager (connect, disconnect, send_message, broadcast, properties)
- websocket_handler (auth, message routing, error handling, heartbeat)
- Edge cases (invalid JSON, unknown message types, empty content)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from isg_agent.api.websocket import (
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    BridgeConnection,
    ConnectionManager,
    MessageType,
    websocket_handler,
)


# ===========================================================================
# MessageType Enum Tests
# ===========================================================================


class TestMessageType:
    """Tests for the MessageType string enum."""

    def test_all_types_present(self) -> None:
        """All expected message types exist."""
        expected = {
            "CHAT_MESSAGE",
            "SYSTEM_EVENT",
            "TYPING_INDICATOR",
            "ERROR",
            "PING",
            "PONG",
            "AUTH",
            "AUTH_OK",
            "AUTH_FAIL",
        }
        actual = {mt.name for mt in MessageType}
        assert actual == expected

    def test_values_are_lowercase(self) -> None:
        """Enum values are snake_case strings."""
        for mt in MessageType:
            assert mt.value == mt.value.lower()
            assert isinstance(mt.value, str)

    def test_chat_message_value(self) -> None:
        """CHAT_MESSAGE has the correct value."""
        assert MessageType.CHAT_MESSAGE.value == "chat_message"

    def test_is_string_enum(self) -> None:
        """MessageType members are strings."""
        assert isinstance(MessageType.PING, str)
        assert MessageType.PING == "ping"


# ===========================================================================
# BridgeConnection Tests
# ===========================================================================


class TestBridgeConnection:
    """Tests for the BridgeConnection dataclass."""

    def test_defaults(self) -> None:
        """BridgeConnection has sensible defaults."""
        ws = MagicMock()
        conn = BridgeConnection(connection_id="conn-1", websocket=ws)
        assert conn.connection_id == "conn-1"
        assert conn.user_id == ""
        assert conn.last_ping == 0.0
        assert conn.authenticated is False

    def test_authenticated_with_user_id(self) -> None:
        """Connection with user_id can be marked authenticated."""
        ws = MagicMock()
        conn = BridgeConnection(
            connection_id="conn-1",
            websocket=ws,
            user_id="user-123",
            authenticated=True,
        )
        assert conn.authenticated is True
        assert conn.user_id == "user-123"

    def test_connected_at_is_monotonic(self) -> None:
        """connected_at uses time.monotonic for elapsed tracking."""
        ws = MagicMock()
        before = time.monotonic()
        conn = BridgeConnection(connection_id="conn-1", websocket=ws)
        after = time.monotonic()
        assert before <= conn.connected_at <= after

    def test_last_ping_default_zero(self) -> None:
        """last_ping starts at 0.0 (no ping sent yet)."""
        ws = MagicMock()
        conn = BridgeConnection(connection_id="conn-1", websocket=ws)
        assert conn.last_ping == 0.0

    def test_fields_are_mutable(self) -> None:
        """BridgeConnection fields can be updated (not frozen)."""
        ws = MagicMock()
        conn = BridgeConnection(connection_id="conn-1", websocket=ws)
        conn.last_ping = 100.0
        conn.authenticated = True
        conn.user_id = "changed"
        assert conn.last_ping == 100.0
        assert conn.authenticated is True
        assert conn.user_id == "changed"


# ===========================================================================
# ConnectionManager Tests
# ===========================================================================


class TestConnectionManager:
    """Tests for the ConnectionManager class."""

    @pytest.fixture
    def manager(self) -> ConnectionManager:
        """Create a fresh ConnectionManager."""
        return ConnectionManager()

    def _make_ws(self) -> MagicMock:
        """Create a mock WebSocket that supports accept()."""
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        ws.client_state = MagicMock()
        ws.client_state.__eq__ = lambda self, other: False
        return ws

    async def test_connect_accepts_websocket(self, manager: ConnectionManager) -> None:
        """connect() calls websocket.accept()."""
        ws = self._make_ws()
        conn = await manager.connect(ws)
        ws.accept.assert_awaited_once()
        assert conn.connection_id
        assert manager.active_count == 1

    async def test_connect_with_user_id(self, manager: ConnectionManager) -> None:
        """connect() with user_id marks connection as authenticated."""
        ws = self._make_ws()
        conn = await manager.connect(ws, user_id="user-42")
        assert conn.user_id == "user-42"
        assert conn.authenticated is True

    async def test_connect_without_user_id_unauthenticated(
        self, manager: ConnectionManager
    ) -> None:
        """connect() without user_id leaves connection unauthenticated."""
        ws = self._make_ws()
        conn = await manager.connect(ws, user_id="")
        assert conn.authenticated is False

    async def test_disconnect_removes_connection(
        self, manager: ConnectionManager
    ) -> None:
        """disconnect() removes the connection from tracking."""
        ws = self._make_ws()
        conn = await manager.connect(ws)
        assert manager.active_count == 1
        await manager.disconnect(conn.connection_id)
        assert manager.active_count == 0

    async def test_disconnect_unknown_is_safe(
        self, manager: ConnectionManager
    ) -> None:
        """disconnect() with unknown ID does not raise."""
        await manager.disconnect("nonexistent")
        assert manager.active_count == 0

    async def test_send_message_success(self, manager: ConnectionManager) -> None:
        """send_message() returns True and sends JSON payload."""
        ws = self._make_ws()
        conn = await manager.connect(ws)
        result = await manager.send_message(
            conn.connection_id,
            MessageType.CHAT_MESSAGE,
            {"content": "hello"},
        )
        assert result is True
        ws.send_json.assert_awaited_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "chat_message"
        assert payload["data"]["content"] == "hello"
        assert "timestamp" in payload

    async def test_send_message_unknown_connection(
        self, manager: ConnectionManager
    ) -> None:
        """send_message() returns False for unknown connection ID."""
        result = await manager.send_message(
            "nonexistent",
            MessageType.ERROR,
            {"error": "test"},
        )
        assert result is False

    async def test_send_message_handles_send_failure(
        self, manager: ConnectionManager
    ) -> None:
        """send_message() disconnects client on send failure and returns False."""
        ws = self._make_ws()
        ws.send_json = AsyncMock(side_effect=ConnectionError("broken"))
        conn = await manager.connect(ws)
        result = await manager.send_message(
            conn.connection_id,
            MessageType.ERROR,
            {"error": "test"},
        )
        assert result is False
        assert manager.active_count == 0

    async def test_broadcast_sends_to_all(self, manager: ConnectionManager) -> None:
        """broadcast() sends to all connected clients."""
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        await manager.connect(ws1)
        await manager.connect(ws2)

        count = await manager.broadcast(
            MessageType.SYSTEM_EVENT,
            {"event": "test"},
        )
        assert count == 2
        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()

    async def test_broadcast_excludes_connections(
        self, manager: ConnectionManager
    ) -> None:
        """broadcast() respects the exclude set."""
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        conn1 = await manager.connect(ws1)
        conn2 = await manager.connect(ws2)

        count = await manager.broadcast(
            MessageType.TYPING_INDICATOR,
            {"typing": True},
            exclude={conn1.connection_id},
        )
        assert count == 1
        ws1.send_json.assert_not_awaited()
        ws2.send_json.assert_awaited_once()

    async def test_broadcast_empty_manager(self, manager: ConnectionManager) -> None:
        """broadcast() with no connections returns 0."""
        count = await manager.broadcast(
            MessageType.SYSTEM_EVENT, {"event": "test"}
        )
        assert count == 0

    async def test_get_connection_returns_connection(
        self, manager: ConnectionManager
    ) -> None:
        """get_connection() returns the BridgeConnection by ID."""
        ws = self._make_ws()
        conn = await manager.connect(ws)
        result = manager.get_connection(conn.connection_id)
        assert result is conn

    async def test_get_connection_unknown_returns_none(
        self, manager: ConnectionManager
    ) -> None:
        """get_connection() returns None for unknown ID."""
        assert manager.get_connection("nope") is None

    async def test_get_connections_for_user(
        self, manager: ConnectionManager
    ) -> None:
        """get_connections_for_user() filters by user_id."""
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        ws3 = self._make_ws()
        await manager.connect(ws1, user_id="alice")
        await manager.connect(ws2, user_id="bob")
        await manager.connect(ws3, user_id="alice")

        alice_conns = manager.get_connections_for_user("alice")
        assert len(alice_conns) == 2
        assert all(c.user_id == "alice" for c in alice_conns)

    async def test_active_count_property(self, manager: ConnectionManager) -> None:
        """active_count reflects the number of tracked connections."""
        assert manager.active_count == 0
        ws = self._make_ws()
        conn = await manager.connect(ws)
        assert manager.active_count == 1
        await manager.disconnect(conn.connection_id)
        assert manager.active_count == 0

    async def test_connection_ids_property(self, manager: ConnectionManager) -> None:
        """connection_ids returns a list of all active connection IDs."""
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        conn1 = await manager.connect(ws1)
        conn2 = await manager.connect(ws2)
        ids = manager.connection_ids
        assert set(ids) == {conn1.connection_id, conn2.connection_id}


# ===========================================================================
# Constants Tests
# ===========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_heartbeat_interval_positive(self) -> None:
        """HEARTBEAT_INTERVAL is a positive number."""
        assert HEARTBEAT_INTERVAL > 0
        assert isinstance(HEARTBEAT_INTERVAL, float)

    def test_heartbeat_timeout_positive(self) -> None:
        """HEARTBEAT_TIMEOUT is a positive number."""
        assert HEARTBEAT_TIMEOUT > 0
        assert isinstance(HEARTBEAT_TIMEOUT, float)

    def test_timeout_less_than_interval(self) -> None:
        """HEARTBEAT_TIMEOUT should be less than HEARTBEAT_INTERVAL."""
        assert HEARTBEAT_TIMEOUT < HEARTBEAT_INTERVAL


# ===========================================================================
# WebSocket Handler Integration Tests
# ===========================================================================


class TestWebsocketHandler:
    """Integration tests for the websocket_handler function."""

    def _make_websocket(
        self,
        token: str = "",
        messages: list[str] | None = None,
    ) -> MagicMock:
        """Create a mock WebSocket for handler testing.

        Parameters
        ----------
        token:
            Token to return from query_params.get("token", ...).
        messages:
            List of raw text messages the websocket will yield.
            After all messages are consumed, WebSocketDisconnect is raised.
        """
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        ws.client_state = MagicMock()

        # Query params
        ws.query_params = {"token": token} if token else {}

        # App state
        ws.app = MagicMock()
        ws.app.state = MagicMock(spec=[])

        # receive_text returns messages then raises WebSocketDisconnect
        msg_list = list(messages or [])

        async def _receive_text() -> str:
            if msg_list:
                return msg_list.pop(0)
            raise WebSocketDisconnect(code=1000)

        ws.receive_text = AsyncMock(side_effect=_receive_text)

        return ws

    async def test_handler_accepts_connection(self) -> None:
        """websocket_handler accepts the WebSocket connection."""
        ws = self._make_websocket()
        await websocket_handler(ws)
        ws.accept.assert_awaited_once()

    async def test_handler_sends_auth_fail_without_token(self) -> None:
        """Handler sends AUTH_FAIL when no token is provided."""
        ws = self._make_websocket()
        await websocket_handler(ws)

        # Collect all sent messages
        sent = [call[0][0] for call in ws.send_json.call_args_list]
        auth_msgs = [m for m in sent if m.get("type") == "auth_fail"]
        assert len(auth_msgs) >= 1
        assert auth_msgs[0]["data"]["reason"] == "No valid token provided"

    async def test_handler_routes_chat_message_echo(self) -> None:
        """Without runtime, chat messages are echoed back."""
        msg = json.dumps({
            "type": "chat_message",
            "data": {"content": "Hello test", "session_id": "s1"},
        })
        ws = self._make_websocket(messages=[msg])
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        chat_msgs = [m for m in sent if m.get("type") == "chat_message"]
        assert len(chat_msgs) >= 1
        assert "Echo: Hello test" in chat_msgs[0]["data"]["content"]

    async def test_handler_rejects_empty_chat_content(self) -> None:
        """Empty chat message content triggers an error response."""
        msg = json.dumps({
            "type": "chat_message",
            "data": {"content": "", "session_id": "s1"},
        })
        ws = self._make_websocket(messages=[msg])
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        error_msgs = [m for m in sent if m.get("type") == "error"]
        assert len(error_msgs) >= 1
        assert "content is required" in error_msgs[0]["data"]["error"]

    async def test_handler_handles_invalid_json(self) -> None:
        """Invalid JSON triggers an error message, not a crash."""
        ws = self._make_websocket(messages=["not valid json{{{"])
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        error_msgs = [m for m in sent if m.get("type") == "error"]
        assert len(error_msgs) >= 1
        assert "Invalid JSON" in error_msgs[0]["data"]["error"]

    async def test_handler_handles_unknown_message_type(self) -> None:
        """Unknown message types produce an error response."""
        msg = json.dumps({"type": "unknown_type_xyz", "data": {}})
        ws = self._make_websocket(messages=[msg])
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        error_msgs = [m for m in sent if m.get("type") == "error"]
        assert len(error_msgs) >= 1
        assert "Unknown message type" in error_msgs[0]["data"]["error"]

    async def test_handler_pong_is_silently_consumed(self) -> None:
        """Pong messages are consumed without sending a response."""
        msg = json.dumps({"type": "pong", "data": {}})
        ws = self._make_websocket(messages=[msg])
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        # Only auth_fail should be sent (no token), no extra messages for pong
        non_auth = [m for m in sent if m.get("type") not in ("auth_fail",)]
        # Pong should NOT generate any response (it's just a heartbeat ack)
        assert all("pong" not in str(m.get("type", "")) for m in non_auth)

    async def test_handler_typing_indicator_broadcast(self) -> None:
        """Typing indicators are broadcast to other connections."""
        msg = json.dumps({"type": "typing_indicator", "data": {"typing": True}})
        ws = self._make_websocket(messages=[msg])

        # The handler creates a ConnectionManager on app.state if not present.
        # Since this is a single connection, broadcast to others sends to 0.
        # We just verify it doesn't crash and processes normally.
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        # No error messages should be generated
        error_msgs = [m for m in sent if m.get("type") == "error"]
        assert len(error_msgs) == 0

    async def test_handler_cancels_heartbeat_on_disconnect(self) -> None:
        """Handler cancels the heartbeat task when client disconnects."""
        ws = self._make_websocket()  # No messages = immediate disconnect
        await websocket_handler(ws)
        # If heartbeat wasn't properly cancelled, we'd get a hanging task
        # The test completing without timeout proves cleanup works

    async def test_handler_creates_manager_on_state(self) -> None:
        """Handler creates a ConnectionManager on app.state if missing."""
        ws = self._make_websocket()
        # app.state has no ws_manager attribute
        assert not hasattr(ws.app.state, "ws_manager")
        await websocket_handler(ws)
        # After handler runs, ws_manager should be set
        assert hasattr(ws.app.state, "ws_manager")
        assert isinstance(ws.app.state.ws_manager, ConnectionManager)

    async def test_handler_multiple_messages(self) -> None:
        """Handler processes multiple messages in sequence."""
        messages = [
            json.dumps({"type": "chat_message", "data": {"content": "first", "session_id": "s1"}}),
            json.dumps({"type": "chat_message", "data": {"content": "second", "session_id": "s1"}}),
        ]
        ws = self._make_websocket(messages=messages)
        await websocket_handler(ws)

        sent = [call[0][0] for call in ws.send_json.call_args_list]
        chat_msgs = [m for m in sent if m.get("type") == "chat_message"]
        assert len(chat_msgs) >= 2
        contents = [m["data"]["content"] for m in chat_msgs]
        assert "Echo: first" in contents[0]
        assert "Echo: second" in contents[1]
