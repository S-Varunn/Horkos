import pytest
from unittest.mock import AsyncMock
from datetime import datetime

from llm.client import LLMClient
from llm.extractor import CommitmentExtractor


@pytest.mark.asyncio
async def test_context_disambiguation_resolves_pronoun():
    mock_client = AsyncMock(spec=LLMClient)
    mock_client.generate_json.return_value = {
        "is_commitment": True,
        "task_title": "Send marketing pitch deck to Alice",
        "recipient": "Alice",
        "relative_deadline_text": "in 30 minutes",
        "implied_deadline_local": "2026-09-12T15:30:00",
        "context_snippet": "Alice asked for the marketing pitch deck",
        "confidence_score": 0.95
    }

    extractor = CommitmentExtractor(client=mock_client)
    context = "Alice: Can someone share the marketing pitch deck?\nBob: Looking into it"
    result = await extractor.extract_commitment(
        message_text="I'll send that over in 30 minutes",
        author_name="Bob",
        reference_time=datetime(2026, 9, 12, 15, 0, 0),
        context_snippet=context
    )

    assert result.is_commitment is True
    assert "marketing pitch deck" in result.task_title
    assert result.recipient == "Alice"

    # Verify context was injected into the prompt sent to LLM
    call_args = mock_client.generate_json.call_args[1]
    assert "RECENT_CHANNEL_CONTEXT:" in call_args["user_prompt"]
    assert "Alice: Can someone share the marketing pitch deck?" in call_args["user_prompt"]
