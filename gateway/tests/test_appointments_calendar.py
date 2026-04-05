"""Tests for Google Calendar sync in the AppointmentsSkill.

Covers:
- Schema: google_event_id column exists; init_tables is idempotent
- Schedule with Calendar connected: create_event called, google_event_id stored
- Schedule when Calendar returns no event id: appointment still saved
- Schedule when Calendar sync raises: appointment still saved (best-effort)
- Schedule when google_calendar=None: no Calendar call, works as before
- Cancel with google_event_id: delete_event called
- Cancel without google_event_id: no Calendar call
- Cancel when Calendar delete raises: cancellation still succeeds
- Reschedule with google_event_id: update_event called with new times
- Reschedule without google_event_id: no Calendar call
- Reschedule when Calendar update raises: reschedule still succeeds
- No regression: list, get, complete, unknown action all work with google_calendar=None
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
import pytest_asyncio

from isg_agent.skills.builtin.appointments import AppointmentsSkill, init_tables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_mock_calendar(
    is_connected: bool = True,
    create_event_result: dict | None = None,
    update_event_result: dict | None = None,
    delete_event_result: dict | None = None,
    create_event_side_effect: Exception | None = None,
    update_event_side_effect: Exception | None = None,
    delete_event_side_effect: Exception | None = None,
) -> AsyncMock:
    """Build a mock GoogleCalendarConnector with configurable return values."""
    mock = AsyncMock()
    mock.is_connected = AsyncMock(return_value=is_connected)

    if create_event_side_effect is not None:
        mock.create_event = AsyncMock(side_effect=create_event_side_effect)
    else:
        mock.create_event = AsyncMock(
            return_value=create_event_result or {"google_event_id": "gcal_abc123", "html_link": "https://cal.google.com/event/abc123"}
        )

    if update_event_side_effect is not None:
        mock.update_event = AsyncMock(side_effect=update_event_side_effect)
    else:
        mock.update_event = AsyncMock(
            return_value=update_event_result or {"google_event_id": "gcal_abc123", "html_link": "https://cal.google.com/event/abc123"}
        )

    if delete_event_side_effect is not None:
        mock.delete_event = AsyncMock(side_effect=delete_event_side_effect)
    else:
        mock.delete_event = AsyncMock(
            return_value=delete_event_result or {"google_event_id": "gcal_abc123", "status": "cancelled"}
        )

    return mock


async def _get_appointment(db_path: str, appt_id: str) -> dict | None:
    """Fetch a single appointment row by ID from SQLite."""
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id, agent_id, contact_name, title, start_time, status, google_event_id "
            "FROM skill_appointments WHERE id=?",
            (appt_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    cols = ["id", "agent_id", "contact_name", "title", "start_time", "status", "google_event_id"]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db() -> Path:
    """Provide a temporary SQLite database file, cleaned up after the test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        p = Path(f.name)
    yield p
    p.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Table schema tests
# ---------------------------------------------------------------------------


class TestTableSchema:
    """Verify schema initialisation and migration behaviour."""

    async def test_google_event_id_column_exists_after_init(self, tmp_db: Path) -> None:
        """google_event_id column is present in skill_appointments after init_tables."""
        await init_tables(str(tmp_db))
        async with aiosqlite.connect(str(tmp_db)) as db:
            cur = await db.execute("PRAGMA table_info(skill_appointments)")
            columns = [row[1] for row in await cur.fetchall()]
        assert "google_event_id" in columns

    async def test_init_tables_is_idempotent(self, tmp_db: Path) -> None:
        """Calling init_tables twice does not raise an error."""
        await init_tables(str(tmp_db))
        # Second call should not raise (ALTER TABLE is guarded by try/except)
        await init_tables(str(tmp_db))

    async def test_google_event_id_is_nullable(self, tmp_db: Path) -> None:
        """google_event_id column accepts NULL values (new appointments have no Calendar event)."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)
        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "schema-test-agent",
            "contact_name": "Schema Tester",
            "title": "Nullable Column Test",
            "start_time": "2026-06-01T09:00:00+00:00",
        })
        result = json.loads(result_json)
        assert "id" in result

        row = await _get_appointment(str(tmp_db), result["id"])
        assert row is not None
        assert row["google_event_id"] is None


# ---------------------------------------------------------------------------
# Schedule action — Calendar sync tests
# ---------------------------------------------------------------------------


class TestScheduleWithCalendar:
    """Tests for _schedule() with Google Calendar integration."""

    async def test_schedule_calls_create_event_when_connected(self, tmp_db: Path) -> None:
        """When Calendar is connected, create_event is called once with correct data."""
        await init_tables(str(tmp_db))
        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "test-agent",
            "contact_name": "Alice Smith",
            "contact_email": "alice@example.com",
            "title": "Haircut Appointment",
            "start_time": "2026-06-01T10:00:00+00:00",
            "end_time": "2026-06-01T10:30:00+00:00",
            "description": "Monthly haircut",
            "location": "123 Main St",
        })

        result = json.loads(result_json)
        assert result["status"] == "scheduled"
        assert "id" in result

        mock_cal.is_connected.assert_called_once_with("test-agent")
        mock_cal.create_event.assert_called_once()

        # Verify the event_data passed to create_event has expected shape
        call_args = mock_cal.create_event.call_args
        event_data = call_args[0][1]  # second positional arg
        assert event_data["title"] == "Haircut Appointment"
        assert event_data["start_time"] == "2026-06-01T10:00:00+00:00"
        assert "alice@example.com" in event_data["attendees"]

    async def test_schedule_stores_google_event_id_in_db(self, tmp_db: Path) -> None:
        """When create_event returns a google_event_id, it is persisted to SQLite."""
        await init_tables(str(tmp_db))
        mock_cal = _build_mock_calendar(
            create_event_result={"google_event_id": "gcal_xyz789", "html_link": "https://cal.google.com/xyz"}
        )
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "agent-gcal-store",
            "contact_name": "Bob Jones",
            "title": "Strategy Session",
            "start_time": "2026-06-02T14:00:00+00:00",
        })

        result = json.loads(result_json)
        row = await _get_appointment(str(tmp_db), result["id"])
        assert row is not None
        assert row["google_event_id"] == "gcal_xyz789"

    async def test_schedule_saves_appointment_when_calendar_sync_fails(self, tmp_db: Path) -> None:
        """When create_event raises an exception, the appointment is still saved (best-effort)."""
        await init_tables(str(tmp_db))
        mock_cal = _build_mock_calendar(
            create_event_side_effect=RuntimeError("Google API timeout")
        )
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "agent-fail",
            "contact_name": "Carol White",
            "title": "Meeting with failure",
            "start_time": "2026-06-03T09:00:00+00:00",
        })

        result = json.loads(result_json)
        # Appointment must be saved even though Calendar failed
        assert result["status"] == "scheduled"
        assert "id" in result

        row = await _get_appointment(str(tmp_db), result["id"])
        assert row is not None
        assert row["status"] == "scheduled"
        # google_event_id remains None since sync failed
        assert row["google_event_id"] is None

    async def test_schedule_when_calendar_not_connected_skips_create_event(self, tmp_db: Path) -> None:
        """When is_connected returns False, create_event is never called."""
        await init_tables(str(tmp_db))
        mock_cal = _build_mock_calendar(is_connected=False)
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "agent-disconnected",
            "contact_name": "Dave Brown",
            "title": "Not synced appointment",
            "start_time": "2026-06-04T11:00:00+00:00",
        })

        result = json.loads(result_json)
        assert result["status"] == "scheduled"
        mock_cal.is_connected.assert_called_once()
        mock_cal.create_event.assert_not_called()

    async def test_schedule_when_google_calendar_is_none_works_as_before(self, tmp_db: Path) -> None:
        """When google_calendar=None, scheduling works exactly as before (SQLite only)."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)

        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "agent-no-cal",
            "contact_name": "Eve Green",
            "title": "No Calendar Appointment",
            "start_time": "2026-06-05T08:00:00+00:00",
        })

        result = json.loads(result_json)
        assert result["status"] == "scheduled"
        assert "id" in result

        row = await _get_appointment(str(tmp_db), result["id"])
        assert row is not None
        assert row["google_event_id"] is None

    async def test_schedule_without_google_event_id_in_response_leaves_null(self, tmp_db: Path) -> None:
        """When create_event returns a result without google_event_id, the DB column remains NULL."""
        await init_tables(str(tmp_db))
        mock_cal = _build_mock_calendar(
            create_event_result={"html_link": "https://cal.google.com/noId"}  # No google_event_id key
        )
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "schedule",
            "agent_id": "agent-noid",
            "contact_name": "Frank Blue",
            "title": "No ID Appointment",
            "start_time": "2026-06-06T09:00:00+00:00",
        })

        result = json.loads(result_json)
        row = await _get_appointment(str(tmp_db), result["id"])
        assert row is not None
        assert row["google_event_id"] is None


# ---------------------------------------------------------------------------
# Cancel action — Calendar sync tests
# ---------------------------------------------------------------------------


class TestCancelWithCalendar:
    """Tests for _cancel() with Google Calendar integration."""

    async def _create_appointment_with_gcal_id(
        self, db_path: str, agent_id: str, google_event_id: str | None = "gcal_del_123"
    ) -> str:
        """Helper: schedule an appointment and optionally inject a google_event_id."""
        skill_no_cal = AppointmentsSkill(db_path=db_path, google_calendar=None)
        result_json = await skill_no_cal.handle({
            "action": "schedule",
            "agent_id": agent_id,
            "contact_name": "Test Contact",
            "title": "Appointment to Cancel",
            "start_time": "2026-07-01T10:00:00+00:00",
        })
        appt_id = json.loads(result_json)["id"]

        if google_event_id:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE skill_appointments SET google_event_id=? WHERE id=?",
                    (google_event_id, appt_id),
                )
                await db.commit()
        return appt_id

    async def test_cancel_with_google_event_id_calls_delete_event(self, tmp_db: Path) -> None:
        """When appointment has a google_event_id, delete_event is called on cancellation."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-cancel-cal", "gcal_del_abc"
        )

        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({"action": "cancel", "id": appt_id})
        result = json.loads(result_json)

        assert result["status"] == "cancelled"
        mock_cal.delete_event.assert_called_once_with("agent-cancel-cal", "gcal_del_abc")

    async def test_cancel_without_google_event_id_skips_delete_event(self, tmp_db: Path) -> None:
        """When appointment has no google_event_id, delete_event is never called."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-cancel-no-gcal", google_event_id=None
        )

        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({"action": "cancel", "id": appt_id})
        result = json.loads(result_json)

        assert result["status"] == "cancelled"
        mock_cal.delete_event.assert_not_called()

    async def test_cancel_succeeds_when_calendar_delete_raises(self, tmp_db: Path) -> None:
        """When delete_event raises, the appointment is still cancelled in SQLite."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-cancel-err", "gcal_del_err"
        )

        mock_cal = _build_mock_calendar(
            delete_event_side_effect=RuntimeError("Calendar API error")
        )
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({"action": "cancel", "id": appt_id})
        result = json.loads(result_json)

        assert result["status"] == "cancelled"

        # Verify DB was actually updated
        row = await _get_appointment(str(tmp_db), appt_id)
        assert row is not None
        assert row["status"] == "cancelled"

    async def test_cancel_missing_id_returns_error(self, tmp_db: Path) -> None:
        """Cancel without an id returns an error response."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)
        result = json.loads(await skill.handle({"action": "cancel"}))
        assert "error" in result

    async def test_cancel_nonexistent_id_returns_error(self, tmp_db: Path) -> None:
        """Cancel with a nonexistent id returns an error response."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)
        result = json.loads(await skill.handle({"action": "cancel", "id": "no-such-id"}))
        assert "error" in result


# ---------------------------------------------------------------------------
# Reschedule action — Calendar sync tests
# ---------------------------------------------------------------------------


class TestRescheduleWithCalendar:
    """Tests for _reschedule() with Google Calendar integration."""

    async def _create_appointment_with_gcal_id(
        self, db_path: str, agent_id: str, google_event_id: str | None = "gcal_upd_456"
    ) -> str:
        """Helper: schedule an appointment and optionally inject a google_event_id."""
        skill_no_cal = AppointmentsSkill(db_path=db_path, google_calendar=None)
        result_json = await skill_no_cal.handle({
            "action": "schedule",
            "agent_id": agent_id,
            "contact_name": "Reschedule Contact",
            "title": "Appointment to Reschedule",
            "start_time": "2026-07-10T10:00:00+00:00",
            "end_time": "2026-07-10T11:00:00+00:00",
        })
        appt_id = json.loads(result_json)["id"]

        if google_event_id:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE skill_appointments SET google_event_id=? WHERE id=?",
                    (google_event_id, appt_id),
                )
                await db.commit()
        return appt_id

    async def test_reschedule_with_google_event_id_calls_update_event(self, tmp_db: Path) -> None:
        """When appointment has a google_event_id, update_event is called with new times."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-reschedule-cal", "gcal_upd_abc"
        )

        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "reschedule",
            "id": appt_id,
            "start_time": "2026-07-10T14:00:00+00:00",
            "end_time": "2026-07-10T15:00:00+00:00",
        })
        result = json.loads(result_json)

        assert result["status"] == "rescheduled"
        mock_cal.update_event.assert_called_once()

        call_args = mock_cal.update_event.call_args
        # call_args: (agent_id, google_event_id, updates)
        assert call_args[0][0] == "agent-reschedule-cal"
        assert call_args[0][1] == "gcal_upd_abc"
        updates = call_args[0][2]
        assert updates["start_time"] == "2026-07-10T14:00:00+00:00"
        assert updates["end_time"] == "2026-07-10T15:00:00+00:00"

    async def test_reschedule_without_google_event_id_skips_update_event(self, tmp_db: Path) -> None:
        """When appointment has no google_event_id, update_event is never called."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-reschedule-no-gcal", google_event_id=None
        )

        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "reschedule",
            "id": appt_id,
            "start_time": "2026-07-10T16:00:00+00:00",
        })
        result = json.loads(result_json)

        assert result["status"] == "rescheduled"
        mock_cal.update_event.assert_not_called()

    async def test_reschedule_succeeds_when_calendar_update_raises(self, tmp_db: Path) -> None:
        """When update_event raises, the appointment is still rescheduled in SQLite."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-reschedule-err", "gcal_upd_err"
        )

        mock_cal = _build_mock_calendar(
            update_event_side_effect=RuntimeError("Calendar API unavailable")
        )
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result_json = await skill.handle({
            "action": "reschedule",
            "id": appt_id,
            "start_time": "2026-07-10T12:00:00+00:00",
        })
        result = json.loads(result_json)

        assert result["status"] == "rescheduled"

        # Verify DB was actually updated
        row = await _get_appointment(str(tmp_db), appt_id)
        assert row is not None
        assert row["status"] == "rescheduled"

    async def test_reschedule_only_start_time_calls_update_with_start_only(self, tmp_db: Path) -> None:
        """When only start_time is provided, update_event receives only start_time in updates."""
        await init_tables(str(tmp_db))
        appt_id = await self._create_appointment_with_gcal_id(
            str(tmp_db), "agent-reschedule-start-only", "gcal_start_only"
        )

        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        await skill.handle({
            "action": "reschedule",
            "id": appt_id,
            "start_time": "2026-07-10T17:00:00+00:00",
        })

        mock_cal.update_event.assert_called_once()
        updates = mock_cal.update_event.call_args[0][2]
        assert "start_time" in updates
        assert "end_time" not in updates


# ---------------------------------------------------------------------------
# No-regression tests — all actions with google_calendar=None
# ---------------------------------------------------------------------------


class TestNoRegressionWithoutCalendar:
    """Verify that all actions work correctly when google_calendar=None."""

    async def test_list_action_works_without_calendar(self, tmp_db: Path) -> None:
        """list action returns appointments when google_calendar=None."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)

        await skill.handle({
            "action": "schedule",
            "agent_id": "agent-list",
            "contact_name": "Lister",
            "title": "Scheduled Meeting",
            "start_time": "2026-08-01T09:00:00+00:00",
        })

        result = json.loads(await skill.handle({"action": "list", "agent_id": "agent-list"}))
        assert "appointments" in result
        assert len(result["appointments"]) == 1

    async def test_get_action_works_without_calendar(self, tmp_db: Path) -> None:
        """get action returns a single appointment when google_calendar=None."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)

        scheduled = json.loads(await skill.handle({
            "action": "schedule",
            "agent_id": "agent-get",
            "contact_name": "Getter",
            "title": "Meeting",
            "start_time": "2026-08-02T10:00:00+00:00",
        }))
        appt_id = scheduled["id"]

        fetched = json.loads(await skill.handle({"action": "get", "id": appt_id}))
        assert fetched["id"] == appt_id
        assert fetched["title"] == "Meeting"

    async def test_complete_action_works_without_calendar(self, tmp_db: Path) -> None:
        """complete action marks appointment as completed when google_calendar=None."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)

        scheduled = json.loads(await skill.handle({
            "action": "schedule",
            "agent_id": "agent-complete",
            "contact_name": "Completer",
            "title": "Done Meeting",
            "start_time": "2026-08-03T11:00:00+00:00",
        }))
        appt_id = scheduled["id"]

        completed = json.loads(await skill.handle({"action": "complete", "id": appt_id}))
        assert completed["status"] == "completed"

    async def test_unknown_action_returns_error_without_calendar(self, tmp_db: Path) -> None:
        """Unknown action returns an error response when google_calendar=None."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)
        result = json.loads(await skill.handle({"action": "fly_to_moon"}))
        assert "error" in result

    async def test_schedule_missing_required_fields_returns_error(self, tmp_db: Path) -> None:
        """Scheduling without required fields returns an error, even with Calendar set."""
        await init_tables(str(tmp_db))
        mock_cal = _build_mock_calendar()
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=mock_cal)

        result = json.loads(await skill.handle({
            "action": "schedule",
            "contact_name": "No Title",
            # Missing: title, start_time
        }))
        assert "error" in result
        mock_cal.create_event.assert_not_called()

    async def test_list_with_status_filter_works_without_calendar(self, tmp_db: Path) -> None:
        """list action with status filter works correctly."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)

        await skill.handle({
            "action": "schedule",
            "agent_id": "agent-filter",
            "contact_name": "Filter Test",
            "title": "Meeting A",
            "start_time": "2026-09-01T09:00:00+00:00",
        })
        sched2 = json.loads(await skill.handle({
            "action": "schedule",
            "agent_id": "agent-filter",
            "contact_name": "Filter Test 2",
            "title": "Meeting B",
            "start_time": "2026-09-02T10:00:00+00:00",
        }))
        # Cancel the second
        await skill.handle({"action": "cancel", "id": sched2["id"]})

        scheduled_list = json.loads(await skill.handle({
            "action": "list",
            "agent_id": "agent-filter",
            "status": "scheduled",
        }))
        assert len(scheduled_list["appointments"]) == 1
        assert scheduled_list["appointments"][0]["title"] == "Meeting A"

    async def test_get_nonexistent_appointment_returns_error(self, tmp_db: Path) -> None:
        """get action for a nonexistent ID returns an error response."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)
        result = json.loads(await skill.handle({"action": "get", "id": "does-not-exist"}))
        assert "error" in result

    async def test_multi_agent_isolation(self, tmp_db: Path) -> None:
        """Appointments from different agent_ids are isolated in list results."""
        await init_tables(str(tmp_db))
        skill = AppointmentsSkill(db_path=str(tmp_db), google_calendar=None)

        await skill.handle({
            "action": "schedule",
            "agent_id": "agent-alpha",
            "contact_name": "Alice",
            "title": "Alpha Meeting",
            "start_time": "2026-10-01T09:00:00+00:00",
        })
        await skill.handle({
            "action": "schedule",
            "agent_id": "agent-beta",
            "contact_name": "Bob",
            "title": "Beta Meeting",
            "start_time": "2026-10-02T09:00:00+00:00",
        })

        alpha_list = json.loads(await skill.handle({"action": "list", "agent_id": "agent-alpha"}))
        beta_list = json.loads(await skill.handle({"action": "list", "agent_id": "agent-beta"}))

        assert len(alpha_list["appointments"]) == 1
        assert alpha_list["appointments"][0]["agent_id"] == "agent-alpha"
        assert len(beta_list["appointments"]) == 1
        assert beta_list["appointments"][0]["agent_id"] == "agent-beta"
