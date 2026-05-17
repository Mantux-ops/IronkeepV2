"""
Dashboard operational awareness tests.

Covers:
  Repository:
    1.  get_latest_readiness_snapshots_for_workspace returns dict keyed by op id.
    2.  Only the latest snapshot per operation is returned (not all snapshots).
    3.  Operations with no snapshot are absent from the dict.
    4.  Multiple operations each get their own correct snapshot.
    5.  Only snapshots belonging to the requested workspace are returned.

  HTTP / template:
    6.  Dashboard shows readiness_state badge when snapshot exists.
    7.  Dashboard shows assigned/total slot counts.
    8.  Dashboard shows open slot count when > 0.
    9.  Dashboard shows unassigned_signup_count when > 0.
    10. Dashboard shows — when no snapshot exists for an operation.
    11. Archived operations still show readiness when ?show_archived=1.
    12. Friendly datetime is rendered (no raw T separator in scheduled column).
    13. Two operations: each gets its own readiness data (no cross-contamination).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_full_op(ws_id: str, title: str = "Dashboard Test Op") -> tuple[dict, dict]:
    """
    Create operation with composition → slots → readiness snapshot.
    Returns (operation, readiness_snapshot).
    """
    comp = make_composition(ws_id, name=f"Comp-{title}")
    op = make_operation(ws_id, title=title)
    use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
    use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    snap = use_cases.calculate_readiness_snapshot(ws_id, op["id"])
    return op, snap


def _insert_raw_snapshot(ws_id: str, op_id: str, state: str, total: int,
                          assigned: int, open_s: int, unassigned: int,
                          created_at: str) -> None:
    """Insert a readiness snapshot directly with a specific created_at for ordering tests."""
    import uuid
    snap = {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "guild_operation_id": op_id,
        "total_slots": total,
        "assigned_slots": assigned,
        "open_slots": open_s,
        "unassigned_signup_count": unassigned,
        "missing_roles_json": "[]",
        "missing_builds_json": "[]",
        "attendance_marked_count": 0,
        "attendance_unmarked_count": 0,
        "scout_count": 0,
        "support_count": 0,
        "reserve_count": 0,
        "readiness_state": state,
        "created_at": created_at,
    }
    with database.transaction() as db:
        repositories.insert_readiness_snapshot(db, snap)


def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

def test_repo_returns_dict_keyed_by_op_id():
    ws = make_workspace(slug="rdr-keyed")
    op, snap = _build_full_op(ws["id"])

    with database.transaction() as db:
        result = repositories.get_latest_readiness_snapshots_for_workspace(db, ws["id"])

    assert op["id"] in result
    assert result[op["id"]]["readiness_state"] == snap["readiness_state"]


def test_repo_only_latest_snapshot_returned():
    ws = make_workspace(slug="rdr-latest")
    op = make_operation(ws["id"])

    # Insert two snapshots with different created_at timestamps
    _insert_raw_snapshot(ws["id"], op["id"], "needs_attention", 5, 2, 3, 0,
                         "2026-06-01T10:00:00+00:00")
    _insert_raw_snapshot(ws["id"], op["id"], "ready",           5, 5, 0, 0,
                         "2026-06-01T11:00:00+00:00")  # latest

    with database.transaction() as db:
        result = repositories.get_latest_readiness_snapshots_for_workspace(db, ws["id"])

    assert result[op["id"]]["readiness_state"] == "ready"


def test_repo_absent_when_no_snapshot():
    ws = make_workspace(slug="rdr-absent")
    op = make_operation(ws["id"])

    with database.transaction() as db:
        result = repositories.get_latest_readiness_snapshots_for_workspace(db, ws["id"])

    assert op["id"] not in result


def test_repo_multiple_ops_each_get_correct_snapshot():
    ws = make_workspace(slug="rdr-multi")
    op1, _ = _build_full_op(ws["id"], title="Op Alpha")
    op2, _ = _build_full_op(ws["id"], title="Op Beta")

    with database.transaction() as db:
        result = repositories.get_latest_readiness_snapshots_for_workspace(db, ws["id"])

    assert op1["id"] in result
    assert op2["id"] in result
    assert result[op1["id"]]["guild_operation_id"] == op1["id"]
    assert result[op2["id"]]["guild_operation_id"] == op2["id"]


def test_repo_workspace_scoped_no_cross_contamination():
    owner1 = make_user("WsOwner-RdrA")
    owner2 = make_user("WsOwner-RdrB")
    ws1 = make_workspace(name="WS-A", slug="rdr-ws-a", owner_user_id=owner1["id"])
    ws2 = make_workspace(name="WS-B", slug="rdr-ws-b", owner_user_id=owner2["id"])

    op1, _ = _build_full_op(ws1["id"], title="WS-A Op")
    op2, _ = _build_full_op(ws2["id"], title="WS-B Op")

    with database.transaction() as db:
        result1 = repositories.get_latest_readiness_snapshots_for_workspace(db, ws1["id"])
        result2 = repositories.get_latest_readiness_snapshots_for_workspace(db, ws2["id"])

    assert op1["id"] in result1
    assert op2["id"] not in result1
    assert op2["id"] in result2
    assert op1["id"] not in result2


# ---------------------------------------------------------------------------
# HTTP / template tests
# ---------------------------------------------------------------------------

def test_http_dashboard_shows_readiness_badge():
    owner = make_user("RdrBadgeOwner")
    ws = make_workspace(name="Rdr Badge WS", slug="rdr-badge", owner_user_id=owner["id"])
    op, snap = _build_full_op(ws["id"])

    client = TestClient(app)
    _login(client, "RdrBadgeOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    assert snap["readiness_state"] in resp.text


def test_http_dashboard_shows_slot_counts():
    owner = make_user("RdrSlotsOwner")
    ws = make_workspace(name="Rdr Slots WS", slug="rdr-slots", owner_user_id=owner["id"])
    op, snap = _build_full_op(ws["id"])

    client = TestClient(app)
    _login(client, "RdrSlotsOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    # assigned_slots / total_slots pattern, e.g. "0 / 5"
    assert f"{snap['assigned_slots']} / {snap['total_slots']}" in resp.text


def test_http_dashboard_shows_open_slots_when_nonzero():
    owner = make_user("RdrOpenOwner")
    ws = make_workspace(name="Rdr Open WS", slug="rdr-open", owner_user_id=owner["id"])
    op, snap = _build_full_op(ws["id"])

    client = TestClient(app)
    _login(client, "RdrOpenOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    if snap["open_slots"] > 0:
        assert "open" in resp.text


def test_http_dashboard_shows_unassigned_signup_count():
    owner = make_user("RdrSignupOwner")
    ws = make_workspace(name="Rdr Signup WS", slug="rdr-signup", owner_user_id=owner["id"])
    op, _ = _build_full_op(ws["id"])

    # Submit a signup that stays unassigned
    use_cases.submit_signup_intent(ws["id"], op["id"], "UnassignedPlayer", "Tank")
    snap = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "RdrSignupOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    assert str(snap["unassigned_signup_count"]) in resp.text


def test_http_dashboard_shows_dash_when_no_snapshot():
    owner = make_user("RdrNoSnapOwner")
    ws = make_workspace(name="Rdr NoSnap WS", slug="rdr-nosnap", owner_user_id=owner["id"])
    _op = make_operation(ws["id"], title="No Readiness Op")

    client = TestClient(app)
    _login(client, "RdrNoSnapOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    # The — em-dash placeholder must appear (at least once for the no-snapshot op)
    assert "—" in resp.text


def test_http_dashboard_archived_ops_show_readiness_with_show_archived():
    owner = make_user("RdrArchOwner")
    ws = make_workspace(name="Rdr Arch WS", slug="rdr-arch", owner_user_id=owner["id"])
    op, snap = _build_full_op(ws["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "RdrArchOwner")

    resp = client.get(f"/workspaces/{ws['slug']}?show_archived=1")
    assert resp.status_code == 200
    # Archived op should still have its readiness state rendered
    assert snap["readiness_state"] in resp.text


def test_http_dashboard_no_raw_T_separator_in_scheduled():
    owner = make_user("RdrDtOwner")
    ws = make_workspace(name="Rdr Dt WS", slug="rdr-dt", owner_user_id=owner["id"])
    _op = make_operation(ws["id"], title="DT Test Op", start="2026-06-07T20:00:00+00:00")

    client = TestClient(app)
    _login(client, "RdrDtOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    # Raw ISO T separator must not appear in the scheduled column
    assert "2026-06-07T20:00" not in resp.text


def test_http_dashboard_two_ops_no_cross_contamination():
    owner = make_user("RdrCrossOwner")
    ws = make_workspace(name="Rdr Cross WS", slug="rdr-cross", owner_user_id=owner["id"])
    op1, snap1 = _build_full_op(ws["id"], title="Alpha Op")
    op2, snap2 = _build_full_op(ws["id"], title="Beta Op")

    client = TestClient(app)
    _login(client, "RdrCrossOwner")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    # Both op titles present
    assert "Alpha Op" in resp.text
    assert "Beta Op" in resp.text
    # Both readiness state values present
    assert snap1["readiness_state"] in resp.text
    assert snap2["readiness_state"] in resp.text
