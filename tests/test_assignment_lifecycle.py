"""
Assignment lifecycle tests.

Covers:
  - remove_assignment: sets status='removed', emits event, keeps row.
  - remove_assignment: frees the slot for reassignment.
  - remove_assignment: rejects double-remove.
  - remove_assignment: guild-workspace scoped.
  - remove_assignment: cannot remove assignment belonging to another operation.
  - remove_assignment: recalculates readiness atomically within the same call.
  - assign_participant_to_operation_slot: rejects double-assignment.
  - Full remove → reassign to different slot flow.
  - set_assignment_status: UPDATE does not mutate rows outside requested scope.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def two_slot_setup():
    """
    Workspace → comp (2 slots: Tank + Healer) → operation → plan → slots.
    Signs up 2 participants and assigns both.

    Returns (ws, op, slot_tank, slot_healer, assignment_tank, assignment_healer).
    """
    ws = make_workspace()
    comp = make_composition(
        ws["id"],
        name="TwoSlotComp",
        slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Mace",       "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
        ],
    )
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    slot_tank   = next(s for s in slots if s["role"] == "Tank")
    slot_healer = next(s for s in slots if s["role"] == "Healer")

    signup_tank   = use_cases.submit_signup_intent(ws["id"], op["id"], "TankPlayer",   "Tank")
    signup_healer = use_cases.submit_signup_intent(ws["id"], op["id"], "HealerPlayer", "Healer")

    asgn_tank   = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_tank["id"],   signup_tank["participant_id"]
    )
    asgn_healer = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_healer["id"], signup_healer["participant_id"]
    )
    return ws, op, slot_tank, slot_healer, asgn_tank, asgn_healer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_remove_assignment_sets_status_removed(two_slot_setup):
    ws, op, slot_tank, _, asgn_tank, _ = two_slot_setup

    result = use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    assert result["status"] == "removed"

    with database.transaction() as db:
        row = repositories.get_assignment_by_id(db, asgn_tank["id"], ws["id"])
    assert row["status"] == "removed"


def test_remove_assignment_emits_removed_event(two_slot_setup):
    ws, op, slot_tank, _, asgn_tank, _ = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    removed_events = [e for e in events if e["event_type"] == "assignment.removed"]
    assert len(removed_events) == 1

    payload = json.loads(removed_events[0]["payload_json"])
    assert payload["participant_id"] == asgn_tank["participant_id"]
    assert payload["operation_slot_id"] == slot_tank["id"]


def test_removed_assignment_row_is_kept_not_deleted(two_slot_setup):
    ws, op, slot_tank, _, asgn_tank, _ = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with database.transaction() as db:
        row = repositories.get_assignment_by_id(db, asgn_tank["id"], ws["id"])

    assert row is not None
    assert row["id"] == asgn_tank["id"]
    assert row["status"] == "removed"


def test_remove_frees_slot_for_reassignment(two_slot_setup):
    ws, op, slot_tank, _, asgn_tank, _ = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with database.transaction() as db:
        active = repositories.get_active_assignment_for_slot(db, slot_tank["id"])

    assert active is None


def test_cannot_remove_already_removed_assignment(two_slot_setup):
    ws, op, slot_tank, _, asgn_tank, _ = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with pytest.raises(ConflictError, match="removed"):
        use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])


def test_remove_assignment_is_guild_scoped(two_slot_setup):
    ws, op, _, _, asgn_tank, _ = two_slot_setup
    other_ws = make_workspace(name="Other Guild", slug="other")

    with pytest.raises(NotFoundError):
        use_cases.remove_assignment(other_ws["id"], op["id"], asgn_tank["id"])


def test_participant_can_be_reassigned_to_different_slot_after_removal(two_slot_setup):
    """
    Full lifecycle: TankPlayer is removed from the Tank slot, then reassigned
    to the (now open) Healer slot after HealerPlayer is also removed.
    """
    ws, op, slot_tank, slot_healer, asgn_tank, asgn_healer = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])
    use_cases.remove_assignment(ws["id"], op["id"], asgn_healer["id"])

    new_asgn = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_healer["id"], asgn_tank["participant_id"]
    )

    assert new_asgn["operation_slot_id"] == slot_healer["id"]
    assert new_asgn["participant_id"] == asgn_tank["participant_id"]
    assert new_asgn["status"] == "assigned"


def test_cannot_assign_participant_already_active_in_same_operation(two_slot_setup):
    """
    TankPlayer is already assigned. Trying to assign the same participant to
    the Healer slot (without removing first) must raise ConflictError.
    """
    ws, op, _, slot_healer, asgn_tank, asgn_healer = two_slot_setup

    # Remove HealerPlayer to free the Healer slot first, then try to put
    # TankPlayer (still active) into it — should be rejected.
    use_cases.remove_assignment(ws["id"], op["id"], asgn_healer["id"])

    with pytest.raises(ConflictError, match="already has an active assignment"):
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slot_healer["id"], asgn_tank["participant_id"]
        )


def test_remove_assignment_recalculates_readiness(two_slot_setup):
    """
    After remove_assignment the latest readiness snapshot must reflect the
    freed slot — no separate recalculate call required.
    """
    ws, op, _, _, asgn_tank, _ = two_slot_setup

    # Establish a 'ready' baseline (both slots assigned).
    use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    with database.transaction() as db:
        before = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])
    assert before["readiness_state"] == "ready"
    assert before["open_slots"] == 0

    # Remove one assignment — readiness must update atomically.
    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with database.transaction() as db:
        after = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert after["open_slots"] == 1
    assert after["readiness_state"] != "ready"


# ---------------------------------------------------------------------------
# Invariant hardening tests
# ---------------------------------------------------------------------------

def test_cannot_remove_assignment_from_different_operation(two_slot_setup):
    """
    An assignment that belongs to operation A must be rejected when the caller
    passes operation B's id — even if both operations live in the same workspace.
    """
    ws, op_a, _, _, asgn_tank, _ = two_slot_setup

    # Create a second operation in the same workspace (no plan/slots needed).
    op_b = make_operation(ws["id"], title="Second Op")

    with pytest.raises((NotFoundError, Exception)) as exc_info:
        use_cases.remove_assignment(ws["id"], op_b["id"], asgn_tank["id"])

    # Must not succeed — any error is acceptable, but the assignment must be
    # unchanged.
    with database.transaction() as db:
        row = repositories.get_assignment_by_id(db, asgn_tank["id"], ws["id"])
    assert row["status"] == "assigned"


def test_set_assignment_status_does_not_mutate_other_operation(two_slot_setup):
    """
    The repository UPDATE is scoped by both guild_workspace_id AND
    guild_operation_id.  Passing a wrong operation_id must leave the row
    untouched (0 rows affected — SQLite silently no-ops).
    """
    ws, op, _, _, asgn_tank, _ = two_slot_setup

    op_b = make_operation(ws["id"], title="Unrelated Op")

    # Direct repository call with the wrong operation_id.
    with database.transaction() as db:
        repositories.set_assignment_status(
            db, asgn_tank["id"], op_b["id"], "removed", ws["id"]
        )

    with database.transaction() as db:
        row = repositories.get_assignment_by_id(db, asgn_tank["id"], ws["id"])

    # Row must be untouched — wrong operation scope should cause 0 rows matched.
    assert row["status"] == "assigned"


def test_remove_already_removed_assignment_raises_conflict(two_slot_setup):
    """
    Removing the same assignment twice must raise ConflictError on the second
    call.  The row must still exist and remain 'removed'.
    """
    ws, op, _, _, asgn_tank, _ = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with pytest.raises(ConflictError, match="removed"):
        use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with database.transaction() as db:
        row = repositories.get_assignment_by_id(db, asgn_tank["id"], ws["id"])
    assert row is not None
    assert row["status"] == "removed"


def test_readiness_recalculated_after_hardened_removal(two_slot_setup):
    """
    Readiness snapshot is persisted inside the same transaction as the removal
    even after the repository hardening (guild_operation_id scoping).
    """
    ws, op, _, _, asgn_tank, _ = two_slot_setup

    use_cases.remove_assignment(ws["id"], op["id"], asgn_tank["id"])

    with database.transaction() as db:
        snapshot = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert snapshot is not None
    assert snapshot["open_slots"] == 1
