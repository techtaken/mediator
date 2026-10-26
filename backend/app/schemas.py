from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionStatus = Literal["intake", "building_joint", "joint_review", "resolved", "halted"]
Party = Literal["user_a", "user_b", "ai"]


class CreateSessionBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    topic: str = Field(
        min_length=3,
        max_length=300,
        description="What this is about, in the opener's words. Shown to the other person as written.",
    )
    relationship_context: str = Field(
        default="",
        max_length=500,
        description="e.g. siblings sharing a flat, in-laws, couple",
    )


class SessionOut(BaseModel):
    id: str
    status: SessionStatus
    topic: str | None = None
    relationship_context: str | None
    created_at: str
    user_a_ready: bool
    user_b_ready: bool
    party: Literal["user_a", "user_b"]
    invite_link: str | None = None
    halted_reason: str | None = None
    # "self": this party triggered the halt and sees support resources.
    # "other": a neutral pause message with no reason.
    halt_view: Literal["self", "other"] | None = None
    halt_message: str | None = None
    helplines: list[str] = Field(default_factory=list)
    # This party's own approved text, if they have shared. Never the other party's.
    my_share: str | None = None


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


class ShareOut(BaseModel):
    draft: str | None = None
    left_out: list[str] = Field(default_factory=list)
    approved: str | None = None
    approved_at: str | None = None


class ApproveShareBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=20, max_length=1200)


class IdeaOut(BaseModel):
    id: str
    text: str
    source: Literal["mediator", "you", "them"]
    my_response: Literal["yes", "change", "no"] | None = None
    my_note: str | None = None
    other_responded: bool = False
    # Only revealed once this party has answered, so nobody anchors on the other.
    other_response: Literal["yes", "change", "no"] | None = None
    other_note: str | None = None
    agreed: bool = False


class AgreementOut(BaseModel):
    version: int
    summary: str | None = None
    terms: list[str]
    flags: list[str] = Field(default_factory=list)
    signed_by_me_at: str | None = None
    signed_by_them_at: str | None = None
    fully_signed: bool = False
    created_at: str | None = None


class JointStateOut(BaseModel):
    ideas: list[IdeaOut]
    agreed_count: int
    agreement: AgreementOut | None = None


class SuggestIdeaBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=10, max_length=300)


class RespondBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    response: Literal["yes", "change", "no"]
    note: str | None = Field(default=None, max_length=300)


class SignBody(BaseModel):
    version: int


class JointSummaryOut(BaseModel):
    user_a_perspective: str
    user_b_perspective: str
    common_ground: str | None = None
    compromises: list[str]
    created_at: str
