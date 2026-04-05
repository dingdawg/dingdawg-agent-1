"""Comprehensive tests for isg_agent.capabilities.cap3_conversations.ConversationEngine.

Tests every public method against a real SQLite database created in a tempfile,
following the patterns established in the rest of the Agent 1 test suite.

Coverage:
- handle_inbound: new thread created, existing thread updated, missed thread recovered
- generate_smart_reply: matching template found + usage_count incremented, no match returns default
- send_reply: message inserted, last_message_at updated, outbound_logs entry created
- detect_missed: threads older than threshold flagged, already-replied threads not flagged
- recover_missed: thread status updated to recovered
- manage_faq: add / update / delete / list all work correctly
- create_smart_reply_template: inserts correctly
- undo_last_send: deletes last outbound, creates rollback record, error on empty
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import MagicMock

import pytest

from isg_agent.capabilities.cap3_conversations import ConversationEngine
from isg_agent.capabilities.shared.db_schema import ensure_tables
from isg_agent.capabilities.shared.foundation import ChannelRouter, CommAdapterProtocol

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path() -> Generator[str, None, None]:
    """Provide a fresh, schema-initialised SQLite database path per test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    ensure_tables(path)
    yield path

    # Cleanup DB and WAL/SHM side-files
    for suffix in ("", "-wal", "-shm"):
        p = Path(path + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture()
def engine(db_path: str) -> ConversationEngine:
    """ConversationEngine with no channel_router."""
    return ConversationEngine(db_path=db_path)


@pytest.fixture()
def engine_with_router(db_path: str) -> ConversationEngine:
    """ConversationEngine wired with a mock ChannelRouter."""
    mock_comm = MagicMock(spec=CommAdapterProtocol)
    mock_comm.send_push.return_value = {"success": True}
    router = ChannelRouter(comm_adapter=mock_comm)
    return ConversationEngine(db_path=db_path, channel_router=router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_thread(db_path: str, thread_id: str) -> Dict[str, Any]:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM conversation_threads WHERE id = ?", (thread_id,)
        ).fetchone()
    return dict(row) if row else {}


def _fetch_messages(db_path: str, thread_id: str) -> list:
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM conversation_messages WHERE thread_id = ? ORDER BY sent_at ASC",
            (thread_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_outbound_logs(db_path: str, client_id: str) -> list:
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM outbound_logs WHERE client_id = ?", (client_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_rollbacks(db_path: str, entity_id: str) -> list:
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM rollbacks WHERE entity_id = ?", (entity_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def _insert_thread(
    db_path: str,
    *,
    thread_id: str,
    client_id: str,
    channel: str,
    status: str = "active",
    started_at: str,
    last_message_at: str,
    missed_at: str | None = None,
) -> None:
    with _conn(db_path) as conn:
        conn.execute(
            "INSERT INTO conversation_threads "
            "(id, client_id, channel, status, started_at, last_message_at, missed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (thread_id, client_id, channel, status, started_at, last_message_at, missed_at),
        )


def _insert_message(
    db_path: str,
    *,
    msg_id: str,
    thread_id: str,
    direction: str,
    content: str,
    sent_at: str,
) -> None:
    with _conn(db_path) as conn:
        conn.execute(
            "INSERT INTO conversation_messages (id, thread_id, direction, content, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg_id, thread_id, direction, content, sent_at),
        )


def _past_iso(hours: int) -> str:
    """Return an ISO 8601 string *hours* hours in the past (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ===========================================================================
# 1. handle_inbound
# ===========================================================================


class TestHandleInbound:
    def test_new_thread_created(self, engine: ConversationEngine, db_path: str) -> None:
        """First inbound from a client creates a new thread."""
        result = engine.handle_inbound(
            client_id="client_001", channel="sms", content="Hello there"
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["thread_created"] is True

        thread = data["thread"]
        assert thread["client_id"] == "client_001"
        assert thread["channel"] == "sms"
        assert thread["status"] == "active"
        assert thread["id"].startswith("thrd_")

        message = data["message"]
        assert message["direction"] == "inbound"
        assert message["content"] == "Hello there"
        assert message["thread_id"] == thread["id"]

        # Verify DB persistence
        db_thread = _fetch_thread(db_path, thread["id"])
        assert db_thread["client_id"] == "client_001"
        assert db_thread["status"] == "active"

        messages = _fetch_messages(db_path, thread["id"])
        assert len(messages) == 1
        assert messages[0]["direction"] == "inbound"

    def test_existing_thread_updated(self, engine: ConversationEngine, db_path: str) -> None:
        """Second inbound from same client+channel updates the existing thread."""
        # First inbound creates the thread
        first = engine.handle_inbound(
            client_id="client_002", channel="email", content="First message"
        )
        assert first["ok"] is True
        thread_id = first["data"]["thread"]["id"]

        # Second inbound should find the same thread
        second = engine.handle_inbound(
            client_id="client_002", channel="email", content="Follow up"
        )
        assert second["ok"] is True
        assert second["data"]["thread_created"] is False
        assert second["data"]["thread"]["id"] == thread_id

        messages = _fetch_messages(db_path, thread_id)
        assert len(messages) == 2
        contents = [m["content"] for m in messages]
        assert "First message" in contents
        assert "Follow up" in contents

    def test_missed_thread_promoted_to_recovered(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """Inbound on a 'missed' thread upgrades status to 'recovered'."""
        thread_id = "thrd_missed_test"
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="client_003",
            channel="chat",
            status="missed",
            started_at=_past_iso(50),
            last_message_at=_past_iso(48),
            missed_at=_past_iso(24),
        )

        result = engine.handle_inbound(
            client_id="client_003", channel="chat", content="I am back"
        )

        assert result["ok"] is True
        assert result["data"]["thread_created"] is False

        db_thread = _fetch_thread(db_path, thread_id)
        assert db_thread["status"] == "recovered"
        assert db_thread["recovered_at"] is not None

    def test_receipt_structure(self, engine: ConversationEngine) -> None:
        """Receipt in ok envelope has correct shape."""
        result = engine.handle_inbound(
            client_id="client_rcpt", channel="sms", content="ping"
        )
        receipt = result["receipt"]
        assert receipt["action_type"] == "handle_inbound"
        assert receipt["outcome"] == "executed"
        assert receipt["triggered_by"] == "client_rcpt"

    def test_different_channels_create_separate_threads(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """Same client on different channels creates separate threads."""
        r_sms = engine.handle_inbound(client_id="multi_ch", channel="sms", content="via sms")
        r_email = engine.handle_inbound(client_id="multi_ch", channel="email", content="via email")

        assert r_sms["ok"] is True
        assert r_email["ok"] is True
        assert r_sms["data"]["thread"]["id"] != r_email["data"]["thread"]["id"]
        assert r_sms["data"]["thread_created"] is True
        assert r_email["data"]["thread_created"] is True


# ===========================================================================
# 2. generate_smart_reply
# ===========================================================================


class TestGenerateSmartReply:
    def _add_template(
        self,
        db_path: str,
        *,
        template_id: str,
        trigger_pattern: str,
        response_template: str,
        category: str,
        usage_count: int = 0,
    ) -> None:
        from isg_agent.capabilities.shared.foundation import iso_now
        with _conn(db_path) as conn:
            conn.execute(
                "INSERT INTO smart_reply_templates "
                "(id, trigger_pattern, response_template, category, usage_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (template_id, trigger_pattern, response_template, category, usage_count, iso_now()),
            )

    def test_matching_template_found(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A template whose pattern matches inbound content is returned."""
        self._add_template(
            db_path,
            template_id="srt_booking_01",
            trigger_pattern="appointment",
            response_template="We would be happy to book you in!",
            category="booking",
        )

        result = engine.generate_smart_reply(
            thread_id="thrd_fake", inbound_content="I need an appointment please"
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["source"] == "template"
        assert data["template_id"] == "srt_booking_01"
        assert data["response_template"] == "We would be happy to book you in!"
        assert data["category"] == "booking"
        assert data["auto_send"] is False

    def test_usage_count_incremented(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """Matching a template increments its usage_count by 1."""
        self._add_template(
            db_path,
            template_id="srt_uc_test",
            trigger_pattern="pricing",
            response_template="Our pricing starts at $50.",
            category="pricing",
            usage_count=5,
        )

        result = engine.generate_smart_reply(
            thread_id="thrd_x", inbound_content="Can you tell me about pricing?"
        )

        assert result["ok"] is True
        # Returned suggestion shows the new count
        assert result["data"]["usage_count"] == 6

        # Verify the DB row was updated
        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT usage_count FROM smart_reply_templates WHERE id = ?",
                ("srt_uc_test",),
            ).fetchone()
        assert row["usage_count"] == 6

    def test_no_match_returns_default(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """When no template matches, a default acknowledgment is returned."""
        # No templates in DB
        result = engine.generate_smart_reply(
            thread_id="thrd_none", inbound_content="xyzzy unrecognised keyword"
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["source"] == "default"
        assert data["template_id"] is None
        assert "Thank you" in data["response_template"]
        assert data["category"] == "default_acknowledgment"
        assert data["auto_send"] is False

    def test_most_used_template_preferred(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """When multiple templates match, the one with highest usage_count wins."""
        self._add_template(
            db_path,
            template_id="srt_low",
            trigger_pattern="hello",
            response_template="Low usage reply",
            category="greeting",
            usage_count=2,
        )
        self._add_template(
            db_path,
            template_id="srt_high",
            trigger_pattern="hello",
            response_template="High usage reply",
            category="greeting",
            usage_count=20,
        )

        result = engine.generate_smart_reply(
            thread_id="thrd_multi", inbound_content="hello world"
        )

        assert result["ok"] is True
        assert result["data"]["template_id"] == "srt_high"

    def test_reply_contains_thread_id(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """The suggestion dict always carries the thread_id back."""
        result = engine.generate_smart_reply(
            thread_id="thrd_tid_check", inbound_content="anything"
        )
        assert result["data"]["thread_id"] == "thrd_tid_check"


# ===========================================================================
# 3. send_reply
# ===========================================================================


class TestSendReply:
    def _create_thread(self, engine: ConversationEngine, db_path: str) -> str:
        result = engine.handle_inbound(
            client_id="sender_client", channel="sms", content="inbound trigger"
        )
        return result["data"]["thread"]["id"]

    def test_message_inserted_as_outbound(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """send_reply inserts an outbound conversation_message."""
        thread_id = self._create_thread(engine, db_path)
        result = engine.send_reply(thread_id=thread_id, content="Hello from us!")

        assert result["ok"] is True
        msg = result["data"]["message"]
        assert msg["direction"] == "outbound"
        assert msg["content"] == "Hello from us!"
        assert msg["thread_id"] == thread_id
        assert msg["id"].startswith("msg_")

        messages = _fetch_messages(db_path, thread_id)
        outbound = [m for m in messages if m["direction"] == "outbound"]
        assert len(outbound) == 1
        assert outbound[0]["content"] == "Hello from us!"

    def test_last_message_at_updated(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """Thread last_message_at is updated after send_reply."""
        thread_id = self._create_thread(engine, db_path)
        before_thread = _fetch_thread(db_path, thread_id)

        result = engine.send_reply(thread_id=thread_id, content="Update timestamp")
        assert result["ok"] is True

        after_thread = _fetch_thread(db_path, thread_id)
        # last_message_at should be >= the original (may equal in fast tests)
        assert after_thread["last_message_at"] >= before_thread["last_message_at"]

    def test_outbound_log_entry_created(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """An outbound_logs row is created with correct client_id and channel."""
        thread_id = self._create_thread(engine, db_path)
        result = engine.send_reply(thread_id=thread_id, content="Logged reply")

        assert result["ok"] is True
        log_id = result["data"]["message"]["log_id"]

        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM outbound_logs WHERE id = ?", (log_id,)
            ).fetchone()
        assert row is not None
        assert row["client_id"] == "sender_client"
        assert row["channel"] == "sms"
        assert row["message_type"] == "reply"
        assert "Logged reply" in row["content_preview"]

    def test_thread_not_found_returns_error(self, engine: ConversationEngine) -> None:
        """send_reply on a non-existent thread_id returns an error envelope."""
        result = engine.send_reply(thread_id="thrd_nonexistent_xyz", content="Ghost reply")
        assert result["ok"] is False
        assert result["error"] != ""

    def test_delivery_status_without_router(self, engine: ConversationEngine, db_path: str) -> None:
        """Without a channel_router delivery_status shows queued=False."""
        thread_id = self._create_thread(engine, db_path)
        result = engine.send_reply(thread_id=thread_id, content="No router")
        assert result["ok"] is True
        delivery = result["data"]["delivery_status"]
        assert delivery["queued"] is False
        assert delivery["channel_router"] is False

    def test_delivery_status_with_router(
        self, engine_with_router: ConversationEngine, db_path: str
    ) -> None:
        """With a channel_router delivery_status shows queued=True."""
        # Create thread via the routed engine's db_path
        result_in = engine_with_router.handle_inbound(
            client_id="router_client", channel="chat", content="hi"
        )
        thread_id = result_in["data"]["thread"]["id"]

        result = engine_with_router.send_reply(thread_id=thread_id, content="Routed reply")
        assert result["ok"] is True
        delivery = result["data"]["delivery_status"]
        assert delivery["queued"] is True
        assert delivery["channel_router"] is True

    def test_content_truncated_in_log_preview(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """Content longer than 200 chars is truncated in outbound_logs preview."""
        thread_id = self._create_thread(engine, db_path)
        long_content = "X" * 300
        result = engine.send_reply(thread_id=thread_id, content=long_content)
        assert result["ok"] is True

        log_id = result["data"]["message"]["log_id"]
        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT content_preview FROM outbound_logs WHERE id = ?", (log_id,)
            ).fetchone()
        assert len(row["content_preview"]) == 200

    def test_receipt_rollback_available(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """send_reply receipt advertises rollback_available=True."""
        thread_id = self._create_thread(engine, db_path)
        result = engine.send_reply(thread_id=thread_id, content="Receipt check")
        assert result["receipt"]["rollback_available"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# 4. detect_missed
# ===========================================================================


class TestDetectMissed:
    def test_old_unanswered_thread_flagged(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A thread older than the threshold with no outbound reply is marked missed."""
        thread_id = "thrd_detect_01"
        old_ts = _past_iso(30)
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="cl_dm_01",
            channel="sms",
            status="active",
            started_at=old_ts,
            last_message_at=old_ts,
        )
        _insert_message(
            db_path,
            msg_id="msg_dm_in_01",
            thread_id=thread_id,
            direction="inbound",
            content="Old inbound",
            sent_at=old_ts,
        )

        missed = engine.detect_missed(hours_threshold=24)

        assert len(missed) == 1
        assert missed[0]["id"] == thread_id
        assert missed[0]["status"] == "missed"

        db_thread = _fetch_thread(db_path, thread_id)
        assert db_thread["status"] == "missed"
        assert db_thread["missed_at"] is not None

    def test_recently_active_thread_not_flagged(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A thread with inbound message within the threshold is NOT flagged."""
        thread_id = "thrd_recent_01"
        recent_ts = _past_iso(1)  # 1 hour ago — well within 24-hour threshold
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="cl_recent",
            channel="sms",
            status="active",
            started_at=recent_ts,
            last_message_at=recent_ts,
        )
        _insert_message(
            db_path,
            msg_id="msg_recent_in",
            thread_id=thread_id,
            direction="inbound",
            content="Recent message",
            sent_at=recent_ts,
        )

        missed = engine.detect_missed(hours_threshold=24)
        assert all(t["id"] != thread_id for t in missed)

        db_thread = _fetch_thread(db_path, thread_id)
        assert db_thread["status"] == "active"

    def test_already_replied_thread_not_flagged(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A thread that already has an outbound reply is NOT flagged as missed."""
        thread_id = "thrd_replied_01"
        old_ts = _past_iso(30)
        reply_ts = _past_iso(25)
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="cl_replied",
            channel="chat",
            status="active",
            started_at=old_ts,
            last_message_at=reply_ts,
        )
        _insert_message(
            db_path,
            msg_id="msg_in_replied",
            thread_id=thread_id,
            direction="inbound",
            content="Old inbound",
            sent_at=old_ts,
        )
        _insert_message(
            db_path,
            msg_id="msg_out_replied",
            thread_id=thread_id,
            direction="outbound",
            content="We replied!",
            sent_at=reply_ts,
        )

        missed = engine.detect_missed(hours_threshold=24)
        assert all(t["id"] != thread_id for t in missed)

    def test_already_missed_thread_not_re_flagged(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A thread already in 'missed' status is skipped (detect only queries 'active')."""
        thread_id = "thrd_already_missed"
        old_ts = _past_iso(50)
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="cl_already_missed",
            channel="sms",
            status="missed",  # already missed
            started_at=old_ts,
            last_message_at=old_ts,
            missed_at=_past_iso(26),
        )
        _insert_message(
            db_path,
            msg_id="msg_already_in",
            thread_id=thread_id,
            direction="inbound",
            content="Old inbound",
            sent_at=old_ts,
        )

        missed = engine.detect_missed(hours_threshold=24)
        assert all(t["id"] != thread_id for t in missed)

    def test_thread_with_no_inbound_messages_skipped(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A thread with no inbound messages is not flagged (nothing to miss)."""
        thread_id = "thrd_no_inbound"
        old_ts = _past_iso(30)
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="cl_no_msg",
            channel="sms",
            status="active",
            started_at=old_ts,
            last_message_at=old_ts,
        )
        # No messages inserted at all

        missed = engine.detect_missed(hours_threshold=24)
        assert all(t["id"] != thread_id for t in missed)

    def test_custom_threshold_respected(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A 2-hour-old thread is flagged with threshold=1 but not threshold=3."""
        thread_id = "thrd_threshold"
        ts = _past_iso(2)
        _insert_thread(
            db_path,
            thread_id=thread_id,
            client_id="cl_thresh",
            channel="sms",
            status="active",
            started_at=ts,
            last_message_at=ts,
        )
        _insert_message(
            db_path,
            msg_id="msg_thresh_in",
            thread_id=thread_id,
            direction="inbound",
            content="2hrs ago",
            sent_at=ts,
        )

        missed_narrow = engine.detect_missed(hours_threshold=1)
        assert any(t["id"] == thread_id for t in missed_narrow)

        # Reset status for the second check
        with _conn(db_path) as conn:
            conn.execute(
                "UPDATE conversation_threads SET status = 'active', missed_at = NULL WHERE id = ?",
                (thread_id,),
            )

        missed_wide = engine.detect_missed(hours_threshold=3)
        assert all(t["id"] != thread_id for t in missed_wide)


# ===========================================================================
# 5. recover_missed
# ===========================================================================


class TestRecoverMissed:
    def _create_missed_thread(self, engine: ConversationEngine, db_path: str) -> str:
        """Create an 'active' thread, flag it as missed, return its ID."""
        r = engine.handle_inbound(
            client_id="recover_client", channel="sms", content="initial"
        )
        thread_id = r["data"]["thread"]["id"]

        old_ts = _past_iso(30)
        _insert_message(
            db_path,
            msg_id="msg_rec_old",
            thread_id=thread_id,
            direction="inbound",
            content="old message",
            sent_at=old_ts,
        )
        with _conn(db_path) as conn:
            conn.execute(
                "UPDATE conversation_threads SET status = 'missed', missed_at = ? WHERE id = ?",
                (old_ts, thread_id),
            )
        return thread_id

    def test_recover_updates_status_to_recovered(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """recover_missed sets thread status to 'recovered' and stamps recovered_at."""
        thread_id = self._create_missed_thread(engine, db_path)
        result = engine.recover_missed(
            thread_id=thread_id, reply_content="Sorry for the delay!"
        )

        assert result["ok"] is True
        updated_thread = result["data"]["thread"]
        assert updated_thread["status"] == "recovered"
        assert updated_thread["recovered_at"] is not None

        db_thread = _fetch_thread(db_path, thread_id)
        assert db_thread["status"] == "recovered"

    def test_recover_sends_reply(self, engine: ConversationEngine, db_path: str) -> None:
        """recover_missed also creates an outbound message in the thread."""
        thread_id = self._create_missed_thread(engine, db_path)
        result = engine.recover_missed(
            thread_id=thread_id, reply_content="Recovery message"
        )

        assert result["ok"] is True
        messages = _fetch_messages(db_path, thread_id)
        outbound = [m for m in messages if m["direction"] == "outbound"]
        assert len(outbound) == 1
        assert outbound[0]["content"] == "Recovery message"

    def test_recover_nonexistent_thread_returns_error(
        self, engine: ConversationEngine
    ) -> None:
        """recover_missed on a missing thread_id returns an error envelope."""
        result = engine.recover_missed(
            thread_id="thrd_ghost_xyz", reply_content="Never sent"
        )
        assert result["ok"] is False
        assert result["error"] != ""

    def test_recover_receipt_shape(self, engine: ConversationEngine, db_path: str) -> None:
        """Receipt on successful recovery has expected outcome and action_type."""
        thread_id = self._create_missed_thread(engine, db_path)
        result = engine.recover_missed(thread_id=thread_id, reply_content="Back to you")
        receipt = result["receipt"]
        assert receipt["action_type"] == "recover_missed"
        assert receipt["outcome"] == "executed"
        assert receipt["rollback_available"] is True


# ===========================================================================
# 6. manage_faq
# ===========================================================================


class TestManageFaq:
    def test_add_creates_entry(self, engine: ConversationEngine, db_path: str) -> None:
        """manage_faq add inserts a new faq_entries row."""
        result = engine.manage_faq(
            action="add",
            question="What are your hours?",
            answer="We are open 9-5 Monday through Friday.",
            category="hours",
        )

        assert result["ok"] is True
        faq = result["data"]["faq"]
        assert faq["id"].startswith("faq_")
        assert faq["question"] == "What are your hours?"
        assert faq["answer"] == "We are open 9-5 Monday through Friday."
        assert faq["category"] == "hours"
        assert faq["usage_count"] == 0

        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM faq_entries WHERE id = ?", (faq["id"],)
            ).fetchone()
        assert row is not None

    def test_add_requires_question_and_answer(self, engine: ConversationEngine) -> None:
        """manage_faq add without question or answer returns an error."""
        r_no_q = engine.manage_faq(action="add", question="", answer="Some answer")
        assert r_no_q["ok"] is False
        assert "question" in r_no_q["error"].lower() or "required" in r_no_q["error"].lower()

        r_no_a = engine.manage_faq(action="add", question="Some question", answer="")
        assert r_no_a["ok"] is False

    def test_update_modifies_existing_entry(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """manage_faq update patches an existing entry."""
        add_result = engine.manage_faq(
            action="add",
            question="Original question?",
            answer="Original answer.",
            category="general",
        )
        faq_id = add_result["data"]["faq"]["id"]

        update_result = engine.manage_faq(
            action="update",
            faq_id=faq_id,
            answer="Updated answer.",
        )

        assert update_result["ok"] is True
        updated_faq = update_result["data"]["faq"]
        assert updated_faq["answer"] == "Updated answer."
        assert updated_faq["question"] == "Original question?"  # unchanged

        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT answer FROM faq_entries WHERE id = ?", (faq_id,)
            ).fetchone()
        assert row["answer"] == "Updated answer."

    def test_update_requires_faq_id(self, engine: ConversationEngine) -> None:
        """manage_faq update without faq_id returns an error."""
        result = engine.manage_faq(action="update", question="New question?")
        assert result["ok"] is False
        assert "faq_id" in result["error"].lower()

    def test_update_requires_at_least_one_field(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """manage_faq update with no patch fields returns an error."""
        add_result = engine.manage_faq(
            action="add", question="Q?", answer="A."
        )
        faq_id = add_result["data"]["faq"]["id"]

        result = engine.manage_faq(action="update", faq_id=faq_id)
        assert result["ok"] is False
        assert "No fields" in result["error"] or "fields" in result["error"].lower()

    def test_delete_removes_entry(self, engine: ConversationEngine, db_path: str) -> None:
        """manage_faq delete removes the row and returns the deleted record."""
        add_result = engine.manage_faq(
            action="add", question="Delete me?", answer="Yes."
        )
        faq_id = add_result["data"]["faq"]["id"]

        delete_result = engine.manage_faq(action="delete", faq_id=faq_id)

        assert delete_result["ok"] is True
        deleted = delete_result["data"]["deleted_faq"]
        assert deleted["id"] == faq_id

        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM faq_entries WHERE id = ?", (faq_id,)
            ).fetchone()
        assert row is None

    def test_delete_nonexistent_returns_error(self, engine: ConversationEngine) -> None:
        """manage_faq delete on missing faq_id returns an error."""
        result = engine.manage_faq(action="delete", faq_id="faq_ghost_xyz")
        assert result["ok"] is False
        assert result["error"] != ""

    def test_delete_requires_faq_id(self, engine: ConversationEngine) -> None:
        """manage_faq delete without faq_id returns an error."""
        result = engine.manage_faq(action="delete")
        assert result["ok"] is False
        assert "faq_id" in result["error"].lower()

    def test_list_returns_all_entries(self, engine: ConversationEngine, db_path: str) -> None:
        """manage_faq list returns all entries when no category filter is given."""
        engine.manage_faq(action="add", question="Q1?", answer="A1.", category="cat_a")
        engine.manage_faq(action="add", question="Q2?", answer="A2.", category="cat_b")

        result = engine.manage_faq(action="list")

        assert result["ok"] is True
        faqs = result["data"]["faqs"]
        assert result["data"]["count"] == len(faqs)
        assert len(faqs) >= 2
        questions = [f["question"] for f in faqs]
        assert "Q1?" in questions
        assert "Q2?" in questions

    def test_list_filters_by_category(self, engine: ConversationEngine, db_path: str) -> None:
        """manage_faq list with category returns only entries in that category."""
        engine.manage_faq(action="add", question="Booking Q?", answer="B.", category="booking")
        engine.manage_faq(action="add", question="Pricing Q?", answer="P.", category="pricing")

        result = engine.manage_faq(action="list", category="booking")

        assert result["ok"] is True
        faqs = result["data"]["faqs"]
        assert all(f["category"] == "booking" for f in faqs)
        categories_present = {f["category"] for f in faqs}
        assert "pricing" not in categories_present

    def test_unknown_action_returns_error(self, engine: ConversationEngine) -> None:
        """manage_faq with an unrecognised action returns an error."""
        result = engine.manage_faq(action="purge_everything")
        assert result["ok"] is False
        assert "Unknown action" in result["error"]


# ===========================================================================
# 7. create_smart_reply_template
# ===========================================================================


class TestCreateSmartReplyTemplate:
    def test_inserts_template_correctly(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """create_smart_reply_template inserts a new row and returns it."""
        result = engine.create_smart_reply_template(
            trigger_pattern="reschedule",
            response_template="Of course! Let us find another time.",
            category="scheduling",
        )

        assert result["ok"] is True
        template = result["data"]["template"]
        assert template["id"].startswith("srt_")
        assert template["trigger_pattern"] == "reschedule"
        assert template["response_template"] == "Of course! Let us find another time."
        assert template["category"] == "scheduling"
        assert template["usage_count"] == 0

        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM smart_reply_templates WHERE id = ?", (template["id"],)
            ).fetchone()
        assert row is not None
        assert row["trigger_pattern"] == "reschedule"

    def test_requires_trigger_pattern(self, engine: ConversationEngine) -> None:
        """create_smart_reply_template without trigger_pattern returns error."""
        result = engine.create_smart_reply_template(
            trigger_pattern="",
            response_template="Some reply.",
            category="misc",
        )
        assert result["ok"] is False
        assert "trigger_pattern" in result["error"].lower() or "required" in result["error"].lower()

    def test_requires_response_template(self, engine: ConversationEngine) -> None:
        """create_smart_reply_template without response_template returns error."""
        result = engine.create_smart_reply_template(
            trigger_pattern="keyword",
            response_template="",
            category="misc",
        )
        assert result["ok"] is False

    def test_template_usable_by_generate_smart_reply(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """A template created via create_smart_reply_template is matched by generate_smart_reply."""
        engine.create_smart_reply_template(
            trigger_pattern="cancel",
            response_template="We are sorry to hear that. Would you like to reschedule?",
            category="cancellation",
        )

        result = engine.generate_smart_reply(
            thread_id="thrd_srt_test",
            inbound_content="I need to cancel my appointment",
        )

        assert result["ok"] is True
        assert result["data"]["source"] == "template"
        assert result["data"]["trigger_pattern"] == "cancel"

    def test_receipt_shape(self, engine: ConversationEngine) -> None:
        """Receipt on successful create has expected action_type."""
        result = engine.create_smart_reply_template(
            trigger_pattern="pay",
            response_template="Payment is easy with us.",
            category="payment",
        )
        assert result["receipt"]["action_type"] == "create_smart_reply_template"
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# 8. undo_last_send
# ===========================================================================


class TestUndoLastSend:
    def _setup_thread_with_reply(
        self, engine: ConversationEngine, db_path: str, *, client_id: str = "undo_client"
    ) -> tuple[str, str]:
        """Create a thread, send one reply. Return (thread_id, msg_id)."""
        r_in = engine.handle_inbound(
            client_id=client_id, channel="sms", content="please help"
        )
        thread_id = r_in["data"]["thread"]["id"]
        r_out = engine.send_reply(thread_id=thread_id, content="Here is your reply.")
        msg_id = r_out["data"]["message"]["id"]
        return thread_id, msg_id

    def test_deletes_last_outbound_message(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """undo_last_send removes the most recent outbound message from the DB."""
        thread_id, msg_id = self._setup_thread_with_reply(engine, db_path)

        result = engine.undo_last_send(thread_id=thread_id)

        assert result["ok"] is True
        assert result["data"]["deleted_message"]["id"] == msg_id

        with _conn(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM conversation_messages WHERE id = ?", (msg_id,)
            ).fetchone()
        assert row is None

    def test_creates_rollback_record(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """undo_last_send writes a rollback row in the rollbacks table."""
        thread_id, msg_id = self._setup_thread_with_reply(engine, db_path)

        result = engine.undo_last_send(thread_id=thread_id)

        assert result["ok"] is True
        rollback = result["data"]["rollback_record"]
        assert rollback["entity_type"] == "conversation_message"
        assert rollback["entity_id"] == msg_id
        assert rollback["action"] == "undo_last_send"
        assert rollback["id"].startswith("rbk_")

        db_rollbacks = _fetch_rollbacks(db_path, msg_id)
        assert len(db_rollbacks) == 1
        assert db_rollbacks[0]["id"] == rollback["id"]

        # Verify previous_state_json is valid JSON containing the deleted message
        state = json.loads(db_rollbacks[0]["previous_state_json"])
        assert state["id"] == msg_id
        assert state["direction"] == "outbound"

    def test_error_on_empty_outbound(self, engine: ConversationEngine, db_path: str) -> None:
        """undo_last_send with no outbound messages returns an error envelope."""
        # Create a thread but send NO replies
        r_in = engine.handle_inbound(
            client_id="undo_empty", channel="sms", content="message"
        )
        thread_id = r_in["data"]["thread"]["id"]

        result = engine.undo_last_send(thread_id=thread_id)
        assert result["ok"] is False
        assert result["error"] != ""

    def test_error_on_nonexistent_thread(self, engine: ConversationEngine) -> None:
        """undo_last_send on a missing thread_id returns an error envelope."""
        result = engine.undo_last_send(thread_id="thrd_ghost_undo")
        assert result["ok"] is False
        assert result["error"] != ""

    def test_thread_last_message_at_reverted_to_previous(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """After undo, thread last_message_at reflects the previous message."""
        r_in = engine.handle_inbound(
            client_id="undo_ts", channel="sms", content="initial"
        )
        thread_id = r_in["data"]["thread"]["id"]

        # The inbound message timestamp becomes the expected fallback
        inbound_ts = r_in["data"]["message"]["sent_at"]

        r_out = engine.send_reply(thread_id=thread_id, content="reply to undo")
        assert r_out["ok"] is True

        engine.undo_last_send(thread_id=thread_id)

        db_thread = _fetch_thread(db_path, thread_id)
        # After undo, last_message_at should not be the outbound's timestamp;
        # it should be the inbound's or started_at
        assert db_thread["last_message_at"] <= inbound_ts or db_thread[
            "last_message_at"
        ] == db_thread["started_at"]

    def test_receipt_outcome_is_rolled_back(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """Receipt on undo_last_send has outcome='rolled_back' and rollback_available=False."""
        thread_id, _ = self._setup_thread_with_reply(engine, db_path, client_id="undo_rcpt")
        result = engine.undo_last_send(thread_id=thread_id)
        receipt = result["receipt"]
        assert receipt["action_type"] == "undo_last_send"
        assert receipt["outcome"] == "rolled_back"
        assert receipt["rollback_available"] is False

    def test_undo_only_removes_most_recent_outbound(
        self, engine: ConversationEngine, db_path: str
    ) -> None:
        """When two outbound messages exist, only the latest is deleted."""
        r_in = engine.handle_inbound(
            client_id="undo_multi", channel="sms", content="hi"
        )
        thread_id = r_in["data"]["thread"]["id"]

        r_out1 = engine.send_reply(thread_id=thread_id, content="First reply")
        r_out2 = engine.send_reply(thread_id=thread_id, content="Second reply")
        msg_id_2 = r_out2["data"]["message"]["id"]
        msg_id_1 = r_out1["data"]["message"]["id"]

        result = engine.undo_last_send(thread_id=thread_id)
        assert result["ok"] is True
        assert result["data"]["deleted_message"]["id"] == msg_id_2

        # First reply should still exist
        messages = _fetch_messages(db_path, thread_id)
        remaining_ids = [m["id"] for m in messages]
        assert msg_id_1 in remaining_ids
        assert msg_id_2 not in remaining_ids
