"""
Phase 8.7 Slice 2 — Design Doctrine Enforcement tests.

Typography and status semantics on operational surfaces:
  - Operational metrics use op-metric* utility classes
  - Dashboard readiness uses canonical badge classes (no inline colour)
  - Locked lifecycle state uses informational (info) tokens, not warning
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


CSS_COMPONENTS = Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "components.css"


def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planning_op_with_readiness(ws_id: str, title: str, state: str) -> dict:
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
        "unassigned_signup_count": 2 if state == "not_ready" else 0,
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


def _make_planner_op(owner_name: str, slug: str):
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    return owner, ws, op


# ---------------------------------------------------------------------------
# CSS — locked state semantics (frozen / informational, not warning)
# ---------------------------------------------------------------------------

def test_badge_locked_uses_info_tokens():
    css = CSS_COMPONENTS.read_text(encoding="utf-8")
    assert ".badge-locked" in css
    locked_rule = css.split(".badge-locked")[1].split("}")[0]
    assert "--info-bg" in locked_rule
    assert "--info-text" in locked_rule
    assert "--warning-bg" not in locked_rule
    assert "--warning-text" not in locked_rule


def test_locked_op_status_accent_uses_info_token():
    css = CSS_COMPONENTS.read_text(encoding="utf-8")
    assert 'main[data-op-status="locked"]' in css
    locked_block = css.split('main[data-op-status="locked"]')[1].split("}")[0]
    assert "var(--info)" in locked_block
    assert "var(--warning)" not in locked_block


# ---------------------------------------------------------------------------
# Dashboard — no inline readiness colours; canonical badges
# ---------------------------------------------------------------------------

def test_dashboard_has_no_inline_readiness_colours():
    owner = make_user("DocSlice2Dash")
    ws = make_workspace(owner_user_id=owner["id"], slug="doc-slice2-dash")
    _make_planning_op_with_readiness(ws["id"], "Not Ready Op", "not_ready")
    _make_planning_op_with_readiness(ws["id"], "Forming Op", "forming")

    client = TestClient(app)
    _login(client, "DocSlice2Dash")
    text = client.get(f"/workspaces/{ws['slug']}").text

    assert 'style="color:var(--danger-text)"' not in text
    assert 'style="color:var(--warning)"' not in text
    assert 'style="color:var(--success)"' not in text


def test_dashboard_attention_uses_readiness_badges():
    owner = make_user("DocSlice2Badges")
    ws = make_workspace(owner_user_id=owner["id"], slug="doc-slice2-badges")
    _make_planning_op_with_readiness(ws["id"], "Critical Op", "not_ready")
    _make_planning_op_with_readiness(ws["id"], "Partial Op", "forming")

    client = TestClient(app)
    _login(client, "DocSlice2Badges")
    text = client.get(f"/workspaces/{ws['slug']}").text

    assert 'class="badge badge-not_ready' in text
    assert 'class="badge badge-forming' in text
    assert "<h2>Needs attention</h2>" in text


def test_dashboard_operations_table_uses_op_metric_classes():
    owner = make_user("DocSlice2Table")
    ws = make_workspace(owner_user_id=owner["id"], slug="doc-slice2-table")
    _make_planning_op_with_readiness(ws["id"], "Table Op", "forming")

    client = TestClient(app)
    _login(client, "DocSlice2Table")
    text = client.get(f"/workspaces/{ws['slug']}").text

    assert 'class="op-metric"' in text
    assert 'class="col-meta op-metric--timestamp"' in text


def test_dashboard_summary_metrics_use_op_metric():
    owner = make_user("DocSlice2Metrics")
    ws = make_workspace(owner_user_id=owner["id"], slug="doc-slice2-metrics")
    make_operation(ws["id"], title="Draft Op")

    client = TestClient(app)
    _login(client, "DocSlice2Metrics")
    text = client.get(f"/workspaces/{ws['slug']}").text

    assert 'class="metric-card__value op-metric"' in text


# ---------------------------------------------------------------------------
# Planner — operational metrics typography
# ---------------------------------------------------------------------------

def test_planner_readiness_instrument_uses_op_metric_classes():
    owner, ws, op = _make_planner_op("DocSlice2Planner", "doc-slice2-planner")
    use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "DocSlice2Planner")
    text = client.get(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/planner"
    ).text

    assert "readiness-bar__fill op-metric" in text
    assert "readiness-bar__pct op-metric--pct" in text
    assert "readiness-bar__meta op-metric--timestamp" in text
    assert "readiness-bar__stats op-metric" in text


def test_locked_planner_banner_uses_alert_info_not_warning():
    owner, ws, op = _make_planner_op("DocSlice2Locked", "doc-slice2-locked")
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "DocSlice2Locked")
    text = client.get(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/planner"
    ).text

    assert ' data-op-status="locked"' in text
    assert 'class="alert alert-info"' in text
    assert "Roster is locked" in text


# ---------------------------------------------------------------------------
# Operation detail — operational metrics typography
# ---------------------------------------------------------------------------

def test_operation_detail_readiness_stats_use_op_metric():
    owner, ws, op = _make_planner_op("DocSlice2Detail", "doc-slice2-detail")
    use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "DocSlice2Detail")
    text = client.get(
        f"/workspaces/{ws['slug']}/operations/{op['id']}"
    ).text

    assert 'class="op-metric--timestamp"' in text
    assert 'class="stat-grid"' in text
    assert '<strong class="op-metric">' in text
