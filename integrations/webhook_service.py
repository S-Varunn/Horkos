import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import aiohttp

from db.models import Commitment
from config import settings

logger = logging.getLogger("CommitmentRadar.Webhook")


class WebhookDispatcher:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or getattr(settings, "webhook_url", None)

    async def dispatch(self, event_type: str, commitment: Commitment, extra_data: Optional[Dict[str, Any]] = None):
        """Sends an asynchronous webhook event notification to configured endpoint."""
        if not self.webhook_url:
            return

        payload = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "commitment": {
                "id": commitment.id,
                "user_id": commitment.user_id,
                "user_name": commitment.user_name,
                "task_title": commitment.task_title,
                "recipient": commitment.recipient,
                "deadline_utc": commitment.deadline_utc.isoformat() if commitment.deadline_utc else None,
                "status": commitment.status.value if hasattr(commitment.status, "value") else commitment.status,
                "calendar_event_link": commitment.calendar_event_link,
                "raw_text": commitment.raw_text
            },
            "extra": extra_data or {}
        }

        asyncio.create_task(self._send_payload(payload))

    async def _send_payload(self, payload: Dict[str, Any]):
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.webhook_url, json=payload) as res:
                    if res.status >= 400:
                        logger.warning(f"Webhook dispatch failed with status {res.status}")
                    else:
                        logger.debug(f"Webhook {payload.get('event')} dispatched successfully.")
        except Exception as e:
            logger.warning(f"Failed to deliver webhook: {e}")
