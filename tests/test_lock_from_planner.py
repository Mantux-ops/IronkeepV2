"""
Lock Roster from Planner Page tests.

Covers:
    1.  Lock Roster button visible for owner on planning operation.
    2.  Lock Roster button visible for officer on planning operation.
    3.  Lock Roster button hidden for members.
    4.  Lock Roster button hidden on draft operations.
    5.  Lock Roster button hidden on locked operations.
    6.  Lock Roster button hidden on completed operations.
    7.  Lock Roster button hidden on archived operations.
    8.  POST lock from planner redirects to planner URL.
    9.  POST lock from planner sets operation status to locked.
    10. POST lock from detail (no next field) still redirects to detail page.
    11. POST lock with invalid next value falls back to detail redirect.
    12. POST lock with next= another operation's planner (wrong op_id) falls back to detail.
    13. Only one Lock Roster form visible on the planner at once.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.application import use_cases
from app import database
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _add_officer(ws_id: str, name: str, owner_id: str) -> dict:
    officer = make_user(name)
    use_cases.add_workspace_member(ws_id, owner_id, name, role="officer")
    return officer


def _add_member(ws_id: str, name: str, owner_id: str) -> dict:
    member = make_user(name)
    use_cases.add_workspace_member(ws_id, owner_id, name, role="member")
    return member


def _make_planning_op(owner_name: str, slug: str):
    """Create workspace + composition + operation in 'planning' status."""
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"], name=f"Comp-{slug}")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])  # draft → planning
    return owner, ws, op


def _planner_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/planner"


def _detail_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}"


def _lock_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/lock"


# ---------------------------------------------------------------------------
# Visibility tests
# ---------------------------------------------------------------------------

def test_lock_button_visible_for_owner_on_planning_op():
    owner, ws, op = _make_planning_op("LockOwner1", "lock-owner-plan")

    client = TestClient(app)
    _login(client, "LockOwner1")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" in resp.text
    # Button must be inside a form targeting the lock route
    assert f'/operations/{op["id"]}/lock' in resp.text


def test_lock_button_visible_for_officer_on_planning_op():
    owner, ws, op = _make_planning_op("LockOwner2", "lock-officer-plan")
    _add_officer(ws["id"], "LockOfficer2", owner["id"])

    client = TestClient(app)
    _login(client, "LockOfficer2")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" in resp.text


def test_lock_button_hidden_for_member():
    owner, ws, op = _make_planning_op("LockOwner3", "lock-member-plan")
    _add_member(ws["id"], "LockMember3", owner["id"])

    client = TestClient(app)
    _login(client, "LockMember3")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" not in resp.text


def test_lock_button_hidden_on_draft_op():
    owner = make_user("LockOwner4")
    ws = make_workspace(owner_user_id=owner["id"], slug="lock-draft")
    comp = make_composition(ws["id"], name="DraftComp")
    op = make_operation(ws["id"])
    # Leave in draft — do NOT publish

    client = TestClient(app)
    _login(client, "LockOwner4")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" not in resp.text


def test_lock_button_hidden_on_locked_op():
    owner, ws, op = _make_planning_op("LockOwner5", "lock-locked")
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "LockOwner5")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" not in resp.text


def test_lock_button_hidden_on_completed_op():
    owner, ws, op = _make_planning_op("LockOwner6", "lock-completed")
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "LockOwner6")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" not in resp.text


def test_lock_button_hidden_on_archived_op():
    owner, ws, op = _make_planning_op("LockOwner7", "lock-archived")
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "LockOwner7")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Lock Roster" not in resp.text


# ---------------------------------------------------------------------------
# POST redirect tests
# ---------------------------------------------------------------------------

def test_post_lock_from_planner_redirects_to_planner():
    owner, ws, op = _make_planning_op("LockOwner8", "lock-redir-planner")

    client = TestClient(app, follow_redirects=False)
    _login(client, "LockOwner8")

    planner = _planner_url(ws["slug"], op["id"])
    resp = client.post(
        _lock_url(ws["slug"], op["id"]),
        data={"next": planner},
    )
    # Should redirect to the planner URL (may have ?success= appended)
    assert resp.status_code in (302, 303)
    assert "/planner" in resp.headers["location"]


def test_post_lock_from_planner_operation_becomes_locked():
    owner, ws, op = _make_planning_op("LockOwner9", "lock-status-planner")

    client = TestClient(app)
    _login(client, "LockOwner9")

    planner = _planner_url(ws["slug"], op["id"])
    client.post(_lock_url(ws["slug"], op["id"]), data={"next": planner})

    with database.transaction() as db:
        from app import repositories
        refreshed = repositories.get_guild_operation(db, op["id"], ws["id"])
    assert refreshed["status"] == "locked"


def test_post_lock_from_detail_no_next_redirects_to_detail():
    """When no next field is present (detail page form), redirect goes to detail."""
    owner, ws, op = _make_planning_op("LockOwner10", "lock-redir-detail")

    client = TestClient(app, follow_redirects=False)
    _login(client, "LockOwner10")

    resp = client.post(_lock_url(ws["slug"], op["id"]), data={})
    assert resp.status_code in (302, 303)
    location = resp.headers["location"]
    assert "/planner" not in location
    assert f'/operations/{op["id"]}' in location


def test_post_lock_with_invalid_next_falls_back_to_detail():
    """An arbitrary path in next= must not be accepted — falls back to detail."""
    owner, ws, op = _make_planning_op("LockOwner11", "lock-invalid-next")

    client = TestClient(app, follow_redirects=False)
    _login(client, "LockOwner11")

    resp = client.post(
        _lock_url(ws["slug"], op["id"]),
        data={"next": "/some/other/path"},
    )
    assert resp.status_code in (302, 303)
    location = resp.headers["location"]
    assert "/planner" not in location
    assert f'/operations/{op["id"]}' in location


def test_post_lock_with_wrong_op_id_in_next_falls_back_to_detail():
    """next= pointing to a different operation's planner must not be accepted."""
    owner, ws, op = _make_planning_op("LockOwner12", "lock-wrong-op")
    other_op = make_operation(ws["id"])

    client = TestClient(app, follow_redirects=False)
    _login(client, "LockOwner12")

    wrong_next = _planner_url(ws["slug"], other_op["id"])
    resp = client.post(
        _lock_url(ws["slug"], op["id"]),
        data={"next": wrong_next},
    )
    assert resp.status_code in (302, 303)
    location = resp.headers["location"]
    # Must NOT redirect to the other operation's planner
    assert other_op["id"] not in location or f'/operations/{op["id"]}' in location


# ---------------------------------------------------------------------------
# No-duplicate test
# ---------------------------------------------------------------------------

def test_only_one_lock_roster_form_on_planner():
    owner, ws, op = _make_planning_op("LockOwner13", "lock-no-dup")

    client = TestClient(app)
    _login(client, "LockOwner13")

    resp = client.get(_planner_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    # Count occurrences of the lock form action URL
    count = resp.text.count(f'/operations/{op["id"]}/lock')
    assert count == 1
