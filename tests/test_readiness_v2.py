"""
ReadinessSnapshot v2 tests.

Verifies that calculate_readiness_snapshot() correctly populates the four
new fields:  attendance_marked_count, attendance_unmarked_count,
scout_count, support_count.

Also verifies that:
  - missing_roles_json is a dict of role → open-slot count.
  - The readiness_state is based solely on slot/assignment coverage; attendance
    and scout data do NOT gate the state.
"""

from __future__ import annotations

import json

from app import database, repositories
from app.application import use_cases

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Shared fixture builder
# ---------------------------------------------------------------------------

def _make_full_setup(*, n_slots: int = 3, assign_all: bool = True):
    """
    Returns (ws, op, slots, assignments).

    Creates a composition with n_slots identical Healer slots, generates
    them, signs up n_slots+1 participants, and optionally assigns all.
    """
    ws = make_workspace()
    comp = make_composition(
        ws["id"],
        name="TestComp",
        slots=[
            {"party_number": 1, "slot_index": i + 1,
             "role": roles[i % len(roles)], "build_name": "Build", "priority": "core"}
            for i in range(n_slots)
        ],
    )
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])

    signups, assignments = [], []
    for i in range(n_slots):
        s = use_cases.submit_signup_intent(
            ws["id"], op["id"], f"Player{i}", "Healer"
        )
        signups.append(s)
        if assign_all:
            a = use_cases.assign_participant_to_operation_slot(
                ws["id"], op["id"], slots[i]["id"], s["participant_id"]
            )
            assignments.append(a)

    return ws, op, slots, assignments


# Different roles to make missing_roles tests interesting.
roles = ["Tank", "Healer", "DPS"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_readiness_includes_open_slots():
    ws, op, slots, assignments = _make_full_setup(n_slots=3, assign_all=False)

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    assert snapshot["total_slots"] == 3
    assert snapshot["assigned_slots"] == 0
    assert snapshot["open_slots"] == 3


def test_readiness_missing_roles_reflects_open_slots():
    ws, op, slots, assignments = _make_full_setup(n_slots=3, assign_all=False)

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    missing = json.loads(snapshot["missing_roles_json"])
    # missing_roles_json is now a dict of role → count.
    # 3 slots: Tank (×1), Healer (×1), DPS (×1) — all unassigned.
    assert missing == {"DPS": 1, "Healer": 1, "Tank": 1}


def test_readiness_missing_roles_empty_when_fully_assigned():
    ws, op, slots, assignments = _make_full_setup(n_slots=3, assign_all=True)

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    missing = json.loads(snapshot["missing_roles_json"])
    assert missing == {}


def test_readiness_includes_attendance_marked_count():
    ws, op, slots, assignments = _make_full_setup(n_slots=3, assign_all=True)
    use_cases.lock_operation(ws["id"], op["id"])

    # Mark 2 of the 3 assigned participants.
    use_cases.record_attendance(ws["id"], op["id"], assignments[0]["id"], "present")
    use_cases.record_attendance(ws["id"], op["id"], assignments[1]["id"], "late")

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    assert snapshot["attendance_marked_count"] == 2
    assert snapshot["attendance_unmarked_count"] == 1


def test_readiness_includes_scout_support_counts():
    ws, op, slots, _ = _make_full_setup(n_slots=2, assign_all=True)

    use_cases.record_scout_attendance(ws["id"], op["id"], "Scout1", "scout")
    use_cases.record_scout_attendance(ws["id"], op["id"], "Helper1", "support")
    use_cases.record_scout_attendance(ws["id"], op["id"], "Helper2", "support")

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    assert snapshot["scout_count"] == 1
    assert snapshot["support_count"] == 2


def test_readiness_state_not_affected_by_attendance_data():
    """
    All slots assigned → state is 'ready' even when no attendance is marked
    and scouts/support have checked in.
    """
    ws, op, slots, assignments = _make_full_setup(n_slots=2, assign_all=True)

    use_cases.record_scout_attendance(ws["id"], op["id"], "Scout1", "scout")
    # Deliberately do NOT record attendance for any assigned participant.

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    assert snapshot["readiness_state"] == "ready"
    assert snapshot["attendance_marked_count"] == 0
    assert snapshot["attendance_unmarked_count"] == 2
    assert snapshot["scout_count"] == 1


def test_readiness_zero_counts_when_no_assignments():
    ws = make_workspace()
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    # No signups, no assignments, no attendance, no scouts.

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    assert snapshot["attendance_marked_count"] == 0
    assert snapshot["attendance_unmarked_count"] == 0
    assert snapshot["scout_count"] == 0
    assert snapshot["support_count"] == 0
    assert snapshot["readiness_state"] == "not_ready"
