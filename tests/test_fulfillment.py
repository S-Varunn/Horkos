import pytest
from unittest.mock import AsyncMock

from pipeline.fulfillment import is_fulfillment_candidate, FulfillmentDetector
from llm.client import LLMClient


def test_is_fulfillment_candidate():
    # Candidates with keywords or attachments
    assert is_fulfillment_candidate("Here is the updated deck", has_attachments=False) is True
    assert is_fulfillment_candidate("Just finished reviewing the PR", has_attachments=False) is True
    assert is_fulfillment_candidate("Uploaded the patch file", has_attachments=False) is True
    assert is_fulfillment_candidate("Done with task", has_attachments=False) is True
    assert is_fulfillment_candidate("random message", has_attachments=True) is True
    assert is_fulfillment_candidate("Check this out: https://github.com/org/repo/pull/1", has_attachments=False) is True

    # Non-candidates
    assert is_fulfillment_candidate("Hey what's up", has_attachments=False) is False
    assert is_fulfillment_candidate("Are we having lunch?", has_attachments=False) is False


from datetime import datetime, timezone
from db.models import Commitment, CommitmentStatus

@pytest.mark.asyncio
async def test_fulfillment_detector_matches_active_commitment():
    mock_client = AsyncMock(spec=LLMClient)
    mock_client.generate_json.return_value = {
        "is_fulfilled": True,
        "matched_commitment_id": 42,
        "confidence_score": 0.95,
        "reason": "User uploaded the promised PDF document"
    }

    detector = FulfillmentDetector(client=mock_client)
    active_commitments = [
        Commitment(
            id=42,
            user_id="123",
            user_name="Alice",
            channel_id="c1",
            message_id="m1",
            raw_text="I will send the Q3 roadmap PDF",
            task_title="Send the Q3 roadmap PDF",
            recipient="Bob",
            deadline_utc=datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc),
            status=CommitmentStatus.PENDING
        ),
        Commitment(
            id=43,
            user_id="123",
            user_name="Alice",
            channel_id="c1",
            message_id="m2",
            raw_text="I will review security audit",
            task_title="Review security audit",
            recipient="Alice",
            deadline_utc=datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc),
            status=CommitmentStatus.PENDING
        )
    ]

    result = await detector.evaluate_fulfillment(
        message_text="Here is the Q3 roadmap PDF, let me know if you need changes",
        speaker_name="Alice",
        pending_commitments=active_commitments,
        attachments=["q3_roadmap.pdf"]
    )

    assert result.is_fulfilled is True
    assert result.matched_commitment_id == 42
    assert result.confidence_score == 0.95


@pytest.mark.asyncio
async def test_fulfillment_detector_ignores_unknown_id():
    mock_client = AsyncMock(spec=LLMClient)
    mock_client.generate_json.return_value = {
        "is_fulfilled": True,
        "matched_commitment_id": 999,  # ID not in active_commitments
        "confidence_score": 0.95,
        "reason": "Hallucinated ID"
    }

    detector = FulfillmentDetector(client=mock_client)
    active_commitments = [
        Commitment(
            id=42,
            user_id="123",
            user_name="Alice",
            channel_id="c1",
            message_id="m1",
            raw_text="I will send the Q3 roadmap PDF",
            task_title="Send the Q3 roadmap PDF",
            recipient="Bob",
            deadline_utc=datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc),
            status=CommitmentStatus.PENDING
        )
    ]

    result = await detector.evaluate_fulfillment(
        message_text="Here is something unrelated",
        speaker_name="Alice",
        pending_commitments=active_commitments,
        attachments=[]
    )

    # Should safely reject hallucinated ID
    assert result.is_fulfilled is False
    assert result.matched_commitment_id is None
