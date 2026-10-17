from typing import Literal

from pydantic import BaseModel, Field

SessionStatus = Literal["intake", "joint_review", "resolved", "halted"]
Party = Literal["user_a", "user_b", "ai"]


class CreateSessionBody(BaseModel):
    relationship_context: str = Field(
        default="",
        max_length=500,
        description="e.g. siblings sharing a flat, in-laws, couple",
    )


class SessionOut(BaseModel):
    id: str
    status: SessionStatus
    relationship_context: str | None
    created_at: str
    user_a_ready: bool
    user_b_ready: bool
    party: Literal["user_a", "user_b"]
    invite_link: str | None = None
    halted_reason: str | None = None


class MessageOut(BaseModel):
    id: str
    sender_role: Party
    audience_role: Party
    content: str
    is_private: bool
    created_at: str


class SendMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ReadyBody(BaseModel):
    ready: bool = True


class JointSummaryOut(BaseModel):
    user_a_perspective: str
    user_b_perspective: str
    compromises: list[str]
    created_at: str
