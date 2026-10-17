import os

import pytest

from app.config import get_settings
from app.gemini_client import generate_intake_reply, generate_joint_summary


settings = get_settings()
os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY is not set; skip live Gemini API tests.",
)
def test_generate_intake_reply_with_real_api_key():
    text = generate_intake_reply(
        party="user_a",
        relationship_context="We keep arguing about housework and who does more.",
        user_input="I feel exhausted and ignored when chores are left to me.",
    )

    assert isinstance(text, str)
    assert len(text.strip()) > 20
    assert "I" in text or "it" in text.lower()


# @pytest.mark.skipif(
#     not os.getenv("GEMINI_API_KEY"),
#     reason="GEMINI_API_KEY is not set; skip live Gemini API tests.",
# )
# def test_generate_joint_summary_with_real_api_key():
#     payload = generate_joint_summary(
#         relationship_context="We are partners sharing a home and disagree on chores and communication.",
#         transcript_a="I feel ignored and overwhelmed because I do most chores. I want more respect.",
#         transcript_b="I feel blamed for not helping enough. I want more clarity and less pressure.",
#     )

#     assert isinstance(payload, dict)
#     assert {"user_a_perspective", "user_b_perspective", "compromises"}.issubset(payload)

#     assert isinstance(payload["user_a_perspective"], str)
#     assert isinstance(payload["user_b_perspective"], str)
#     assert isinstance(payload["compromises"], list)
#     assert len(payload["compromises"]) >= 2
#     assert all(isinstance(item, str) and item.strip() for item in payload["compromises"])
