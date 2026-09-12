import pytest
from unittest.mock import AsyncMock, patch

from datetime import datetime, timezone
from integrations.webhook_service import WebhookDispatcher
from integrations.mcp_server import format_commitments_markdown, format_commitments_todoist, MCPServer


from db.models import Commitment, CommitmentStatus

@pytest.mark.asyncio
async def test_webhook_dispatcher_dispatches_event():
    dispatcher = WebhookDispatcher(webhook_url="https://example.com/webhook")
    
    dummy_commitment = Commitment(
        id=1,
        user_id="12345",
        user_name="Alice",
        channel_id="c1",
        message_id="m1",
        task_title="Submit report",
        recipient="Bob",
        deadline_utc=datetime(2026, 9, 12, 17, 0, 0, tzinfo=timezone.utc),
        status=CommitmentStatus.PENDING,
        calendar_event_link=None,
        raw_text="I will submit report"
    )

    with patch.object(dispatcher, "_send_payload", new_callable=AsyncMock) as mock_send:
        await dispatcher.dispatch("commitment.created", dummy_commitment)
        # Give event loop a microsecond to launch task
        import asyncio
        await asyncio.sleep(0.01)

        assert mock_send.called
        payload = mock_send.call_args[0][0]
        assert payload["event"] == "commitment.created"
        assert payload["commitment"]["id"] == 1
        assert payload["commitment"]["task_title"] == "Submit report"


def test_export_formatters():
    commitments = [
        Commitment(
            id=10,
            user_id="123",
            user_name="Alice",
            channel_id="c1",
            message_id="m1",
            raw_text="I will update documentation",
            task_title="Update documentation",
            recipient="Bob",
            deadline_utc=datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc),
            status=CommitmentStatus.PENDING,
            calendar_event_link="https://calendar.google.com/event?eid=xyz"
        )
    ]

    md_output = format_commitments_markdown(commitments)
    assert "Active Commitments" in md_output
    assert "Update documentation" in md_output
    assert "[Calendar Link](https://calendar.google.com/event?eid=xyz)" in md_output

    todoist_output = format_commitments_todoist(commitments)
    assert len(todoist_output) == 1
    assert "Update documentation" in todoist_output[0]["content"]
    assert "Bob" in todoist_output[0]["content"]


@pytest.mark.asyncio
async def test_mcp_server_handle_tool_call():
    server = MCPServer()
    server.db.get_all_active_commitments = AsyncMock(return_value=[
        Commitment(
            id=5,
            user_id="345",
            user_name="Carol",
            channel_id="c1",
            message_id="m1",
            raw_text="Ship Phase 2",
            task_title="Ship Phase 2",
            recipient="Dave",
            deadline_utc=datetime(2026, 9, 12, 20, 0, 0, tzinfo=timezone.utc),
            status=CommitmentStatus.PENDING,
            calendar_event_link=None
        )
    ])

    response = await server.handle_call("list_active_commitments", {})
    assert len(response["commitments"]) == 1
    assert response["commitments"][0]["id"] == 5
    assert response["commitments"][0]["task_title"] == "Ship Phase 2"

    export_res = await server.handle_call("export_commitments", {"format": "markdown"})
    assert "Ship Phase 2" in export_res["content"]
