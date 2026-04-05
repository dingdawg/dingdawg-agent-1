"""Tests for isg_agent.comms.transaction.TransactionManager.

All tests use in-memory SQLite.  Each test creates its own TransactionManager
to prevent state bleed.
"""

from __future__ import annotations

import pytest

from isg_agent.comms.encryption import generate_key
from isg_agent.comms.transaction import TransactionManager


class TestCreateTransaction:
    """Tests for TransactionManager.create_transaction."""

    async def test_create_transaction(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()
            txn_id = await mgr.create_transaction(
                from_handle="alice",
                to_handle="bobs-pizza",
                transaction_type="order",
                request_payload={"items": ["margherita"]},
                encryption_key=key,
            )
            assert isinstance(txn_id, str)
            assert len(txn_id) == 36  # UUID

            # The request message must exist in the DB
            record = await mgr.protocol.get_message(txn_id)
            assert record is not None
            assert record["message_type"] == "request"
            assert record["from_agent"] == "alice"
            assert record["to_agent"] == "bobs-pizza"
        finally:
            await mgr.close()

    async def test_create_transaction_invalid_type_raises(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            with pytest.raises(ValueError, match="transaction_type"):
                await mgr.create_transaction(
                    from_handle="a",
                    to_handle="b",
                    transaction_type="invalid",
                    request_payload={},
                    encryption_key=generate_key(),
                )
        finally:
            await mgr.close()

    async def test_create_transaction_payload_is_encrypted(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()
            txn_id = await mgr.create_transaction(
                from_handle="alice",
                to_handle="bob",
                transaction_type="inquiry",
                request_payload={"question": "do you deliver?"},
                encryption_key=key,
            )
            record = await mgr.protocol.get_message(txn_id)
            assert record is not None
            # Plaintext must not appear in stored ciphertext
            assert "do you deliver" not in record["payload_encrypted"]
        finally:
            await mgr.close()


class TestFullTransactionLifecycle:
    """Integration test: full request → response → confirmation → receipt flow."""

    async def test_full_transaction_lifecycle(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()

            # Step 1: request
            txn_id = await mgr.create_transaction(
                from_handle="customer",
                to_handle="restaurant",
                transaction_type="order",
                request_payload={"pizza": "pepperoni", "size": "large"},
                encryption_key=key,
            )
            assert txn_id

            # Step 2: response
            resp_id = await mgr.respond_to_transaction(
                transaction_id=txn_id,
                response_payload={"accepted": True, "eta_minutes": 30},
                encryption_key=key,
            )
            assert resp_id
            assert resp_id != txn_id

            # Step 3: confirmation
            conf_id = await mgr.confirm_transaction(
                transaction_id=txn_id,
                confirmation_payload={"confirmed": True, "payment": "card"},
                encryption_key=key,
            )
            assert conf_id
            assert conf_id != resp_id

            # Step 4: receipt
            receipt_id = await mgr.complete_transaction(
                transaction_id=txn_id,
                receipt_payload={"order_ref": "ORD-001", "total_cents": 2499},
                encryption_key=key,
            )
            assert receipt_id
            assert receipt_id != conf_id

            # Verify original request is now "read"
            original = await mgr.protocol.get_message(txn_id)
            assert original is not None
            assert original["status"] == "read"
        finally:
            await mgr.close()

    async def test_respond_to_nonexistent_transaction_raises(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            with pytest.raises(KeyError):
                await mgr.respond_to_transaction(
                    transaction_id="no-such-txn",
                    response_payload={"ok": True},
                    encryption_key=generate_key(),
                )
        finally:
            await mgr.close()

    async def test_confirm_nonexistent_transaction_raises(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            with pytest.raises(KeyError):
                await mgr.confirm_transaction(
                    transaction_id="no-such-txn",
                    confirmation_payload={},
                    encryption_key=generate_key(),
                )
        finally:
            await mgr.close()

    async def test_complete_nonexistent_transaction_raises(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            with pytest.raises(KeyError):
                await mgr.complete_transaction(
                    transaction_id="no-such-txn",
                    receipt_payload={},
                    encryption_key=generate_key(),
                )
        finally:
            await mgr.close()


class TestGetTransactionHistory:
    """Tests for TransactionManager.get_transaction_history."""

    async def test_get_transaction_history(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()
            txn_id = await mgr.create_transaction(
                from_handle="buyer",
                to_handle="seller",
                transaction_type="purchase",
                request_payload={"item": "book"},
                encryption_key=key,
            )
            await mgr.respond_to_transaction(
                txn_id, {"available": True}, key
            )

            history = await mgr.get_transaction_history(txn_id, key)
            assert len(history) >= 1  # At minimum the request
            # First entry is always the request
            assert history[0]["message_type"] == "request"
        finally:
            await mgr.close()

    async def test_get_transaction_history_not_found_raises(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            with pytest.raises(KeyError):
                await mgr.get_transaction_history("ghost-txn", generate_key())
        finally:
            await mgr.close()

    async def test_get_transaction_history_has_payloads(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()
            txn_id = await mgr.create_transaction(
                from_handle="buyer",
                to_handle="seller",
                transaction_type="booking",
                request_payload={"date": "2026-03-01", "party_size": 4},
                encryption_key=key,
            )

            history = await mgr.get_transaction_history(txn_id, key)
            assert len(history) == 1
            first = history[0]
            assert "payload" in first
            assert first["payload"]["date"] == "2026-03-01"
        finally:
            await mgr.close()


class TestTransactionWithEncryption:
    """Tests that encryption is properly applied across transaction steps."""

    async def test_transaction_with_encryption(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()

            txn_id = await mgr.create_transaction(
                from_handle="userA",
                to_handle="userB",
                transaction_type="order",
                request_payload={"order_secret": "XYZ-TOP-SECRET"},
                encryption_key=key,
            )

            resp_id = await mgr.respond_to_transaction(
                txn_id,
                {"status": "accepted"},
                key,
            )

            # Retrieve raw DB records — secrets must not appear
            req_record = await mgr.protocol.get_message(txn_id)
            resp_record = await mgr.protocol.get_message(resp_id)

            assert req_record is not None
            assert "XYZ-TOP-SECRET" not in req_record["payload_encrypted"]

            assert resp_record is not None
            # Both sides decrypt correctly with the same key
            req_payload = await mgr.protocol.decrypt_payload(txn_id, key)
            resp_payload = await mgr.protocol.decrypt_payload(resp_id, key)

            assert req_payload["order_secret"] == "XYZ-TOP-SECRET"
            assert resp_payload["status"] == "accepted"
        finally:
            await mgr.close()

    async def test_all_transaction_types_valid(self) -> None:
        mgr = TransactionManager(db_path=":memory:")
        try:
            key = generate_key()
            for txn_type in ("booking", "order", "inquiry", "purchase"):
                txn_id = await mgr.create_transaction(
                    from_handle="a",
                    to_handle="b",
                    transaction_type=txn_type,
                    request_payload={"type": txn_type},
                    encryption_key=key,
                )
                record = await mgr.protocol.get_message(txn_id)
                assert record is not None
        finally:
            await mgr.close()
