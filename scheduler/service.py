import logging
from typing import Callable, Awaitable, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db.database import Database
from db.models import Commitment, CommitmentStatus
from config import settings

logger = logging.getLogger("CommitmentRadar.Scheduler")


class AlertScheduler:
    def __init__(
        self,
        db: Database,
        alert_callback: Optional[Callable[[Commitment], Awaitable[None]]] = None,
        check_interval_seconds: Optional[int] = None,
        alert_advance_minutes: Optional[int] = None
    ):
        self.db = db
        self.alert_callback = alert_callback
        self.check_interval_seconds = check_interval_seconds or settings.check_interval_seconds
        self.alert_advance_minutes = alert_advance_minutes or settings.alert_advance_minutes
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    def set_alert_callback(self, callback: Callable[[Commitment], Awaitable[None]]):
        self.alert_callback = callback

    def start(self):
        """Starts the background scheduler job."""
        if self.is_running:
            return

        self.scheduler.add_job(
            self._check_and_trigger_alerts,
            "interval",
            seconds=self.check_interval_seconds,
            id="commitment_check_job",
            replace_existing=True
        )
        self.scheduler.start()
        self.is_running = True
        logger.info(f"AlertScheduler started (checking every {self.check_interval_seconds}s)")

    def stop(self):
        """Stops the background scheduler."""
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("AlertScheduler stopped")

    async def _check_and_trigger_alerts(self):
        """Scans database for commitments needing notification."""
        try:
            due_commitments = await self.db.get_due_alerts(lead_minutes=self.alert_advance_minutes)
            if not due_commitments:
                return

            logger.info(f"Found {len(due_commitments)} commitments due for alert")

            for commitment in due_commitments:
                if self.alert_callback and commitment.id is not None:
                    try:
                        await self.alert_callback(commitment)
                        # Mark as NOTIFIED so we don't alert repeatedly
                        await self.db.update_status(commitment.id, CommitmentStatus.NOTIFIED)
                    except Exception as e:
                        logger.error(f"Failed to trigger alert for commitment #{commitment.id}: {e}")
        except Exception as e:
            logger.error(f"Error checking due alerts: {e}")
