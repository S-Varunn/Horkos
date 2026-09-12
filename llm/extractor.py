from datetime import datetime, timedelta, timezone
import logging
from typing import Optional
from dateutil import parser as date_parser

from llm.client import LLMClient
from llm.schemas import (
    ExtractedCommitment,
    ResolutionDraft,
    RestaurantOption,
    RestaurantRecommendations,
    AcceptedPlanCheck
)
from llm.prompts import (
    HERMES_EXTRACTOR_SYSTEM_PROMPT,
    HERMES_DRAFT_UPDATE_PROMPT,
    HERMES_RESTAURANT_SUGGESTION_PROMPT,
    HERMES_CHECK_ACCEPTED_PLAN_PROMPT
)
from config import settings

logger = logging.getLogger("CommitmentRadar.Extractor")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CommitmentExtractor:
    def __init__(self, client: Optional[LLMClient] = None):
        self.client = client or LLMClient()

    async def extract_commitment(
        self,
        message_text: str,
        author_name: str,
        reference_time: Optional[datetime] = None,
        context_snippet: Optional[str] = None
    ) -> ExtractedCommitment:
        """
        Analyzes a chat message using Hermes to determine if it is a commitment
        and extract task, recipient, and UTC deadline.
        """
        ref_time = reference_time or utc_now()
        ref_iso = ref_time.strftime("%Y-%m-%d %H:%M:%S UTC")

        user_prompt = f"""CURRENT_TIME_UTC: {ref_iso}
USER_TIMEZONE: {settings.default_timezone}
SPEAKER: {author_name}
MESSAGE_TEXT: "{message_text}"
"""
        if context_snippet:
            user_prompt += f"RECENT_CHANNEL_CONTEXT: \"{context_snippet}\"\n"

        user_prompt += "\nExtract any micro-commitment from the SPEAKER's message following the rules."

        try:
            raw_data = await self.client.generate_json(
                system_prompt=HERMES_EXTRACTOR_SYSTEM_PROMPT,
                user_prompt=user_prompt
            )
            extracted = ExtractedCommitment(**raw_data)

            # Ensure deadline_utc is properly formatted or defaulted if missing
            if extracted.is_commitment:
                if not extracted.implied_deadline_utc:
                    extracted.implied_deadline_utc = (ref_time + timedelta(hours=2)).isoformat()
                else:
                    # Sanitize date parsing
                    try:
                        parsed_dt = date_parser.parse(extracted.implied_deadline_utc)
                        # If naive, assume UTC
                        if parsed_dt.tzinfo is None:
                            extracted.implied_deadline_utc = parsed_dt.isoformat()
                    except Exception as pe:
                        logger.warning(f"Could not parse deadline string '{extracted.implied_deadline_utc}': {pe}")
                        extracted.implied_deadline_utc = (ref_time + timedelta(hours=2)).isoformat()

            return extracted
        except Exception as e:
            logger.error(f"Commitment extraction failed: {e}")
            return ExtractedCommitment(
                is_commitment=False,
                confidence_score=0.0
            )

    async def generate_resolution_draft(
        self,
        task_title: str,
        recipient: Optional[str],
        original_deadline_text: str,
        speaker_name: str
    ) -> ResolutionDraft:
        """
        Drafts a contextual update message for the user to send with one click.
        """
        user_prompt = f"""SPEAKER: {speaker_name}
TASK: {task_title}
RECIPIENT: {recipient or 'the team'}
ORIGINAL_TIMEFRAME: {original_deadline_text}

Generate a short, natural update message to post in the channel."""

        try:
            data = await self.client.generate_json(
                system_prompt=HERMES_DRAFT_UPDATE_PROMPT,
                user_prompt=user_prompt
            )
            return ResolutionDraft(**data)
        except Exception as e:
            logger.error(f"Draft generation failed: {e}")
            recipient_mention = f"@{recipient} " if recipient else ""
            return ResolutionDraft(
                suggested_reply=f"Hey {recipient_mention}quick update: working on '{task_title}' right now, will have it over shortly!",
                new_suggested_deadline=None
            )

    async def generate_restaurant_suggestions(
        self,
        cuisine_or_craving: str,
        location: Optional[str] = None
    ) -> RestaurantRecommendations:
        """
        Generates 2-3 tailored restaurant recommendations based on cuisine and location.
        """
        loc = location or settings.default_location
        user_prompt = f"""CUISINE_OR_CRAVING: {cuisine_or_craving}
LOCATION_OR_CITY: {loc}

Suggest 2 to 3 top-notch, authentic food or restaurant options for the group. Respond in valid JSON."""

        try:
            data = await self.client.generate_json(
                system_prompt=HERMES_RESTAURANT_SUGGESTION_PROMPT,
                user_prompt=user_prompt
            )
            return RestaurantRecommendations(**data)
        except Exception as e:
            logger.error(f"Restaurant recommendation failed: {e}")
            # Fallback recommendations if LLM API is unavailable
            cuisine_clean = cuisine_or_craving.title()
            return RestaurantRecommendations(
                cuisine=cuisine_clean,
                location=loc,
                summary=f"Here are top-rated {cuisine_clean} recommendations to break the deadlock:",
                options=[
                    RestaurantOption(
                        name=f"The Rustic {cuisine_clean} Spot",
                        cuisine_type=cuisine_clean,
                        price_range="$$",
                        vibe="Lively & cozy, great for groups",
                        highlight_dish="House Specialty Tasting Platter",
                        why_go=f"Beloved local favorite known for quick seating and crowd-pleasing {cuisine_clean}."
                    ),
                    RestaurantOption(
                        name=f"Metro {cuisine_clean} Kitchen & Bar",
                        cuisine_type=f"Modern {cuisine_clean}",
                        price_range="$$$",
                        vibe="Modern atmosphere with great drinks",
                        highlight_dish="Chef's Seasonal Feature",
                        why_go="High energy, great ambiance, and fast service for dinner groups."
                    ),
                    RestaurantOption(
                        name=f"Street Style {cuisine_clean} Co.",
                        cuisine_type=f"Fast Casual {cuisine_clean}",
                        price_range="$",
                        vibe="Quick, casual & vibrant",
                        highlight_dish="Loaded Signature Box",
                        why_go="Zero wait time, highly rated, and satisfying for everyone."
                    )
                ]
            )

    async def check_for_accepted_plan(
        self,
        recent_messages: list[str]
    ) -> AcceptedPlanCheck:
        """
        Analyzes messages from the last 3 minutes to determine if the group
        already confirmed or accepted a dinner/meal plan.
        """
        if not recent_messages:
            return AcceptedPlanCheck(has_accepted_plan=False)

        chat_transcript = "\n".join(recent_messages)
        user_prompt = f"""MESSAGES_LAST_3_MINUTES:
{chat_transcript}

Did the group already agree on or accept a specific dinner/food plan or restaurant?"""

        try:
            data = await self.client.generate_json(
                system_prompt=HERMES_CHECK_ACCEPTED_PLAN_PROMPT,
                user_prompt=user_prompt
            )
            return AcceptedPlanCheck(**data)
        except Exception as e:
            logger.warning(f"LLM check_for_accepted_plan failed: {e}")
            # Local regex heuristic fallback for common agreement phrases
            agreement_patterns = [
                r"\b(?:let's|lets|down for|agreed on|locked in|sounds good let's do|pizza it is)\s+(?:do|get|have|eat)?\s*([a-zA-Z\s]+)",
                r"\b([a-zA-Z\s]+)\s+(?:sounds good to everyone|it is|works for everyone)\b"
            ]
            import re
            for line in recent_messages:
                for pat in agreement_patterns:
                    match = re.search(pat, line, re.IGNORECASE)
                    if match:
                        plan_candidate = match.group(0).strip()
                        return AcceptedPlanCheck(
                            has_accepted_plan=True,
                            agreed_plan=plan_candidate.title(),
                            confidence=0.8,
                            context_quote=line
                        )
            return AcceptedPlanCheck(has_accepted_plan=False)
