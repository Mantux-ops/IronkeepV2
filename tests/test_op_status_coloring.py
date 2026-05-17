"""
Operation Status Urgency Coloring tests.

Verifies that:
- main[data-op-status] is present on all five operation sub-pages.
- The attribute value matches the actual operation status.
- Non-operation pages (dashboard) do not carry data-op-status.
- All five lifecycle statuses are represented.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planning_op(owner_name: str, slug: str):
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    return owner, ws, op


def _attr(status: str) -> str:
    # Use a leading space so the pattern matches the HTML attribute ( data-op-status="…")
    # but NOT the CSS selector form (main[data-op-status="…"]).
    return f' data-op-status="{status}"'


# ---------------------------------------------------------------------------
# data-op-status on operation sub-pages
# ---------------------------------------------------------------------------

def test_detail_page_carries_planning_status():
    owner, ws, op = _make_planning_op("ColOwner1", "col-detail-planning")
    client = TestClient(app)
    _login(client, "ColOwner1")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200
    assert _attr("planning") in resp.text


def test_planner_page_carries_planning_status():
    owner, ws, op = _make_planning_op("ColOwner2", "col-planner-planning")
    client = TestClient(app)
    _login(client, "ColOwner2")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/planner")
    assert resp.status_code == 200
    assert _attr("planning") in resp.text


def test_attendance_page_carries_planning_status():
    owner, ws, op = _make_planning_op("ColOwner3", "col-attendance-planning")
    client = TestClient(app)
    _login(client, "ColOwner3")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance")
    assert resp.status_code == 200
    assert _attr("planning") in resp.text


def test_timeline_page_carries_planning_status():
    owner, ws, op = _make_planning_op("ColOwner4", "col-timeline-planning")
    client = TestClient(app)
    _login(client, "ColOwner4")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/timeline")
    assert resp.status_code == 200
    assert _attr("planning") in resp.text


def test_signup_page_carries_planning_status():
    owner, ws, op = _make_planning_op("ColOwner5", "col-signup-planning")
    client = TestClient(app)
    _login(client, "ColOwner5")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/signup")
    assert resp.status_code == 200
    assert _attr("planning") in resp.text


# ---------------------------------------------------------------------------
# Status changes propagate to attribute value
# ---------------------------------------------------------------------------

def test_detail_page_carries_locked_status():
    owner, ws, op = _make_planning_op("ColOwner6", "col-detail-locked")
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "ColOwner6")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200
    assert _attr("locked") in resp.text
    assert _attr("planning") not in resp.text


def test_detail_page_carries_completed_status():
    owner, ws, op = _make_planning_op("ColOwner7", "col-detail-completed")
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "ColOwner7")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200
    assert _attr("completed") in resp.text


def test_detail_page_carries_archived_status():
    owner, ws, op = _make_planning_op("ColOwner8", "col-detail-archived")
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "ColOwner8")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200
    assert _attr("archived") in resp.text


# ---------------------------------------------------------------------------
# Non-operation pages are unaffected
# ---------------------------------------------------------------------------

def test_dashboard_has_no_data_op_status():
    owner, ws, _op = _make_planning_op("ColOwner9", "col-dashboard-clean")
    client = TestClient(app)
    _login(client, "ColOwner9")

    resp = client.get(f"/workspaces/{ws['slug']}")
    assert resp.status_code == 200
    # CSS selectors contain data-op-status; check the HTML attribute form (leading space).
    for status in ("draft", "planning", "locked", "completed", "archived"):
        assert _attr(status) not in resp.text


def test_members_page_has_no_data_op_status():
    owner, ws, _op = _make_planning_op("ColOwner10", "col-members-clean")
    client = TestClient(app)
    _login(client, "ColOwner10")

    resp = client.get(f"/workspaces/{ws['slug']}/members")
    assert resp.status_code == 200
    for status in ("draft", "planning", "locked", "completed", "archived"):
        assert _attr(status) not in resp.text
