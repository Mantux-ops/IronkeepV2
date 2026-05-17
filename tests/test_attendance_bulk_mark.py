"""
Attendance bulk mark present tests.

Covers:
  Use case:
    1.  bulk_mark_present creates records for all unmarked active assignments.
    2.  bulk_mark_present returns the count of newly created records.
    3.  bulk_mark_present skips assignments that already have an attendance record.
    4.  Existing attendance records are never overwritten.
    5.  Returns 0 when all assignments are already marked.
    6.  Works on locked operations.
    7.  Works on completed operations.
    8.  Blocked on planning operations (same gate as record_attendance).
    9.  Blocked on archived operations.
    10. Emits attendance.recorded event for each newly-created record.
    11. Mixed case: some marked, some not — only unmarked are touched.
    12. No attendance records deleted by bulk mark.

  HTTP route (POST /attendance/bulk-present):
    13. Owner can POST bulk-present.
    14. Officer can POST bulk-present.
    15. Member POST is denied.
    16. Success redirects with count in message.
    17. "All already marked" message when count is 0.
    18. Idempotent: second call after all marked creates no new records.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError
from app.main import app
from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_full_setup(ws_id: str, num_slots: int = 3, title: str = "Bulk Attendance Op"):
    """
    Workspace → composition (num_slots Healer slots) → operation (planning)
    → slots → signups → assignments.

    Returns (operation, list_of_assignment_dicts).
    """
    slots_def = [
        {
            "party_number": 1,
            "slot_index": i,
            "role": "Healer",
            "build_name": "Hallowfall",
            "priority": "core",
        }
        for i in range(1, num_slots + 1)
    ]
    comp = use_cases.create_albion_composition(ws_id, name="BulkComp", description="", slots=slots_def)
    op = use_cases.create_guild_operation(
        ws_id, title=title, operation_type="zvz", scheduled_start_at="2026-06-07T20:00:00+00:00"
    )
    use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
    generated = use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])

    assignments = []
    for i, slot in enumerate(generated):
        signup = use_cases.submit_signup_intent(ws_id, op["id"], f"Player{i+1}", "Healer")
        asgn = use_cases.assign_participant_to_operation_slot(
            ws_id, op["id"], slot["id"], signup["participant_id"]
        )
        assignments.append(asgn)

    return op, assignments


def _get_attendance_records(ws_id: str, op_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_assignments_with_attendance(db, op_id, ws_id)


def _get_events(ws_id: str, op_id: str, event_type: str) -> list[dict]:
    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws_id, op_id)
    return [e for e in events if e["event_type"] == event_type]


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


# ---------------------------------------------------------------------------
# Use case tests
# ---------------------------------------------------------------------------

def test_bulk_mark_present_creates_records_for_all_unmarked():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=3)
    use_cases.lock_operation(ws["id"], op["id"])

    count = use_cases.bulk_mark_present(ws["id"], op["id"])

    assert count == 3
    rows = _get_attendance_records(ws["id"], op["id"])
    statuses = [r["attendance_status"] for r in rows]
    assert all(s == "present" for s in statuses)


def test_bulk_mark_present_returns_correct_count():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=5)
    use_cases.lock_operation(ws["id"], op["id"])

    count = use_cases.bulk_mark_present(ws["id"], op["id"])

    assert count == 5


def test_bulk_mark_present_skips_already_marked():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=3)
    use_cases.lock_operation(ws["id"], op["id"])

    # Pre-mark the first assignment as absent
    use_cases.record_attendance(ws["id"], op["id"], assignments[0]["id"], "absent")

    count = use_cases.bulk_mark_present(ws["id"], op["id"])

    # Only the 2 unmarked ones should have been created
    assert count == 2


def test_bulk_mark_present_does_not_overwrite_existing_records():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=2)
    use_cases.lock_operation(ws["id"], op["id"])

    # Mark first as 'absent' explicitly
    use_cases.record_attendance(ws["id"], op["id"], assignments[0]["id"], "absent")

    use_cases.bulk_mark_present(ws["id"], op["id"])

    rows = _get_attendance_records(ws["id"], op["id"])
    by_assignment = {r["assignment_id"]: r["attendance_status"] for r in rows}

    # First stays absent — bulk must not overwrite
    assert by_assignment[assignments[0]["id"]] == "absent"
    # Second gets marked present by bulk
    assert by_assignment[assignments[1]["id"]] == "present"


def test_bulk_mark_present_returns_zero_when_all_marked():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=2)
    use_cases.lock_operation(ws["id"], op["id"])

    # Mark all manually first
    for asgn in assignments:
        use_cases.record_attendance(ws["id"], op["id"], asgn["id"], "present")

    count = use_cases.bulk_mark_present(ws["id"], op["id"])

    assert count == 0


def test_bulk_mark_present_works_on_locked_operation():
    ws = make_workspace()
    op, _ = _make_full_setup(ws["id"], num_slots=2)
    use_cases.lock_operation(ws["id"], op["id"])

    count = use_cases.bulk_mark_present(ws["id"], op["id"])

    assert count == 2


def test_bulk_mark_present_works_on_completed_operation():
    ws = make_workspace()
    op, _ = _make_full_setup(ws["id"], num_slots=2)
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])

    count = use_cases.bulk_mark_present(ws["id"], op["id"])

    assert count == 2


def test_bulk_mark_present_blocked_on_planning_operation():
    ws = make_workspace()
    op, _ = _make_full_setup(ws["id"], num_slots=1)
    # operation is in 'planning' after publish — don't lock

    with pytest.raises(ConflictError):
        use_cases.bulk_mark_present(ws["id"], op["id"])


def test_bulk_mark_present_blocked_on_archived_operation():
    ws = make_workspace()
    op, _ = _make_full_setup(ws["id"], num_slots=1)
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    with pytest.raises(ConflictError):
        use_cases.bulk_mark_present(ws["id"], op["id"])


def test_bulk_mark_present_emits_attendance_recorded_event_per_record():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=3)
    use_cases.lock_operation(ws["id"], op["id"])

    use_cases.bulk_mark_present(ws["id"], op["id"])

    events = _get_events(ws["id"], op["id"], "attendance.recorded")
    # 3 new records → 3 events
    assert len(events) == 3


def test_bulk_mark_present_mixed_emits_only_for_new_records():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=3)
    use_cases.lock_operation(ws["id"], op["id"])

    # Pre-mark one (emits 1 event)
    use_cases.record_attendance(ws["id"], op["id"], assignments[0]["id"], "late")

    use_cases.bulk_mark_present(ws["id"], op["id"])

    events = _get_events(ws["id"], op["id"], "attendance.recorded")
    # 1 pre-existing + 2 from bulk = 3 total events
    assert len(events) == 3


def test_bulk_mark_present_does_not_delete_any_records():
    ws = make_workspace()
    op, assignments = _make_full_setup(ws["id"], num_slots=3)
    use_cases.lock_operation(ws["id"], op["id"])

    use_cases.record_attendance(ws["id"], op["id"], assignments[0]["id"], "absent")
    before_rows = _get_attendance_records(ws["id"], op["id"])
    before_marked = sum(1 for r in before_rows if r["attendance_status"] is not None)

    use_cases.bulk_mark_present(ws["id"], op["id"])

    after_rows = _get_attendance_records(ws["id"], op["id"])
    after_marked = sum(1 for r in after_rows if r["attendance_status"] is not None)

    # No records were removed — count only increases
    assert after_marked >= before_marked
    assert after_marked == 3


# ---------------------------------------------------------------------------
# HTTP route tests
# ---------------------------------------------------------------------------

def _setup_locked_op_with_assignments(slug: str, owner_name: str, num_slots: int = 2):
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    op, assignments = _make_full_setup(ws["id"], num_slots=num_slots, title=f"HTTP Test Op {slug}")
    use_cases.lock_operation(ws["id"], op["id"])
    return ws, op, assignments


def test_http_owner_can_bulk_mark_present():
    ws, op, _ = _setup_locked_op_with_assignments("bulk-owner", "BulkOwner1")
    client = TestClient(app)
    _login(client, "BulkOwner1")

    resp = client.post(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance/bulk-present",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def test_http_officer_can_bulk_mark_present():
    owner = make_user("BulkOwner2")
    ws = make_workspace(owner_user_id=owner["id"], slug="bulk-officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "BulkOfficer2", role="officer")
    op, _ = _make_full_setup(ws["id"], num_slots=1, title="Officer Bulk Test")
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "BulkOfficer2")

    resp = client.post(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance/bulk-present",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def test_http_member_bulk_mark_is_denied():
    owner = make_user("BulkOwner3")
    ws = make_workspace(owner_user_id=owner["id"], slug="bulk-member-deny")
    use_cases.add_workspace_member(ws["id"], owner["id"], "BulkMember3", role="member")
    op, _ = _make_full_setup(ws["id"], num_slots=1, title="Member Deny Test")
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "BulkMember3")

    resp = client.post(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance/bulk-present",
        follow_redirects=True,
    )
    # Expect an error redirect (permission denied) — flash message should mention it
    assert "permission" in resp.text.lower() or "not allowed" in resp.text.lower() or "denied" in resp.text.lower() or resp.status_code in (403, 302)


def test_http_success_redirect_contains_count():
    ws, op, assignments = _setup_locked_op_with_assignments("bulk-count-msg", "BulkOwner4", num_slots=3)
    client = TestClient(app)
    _login(client, "BulkOwner4")

    resp = client.post(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance/bulk-present",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "3" in resp.text
    assert "present" in resp.text.lower()


def test_http_all_already_marked_message():
    ws, op, assignments = _setup_locked_op_with_assignments("bulk-all-done", "BulkOwner5", num_slots=2)
    # Pre-mark everything
    for asgn in assignments:
        use_cases.record_attendance(ws["id"], op["id"], asgn["id"], "present")

    client = TestClient(app)
    _login(client, "BulkOwner5")

    resp = client.post(
        f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance/bulk-present",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "already marked" in resp.text.lower()


def test_http_bulk_mark_is_idempotent():
    ws, op, _ = _setup_locked_op_with_assignments("bulk-idem", "BulkOwner6", num_slots=2)
    client = TestClient(app)
    _login(client, "BulkOwner6")

    url = f"/workspaces/{ws['slug']}/operations/{op['id']}/attendance/bulk-present"

    # First call — marks 2
    client.post(url, follow_redirects=True)

    # Second call — nothing to mark
    resp = client.post(url, follow_redirects=True)
    assert resp.status_code == 200
    assert "already marked" in resp.text.lower()

    # DB: still exactly 2 records, none deleted
    rows = _get_attendance_records(ws["id"], op["id"])
    assert sum(1 for r in rows if r["attendance_status"] == "present") == 2
