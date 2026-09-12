from typing import Optional
from pydantic import BaseModel, Field


class ExtractedCommitment(BaseModel):
    is_commitment: bool = Field(
        description="Whether the speaker made an explicit or implicit promise or micro-commitment"
    )
    task_title: str = Field(
        default="",
        description="A concise, actionable title describing the committed task (e.g. 'Send updated pitch deck')"
    )
    recipient: Optional[str] = Field(
        default=None,
        description="The person or group the user promised to deliver to, if identifiable"
    )
    relative_deadline_text: str = Field(
        default="",
        description="The exact text snippet referring to the deadline or timeframe (e.g. 'by 4 PM', 'tonight', 'after lunch')"
    )
    implied_deadline_utc: Optional[str] = Field(
        default=None,
        description="The ISO 8601 UTC timestamp calculated from the message context and reference time"
    )
    context_snippet: Optional[str] = Field(
        default=None,
        description="Brief context of what triggered this commitment or why it was made"
    )
    confidence_score: float = Field(
        default=0.0,
        description="Confidence between 0.0 and 1.0 that this is an actual micro-commitment"
    )


class ResolutionDraft(BaseModel):
    suggested_reply: str = Field(
        description="A natural, empathetic, and professional message updating the recipient on progress or rescheduling"
    )
    new_suggested_deadline: Optional[str] = Field(
        default=None,
        description="New suggested deadline if an extension is proposed"
    )
