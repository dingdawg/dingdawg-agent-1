"""WebSocket handler for real-time communication.

Manages WebSocket connections from clients, handles authentication
via token query parameter, routes messages through the agent runtime,
and provides heartbeat ping/pong for connection health monitoring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

__all__ = [
    "BridgeConnection",
    "ConnectionManager",
    "MessageType",
    "websocket_handler",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants and enums
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL: float = 30.0  # seconds between pings
HEARTBEAT_TIMEOUT: float = 10.0   # seconds to wait for pong


class MessageType(str, Enum):
    """WebSocket message types."""

    CHAT_MESSAGE = "chat_message"
    SYSTEM_EVENT = "system_event"
    TYPING_INDICATOR = "typing_indicator"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    AUTH = "auth"
    AUTH_OK = "auth_ok"
    AUTH_FAIL = "auth_fail"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BridgeConnection:
    """A tracked WebSocket connection.

    Attributes
    ----------
    connection_id:
        Unique identifier for this connection.
    websocket:
        The underlying WebSocket instance.
    user_id:
        Authenticated user ID (empty if unauthenticated).
    connected_at:
        monotonic timestamp of when the connection was established.
    last_ping:
        monotonic timestamp of the last ping sent.
    authenticated:
        Whether the connection has been authenticated.
    """

    connection_id: str
    websocket: WebSocket
    user_id: str = ""
    connected_at: float = field(default_factory=time.monotonic)
    last_ping: float = 0.0
    authenticated: bool = False


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections.

    Tracks connections, handles broadcasts, and monitors heartbeats.
    Thread-safe for async access via dictionary operations.
    """

    def __init__(self) -> None:
        self._connections: dict[str, BridgeConnection] = {}

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str = "",
    ) -> BridgeConnection:
        """Accept a new WebSocket connection and track it.

        Parameters
        ----------
        websocket:
            The WebSocket to accept.
        user_id:
            The authenticated user ID.

        Returns
        -------
        BridgeConnection
            The tracked connection object.
        """
        await websocket.accept()
        connection_id = str(uuid.uuid4())

        conn = BridgeConnection(
            connection_id=connection_id,
            websocket=websocket,
            user_id=user_id,
            authenticated=bool(user_id),
        )
        self._connections[connection_id] = conn

        logger.info(
            "WebSocket connected: %s (user=%s)", connection_id, user_id or "anonymous"
        )
        return conn

    async def disconnect(self, connection_id: str) -> None:
        """Remove a connection from tracking.

        Parameters
        ----------
        connection_id:
            The connection ID to remove.
        """
        conn = self._connections.pop(connection_id, None)
        if conn is not None:
            logger.info("WebSocket disconnected: %s", connection_id)
            try:
                if conn.websocket.client_state == WebSocketState.CONNECTED:
                    await conn.websocket.close()
            except Exception:
                pass

    async def send_message(
        self,
        connection_id: str,
        message_type: MessageType,
        data: dict[str, Any],
    ) -> bool:
        """Send a typed message to a specific connection.

        Parameters
        ----------
        connection_id:
            Target connection ID.
        message_type:
            Type of message being sent.
        data:
            Message payload.

        Returns
        -------
        bool
            ``True`` if the message was sent, ``False`` if the connection
            was not found or the send failed.
        """
        conn = self._connections.get(connection_id)
        if conn is None:
            return False

        payload = {
            "type": message_type.value,
            "data": data,
            "timestamp": time.time(),
        }

        try:
            await conn.websocket.send_json(payload)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to send to %s: %s", connection_id, exc
            )
            await self.disconnect(connection_id)
            return False

    async def broadcast(
        self,
        message_type: MessageType,
        data: dict[str, Any],
        exclude: Optional[set[str]] = None,
    ) -> int:
        """Send a message to all connected clients.

        Parameters
        ----------
        message_type:
            Type of message being sent.
        data:
            Message payload.
        exclude:
            Set of connection IDs to skip.

        Returns
        -------
        int
            Number of connections that received the message.
        """
        sent_count = 0
        exclude_set = exclude or set()

        # Iterate over a snapshot to avoid modification during iteration
        connection_ids = list(self._connections.keys())
        for conn_id in connection_ids:
            if conn_id in exclude_set:
                continue
            if await self.send_message(conn_id, message_type, data):
                sent_count += 1

        return sent_count

    def get_connection(self, connection_id: str) -> Optional[BridgeConnection]:
        """Get a connection by ID."""
        return self._connections.get(connection_id)

    def get_connections_for_user(self, user_id: str) -> list[BridgeConnection]:
        """Get all connections for a specific user."""
        return [
            c for c in self._connections.values()
            if c.user_id == user_id
        ]

    @property
    def active_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    @property
    def connection_ids(self) -> list[str]:
        """List of all active connection IDs."""
        return list(self._connections.keys())


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------


def _verify_ws_token(token: str, app_state: Any) -> Optional[str]:
    """Verify a WebSocket authentication token.

    Parameters
    ----------
    token:
        JWT token string from the query parameter.
    app_state:
        FastAPI app state containing settings.

    Returns
    -------
    str or None
        The user_id from the token, or ``None`` if invalid.
    """
    settings = getattr(app_state, "settings", None)
    if settings is None:
        return None

    try:
        from isg_agent.api.routes.auth import verify_token

        payload = verify_token(token=token, secret_key=settings.secret_key)
        if payload is None:
            return None
        return str(payload.get("sub", ""))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Heartbeat task
# ---------------------------------------------------------------------------


async def _heartbeat_loop(
    manager: ConnectionManager,
    conn: BridgeConnection,
) -> None:
    """Send periodic ping messages to keep the connection alive.

    Runs until the connection is closed or an error occurs.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)

        if conn.connection_id not in manager.connection_ids:
            break

        try:
            conn.last_ping = time.monotonic()
            await manager.send_message(
                conn.connection_id,
                MessageType.PING,
                {"server_time": time.time()},
            )
        except Exception:
            break


# ---------------------------------------------------------------------------
# WebSocket endpoint handler
# ---------------------------------------------------------------------------


async def websocket_handler(websocket: WebSocket) -> None:
    """Main WebSocket endpoint handler.

    Authentication is performed via the ``token`` query parameter.
    If no token is provided, the connection is accepted but marked
    as unauthenticated.

    Message protocol:
    - ``chat_message``: Routed to the agent runtime
    - ``typing_indicator``: Forwarded to other connections
    - ``ping``/``pong``: Heartbeat management
    - ``error``: Error notifications from the server

    Parameters
    ----------
    websocket:
        The incoming WebSocket connection.
    """
    # Get or create connection manager
    manager: Optional[ConnectionManager] = getattr(
        websocket.app.state, "ws_manager", None
    )
    if manager is None:
        manager = ConnectionManager()
        websocket.app.state.ws_manager = manager

    # Authenticate via token query param
    token = websocket.query_params.get("token", "")
    user_id = ""
    if token:
        user_id = _verify_ws_token(token, websocket.app.state) or ""

    # Accept and track connection
    conn = await manager.connect(websocket, user_id=user_id)

    # Send auth result
    if user_id:
        await manager.send_message(
            conn.connection_id,
            MessageType.AUTH_OK,
            {"user_id": user_id},
        )
    else:
        await manager.send_message(
            conn.connection_id,
            MessageType.AUTH_FAIL,
            {"reason": "No valid token provided"},
        )

    # Start heartbeat in background
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(manager, conn)
    )

    try:
        while True:
            # Receive message
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            # Parse message
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_message(
                    conn.connection_id,
                    MessageType.ERROR,
                    {"error": "Invalid JSON"},
                )
                continue

            msg_type = message.get("type", "")
            msg_data = message.get("data", {})

            # Handle message types
            if msg_type == MessageType.PONG.value:
                # Pong response — update last activity
                continue

            elif msg_type == MessageType.CHAT_MESSAGE.value:
                # Route to agent runtime if available
                runtime = getattr(websocket.app.state, "runtime", None)
                content = msg_data.get("content", "")
                session_id = msg_data.get("session_id", "")

                if not content:
                    await manager.send_message(
                        conn.connection_id,
                        MessageType.ERROR,
                        {"error": "Message content is required"},
                    )
                    continue

                if runtime is not None and user_id and session_id:
                    try:
                        response = await runtime.process_message(
                            session_id=session_id,
                            user_message=content,
                            user_id=user_id,
                        )
                        await manager.send_message(
                            conn.connection_id,
                            MessageType.CHAT_MESSAGE,
                            {
                                "content": response.content,
                                "session_id": response.session_id,
                                "model_used": response.model_used,
                            },
                        )
                    except Exception as exc:
                        await manager.send_message(
                            conn.connection_id,
                            MessageType.ERROR,
                            {"error": f"Processing failed: {type(exc).__name__}"},
                        )
                else:
                    # Echo back for unauthenticated or no-runtime scenarios
                    await manager.send_message(
                        conn.connection_id,
                        MessageType.CHAT_MESSAGE,
                        {"content": f"Echo: {content}", "session_id": session_id},
                    )

            elif msg_type == MessageType.TYPING_INDICATOR.value:
                # Broadcast typing indicator to other connections
                await manager.broadcast(
                    MessageType.TYPING_INDICATOR,
                    {
                        "user_id": user_id or conn.connection_id,
                        "typing": msg_data.get("typing", True),
                    },
                    exclude={conn.connection_id},
                )

            else:
                await manager.send_message(
                    conn.connection_id,
                    MessageType.ERROR,
                    {"error": f"Unknown message type: {msg_type!r}"},
                )

    except Exception as exc:
        logger.error("WebSocket error for %s: %s", conn.connection_id, exc)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await manager.disconnect(conn.connection_id)
