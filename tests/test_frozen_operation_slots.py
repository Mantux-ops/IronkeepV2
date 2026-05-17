"""
Frozen OperationSlot invariant tests.

Core rule: editing a CompositionSlotTemplate after slots have been generated
must not change existing OperationSlot rows.  OperationSlot is the frozen
operational snapshot.

Tests also verify:
- Slots cannot be regenerated once created.
- Assigning the same slot twice raises ConflictError.
- The slot's build/role is copied from the template at generation time,
  not looked up dynamically.
"""

import sqlite3

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError
from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


@pytest.fixture()
def ws():
    return make_workspace()


@pytest.fixture()
def full_op(ws):
    """Returns (operation, slots) with a single-slot composition."""
    comp = use_cases.create_albion_composition(
        guild_workspace_id=ws["id"],
        name="Hallowfall Comp",
        description=None,
        slots=[
            {
                "party_number": 1,
                "slot_index": 1,
                "role": "Healer",
                "build_name": "Hallowfall",
                "weapon_name": "Hallowfall",
                "priority": "core",
            }
        ],
    )
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        albion_composition_id=comp["id"],
    )
    slots = use_cases.generate_operation_slots(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
    )
    publish_operation(ws["id"], op["id"])
    return op, slots, comp


def test_operation_slot_has_no_status_column(ws, full_op):
    op, slots, _ = full_op
    with database.transaction() as db:
        db_slots = repositories.get_operation_slots(db, op["id"], ws["id"])
    assert "status" not in db_slots[0]


def test_editing_template_does_not_change_existing_slot(ws, full_op):
    """
    Directly update the composition_slot_templates row (simulating a future
    edit-composition feature) and assert the operation slot is unchanged.
    """
    op, slots, comp = full_op
    original_build = slots[0]["build_name"]
    assert original_build == "Hallowfall"

    # Simulate an out-of-band edit to the template (no use case exists yet)
    raw_conn = sqlite3.connect(database._DB_PATH)
    raw_conn.execute(
        "UPDATE composition_slot_templates SET build_name = 'Great Holy' WHERE albion_composition_id = ?",
        (comp["id"],),
    )
    raw_conn.commit()
    raw_conn.close()

    # OperationSlot must still say Hallowfall
    with database.transaction() as db:
        db_slots = repositories.get_operation_slots(db, op["id"], ws["id"])

    assert db_slots[0]["build_name"] == "Hallowfall", (
        "OperationSlot must not reflect template edits — it is a frozen snapshot."
    )


def test_cannot_regenerate_slots(ws, full_op):
    op, _, _ = full_op
    with pytest.raises(ConflictError, match="already been generated"):
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )


def test_cannot_generate_slots_without_plan(ws):
    op = make_operation(ws["id"])
    with pytest.raises(Exception):  # NotFoundError
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )


def test_cannot_assign_same_slot_twice(ws, full_op):
    op, slots, _ = full_op
    slot = slots[0]

    signup1 = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="Alpha",
        preferred_role="Healer",
    )
    signup2 = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="Beta",
        preferred_role="Healer",
    )

    use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        operation_slot_id=slot["id"],
        participant_id=signup1["participant_id"],
    )

    with pytest.raises(ConflictError, match="already has an active assignment"):
        use_cases.assign_participant_to_operation_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            operation_slot_id=slot["id"],
            participant_id=signup2["participant_id"],
        )


def test_slot_open_check_uses_assignments_table_not_status_column(ws, full_op):
    """
    Verify that the open/assigned distinction is entirely based on the
    assignments table — there is no status column on operation_slots.
    """
    op, slots, _ = full_op
    slot = slots[0]

    with database.transaction() as db:
        active = repositories.get_active_assignment_for_slot(db, slot["id"])
    assert active is None, "Slot should be open (no assignments row)"

    signup = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="Gamma",
        preferred_role="Healer",
    )
    use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        operation_slot_id=slot["id"],
        participant_id=signup["participant_id"],
    )

    with database.transaction() as db:
        active = repositories.get_active_assignment_for_slot(db, slot["id"])
    assert active is not None, "Slot should be assigned (assignments row exists)"
    assert active["status"] == "assigned"


def test_source_template_id_is_recorded_for_audit(ws, full_op):
    """
    Each operation slot must record which template it was cloned from.
    This is an audit link — it does not create a live dependency.
    """
    op, slots, _ = full_op
    assert slots[0]["source_composition_slot_template_id"] is not None
