import re
from typing import Tuple

# Intent patterns indicating a self-commitment or agreement to act
INTENT_PATTERNS = [
    r"\b(i'll|i will|let me|i can|i'm gonna|i am going to|gonna|will do|promise to|plan to)\b",
    r"\b(will (review|send|look|check|push|deploy|share|upload|update|write|ping|finish|draft|fix|get back|follow up))\b",
    r"\b(give me (a minute|a sec|few minutes|an hour))\b",
    r"\b(on it|working on it)\b"
]

# Temporal indicators indicating a timeframe or deadline
TEMPORAL_PATTERNS = [
    r"\b(by|before|until|after)\s+(eod|end of day|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|noon|lunch|\d{1,2}(:\d{2})?\s*(am|pm)?)\b",
    r"\b(in\s+\d+\s*(mins?|minutes?|hours?|hrs?|days?))\b",
    r"\b(later (today|tonight|this afternoon|this evening|after lunch))\b",
    r"\b(this (afternoon|evening|weekend))\b",
    r"\b(first thing tomorrow|by the end of the (day|week))\b"
]

# Action verbs commonly tied to task delivery (including gerunds and common multi-word verbs)
ACTION_VERBS = [
    r"\b(send|sending|share|sharing|upload|uploading|review|reviewing|push|pushing|deploy|deploying|fix|fixing|write|writing|submit|submitting|deliver|delivering|email|emailing|forward|ping|pinging|create|creating|update|updating|draft|drafting|merge|merging|check|checking|look into|get back|follow up)\b"
]

_INTENT_REGEX = re.compile("|".join(INTENT_PATTERNS), re.IGNORECASE)
_TEMPORAL_REGEX = re.compile("|".join(TEMPORAL_PATTERNS), re.IGNORECASE)
_ACTION_REGEX = re.compile("|".join(ACTION_VERBS), re.IGNORECASE)


def is_commitment_candidate(message_text: str) -> Tuple[bool, str]:
    """
    Evaluates whether a message is likely to contain a micro-commitment.
    Returns (is_candidate, reason).
    """
    if not message_text or len(message_text.strip()) < 5:
        return False, "Message too short"

    # Avoid bot commands and code blocks
    stripped = message_text.strip()
    if stripped.startswith(("/", "!", "$", ">")) or stripped.startswith("```"):
        return False, "Bot command or code block"

    has_intent = bool(_INTENT_REGEX.search(stripped))
    has_temporal = bool(_TEMPORAL_REGEX.search(stripped))
    has_action = bool(_ACTION_REGEX.search(stripped))

    if has_intent and has_temporal:
        return True, "Intent + Temporal anchor detected"
    if has_intent and has_action:
        return True, "Intent + Action verb detected"
    if has_action and has_temporal:
        return True, "Action verb + Temporal anchor detected"

    return False, "No commitment patterns matched"
