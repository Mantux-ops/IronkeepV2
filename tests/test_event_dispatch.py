"""
Post-commit OperationalEvent dispatch tests.

Covers:
1. Dispatch called after successful commit
2. Rollback prevents dispatch
3. Dispatcher exception does not propagate to caller
4. Dispatcher exception inserts discord_dispatch_failures row
5. Multiple events dispatched in emit order
6. Dispatcher receives exact event payload (matches DB row)
7. Non-dispatchable event types are skipped
8. Readonly transaction (no insert_operational_event) triggers no dispatch
"""

import uuid
from unittest.mock import patch

import pytest

from app import database, repositories
from app.application import use_cases
from app.domain import operational_events
from app.events import DISPATCHABLE_EVENT_TYPES
from tests.conftest import (
    make_composition,
    make_operation,
    make_workspace,
    publish_operation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DISPATCH_TARGET = "app.discord.dispatcher.dispatch"


def _raw_event(workspace_id: str, operation_id: str, event_type: str) -> dict:
    """Build a minimal OperationalEvent dict directly (no DB write)."""
    return operational_events.make_event(
        guild_workspace_id=workspace_id,
        guild_operation_id=operation_id,
        event_type=event_type,
        entity_type="guild_operation",
        entity_id=operation_id,
    )


# ---------------------------------------------------------------------------
# 1. Dispatch called after successful commit
# ---------------------------------------------------------------------------

def test_dispatch_called_after_successful_commit():
    ws = make_workspace()
    op = make_operation(ws["id"])
    with patch(_DISPATCH_TARGET) as mock_dispatch:
        publish_operation(ws["id"], op["id"])  # emits guild_operation.published

    mock_dispatch.assert_called_once()
    event_arg = mock_dispatch.call_args[0][0]
    assert event_arg["event_type"] == "guild_operation.published"
    assert event_arg["guild_workspace_id"] == ws["id"]


# ---------------------------------------------------------------------------
# 2. Rollback prevents dispatch
# ---------------------------------------------------------------------------

def test_rollback_prevents_dispatch():
    ws = make_workspace()
    op = make_operation(ws["id"])
    dispatched = []

    with pytest.raises(ValueError):
        with patch(_DISPATCH_TARGET, side_effect=lambda e: dispatched.append(e)):
            with database.transaction() as db:
                event = _raw_event(
                    ws["id"], op["id"], operational_events.GUILD_OPERATION_PUBLISHED
                )
                repositories.insert_operational_event(db, event)
                raise ValueError("forced rollback")

    assert dispatched == [], "dispatcher must not be called when transaction rolls back"

    # Verify the event was not persisted
    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], op["id"])
    published = [e for e in events if e["event_type"] == "guild_operation.published"]
    assert published == [], "rolled-back event must not appear in DB"


# ---------------------------------------------------------------------------
# 3. Dispatcher exception does not propagate to caller
# ---------------------------------------------------------------------------

def test_dispatcher_exception_does_not_propagate():
    ws = make_workspace()
    op = make_operation(ws["id"])

    with patch(_DISPATCH_TARGET, side_effect=RuntimeError("discord offline")):
        # Must not raise
        result = publish_operation(ws["id"], op["id"])

    assert result["status"] == "planning"


# ---------------------------------------------------------------------------
# 4. Dispatcher exception inserts discord_dispatch_failures row
# ---------------------------------------------------------------------------

def test_dispatcher_exception_inserts_failure_row():
    ws = make_workspace()
    op = make_operation(ws["id"])

    with patch(_DISPATCH_TARGET, side_effect=RuntimeError("discord offline")):
        publish_operation(ws["id"], op["id"])

    with database.transaction() as db:
        failures = repositories.get_pending_discord_dispatch_failures(db, ws["id"])

    assert len(failures) >= 1
    failure = next(f for f in failures if f["event_type"] == "guild_operation.published")
    assert failure["status"] == "pending_retry"
    assert "discord offline" in failure["error_message"]
    assert failure["guild_workspace_id"] == ws["id"]


# ---------------------------------------------------------------------------
# 5. Multiple events dispatched in emit order
# ---------------------------------------------------------------------------

def test_multiple_events_dispatched_in_emit_order():
    ws = make_workspace()
    op = make_operation(ws["id"])
    dispatched = []

    with patch(_DISPATCH_TARGET, side_effect=lambda e: dispatched.append(e)):
        with database.transaction() as db:
            event1 = _raw_event(
                ws["id"], op["id"], operational_events.GUILD_OPERATION_PUBLISHED
            )
            event2 = _raw_event(
                ws["id"], op["id"], operational_events.READINESS_SNAPSHOT_CREATED
            )
            repositories.insert_operational_event(db, event1)
            repositories.insert_operational_event(db, event2)

    assert len(dispatched) == 2
    assert dispatched[0]["id"] == event1["id"]
    assert dispatched[1]["id"] == event2["id"]


# ---------------------------------------------------------------------------
# 6. Dispatcher receives exact event payload (matches DB row)
# ---------------------------------------------------------------------------

def test_dispatcher_receives_exact_event_payload():
    ws = make_workspace()
    op = make_operation(ws["id"])
    captured = []

    with patch(_DISPATCH_TARGET, side_effect=lambda e: captured.append(e)):
        publish_operation(ws["id"], op["id"])

    assert len(captured) == 1
    dispatched = captured[0]

    with database.transaction() as db:
        db_events = repositories.get_operational_events(db, ws["id"], op["id"])
    db_event = next(
        e for e in db_events if e["event_type"] == "guild_operation.published"
    )

    assert dispatched["id"] == db_event["id"]
    assert dispatched["guild_workspace_id"] == db_event["guild_workspace_id"]
    assert dispatched["guild_operation_id"] == db_event["guild_operation_id"]
    assert dispatched["event_type"] == db_event["event_type"]
    assert dispatched["occurred_at"] == db_event["occurred_at"]


# ---------------------------------------------------------------------------
# 7. Non-dispatchable event types are silently skipped
# ---------------------------------------------------------------------------

def test_non_dispatchable_event_type_is_skipped():
    """operation_slots.generated is not in DISPATCHABLE_EVENT_TYPES."""
    assert "operation_slots.generated" not in DISPATCHABLE_EVENT_TYPES

    ws = make_workspace()
    op = make_operation(ws["id"])
    comp = make_composition(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])

    with patch(_DISPATCH_TARGET) as mock_dispatch:
        use_cases.generate_operation_slots(ws["id"], op["id"])

    mock_dispatch.assert_not_called()


def test_non_dispatchable_event_skipped_directly():
    """Direct test of app.events.dispatch_event allowlist."""
    from app import events as app_events

    not_dispatchable_types = [
        "assignment.created",
        "assignment.removed",
        "reserve.created",
        "reserve.removed",
        "operation_slots.generated",
        "operation_plan.attached",
        "guild_operation.created",
        "guild_operation.archived",
        "albion_composition.created",
    ]
    for event_type in not_dispatchable_types:
        with patch(_DISPATCH_TARGET) as mock_dispatch:
            app_events.dispatch_event(
                {"event_type": event_type, "id": str(uuid.uuid4())}
            )
        mock_dispatch.assert_not_called(), f"{event_type} should be skipped"


# ---------------------------------------------------------------------------
# 8. Readonly transaction triggers no dispatch
# ---------------------------------------------------------------------------

def test_readonly_transaction_triggers_no_dispatch():
    ws = make_workspace()

    with patch(_DISPATCH_TARGET) as mock_dispatch:
        with database.transaction() as db:
            repositories.get_workspace_by_id(db, ws["id"])

    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Allowlist completeness
# ---------------------------------------------------------------------------

def test_dispatchable_event_types_are_all_defined_constants():
    """Every type in DISPATCHABLE_EVENT_TYPES must be a known constant."""
    all_constants = {
        operational_events.WORKSPACE_CREATED,
        operational_events.ALBION_COMPOSITION_CREATED,
        operational_events.GUILD_OPERATION_CREATED,
        operational_events.GUILD_OPERATION_PUBLISHED,
        operational_events.GUILD_OPERATION_LOCKED,
        operational_events.GUILD_OPERATION_COMPLETED,
        operational_events.GUILD_OPERATION_ARCHIVED,
        operational_events.OPERATION_PLAN_ATTACHED,
        operational_events.OPERATION_SLOTS_GENERATED,
        operational_events.SIGNUP_INTENT_SUBMITTED,
        operational_events.ASSIGNMENT_CREATED,
        operational_events.ASSIGNMENT_REMOVED,
        operational_events.RESERVE_CREATED,
        operational_events.RESERVE_REMOVED,
        operational_events.READINESS_SNAPSHOT_CREATED,
        operational_events.ATTENDANCE_RECORDED,
        operational_events.SCOUT_ATTENDANCE_RECORDED,
        operational_events.SUPPORT_ATTENDANCE_RECORDED,
    }
    for event_type in DISPATCHABLE_EVENT_TYPES:
        assert event_type in all_constants, (
            f"'{event_type}' in DISPATCHABLE_EVENT_TYPES is not a known constant"
        )
