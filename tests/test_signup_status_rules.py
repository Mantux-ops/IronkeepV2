"""
Status-aware signup rules tests.

Covers:
  1. Signup allowed when GuildOperation.status is planning.
  2. Signup blocked for draft, locked, completed, and archived.
  3. Plan-level signup_status=closed still blocks during planning.
  4. Existing signups remain readable after lock.
  5. Cross-workspace submit still raises NotFoundError.
"""

from __future__ import annotations

import pytest

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError

from tests.conftest import make_operation, make_workspace, publish_operation


def _planning_operation(ws_id: str):
    op = make_operation(ws_id)
    publish_operation(ws_id, op["id"])
    return op


def test_signup_allowed_when_operation_is_planning():
    ws = make_workspace()
    op = _planning_operation(ws["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    assert signup["preferred_role"] == "Healer"


@pytest.mark.parametrize("status", ["draft", "locked", "completed", "archived"])
def test_signup_blocked_outside_planning(status):
    ws = make_workspace()
    op = make_operation(ws["id"])
    if status == "planning":
        publish_operation(ws["id"], op["id"])
    elif status == "locked":
        publish_operation(ws["id"], op["id"])
        use_cases.lock_operation(ws["id"], op["id"])
    elif status == "completed":
        publish_operation(ws["id"], op["id"])
        use_cases.complete_operation(ws["id"], op["id"])
    elif status == "archived":
        publish_operation(ws["id"], op["id"])
        use_cases.complete_operation(ws["id"], op["id"])
        use_cases.archive_operation(ws["id"], op["id"])

    with pytest.raises(ConflictError):
        use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")


def test_plan_closed_still_blocks_signup_during_planning():
    ws = make_workspace()
    comp = use_cases.create_albion_composition(
        guild_workspace_id=ws["id"],
        name="Closed Signup Comp",
        description=None,
        slots=[
            {
                "party_number": 1,
                "slot_index": 1,
                "role": "Healer",
                "build_name": "Hallowfall",
                "priority": "core",
            }
        ],
    )
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(
        ws["id"],
        op["id"],
        comp["id"],
        signup_status="closed",
    )
    publish_operation(ws["id"], op["id"])

    with pytest.raises(ConflictError, match="Signups are closed for this operation."):
        use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")


def test_existing_signups_remain_visible_after_lock():
    ws = make_workspace()
    op = _planning_operation(ws["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "PlayerOne", "Healer")
    use_cases.lock_operation(ws["id"], op["id"])

    with database.transaction() as db:
        signups = repositories.get_signups_with_display_names(db, op["id"], ws["id"])

    assert len(signups) == 1
    assert signups[0]["display_name"] == "PlayerOne"


def test_cross_workspace_signup_submit_raises_not_found():
    ws1 = make_workspace(name="Guild One", slug="guild-one")
    ws2 = make_workspace(name="Guild Two", slug="guild-two")
    op = _planning_operation(ws1["id"])

    with pytest.raises(NotFoundError):
        use_cases.submit_signup_intent(ws2["id"], op["id"], "PlayerOne", "Healer")
