import re

# Hard-stop phrases for Indian-context family disputes. Conservative on purpose.
TOXIC_OR_CRISIS_PATTERNS = [
    r"\bkill myself\b",
    r"\bsuicide\b",
    r"\bself[-\s]?harm\b",
    r"\bwant to die\b",
    r"\bend my life\b",
    r"\bhang myself\b",
    r"\bi will kill (him|her|them|you)\b",
    r"\bmurder\b",
    r"\brape\b",
    r"\bsexually assault\b",
    r"\bmarital rape\b",
    r"\bdomestic violence\b",
    r"\bbeat (her|him|them)\b",
    r"\bhit (her|him|them) (again|tonight|today)\b",
    r"\bchild abuse\b",
    r"\battempt to die\b",
    r"\bआत्महत्या\b",
    r"\bमार डालूँगा\b",
    r"\bमार डालूंगी\b",
    r"\bखुदकुशी\b",
]

# Single source of truth for crisis resources. The agents, the halt message and
# the frontend all read from here. Re-verify numbers before any public launch.
HELPLINES: list[str] = [
    "Emergency: 112",
    "Tele-MANAS (mental health, 24x7): 14416",
    "Women's helpline: 181",
    "iCall: 9152987821 (Mon–Sat, counselling)",
    "Vandrevala Foundation: 1860-2662-345 / 1800-2333-330",
    "AASRA: 9820466726",
]

HELPLINES_TEXT = "\n".join(f"• {line}" for line in HELPLINES)

HELP_MESSAGE = (
    "This conversation needs to pause. Mediator is not equipped for crisis, "
    "violence, or abuse. Please reach out to people who can help right now:\n\n"
    f"{HELPLINES_TEXT}\n\n"
    "If someone is in immediate danger, call local emergency services."
)

# Shown to the party who did NOT trigger a halt. It must not hint at why.
PAUSED_FOR_OTHER_MESSAGE = (
    "This session has been paused and cannot continue here. "
    "Nothing from your private room has been shared."
)


def is_crisis_or_severe_harm(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in TOXIC_OR_CRISIS_PATTERNS)


def with_helplines(text: str | None) -> str:
    """Return a supportive message that always carries the canonical helplines."""
    body = (text or "").strip()
    if not body:
        return HELP_MESSAGE
    if "112" in body and "14416" in body:
        return body
    return f"{body}\n\n{HELPLINES_TEXT}"
