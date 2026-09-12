import asyncio
import json
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from config import settings
from db.database import Database
from db.models import Commitment

logger = logging.getLogger("CommitmentRadar.Calendar")

# Allow Google OAuth to add default scopes (such as openid) without raising Warning/Exception
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid"
]


class GoogleCalendarService:
    def __init__(
        self,
        db: Optional[Database] = None,
        enabled: Optional[bool] = None,
        calendar_id: Optional[str] = None,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None,
        service_account_file: Optional[str] = None,
        reminder_minutes: Optional[List[int]] = None
    ):
        self.db = db
        self.enabled = settings.google_calendar_enabled if enabled is None else enabled
        self.calendar_id = calendar_id or settings.google_calendar_id
        self.credentials_file = credentials_file or settings.google_credentials_file
        self.token_file = token_file or settings.google_token_file
        self.service_account_file = service_account_file or settings.google_service_account_file
        self.redirect_uri = settings.google_oauth_redirect_uri

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

        # Service cache keyed by discord_user_id
        self._user_services: Dict[str, Any] = {}
        self._pending_flows: Dict[str, Any] = {}
        self.global_service = None
        self.is_mock = True
        self._init_global_fallback()

    def _init_global_fallback(self):
        """Initializes fallback service account or local token.json if present."""
        if not self.enabled:
            return

        # Try Service Account
        if self.service_account_file and os.path.exists(self.service_account_file):
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build

                creds = service_account.Credentials.from_service_account_file(
                    self.service_account_file, scopes=SCOPES
                )
                self.global_service = build("calendar", "v3", credentials=creds)
                self.is_mock = False
                logger.info(f"Google Calendar fallback connected via Service Account ({self.service_account_file})")
                return
            except Exception as e:
                logger.warning(f"Failed to authenticate with Service Account: {e}")

        # Try local token.json
        if self.token_file and os.path.exists(self.token_file):
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
                if creds and creds.valid:
                    self.global_service = build("calendar", "v3", credentials=creds)
                    self.is_mock = False
                    logger.info("Google Calendar fallback connected via token.json.")
                    return
            except Exception as e:
                logger.warning(f"Failed to load token.json fallback: {e}")

    def get_authorization_url(self, discord_user_id: str) -> str:
        """Generates a personalized Google OAuth consent URL with state=discord_user_id."""
        if not os.path.exists(self.credentials_file):
            raise FileNotFoundError(f"'{self.credentials_file}' not found. Download it from Google Cloud Console.")

        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            self.credentials_file,
            scopes=SCOPES,
            redirect_uri=self.redirect_uri,
            autogenerate_code_verifier=False
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=discord_user_id
        )
        self._pending_flows[discord_user_id] = flow
        return auth_url

    async def handle_oauth_code(self, code: str, discord_user_id: str) -> Dict[str, Any]:
        """Exchanges authorization code for credentials and saves to database for this user."""
        try:
            from google_auth_oauthlib.flow import Flow
            from googleapiclient.discovery import build

            flow = self._pending_flows.pop(discord_user_id, None)
            if not flow:
                flow = Flow.from_client_secrets_file(
                    self.credentials_file,
                    scopes=SCOPES,
                    redirect_uri=self.redirect_uri,
                    autogenerate_code_verifier=False
                )

            flow.fetch_token(code=code)
            creds = flow.credentials

            # Retrieve user email if accessible
            email = None
            try:
                oauth2_service = build("oauth2", "v2", credentials=creds)
                user_info = oauth2_service.userinfo().get().execute()
                email = user_info.get("email")
            except Exception:
                pass

            token_json = creds.to_json()
            if self.db:
                await self.db.save_user_google_auth(
                    discord_user_id=discord_user_id,
                    token_json=token_json,
                    google_email=email
                )

            # Invalidate cached service so it rebuilds fresh
            self._user_services.pop(discord_user_id, None)

            logger.info(f"Successfully linked Google Calendar for Discord user {discord_user_id} ({email or 'no email'})")
            return {"success": True, "email": email}
        except Exception as e:
            logger.error(f"Failed to exchange OAuth code for user {discord_user_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_service_for_user(self, discord_user_id: Optional[str]) -> Optional[Any]:
        """Retrieves or builds an authenticated Google Calendar API client for a specific user."""
        if not self.enabled or not discord_user_id:
            return self.global_service

        if discord_user_id in self._user_services:
            return self._user_services[discord_user_id]

        # 1. Look up user in SQLite
        if self.db:
            user_auth = await self.db.get_user_google_auth(discord_user_id)
            if user_auth:
                try:
                    from google.oauth2.credentials import Credentials
                    from google.auth.transport.requests import Request
                    from googleapiclient.discovery import build

                    token_dict = json.loads(user_auth.token_json)
                    creds = Credentials.from_authorized_user_info(token_dict, SCOPES)

                    # Refresh if expired
                    if creds.expired and creds.refresh_token:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, lambda: creds.refresh(Request()))
                        await self.db.save_user_google_auth(
                            discord_user_id=discord_user_id,
                            token_json=creds.to_json(),
                            google_email=user_auth.google_email
                        )

                    service = build("calendar", "v3", credentials=creds)
                    self._user_services[discord_user_id] = service
                    return service
                except Exception as e:
                    logger.warning(f"Failed to build Google Calendar client for user {discord_user_id}: {e}")

        # 2. Check if local token.json exists (auto-link to this user)
        if self.token_file and os.path.exists(self.token_file):
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build

                creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
                if creds and creds.valid:
                    # Auto-seed database for this user
                    if self.db:
                        await self.db.save_user_google_auth(
                            discord_user_id=discord_user_id,
                            token_json=creds.to_json()
                        )
                    service = build("calendar", "v3", credentials=creds)
                    self._user_services[discord_user_id] = service
                    return service
            except Exception as e:
                logger.warning(f"Failed to read token.json for user {discord_user_id}: {e}")

        # 3. Fallback to global service account if configured
        return self.global_service

    async def is_user_connected(self, discord_user_id: str) -> bool:
        """Checks if a specific Discord user has an active Google Calendar integration."""
        service = await self.get_service_for_user(discord_user_id)
        return service is not None

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
        Creates an event in the commitment owner's Google Calendar with their reminder notifications.
        """
        deadline = commitment.deadline_utc
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
        if any(m >= 30 for m in reminders_list):
            overrides.append({"method": "email", "minutes": max(reminders_list)})

        event_payload = {
            "summary": event_title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            "reminders": {"useDefault": False, "overrides": overrides},
            "colorId": "5"  # Yellow/Gold for in-progress tasks
        }

        # Look up service for this specific user
        user_service = await self.get_service_for_user(commitment.user_id)

        if user_service:
            try:
                loop = asyncio.get_running_loop()
                created_event = await loop.run_in_executor(
                    None,
                    lambda: user_service.events().insert(
                        calendarId=self.calendar_id,
                        body=event_payload
                    ).execute()
                )
                logger.info(
                    f"Google Calendar event created on {commitment.user_name}'s calendar: "
                    f"ID {created_event.get('id')}"
                )
                return {
                    "id": created_event.get("id"),
                    "htmlLink": created_event.get("htmlLink"),
                    "status": "confirmed",
                    "is_mock": False
                }
            except Exception as e:
                logger.error(f"Error calling Google Calendar API for user {commitment.user_id}: {e}", exc_info=True)

        # Fallback / Unlinked User: Provide simulated 1-click web event template link
        synthetic_id = f"gcal_sim_{commitment.id or int(datetime.now().timestamp())}"
        synthetic_link = self._generate_web_event_link(
            title=event_title,
            start_time=start_dt,
            end_time=end_dt,
            description=description
        )
        logger.info(f"Generated 1-click Google Calendar web link for user {commitment.user_name} ({synthetic_id})")
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
        discord_user_id: Optional[str] = None,
        duration_minutes: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Updates event start and end time in user's calendar when pushing deadline."""
        if not event_id:
            return None

        if new_deadline.tzinfo is None:
            new_deadline = new_deadline.replace(tzinfo=timezone.utc)

        new_start = new_deadline - timedelta(minutes=duration_minutes)
        user_service = await self.get_service_for_user(discord_user_id)

        if user_service and not event_id.startswith("gcal_sim_"):
            try:
                loop = asyncio.get_running_loop()
                event = await loop.run_in_executor(
                    None,
                    lambda: user_service.events().get(
                        calendarId=self.calendar_id,
                        eventId=event_id
                    ).execute()
                )
                event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "UTC"}
                event["end"] = {"dateTime": new_deadline.isoformat(), "timeZone": "UTC"}

                updated_event = await loop.run_in_executor(
                    None,
                    lambda: user_service.events().update(
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

        return {"id": event_id, "status": "updated", "is_mock": True}

    async def complete_event(
        self,
        event_id: str,
        task_title: Optional[str] = None,
        discord_user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Marks event completed in user's calendar (changes color to Green and prepends [✅ Done])."""
        if not event_id:
            return None

        user_service = await self.get_service_for_user(discord_user_id)

        if user_service and not event_id.startswith("gcal_sim_"):
            try:
                loop = asyncio.get_running_loop()
                event = await loop.run_in_executor(
                    None,
                    lambda: user_service.events().get(
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
                    lambda: user_service.events().update(
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

        return {"id": event_id, "status": "completed", "is_mock": True}
