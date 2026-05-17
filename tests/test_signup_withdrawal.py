"""
Signup withdrawal tests.

Covers:
    Use-case logic
    1.  Officer can withdraw any signup.
    2.  Owner can withdraw any signup.
    3.  Member can withdraw own signup (by display_name — dev-auth phase).
    4.  Member cannot withdraw another player's signup → PermissionDenied.
    5.  Withdrawal sets withdrawn_at.
    6.  Already-withdrawn signup raises ConflictError.
    7.  Active assignment blocks withdrawal → ConflictError.
    8.  Removal of assignment unblocks re-withdrawal (assignment guard is per-state).
    9.  signup_intent.withdrawn event emitted.
    10. Archived operation blocks withdrawal → ConflictError.
    11. Completed operation blocks withdrawal → ConflictError.
    12. Draft operation blocks withdrawal → ConflictError.

    Repository filtering
    13. get_participants_for_operation excludes withdrawn signups.
    14. get_signups_with_display_names excludes withdrawn signups.
    15. get_signup_intents excludes withdrawn signups.

    HTTP / template
    16. Withdraw button visible to officer on every signup row.
    17. Withdraw button visible to member only on their own row.
    18. Withdraw button absent for member on another's signup.
    19. POST withdraw by officer succeeds → redirects to signup page.
    20. POST withdraw by member on own signup succeeds.
    21. POST withdraw by member on another's signup → error flash.
    22. Withdrawn signup absent from signup page list.
    23. Withdrawn player absent from planner unassigned panel.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, PermissionDenied
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _add_member(ws_id: str, owner_id: str, name: str) -> dict:
    user = make_user(name)
    use_cases.add_workspace_member(ws_id, owner_id, name, role="member")
    return user


def _add_officer(ws_id: str, owner_id: str, name: str) -> dict:
    user = make_user(name)
    use_cases.add_workspace_member(ws_id, owner_id, name, role="officer")
    return user


def _make_planning_ws_op(owner_name: str, slug: str):
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    return owner, ws, op


def _signup(ws_id, op_id, display_name, role="Tank"):
    return use_cases.submit_signup_intent(ws_id, op_id, display_name, role)


def _withdraw(ws_id, op_id, actor_id, signup_id):
    use_cases.withdraw_signup_intent(ws_id, op_id, actor_id, signup_id)


def _signup_url(ws_slug, op_id):
    return f"/workspaces/{ws_slug}/operations/{op_id}/signup"


def _planner_url(ws_slug, op_id):
    return f"/workspaces/{ws_slug}/operations/{op_id}/planner"


def _withdraw_url(ws_slug, op_id, signup_id):
    return f"/workspaces/{ws_slug}/operations/{op_id}/signups/{signup_id}/withdraw"


# ---------------------------------------------------------------------------
# Use-case tests
# ---------------------------------------------------------------------------

def test_officer_can_withdraw_any_signup():
    owner, ws, op = _make_planning_ws_op("WdOwner1", "wd-officer")
    officer = _add_officer(ws["id"], owner["id"], "WdOfficer1")
    signup = _signup(ws["id"], op["id"], "TargetPlayer1")

    _withdraw(ws["id"], op["id"], officer["id"], signup["id"])

    with database.transaction() as db:
        row = repositories.get_signup_intent_by_id(db, signup["id"], ws["id"])
    assert row["withdrawn_at"] is not None


def test_owner_can_withdraw_any_signup():
    owner, ws, op = _make_planning_ws_op("WdOwner2", "wd-owner-withdraw")
    signup = _signup(ws["id"], op["id"], "TargetPlayer2")

    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    with database.transaction() as db:
        row = repositories.get_signup_intent_by_id(db, signup["id"], ws["id"])
    assert row["withdrawn_at"] is not None


def test_member_can_withdraw_own_signup():
    owner, ws, op = _make_planning_ws_op("WdOwner3", "wd-member-own")
    member = _add_member(ws["id"], owner["id"], "WdMember3")
    signup = _signup(ws["id"], op["id"], "WdMember3")  # same display_name as member user

    _withdraw(ws["id"], op["id"], member["id"], signup["id"])

    with database.transaction() as db:
        row = repositories.get_signup_intent_by_id(db, signup["id"], ws["id"])
    assert row["withdrawn_at"] is not None


def test_member_cannot_withdraw_another_signup():
    owner, ws, op = _make_planning_ws_op("WdOwner4", "wd-member-other")
    member = _add_member(ws["id"], owner["id"], "WdMember4")
    signup = _signup(ws["id"], op["id"], "SomeOtherPlayer4")

    with pytest.raises(PermissionDenied):
        _withdraw(ws["id"], op["id"], member["id"], signup["id"])


def test_withdrawal_sets_withdrawn_at():
    owner, ws, op = _make_planning_ws_op("WdOwner5", "wd-sets-ts")
    signup = _signup(ws["id"], op["id"], "TimestampPlayer")

    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    with database.transaction() as db:
        row = repositories.get_signup_intent_by_id(db, signup["id"], ws["id"])
    assert row["withdrawn_at"] is not None
    assert "T" in row["withdrawn_at"]  # ISO-8601 format


def test_already_withdrawn_raises_conflict():
    owner, ws, op = _make_planning_ws_op("WdOwner6", "wd-already")
    signup = _signup(ws["id"], op["id"], "AlreadyGone")

    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    with pytest.raises(ConflictError, match="already been withdrawn"):
        _withdraw(ws["id"], op["id"], owner["id"], signup["id"])


def test_active_assignment_blocks_withdrawal():
    owner, ws, op = _make_planning_ws_op("WdOwner7", "wd-assigned")
    signup = _signup(ws["id"], op["id"], "AssignedPlayer")

    with database.transaction() as db:
        slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        participant = repositories.find_participant_by_display_name(db, ws["id"], "AssignedPlayer")

    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], participant["id"]
    )

    with pytest.raises(ConflictError, match="active slot assignment"):
        _withdraw(ws["id"], op["id"], owner["id"], signup["id"])


def test_removing_assignment_allows_withdrawal():
    owner, ws, op = _make_planning_ws_op("WdOwner8", "wd-unassign-then-withdraw")
    signup = _signup(ws["id"], op["id"], "FlexPlayer")

    with database.transaction() as db:
        slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        participant = repositories.find_participant_by_display_name(db, ws["id"], "FlexPlayer")

    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], participant["id"]
    )
    use_cases.remove_assignment(ws["id"], op["id"], assignment["id"])

    # Should not raise now
    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    with database.transaction() as db:
        row = repositories.get_signup_intent_by_id(db, signup["id"], ws["id"])
    assert row["withdrawn_at"] is not None


def test_withdrawal_emits_event():
    owner, ws, op = _make_planning_ws_op("WdOwner9", "wd-event")
    signup = _signup(ws["id"], op["id"], "EventPlayer")

    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])
    types = [e["event_type"] for e in events]
    assert "signup_intent.withdrawn" in types


def test_archived_operation_blocks_withdrawal():
    owner, ws, op = _make_planning_ws_op("WdOwner10", "wd-archived")
    signup = _signup(ws["id"], op["id"], "ArchivedPlayer")
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    with pytest.raises(ConflictError, match="archived"):
        _withdraw(ws["id"], op["id"], owner["id"], signup["id"])


def test_completed_operation_blocks_withdrawal():
    owner, ws, op = _make_planning_ws_op("WdOwner11", "wd-completed")
    signup = _signup(ws["id"], op["id"], "CompletedPlayer")
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])

    with pytest.raises(ConflictError, match="completed"):
        _withdraw(ws["id"], op["id"], owner["id"], signup["id"])


def test_locked_operation_allows_withdrawal():
    """Withdrawal of an unassigned signup on a locked operation is allowed."""
    owner, ws, op = _make_planning_ws_op("WdOwner11b", "wd-locked-ok")
    signup = _signup(ws["id"], op["id"], "UnassignedLocked")
    use_cases.lock_operation(ws["id"], op["id"])

    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    with database.transaction() as db:
        row = repositories.get_signup_intent_by_id(db, signup["id"], ws["id"])
    assert row["withdrawn_at"] is not None


def test_draft_operation_blocks_withdrawal():
    """Draft operations cannot have signups, but guard should still reject."""
    owner = make_user("WdOwner12")
    ws = make_workspace(owner_user_id=owner["id"], slug="wd-draft")
    op = make_operation(ws["id"])
    # Manually insert a signup_intent to bypass the submission status gate
    from datetime import datetime, timezone
    import uuid
    with database.transaction() as db:
        participant = repositories.find_or_create_participant(db, ws["id"], "DraftPlayer")
        fake_signup = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "guild_operation_id": op["id"],
            "participant_id": participant["id"],
            "preferred_role": "Tank",
            "preferred_build_name": None,
            "willingness": "specific",
            "availability": "confirmed",
            "source": "web",
            "withdrawn_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db.execute(
            """INSERT INTO signup_intents
               (id, guild_workspace_id, guild_operation_id, participant_id,
                preferred_role, preferred_build_name, willingness, availability,
                source, withdrawn_at, created_at)
               VALUES (:id, :guild_workspace_id, :guild_operation_id, :participant_id,
                :preferred_role, :preferred_build_name, :willingness, :availability,
                :source, :withdrawn_at, :created_at)""",
            fake_signup,
        )
        signup_id = fake_signup["id"]

    with pytest.raises(ConflictError, match="draft"):
        _withdraw(ws["id"], op["id"], owner["id"], signup_id)


# ---------------------------------------------------------------------------
# Repository filtering tests
# ---------------------------------------------------------------------------

def test_get_participants_for_operation_excludes_withdrawn():
    owner, ws, op = _make_planning_ws_op("WdOwner13", "wd-repo-parts")
    signup_a = _signup(ws["id"], op["id"], "ActiveParticipant")
    signup_b = _signup(ws["id"], op["id"], "WithdrawnParticipant", role="Healer")

    _withdraw(ws["id"], op["id"], owner["id"], signup_b["id"])

    with database.transaction() as db:
        participants = repositories.get_participants_for_operation(db, op["id"], ws["id"])
    names = [p["display_name"] for p in participants]
    assert "ActiveParticipant" in names
    assert "WithdrawnParticipant" not in names


def test_get_signups_with_display_names_excludes_withdrawn():
    owner, ws, op = _make_planning_ws_op("WdOwner14", "wd-repo-signups-dn")
    signup_a = _signup(ws["id"], op["id"], "ActiveSignup")
    signup_b = _signup(ws["id"], op["id"], "WithdrawnSignup", role="DPS")

    _withdraw(ws["id"], op["id"], owner["id"], signup_b["id"])

    with database.transaction() as db:
        rows = repositories.get_signups_with_display_names(db, op["id"], ws["id"])
    names = [r["display_name"] for r in rows]
    assert "ActiveSignup" in names
    assert "WithdrawnSignup" not in names


def test_get_signup_intents_excludes_withdrawn():
    owner, ws, op = _make_planning_ws_op("WdOwner15", "wd-repo-intents")
    signup_a = _signup(ws["id"], op["id"], "IntentActive")
    signup_b = _signup(ws["id"], op["id"], "IntentWithdrawn", role="Support")

    _withdraw(ws["id"], op["id"], owner["id"], signup_b["id"])

    with database.transaction() as db:
        rows = repositories.get_signup_intents(db, op["id"], ws["id"])
    pids = [r["participant_id"] for r in rows]
    assert signup_a["participant_id"] in pids
    assert signup_b["participant_id"] not in pids


# ---------------------------------------------------------------------------
# HTTP / template tests
# ---------------------------------------------------------------------------

def test_withdraw_button_visible_to_officer_on_all_rows():
    owner, ws, op = _make_planning_ws_op("WdOwner16", "wd-http-btn-officer")
    officer = _add_officer(ws["id"], owner["id"], "WdOfficer16")
    _signup(ws["id"], op["id"], "OtherPlayer16")

    client = TestClient(app)
    _login(client, "WdOfficer16")

    resp = client.get(_signup_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Withdraw" in resp.text
    assert "/withdraw" in resp.text


def test_withdraw_button_visible_to_member_only_for_own_row():
    owner, ws, op = _make_planning_ws_op("WdOwner17", "wd-http-btn-member")
    member = _add_member(ws["id"], owner["id"], "WdMember17")
    _signup(ws["id"], op["id"], "WdMember17")       # own
    _signup(ws["id"], op["id"], "OtherPlayer17", role="Healer")  # someone else's

    client = TestClient(app)
    _login(client, "WdMember17")

    resp = client.get(_signup_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    # The member sees exactly one withdraw form (their own)
    assert resp.text.count("/withdraw") == 1


def test_withdraw_button_absent_for_member_on_other_signup():
    owner, ws, op = _make_planning_ws_op("WdOwner18", "wd-http-btn-absent")
    member = _add_member(ws["id"], owner["id"], "WdMember18")
    # Only another player signs up, not the member
    _signup(ws["id"], op["id"], "OtherPlayer18")

    client = TestClient(app)
    _login(client, "WdMember18")

    resp = client.get(_signup_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "/withdraw" not in resp.text


def test_http_officer_withdraw_redirects_to_signup_page():
    owner, ws, op = _make_planning_ws_op("WdOwner19", "wd-http-redir")
    officer = _add_officer(ws["id"], owner["id"], "WdOfficer19")
    signup = _signup(ws["id"], op["id"], "RedirPlayer")

    client = TestClient(app, follow_redirects=False)
    _login(client, "WdOfficer19")

    resp = client.post(_withdraw_url(ws["slug"], op["id"], signup["id"]))
    assert resp.status_code in (302, 303)
    assert "/signup" in resp.headers["location"]


def test_http_member_withdraw_own_succeeds():
    owner, ws, op = _make_planning_ws_op("WdOwner20", "wd-http-member-own")
    member = _add_member(ws["id"], owner["id"], "WdMember20")
    signup = _signup(ws["id"], op["id"], "WdMember20")

    client = TestClient(app)
    _login(client, "WdMember20")

    resp = client.post(_withdraw_url(ws["slug"], op["id"], signup["id"]))
    assert resp.status_code == 200
    assert "Signup withdrawn" in resp.text or "withdrawn" in resp.text.lower()


def test_http_member_withdraw_other_shows_error():
    owner, ws, op = _make_planning_ws_op("WdOwner21", "wd-http-member-other")
    member = _add_member(ws["id"], owner["id"], "WdMember21")
    signup = _signup(ws["id"], op["id"], "OtherPlayer21")

    client = TestClient(app)
    _login(client, "WdMember21")

    resp = client.post(_withdraw_url(ws["slug"], op["id"], signup["id"]))
    assert resp.status_code == 200
    # Error flash present
    assert "error" in resp.text.lower() or "only withdraw" in resp.text.lower() or "permission" in resp.text.lower()


def test_withdrawn_signup_absent_from_signup_page():
    owner, ws, op = _make_planning_ws_op("WdOwner22", "wd-http-absent-list")
    signup = _signup(ws["id"], op["id"], "VanishingPlayer")
    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])

    client = TestClient(app)
    _login(client, "WdOwner22")

    resp = client.get(_signup_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "VanishingPlayer" not in resp.text


def test_withdrawn_player_absent_from_planner_unassigned():
    owner, ws, op = _make_planning_ws_op("WdOwner23", "wd-http-planner")
    signup = _signup(ws["id"], op["id"], "PlannerVanish")
    _withdraw(ws["id"], op["id"], owner["id"], signup["id"])
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "WdOwner23")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "PlannerVanish" not in resp.text
