from enum import Enum
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict


class CommitmentStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    COMPLETED = "COMPLETED"
    SNOOZED = "SNOOZED"
    CANCELLED = "CANCELLED"


def utc_now() -> datetime:
    # Use timezone-aware UTC datetime with tzinfo stripped for clean SQLite ISO format
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Commitment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[int] = None
    user_id: str
    user_name: str
    channel_id: str
    channel_name: Optional[str] = None
    guild_id: Optional[str] = None
    message_id: str
    raw_text: str
    task_title: str
    recipient: Optional[str] = None
    deadline_utc: datetime
    relative_deadline_text: str = ""
    context_snippet: Optional[str] = None
    status: CommitmentStatus = CommitmentStatus.PENDING
    calendar_event_id: Optional[str] = None
    calendar_event_link: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserGoogleAuth(BaseModel):
    discord_user_id: str
    google_email: Optional[str] = None
    token_json: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserCalendarTemplate(BaseModel):
    discord_user_id: str
    title_template: str = "{task}"
    completed_template: str = "[Done] {task}"
    description_template: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelCalendarTemplate(BaseModel):
    channel_id: str
    guild_id: Optional[str] = None
    channel_name: Optional[str] = None
    title_template: str = "{task}"
    completed_template: str = "[Done] {task}"
    description_template: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


