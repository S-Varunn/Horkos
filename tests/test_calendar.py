import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from integrations.calendar_service import GoogleCalendarService
from db.database import Database
from db.models import Commitment, CommitmentStatus


@pytest.mark.asyncio
async def test_calendar_service_mock_schedule():
    cal = GoogleCalendarService(enabled=True, token_file="non_existent_token.json", reminder_minutes=[30, 10])
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

    cal = GoogleCalendarService(enabled=True, token_file="non_existent_token.json", reminder_minutes=[30, 10])
    cal._user_services["u1"] = mock_service

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
    popup_minutes = [o["minutes"] for o in overrides if o["method"] == "popup"]
    assert 30 in popup_minutes
    assert 10 in popup_minutes


@pytest.mark.asyncio
async def test_multi_user_token_persistence(tmp_path):
    db_file = str(tmp_path / "test_user_auth.db")
    db = Database(db_file)
    await db.init_db()

    # Save user token
    sample_token = '{"token": "xyz123", "refresh_token": "ref456"}'
    saved = await db.save_user_google_auth("user_discord_1", sample_token, "user1@example.com")
    assert saved is True

    # Retrieve user token
    auth = await db.get_user_google_auth("user_discord_1")
    assert auth is not None
    assert auth.discord_user_id == "user_discord_1"
    assert auth.google_email == "user1@example.com"
    assert "refresh_token" in auth.token_json

    # Test non-existent user
    assert await db.get_user_google_auth("user_non_existent") is None

    # Delete user token
    deleted = await db.delete_user_google_auth("user_discord_1")
    assert deleted is True
    assert await db.get_user_google_auth("user_discord_1") is None


@pytest.mark.asyncio
async def test_multi_user_calendar_service_routing(tmp_path):
    db_file = str(tmp_path / "test_routing.db")
    db = Database(db_file)
    await db.init_db()

    cal = GoogleCalendarService(db=db, enabled=True, token_file="non_existent_token.json")

    # Mock service for User A
    mock_service_a = MagicMock()
    mock_events = MagicMock()
    mock_insert = MagicMock()
    mock_service_a.events.return_value = mock_events
    mock_events.insert.return_value = mock_insert
    mock_insert.execute.return_value = {
        "id": "evt_user_a_live",
        "htmlLink": "https://calendar.google.com/event/user_a",
        "status": "confirmed"
    }
    cal._user_services["user_a"] = mock_service_a

    # User A commitment -> should use User A's live service
    comm_a = Commitment(
        id=1,
        user_id="user_a",
        user_name="Alice",
        channel_id="c1",
        message_id="m1",
        raw_text="Will do it by 4pm",
        task_title="Alice Task",
        deadline_utc=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        status=CommitmentStatus.PENDING
    )
    res_a = await cal.schedule_commitment_event(comm_a)
    assert res_a["is_mock"] is False
    assert res_a["id"] == "evt_user_a_live"

    # User B (unlinked) commitment -> should fall back to mock web template link
    comm_b = Commitment(
        id=2,
        user_id="user_b",
        user_name="Bob",
        channel_id="c1",
        message_id="m2",
        raw_text="Will do it by 5pm",
        task_title="Bob Task",
        deadline_utc=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2),
        status=CommitmentStatus.PENDING
    )
    res_b = await cal.schedule_commitment_event(comm_b)
    assert res_b["is_mock"] is True
    assert "calendar.google.com/calendar/r/eventedit" in res_b["htmlLink"]


def test_authorization_url_generation():
    cal = GoogleCalendarService(credentials_file="credentials.json")
    url = cal.get_authorization_url("discord_user_999")
    assert "accounts.google.com/o/oauth2" in url
    assert "state=discord_user_999" in url
    assert "access_type=offline" in url
