"""Add workspace member use case tests."""

from __future__ import annotations

import pytest

from app.application import use_cases
from app.errors import ConflictError, PermissionDenied
from tests.conftest import make_user, make_workspace


def test_officer_can_add_member():
    owner = make_user("Owner")
    ws = make_workspace(owner_user_id=owner["id"], slug="add-member")
    officer = make_user("Officer")
    use_cases.add_workspace_member(ws["id"], owner["id"], "Officer", role="officer")
    membership = use_cases.add_workspace_member(
        ws["id"], officer["id"], "Bench Player", role="member"
    )
    assert membership["role"] == "member"


def test_member_cannot_add_member():
    owner = make_user("Owner Two")
    ws = make_workspace(owner_user_id=owner["id"], slug="add-member-two")
    member = make_user("Member")
    use_cases.add_workspace_member(ws["id"], owner["id"], "Member", role="member")
    with pytest.raises(PermissionDenied):
        use_cases.add_workspace_member(
            ws["id"], member["id"], "Another Player", role="member"
        )


def test_duplicate_membership_rejected():
    owner = make_user("Owner Three")
    ws = make_workspace(owner_user_id=owner["id"], slug="add-member-three")
    use_cases.add_workspace_member(ws["id"], owner["id"], "Player", role="member")
    with pytest.raises(ConflictError):
        use_cases.add_workspace_member(ws["id"], owner["id"], "Player", role="member")
