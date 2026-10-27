from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionStatus = Literal["intake", "building_joint", "joint_review", "resolved", "halted"]
Party = Literal["user_a", "user_b", "ai"]
Language = Literal["en", "hinglish", "hi"]


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
    # Whether this party has accepted how Mediator works. Required before chatting.
    i_consented: bool = False
    # Person A only, while the other person hasn't joined yet.
    invite_expires_at: str | None = None
    other_joined: bool = True
    # Rooms are removed this many days after they open (0: kept until deleted).
    retention_days: int = 0
    my_data_deleted: bool = False
    # This party's language for the mediator's replies (None: match how they write).
    my_language: Language | None = None


class DeletedOut(BaseModel):
    deleted: bool


class RoomSummaryOut(BaseModel):
    id: str
    status: SessionStatus
    topic: str | None = None
    created_at: str
    user_a_ready: bool
    user_b_ready: bool


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
    # This party's private "think it through" questions, if they asked for them.
    my_questions: list["RealityQuestionOut"] = Field(default_factory=list)


class RealityQuestionOut(BaseModel):
    type: Literal["alternative", "practical", "their_view"]
    question: str


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
    # The joint session was opened again after a check-in.
    reopened: bool = False


class SuggestIdeaBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=10, max_length=300)


class RespondBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    response: Literal["yes", "change", "no"]
    note: str | None = Field(default=None, max_length=300)


class SignBody(BaseModel):
    version: int
    # Days until this person's private check-in (0: no check-in). None: the default.
    checkin_days: Literal[0, 7, 14, 30] | None = None


class LanguageBody(BaseModel):
    language: Language


class TranslationOut(BaseModel):
    language: Language
    original: str
    # None when no checked translation could be made; the original always shows.
    translation: str | None = None


class TermStatus(BaseModel):
    term: int = Field(ge=0, le=50)
    status: Literal["kept", "partly", "not_kept"]


class CheckInBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    term_status: list[TermStatus] = Field(max_length=50)
    satisfaction: int = Field(ge=1, le=5)
    new_issues: str | None = Field(default=None, max_length=500)
    wants_to_talk: bool = False


class FollowUpView(BaseModel):
    status: Literal["none", "scheduled", "open", "answered"]
    round: int = 0
    due_at: str | None = None
    terms: list[str] = Field(default_factory=list)
    # Only this person's own answers, never the other's.
    my_answers: dict | None = None
    reply: str | None = None
    other_answered: bool = False
    # False when the other person has no check-in this round (they opted out).
    other_checking_in: bool = False
    # Term numbers the two accounts differ on, once both have answered.
    accounts_differ: list[int] = Field(default_factory=list)
    can_reopen: bool = False


class JointSummaryOut(BaseModel):
    user_a_perspective: str
    user_b_perspective: str
    common_ground: str | None = None
    compromises: list[str]
    created_at: str


IdeaOut.model_rebuild()
