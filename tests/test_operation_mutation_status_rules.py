"""
Status-aware operation mutation rules tests.
"""

from __future__ import annotations

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError

from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


def _draft_with_plan(ws_id: str):
    comp = make_composition(ws_id, name="MutationComp", slots=[
        {"party_number": 1, "slot_index": 1, "role": "Healer", "build_name": "Hallowfall", "priority": "core"}
    ])
    op = make_operation(ws_id)
    use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
    return op, comp


def _planning_with_slots(ws_id: str):
    op, _ = _draft_with_plan(ws_id)
    slots = use_cases.generate_operation_slots(ws_id, op["id"])
    publish_operation(ws_id, op["id"])
    return op, slots


def test_attach_plan_allowed_in_draft():
    ws = make_workspace()
    op = make_operation(ws["id"])
    comp = make_composition(ws["id"])
    plan = use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    assert plan["guild_operation_id"] == op["id"]


def test_attach_plan_blocked_after_planning():
    ws = make_workspace()
    op, _ = _planning_with_slots(ws["id"])
    comp = make_composition(ws["id"], name="Second Comp")
    with pytest.raises(ConflictError, match="attach an operation plan"):
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])


def test_generate_slots_allowed_in_draft_and_planning():
    ws = make_workspace()
    op, _ = _draft_with_plan(ws["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    assert len(slots) == 1

    op2, _ = _draft_with_plan(ws["id"])
    use_cases.generate_operation_slots(ws["id"], op2["id"])
    publish_operation(ws["id"], op2["id"])
    with pytest.raises(ConflictError, match="already been generated"):
        use_cases.generate_operation_slots(ws["id"], op2["id"])


def test_generate_slots_blocked_when_locked():
    ws = make_workspace()
    op, _ = _planning_with_slots(ws["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    with pytest.raises(ConflictError, match="generate operation slots"):
        use_cases.generate_operation_slots(ws["id"], op["id"])


def test_assignment_blocked_in_draft():
    ws = make_workspace()
    op, _ = _draft_with_plan(ws["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    with database.transaction() as db:
        participant = repositories.find_or_create_participant(db, ws["id"], "PlayerOne")
    with pytest.raises(ConflictError, match="change assignments"):
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slots[0]["id"], participant["id"]
        )


def test_assignment_allowed_in_planning():
    ws = make_workspace()
    op, slots = _planning_with_slots(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    assert assignment["operation_slot_id"] == slots[0]["id"]


def test_assignment_blocked_when_locked():
    ws = make_workspace()
    op, slots = _planning_with_slots(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    use_cases.lock_operation(ws["id"], op["id"])
    with pytest.raises(ConflictError, match="change assignments"):
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
        )


def test_unassign_blocked_when_locked():
    ws = make_workspace()
    op, slots = _planning_with_slots(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws["id"], op["id"])
    with pytest.raises(ConflictError, match="change assignments"):
        use_cases.remove_assignment(ws["id"], op["id"], assignment["id"])


def test_reserve_blocked_in_completed():
    ws = make_workspace()
    op, slots = _planning_with_slots(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "BenchPlayer", "Healer")
    use_cases.complete_operation(ws["id"], op["id"])
    with pytest.raises(ConflictError, match="change reserve participants"):
        use_cases.mark_participant_as_reserve(
            ws["id"], op["id"], signup["participant_id"]
        )


def test_attendance_allowed_in_locked_and_completed():
    ws = make_workspace()
    op, slots = _planning_with_slots(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "present")
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "late")


def test_attendance_blocked_in_planning():
    ws = make_workspace()
    op, slots = _planning_with_slots(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    with pytest.raises(ConflictError, match="record attendance"):
        use_cases.record_attendance(ws["id"], op["id"], assignment["id"], "present")


def test_scout_attendance_blocked_in_draft_and_archived():
    ws = make_workspace()
    op = make_operation(ws["id"])
    with pytest.raises(ConflictError, match="record scout or support attendance"):
        use_cases.record_scout_attendance(ws["id"], op["id"], "ScoutOne", "scout")

    op2, _ = _planning_with_slots(ws["id"])
    use_cases.complete_operation(ws["id"], op2["id"])
    use_cases.archive_operation(ws["id"], op2["id"])
    with pytest.raises(ConflictError, match="record scout or support attendance"):
        use_cases.record_scout_attendance(ws["id"], op2["id"], "ScoutOne", "scout")


def test_readiness_blocked_without_slots():
    ws = make_workspace()
    op = make_operation(ws["id"])
    with pytest.raises(ConflictError, match="before operation slots have been generated"):
        use_cases.calculate_readiness_snapshot(ws["id"], op["id"])


def test_readiness_blocked_when_archived():
    ws = make_workspace()
    op, _ = _planning_with_slots(ws["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])
    with pytest.raises(ConflictError, match="recalculate readiness"):
        use_cases.calculate_readiness_snapshot(ws["id"], op["id"])


def test_archived_blocks_assignment_but_keeps_existing_signups():
    ws = make_workspace()
    op, _ = _planning_with_slots(ws["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    with database.transaction() as db:
        signups = repositories.get_signups_with_display_names(db, op["id"], ws["id"])
    assert len(signups) == 1
