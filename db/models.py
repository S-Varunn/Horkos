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
    guild_id: Optional[str] = None
    message_id: str
    raw_text: str
    task_title: str
    recipient: Optional[str] = None
    deadline_utc: datetime
    relative_deadline_text: str = ""
    context_snippet: Optional[str] = None
    status: CommitmentStatus = CommitmentStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
