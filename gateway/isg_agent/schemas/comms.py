"""Pydantic schemas for the inter-agent communications API.

Defines the API-facing DTOs for sending messages, listing received
messages, retrieving decrypted message detail, and managing transactions.

Design notes
------------
- Payload is OMITTED from list responses (it is encrypted at rest;
  clients must call the detail endpoint to retrieve decrypted content).
- ``MessageDetail`` extends ``MessageResponse`` with a ``payload`` field
  for the one-at-a-time decrypt-and-return pattern.
- All timestamps are ISO 8601 UTC strings (passed through from SQLite
  without re-parsing to avoid timezone ambiguity).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

__all__ = [
    "MessageSend",
    "MessageResponse",
    "MessageDetail",
    "MessageList",
    "TransactionCreate",
    "TransactionResponse",
]


class MessageSend(BaseModel):
    """Request body for sending a message from the authenticated agent.

    Attributes
    ----------
    to_handle:
        The @handle of the recipient agent.
    message_type:
        One of ``"request"``, ``"response"``, ``"confirmation"``, ``"receipt"``.
    payload:
        Arbitrary JSON-serialisable dictionary — the message content.
    """

    to_handle: str = Field(
        ...,
        min_length=3,
        max_length=30,
        description="Recipient agent @handle.",
    )
    message_type: str = Field(
        ...,
        pattern="^(request|response|confirmation|receipt)$",
        description="Message type: request | response | confirmation | receipt.",
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Arbitrary JSON payload — will be encrypted before storage.",
    )


class MessageResponse(BaseModel):
    """Metadata for a single message (payload NOT included — encrypted at rest).

    Attributes
    ----------
    id:
        UUID of the message.
    from_agent:
        Handle of the sending agent.
    to_agent:
        Handle of the receiving agent.
    message_type:
        One of ``"request"``, ``"response"``, ``"confirmation"``, ``"receipt"``.
    status:
        Current delivery status: ``"sent"``, ``"delivered"``, ``"read"``, ``"expired"``.
    governance_hash:
        Optional SHA-256 governance hash covering identity + type + timestamp.
    created_at:
        ISO 8601 UTC creation timestamp.
    """

    id: str
    from_agent: str
    to_agent: str
    message_type: str
    status: str
    governance_hash: Optional[str] = None
    created_at: str


class MessageDetail(MessageResponse):
    """Full message including the decrypted payload.

    Extends :class:`MessageResponse` with the decrypted payload dict.
    Only returned by the ``GET /messages/{message_id}`` detail endpoint.

    Attributes
    ----------
    payload:
        The decrypted JSON payload as a Python dictionary.
    """

    payload: dict[str, Any]


class MessageList(BaseModel):
    """Paginated list of messages.

    Attributes
    ----------
    messages:
        List of message metadata objects (payloads excluded).
    count:
        Total number of messages returned in this response.
    """

    messages: list[MessageResponse]
    count: int


class TransactionCreate(BaseModel):
    """Request body for starting a new transaction.

    Attributes
    ----------
    to_handle:
        The @handle of the agent to transact with.
    transaction_type:
        One of ``"booking"``, ``"order"``, ``"inquiry"``, ``"purchase"``.
    payload:
        Request payload for the first step of the transaction.
    """

    to_handle: str = Field(
        ...,
        min_length=3,
        max_length=30,
        description="Target agent @handle.",
    )
    transaction_type: str = Field(
        ...,
        pattern="^(booking|order|inquiry|purchase)$",
        description="Transaction type: booking | order | inquiry | purchase.",
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Initial request payload.",
    )


class TransactionResponse(BaseModel):
    """Response for a transaction query.

    Attributes
    ----------
    transaction_id:
        The UUID of the initial request message (transaction correlation key).
    status:
        Status of the originating request message.
    messages:
        All messages belonging to this transaction in chronological order.
        Payloads are decrypted and included in each :class:`MessageDetail`.
    """

    transaction_id: str
    status: str
    messages: list[MessageDetail]
