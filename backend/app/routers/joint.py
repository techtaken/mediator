"""Joint session: react to ideas, agree on terms, and sign one agreement.

Rules that keep this fair:
- A party sees the other's answer to an idea only after giving their own.
- An idea is agreed only when both answered "yes".
- The agreement lists agreed ideas word for word; a model only adds a
  neutral summary and "make this specific" flags.
- Changing the agreed set clears any unsigned draft. The room is resolved
  only when both sign the same version.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.agents.pipeline import check_share, share_severity, summarize_agreement
from app.agents.state import party_code, record_safety_flag
from app.agents.store import load_state
from app.agents.telemetry import track_calls
from app.auth import Actor
from app.db import get_supabase
from app.joint_store import (
    add_idea,
    agreed_idea_ids,
    clear_agreement,
    get_agreement,
    list_ideas,
    list_responses,
    now_iso,
    save_agreement,
    seed_ideas,
    set_response,
)
from app.routers.sessions import (
    HALTED_DETAIL,
    _halt,
    _insert_message,
    _update_state,
    get_actor,
)
from app.ratelimit import limit_writes
from app.safety import with_helplines
from app.schemas import (
    AgreementOut,
    IdeaOut,
    JointStateOut,
    RespondBody,
    SignBody,
    SuggestIdeaBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

SLOW_DOWN_DETAIL = "Let's slow down a little. Try saying that in a different way."


def _other(party_role: str) -> str:
    return "user_b" if party_role == "user_a" else "user_a"


def _require_open(session: dict) -> None:
    if session["status"] == "halted":
        raise HTTPException(status_code=409, detail=HALTED_DETAIL)
    if session["status"] != "joint_review":
        raise HTTPException(status_code=409, detail="The joint session isn't open.")


def _ensure_seeded(session_id: str) -> list[dict]:
    """Rooms that reached the joint view before ideas existed get them lazily."""
    ideas = list_ideas(session_id)
    if ideas:
        return ideas
    rows = get_supabase().table("joint_summaries").select("compromises").eq("session_id", session_id).limit(1).execute().data
    texts = [str(text) for text in ((rows[0].get("compromises") or []) if rows else []) if str(text).strip()]
    seed_ideas(session_id, texts)
    return list_ideas(session_id)


def _joint_state(session_id: str, me: str) -> JointStateOut:
    other = _other(me)
    ideas = _ensure_seeded(session_id)
    responses = list_responses(session_id)
    by_key = {(row["idea_id"], row["party_role"]): row for row in responses}
    agreed = set(agreed_idea_ids(ideas, responses))

    out = []
    for idea in ideas:
        mine = by_key.get((idea["id"], me))
        theirs = by_key.get((idea["id"], other))
        reveal = mine is not None
        source = idea["source"]
        out.append(
            IdeaOut(
                id=idea["id"],
                text=idea["text"],
                source="mediator" if source == "mediator" else ("you" if source == me else "them"),
                my_response=mine["response"] if mine else None,
                my_note=mine.get("note") if mine else None,
                other_responded=theirs is not None,
                other_response=theirs["response"] if (theirs and reveal) else None,
                other_note=theirs.get("note") if (theirs and reveal) else None,
                agreed=idea["id"] in agreed,
            )
        )

    agreement = get_agreement(session_id)
    agreement_out = None
    if agreement:
        mine_at = agreement.get("signed_a_at" if me == "user_a" else "signed_b_at")
        theirs_at = agreement.get("signed_b_at" if me == "user_a" else "signed_a_at")
        agreement_out = AgreementOut(
            version=agreement["version"],
            summary=agreement.get("summary"),
            terms=[term["text"] for term in agreement.get("terms") or []],
            flags=list(agreement.get("flags") or []),
            signed_by_me_at=mine_at,
            signed_by_them_at=theirs_at,
            fully_signed=bool(mine_at and theirs_at),
            created_at=agreement.get("created_at"),
        )
    return JointStateOut(ideas=out, agreed_count=len(agreed), agreement=agreement_out)


def _screen_text(session: dict, actor: Actor, text: str) -> None:
    """Safety-check words one party is about to show the other.

    Halts the room for this party on a crisis signal, refuses on a moderate
    flag, and refuses outright if the check can't run.
    """
    code = party_code(actor.party)
    try:
        with track_calls(session["id"]):
            safety = check_share(party=code, text=text, state=load_state(session))
    except Exception as exc:
        logger.exception("joint text safety check failed for %s", session["id"])
        raise HTTPException(status_code=503, detail="We couldn't check that just now. Please try again.") from exc
    severity = share_severity(safety)
    if severity >= 3:
        _update_state(session, lambda state: record_safety_flag(state, code, {**safety, "severity": 3}))
        _halt(session["id"], actor.party, "safety")
        _insert_message(session["id"], "ai", actor.party, with_helplines(safety.get("message_to_affected_party")))
        raise HTTPException(status_code=409, detail=HALTED_DETAIL)
    if severity == 2:
        _update_state(session, lambda state: record_safety_flag(state, code, {**safety, "severity": 2}))
        raise HTTPException(status_code=409, detail=SLOW_DOWN_DETAIL)


def _invalidate_if_changed(session_id: str, before: list[str]) -> None:
    """An unsigned draft must match the current agreed set exactly."""
    agreement = get_agreement(session_id)
    if not agreement:
        return
    after = agreed_idea_ids(list_ideas(session_id), list_responses(session_id))
    if after != before:
        clear_agreement(session_id)


@router.get("/sessions/{session_id}/joint", response_model=JointStateOut)
def get_joint(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    if session["status"] not in ("joint_review", "resolved"):
        raise HTTPException(status_code=409, detail="The joint session isn't open.")
    return _joint_state(session["id"], actor.party)


@router.post("/sessions/{session_id}/ideas", response_model=JointStateOut)
def suggest_idea(body: SuggestIdeaBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_open(session)
    limit_writes(session["id"], actor.party)
    _screen_text(session, actor, body.text)
    idea = add_idea(session["id"], body.text, actor.party)
    # Suggesting an idea means it works for you.
    set_response(session["id"], idea["id"], actor.party, "yes", None)
    return _joint_state(session["id"], actor.party)


@router.post("/sessions/{session_id}/ideas/{idea_id}/response", response_model=JointStateOut)
def respond_to_idea(idea_id: str, body: RespondBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_open(session)
    limit_writes(session["id"], actor.party)
    ideas = list_ideas(session["id"])
    if not any(idea["id"] == idea_id for idea in ideas):
        raise HTTPException(status_code=404, detail="Idea not found")
    note = (body.note or "").strip() or None
    if note and body.response == "yes":
        note = None
    if note:
        _screen_text(session, actor, note)

    before = agreed_idea_ids(ideas, list_responses(session["id"]))
    set_response(session["id"], idea_id, actor.party, body.response, note)
    _invalidate_if_changed(session["id"], before)
    return _joint_state(session["id"], actor.party)


@router.post("/sessions/{session_id}/agreement/draft", response_model=JointStateOut)
def draft_agreement(ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_open(session)
    limit_writes(session["id"], actor.party)
    ideas = list_ideas(session["id"])
    agreed = agreed_idea_ids(ideas, list_responses(session["id"]))
    if not agreed:
        raise HTTPException(status_code=409, detail="Agree on at least one idea first.")
    text_by_id = {idea["id"]: idea["text"] for idea in ideas}
    terms = [{"idea_id": idea_id, "text": text_by_id[idea_id]} for idea_id in agreed]

    with track_calls(session["id"]):
        written = summarize_agreement(state=load_state(session), terms=[term["text"] for term in terms])
    previous = get_agreement(session["id"])
    save_agreement(
        session["id"],
        {
            "version": (previous["version"] + 1) if previous else 1,
            "summary": written["summary"],
            "terms": terms,
            "flags": written["flags"],
            "created_by": actor.party,
            "created_at": now_iso(),
            "signed_a_at": None,
            "signed_b_at": None,
        },
    )
    return _joint_state(session["id"], actor.party)


@router.post("/sessions/{session_id}/agreement/sign", response_model=JointStateOut)
def sign_agreement(body: SignBody, ctx: tuple[dict, Actor] = Depends(get_actor)):
    session, actor = ctx
    _require_open(session)
    limit_writes(session["id"], actor.party)
    agreement = get_agreement(session["id"])
    if not agreement:
        raise HTTPException(status_code=409, detail="There is no agreement to sign yet.")
    if agreement["version"] != body.version:
        raise HTTPException(status_code=409, detail="The agreement changed. Please read the new version before signing.")

    field = "signed_a_at" if actor.party == "user_a" else "signed_b_at"
    if not agreement.get(field):
        agreement[field] = now_iso()
        save_agreement(session["id"], {key: value for key, value in agreement.items() if key != "session_id"})
    if agreement.get("signed_a_at") and agreement.get("signed_b_at"):
        get_supabase().table("sessions").update({"status": "resolved"}).eq("id", session["id"]).eq(
            "status", "joint_review"
        ).execute()
    return _joint_state(session["id"], actor.party)
