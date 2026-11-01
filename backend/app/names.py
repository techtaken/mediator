"""People's names. The other person sees them, and they reach the mediator's
prompts, so a name can only be a name: no digits, links or long text."""

from __future__ import annotations

import unicodedata

NAME_MAX_LENGTH = 40
NAME_DETAIL = "Please enter just your name, using letters."
NAME_REQUIRED_DETAIL = "Tell us your name first."
INVITED_NAME_DETAIL = "Please enter just their name, using letters."

_ALLOWED_MARKS = " .'\u2019-\u200c\u200d"  # the last two are joiners some Indian scripts need


def clean_name(value: str) -> str | None:
    """The name tidied up, or None if it isn't one. Letters in any script."""
    name = " ".join(unicodedata.normalize("NFC", value).split())
    if not name or len(name) > NAME_MAX_LENGTH:
        return None
    has_letter = False
    for char in name:
        kind = unicodedata.category(char)[0]
        if kind == "L":
            has_letter = True
        elif kind != "M" and char not in _ALLOWED_MARKS:
            return None
    return name if has_letter else None
