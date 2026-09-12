import os
import pytest
from datetime import timedelta
from unittest.mock import AsyncMock

from db.database import Database
from db.models import Commitment, CommitmentStatus, utc_now
from scheduler.service import AlertScheduler

TEST_SCHEDULER_DB = "test_scheduler.db"


@pytest.fixture
async def scheduler_db():
    if os.path.exists(TEST_SCHEDULER_DB):
        os.remove(TEST_SCHEDULER_DB)

    db = Database(TEST_SCHEDULER_DB)
    await db.init_db()
    yield db

    if os.path.exists(TEST_SCHEDULER_DB):
        os.remove(TEST_SCHEDULER_DB)


@pytest.mark.asyncio
async def test_scheduler_triggers_alert(scheduler_db: Database):
    mock_callback = AsyncMock()

    # Create commitment due in 15 minutes (within 30m window)
    c = Commitment(
        user_id="user_test",
        user_name="Tester",
        channel_id="channel_test",
        message_id="msg_test",
        raw_text="I will finish in 15 mins",
        task_title="Finish project demo",
        deadline_utc=utc_now() + timedelta(minutes=15),
        status=CommitmentStatus.PENDING
    )
    saved = await scheduler_db.add_commitment(c)

    scheduler = AlertScheduler(
        db=scheduler_db,
        alert_callback=mock_callback,
        alert_advance_minutes=30
    )

    # Trigger alert check
    await scheduler._check_and_trigger_alerts()

    # Verify callback was called with the commitment
    assert mock_callback.call_count == 1
    call_arg = mock_callback.call_args[0][0]
    assert call_arg.id == saved.id
    assert call_arg.task_title == "Finish project demo"

    # Verify status in DB is updated to NOTIFIED
    updated_commitment = await scheduler_db.get_commitment_by_id(saved.id)
    assert updated_commitment.status == CommitmentStatus.NOTIFIED
