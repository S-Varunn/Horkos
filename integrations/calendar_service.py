import asyncio
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from config import settings
from db.models import Commitment

logger = logging.getLogger("CommitmentRadar.Calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarService:
    def __init__(
        self,
        enabled: Optional[bool] = None,
        calendar_id: Optional[str] = None,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None,
        service_account_file: Optional[str] = None,
        reminder_minutes: Optional[List[int]] = None
    ):
        self.enabled = settings.google_calendar_enabled if enabled is None else enabled
        self.calendar_id = calendar_id or settings.google_calendar_id
        self.credentials_file = credentials_file or settings.google_credentials_file
        self.token_file = token_file or settings.google_token_file
        self.service_account_file = service_account_file or settings.google_service_account_file
        
        # Parse comma-separated reminders like "30,10"
        if reminder_minutes is not None:
            self.default_reminders = reminder_minutes
        else:
            try:
                self.default_reminders = [
                    int(x.strip()) for x in settings.calendar_reminder_minutes.split(",") if x.strip()
                ]
            except Exception:
                self.default_reminders = [30, 10]

        self.service = None
        self.is_mock = True
        self._init_client()

    def _init_client(self):
        """Initializes the official Google Calendar API service or sets mock mode."""
        if not self.enabled:
            logger.info("Google Calendar integration is disabled via configuration.")
            self.is_mock = True
            return

        # 1. Try Service Account Authentication
        if self.service_account_file and os.path.exists(self.service_account_file):
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build

                creds = service_account.Credentials.from_service_account_file(
                    self.service_account_file, scopes=SCOPES
                )
                self.service = build("calendar", "v3", credentials=creds)
                self.is_mock = False
                logger.info(f"Google Calendar connected via Service Account ({self.service_account_file})")
                return
            except Exception as e:
                logger.warning(f"Failed to authenticate with Service Account: {e}")

        # 2. Try User OAuth2 Token / Credentials
        creds = None
        if self.token_file and os.path.exists(self.token_file):
            try:
                from google.oauth2.credentials import Credentials
                creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
            except Exception as e:
                logger.warning(f"Failed to read existing token file {self.token_file}: {e}")

        if creds and creds.valid:
            try:
                from googleapiclient.discovery import build
                self.service = build("calendar", "v3", credentials=creds)
                self.is_mock = False
                logger.info("Google Calendar connected via authorized user token.")
                return
            except Exception as e:
                logger.warning(f"Failed to build calendar service with token: {e}")

        # Fallback to Mock/Dry-Run Mode
        self.is_mock = True
        logger.info(
            "Google Calendar API running in simulated/mock mode. "
            "(To connect live, provide credentials.json or service_account.json)"
        )

    def _generate_web_event_link(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: str
    ) -> str:
        """Generates a direct Google Calendar template web link for instant 1-click addition."""
        base_url = "https://calendar.google.com/calendar/r/eventedit"
        start_fmt = start_time.strftime("%Y%m%dT%H%M%SZ")
        end_fmt = end_time.strftime("%Y%m%dT%H%M%SZ")
        params = {
            "text": title,
            "dates": f"{start_fmt}/{end_fmt}",
            "details": description
        }
        return f"{base_url}?{urllib.parse.urlencode(params)}"

    async def schedule_commitment_event(
        self,
        commitment: Commitment,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        reminder_minutes: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Creates an event in Google Calendar with reminder notifications (popups/email).
        """
        deadline = commitment.deadline_utc
        # Make naive UTC datetime timezone-aware for formatting
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        end_dt = end_time or deadline
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        start_dt = start_time or (end_dt - timedelta(minutes=30))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        reminders_list = reminder_minutes or self.default_reminders

        event_title = f"🎯 [Commitment] {commitment.task_title}"
        description = (
            f"🎯 Commitment Radar Auto-Scheduled Task\n\n"
            f"• Task: {commitment.task_title}\n"
            f"• Promised by: {commitment.user_name}\n"
            f"• For / Recipient: {commitment.recipient or 'Team'}\n"
            f"• Mentioned Timeframe: \"{commitment.relative_deadline_text}\"\n"
            f"• Context: {commitment.context_snippet or 'Micro-commitment captured ambiently'}\n"
            f"• Original Discord Message: \"{commitment.raw_text}\""
        )

        overrides = [{"method": "popup", "minutes": m} for m in reminders_list]
        # If any reminder is 30m or more, also add an email notification
        if any(m >= 30 for m in reminders_list):
            overrides.append({"method": "email", "minutes": max(reminders_list)})

        event_payload = {
            "summary": event_title,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC"
            },
            "reminders": {
                "useDefault": False,
                "overrides": overrides
            },
            "colorId": "5"  # Yellow/Gold for in-progress tasks
        }

        if not self.is_mock and self.service:
            try:
                loop = asyncio.get_running_loop()
                created_event = await loop.run_in_executor(
                    None,
                    lambda: self.service.events().insert(
                        calendarId=self.calendar_id,
                        body=event_payload
                    ).execute()
                )
                logger.info(f"Google Calendar event created successfully: ID {created_event.get('id')}")
                return {
                    "id": created_event.get("id"),
                    "htmlLink": created_event.get("htmlLink"),
                    "status": "confirmed",
                    "is_mock": False
                }
            except Exception as e:
                logger.error(f"Error calling Google Calendar API: {e}", exc_info=True)

        # Mock / Simulation Return
        synthetic_id = f"gcal_sim_{commitment.id or int(datetime.now().timestamp())}"
        synthetic_link = self._generate_web_event_link(
            title=event_title,
            start_time=start_dt,
            end_time=end_dt,
            description=description
        )
        logger.info(f"Simulated Google Calendar event scheduled: {synthetic_id}")
        return {
            "id": synthetic_id,
            "htmlLink": synthetic_link,
            "status": "confirmed",
            "is_mock": True
        }

    async def update_event_time(
        self,
        event_id: str,
        new_deadline: datetime,
        duration_minutes: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Updates event start and end time when user pushes or changes deadline."""
        if not event_id:
            return None

        if new_deadline.tzinfo is None:
            new_deadline = new_deadline.replace(tzinfo=timezone.utc)

        new_start = new_deadline - timedelta(minutes=duration_minutes)

        if not self.is_mock and self.service:
            try:
                loop = asyncio.get_running_loop()
                event = await loop.run_in_executor(
                    None,
                    lambda: self.service.events().get(
                        calendarId=self.calendar_id,
                        eventId=event_id
                    ).execute()
                )
                event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "UTC"}
                event["end"] = {"dateTime": new_deadline.isoformat(), "timeZone": "UTC"}

                updated_event = await loop.run_in_executor(
                    None,
                    lambda: self.service.events().update(
                        calendarId=self.calendar_id,
                        eventId=event_id,
                        body=event
                    ).execute()
                )
                logger.info(f"Google Calendar event {event_id} updated with new deadline {new_deadline}")
                return updated_event
            except Exception as e:
                logger.error(f"Failed to update Google Calendar event {event_id}: {e}")
                return None

        logger.info(f"Simulated Google Calendar event {event_id} deadline updated to {new_deadline}")
        return {"id": event_id, "status": "updated", "is_mock": True}

    async def complete_event(
        self,
        event_id: str,
        task_title: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Marks event completed on Google Calendar (changes color to Green and prepends [✅ Done])."""
        if not event_id:
            return None

        if not self.is_mock and self.service:
            try:
                loop = asyncio.get_running_loop()
                event = await loop.run_in_executor(
                    None,
                    lambda: self.service.events().get(
                        calendarId=self.calendar_id,
                        eventId=event_id
                    ).execute()
                )
                summary = event.get("summary", "")
                if not summary.startswith("✅"):
                    event["summary"] = f"✅ [Done] {task_title or summary.replace('🎯 [Commitment] ', '')}"
                event["colorId"] = "10"  # Google Calendar Green (Basil)

                updated_event = await loop.run_in_executor(
                    None,
                    lambda: self.service.events().update(
                        calendarId=self.calendar_id,
                        eventId=event_id,
                        body=event
                    ).execute()
                )
                logger.info(f"Google Calendar event {event_id} marked completed.")
                return updated_event
            except Exception as e:
                logger.error(f"Failed to mark Google Calendar event {event_id} completed: {e}")
                return None

        logger.info(f"Simulated Google Calendar event {event_id} marked as completed.")
        return {"id": event_id, "status": "completed", "is_mock": True}
