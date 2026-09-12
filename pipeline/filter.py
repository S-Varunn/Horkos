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


# Dining inquiry patterns indicating someone is asking about meals / food decisions
DINING_INQUIRY_PATTERNS = [
    # "where you want to eat", "where do you want to eat", "where should we eat", "where to eat"
    r"\bwhere\s+(?:(?:do\s+you|you|do\s+we|we|should\s+we|are\s+we|can\s+we|to)\s+)?(?:want\s+to\s+)?(?:eat|grab\s+(?:food|lunch|dinner|a\s+bite)|go\s+for\s+(?:lunch|dinner|food)|dine)\b",
    # Any meal/dinner/lunch plan question: "do we have a dinner plan?", "what is the dinner plan?", "any dinner plans", "dinner plan?"
    r"\b(?:dinner|lunch|food|breakfast|meal)\s+plans?\b",
    r"\bplans?\s+for\s+(?:dinner|lunch|food|breakfast|meal)\b",
    # "did we decide on dinner?", "what did we decide for dinner?"
    r"\b(?:did\s+we|have\s+we|what\s+did\s+we)\s+(?:decide|pick|choose)\b",
    # "what do you want to eat?", "what should we eat?", "what are we eating?"
    r"\bwhat\s+(?:do\s+you|do\s+we|should\s+we|are\s+we|you\s+guys)\s+(?:want\s+to\s+eat|having|doing\s+for\s+(?:dinner|lunch)|eating)\b",
    r"\bwhat\s+should\s+we\s+eat\b",
    # "any food ideas?", "any restaurant recommendations?", "food suggestions"
    r"\b(?:any|got\s+any)\s+(?:food|lunch|dinner|restaurant)\s+(?:ideas|suggestions|recs|recommendations)\b",
    # "anyone hungry?", "who wants food/lunch/dinner?"
    r"\b(?:anyone|who(?:'s|\s+is)?)\s+(?:hungry|want\s+(?:food|lunch|dinner|to\s+eat))\b",
    # "how about we guys go eat indian tonight?", "how about sushi tonight?"
    r"\b(?:how|what)\s+about\s+.*?\b(?:eat|grab|dinner|lunch|food|tonight)\b",
    # "go eat ... tonight / for dinner"
    r"\b(?:go\s+)?(?:eat|grab|get)\s+.*?\b(?:tonight|for\s+dinner|for\s+lunch)\b",
    # "wanna / want to go eat / grab dinner"
    r"\b(?:wanna|want\s+to)\s+(?:go\s+)?(?:eat|grab|get)\b",
    # "who's down for tacos?", "up for dinner?"
    r"\b(?:down|up)\s+for\s+.*?\b(?:dinner|lunch|food|tacos|sushi|pizza|burgers)\b",
    # Standalone inquiry: "For dinner?", "For lunch?"
    r"\bfor\s+(?:dinner|lunch|breakfast)\s*\?",
    # Cuisine preferences: "Mexican food also works for me?"
    r"\b(?:food|cuisine)\s+.*?\b(?:works|sounds\s+good|fine)\b",
    # Dilemmas / choices: "should we go pizza or sushi this time", "should we do thai or indian"
    r"\b(?:should\s+we|do\s+we|shall\s+we|can\s+we|wanna|want\s+to)\s+(?:do|get|have|eat|grab|go(?:\s+for)?)\s+.*?\b(?:pizza|sushi|tacos|burgers|mexican|indian|thai|chinese|italian|ramen|pasta|bbq|korean|vietnamese|wings|mediterranean|shawarma|greek|steak|seafood|fast\s+food|food|dinner|lunch)\b.*?\b(?:or|vs)\b",
    # Direct food vs food: "pizza or sushi?", "tacos vs burgers"
    r"\b(?:pizza|sushi|tacos|burgers|mexican|indian|thai|chinese|italian|ramen|pasta|bbq|korean|vietnamese|wings|mediterranean|shawarma|greek|steak|seafood)\s+(?:or|vs)\s+(?:pizza|sushi|tacos|burgers|mexican|indian|thai|chinese|italian|ramen|pasta|bbq|korean|vietnamese|wings|mediterranean|shawarma|greek|steak|seafood)\b",
    # "should we go/do [cuisine] this time / tonight"
    r"\b(?:should\s+we|do\s+we|shall\s+we|wanna|want\s+to)\s+(?:do|get|have|eat|grab|go(?:\s+for)?)\s+.*?\b(?:pizza|sushi|tacos|burgers|mexican|indian|thai|chinese|italian|ramen|pasta|bbq|korean|vietnamese|wings|mediterranean|shawarma|greek|steak|seafood|food|dinner|lunch)\b.*?\b(?:this\s+time|tonight|today|later)\b"
]

_DINING_REGEX = re.compile("|".join(DINING_INQUIRY_PATTERNS), re.IGNORECASE)


def is_dining_inquiry(message_text: str) -> Tuple[bool, str]:
    """
    Evaluates whether a message is an open dining or food-decision inquiry
    (e.g., 'where you want to eat?', 'what is the dinner plan?').
    Returns (is_dining, reason).
    """
    if not message_text or len(message_text.strip()) < 5:
        return False, "Message too short"

    stripped = message_text.strip()
    if stripped.startswith(("/", "!", "$", ">")) or stripped.startswith("```"):
        return False, "Bot command or code block"

    if _DINING_REGEX.search(stripped):
        return True, "Dining/meal inquiry pattern detected"

    return False, "No dining inquiry matched"
