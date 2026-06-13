"""
Dashboard widget and structural rendering tests — Phase 6 / Phase 7.

Covers:
  1.  Recent activity widget absent on a brand-new workspace (no qualifying events).
  2.  Recent activity widget appears after an operation is created.
  3.  Recent activity widget does NOT expose archived operation titles.
  4.  Sidebar "Plan" action-section-label is present for workspace owners.
  5.  Sidebar "Settings" action-section-label present for users with can_mutate.
  6.  "Needs attention" card absent when workspace has no planning/locked ops.
  7.  "Needs attention" card present when a planning op is not-ready.
  8.  Attention items: danger tier items rendered before warning tier items.
  9.  All-clear state shown when active operations exist with no attention issues.
  10. Context-aware table CTAs: draft ops show "Setup", planning not-ready ops show "Planner".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
)


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _stamp_fresh_scheduler_run() -> None:
    """
    Insert a recent scheduler_runs row so the dashboard does not flag the
    scheduler as stale. Tests that check for 'no attention items' need this
    to avoid a false-positive attention section from a never-run scheduler.
    """
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    with database.transaction() as db:
        repositories.insert_scheduler_run(db, {
            "id": str(uuid.uuid4()),
            "job_name": "reminder_check",
            "started_at": now,
            "finished_at": now,
            "status": "ok",
            "result_json": "{}",
            "error_message": None,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _get_dashboard(slug: str, user_name: str) -> str:
    """Log in as user_name and GET the workspace dashboard. Returns response text."""
    client = TestClient(app)
    _login(client, user_name)
    resp = client.get(f"/workspaces/{slug}")
    assert resp.status_code == 200
    return resp.text


def _make_planning_op_with_readiness(ws_id: str, title: str, state: str) -> None:
    """
    Create an operation in planning state with a readiness snapshot of the given state.
    Uses direct repository insertion for the snapshot so any state can be forced.
    """
    import uuid
    op = make_operation(ws_id, title=title)
    use_cases.publish_operation(ws_id, op["id"])

    snap = {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "guild_operation_id": op["id"],
        "total_slots": 5,
        "assigned_slots": 0 if state == "not_ready" else 3,
        "open_slots": 5 if state == "not_ready" else 2,
        "unassigned_signup_count": 0,
        "missing_roles_json": "[]",
        "missing_builds_json": "[]",
        "attendance_marked_count": 0,
        "attendance_unmarked_count": 0,
        "scout_count": 0,
        "support_count": 0,
        "reserve_count": 0,
        "readiness_state": state,
        "created_at": "2026-06-01T10:00:00+00:00",
    }
    with database.transaction() as db:
        repositories.insert_readiness_snapshot(db, snap)
    return op


def _make_ready_op(ws_id: str, title: str) -> dict:
    """Create an operation in planning state with a ready readiness snapshot."""
    import uuid
    op = make_operation(ws_id, title=title)
    use_cases.publish_operation(ws_id, op["id"])
    snap = {
        "id": str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "guild_operation_id": op["id"],
        "total_slots": 5,
        "assigned_slots": 5,
        "open_slots": 0,
        "unassigned_signup_count": 0,
        "missing_roles_json": "[]",
        "missing_builds_json": "[]",
        "attendance_marked_count": 0,
        "attendance_unmarked_count": 0,
        "scout_count": 0,
        "support_count": 0,
        "reserve_count": 0,
        "readiness_state": "ready",
        "created_at": "2026-06-01T10:00:00+00:00",
    }
    with database.transaction() as db:
        repositories.insert_readiness_snapshot(db, snap)
    return op


# ---------------------------------------------------------------------------
# Test 1 — Recent activity absent on new workspace
# ---------------------------------------------------------------------------

def test_recent_activity_absent_on_new_workspace():
    """A brand-new workspace has no qualifying events — widget must not appear."""
    owner = make_user("WgtOwner1")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-no-activity")
    text = _get_dashboard(ws["slug"], "WgtOwner1")
    # Check for the HTML element — the CSS comment also contains "Recent activity"
    # so we test for the sidebar-label HTML node specifically.
    assert 'sidebar-label">Recent activity' not in text
    assert 'class="activity-list"' not in text


# ---------------------------------------------------------------------------
# Test 2 — Recent activity appears after operation created
# ---------------------------------------------------------------------------

def test_recent_activity_shows_after_operation_created():
    """Creating an operation fires guild_operation.created — widget must appear."""
    owner = make_user("WgtOwner2")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-with-activity")
    make_operation(ws["id"], title="Tactical ZvZ")

    text = _get_dashboard(ws["slug"], "WgtOwner2")
    assert "Recent activity" in text
    assert "Operation created" in text


# ---------------------------------------------------------------------------
# Test 3 — Recent activity excludes archived operation titles
# ---------------------------------------------------------------------------

def test_recent_activity_excludes_archived_op_titles():
    """
    Events from archived operations must not appear in the activity widget.
    The widget filters to ops where status != 'archived'.
    """
    owner = make_user("WgtOwner3")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-archived-hidden")
    op = make_operation(ws["id"], title="Old Campaign")

    # Walk op through to archived state
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    text = _get_dashboard(ws["slug"], "WgtOwner3")
    assert "Old Campaign" not in text


# ---------------------------------------------------------------------------
# Test 4 — Sidebar Plan section label always present
# ---------------------------------------------------------------------------

def test_sidebar_plan_section_present():
    """The 'Plan' action-section-label must be visible to all logged-in users."""
    owner = make_user("WgtOwner4")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-sidebar-plan")
    text = _get_dashboard(ws["slug"], "WgtOwner4")
    assert "Plan" in text
    assert "+ New Operation" in text


# ---------------------------------------------------------------------------
# Test 5 — Sidebar Settings section present for owner
# ---------------------------------------------------------------------------

def test_sidebar_settings_section_present_for_owner():
    """The 'Settings' action-section-label must appear for workspace owners."""
    owner = make_user("WgtOwner5")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-sidebar-settings")
    text = _get_dashboard(ws["slug"], "WgtOwner5")
    assert "Settings" in text
    assert "Discord settings" in text
    assert "Scheduler" in text


# ---------------------------------------------------------------------------
# Test 6 — Needs attention absent when no planning/locked ops
# ---------------------------------------------------------------------------

def test_attention_absent_when_no_planning_ops():
    """
    With no operations in planning or locked state, the attention card
    must not be rendered.  Stamp a fresh scheduler run so the scheduler-stale
    check does not produce a false-positive attention item.
    """
    owner = make_user("WgtOwner6")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-no-attention")
    # Draft op only — not in attention scope
    make_operation(ws["id"], title="Draft Only Op")
    _stamp_fresh_scheduler_run()

    text = _get_dashboard(ws["slug"], "WgtOwner6")
    # "Needs attention" also appears inside a CSS comment; check the HTML heading.
    assert "<h2>Needs attention</h2>" not in text


# ---------------------------------------------------------------------------
# Test 7 — Needs attention present when planning op is not-ready
# ---------------------------------------------------------------------------

def test_attention_present_for_not_ready_planning_op():
    """A planning op with not_ready readiness must appear in the attention card."""
    owner = make_user("WgtOwner7")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-has-attention")
    _make_planning_op_with_readiness(ws["id"], "Urgent ZvZ", "not_ready")

    text = _get_dashboard(ws["slug"], "WgtOwner7")
    assert "<h2>Needs attention</h2>" in text
    assert "Urgent ZvZ" in text


# ---------------------------------------------------------------------------
# Test 8 — Attention ordering: danger (not_ready) before warning (forming)
# ---------------------------------------------------------------------------

def test_attention_danger_before_warning():
    """
    not_ready ops (danger tier) must appear before forming ops (warning tier)
    in the attention card HTML.
    """
    owner = make_user("WgtOwner8")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-attention-order")
    _make_planning_op_with_readiness(ws["id"], "Forming Op Alpha", "forming")
    _make_planning_op_with_readiness(ws["id"], "Critical Not Ready", "not_ready")

    text = _get_dashboard(ws["slug"], "WgtOwner8")
    assert "<h2>Needs attention</h2>" in text
    danger_pos  = text.index("Critical Not Ready")
    forming_pos = text.index("Forming Op Alpha")
    assert danger_pos < forming_pos, (
        "not_ready (danger) item must appear before forming (warning) item"
    )


# ---------------------------------------------------------------------------
# Test 9 — All-clear state shown when active ops are healthy
# ---------------------------------------------------------------------------

def test_all_clear_shown_when_active_ops_are_healthy():
    """
    When active operations exist but none require attention and no infra issues
    are present, the all-clear strip must be visible and attention absent.
    Stamp a fresh scheduler run so the stale-scheduler check passes.
    """
    owner = make_user("WgtOwner9")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-all-clear")
    _make_ready_op(ws["id"], "Ready Operation")
    _stamp_fresh_scheduler_run()

    text = _get_dashboard(ws["slug"], "WgtOwner9")
    assert "All clear" in text
    # "Needs attention" also lives in a CSS comment; target the HTML heading.
    assert "<h2>Needs attention</h2>" not in text


# ---------------------------------------------------------------------------
# Test 10 — Context-aware table CTAs
# ---------------------------------------------------------------------------

def test_draft_op_shows_setup_cta():
    """A draft operation row must display a 'Setup' continuation CTA."""
    owner = make_user("WgtOwner10")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-cta-draft")
    make_operation(ws["id"], title="Draft Operation")

    text = _get_dashboard(ws["slug"], "WgtOwner10")
    assert "Setup" in text


def test_not_ready_planning_op_shows_planner_cta():
    """A planning op with not_ready readiness must display a 'Planner' CTA."""
    owner = make_user("WgtOwner11")
    ws = make_workspace(owner_user_id=owner["id"], slug="wgt-cta-planner")
    _make_planning_op_with_readiness(ws["id"], "Planning Not Ready", "not_ready")

    text = _get_dashboard(ws["slug"], "WgtOwner11")
    # Should appear in both the attention card and the table
    assert "Planner" in text
