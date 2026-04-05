"""Tests for isg_agent.comms.agent_protocol.AgentProtocol.

All tests use in-memory SQLite databases for isolation and speed.
Each test creates its own AgentProtocol instance to prevent state bleed.
"""

from __future__ import annotations

import pytest

from isg_agent.comms.agent_protocol import AgentProtocol
from isg_agent.comms.encryption import generate_key


class TestSendMessage:
    """Tests for AgentProtocol.send_message."""

    async def test_send_message_creates_record(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            msg_id = await proto.send_message(
                from_handle="alice",
                to_handle="bob",
                message_type="request",
                payload={"action": "order_pizza"},
                encryption_key=key,
            )
            assert isinstance(msg_id, str)
            assert len(msg_id) == 36  # UUID format

            record = await proto.get_message(msg_id)
            assert record is not None
            assert record["from_agent"] == "alice"
            assert record["to_agent"] == "bob"
            assert record["message_type"] == "request"
            assert record["status"] == "sent"
        finally:
            await proto.close()

    async def test_send_message_encrypts_payload(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            payload = {"secret": "pizza order"}
            msg_id = await proto.send_message(
                from_handle="alice",
                to_handle="bob",
                message_type="request",
                payload=payload,
                encryption_key=key,
            )
            record = await proto.get_message(msg_id)
            # The stored payload must not contain the plaintext
            assert record is not None
            assert "pizza order" not in record["payload_encrypted"]
        finally:
            await proto.close()

    async def test_send_message_invalid_type_raises(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            with pytest.raises(ValueError, match="message_type"):
                await proto.send_message(
                    from_handle="a",
                    to_handle="b",
                    message_type="unknown",
                    payload={},
                    encryption_key=key,
                )
        finally:
            await proto.close()

    async def test_send_message_stores_governance_hash(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            msg_id = await proto.send_message(
                from_handle="alice",
                to_handle="bob",
                message_type="request",
                payload={},
                encryption_key=key,
                governance_hash="custom-hash-abc123",
            )
            record = await proto.get_message(msg_id)
            assert record is not None
            assert record["governance_hash"] == "custom-hash-abc123"
        finally:
            await proto.close()

    async def test_send_message_auto_computes_governance_hash(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            msg_id = await proto.send_message(
                from_handle="alice",
                to_handle="bob",
                message_type="request",
                payload={},
                encryption_key=key,
            )
            record = await proto.get_message(msg_id)
            assert record is not None
            assert record["governance_hash"] is not None
            assert len(record["governance_hash"]) == 64  # SHA-256 hex
        finally:
            await proto.close()


class TestReceiveMessages:
    """Tests for AgentProtocol.receive_messages."""

    async def test_receive_messages_for_agent(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            await proto.send_message("alice", "bob", "request", {"x": 1}, key)
            await proto.send_message("alice", "bob", "request", {"x": 2}, key)

            msgs = await proto.receive_messages("bob")
            assert len(msgs) == 2
            assert all(m["to_agent"] == "bob" for m in msgs)
        finally:
            await proto.close()

    async def test_receive_messages_empty(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            msgs = await proto.receive_messages("nobody")
            assert msgs == []
        finally:
            await proto.close()

    async def test_receive_messages_only_addressed_to_agent(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            await proto.send_message("alice", "bob", "request", {}, key)
            await proto.send_message("alice", "carol", "request", {}, key)

            bobs = await proto.receive_messages("bob")
            carols = await proto.receive_messages("carol")
            assert len(bobs) == 1
            assert len(carols) == 1
        finally:
            await proto.close()

    async def test_receive_messages_invalid_status_raises(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="status"):
                await proto.receive_messages("bob", status="invalid")
        finally:
            await proto.close()


class TestGetMessage:
    """Tests for AgentProtocol.get_message."""

    async def test_get_message_by_id(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            msg_id = await proto.send_message("a", "b", "request", {"k": "v"}, key)
            record = await proto.get_message(msg_id)
            assert record is not None
            assert record["id"] == msg_id
        finally:
            await proto.close()

    async def test_get_message_not_found(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            result = await proto.get_message("nonexistent-id")
            assert result is None
        finally:
            await proto.close()


class TestUpdateStatus:
    """Tests for AgentProtocol.update_status."""

    async def test_update_status(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            msg_id = await proto.send_message("a", "b", "request", {}, key)

            updated = await proto.update_status(msg_id, "delivered")
            assert updated is True

            record = await proto.get_message(msg_id)
            assert record is not None
            assert record["status"] == "delivered"
        finally:
            await proto.close()

    async def test_update_status_not_found(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            result = await proto.update_status("no-such-id", "read")
            assert result is False
        finally:
            await proto.close()

    async def test_update_status_invalid_raises(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="status"):
                await proto.update_status("any-id", "purple")
        finally:
            await proto.close()


class TestDecryptPayload:
    """Tests for AgentProtocol.decrypt_payload."""

    async def test_decrypt_payload(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            payload = {"order": "margherita", "qty": 2}
            msg_id = await proto.send_message("a", "b", "request", payload, key)

            decrypted = await proto.decrypt_payload(msg_id, key)
            assert decrypted["order"] == "margherita"
            assert decrypted["qty"] == 2
        finally:
            await proto.close()

    async def test_decrypt_payload_wrong_key_raises(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key1 = generate_key()
            key2 = generate_key()
            msg_id = await proto.send_message("a", "b", "request", {"x": 1}, key1)

            with pytest.raises((ValueError, Exception)):
                await proto.decrypt_payload(msg_id, key2)
        finally:
            await proto.close()

    async def test_decrypt_payload_not_found_raises(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            with pytest.raises(KeyError):
                await proto.decrypt_payload("nonexistent-id", key)
        finally:
            await proto.close()


class TestMessageTypes:
    """Tests for all four valid message types."""

    async def test_message_types_valid(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            for msg_type in ("request", "response", "confirmation", "receipt"):
                msg_id = await proto.send_message("a", "b", msg_type, {}, key)
                record = await proto.get_message(msg_id)
                assert record is not None
                assert record["message_type"] == msg_type
        finally:
            await proto.close()


class TestSendAndReceiveMultiple:
    """Integration: send multiple messages and receive them in order."""

    async def test_send_and_receive_multiple(self) -> None:
        proto = AgentProtocol(db_path=":memory:")
        try:
            key = generate_key()
            ids = []
            for i in range(3):
                msg_id = await proto.send_message(
                    "sender",
                    "receiver",
                    "request",
                    {"seq": i},
                    key,
                )
                ids.append(msg_id)

            msgs = await proto.receive_messages("receiver", limit=10)
            assert len(msgs) == 3

            # Verify each message can be decrypted
            for i, msg in enumerate(msgs):
                payload = await proto.decrypt_payload(msg["id"], key)
                assert payload["seq"] == i
        finally:
            await proto.close()
