"""
Scout / support attendance tests.

Key invariant (test 10): a scout check-in requires no signup and no assignment.
Scout records live in scout_attendance_records, never in attendance_records.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import NotFoundError, ValidationError

from tests.conftest import make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _planning_op(ws):
    op = make_operation(ws["id"])
    publish_operation(ws["id"], op["id"])
    return op


def _checkin(ws_id, op_id, name="Scout1", role_type="scout", notes=None):
    return use_cases.record_scout_attendance(
        guild_workspace_id=ws_id,
        guild_operation_id=op_id,
        display_name=name,
        role_type=role_type,
        notes=notes,
    )


def _scout_events(ws_id, op_id):
    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws_id, op_id)
    return [
        e for e in events
        if e["event_type"] in ("scout_attendance.recorded", "support_attendance.recorded")
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_record_scout_checkin_creates_record():
    ws = make_workspace()
    op = _planning_op(ws)

    record = _checkin(ws["id"], op["id"], name="Scout1", role_type="scout")

    assert record["id"] is not None
    assert record["guild_workspace_id"] == ws["id"]
    assert record["guild_operation_id"] == op["id"]
    assert record["role_type"] == "scout"
    assert record["participant_id"] is not None


def test_scout_role_type_stored_correctly():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], name="Helper1", role_type="support", notes="Ran logistics")

    with database.transaction() as db:
        rows = repositories.get_scout_attendance_records_for_operation(db, op["id"], ws["id"])

    assert len(rows) == 1
    assert rows[0]["role_type"] == "support"
    assert rows[0]["notes"] == "Ran logistics"
    assert rows[0]["display_name"] == "Helper1"


def test_scout_checkin_emits_scout_event():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], role_type="scout")

    events = _scout_events(ws["id"], op["id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "scout_attendance.recorded"

    payload = json.loads(events[0]["payload_json"])
    assert payload["role_type"] == "scout"
    assert "previous_role_type" not in payload


def test_support_checkin_emits_support_event():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], role_type="support")

    events = _scout_events(ws["id"], op["id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "support_attendance.recorded"

    payload = json.loads(events[0]["payload_json"])
    assert payload["role_type"] == "support"


def test_re_checkin_updates_not_inserts():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], name="Scout1", role_type="scout")
    _checkin(ws["id"], op["id"], name="Scout1", role_type="support")

    with database.transaction() as db:
        rows = repositories.get_scout_attendance_records_for_operation(db, op["id"], ws["id"])

    assert len(rows) == 1
    assert rows[0]["role_type"] == "support"


def test_re_checkin_event_includes_previous_role_type():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], name="Scout1", role_type="scout")
    _checkin(ws["id"], op["id"], name="Scout1", role_type="support")

    events = _scout_events(ws["id"], op["id"])
    assert len(events) == 2

    correction_payload = json.loads(events[1]["payload_json"])
    assert correction_payload["role_type"] == "support"
    assert correction_payload["previous_role_type"] == "scout"


def test_re_checkin_includes_previous_notes_when_notes_changed():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], name="Scout1", role_type="scout", notes="On the west flank")
    _checkin(ws["id"], op["id"], name="Scout1", role_type="scout", notes="Switched to east")

    events = _scout_events(ws["id"], op["id"])
    correction_payload = json.loads(events[1]["payload_json"])
    assert correction_payload["previous_notes"] == "On the west flank"


def test_re_checkin_omits_previous_notes_when_notes_unchanged():
    ws = make_workspace()
    op = _planning_op(ws)

    _checkin(ws["id"], op["id"], name="Scout1", role_type="scout", notes="Same note")
    _checkin(ws["id"], op["id"], name="Scout1", role_type="support", notes="Same note")

    events = _scout_events(ws["id"], op["id"])
    correction_payload = json.loads(events[1]["payload_json"])
    assert "previous_notes" not in correction_payload


def test_invalid_role_type_rejected():
    ws = make_workspace()
    op = _planning_op(ws)

    with pytest.raises(ValidationError, match="role_type"):
        use_cases.record_scout_attendance(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            display_name="Someone",
            role_type="sniper",
        )


def test_scout_checkin_is_guild_scoped():
    ws = make_workspace()
    op = _planning_op(ws)
    other_ws = make_workspace(name="Other Guild", slug="other")

    with pytest.raises(NotFoundError):
        use_cases.record_scout_attendance(
            guild_workspace_id=other_ws["id"],
            guild_operation_id=op["id"],
            display_name="Scout1",
            role_type="scout",
        )


def test_scout_checkin_creates_participant_if_not_found():
    """A brand-new display_name triggers participant creation."""
    ws = make_workspace()
    op = _planning_op(ws)

    record = _checkin(ws["id"], op["id"], name="BrandNewScout", role_type="scout")

    with database.transaction() as db:
        participant = db.execute(
            "SELECT * FROM participants WHERE id = ? AND guild_workspace_id = ?",
            (record["participant_id"], ws["id"]),
        ).fetchone()

    assert participant is not None
    assert participant["display_name"] == "BrandNewScout"


def test_scout_checkin_does_not_require_signup_or_assignment():
    """
    Core invariant: scout check-in must succeed even when the operation has
    zero signups and zero assignments.  No dependency on the assignment path.
    """
    ws = make_workspace()
    op = _planning_op(ws)
    # Deliberately skip: attach_plan, generate_slots, submit_signup_intent, assign

    record = _checkin(ws["id"], op["id"], name="PureScout", role_type="scout")

    assert record["role_type"] == "scout"

    with database.transaction() as db:
        rows = repositories.get_scout_attendance_records_for_operation(db, op["id"], ws["id"])
        # Verify scout record is NOT in attendance_records
        att_rows = repositories.get_attendance_records_for_operation(db, op["id"], ws["id"])

    assert len(rows) == 1
    assert len(att_rows) == 0
