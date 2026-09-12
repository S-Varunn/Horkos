import pytest
from pipeline.filter import is_commitment_candidate


@pytest.mark.parametrize("text,expected", [
    # Positive: Should match candidates
    ("I'll send that PDF later tonight", True),
    ("Let me look at this after lunch", True),
    ("Will review by EOD", True),
    ("I can push the fix in 30 minutes", True),
    ("I will draft the update before tomorrow morning", True),
    ("Working on it, will deliver by Friday noon", True),
    ("I'll share the Figma link in 10 mins", True),
    ("Let me check the logs and get back to you", True),
    ("Will deploy to staging by 5pm", True),
    ("Reviewing the pull request by tomorrow", True),
    ("I can host a volleyball match at 6pm today", True),
    ("Will organize the team sync around 3pm", True),

    # Negative: Casual chatter and non-commitments
    ("lol that's awesome", False),
    ("gm everyone!", False),
    ("ok thanks", False),
    ("Can you send me the PDF?", False),
    ("What time is the meeting?", False),
    ("I already sent the email yesterday", False),
    ("nice job team", False),
    ("👍", False),
    ("```python\nprint('hello')\n```", False),
    ("/commitments list", False),
    ("!help", False)
])
def test_heuristic_pre_filter(text, expected):
    is_candidate, reason = is_commitment_candidate(text)
    assert is_candidate == expected, f"Failed for '{text}'. Expected {expected}, got {is_candidate} (Reason: {reason})"
