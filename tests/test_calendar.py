import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from integrations.calendar_service import GoogleCalendarService
from db.database import Database
from db.models import Commitment, CommitmentStatus


@pytest.mark.asyncio
async def test_calendar_service_mock_schedule():
    cal = GoogleCalendarService(enabled=True, reminder_minutes=[30, 10])
    commitment = Commitment(
        id=42,
        user_id="123",
        user_name="Alice",
        channel_id="c1",
        message_id="m1",
        raw_text="I will finish the deck in 2 hours",
        task_title="Finish the deck",
        recipient="Bob",
        deadline_utc=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2),
        relative_deadline_text="in 2 hours",
        status=CommitmentStatus.PENDING
    )

    result = await cal.schedule_commitment_event(commitment)
    assert result["status"] == "confirmed"
    assert result["is_mock"] is True
    assert "gcal_sim_42" in result["id"]
    assert "calendar.google.com/calendar/r/eventedit" in result["htmlLink"]


@pytest.mark.asyncio
async def test_calendar_service_update_and_complete():
    cal = GoogleCalendarService(enabled=True)
    new_deadline = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)

    update_res = await cal.update_event_time("gcal_sim_42", new_deadline)
    assert update_res is not None
    assert update_res["status"] == "updated"

    comp_res = await cal.complete_event("gcal_sim_42", "Finish the deck")
    assert comp_res is not None
    assert comp_res["status"] == "completed"


@pytest.mark.asyncio
async def test_calendar_database_persistence(tmp_path):
    db_file = str(tmp_path / "test_cal.db")
    db = Database(db_file)
    await db.init_db()

    commitment = Commitment(
        user_id="user_abc",
        user_name="Charlie",
        channel_id="chan_123",
        message_id="msg_999",
        raw_text="I'll deliver the slides by 5pm",
        task_title="Deliver the slides",
        deadline_utc=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        calendar_event_id="evt_123",
        calendar_event_link="https://calendar.google.com/event/123"
    )

    saved = await db.add_commitment(commitment)
    assert saved.id is not None
    assert saved.calendar_event_id == "evt_123"
    assert saved.calendar_event_link == "https://calendar.google.com/event/123"

    # Test updating calendar event
    ok = await db.update_calendar_event(saved.id, "evt_new", "https://calendar.google.com/event/new")
    assert ok is True

    fetched = await db.get_commitment_by_id(saved.id)
    assert fetched is not None
    assert fetched.calendar_event_id == "evt_new"
    assert fetched.calendar_event_link == "https://calendar.google.com/event/new"


@pytest.mark.asyncio
async def test_calendar_service_mocked_google_api():
    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_insert = MagicMock()
    mock_service.events.return_value = mock_events
    mock_events.insert.return_value = mock_insert
    mock_insert.execute.return_value = {
        "id": "live_google_evt_777",
        "htmlLink": "https://www.google.com/calendar/event?eid=live777",
        "status": "confirmed"
    }

    cal = GoogleCalendarService(enabled=True, reminder_minutes=[30, 10])
    cal.service = mock_service
    cal.is_mock = False

    commitment = Commitment(
        id=77,
        user_id="u1",
        user_name="Dan",
        channel_id="c1",
        message_id="m1",
        raw_text="Will email client in 1 hour",
        task_title="Email client",
        deadline_utc=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        status=CommitmentStatus.PENDING
    )

    result = await cal.schedule_commitment_event(commitment)
    assert result["is_mock"] is False
    assert result["id"] == "live_google_evt_777"
    assert result["htmlLink"] == "https://www.google.com/calendar/event?eid=live777"

    # Verify parameters passed to googleapiclient
    call_args = mock_events.insert.call_args[1]
    body = call_args["body"]
    assert "Email client" in body["summary"]
    overrides = body["reminders"]["overrides"]
    # Should include popups for 30m, 10m and email notification for 30m
    popup_minutes = [o["minutes"] for o in overrides if o["method"] == "popup"]
    assert 30 in popup_minutes
    assert 10 in popup_minutes
