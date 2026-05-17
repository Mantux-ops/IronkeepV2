"""
GuildOperation status lifecycle tests.

Covers:
  1.  New operation starts as draft.
  2.  publish_operation transitions draft → planning.
  3.  lock_operation transitions planning → locked.
  4.  complete_operation transitions locked → completed.
  5.  complete_operation transitions planning → completed (small-ops fast-path).
  6.  archive_operation transitions completed → archived.
  7.  Invalid transition (e.g. draft → locked) raises ConflictError.
  8.  Each transition emits the correct OperationalEvent.
  9.  Workspace boundary check: cross-workspace transition raises NotFoundError.
  10. archived is a terminal state — any transition out raises ConflictError.
"""

from __future__ import annotations

import json

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError

from tests.conftest import make_workspace, make_operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latest_event(ws_id: str, op_id: str, event_type: str) -> dict | None:
    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws_id, op_id)
    matches = [e for e in events if e["event_type"] == event_type]
    if not matches:
        return None
    evt = dict(matches[-1])
    evt["payload"] = json.loads(evt.get("payload_json") or "{}")
    return evt


# ---------------------------------------------------------------------------
# 1. New operation starts as draft
# ---------------------------------------------------------------------------

def test_new_operation_starts_as_draft():
    ws = make_workspace()
    op = make_operation(ws["id"])
    assert op["status"] == "draft"


# ---------------------------------------------------------------------------
# 2. publish_operation: draft → planning
# ---------------------------------------------------------------------------

def test_publish_operation_draft_to_planning():
    ws = make_workspace()
    op = make_operation(ws["id"])
    updated = use_cases.publish_operation(ws["id"], op["id"])
    assert updated["status"] == "planning"
    with database.transaction() as db:
        fresh = repositories.get_guild_operation(db, op["id"], ws["id"])
    assert fresh["status"] == "planning"


# ---------------------------------------------------------------------------
# 3. lock_operation: planning → locked
# ---------------------------------------------------------------------------

def test_lock_operation_planning_to_locked():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    updated = use_cases.lock_operation(ws["id"], op["id"])
    assert updated["status"] == "locked"
    with database.transaction() as db:
        fresh = repositories.get_guild_operation(db, op["id"], ws["id"])
    assert fresh["status"] == "locked"


# ---------------------------------------------------------------------------
# 4. complete_operation: locked → completed
# ---------------------------------------------------------------------------

def test_complete_operation_locked_to_completed():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    updated = use_cases.complete_operation(ws["id"], op["id"])
    assert updated["status"] == "completed"
    with database.transaction() as db:
        fresh = repositories.get_guild_operation(db, op["id"], ws["id"])
    assert fresh["status"] == "completed"


# ---------------------------------------------------------------------------
# 5. complete_operation: planning → completed (fast-path)
# ---------------------------------------------------------------------------

def test_complete_operation_planning_fast_path():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    updated = use_cases.complete_operation(ws["id"], op["id"])
    assert updated["status"] == "completed"


# ---------------------------------------------------------------------------
# 6. archive_operation: completed → archived
# ---------------------------------------------------------------------------

def test_archive_operation_completed_to_archived():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    updated = use_cases.archive_operation(ws["id"], op["id"])
    assert updated["status"] == "archived"
    with database.transaction() as db:
        fresh = repositories.get_guild_operation(db, op["id"], ws["id"])
    assert fresh["status"] == "archived"


# ---------------------------------------------------------------------------
# 7. Invalid transition raises ConflictError
# ---------------------------------------------------------------------------

def test_invalid_transition_draft_to_locked_raises():
    ws = make_workspace()
    op = make_operation(ws["id"])
    with pytest.raises(ConflictError):
        use_cases.lock_operation(ws["id"], op["id"])


def test_invalid_transition_draft_to_completed_raises():
    ws = make_workspace()
    op = make_operation(ws["id"])
    with pytest.raises(ConflictError):
        use_cases.complete_operation(ws["id"], op["id"])


def test_invalid_transition_locked_to_planning_raises():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    with pytest.raises(ConflictError):
        use_cases.publish_operation(ws["id"], op["id"])


# ---------------------------------------------------------------------------
# 8. Each transition emits the correct OperationalEvent
# ---------------------------------------------------------------------------

def test_publish_emits_guild_operation_published_event():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    evt = _latest_event(ws["id"], op["id"], "guild_operation.published")
    assert evt is not None
    assert evt["payload"]["previous_status"] == "draft"
    assert evt["payload"]["new_status"] == "planning"


def test_lock_emits_guild_operation_locked_event():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    evt = _latest_event(ws["id"], op["id"], "guild_operation.locked")
    assert evt is not None
    assert evt["payload"]["previous_status"] == "planning"
    assert evt["payload"]["new_status"] == "locked"


def test_complete_emits_guild_operation_completed_event():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    evt = _latest_event(ws["id"], op["id"], "guild_operation.completed")
    assert evt is not None
    assert evt["payload"]["previous_status"] == "locked"
    assert evt["payload"]["new_status"] == "completed"


def test_archive_emits_guild_operation_archived_event():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])
    evt = _latest_event(ws["id"], op["id"], "guild_operation.archived")
    assert evt is not None
    assert evt["payload"]["previous_status"] == "completed"
    assert evt["payload"]["new_status"] == "archived"


# ---------------------------------------------------------------------------
# 9. Workspace boundary check
# ---------------------------------------------------------------------------

def test_transition_rejects_wrong_workspace():
    ws1 = make_workspace(name="Guild One", slug="guild-one")
    ws2 = make_workspace(name="Guild Two", slug="guild-two")
    op = make_operation(ws1["id"])
    with pytest.raises(NotFoundError):
        use_cases.publish_operation(ws2["id"], op["id"])


# ---------------------------------------------------------------------------
# 10. archived is terminal — all transitions out raise ConflictError
# ---------------------------------------------------------------------------

def test_archived_is_terminal_state():
    ws = make_workspace()
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.complete_operation(ws["id"], op["id"])
    use_cases.archive_operation(ws["id"], op["id"])

    for fn in (
        use_cases.publish_operation,
        use_cases.lock_operation,
        use_cases.complete_operation,
        use_cases.archive_operation,
    ):
        with pytest.raises(ConflictError):
            fn(ws["id"], op["id"])
