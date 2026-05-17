"""
GuildWorkspace boundary tests.

All cross-workspace access must be rejected.  The boundary is enforced at
the repository layer (guild_workspace_id in every WHERE clause) so the
errors surface as NotFoundError rather than explicit boundary violations —
intentionally: we do not reveal the existence of entities in other workspaces.
"""

import pytest

from app.application import use_cases
from app.errors import ConflictError, NotFoundError
from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


@pytest.fixture()
def ws_a():
    return make_workspace("Guild A", "guild-a")


@pytest.fixture()
def ws_b():
    return make_workspace("Guild B", "guild-b")


def test_duplicate_slug_raises_conflict():
    make_workspace("Orbie", "orbie")
    with pytest.raises(ConflictError, match="already exists"):
        make_workspace("Orbie 2", "orbie")


def test_operation_not_visible_across_workspaces(ws_a, ws_b):
    op_a = make_operation(ws_a["id"])
    with pytest.raises(NotFoundError):
        # Use ws_b's id when querying an operation that belongs to ws_a
        use_cases.attach_operation_plan(
            guild_workspace_id=ws_b["id"],
            guild_operation_id=op_a["id"],
            albion_composition_id="any",
        )


def test_composition_from_other_workspace_cannot_be_attached(ws_a, ws_b):
    op_a = make_operation(ws_a["id"])
    comp_b = make_composition(ws_b["id"])
    # Operation is ws_a's, composition is ws_b's
    with pytest.raises(NotFoundError):
        use_cases.attach_operation_plan(
            guild_workspace_id=ws_a["id"],
            guild_operation_id=op_a["id"],
            albion_composition_id=comp_b["id"],
        )


def test_cannot_generate_slots_for_other_workspace_operation(ws_a, ws_b):
    op_a = make_operation(ws_a["id"])
    with pytest.raises(NotFoundError):
        use_cases.generate_operation_slots(
            guild_workspace_id=ws_b["id"],
            guild_operation_id=op_a["id"],
        )


def test_cannot_submit_signup_for_other_workspace_operation(ws_a, ws_b):
    op_a = make_operation(ws_a["id"])
    with pytest.raises(NotFoundError):
        use_cases.submit_signup_intent(
            guild_workspace_id=ws_b["id"],
            guild_operation_id=op_a["id"],
            display_name="Spy",
            preferred_role="DPS",
        )


def test_cannot_assign_slot_from_other_workspace(ws_a, ws_b):
    """
    Set up a full operation in ws_a.  Attempt to assign using ws_b's
    workspace id — the slot query returns NotFound.
    """
    comp_a = make_composition(ws_a["id"])
    op_a = make_operation(ws_a["id"])
    use_cases.attach_operation_plan(
        guild_workspace_id=ws_a["id"],
        guild_operation_id=op_a["id"],
        albion_composition_id=comp_a["id"],
    )
    slots_a = use_cases.generate_operation_slots(
        guild_workspace_id=ws_a["id"],
        guild_operation_id=op_a["id"],
    )
    publish_operation(ws_a["id"], op_a["id"])
    signup_a = use_cases.submit_signup_intent(
        guild_workspace_id=ws_a["id"],
        guild_operation_id=op_a["id"],
        display_name="Emiel",
        preferred_role="Tank",
    )
    with pytest.raises(NotFoundError):
        use_cases.assign_participant_to_operation_slot(
            guild_workspace_id=ws_b["id"],  # wrong workspace
            guild_operation_id=op_a["id"],
            operation_slot_id=slots_a[0]["id"],
            participant_id=signup_a["participant_id"],
        )


def test_cannot_calculate_readiness_for_other_workspace(ws_a, ws_b):
    op_a = make_operation(ws_a["id"])
    with pytest.raises(NotFoundError):
        use_cases.calculate_readiness_snapshot(
            guild_workspace_id=ws_b["id"],
            guild_operation_id=op_a["id"],
        )


def test_operational_events_are_workspace_isolated(ws_a, ws_b):
    """Events from ws_a are not returned when querying ws_b."""
    from app import database, repositories

    make_operation(ws_a["id"], title="Op A")
    make_operation(ws_b["id"], title="Op B")

    with database.transaction() as db:
        events_a = repositories.get_operational_events(db, ws_a["id"])
        events_b = repositories.get_operational_events(db, ws_b["id"])

    ws_a_ids = {e["guild_workspace_id"] for e in events_a}
    ws_b_ids = {e["guild_workspace_id"] for e in events_b}

    assert ws_a_ids == {ws_a["id"]}
    assert ws_b_ids == {ws_b["id"]}
