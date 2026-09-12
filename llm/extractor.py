from datetime import datetime, timedelta, timezone
import logging
from typing import Optional
from dateutil import parser as date_parser

from llm.client import LLMClient
from llm.schemas import ExtractedCommitment, ResolutionDraft
from llm.prompts import HERMES_EXTRACTOR_SYSTEM_PROMPT, HERMES_DRAFT_UPDATE_PROMPT
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

        # Local time formatting for timezone context
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(settings.default_timezone)
            local_dt = datetime.now(tz)
            local_str = local_dt.strftime("%Y-%m-%d %I:%M %p %Z")
        except Exception:
            local_str = ref_iso

        user_prompt = f"""CURRENT_LOCAL_TIME: {local_str}
CURRENT_TIME_UTC: {ref_iso}
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

            # Ensure deadline_utc is properly formatted and localized
            if extracted.is_commitment:
                import zoneinfo
                try:
                    user_tz = zoneinfo.ZoneInfo(settings.default_timezone)
                except Exception:
                    user_tz = timezone.utc

                if extracted.implied_deadline_local:
                    try:
                        clean_str = extracted.implied_deadline_local.rstrip("Z").replace("+00:00", "")
                        parsed_dt = date_parser.parse(clean_str)
                        if parsed_dt.tzinfo is None:
                            local_aware = parsed_dt.replace(tzinfo=user_tz)
                        else:
                            local_aware = parsed_dt.astimezone(user_tz)

                        now_local = datetime.now(user_tz)
                        if local_aware <= now_local and (now_local - local_aware).total_seconds() > 60:
                            local_aware += timedelta(days=1)

                        deadline_utc_dt = local_aware.astimezone(timezone.utc).replace(tzinfo=None)
                    except Exception as pe:
                        logger.warning(f"Could not parse local deadline '{extracted.implied_deadline_local}': {pe}")
                        deadline_utc_dt = ref_time + timedelta(hours=2)
                elif extracted.implied_deadline_utc:
                    try:
                        parsed_dt = date_parser.parse(extracted.implied_deadline_utc)
                        if parsed_dt.tzinfo is not None:
                            deadline_utc_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
                        else:
                            deadline_utc_dt = parsed_dt
                    except Exception as pe:
                        logger.warning(f"Could not parse UTC deadline '{extracted.implied_deadline_utc}': {pe}")
                        deadline_utc_dt = ref_time + timedelta(hours=2)
                else:
                    deadline_utc_dt = ref_time + timedelta(hours=2)

                extracted.implied_deadline_utc = deadline_utc_dt.isoformat()

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
