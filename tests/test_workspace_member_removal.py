"""
Workspace member removal tests.

Covers:
  Use case:
    1.  Owner removes member → membership deleted, event emitted.
    2.  Owner removes officer → membership deleted.
    3.  Officer removes member → membership deleted.
    4.  Officer cannot remove another officer → PermissionDenied.
    5.  Officer cannot remove owner → PermissionDenied.
    6.  Owner cannot remove owner → PermissionDenied.
    7.  Actor cannot remove themselves → PermissionDenied.
    8.  Member cannot remove anyone → PermissionDenied.
    9.  Target with active assignment → ConflictError with clear message.
    10. Target with removed (soft-deleted) assignment → removal allowed.
    11. Users, participants, signup_intents, assignments preserved after removal.
    12. workspace.member.removed event is emitted with correct payload.
    13. Removing non-existent member → NotFoundError.

  Repository:
    14. count_active_assignments_for_participant counts only status='assigned'.
    15. find_participant_by_display_name returns correct row / None.
    16. delete_workspace_member removes only the membership row.

  HTTP route:
    17. GET /members shows member list (owner access).
    18. GET /members denied for plain members.
    19. POST /members/{id}/remove → success redirect with flash.
    20. POST /members/{id}/remove with active assignment → error flash.
    21. POST /members/{id}/remove by officer on officer → error flash.
    22. POST /members/{id}/remove self → error flash.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, PermissionDenied
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _add_member(ws_id: str, display_name: str, role: str = "member") -> dict:
    owner = _get_owner_id(ws_id)
    return use_cases.add_workspace_member(ws_id, owner, display_name, role=role)


def _get_owner_id(ws_id: str) -> str:
    with database.transaction() as db:
        members = repositories.list_workspace_members(db, ws_id)
    for m in members:
        if m["role"] == "owner":
            return m["user_id"]
    raise AssertionError("No owner found")


def _slugify(name: str) -> str:
    """Mirror dev_provider_user_id() slug logic."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if len(s) < 3:
        s = f"user-{s}" if s else "user"
    return s


def _get_user_id_for_name(display_name: str) -> str:
    slug = _slugify(display_name)
    with database.transaction() as db:
        user = repositories.get_user_by_provider_identity(db, "dev", slug)
    assert user, f"User '{display_name}' (slug='{slug}') not found"
    return user["id"]


def _get_membership(ws_id: str, user_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_workspace_membership(db, ws_id, user_id)


def _get_events(ws_id: str, event_type: str) -> list[dict]:
    with database.transaction() as db:
        all_events = db.execute(
            "SELECT * FROM operational_events WHERE guild_workspace_id = ? AND event_type = ?",
            (ws_id, event_type),
        ).fetchall()
    return [dict(e) for e in all_events]


def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_ws_with_owner(owner_name: str, slug: str):
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    return ws, owner


# ---------------------------------------------------------------------------
# Use case tests
# ---------------------------------------------------------------------------

def test_owner_removes_member():
    ws, owner = _make_ws_with_owner("RemOwner1", "rem-owner-member")
    use_cases.add_workspace_member(ws["id"], owner["id"], "TargetMember1", role="member")
    target_id = _get_user_id_for_name("TargetMember1")

    use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)

    assert _get_membership(ws["id"], target_id) is None


def test_owner_removes_officer():
    ws, owner = _make_ws_with_owner("RemOwner2", "rem-owner-officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "TargetOfficer1", role="officer")
    target_id = _get_user_id_for_name("TargetOfficer1")

    use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)

    assert _get_membership(ws["id"], target_id) is None


def test_officer_removes_member():
    ws, owner = _make_ws_with_owner("RemOwner3", "rem-officer-member")
    use_cases.add_workspace_member(ws["id"], owner["id"], "RemOfficerActor1", role="officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "TargetMember2", role="member")
    actor_id = _get_user_id_for_name("RemOfficerActor1")
    target_id = _get_user_id_for_name("TargetMember2")

    use_cases.remove_workspace_member(ws["id"], actor_id, target_id)

    assert _get_membership(ws["id"], target_id) is None


def test_officer_cannot_remove_officer():
    ws, owner = _make_ws_with_owner("RemOwner4", "rem-officer-officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "OfficerActor1", role="officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "OfficerTarget1", role="officer")
    actor_id = _get_user_id_for_name("OfficerActor1")
    target_id = _get_user_id_for_name("OfficerTarget1")

    with pytest.raises(PermissionDenied):
        use_cases.remove_workspace_member(ws["id"], actor_id, target_id)


def test_officer_cannot_remove_owner():
    ws, owner = _make_ws_with_owner("RemOwner5", "rem-officer-owner")
    use_cases.add_workspace_member(ws["id"], owner["id"], "OfficerActor2", role="officer")
    actor_id = _get_user_id_for_name("OfficerActor2")

    with pytest.raises(PermissionDenied):
        use_cases.remove_workspace_member(ws["id"], actor_id, owner["id"])


def test_owner_cannot_remove_owner():
    ws, owner = _make_ws_with_owner("RemOwner6", "rem-owner-owner")
    use_cases.add_workspace_member(ws["id"], owner["id"], "SecondOwner1", role="owner")
    target_id = _get_user_id_for_name("SecondOwner1")

    with pytest.raises(PermissionDenied):
        use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)


def test_actor_cannot_remove_themselves():
    ws, owner = _make_ws_with_owner("RemOwner7", "rem-self")

    with pytest.raises(PermissionDenied, match="yourself"):
        use_cases.remove_workspace_member(ws["id"], owner["id"], owner["id"])


def test_member_cannot_remove_anyone():
    ws, owner = _make_ws_with_owner("RemOwner8", "rem-member-deny")
    use_cases.add_workspace_member(ws["id"], owner["id"], "PlainMemberActor1", role="member")
    use_cases.add_workspace_member(ws["id"], owner["id"], "PlainMemberTarget1", role="member")
    actor_id = _get_user_id_for_name("PlainMemberActor1")
    target_id = _get_user_id_for_name("PlainMemberTarget1")

    with pytest.raises(PermissionDenied):
        use_cases.remove_workspace_member(ws["id"], actor_id, target_id)


def test_active_assignment_blocks_removal():
    ws, owner = _make_ws_with_owner("RemOwner9", "rem-active-asgn")
    use_cases.add_workspace_member(ws["id"], owner["id"], "AssignedMember1", role="member")
    target_id = _get_user_id_for_name("AssignedMember1")

    # Create assignment for this participant
    comp = make_composition(ws["id"], name="RemComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "AssignedMember1", "Tank")
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )

    with pytest.raises(ConflictError, match="active assignment"):
        use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)


def test_removed_assignment_does_not_block_removal():
    ws, owner = _make_ws_with_owner("RemOwner10", "rem-removed-asgn")
    use_cases.add_workspace_member(ws["id"], owner["id"], "RemovedAsgMember1", role="member")
    target_id = _get_user_id_for_name("RemovedAsgMember1")

    comp = make_composition(ws["id"], name="RemComp2")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "RemovedAsgMember1", "Tank")
    asgn = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    # Soft-remove the assignment
    use_cases.remove_assignment(ws["id"], op["id"], asgn["id"])

    # Should not raise
    use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)
    assert _get_membership(ws["id"], target_id) is None


def test_historical_data_preserved_after_removal():
    ws, owner = _make_ws_with_owner("RemOwner11", "rem-history")
    use_cases.add_workspace_member(ws["id"], owner["id"], "HistoryMember1", role="member")
    target_id = _get_user_id_for_name("HistoryMember1")

    comp = make_composition(ws["id"], name="RemComp3")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "HistoryMember1", "Tank")

    use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)

    # Signup intent still exists
    with database.transaction() as db:
        row = db.execute(
            "SELECT * FROM signup_intents WHERE id = ?", (signup["id"],)
        ).fetchone()
    assert row is not None

    # Participant still exists
    with database.transaction() as db:
        p = db.execute(
            "SELECT * FROM participants WHERE display_name = ? AND guild_workspace_id = ?",
            ("HistoryMember1", ws["id"]),
        ).fetchone()
    assert p is not None

    # User still exists
    with database.transaction() as db:
        u = repositories.get_user_by_id(db, target_id)
    assert u is not None


def test_workspace_member_removed_event_emitted():
    ws, owner = _make_ws_with_owner("RemOwner12", "rem-event")
    use_cases.add_workspace_member(ws["id"], owner["id"], "EventMember1", role="member")
    target_id = _get_user_id_for_name("EventMember1")

    use_cases.remove_workspace_member(ws["id"], owner["id"], target_id)

    events = _get_events(ws["id"], "workspace.member.removed")
    assert len(events) == 1
    import json
    payload = json.loads(events[0]["payload_json"])
    assert payload["removed_user_id"] == target_id
    assert payload["removed_role"] == "member"
    assert payload["removed_user_display_name"] == "EventMember1"


def test_remove_nonexistent_member_raises():
    ws, owner = _make_ws_with_owner("RemOwner13", "rem-notfound")
    fake_user_id = "00000000-0000-0000-0000-000000000000"

    with pytest.raises(NotFoundError):
        use_cases.remove_workspace_member(ws["id"], owner["id"], fake_user_id)


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

def test_repo_count_active_assignments_counts_only_assigned():
    ws, owner = _make_ws_with_owner("RepoOwner1", "repo-count-asgn")
    comp = make_composition(ws["id"], name="RepoComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "RepoPlayer1", "Tank")
    asgn = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    participant_id = signup["participant_id"]

    with database.transaction() as db:
        count = repositories.count_active_assignments_for_participant(
            db, ws["id"], participant_id
        )
    assert count == 1

    # Soft-remove → count drops to 0
    use_cases.remove_assignment(ws["id"], op["id"], asgn["id"])
    with database.transaction() as db:
        count = repositories.count_active_assignments_for_participant(
            db, ws["id"], participant_id
        )
    assert count == 0


def test_repo_find_participant_by_display_name_returns_row():
    ws, _ = _make_ws_with_owner("RepoOwner2", "repo-find-part")
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "FindMe1", "Tank")

    with database.transaction() as db:
        result = repositories.find_participant_by_display_name(db, ws["id"], "FindMe1")
    assert result is not None
    assert result["display_name"] == "FindMe1"


def test_repo_find_participant_by_display_name_returns_none_when_absent():
    ws, _ = _make_ws_with_owner("RepoOwner3", "repo-find-part-none")

    with database.transaction() as db:
        result = repositories.find_participant_by_display_name(db, ws["id"], "DoesNotExist")
    assert result is None


def test_repo_delete_workspace_member_removes_only_membership():
    ws, owner = _make_ws_with_owner("RepoOwner4", "repo-del-member")
    use_cases.add_workspace_member(ws["id"], owner["id"], "DelTargetRepo1", role="member")
    target_id = _get_user_id_for_name("DelTargetRepo1")

    with database.transaction() as db:
        repositories.delete_workspace_member(db, ws["id"], target_id)

    # Membership gone
    assert _get_membership(ws["id"], target_id) is None
    # User still exists
    with database.transaction() as db:
        u = repositories.get_user_by_id(db, target_id)
    assert u is not None


# ---------------------------------------------------------------------------
# HTTP route tests
# ---------------------------------------------------------------------------

def test_http_get_members_page_shows_list():
    owner = make_user("HttpOwner1")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-members-list")
    use_cases.add_workspace_member(ws["id"], owner["id"], "ListedMember1", role="member")

    client = TestClient(app)
    _login(client, "HttpOwner1")

    resp = client.get(f"/workspaces/{ws['slug']}/members")
    assert resp.status_code == 200
    assert "ListedMember1" in resp.text
    assert "HttpOwner1" in resp.text


def test_http_get_members_page_denied_for_member():
    owner = make_user("HttpOwner2")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-members-deny")
    use_cases.add_workspace_member(ws["id"], owner["id"], "PlainHttpMember1", role="member")

    client = TestClient(app)
    _login(client, "PlainHttpMember1")

    resp = client.get(f"/workspaces/{ws['slug']}/members")
    assert resp.status_code == 403


def test_http_post_remove_member_success():
    owner = make_user("HttpOwner3")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-remove-success")
    use_cases.add_workspace_member(ws["id"], owner["id"], "RemovableHttp1", role="member")
    target_id = _get_user_id_for_name("RemovableHttp1")

    client = TestClient(app)
    _login(client, "HttpOwner3")

    resp = client.post(
        f"/workspaces/{ws['slug']}/members/{target_id}/remove",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Member removed" in resp.text
    assert _get_membership(ws["id"], target_id) is None


def test_http_post_remove_with_active_assignment_shows_error():
    owner = make_user("HttpOwner4")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-remove-conflict")
    use_cases.add_workspace_member(ws["id"], owner["id"], "ConflictHttpMember1", role="member")
    target_id = _get_user_id_for_name("ConflictHttpMember1")

    comp = make_composition(ws["id"], name="HttpConflictComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "ConflictHttpMember1", "Tank")
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )

    client = TestClient(app)
    _login(client, "HttpOwner4")

    resp = client.post(
        f"/workspaces/{ws['slug']}/members/{target_id}/remove",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "active assignment" in resp.text.lower()
    # Membership still intact
    assert _get_membership(ws["id"], target_id) is not None


def test_http_officer_removing_officer_shows_error():
    owner = make_user("HttpOwner5")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-officer-officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "ActorOfficerHttp1", role="officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "TargetOfficerHttp1", role="officer")
    actor_id = _get_user_id_for_name("ActorOfficerHttp1")
    target_id = _get_user_id_for_name("TargetOfficerHttp1")

    client = TestClient(app)
    _login(client, "ActorOfficerHttp1")

    resp = client.post(
        f"/workspaces/{ws['slug']}/members/{target_id}/remove",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # An error flash should be present; membership still intact
    assert _get_membership(ws["id"], target_id) is not None


def test_http_self_removal_shows_error():
    owner = make_user("HttpOwner6")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-self-remove")

    client = TestClient(app)
    _login(client, "HttpOwner6")

    resp = client.post(
        f"/workspaces/{ws['slug']}/members/{owner['id']}/remove",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "yourself" in resp.text.lower()
