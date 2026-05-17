"""
Reserve / bench participant tests.

Covers:
  1.  mark_participant_as_reserve: inserts reserve row.
  2.  mark_participant_as_reserve: emits reserve.created event.
  3.  mark_participant_as_reserve: rejects duplicate reserve (already on bench).
  4.  mark_participant_as_reserve: rejects participant without signup.
  5.  mark_participant_as_reserve: rejects participant with active assignment.
  6.  remove_reserve: deletes the reserve row.
  7.  remove_reserve: emits reserve.removed event.
  8.  reserve rows are scoped to guild_workspace_id.
  9.  reserve_count is included in the readiness snapshot.
  10. reserved participant can be assigned to a slot.
  11. assigning a reserved participant removes the reserve row automatically.
  12. active assigned participant cannot be added to reserve.
  13. reserve_count decreases in readiness snapshot after assignment removes reserve.
  14. remove_reserve recalculates readiness atomically.
  15. mark_participant_as_reserve recalculates readiness atomically.
  16. reserve timeline events are operation-scoped.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def reserve_setup():
    """
    Workspace → comp (Tank + Healer) → operation → plan → slots.
    Signs up two participants (TankPlayer, HealerPlayer) but assigns neither.

    Returns (ws, op, slot_tank, slot_healer, tank_signup, healer_signup).
    """
    ws = make_workspace()
    comp = make_composition(
        ws["id"],
        name="ReserveComp",
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

    tank_signup   = use_cases.submit_signup_intent(ws["id"], op["id"], "TankPlayer",   "Tank")
    healer_signup = use_cases.submit_signup_intent(ws["id"], op["id"], "HealerPlayer", "Healer")

    return ws, op, slot_tank, slot_healer, tank_signup, healer_signup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_mark_reserve_creates_row(reserve_setup):
    ws, op, _, _, tank_signup, _ = reserve_setup

    result = use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    assert result["guild_workspace_id"] == ws["id"]
    assert result["guild_operation_id"] == op["id"]
    assert result["participant_id"] == tank_signup["participant_id"]

    with database.transaction() as db:
        row = repositories.get_reserve(
            db, ws["id"], op["id"], tank_signup["participant_id"]
        )
    assert row is not None
    assert row["participant_id"] == tank_signup["participant_id"]


def test_mark_reserve_emits_reserve_created_event(reserve_setup):
    ws, op, _, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    created_events = [e for e in events if e["event_type"] == "reserve.created"]
    assert len(created_events) == 1

    payload = json.loads(created_events[0]["payload_json"])
    assert payload["participant_id"] == tank_signup["participant_id"]
    assert payload["display_name"] == "TankPlayer"


def test_cannot_reserve_participant_twice(reserve_setup):
    ws, op, _, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    with pytest.raises(ConflictError, match="already on reserve"):
        use_cases.mark_participant_as_reserve(
            ws["id"], op["id"], tank_signup["participant_id"]
        )


def test_cannot_reserve_participant_without_signup(reserve_setup):
    ws, op, _, _, _, _ = reserve_setup

    # A participant that exists in the workspace but has NOT signed up.
    ws2 = make_workspace(name="Other", slug="other")
    other_op = make_operation(ws2["id"])
    publish_operation(ws2["id"], other_op["id"])
    stranger_signup = use_cases.submit_signup_intent(
        ws2["id"], other_op["id"], "Stranger", "DPS"
    )

    # The participant exists in ws2, but has no signup in ws/op.
    # We need a participant that exists in ws but has no signup for this op.
    # Use find_or_create to plant one in the target workspace.
    with database.transaction() as db:
        p = repositories.find_or_create_participant(db, ws["id"], "NoSignupGuy")

    with pytest.raises(ConflictError, match="no signup intent"):
        use_cases.mark_participant_as_reserve(ws["id"], op["id"], p["id"])


def test_cannot_reserve_assigned_participant(reserve_setup):
    """Active assigned participant cannot be added to reserve."""
    ws, op, slot_tank, _, tank_signup, _ = reserve_setup

    # Assign TankPlayer first.
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_tank["id"], tank_signup["participant_id"]
    )

    with pytest.raises(ConflictError, match="active assignment"):
        use_cases.mark_participant_as_reserve(
            ws["id"], op["id"], tank_signup["participant_id"]
        )


def test_remove_reserve_deletes_row(reserve_setup):
    ws, op, _, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )
    use_cases.remove_reserve(ws["id"], op["id"], tank_signup["participant_id"])

    with database.transaction() as db:
        row = repositories.get_reserve(
            db, ws["id"], op["id"], tank_signup["participant_id"]
        )
    assert row is None


def test_remove_reserve_emits_reserve_removed_event(reserve_setup):
    ws, op, _, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )
    use_cases.remove_reserve(ws["id"], op["id"], tank_signup["participant_id"])

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    removed_events = [e for e in events if e["event_type"] == "reserve.removed"]
    assert len(removed_events) == 1

    payload = json.loads(removed_events[0]["payload_json"])
    assert payload["participant_id"] == tank_signup["participant_id"]


def test_reserve_is_guild_scoped(reserve_setup):
    """Reserves from one workspace cannot be removed via a different workspace."""
    ws, op, _, _, tank_signup, _ = reserve_setup
    other_ws = make_workspace(name="Other Guild", slug="other")

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    with pytest.raises(NotFoundError):
        use_cases.remove_reserve(other_ws["id"], op["id"], tank_signup["participant_id"])

    # Row must still exist in the original workspace.
    with database.transaction() as db:
        row = repositories.get_reserve(
            db, ws["id"], op["id"], tank_signup["participant_id"]
        )
    assert row is not None


def test_reserve_count_included_in_readiness_snapshot(reserve_setup):
    ws, op, _, _, tank_signup, healer_signup = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )
    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], healer_signup["participant_id"]
    )

    # mark_participant_as_reserve recalculates readiness internally; read the latest.
    with database.transaction() as db:
        snapshot = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert snapshot is not None
    assert snapshot["reserve_count"] == 2


def test_reserved_participant_can_be_assigned_to_slot(reserve_setup):
    ws, op, slot_tank, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    # Assignment must succeed even when the participant is on reserve.
    asgn = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_tank["id"], tank_signup["participant_id"]
    )

    assert asgn["participant_id"] == tank_signup["participant_id"]
    assert asgn["status"] == "assigned"


def test_assigning_reserved_participant_removes_reserve_row(reserve_setup):
    """
    Assigning a reserved participant to a slot must automatically remove their
    reserve row in the same transaction.
    """
    ws, op, slot_tank, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_tank["id"], tank_signup["participant_id"]
    )

    with database.transaction() as db:
        row = repositories.get_reserve(
            db, ws["id"], op["id"], tank_signup["participant_id"]
        )

    assert row is None, "Reserve row must be removed automatically when the participant is assigned"


def test_reserve_count_decreases_after_assignment(reserve_setup):
    """
    When a reserved participant is assigned, the reserve row is removed in the
    same transaction and readiness is recalculated.  The snapshot must reflect
    the lower reserve_count immediately — no separate recalculate call needed.
    """
    ws, op, slot_tank, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    with database.transaction() as db:
        before = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])
    assert before["reserve_count"] == 1

    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_tank["id"], tank_signup["participant_id"]
    )

    with database.transaction() as db:
        after = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert after["reserve_count"] == 0


def test_remove_reserve_recalculates_readiness(reserve_setup):
    """
    remove_reserve must recalculate readiness within the same transaction
    so the snapshot immediately reflects the updated bench count.
    """
    ws, op, _, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    with database.transaction() as db:
        before = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])
    assert before["reserve_count"] == 1

    use_cases.remove_reserve(ws["id"], op["id"], tank_signup["participant_id"])

    with database.transaction() as db:
        after = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert after["reserve_count"] == 0


def test_mark_reserve_recalculates_readiness(reserve_setup):
    """
    mark_participant_as_reserve must recalculate readiness within the same
    transaction so the snapshot immediately reflects the new bench count.
    """
    ws, op, _, _, tank_signup, _ = reserve_setup

    # Establish a baseline snapshot (no reserves yet).
    use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    with database.transaction() as db:
        before = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])
    assert before["reserve_count"] == 0

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )

    with database.transaction() as db:
        after = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert after["reserve_count"] == 1


def test_reserve_timeline_events_are_operation_scoped(reserve_setup):
    """
    reserve.created and reserve.removed events must be associated with the
    correct guild_operation_id (operation-level timeline, not workspace-level).
    """
    ws, op, _, _, tank_signup, _ = reserve_setup

    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], tank_signup["participant_id"]
    )
    use_cases.remove_reserve(ws["id"], op["id"], tank_signup["participant_id"])

    with database.transaction() as db:
        # Query for this specific operation's timeline.
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    event_types = [e["event_type"] for e in events]
    assert "reserve.created" in event_types
    assert "reserve.removed" in event_types

    for e in events:
        if e["event_type"] in ("reserve.created", "reserve.removed"):
            assert e["guild_operation_id"] == op["id"], (
                f"Event {e['event_type']} must carry guild_operation_id={op['id']!r}, "
                f"got {e['guild_operation_id']!r}"
            )
            assert e["guild_workspace_id"] == ws["id"]
