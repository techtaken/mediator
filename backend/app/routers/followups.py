"""Private check-ins after an agreement, and reopening the joint session.

- Each person answers their own check-in: per-term status, how it's going,
  and anything new. Their answers are never shown to the other person.
- Once both have answered a round, each sees only the term numbers where the
  two accounts differ ("accounts differ"), never a verdict on who is right.
- Either person can reopen the joint session after answering; the signed
  agreement is kept in the shared state's history.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.agents.pipeline import check_share, follow_up_reply, share_severity
from app.agents.state import append_audit, party_code, record_safety_flag
from app.agents.store import load_state
from app.agents.telemetry import track_calls
from app.auth import Actor, load_session
from app.db import get_supabase
from app.followup_store import accounts_differ, list_followups, save_answers
from app.joint_store import clear_agreement, get_agreement, now_iso
from app.ratelimit import limit_writes
from app.routers.sessions import _update_state, get_actor, language_field
from app.safety import is_crisis_or_severe_harm, with_helplines
from app.schemas import CheckInBody, FollowUpView, JointStateOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _other(party_role: str) -> str:
    return "user_b" if party_role == "user_a" else "user_a"


def _terms(session_id: str) -> list[str]:
    agreement = get_agreement(session_id)
    return [term["text"] for term in (agreement or {}).get("terms") or []]


def _current(session_id: str, party_role: str) -> dict | None:
    """This person's latest check-in that isn't still waiting to open, else the scheduled one."""
    mine = list_followups(session_id, party_role)
    visible = [row for row in mine if row["status"] in ("open", "answered")]
    if visible:
        return visible[-1]
    scheduled = [row for row in mine if row["status"] == "scheduled"]
    return scheduled[0] if scheduled else None


def _view(session: dict, me: str) -> FollowUpView:
    row = _current(session["id"], me)
    if row is None:
        return FollowUpView(status="none")
    if row["status"] == "scheduled":
        return FollowUpView(status="scheduled", round=row["round"], due_at=row["due_at"])
    theirs = next(
        (item for item in list_followups(session["id"], _other(me)) if item["round"] == row["round"]),
        None,
    )
    other_answered = bool(theirs and theirs["status"] == "answered")
    mine_answered = row["status"] == "answered"
    return FollowUpView(
        status=row["status"],
        round=row["round"],
        due_at=row["due_at"],
        terms=_terms(session["id"]),
        my_answers=row.get("answers") if mine_answered else None,
        reply=row.get("reply") if mine_answered else None,
        other_answered=other_answered,
        other_checking_in=theirs is not None,
        accounts_differ=accounts_differ(row.get("answers"), theirs.get("answers")) if (mine_answered and other_answered) else [],
        can_reopen=mine_answered and session["status"] == "resolved",
    )


@router.get("/sessions/{session_id}/followup", response_model=FollowUpView)
def get_followup(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    return _view(session, actor.party)


@router.post("/sessions/{session_id}/followup", response_model=FollowUpView)
def answer_followup(body: CheckInBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    row = _current(session["id"], actor.party)
    if row is None or row["status"] != "open":
        raise HTTPException(status_code=409, detail="There's no check-in to answer right now.")
    limit_writes(session["id"], actor.party)
    terms = _terms(session["id"])
    if any(item.term >= len(terms) for item in body.term_status):
        raise HTTPException(status_code=422, detail="Unknown term")

    answers = {
        "term_status": [item.model_dump() for item in body.term_status],
        "satisfaction": body.satisfaction,
        "new_issues": body.new_issues or None,
        "wants_to_talk": body.wants_to_talk,
    }
    code = party_code(actor.party)
    state = load_state(session)
    reply: str
    with track_calls(session["id"]):
        severity = 0
        if body.new_issues:
            # Private to this person, but still checked: someone may be unsafe.
            if is_crisis_or_severe_harm(body.new_issues):
                severity = 3
                safety = {"severity": 3, "action": "HALT_AND_REFER", "categories": ["keyword"]}
            else:
                try:
                    safety = check_share(party=code, text=body.new_issues, state=state)
                    severity = share_severity(safety)
                except Exception:
                    logger.exception("check-in safety check failed for %s", session["id"])
                    safety, severity = {"severity": 1, "action": "CONTINUE_WITH_CARE", "categories": ["safety_check_unavailable"]}, 1
        if severity >= 2:
            reply = with_helplines(
                safety.get("message_to_affected_party")
                or "Thank you for telling us. It sounds like things may not feel safe right now."
            )
            _update_state(session, lambda current: record_safety_flag(current, code, {**safety, "severity": severity}))
        else:
            written = follow_up_reply(
                party=code,
                terms=terms,
                answers=answers,
                state=state,
                language=session.get(language_field(actor.party)),
            )
            reply = written["reply"]
            answers["recommendation"] = written["recommendation"]
    save_answers(row["id"], answers, reply, now_iso())
    _update_state(
        session,
        lambda current: append_audit(current, {"stage": "FOLLOW_UP", "agent": "FOLLOW_UP", "type": f"checkin_{actor.party}"}),
    )
    return _view(load_session(session["id"]), actor.party)


@router.post("/sessions/{session_id}/reopen", response_model=JointStateOut)
def reopen_joint(ctx: tuple[dict, Actor] = Depends(get_actor)):
    """Open the joint session again after a check-in.

    The signed agreement is kept in the shared history; ideas and answers stay,
    so the two people can change answers and sign a new version.
    """
    from app.routers.joint import _joint_state

    session, actor = ctx
    if session["status"] != "resolved":
        raise HTTPException(status_code=409, detail="Only a finished session can be reopened.")
    row = _current(session["id"], actor.party)
    if row is None or row["status"] != "answered":
        raise HTTPException(status_code=409, detail="Answer your check-in first.")
    agreement = get_agreement(session["id"])

    def archive(state: dict) -> None:
        if agreement:
            state.setdefault("past_agreements", []).append(
                {
                    "version": agreement.get("version"),
                    "terms": [term["text"] for term in agreement.get("terms") or []],
                    "signed_a_at": agreement.get("signed_a_at"),
                    "signed_b_at": agreement.get("signed_b_at"),
                    "reopened_at": now_iso(),
                }
            )
        append_audit(state, {"stage": "FOLLOW_UP", "agent": "FOLLOW_UP", "type": f"reopened_by_{actor.party}"})

    _update_state(session, archive)
    reopened = (
        get_supabase()
        .table("sessions")
        .update({"status": "joint_review"})
        .eq("id", session["id"])
        .eq("status", "resolved")
        .execute()
    )
    if reopened.data and agreement:
        clear_agreement(session["id"])
    return _joint_state(session["id"], actor.party)
