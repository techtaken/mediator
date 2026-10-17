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

HELP_MESSAGE = (
    "This conversation needs to pause. Mediator is not equipped for crisis, "
    "violence, or abuse. Please reach out to people who can help right now:\n\n"
    "• iCall: 9152987821 (Mon–Sat, counselling)\n"
    "• Vandrevala Foundation: 1860-2662-345 / 1800-2333-330\n"
    "• AASRA: 9820466726\n"
    "• Emergency: 112\n\n"
    "If someone is in immediate danger, call local emergency services."
)


def is_crisis_or_severe_harm(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in TOXIC_OR_CRISIS_PATTERNS)
