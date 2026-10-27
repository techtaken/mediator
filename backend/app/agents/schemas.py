"""Lenient output contracts for each agent.

Models coerce what they can (e.g. "2" -> 2, out-of-range scores clamped) and fill
safe defaults, so one sloppy field doesn't sink a turn. Anything that cannot be
coerced fails validation and the call is retried. Unknown fields are kept.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class SafetyOut(_Out):
    flag: bool = False
    severity: int = 0
    categories: list[str] = Field(default_factory=list)
    evidence: str = ""
    action: Literal["CONTINUE", "CONTINUE_WITH_CARE", "PAUSE_AND_CHECK", "HALT_AND_REFER"] = "CONTINUE"
    message_to_affected_party: str | None = None
    block_outgoing_message: bool = False

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> int:
        return _clamp(value, 0, 3, 0)

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value: Any) -> list[Any]:
        return [str(item) for item in _as_list(value)]

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value: Any) -> str:
        return "" if value is None else str(value)


class OrchestratorOut(_Out):
    stage: str = "STORYTELLING"
    focus: str | None = None
    gate_triggered: int | None = None
    next_agent: str
    mode: Literal["private", "joint"] = "private"
    instructions_to_agent: str = ""
    reason: str = ""

    @field_validator("focus", mode="before")
    @classmethod
    def _focus(cls, value: Any) -> str | None:
        return None if value is None else str(value)

    @field_validator("gate_triggered", mode="before")
    @classmethod
    def _gate(cls, value: Any) -> int | None:
        return None if value is None else _clamp(value, 1, 10, 5)


class CaucusUpdates(_Out):
    intensity: int | None = None
    feels_heard: bool | None = None
    willing: bool | Literal["unclear"] | None = None
    positions: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    new_issues: list[dict[str, Any]] = Field(default_factory=list)
    hidden_concerns: list[str] = Field(default_factory=list)
    resolution_needs: list[str] = Field(default_factory=list)

    @field_validator("intensity", mode="before")
    @classmethod
    def _intensity(cls, value: Any) -> int | None:
        return None if value is None else _clamp(value, 0, 10, 5)

    @field_validator("positions", "interests", "hidden_concerns", "resolution_needs", mode="before")
    @classmethod
    def _strings(cls, value: Any) -> list[str]:
        return [str(item) for item in _as_list(value) if item is not None]

    @field_validator("new_issues", mode="before")
    @classmethod
    def _issues(cls, value: Any) -> list[dict[str, Any]]:
        return [item for item in _as_list(value) if isinstance(item, dict)]


class ShareProposal(_Out):
    text: str | None = None
    approved_by_party: bool = False


class CaucusOut(_Out):
    reply_to_party: str
    state_updates: CaucusUpdates = Field(default_factory=CaucusUpdates)
    share_proposal: ShareProposal = Field(default_factory=ShareProposal)
    safety_concern: bool = False
    private_notes: str | None = None

    @field_validator("state_updates", "share_proposal", mode="before")
    @classmethod
    def _null_to_default(cls, value: Any) -> Any:
        return {} if value is None else value


class AuditorOut(_Out):
    scores: dict[str, Any] = Field(default_factory=dict)
    overall: int = 0
    issues_found: list[Any] = Field(default_factory=list)
    final_message: str = ""
    blocked: bool = False
    alert_orchestrator: bool = False

    @field_validator("overall", mode="before")
    @classmethod
    def _overall(cls, value: Any) -> int:
        return _clamp(value, 0, 3, 0)

    @field_validator("final_message", mode="before")
    @classmethod
    def _final(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("issues_found", mode="before")
    @classmethod
    def _found(cls, value: Any) -> list[Any]:
        return _as_list(value)


class JointVoiceOut(_Out):
    message: str
    user_a_perspective: str = ""
    user_b_perspective: str = ""


class DiagnosticianOut(_Out):
    issues: list[dict[str, Any]] = Field(default_factory=list)
    issue_links: list[dict[str, Any]] = Field(default_factory=list)
    escalation_stage: int | None = None
    escalation_evidence: list[Any] = Field(default_factory=list)
    agenda: list[str] = Field(default_factory=list)
    mediation_suitable: bool = True
    suitability_reason: str = ""
    style: Literal["facilitative", "transformative", "narrative"] = "facilitative"
    style_reason: str = ""

    @field_validator("style", mode="before")
    @classmethod
    def _style(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"facilitative", "transformative", "narrative"} else "facilitative"

    @field_validator("style_reason", "suitability_reason", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("escalation_stage", mode="before")
    @classmethod
    def _stage(cls, value: Any) -> int | None:
        return None if value is None else _clamp(value, 1, 9, 3)

    @field_validator("agenda", mode="before")
    @classmethod
    def _agenda(cls, value: Any) -> list[str]:
        return [str(item) for item in _as_list(value)]


class OptionsOut(_Out):
    options: list[Any] = Field(default_factory=list)
    open_questions: list[Any] = Field(default_factory=list)


class HandoffOut(_Out):
    urgency: Literal["URGENT", "STANDARD"] = "STANDARD"
    message_to_parties: str = ""

    @field_validator("urgency", mode="before")
    @classmethod
    def _urgency(cls, value: Any) -> str:
        return "URGENT" if str(value or "").upper() == "URGENT" else "STANDARD"

    @field_validator("message_to_parties", mode="before")
    @classmethod
    def _message(cls, value: Any) -> str:
        return "" if value is None else str(value)


class DrafterOut(_Out):
    summary: str = ""
    flags: list[str] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("flags", mode="before")
    @classmethod
    def _flags(cls, value: Any) -> list[str]:
        return [str(item) for item in _as_list(value) if item][:4]


class ShareDraftOut(_Out):
    summary: str
    left_out: list[str] = Field(default_factory=list)

    @field_validator("left_out", mode="before")
    @classmethod
    def _left_out(cls, value: Any) -> list[str]:
        return [str(item) for item in _as_list(value) if item]


REALITY_TYPES = ("alternative", "practical", "their_view")


class RealityQuestion(_Out):
    type: str = ""
    question: str = ""

    @field_validator("type", "question", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()


class RealityOut(_Out):
    questions: list[RealityQuestion] = Field(default_factory=list)

    @field_validator("questions", mode="before")
    @classmethod
    def _questions(cls, value: Any) -> list[Any]:
        # Accept bare strings in type order as well as {type, question} objects.
        out = []
        for index, item in enumerate(_as_list(value)):
            if isinstance(item, str):
                kind = REALITY_TYPES[index] if index < len(REALITY_TYPES) else ""
                out.append({"type": kind, "question": item})
            elif isinstance(item, dict):
                out.append(item)
        return out


class FollowUpOut(_Out):
    reply_to_party: str
    satisfaction: int | None = None
    new_issues: list[Any] = Field(default_factory=list)
    recommendation: Literal["NEXT_CHECKIN", "REOPEN", "REFER_TO_HUMAN"] = "NEXT_CHECKIN"

    @field_validator("satisfaction", mode="before")
    @classmethod
    def _satisfaction(cls, value: Any) -> int | None:
        return None if value is None else _clamp(value, 1, 5, 3)

    @field_validator("recommendation", mode="before")
    @classmethod
    def _recommendation(cls, value: Any) -> str:
        text = str(value or "").strip().upper()
        return text if text in {"NEXT_CHECKIN", "REOPEN", "REFER_TO_HUMAN"} else "NEXT_CHECKIN"

    @field_validator("new_issues", mode="before")
    @classmethod
    def _issues(cls, value: Any) -> list[Any]:
        return _as_list(value)


class TranslatorOut(_Out):
    translation: str


ROLE_SCHEMAS: dict[str, type[BaseModel]] = {
    "SAFETY_GUARDIAN": SafetyOut,
    "ORCHESTRATOR": OrchestratorOut,
    "CAUCUS": CaucusOut,
    "NEUTRALITY_AUDITOR": AuditorOut,
    "JOINT_VOICE": JointVoiceOut,
    "DIAGNOSTICIAN": DiagnosticianOut,
    "OPTIONS": OptionsOut,
    "HANDOFF": HandoffOut,
    "SHARE_DRAFTER": ShareDraftOut,
    "DRAFTER": DrafterOut,
    "REALITY_TESTER": RealityOut,
    "FOLLOW_UP": FollowUpOut,
    "TRANSLATOR": TranslatorOut,
}


def validate_output(role: str, data: dict[str, Any]) -> dict[str, Any]:
    schema = ROLE_SCHEMAS.get(role)
    if schema is None:
        return data
    return schema.model_validate(data).model_dump()
