"""
OperationalEvent recording tests.

Every state-changing command must emit an event within its transaction.
Workspace-level events have guild_operation_id = NULL.
Operation-level events have guild_operation_id set.
All events must have guild_workspace_id set.
"""

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.domain import operational_events as ev
from app.errors import ValidationError
from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


@pytest.fixture()
def ws():
    return make_workspace()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_events(workspace_id, operation_id=None):
    with database.transaction() as db:
        return repositories.get_operational_events(db, workspace_id, operation_id)


def event_of_type(events, event_type):
    return next((e for e in events if e["event_type"] == event_type), None)


# ---------------------------------------------------------------------------
# workspace.created
# ---------------------------------------------------------------------------

def test_workspace_created_event_emitted(ws):
    events = get_events(ws["id"])
    e = event_of_type(events, ev.WORKSPACE_CREATED)
    assert e is not None
    assert e["guild_workspace_id"] == ws["id"]
    assert e["guild_operation_id"] is None  # workspace-level: no operation
    assert e["entity_type"] == "guild_workspace"
    assert e["entity_id"] == ws["id"]
    payload = json.loads(e["payload_json"])
    assert payload["slug"] == "orbie"


# ---------------------------------------------------------------------------
# albion_composition.created
# ---------------------------------------------------------------------------

def test_composition_created_event_is_workspace_level(ws):
    comp = make_composition(ws["id"])
    events = get_events(ws["id"])
    e = event_of_type(events, ev.ALBION_COMPOSITION_CREATED)
    assert e is not None
    assert e["guild_workspace_id"] == ws["id"]
    assert e["guild_operation_id"] is None  # workspace-level
    assert e["entity_id"] == comp["id"]
    payload = json.loads(e["payload_json"])
    assert payload["slot_count"] == 5


# ---------------------------------------------------------------------------
# guild_operation.created
# ---------------------------------------------------------------------------

def test_guild_operation_created_event_emitted(ws):
    op = make_operation(ws["id"])
    events = get_events(ws["id"], op["id"])
    e = event_of_type(events, ev.GUILD_OPERATION_CREATED)
    assert e is not None
    assert e["guild_workspace_id"] == ws["id"]
    assert e["guild_operation_id"] == op["id"]
    assert e["entity_id"] == op["id"]


# ---------------------------------------------------------------------------
# operation_plan.attached
# ---------------------------------------------------------------------------

def test_operation_plan_attached_event_emitted(ws):
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    plan = use_cases.attach_operation_plan(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        albion_composition_id=comp["id"],
    )
    events = get_events(ws["id"], op["id"])
    e = event_of_type(events, ev.OPERATION_PLAN_ATTACHED)
    assert e is not None
    assert e["guild_operation_id"] == op["id"]
    payload = json.loads(e["payload_json"])
    assert payload["albion_composition_id"] == comp["id"]


# ---------------------------------------------------------------------------
# operation_slots.generated
# ---------------------------------------------------------------------------

def test_slots_generated_event_has_slot_count(ws):
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        albion_composition_id=comp["id"],
    )
    use_cases.generate_operation_slots(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
    )
    events = get_events(ws["id"], op["id"])
    e = event_of_type(events, ev.OPERATION_SLOTS_GENERATED)
    assert e is not None
    payload = json.loads(e["payload_json"])
    assert payload["slot_count"] == 5


# ---------------------------------------------------------------------------
# signup_intent.submitted
# ---------------------------------------------------------------------------

def test_signup_submitted_event_emitted(ws):
    op = make_operation(ws["id"])
    publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        display_name="Emiel",
        preferred_role="Healer",
    )
    events = get_events(ws["id"], op["id"])
    e = event_of_type(events, ev.SIGNUP_INTENT_SUBMITTED)
    assert e is not None
    assert e["guild_operation_id"] == op["id"]
    payload = json.loads(e["payload_json"])
    assert payload["preferred_role"] == "Healer"
    assert "participant_id" in payload


# ---------------------------------------------------------------------------
# assignment.created
# ---------------------------------------------------------------------------

def test_assignment_created_event_emitted(ws):
    comp = make_composition(ws["id"], slots=[
        {"party_number": 1, "slot_index": 1, "role": "Healer", "build_name": "Hallowfall", "priority": "core"}
    ])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "Emiel", "Healer")
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )

    events = get_events(ws["id"], op["id"])
    e = event_of_type(events, ev.ASSIGNMENT_CREATED)
    assert e is not None
    assert e["guild_operation_id"] == op["id"]
    payload = json.loads(e["payload_json"])
    assert payload["assigned_role"] == "Healer"
    assert payload["assigned_build_name"] == "Hallowfall"
    assert payload["operation_slot_id"] == slots[0]["id"]


# ---------------------------------------------------------------------------
# readiness_snapshot.created
# ---------------------------------------------------------------------------

def test_readiness_snapshot_event_emitted(ws):
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    snapshot = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])
    events = get_events(ws["id"], op["id"])
    e = event_of_type(events, ev.READINESS_SNAPSHOT_CREATED)
    assert e is not None
    payload = json.loads(e["payload_json"])
    assert payload["readiness_state"] == snapshot["readiness_state"]
    assert "total_slots" in payload
    assert "assigned_slots" in payload


# ---------------------------------------------------------------------------
# Event invariants
# ---------------------------------------------------------------------------

def test_all_events_have_guild_workspace_id(ws):
    comp = make_composition(ws["id"])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "Emiel", "Healer")
    use_cases.calculate_readiness_snapshot(ws["id"], op["id"])

    events = get_events(ws["id"])
    assert len(events) > 0
    for e in events:
        assert e["guild_workspace_id"] == ws["id"], (
            f"Event {e['event_type']} is missing guild_workspace_id"
        )


def test_operation_level_event_requires_guild_operation_id():
    """make_event must raise for operation-level events without guild_operation_id."""
    with pytest.raises(ValidationError, match="operation-level"):
        ev.make_event(
            guild_workspace_id="ws-1",
            guild_operation_id=None,  # missing — should raise
            event_type=ev.ASSIGNMENT_CREATED,
            entity_type="assignment",
            entity_id="a-1",
        )


def test_workspace_level_event_allows_null_operation_id():
    """workspace.created and albion_composition.created allow null guild_operation_id."""
    e = ev.make_event(
        guild_workspace_id="ws-1",
        guild_operation_id=None,
        event_type=ev.WORKSPACE_CREATED,
        entity_type="guild_workspace",
        entity_id="ws-1",
    )
    assert e["guild_operation_id"] is None
    assert e["guild_workspace_id"] == "ws-1"
