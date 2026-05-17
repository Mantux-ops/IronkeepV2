"""
Quick assignment workflow tests.

Covers:
  1.  quick_assign_slot picks the exact-match (tier-1) candidate first.
  2.  quick_assign_slot picks role-match (tier-2) over fill (tier-3).
  3.  quick_assign_slot uses fill willingness when no role/build match exists.
  4.  quick_assign_slot skips reserved participants entirely.
  5.  quick_assign_slot raises ConflictError when no eligible candidates.
  6.  quick_assign_slot emits assignment.created event.
  7.  quick_assign_slot recalculates readiness.
  8.  quick_fill_party fills all open slots in a party.
  9.  quick_fill_party skips already-assigned slots.
  10. quick_fill_party does not double-assign the same participant.
  11. quick_fill_party partial-fills when candidates are insufficient.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _setup(slots_spec: list[dict]):
    """
    Create workspace → comp → operation → plan → generate slots.
    Returns (ws, op, slots).
    """
    ws = make_workspace()
    comp = make_composition(ws["id"], name="QAComp", slots=slots_spec)
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    return ws, op, slots


def _signup(ws, op, name, role, build=None, willingness="specific", availability="confirmed"):
    return use_cases.submit_signup_intent(
        ws["id"], op["id"], name, role,
        preferred_build_name=build,
        willingness=willingness,
        availability=availability,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_quick_assign_picks_exact_match_first():
    """
    Two candidates for a Tank/Mace slot:
      - ExactPlayer: Tank/Mace/specific (tier 1)
      - RolePlayer:  Tank/Bow/specific  (tier 2)
    quick_assign_slot must pick ExactPlayer.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Mace", "priority": "core"},
    ])
    slot = slots[0]

    exact_signup = _signup(ws, op, "ExactPlayer", "Tank", build="Mace")
    role_signup  = _signup(ws, op, "RolePlayer",  "Tank", build="Bow")

    asgn = use_cases.quick_assign_slot(ws["id"], op["id"], slot["id"])

    assert asgn["participant_id"] == exact_signup["participant_id"]


def test_quick_assign_picks_role_match_over_fill():
    """
    Two candidates for a Healer/Hallowfall slot:
      - RoleMatch: Healer/Daggers/specific (tier 2 — role only)
      - FillPlayer: DPS/Bow/fill            (tier 3 — fill, no role match)
    quick_assign_slot must pick RoleMatch.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    ])
    slot = slots[0]

    role_signup = _signup(ws, op, "RoleMatch",  "Healer", build="Daggers")
    fill_signup = _signup(ws, op, "FillPlayer", "DPS",    build="Bow",    willingness="fill")

    asgn = use_cases.quick_assign_slot(ws["id"], op["id"], slot["id"])

    assert asgn["participant_id"] == role_signup["participant_id"]


def test_quick_assign_uses_fill_when_no_role_match():
    """
    Only candidate is a fill-willingness player with no role match (tier 3).
    quick_assign_slot must still assign them — fill is always eligible.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Support", "build_name": "Locus", "priority": "core"},
    ])
    slot = slots[0]

    fill_signup = _signup(ws, op, "AnybodyPlayer", "DPS", build="Bow", willingness="fill")

    asgn = use_cases.quick_assign_slot(ws["id"], op["id"], slot["id"])

    assert asgn["participant_id"] == fill_signup["participant_id"]


def test_quick_assign_skips_reserved_participants():
    """
    Best candidate (exact match) is on reserve.  The second candidate (role match)
    must be assigned instead — reserved players are excluded from the pool.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Mace", "priority": "core"},
    ])
    slot = slots[0]

    exact_signup = _signup(ws, op, "ExactReserved", "Tank", build="Mace")
    role_signup  = _signup(ws, op, "RolePlayer",    "Tank", build="Bow")

    # Place the exact-match player on reserve.
    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], exact_signup["participant_id"]
    )

    asgn = use_cases.quick_assign_slot(ws["id"], op["id"], slot["id"])

    assert asgn["participant_id"] == role_signup["participant_id"], (
        "Reserved participant must be skipped even if they are the best match"
    )


def test_quick_assign_no_candidates_raises_error():
    """
    When all signed-up participants are reserved or already assigned,
    quick_assign_slot must raise ConflictError.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Mace", "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    ])
    slot_tank, slot_healer = slots[0], slots[1]

    only_signup = _signup(ws, op, "OnlyPlayer", "Tank", build="Mace")

    # Reserve the only eligible candidate.
    use_cases.mark_participant_as_reserve(
        ws["id"], op["id"], only_signup["participant_id"]
    )

    with pytest.raises(ConflictError, match="No eligible participants"):
        use_cases.quick_assign_slot(ws["id"], op["id"], slot_tank["id"])


def test_quick_assign_emits_assignment_created_event():
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Bow", "priority": "core"},
    ])
    slot = slots[0]
    _signup(ws, op, "Archer", "DPS", build="Bow")

    use_cases.quick_assign_slot(ws["id"], op["id"], slot["id"])

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])

    created = [e for e in events if e["event_type"] == "assignment.created"]
    assert len(created) == 1
    payload = json.loads(created[0]["payload_json"])
    assert payload["operation_slot_id"] == slot["id"]


def test_quick_assign_recalculates_readiness():
    """
    quick_assign_slot must persist a new readiness snapshot reflecting the
    now-filled slot — no separate recalculate call required.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Bow", "priority": "core"},
    ])
    slot = slots[0]
    _signup(ws, op, "Archer", "DPS", build="Bow")

    with database.transaction() as db:
        before = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])
    assert before is None  # No snapshot yet.

    use_cases.quick_assign_slot(ws["id"], op["id"], slot["id"])

    with database.transaction() as db:
        after = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert after is not None
    assert after["open_slots"] == 0
    assert after["readiness_state"] == "ready"


def test_quick_fill_party_fills_all_open_slots():
    """
    Party 1 has 2 open slots and 2 matching candidates → both slots filled.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Mace",       "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    ])
    _signup(ws, op, "TankPlayer",   "Tank",   build="Mace")
    _signup(ws, op, "HealerPlayer", "Healer", build="Hallowfall")

    result = use_cases.quick_fill_party(ws["id"], op["id"], party_number=1)

    assert result["filled_count"] == 2
    assert result["total_open"] == 2


def test_quick_fill_party_skips_already_assigned_slots():
    """
    Tank slot is already assigned; Healer slot is open.
    quick_fill_party must only fill the open Healer slot.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Mace",       "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    ])
    slot_tank   = next(s for s in slots if s["role"] == "Tank")
    slot_healer = next(s for s in slots if s["role"] == "Healer")

    tank_s   = _signup(ws, op, "TankPlayer",   "Tank",   build="Mace")
    healer_s = _signup(ws, op, "HealerPlayer", "Healer", build="Hallowfall")

    # Pre-assign the tank slot manually.
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot_tank["id"], tank_s["participant_id"]
    )

    result = use_cases.quick_fill_party(ws["id"], op["id"], party_number=1)

    assert result["filled_count"] == 1
    assert result["total_open"] == 1

    with database.transaction() as db:
        asgn_map = repositories.get_assigned_participants_for_operation(
            db, op["id"], ws["id"]
        )
    assert slot_healer["id"] in asgn_map
    assert asgn_map[slot_healer["id"]]["participant_id"] == healer_s["participant_id"]


def test_quick_fill_party_does_not_double_assign_same_participant():
    """
    Only one candidate available for two open slots.
    quick_fill_party must assign them to the first slot and leave the second open.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Bow",     "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "DPS", "build_name": "Daggers", "priority": "core"},
    ])
    _signup(ws, op, "OnlyDPS", "DPS", build="Bow", willingness="fill")

    result = use_cases.quick_fill_party(ws["id"], op["id"], party_number=1)

    # Only 1 slot can be filled — the candidate is removed from the pool after.
    assert result["filled_count"] == 1
    assert result["total_open"] == 2

    with database.transaction() as db:
        asgn_map = repositories.get_assigned_participants_for_operation(
            db, op["id"], ws["id"]
        )
    assert len(asgn_map) == 1


def test_quick_fill_party_partial_fill_when_insufficient_candidates():
    """
    3 open slots, 2 candidates.  quick_fill_party fills what it can and
    leaves the remaining slot open — no error is raised.
    """
    ws, op, slots = _setup([
        {"party_number": 1, "slot_index": 1, "role": "Tank",    "build_name": "Mace",  "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer",  "build_name": "Staff", "priority": "core"},
        {"party_number": 1, "slot_index": 3, "role": "Support", "build_name": "Locus", "priority": "core"},
    ])
    _signup(ws, op, "TankPlayer",   "Tank",   build="Mace",  willingness="fill")
    _signup(ws, op, "HealerPlayer", "Healer", build="Staff", willingness="fill")
    # No one signed up for Support.

    result = use_cases.quick_fill_party(ws["id"], op["id"], party_number=1)

    assert result["filled_count"] == 2
    assert result["total_open"] == 3

    with database.transaction() as db:
        snapshot = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert snapshot["open_slots"] == 1
