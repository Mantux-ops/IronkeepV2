"""
Attendance foundation tests.

Covers:
  - Creating a new attendance record.
  - Status is persisted correctly.
  - attendance.recorded OperationalEvent is emitted.
  - Re-marking is an upsert (no duplicate row).
  - Re-mark event includes previous_status.
  - All five valid statuses are accepted.
  - Invalid status raises ValidationError.
  - Attendance for an unknown assignment raises NotFoundError.
  - Attendance is guild_workspace scoped.
  - Attendance page data only includes active assignments (not raw signups).
  - Attendance cannot be recorded for a 'removed' assignment.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.domain.attendance import VALID_STATUSES
from app.errors import ConflictError, NotFoundError, ValidationError

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def assigned_setup():
    """
    Full chain: workspace → composition (1 Healer slot) → operation → plan
    → slots → signup → assignment.

    Returns (workspace, operation, slot, assignment).
    """
    ws = make_workspace()
    comp = make_composition(
        ws["id"],
        name="AttendanceComp",
        slots=[
            {
                "party_number": 1,
                "slot_index": 1,
                "role": "Healer",
                "build_name": "Hallowfall",
                "priority": "core",
            }
        ],
    )
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "TestPlayer", "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    return ws, op, slots[0], assignment


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_record_attendance_creates_record(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    record = use_cases.record_attendance(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        assignment_id=assignment["id"],
        status="present",
    )

    assert record["id"] is not None
    assert record["guild_workspace_id"] == ws["id"]
    assert record["guild_operation_id"] == op["id"]
    assert record["assignment_id"] == assignment["id"]
    assert record["participant_id"] == assignment["participant_id"]


def test_attendance_status_stored_correctly(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    use_cases.record_attendance(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        assignment_id=assignment["id"],
        status="late",
        notes="Joined after pull",
    )

    with database.transaction() as db:
        row = repositories.get_attendance_record(
            db, ws["id"], op["id"], assignment["id"]
        )

    assert row is not None
    assert row["status"] == "late"
    assert row["notes"] == "Joined after pull"


def test_record_attendance_emits_event(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    use_cases.record_attendance(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        assignment_id=assignment["id"],
        status="present",
    )

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    attendance_events = [e for e in events if e["event_type"] == "attendance.recorded"]
    assert len(attendance_events) == 1

    payload = json.loads(attendance_events[0]["payload_json"])
    assert payload["status"] == "present"
    assert payload["assignment_id"] == assignment["id"]
    assert "previous_status" not in payload


def test_re_recording_updates_status_not_inserts(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "present")
    use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "late")

    with database.transaction() as db:
        records = repositories.get_attendance_records_for_operation(db, op["id"], ws["id"])

    assert len(records) == 1
    assert records[0]["status"] == "late"


def test_re_recording_event_includes_previous_status(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "present")
    use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "absent")

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    attendance_events = [e for e in events if e["event_type"] == "attendance.recorded"]
    assert len(attendance_events) == 2

    correction_payload = json.loads(attendance_events[1]["payload_json"])
    assert correction_payload["status"] == "absent"
    assert correction_payload["previous_status"] == "present"


def test_all_valid_statuses_accepted(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    for status in VALID_STATUSES:
        record = use_cases.record_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            assignment_id=assignment["id"],
            status=status,
        )
        assert record["status"] == status


def test_invalid_status_rejected(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    with pytest.raises(ValidationError, match="Invalid attendance status"):
        use_cases.record_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            assignment_id=assignment["id"],
            status="showed_up_maybe",
        )


def test_attendance_requires_active_assignment(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    with pytest.raises(NotFoundError):
        use_cases.record_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            assignment_id="nonexistent-id",
            status="present",
        )


def test_attendance_is_guild_scoped(assigned_setup):
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    other_ws = make_workspace(name="Other Guild", slug="other")

    with pytest.raises(NotFoundError):
        use_cases.record_attendance(
            guild_workspace_id=other_ws["id"],
            guild_operation_id=op["id"],
            assignment_id=assignment["id"],
            status="present",
        )


def test_attendance_page_data_excludes_unassigned_signers(assigned_setup):
    ws, op, slot, assignment = assigned_setup

    # Add a second signup without assigning them
    use_cases.submit_signup_intent(ws["id"], op["id"], "UnassignedPlayer", "DPS")

    with database.transaction() as db:
        rows = repositories.get_assignments_with_attendance(db, op["id"], ws["id"])

    # Only the assigned participant appears; the unassigned signer is excluded
    assert len(rows) == 1
    assert rows[0]["assignment_id"] == assignment["id"]


def test_cannot_record_attendance_for_removed_assignment(assigned_setup):
    """
    An assignment whose status is 'removed' must not receive an attendance
    record.  ConflictError is expected.
    """
    ws, op, slot, assignment = assigned_setup
    use_cases.lock_operation(ws["id"], op["id"])

    # Directly set the assignment to 'removed' (no remove use case in this slice)
    import sqlite3
    conn = sqlite3.connect(database._DB_PATH)
    conn.execute(
        "UPDATE assignments SET status = 'removed' WHERE id = ?",
        (assignment["id"],),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ConflictError, match="removed"):
        use_cases.record_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            assignment_id=assignment["id"],
            status="present",
        )
