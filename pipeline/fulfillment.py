import re
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from llm.client import LLMClient
from llm.prompts import HERMES_FULFILLMENT_SYSTEM_PROMPT
from db.models import Commitment

logger = logging.getLogger("CommitmentRadar.Fulfillment")

FULFILLMENT_TRIGGER_PATTERNS = [
    r"\bhere('s| is| are)\b",
    r"\bdone(\b|!|\.)",
    r"\bfinished(\b|!|\.)",
    r"\b(pushed|deployed)(\b|!|\.)",
    r"\bsent(\b|!|\.)",
    r"\battached\b",
    r"\b(pr|pull request) (is |has been )?(up|ready|open|merged)\b",
    r"\bfixed(\b|!|\.)",
    r"\buploaded\b",
    r"\bhere you go\b",
    r"\bjust (sent|pushed|uploaded|finished|shared)\b",
    r"\bcheck (this|it) out\b",
    r"\ball set\b",
    r"\bwrapped up\b"
]


def is_fulfillment_candidate(message_content: str, has_attachments: bool = False) -> bool:
    """Fast, zero-latency pre-filter to determine if a message might fulfill a commitment."""
    if has_attachments:
        return True

    text = message_content.lower().strip()
    if not text:
        return False

    # Check for URLs (e.g. shared documents, Figma, GitHub PRs)
    if "http://" in text or "https://" in text:
        return True

    for pattern in FULFILLMENT_TRIGGER_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


class FulfillmentResult(BaseModel):
    is_fulfilled: bool = False
    matched_commitment_id: Optional[int] = None
    reason: str = ""
    confidence_score: float = 0.0


class FulfillmentDetector:
    def __init__(self, client: Optional[LLMClient] = None):
        self.client = client or LLMClient()

    async def evaluate_fulfillment(
        self,
        message_text: str,
        speaker_name: str,
        pending_commitments: List[Commitment],
        attachments: Optional[List[str]] = None
    ) -> FulfillmentResult:
        """Evaluates whether the user's latest message fulfills one of their pending commitments."""
        if not pending_commitments:
            return FulfillmentResult(is_fulfilled=False, reason="No active commitments")

        commitments_summary = []
        for c in pending_commitments:
            commitments_summary.append(
                f"- ID #{c.id}: \"{c.task_title}\" (Recipient: {c.recipient or 'Team'}, Promised: \"{c.raw_text}\")"
            )

        attach_str = f"ATTACHMENTS: {', '.join(attachments)}\n" if attachments else ""

        user_prompt = f"""PENDING_COMMITMENTS:
{chr(10).join(commitments_summary)}

NEW_MESSAGE:
SPEAKER: {speaker_name}
CONTENT: "{message_text}"
{attach_str}
Determine if NEW_MESSAGE fulfills any of the PENDING_COMMITMENTS following the rules.
"""

        try:
            raw_data = await self.client.generate_json(
                system_prompt=HERMES_FULFILLMENT_SYSTEM_PROMPT,
                user_prompt=user_prompt
            )
            result = FulfillmentResult(**raw_data)

            # Validate matched_commitment_id exists in pending_commitments
            if result.is_fulfilled and result.matched_commitment_id:
                valid_ids = {c.id for c in pending_commitments}
                if result.matched_commitment_id not in valid_ids:
                    logger.warning(
                        f"LLM returned invalid matched_commitment_id {result.matched_commitment_id}. Valid: {valid_ids}"
                    )
                    result.is_fulfilled = False
                    result.matched_commitment_id = None

            return result
        except Exception as e:
            logger.error(f"Fulfillment evaluation failed: {e}", exc_info=True)
            return FulfillmentResult(is_fulfilled=False, reason=str(e))
