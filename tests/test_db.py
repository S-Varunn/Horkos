import os
import pytest
from datetime import timedelta
from db.database import Database
from db.models import Commitment, CommitmentStatus, utc_now

TEST_DB_PATH = "test_commitments.db"


@pytest.fixture
async def test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    db = Database(TEST_DB_PATH)
    await db.init_db()
    yield db

    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.mark.asyncio
async def test_add_and_retrieve_commitment(test_db: Database):
    commitment = Commitment(
        user_id="123456789",
        user_name="Alice",
        channel_id="987654321",
        message_id="55555",
        raw_text="I will send the deck by 4pm",
        task_title="Send the pitch deck",
        recipient="Bob",
        deadline_utc=utc_now() + timedelta(hours=2),
        relative_deadline_text="by 4pm",
        context_snippet="Pitch deck preparation",
        status=CommitmentStatus.PENDING
    )

    saved = await test_db.add_commitment(commitment)
    assert saved.id is not None
    assert saved.id > 0

    retrieved = await test_db.get_commitment_by_id(saved.id)
    assert retrieved is not None
    assert retrieved.task_title == "Send the pitch deck"
    assert retrieved.recipient == "Bob"
    assert retrieved.status == CommitmentStatus.PENDING


@pytest.mark.asyncio
async def test_update_status(test_db: Database):
    commitment = Commitment(
        user_id="123456789",
        user_name="Alice",
        channel_id="987654321",
        message_id="55556",
        raw_text="Will review the PR",
        task_title="Review PR",
        deadline_utc=utc_now() + timedelta(hours=1),
        status=CommitmentStatus.PENDING
    )
    saved = await test_db.add_commitment(commitment)
    
    updated = await test_db.update_status(saved.id, CommitmentStatus.COMPLETED)
    assert updated is True

    retrieved = await test_db.get_commitment_by_id(saved.id)
    assert retrieved.status == CommitmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_due_alerts_query(test_db: Database):
    now = utc_now()
    # 1. Due in 10 minutes (should be caught by 30 min window)
    c1 = Commitment(
        user_id="user1",
        user_name="Alice",
        channel_id="chan1",
        message_id="msg1",
        raw_text="Almost done",
        task_title="Task due soon",
        deadline_utc=now + timedelta(minutes=10),
        status=CommitmentStatus.PENDING
    )
    # 2. Due in 2 hours (should NOT be caught by 30 min window)
    c2 = Commitment(
        user_id="user2",
        user_name="Bob",
        channel_id="chan1",
        message_id="msg2",
        raw_text="Later",
        task_title="Task due later",
        deadline_utc=now + timedelta(hours=2),
        status=CommitmentStatus.PENDING
    )
    await test_db.add_commitment(c1)
    await test_db.add_commitment(c2)

    due_alerts = await test_db.get_due_alerts(lead_minutes=30)
    assert len(due_alerts) == 1
    assert due_alerts[0].task_title == "Task due soon"
