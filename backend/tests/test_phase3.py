"""Phase 3: check-ins, referral inbox, live updates, language, reality checks, style."""

import json
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import pipeline
from app.agents.prompts import STYLES
from app.agents.state import new_shared_state
from app.auth import Actor, load_session
from app.followup_store import accounts_differ, open_due_followups
from app.routers import admin as admin_module
from app.routers import followups as followups_module
from app.routers import jobs as jobs_module
from app.routers import joint as joint_module
from app.routers import sessions as sessions_module
from app.routers.sessions import _room_fingerprint, get_actor
from tests.fakes import FakeSupabase
from tests.test_pipeline import SAFE, FakeAgents

app = FastAPI()
for module in (sessions_module, joint_module, followups_module, admin_module, jobs_module):
    app.include_router(module.router)
client = TestClient(app)

A_TEXT = "I felt hurt when the Goa trip happened without me. I want to be asked."
B_TEXT = "I thought they weren't interested, so I didn't ask. I see it hurt."
A_PRIVATE = "A's private chat line about the cousin's wedding"
B_PRIVATE = "B secretly saved ten thousand for the trip"
TERMS = ["Ask in the family group before booking trips.", "Plan one outing together next month."]


@pytest.fixture
def db():
    fake = FakeSupabase()
    targets = (
        "app.routers.sessions.get_supabase",
        "app.routers.joint.get_supabase",
        "app.routers.followups.get_supabase",
        "app.routers.admin.get_supabase",
        "app.joint_store.get_supabase",
        "app.followup_store.get_supabase",
        "app.agents.store.get_supabase",
        "app.agents.telemetry.get_supabase",
        "app.auth.get_supabase",
        "app.retention.get_supabase",
    )
    patches = [patch(target, return_value=fake) for target in targets]
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


@pytest.fixture
def as_party():
    current = {"party": "user_a"}

    def actor_override(session_id: str):
        party = current["party"]
        actor = Actor(party, user_id="user_123") if party == "user_a" else Actor(party, invite_token="token_xyz")
        return load_session(session_id), actor

    app.dependency_overrides[get_actor] = actor_override
    yield lambda party: current.update(party=party)
    app.dependency_overrides.clear()


@pytest.fixture
def agents():
    fake = FakeAgents(
        DRAFTER={"summary": "You disagreed about being included.", "flags": []},
        FOLLOW_UP={"reply_to_party": "Thanks for checking in. It sounds like the outing helped.", "recommendation": "NEXT_CHECKIN"},
        REALITY_TESTER={
            "questions": [
                {"type": "alternative", "question": "If you don't agree on trips, what happens next time?"},
                {"type": "practical", "question": "Who would post in the family group first?"},
                {"type": "their_view", "question": "How might they see being asked first?"},
            ]
        },
        TRANSLATOR={"translation": "मुझे बुरा लगा जब गोवा ट्रिप मेरे बिना हुई। मैं चाहता हूँ कि मुझसे पूछा जाए।"},
    )
    targets = [
        (joint_module, "check_share", pipeline.check_share),
        (joint_module, "summarize_agreement", pipeline.summarize_agreement),
        (joint_module, "reality_check", pipeline.reality_check),
        (joint_module, "translate_share", pipeline.translate_share),
        (followups_module, "check_share", pipeline.check_share),
        (followups_module, "follow_up_reply", pipeline.follow_up_reply),
        (admin_module, "referral_brief", pipeline.referral_brief),
        (sessions_module, "handle_party_turn", pipeline.handle_party_turn),
        (sessions_module, "draft_share", pipeline.draft_share),
    ]
    patches = [patch.object(module, name, partial(func, caller=fake)) for module, name, func in targets]
    for item in patches:
        item.start()
    yield fake
    for item in patches:
        item.stop()


def _joint_room(db, status="joint_review", **overrides):
    state = new_shared_state("sess_abc")
    state["approved_shares"] = {"A": [A_TEXT], "B": [B_TEXT]}
    db.add_session(status=status, user_a_ready=True, user_b_ready=True, mediation_state=state,
                   consented_a_at="2026-06-01T00:00:00Z", consented_b_at="2026-06-01T00:00:00Z", **overrides)
    db.table("joint_summaries").insert(
        {"session_id": "sess_abc", "user_a_perspective": A_TEXT, "user_b_perspective": B_TEXT, "compromises": TERMS}
    ).execute()
    for party, text in (("user_a", A_PRIVATE), ("user_b", B_PRIVATE)):
        db.table("messages").insert({"session_id": "sess_abc", "sender_role": party, "audience_role": party, "content": text}).execute()
        db.table("private_memories").insert({"session_id": "sess_abc", "party_role": party, "notes": text, "profile": {}}).execute()
    return db


def _ideas():
    return client.get("/api/sessions/sess_abc/joint").json()["ideas"]


def _sign_both(as_party, days_a=None, days_b=None):
    """Agree on both ideas, draft, and sign as both parties."""
    as_party("user_a")
    ids = [idea["id"] for idea in _ideas()]
    for party in ("user_a", "user_b"):
        as_party(party)
        for idea_id in ids:
            client.post(f"/api/sessions/sess_abc/ideas/{idea_id}/response", json={"response": "yes"})
    as_party("user_a")
    version = client.post("/api/sessions/sess_abc/agreement/draft").json()["agreement"]["version"]
    for party, days in (("user_a", days_a), ("user_b", days_b)):
        as_party(party)
        body = {"version": version} if days is None else {"version": version, "checkin_days": days}
        assert client.post("/api/sessions/sess_abc/agreement/sign", json=body).status_code == 200


# --- Follow-up check-ins -----------------------------------------------------------


def test_signing_schedules_a_check_in_per_person(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party, days_a=7, days_b=None)
    assert db.rows("sessions")[0]["status"] == "resolved"
    rows = {row["party_role"]: row for row in db.rows("followups")}
    signed = max(db.rows("agreements")[0]["signed_a_at"], db.rows("agreements")[0]["signed_b_at"])
    signed_at = datetime.fromisoformat(signed)
    assert datetime.fromisoformat(rows["user_a"]["due_at"]) - signed_at == timedelta(days=7)
    assert datetime.fromisoformat(rows["user_b"]["due_at"]) - signed_at == timedelta(days=14)  # the default
    assert all(row["status"] == "scheduled" and row["round"] == 1 for row in rows.values())


def test_no_check_in_when_someone_opts_out(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party, days_a=0, days_b=30)
    assert [row["party_role"] for row in db.rows("followups")] == ["user_b"]
    _open_checkins(db)
    as_party("user_b")
    view = client.post("/api/sessions/sess_abc/followup", json={"term_status": [], "satisfaction": 4}).json()
    assert view["other_checking_in"] is False and view["other_answered"] is False


def test_job_opens_check_ins_that_are_due(db):
    db.table("followups").insert([
        {"session_id": "s1", "party_role": "user_a", "round": 1, "status": "scheduled", "due_at": "2026-06-01T00:00:00+00:00"},
        {"session_id": "s1", "party_role": "user_b", "round": 1, "status": "scheduled", "due_at": "2026-12-01T00:00:00+00:00"},
    ]).execute()
    assert open_due_followups(datetime(2026, 7, 1, tzinfo=timezone.utc)) == 1
    assert [row["status"] for row in db.rows("followups")] == ["open", "scheduled"]
    assert open_due_followups(datetime(2026, 7, 1, tzinfo=timezone.utc)) == 0


def test_followup_job_endpoint(db):
    settings = SimpleNamespace(job_token="tok", admin_email_set=set())
    with patch("app.auth.get_settings", return_value=settings):
        assert client.post("/api/jobs/followups").status_code == 401
        assert client.post("/api/jobs/followups", headers={"X-Job-Token": "tok"}).json() == {"opened": 0}


def _open_checkins(db):
    for row in db.rows("followups"):
        row["status"] = "open"


def test_scheduled_check_in_shows_only_its_date(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    view = client.get("/api/sessions/sess_abc/followup").json()
    assert view["status"] == "scheduled" and view["due_at"] and view["terms"] == []


def test_answering_a_check_in_privately(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    _open_checkins(db)
    as_party("user_b")
    view = client.get("/api/sessions/sess_abc/followup").json()
    assert view["status"] == "open" and view["terms"] == TERMS
    answer = {"term_status": [{"term": 0, "status": "kept"}, {"term": 1, "status": "not_kept"}],
              "satisfaction": 3, "new_issues": "We still haven't planned the outing."}
    view = client.post("/api/sessions/sess_abc/followup", json=answer).json()
    assert view["status"] == "answered" and view["reply"].startswith("Thanks for checking in")
    assert view["my_answers"]["satisfaction"] == 3
    assert view["other_answered"] is False and view["accounts_differ"] == []
    (call,) = agents.of("FOLLOW_UP")
    assert "We still haven't planned the outing." in call["prompt"]
    for secret in (A_PRIVATE, B_PRIVATE):
        assert secret not in call["prompt"]
    # A sees that B answered, but nothing of what B said.
    as_party("user_a")
    a_view = client.get("/api/sessions/sess_abc/followup").json()
    assert a_view["status"] == "open" and a_view["my_answers"] is None
    assert "outing" not in json.dumps(a_view).replace(TERMS[1], "")


def test_accounts_differ_is_shown_without_a_verdict(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    _open_checkins(db)
    for party, status in (("user_a", "kept"), ("user_b", "not_kept")):
        as_party(party)
        client.post("/api/sessions/sess_abc/followup", json={
            "term_status": [{"term": 0, "status": "kept"}, {"term": 1, "status": status}], "satisfaction": 4})
    for party in ("user_a", "user_b"):
        as_party(party)
        view = client.get("/api/sessions/sess_abc/followup").json()
        assert view["accounts_differ"] == [2] and view["other_answered"] is True
        assert view["can_reopen"] is True
        # Only my own answers come back.
        mine = "kept" if party == "user_a" else "not_kept"
        assert view["my_answers"]["term_status"][1]["status"] == mine


def test_accounts_differ_helper():
    mine = {"term_status": [{"term": 0, "status": "kept"}, {"term": 1, "status": "partly"}]}
    theirs = {"term_status": [{"term": 0, "status": "kept"}, {"term": 1, "status": "kept"}]}
    assert accounts_differ(mine, theirs) == [2]
    assert accounts_differ(mine, None) == []


def test_crisis_words_in_a_check_in_get_helplines_not_the_agent(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    _open_checkins(db)
    as_party("user_a")
    view = client.post("/api/sessions/sess_abc/followup", json={
        "term_status": [], "satisfaction": 1, "new_issues": "Some days I want to end my life."}).json()
    assert "112" in view["reply"] and "14416" in view["reply"]
    assert agents.of("FOLLOW_UP") == []
    assert db.rows("sessions")[0]["mediation_state"]["safety"]["flags"]["A"]["severity"] == 3


def test_check_in_needs_an_open_one(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    as_party("user_a")
    assert client.post("/api/sessions/sess_abc/followup", json={"term_status": [], "satisfaction": 3}).status_code == 409


def test_reopen_after_a_check_in(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    as_party("user_a")
    assert client.post("/api/sessions/sess_abc/reopen").status_code == 409  # answer first
    _open_checkins(db)
    client.post("/api/sessions/sess_abc/followup", json={"term_status": [{"term": 1, "status": "not_kept"}], "satisfaction": 2})
    state = client.post("/api/sessions/sess_abc/reopen").json()
    assert state["reopened"] is True and state["agreement"] is None
    assert state["agreed_count"] == 2  # answers stay, so they can redraft
    session = db.rows("sessions")[0]
    assert session["status"] == "joint_review"
    (past,) = session["mediation_state"]["past_agreements"]
    assert past["terms"] == TERMS
    # Signing again schedules round 2.
    _sign_both(as_party)
    assert {row["round"] for row in db.rows("followups")} == {1, 2}


def test_deleting_my_data_removes_my_check_ins(db, as_party, agents):
    _joint_room(db)
    _sign_both(as_party)
    as_party("user_b")
    client.post("/api/sessions/sess_abc/delete-my-data")
    assert [row["party_role"] for row in db.rows("followups")] == ["user_a"]


# --- Referral inbox -------------------------------------------------------------------

ADMIN = {"Authorization": "Bearer admin"}


@pytest.fixture
def admin_auth():
    with patch("app.auth._decode_claims", return_value={"sub": "admin-1", "email": "admin@example.com"}), \
         patch("app.auth.get_settings", return_value=SimpleNamespace(admin_email_set={"admin@example.com"})):
        yield


def test_referral_inbox_lists_only_referrals(db, admin_auth):
    db.add_session(id="r1", status="halted", halt_kind="referral", halted_for="user_b", created_at="2026-06-02")
    db.add_session(id="r2", status="halted", halt_kind="safety", halted_for="user_a", created_at="2026-06-03")
    db.add_session(id="r3", status="halted", halt_kind="referral", halted_for="user_a", created_at="2026-06-04",
                   referral_handled_at="2026-06-05T00:00:00Z")
    ids = [row["id"] for row in client.get("/api/admin/referrals", headers=ADMIN).json()["referrals"]]
    assert ids == ["r3", "r1"]
    open_ids = [row["id"] for row in client.get("/api/admin/referrals?handled=false", headers=ADMIN).json()["referrals"]]
    assert open_ids == ["r1"]
    assert "invite_token_b" not in json.dumps(client.get("/api/admin/referrals", headers=ADMIN).json())


def test_handoff_brief_uses_shared_content_only(db, admin_auth, agents):
    _joint_room(db, status="halted", halt_kind="referral", halted_for="user_b")
    data = client.post("/api/admin/referrals/sess_abc/brief", headers=ADMIN).json()
    assert data["brief"]["urgency"] in ("STANDARD", "URGENT")
    assert "message_to_parties" not in data["brief"]
    (call,) = agents.of("HANDOFF")
    assert A_TEXT in call["prompt"] and B_TEXT in call["prompt"]  # approved words are shared
    for secret in (A_PRIVATE, B_PRIVATE):
        assert secret not in call["prompt"]
    assert "Person B asked to talk to a person" in call["prompt"]
    session = db.rows("sessions")[0]
    assert session["referral_brief"] and session["referral_brief_at"]
    assert any(row["payload"].get("type") == "referral_brief" for row in db.rows("mediation_audit_events"))


def test_mark_referral_handled(db, admin_auth):
    db.add_session(id="r1", status="halted", halt_kind="referral", halted_for="user_b")
    db.add_session(id="r2", status="intake")
    assert client.post("/api/admin/referrals/r2/handled", headers=ADMIN).status_code == 409
    assert client.post("/api/admin/referrals/r1/handled", headers=ADMIN).json() == {"handled": True}
    row = db.rows("sessions", id="r1")[0]
    assert row["referral_handled_at"] and row["referral_handled_by"] == "admin@example.com"


def test_referral_endpoints_need_an_admin(db):
    with patch("app.auth._decode_claims", return_value={"sub": "u", "email": "someone@example.com"}), \
         patch("app.auth.get_settings", return_value=SimpleNamespace(admin_email_set={"admin@example.com"})):
        assert client.get("/api/admin/referrals", headers=ADMIN).status_code == 403
        assert client.post("/api/admin/referrals/r1/brief", headers=ADMIN).status_code == 403


# --- Live updates ------------------------------------------------------------------------


def test_fingerprint_changes_with_my_view_only(db):
    db.add_session(consented_a_at="2026-06-01T00:00:00Z", consented_b_at="2026-06-01T00:00:00Z")
    before = _room_fingerprint("sess_abc", "user_a")
    # The other person's private activity must not show up as a change.
    db.table("messages").insert({"session_id": "sess_abc", "sender_role": "user_b", "audience_role": "user_b", "content": "x"}).execute()
    db.rows("sessions")[0]["state_version"] = 7
    db.rows("sessions")[0]["updated_at"] = "2026-06-02T00:00:00Z"
    assert _room_fingerprint("sess_abc", "user_a") == before
    db.table("messages").insert({"session_id": "sess_abc", "sender_role": "ai", "audience_role": "user_a", "content": "y"}).execute()
    assert _room_fingerprint("sess_abc", "user_a") != before
    after = _room_fingerprint("sess_abc", "user_a")
    db.rows("sessions")[0]["user_b_ready"] = True  # visible to A
    assert _room_fingerprint("sess_abc", "user_a") != after


def _events(max_seconds=0.3, poll=0.05):
    with patch.object(sessions_module, "_sse_limits", return_value=(max_seconds, poll)):
        with client.stream("GET", "/api/sessions/sess_abc/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            return response.read().decode()


def test_event_stream_sends_a_change_then_reconnect(db, as_party):
    db.add_session()
    body = _events()
    assert body.startswith("retry: 3000")
    assert body.count("event: change") == 1
    assert body.rstrip().endswith('event: reconnect\ndata: {}')


def test_event_stream_says_gone_when_the_room_is_deleted(db, as_party):
    db.add_session()
    calls = {"n": 0}
    real = sessions_module._room_fingerprint

    def flaky(session_id, party):
        calls["n"] += 1
        if calls["n"] > 1:
            db.tables["sessions"].clear()
        return real(session_id, party)

    with patch.object(sessions_module, "_room_fingerprint", side_effect=flaky):
        body = _events(max_seconds=1)
    assert "event: gone" in body


# --- Language -------------------------------------------------------------------------------


def test_language_choice_reaches_caucus_and_rewrites_the_welcome(db, as_party, agents):
    db.add_session(topic="Goa trip", consented_a_at="2026-06-01T00:00:00Z", consented_b_at="2026-06-01T00:00:00Z")
    db.table("messages").insert({"session_id": "sess_abc", "sender_role": "ai", "audience_role": "user_a",
                                 "content": sessions_module.welcome_a("Goa trip")}).execute()
    data = client.post("/api/sessions/sess_abc/language", json={"language": "hi"}).json()
    assert data["my_language"] == "hi"
    (welcome,) = db.rows("messages", audience_role="user_a")
    assert "यह आपका निजी कमरा है" in welcome["content"] and "AI" in welcome["content"]
    client.post("/api/sessions/sess_abc/messages", json={"content": "Mujhe bura laga"})
    assert "Hindi, written in Devanagari script" in agents.of("CAUCUS")[0]["prompt"]
    # After they've written, the welcome is left alone.
    client.post("/api/sessions/sess_abc/language", json={"language": "en"})
    first = db.rows("messages", audience_role="user_a")[0]
    assert "यह आपका निजी कमरा है" in first["content"]


def test_unknown_language_is_rejected(db, as_party):
    db.add_session()
    assert client.post("/api/sessions/sess_abc/language", json={"language": "fr"}).status_code == 422


def test_share_drafter_gets_the_language(db, as_party, agents):
    db.add_session(language_a="hinglish", consented_a_at="2026-06-01T00:00:00Z", consented_b_at="2026-06-01T00:00:00Z")
    client.post("/api/sessions/sess_abc/share/draft")
    assert "Reply in Hinglish" in agents.of("SHARE_DRAFTER")[0]["prompt"]


def test_translation_of_the_other_persons_words(db, as_party, agents):
    _joint_room(db, language_a="hi")
    data = client.get("/api/sessions/sess_abc/translation").json()
    # A reads B's words: original always included, translation labelled by the UI.
    assert data["original"] == B_TEXT and data["language"] == "hi"
    assert data["translation"].startswith("मुझे")
    (call,) = agents.of("TRANSLATOR")
    assert B_TEXT in call["prompt"] and "Hindi (Devanagari script)" in call["prompt"]
    for secret in (A_PRIVATE, B_PRIVATE, A_TEXT):
        assert secret not in call["prompt"]
    client.get("/api/sessions/sess_abc/translation")
    assert len(agents.of("TRANSLATOR")) == 1  # cached
    assert db.rows("joint_summaries")[0]["user_b_perspective"] == B_TEXT  # original untouched


def test_translation_that_fails_safety_is_not_shown(db, as_party, agents):
    _joint_room(db)
    agents.overrides["SAFETY_GUARDIAN"] = lambda m: {**SAFE, "block_outgoing_message": True} if "outbound" in m["LATEST_EVENT"] else dict(SAFE)
    data = client.get("/api/sessions/sess_abc/translation?language=hi").json()
    assert data["translation"] is None and data["original"] == B_TEXT
    assert db.rows("share_translations") == []


def test_translation_with_a_wild_length_is_dropped():
    agents = FakeAgents(TRANSLATOR={"translation": "ok"})
    assert pipeline.translate_share(text=A_TEXT, language="hi", state=new_shared_state("x"), caller=agents) is None


# --- Reality checks ---------------------------------------------------------------------------


def test_think_it_through_gives_three_private_questions(db, as_party, agents):
    _joint_room(db)
    idea = _ideas()[0]
    state = client.post(f"/api/sessions/sess_abc/ideas/{idea['id']}/think").json()
    questions = state["ideas"][0]["my_questions"]
    assert [item["type"] for item in questions] == ["alternative", "practical", "their_view"]
    assert questions[1]["question"] == "Who would post in the family group first?"
    (call,) = agents.of("REALITY_TESTER")
    assert TERMS[0] in call["prompt"]
    for secret in (A_PRIVATE, B_PRIVATE):
        assert secret not in call["prompt"]
    # Cached, and never shown to the other person.
    client.post(f"/api/sessions/sess_abc/ideas/{idea['id']}/think")
    assert len(agents.of("REALITY_TESTER")) == 1
    as_party("user_b")
    assert _ideas()[0]["my_questions"] == []


def test_both_parties_get_the_same_question_types_even_if_the_model_skips_one():
    agents = FakeAgents(REALITY_TESTER={"questions": [{"type": "practical", "question": "Who starts?"},
                                                       {"type": "bogus", "question": "Isn't A right?"}]})
    state = new_shared_state("x")
    for party in ("A", "B"):
        questions = pipeline.reality_check(party=party, idea="Plan an outing.", state=state, caller=agents)
        assert [item["type"] for item in questions] == ["alternative", "practical", "their_view"]
        assert questions[1]["question"] == "Who starts?"
        assert questions[0]["question"] == pipeline.REALITY_FALLBACK["en"]["alternative"]
        assert all("A right" not in item["question"] for item in questions)


def test_unsafe_questions_are_replaced_by_the_prewritten_ones():
    def guardian(mapping):
        event = json.loads(mapping["LATEST_EVENT"])
        return {**SAFE, "block_outgoing_message": event.get("direction") == "outbound"}

    agents = FakeAgents(SAFETY_GUARDIAN=guardian,
                        REALITY_TESTER={"questions": ["You'll regret it if you say no.", "Q2", "Q3"]})
    questions = pipeline.reality_check(party="A", idea="Plan an outing.", state=new_shared_state("x"),
                                       language="hi", caller=agents)
    assert [item["question"] for item in questions] == list(pipeline.REALITY_FALLBACK["hi"].values())


def test_questions_fall_back_when_safety_cannot_run():
    agents = FakeAgents(SAFETY_GUARDIAN=RuntimeError("down"))
    questions = pipeline.reality_check(party="A", idea="Plan an outing.", state=new_shared_state("x"), caller=agents)
    assert [item["question"] for item in questions] == list(pipeline.REALITY_FALLBACK["en"].values())


# --- Mediation style ---------------------------------------------------------------------------


def _shared_state():
    state = new_shared_state("x")
    state["approved_shares"] = {"A": [A_TEXT], "B": [B_TEXT]}
    return state


def test_diagnostician_picks_a_style_used_by_options_and_joint_voice():
    agents = FakeAgents(DIAGNOSTICIAN={"issues": [], "agenda": [], "style": "Transformative", "style_reason": "Feeling left out."})
    built = pipeline.run_joint_pipeline(state=_shared_state(), caller=agents)
    assert built["state"]["style"] == "transformative"
    for role in ("OPTIONS", "JOINT_VOICE"):
        assert STYLES["transformative"] in agents.of(role)[0]["prompt"]


def test_unknown_style_falls_back_to_facilitative():
    agents = FakeAgents(DIAGNOSTICIAN={"issues": [], "style": "A_IS_RIGHT_STYLE"})
    built = pipeline.run_joint_pipeline(state=_shared_state(), caller=agents)
    assert built["state"]["style"] == "facilitative"
    assert STYLES["facilitative"] in agents.of("OPTIONS")[0]["prompt"]
