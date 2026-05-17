"""
Role-gap readiness tests.

Verifies that ReadinessSnapshot correctly reports:
  - missing_roles_json as a dict of role → open-slot count.
  - missing_builds_json as a dict of build_name → open-slot count.
  - Both are {} when all slots are assigned.
  - Both count correctly under partial assignment scenarios.
  - missing_builds_json is persisted to and retrievable from the DB.
  - Multiple build types for the same role are counted separately.

Source for both dicts: operation_slots + active assignments only.
CompositionSlotTemplates are never read.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _setup_custom_comp(slots_spec: list[dict]):
    """
    Create workspace → custom comp → operation → plan → generate slots.
    Returns (ws, op, slots).
    """
    ws = make_workspace()
    comp = make_composition(ws["id"], name="GapTestComp", slots=slots_spec)
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    return ws, op, slots


def _signup_and_assign(ws, op, slot, name):
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], name, slot["role"])
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slot["id"], signup["participant_id"]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_missing_roles_json_is_dict_with_counts():
    """
    With 2 open DPS slots (no assignments), missing_roles_json must be
    {"DPS": 2} — not a list.
    """
    ws, op, slots = _setup_custom_comp([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Daggers", "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "DPS", "build_name": "Bow",     "priority": "core"},
    ])

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    missing = json.loads(snapshot["missing_roles_json"])
    assert isinstance(missing, dict), "missing_roles_json must be a dict, not a list"
    assert missing == {"DPS": 2}


def test_missing_builds_json_counts_open_slots_by_build():
    """
    Two open slots with distinct builds must each appear in missing_builds_json.
    """
    ws, op, slots = _setup_custom_comp([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Daggers", "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "DPS", "build_name": "Bow",     "priority": "core"},
    ])

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    builds = json.loads(snapshot["missing_builds_json"])
    assert builds == {"Bow": 1, "Daggers": 1}


def test_fully_assigned_has_empty_gaps():
    """
    When every slot has an active assignment both gap dicts must be {}.
    """
    ws, op, slots = _setup_custom_comp([
        {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Mace",       "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    ])
    _signup_and_assign(ws, op, slots[0], "TankPlayer")
    _signup_and_assign(ws, op, slots[1], "HealerPlayer")

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    assert json.loads(snapshot["missing_roles_json"])  == {}
    assert json.loads(snapshot["missing_builds_json"]) == {}


def test_partial_assignment_correct_role_and_build_counts():
    """
    5-slot comp: Tank/Mace, Healer/Hallowfall, DPS/Daggers, DPS/Bow, Support/Locus.
    Assign Tank and one DPS (Daggers).  Remaining open: Healer, DPS/Bow, Support.
    """
    ws, op, slots = _setup_custom_comp([
        {"party_number": 1, "slot_index": 1, "role": "Tank",    "build_name": "Mace",       "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "Healer",  "build_name": "Hallowfall", "priority": "core"},
        {"party_number": 1, "slot_index": 3, "role": "DPS",     "build_name": "Daggers",    "priority": "core"},
        {"party_number": 1, "slot_index": 4, "role": "DPS",     "build_name": "Bow",        "priority": "core"},
        {"party_number": 1, "slot_index": 5, "role": "Support", "build_name": "Locus",      "priority": "core"},
    ])

    slot_by_build = {s["build_name"]: s for s in slots}
    _signup_and_assign(ws, op, slot_by_build["Mace"],    "TankPlayer")
    _signup_and_assign(ws, op, slot_by_build["Daggers"], "DPSPlayer")

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    roles  = json.loads(snapshot["missing_roles_json"])
    builds = json.loads(snapshot["missing_builds_json"])

    assert roles  == {"DPS": 1, "Healer": 1, "Support": 1}
    assert builds == {"Bow": 1, "Hallowfall": 1, "Locus": 1}


def test_missing_builds_included_in_snapshot_row():
    """
    missing_builds_json must survive the INSERT → SELECT round-trip through SQLite.
    """
    ws, op, slots = _setup_custom_comp([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Shadowcaller", "priority": "core"},
    ])

    use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    with database.transaction() as db:
        row = repositories.get_latest_readiness_snapshot(db, op["id"], ws["id"])

    assert row is not None
    builds = json.loads(row["missing_builds_json"])
    assert builds == {"Shadowcaller": 1}


def test_single_role_multiple_builds_counted_separately():
    """
    Three open DPS slots with three different builds must appear as three
    separate entries in missing_builds_json and as DPS ×3 in missing_roles_json.
    """
    ws, op, slots = _setup_custom_comp([
        {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Bow",          "priority": "core"},
        {"party_number": 1, "slot_index": 2, "role": "DPS", "build_name": "Daggers",      "priority": "core"},
        {"party_number": 1, "slot_index": 3, "role": "DPS", "build_name": "Shadowcaller", "priority": "core"},
    ])

    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    roles  = json.loads(snapshot["missing_roles_json"])
    builds = json.loads(snapshot["missing_builds_json"])

    assert roles  == {"DPS": 3}
    assert builds == {"Bow": 1, "Daggers": 1, "Shadowcaller": 1}
