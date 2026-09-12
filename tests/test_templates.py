import pytest
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from db.database import Database
from db.models import Commitment, CommitmentStatus
from integrations.calendar_service import GoogleCalendarService, render_calendar_template


def test_render_calendar_template():
    context = {
        "task": "Review security audit",
        "author": "Alice",
        "recipient": "Bob",
        "timeframe": "by 5 PM"
    }

    # Test custom title formats
    res1 = render_calendar_template("!!Reminder!! {task}", context)
    assert res1 == "!!Reminder!! Review security audit"

    res2 = render_calendar_template("Reminder: {task} (for {recipient})", context)
    assert res2 == "Reminder: Review security audit (for Bob)"

    # Test safe missing key fallback
    res3 = render_calendar_template("{task} - {unknown_key}", context)
    assert res3 == "Review security audit - {unknown_key}"


@pytest.mark.asyncio
async def test_database_user_calendar_template(tmp_path):
    db_file = os.path.join(tmp_path, "test_templates.db")
    db = Database(db_file)
    await db.init_db()

    user_id = "user_999"

    # Initially None
    initial = await db.get_user_calendar_template(user_id)
    assert initial is None

    # Save custom template
    saved = await db.save_user_calendar_template(
        discord_user_id=user_id,
        title_template="!!Reminder!! {task}",
        completed_template="[Resolved] {task}",
        description_template="Promised by {author} to {recipient}"
    )
    assert saved.discord_user_id == user_id
    assert saved.title_template == "!!Reminder!! {task}"
    assert saved.completed_template == "[Resolved] {task}"
    assert saved.description_template == "Promised by {author} to {recipient}"

    # Retrieve
    retrieved = await db.get_user_calendar_template(user_id)
    assert retrieved is not None
    assert retrieved.title_template == "!!Reminder!! {task}"

    # Update template
    updated = await db.save_user_calendar_template(
        discord_user_id=user_id,
        title_template="Reminder: {task}"
    )
    assert updated.title_template == "Reminder: {task}"

    # Delete / Reset
    del_res = await db.delete_user_calendar_template(user_id)
    assert del_res is True

    after_del = await db.get_user_calendar_template(user_id)
    assert after_del is None


@pytest.mark.asyncio
async def test_calendar_service_uses_user_template(tmp_path):
    db_file = os.path.join(tmp_path, "test_cal_tpl.db")
    db = Database(db_file)
    await db.init_db()

    user_id = "user_777"
    await db.save_user_calendar_template(
        discord_user_id=user_id,
        title_template="!!Reminder!! {task}",
        completed_template="[Done] {task}"
    )

    calendar_service = GoogleCalendarService(db=db, enabled=True)

    # Mock user calendar API client
    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute.return_value = {"id": "event_123", "htmlLink": "https://calendar.google.com/test"}
    mock_events.insert.return_value = mock_insert
    mock_service.events.return_value = mock_events

    calendar_service.get_service_for_user = AsyncMock(return_value=mock_service)

    commitment = Commitment(
        id=1,
        user_id=user_id,
        user_name="Alice",
        channel_id="c1",
        message_id="m1",
        task_title="Submit invoice",
        recipient="Bob",
        deadline_utc=datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc),
        status=CommitmentStatus.PENDING,
        raw_text="I'll submit the invoice by 6pm"
    )

    result = await calendar_service.schedule_commitment_event(commitment)
    assert result["id"] == "event_123"

    # Verify event_payload summary used custom template
    insert_call_kwargs = mock_events.insert.call_args[1]
    payload = insert_call_kwargs["body"]
    assert payload["summary"] == "!!Reminder!! Submit invoice"
    # Verify no emojis forced
    assert "🎯" not in payload["summary"]


@pytest.mark.asyncio
async def test_calendar_service_complete_event_uses_user_template(tmp_path):
    db_file = os.path.join(tmp_path, "test_cal_tpl2.db")
    db = Database(db_file)
    await db.init_db()

    user_id = "user_888"
    await db.save_user_calendar_template(
        discord_user_id=user_id,
        title_template="Reminder: {task}",
        completed_template="Resolved: {task}"
    )

    calendar_service = GoogleCalendarService(db=db, enabled=True)

    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_get = MagicMock()
    mock_get.execute.return_value = {"id": "event_456", "summary": "Reminder: Submit invoice"}
    mock_update = MagicMock()
    mock_update.execute.return_value = {"id": "event_456", "summary": "Resolved: Submit invoice", "colorId": "10"}
    mock_events.get.return_value = mock_get
    mock_events.update.return_value = mock_update
    mock_service.events.return_value = mock_events

    calendar_service.get_service_for_user = AsyncMock(return_value=mock_service)

    res = await calendar_service.complete_event(
        event_id="event_456",
        task_title="Submit invoice",
        discord_user_id=user_id
    )

    assert res["summary"] == "Resolved: Submit invoice"
    update_call_kwargs = mock_events.update.call_args[1]
    updated_body = update_call_kwargs["body"]
    assert updated_body["summary"] == "Resolved: Submit invoice"
    assert updated_body["colorId"] == "10"

