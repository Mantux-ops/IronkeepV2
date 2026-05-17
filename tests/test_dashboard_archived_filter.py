"""
Dashboard archived-operation filter tests.

Covers:
  1.  Dashboard hides archived operations by default.
  2.  Archived operation absent from default dashboard HTML.
  3.  Dashboard shows archived operations with ?show_archived=1.
  4.  Archived operation visible (title + badge) with ?show_archived=1.
  5.  Direct URL to archived operation detail still works (200).
  6.  Archived operation detail shows archived status badge.
  7.  Count hint ("Show N archived") appears when archived ops exist.
  8.  "Hide archived" link appears when ?show_archived=1.
  9.  No count hint when no archived operations exist.
  10. Non-archived operations always visible on default dashboard.
  11. No rows are deleted — archived operation row is preserved in DB.
  12. get_guild_operations include_archived=False excludes archived.
  13. get_guild_operations include_archived=True includes archived.
  14. count_archived_guild_operations returns correct count.
  15. count_archived_guild_operations returns 0 when none archived.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app
from tests.conftest import make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _make_archived_op(ws_id: str, title: str = "Old Campaign") -> dict:
    """Create an operation and drive it all the way to archived."""
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws_id,
        title=title,
        operation_type="zvz",
        scheduled_start_at="2025-01-01T20:00:00+00:00",
    )
    use_cases.publish_operation(ws_id, op["id"])
    use_cases.complete_operation(ws_id, op["id"])
    use_cases.archive_operation(ws_id, op["id"])
    return op


def _make_active_op(ws_id: str, title: str = "Active Campaign") -> dict:
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws_id,
        title=title,
        operation_type="zvz",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
    )
    use_cases.publish_operation(ws_id, op["id"])
    return op


# ---------------------------------------------------------------------------
# Repository-level tests (no HTTP)
# ---------------------------------------------------------------------------

def test_get_guild_operations_excludes_archived_by_default():
    ws = make_workspace()
    active = _make_active_op(ws["id"], "Active Op")
    archived = _make_archived_op(ws["id"], "Archived Op")

    with database.transaction() as db:
        ops = repositories.get_guild_operations(db, ws["id"])

    ids = [o["id"] for o in ops]
    assert active["id"] in ids
    assert archived["id"] not in ids


def test_get_guild_operations_includes_archived_when_requested():
    ws = make_workspace()
    active = _make_active_op(ws["id"], "Active Op")
    archived = _make_archived_op(ws["id"], "Archived Op")

    with database.transaction() as db:
        ops = repositories.get_guild_operations(db, ws["id"], include_archived=True)

    ids = [o["id"] for o in ops]
    assert active["id"] in ids
    assert archived["id"] in ids


def test_count_archived_guild_operations_returns_correct_count():
    ws = make_workspace()
    _make_archived_op(ws["id"], "Archived One")
    _make_archived_op(ws["id"], "Archived Two")
    _make_active_op(ws["id"], "Active Op")

    with database.transaction() as db:
        count = repositories.count_archived_guild_operations(db, ws["id"])

    assert count == 2


def test_count_archived_guild_operations_returns_zero_when_none():
    ws = make_workspace()
    _make_active_op(ws["id"], "Active Op")

    with database.transaction() as db:
        count = repositories.count_archived_guild_operations(db, ws["id"])

    assert count == 0


def test_archived_operation_row_preserved_in_db():
    """Archiving never deletes the row — it only changes status."""
    ws = make_workspace()
    op = _make_archived_op(ws["id"], "Preserved Archived Op")

    with database.transaction() as db:
        row = repositories.get_guild_operation(db, op["id"], ws["id"])

    assert row is not None
    assert row["status"] == "archived"
    assert row["id"] == op["id"]


# ---------------------------------------------------------------------------
# HTTP / route tests
# ---------------------------------------------------------------------------

def test_dashboard_hides_archived_by_default():
    owner = make_user("DashOwner1")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-hide-archived")
    _make_archived_op(ws["id"], "Buried Old Op")

    client = TestClient(app)
    _login(client, "DashOwner1")

    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert "Buried Old Op" not in response.text


def test_archived_operation_absent_from_default_dashboard_html():
    owner = make_user("DashOwner2")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-absent-archived")
    archived = _make_archived_op(ws["id"], "Gone Op")
    active = _make_active_op(ws["id"], "Visible Op")

    client = TestClient(app)
    _login(client, "DashOwner2")

    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert "Gone Op" not in response.text
    assert "Visible Op" in response.text


def test_dashboard_shows_archived_with_query_param():
    owner = make_user("DashOwner3")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-show-archived")
    _make_archived_op(ws["id"], "The Archived Op")

    client = TestClient(app)
    _login(client, "DashOwner3")

    response = client.get(f"/workspaces/{ws['slug']}?show_archived=1")
    assert response.status_code == 200
    assert "The Archived Op" in response.text


def test_archived_operation_has_archived_badge_in_dashboard():
    owner = make_user("DashOwner4")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-badge-archived")
    _make_archived_op(ws["id"], "Badged Op")

    client = TestClient(app)
    _login(client, "DashOwner4")

    response = client.get(f"/workspaces/{ws['slug']}?show_archived=1")
    assert response.status_code == 200
    assert "badge-archived" in response.text
    assert "archived" in response.text


def test_archived_count_hint_shown_on_default_dashboard():
    owner = make_user("DashOwner5")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-hint")
    _make_archived_op(ws["id"], "Hinted Op One")
    _make_archived_op(ws["id"], "Hinted Op Two")

    client = TestClient(app)
    _login(client, "DashOwner5")

    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert "show_archived=1" in response.text
    assert "2" in response.text


def test_no_count_hint_when_no_archived_operations():
    owner = make_user("DashOwner6")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-no-hint")
    _make_active_op(ws["id"], "Only Active")

    client = TestClient(app)
    _login(client, "DashOwner6")

    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert "show_archived=1" not in response.text


def test_hide_archived_link_appears_when_showing_archived():
    owner = make_user("DashOwner7")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-hide-link")
    _make_archived_op(ws["id"], "Some Archived Op")

    client = TestClient(app)
    _login(client, "DashOwner7")

    response = client.get(f"/workspaces/{ws['slug']}?show_archived=1")
    assert response.status_code == 200
    assert "Hide archived" in response.text


def test_active_operations_always_visible_on_default_dashboard():
    owner = make_user("DashOwner8")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-active-visible")
    _make_active_op(ws["id"], "Saturday ZvZ")
    _make_archived_op(ws["id"], "Old Campaign")

    client = TestClient(app)
    _login(client, "DashOwner8")

    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert "Saturday ZvZ" in response.text
    assert "Old Campaign" not in response.text


def test_direct_url_to_archived_operation_detail_works():
    owner = make_user("DashOwner9")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-direct-url")
    archived_op = _make_archived_op(ws["id"], "Direct URL Op")

    client = TestClient(app)
    _login(client, "DashOwner9")

    response = client.get(f"/workspaces/{ws['slug']}/operations/{archived_op['id']}")
    assert response.status_code == 200


def test_archived_operation_detail_shows_archived_status():
    owner = make_user("DashOwner10")
    ws = make_workspace(owner_user_id=owner["id"], slug="dash-detail-status")
    archived_op = _make_archived_op(ws["id"], "Detail Status Op")

    client = TestClient(app)
    _login(client, "DashOwner10")

    response = client.get(f"/workspaces/{ws['slug']}/operations/{archived_op['id']}")
    assert response.status_code == 200
    assert "archived" in response.text.lower()
