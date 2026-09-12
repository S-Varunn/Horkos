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


class RestaurantOption(BaseModel):
    name: str = Field(description="Name of the restaurant or eatery")
    cuisine_type: str = Field(default="", description="Cuisine type or specialty")
    price_range: str = Field(default="$$", description="Price level: $, $$, $$$, or $$$$")
    vibe: str = Field(default="", description="Atmosphere or vibe of the place")
    highlight_dish: str = Field(default="", description="Top recommended dish or specialty")
    why_go: str = Field(default="", description="Why this spot fits the group")


class RestaurantRecommendations(BaseModel):
    cuisine: str = Field(default="Food", description="Cuisine or craving requested")
    location: str = Field(default="", description="Location context")
    summary: str = Field(default="", description="Brief 1-sentence lively summary")
    options: list[RestaurantOption] = Field(default_factory=list, description="List of recommended restaurant options")


class AcceptedPlanCheck(BaseModel):
    has_accepted_plan: bool = Field(default=False, description="Whether a specific meal/dinner plan was already accepted")
    agreed_plan: Optional[str] = Field(default=None, description="The accepted cuisine, restaurant, or plan name")
    confidence: float = Field(default=0.0, description="Confidence score between 0.0 and 1.0")
    context_quote: Optional[str] = Field(default=None, description="Snippet showing the agreement")
