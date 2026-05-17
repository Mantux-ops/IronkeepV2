"""
Full happy-path integration test for the first vertical slice.

Exercises the complete command flow end-to-end:
  create workspace → create operation → create composition →
  attach plan → generate slots → submit signup →
  assign participant → calculate readiness → verify events
"""

import json

import pytest

from app import database, repositories
from app.application import use_cases
from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def workspace():
    return make_workspace()


@pytest.fixture()
def operation(workspace):
    return make_operation(workspace["id"])


@pytest.fixture()
def composition(workspace):
    return make_composition(workspace["id"])


@pytest.fixture()
def plan(workspace, operation, composition):
    return use_cases.attach_operation_plan(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        albion_composition_id=composition["id"],
    )


@pytest.fixture()
def slots(workspace, operation, plan):
    generated = use_cases.generate_operation_slots(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
    )
    publish_operation(workspace["id"], operation["id"])
    return generated


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_workspace_persists(workspace):
    with database.transaction() as db:
        row = repositories.get_workspace_by_id(db, workspace["id"])
    assert row is not None
    assert row["slug"] == "orbie"
    assert row["primary_game"] == "albion"


def test_create_operation_belongs_to_workspace(workspace):
    op = make_operation(workspace["id"])
    with database.transaction() as db:
        row = repositories.get_guild_operation(db, op["id"], workspace["id"])
    assert row is not None
    assert row["title"] == "Saturday ZvZ"
    assert row["status"] == "draft"
    assert row["guild_workspace_id"] == workspace["id"]


def test_composition_has_five_slot_templates(workspace, composition):
    with database.transaction() as db:
        templates = repositories.get_composition_slot_templates(
            db, composition["id"], workspace["id"]
        )
    assert len(templates) == 5
    roles = [t["role"] for t in templates]
    assert "Tank" in roles
    assert "Healer" in roles


def test_attach_plan_links_operation_and_composition(workspace, operation, composition, plan):
    with database.transaction() as db:
        row = repositories.get_operation_plan(db, operation["id"], workspace["id"])
    assert row is not None
    assert row["albion_composition_id"] == composition["id"]
    assert row["signup_status"] == "open"


def test_generate_slots_produces_frozen_snapshot(workspace, operation, slots):
    assert len(slots) == 5
    with database.transaction() as db:
        db_slots = repositories.get_operation_slots(db, operation["id"], workspace["id"])
    assert len(db_slots) == 5
    # Slots are ordered by party_number, slot_index
    assert db_slots[0]["party_number"] == 1
    assert db_slots[0]["slot_index"] == 1
    # source link is recorded for audit
    assert db_slots[0]["source_composition_slot_template_id"] is not None


def test_operation_slots_have_no_status_column(workspace, operation, slots):
    """operation_slots must not carry a status column in this slice."""
    with database.transaction() as db:
        db_slots = repositories.get_operation_slots(db, operation["id"], workspace["id"])
    assert len(db_slots) > 0
    assert "status" not in db_slots[0], (
        "operation_slots must not have a status column — "
        "assignment state lives in the assignments table"
    )


def test_all_slots_open_before_any_assignment(workspace, operation, slots):
    with database.transaction() as db:
        assigned_ids = repositories.get_assigned_slot_ids(db, operation["id"], workspace["id"])
    assert len(assigned_ids) == 0, "No slots should be assigned before any assignment"


def test_submit_signup_creates_participant_and_intent(workspace, operation, slots):
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="Emiel",
        preferred_role="Healer",
        preferred_build_name="Hallowfall",
    )
    assert signup["preferred_role"] == "Healer"
    with database.transaction() as db:
        intents = repositories.get_signup_intents(db, operation["id"], workspace["id"])
    assert len(intents) == 1
    assert intents[0]["preferred_role"] == "Healer"


def test_assign_participant_inserts_assignment_row(workspace, operation, slots):
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="Emiel",
        preferred_role="Healer",
    )
    healer_slot = next(s for s in slots if s["role"] == "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        operation_slot_id=healer_slot["id"],
        participant_id=signup["participant_id"],
    )
    assert assignment["assigned_role"] == "Healer"
    assert assignment["assigned_build_name"] == "Hallowfall"
    assert assignment["status"] == "assigned"


def test_assigned_role_comes_from_frozen_slot_not_signup(workspace, operation, slots):
    """
    The participant signed up preferring 'DPS' but is assigned to the Healer slot.
    assigned_role must reflect the slot (frozen truth), not the preference.
    """
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="Emiel",
        preferred_role="DPS",
    )
    healer_slot = next(s for s in slots if s["role"] == "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        operation_slot_id=healer_slot["id"],
        participant_id=signup["participant_id"],
    )
    assert assignment["assigned_role"] == "Healer"  # slot, not preferred
    assert assignment["assigned_build_name"] == "Hallowfall"  # slot's build


def test_slot_is_open_via_assignments_table(workspace, operation, slots):
    """
    A slot is considered open only when there is no active assignment row.
    Verify that after assignment, get_active_assignment_for_slot returns a row.
    """
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="Emiel",
        preferred_role="Tank",
    )
    tank_slot = next(s for s in slots if s["role"] == "Tank")

    with database.transaction() as db:
        before = repositories.get_active_assignment_for_slot(db, tank_slot["id"])
    assert before is None, "Slot should be open before assignment"

    use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        operation_slot_id=tank_slot["id"],
        participant_id=signup["participant_id"],
    )

    with database.transaction() as db:
        after = repositories.get_active_assignment_for_slot(db, tank_slot["id"])
    assert after is not None, "Slot should be assigned after assignment"


def test_readiness_snapshot_reflects_assignment_state(workspace, operation, slots):
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="Emiel",
        preferred_role="Healer",
    )
    healer_slot = next(s for s in slots if s["role"] == "Healer")
    use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        operation_slot_id=healer_slot["id"],
        participant_id=signup["participant_id"],
    )

    snapshot = use_cases.calculate_readiness_snapshot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
    )

    assert snapshot["total_slots"] == 5
    assert snapshot["assigned_slots"] == 1
    assert snapshot["open_slots"] == 4
    assert snapshot["readiness_state"] == "not_ready"
    missing = json.loads(snapshot["missing_roles_json"])
    # missing_roles_json is now a dict of role → count.
    # The 5-slot comp has: Tank×1, Healer×1, DPS×2, Support×1.
    # Healer slot is assigned; the other 4 remain open.
    assert "Healer" not in missing
    assert missing == {"DPS": 2, "Support": 1, "Tank": 1}


def test_readiness_ready_when_all_slots_assigned(workspace, operation, slots):
    names = ["P1", "P2", "P3", "P4", "P5"]
    for slot, name in zip(slots, names):
        signup = use_cases.submit_signup_intent(
            guild_workspace_id=workspace["id"],
            guild_operation_id=operation["id"],
            display_name=name,
            preferred_role=slot["role"],
        )
        use_cases.assign_participant_to_operation_slot(
            guild_workspace_id=workspace["id"],
            guild_operation_id=operation["id"],
            operation_slot_id=slot["id"],
            participant_id=signup["participant_id"],
        )

    snapshot = use_cases.calculate_readiness_snapshot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
    )
    assert snapshot["readiness_state"] == "ready"
    assert snapshot["assigned_slots"] == 5
    assert snapshot["open_slots"] == 0
    assert json.loads(snapshot["missing_roles_json"]) == {}


def test_caller_can_assign_non_matching_participant_to_any_open_slot(workspace, operation, slots):
    """
    Caller override is first-class.
    A participant who signed up for 'Tank' may be assigned to a 'Healer' slot.
    The planner board must not block this — the caller decides the final placement.
    The assigned_role on the assignment must reflect the slot (frozen truth),
    not the signup preference.
    """
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="FlexPlayer",
        preferred_role="Tank",
        preferred_build_name="1H Mace",
    )
    healer_slot = next(s for s in slots if s["role"] == "Healer")

    assignment = use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        operation_slot_id=healer_slot["id"],
        participant_id=signup["participant_id"],
    )

    assert assignment["status"] == "assigned"
    assert assignment["assigned_role"] == "Healer"        # slot role, not "Tank"
    assert assignment["assigned_build_name"] == "Hallowfall"  # slot build, not "1H Mace"


def test_full_event_timeline_recorded(workspace, operation, composition, plan, slots):
    """Verify an event row exists for each major command executed in this test."""
    use_cases.submit_signup_intent(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        display_name="Emiel",
        preferred_role="Tank",
    )
    tank_slot = next(s for s in slots if s["role"] == "Tank")
    with database.transaction() as db:
        participant = repositories.find_or_create_participant(
            db, workspace["id"], "Emiel"
        )
    use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
        operation_slot_id=tank_slot["id"],
        participant_id=participant["id"],
    )
    use_cases.calculate_readiness_snapshot(
        guild_workspace_id=workspace["id"],
        guild_operation_id=operation["id"],
    )

    with database.transaction() as db:
        events = repositories.get_operational_events(db, workspace["id"])

    event_types = [e["event_type"] for e in events]
    assert "workspace.created" in event_types
    assert "albion_composition.created" in event_types
    assert "guild_operation.created" in event_types
    assert "operation_plan.attached" in event_types
    assert "operation_slots.generated" in event_types
    assert "signup_intent.submitted" in event_types
    assert "assignment.created" in event_types
    assert "readiness_snapshot.created" in event_types
