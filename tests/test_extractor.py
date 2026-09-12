import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta
from llm.extractor import CommitmentExtractor
from llm.client import LLMClient


@pytest.mark.asyncio
async def test_extractor_with_mock_llm():
    mock_client = AsyncMock(spec=LLMClient)
    ref_time = datetime(2026, 9, 12, 14, 0, 0)
    expected_deadline = (ref_time + timedelta(hours=2)).isoformat()

    mock_client.generate_json.return_value = {
        "is_commitment": True,
        "task_title": "Send the pitch deck PDF",
        "recipient": "Sarah",
        "relative_deadline_text": "in 2 hours",
        "implied_deadline_utc": expected_deadline,
        "context_snippet": "Discussing investor updates",
        "confidence_score": 0.95
    }

    extractor = CommitmentExtractor(client=mock_client)
    result = await extractor.extract_commitment(
        message_text="I'll send the pitch deck PDF to Sarah in 2 hours",
        author_name="Alice",
        reference_time=ref_time
    )

    assert result.is_commitment is True
    assert result.task_title == "Send the pitch deck PDF"
    assert result.recipient == "Sarah"
    assert result.implied_deadline_utc == expected_deadline
    assert result.confidence_score == 0.95


@pytest.mark.asyncio
async def test_extractor_non_commitment():
    mock_client = AsyncMock(spec=LLMClient)
    mock_client.generate_json.return_value = {
        "is_commitment": False,
        "task_title": "",
        "recipient": None,
        "relative_deadline_text": "",
        "implied_deadline_utc": None,
        "context_snippet": None,
        "confidence_score": 0.1
    }

    extractor = CommitmentExtractor(client=mock_client)
    result = await extractor.extract_commitment(
        message_text="Can someone send the link?",
        author_name="Bob"
    )

    assert result.is_commitment is False
    assert result.confidence_score == 0.1
