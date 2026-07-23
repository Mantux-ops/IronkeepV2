"""
Workspace member role management (promote/demote) test suite.

Feature: an owner (or platform super-admin via god-mode) can promote a member
to officer or demote an officer to member from the members page. Officers and
members cannot change roles. This is how Discord auto-joined members (who land
as 'member') get build/operation permissions.

Test groups:
  1. Use case: set_workspace_member_role (happy path + all guard rails)
  2. Use case: super-admin bypass
  3. Route: POST /members/{id}/role
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import NotFoundError, PermissionDenied, ValidationError
from app.main import app
from tests.conftest import make_user, make_workspace


def _member_role(ws_id: str, user_id: str) -> str | None:
    with database.transaction() as db:
        m = repositories.get_workspace_membership(db, ws_id, user_id)
    return m["role"] if m else None


# ---------------------------------------------------------------------------
# 1. Use case
# ---------------------------------------------------------------------------

class TestSetMemberRole:

    def test_owner_promotes_member_to_officer(self):
        owner = make_user("Owner MR1")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-1")
        member = use_cases.add_workspace_member(ws["id"], owner["id"], "Recruit One", "member")

        result = use_cases.set_workspace_member_role(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            target_user_id=member["user_id"], new_role="officer",
        )
        assert result["old_role"] == "member"
        assert result["new_role"] == "officer"
        assert _member_role(ws["id"], member["user_id"]) == "officer"

    def test_owner_demotes_officer_to_member(self):
        owner = make_user("Owner MR2")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-2")
        officer = use_cases.add_workspace_member(ws["id"], owner["id"], "Off Two", "officer")

        use_cases.set_workspace_member_role(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            target_user_id=officer["user_id"], new_role="member",
        )
        assert _member_role(ws["id"], officer["user_id"]) == "member"

    def test_officer_cannot_change_roles(self):
        owner = make_user("Owner MR3")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-3")
        officer = use_cases.add_workspace_member(ws["id"], owner["id"], "Off Three", "officer")
        member = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem Three", "member")

        with pytest.raises(PermissionDenied):
            use_cases.set_workspace_member_role(
                guild_workspace_id=ws["id"], actor_user_id=officer["user_id"],
                target_user_id=member["user_id"], new_role="officer",
            )

    def test_member_cannot_change_roles(self):
        owner = make_user("Owner MR4")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-4")
        m1 = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem A", "member")
        m2 = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem B", "member")

        with pytest.raises(PermissionDenied):
            use_cases.set_workspace_member_role(
                guild_workspace_id=ws["id"], actor_user_id=m1["user_id"],
                target_user_id=m2["user_id"], new_role="officer",
            )

    def test_cannot_change_own_role(self):
        owner = make_user("Owner MR5")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-5")
        with pytest.raises(PermissionDenied):
            use_cases.set_workspace_member_role(
                guild_workspace_id=ws["id"], actor_user_id=owner["id"],
                target_user_id=owner["id"], new_role="officer",
            )

    def test_cannot_change_owner_role(self):
        owner = make_user("Owner MR6")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-6")
        # A second owner (rare, but role changes must never touch owners).
        other_owner = use_cases.add_workspace_member(ws["id"], owner["id"], "Owner Two", "owner")
        with pytest.raises(PermissionDenied):
            use_cases.set_workspace_member_role(
                guild_workspace_id=ws["id"], actor_user_id=owner["id"],
                target_user_id=other_owner["user_id"], new_role="member",
            )

    def test_invalid_role_rejected(self):
        owner = make_user("Owner MR7")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-7")
        member = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem Seven", "member")
        with pytest.raises(ValidationError):
            use_cases.set_workspace_member_role(
                guild_workspace_id=ws["id"], actor_user_id=owner["id"],
                target_user_id=member["user_id"], new_role="admin",
            )

    def test_target_not_a_member_raises(self):
        owner = make_user("Owner MR8")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-8")
        stranger = make_user("Stranger Eight")
        with pytest.raises(NotFoundError):
            use_cases.set_workspace_member_role(
                guild_workspace_id=ws["id"], actor_user_id=owner["id"],
                target_user_id=stranger["id"], new_role="officer",
            )

    def test_emits_role_changed_event(self):
        owner = make_user("Owner MR9")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-9")
        member = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem Nine", "member")
        use_cases.set_workspace_member_role(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            target_user_id=member["user_id"], new_role="officer",
        )
        with database.transaction() as db:
            rows = db.execute(
                "SELECT event_type FROM operational_events WHERE guild_workspace_id = ?",
                (ws["id"],),
            ).fetchall()
        assert any(r[0] == "workspace.member.role_changed" for r in rows)

    def test_idempotent_same_role_no_event(self):
        owner = make_user("Owner MR10")
        ws = make_workspace(owner_user_id=owner["id"], slug="mr-10")
        member = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem Ten", "member")
        result = use_cases.set_workspace_member_role(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            target_user_id=member["user_id"], new_role="member",
        )
        assert result["new_role"] == "member"
        with database.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM operational_events "
                "WHERE guild_workspace_id = ? AND event_type = 'workspace.member.role_changed'",
                (ws["id"],),
            ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# 2. Super-admin bypass
# ---------------------------------------------------------------------------

def test_superadmin_can_change_roles_without_membership():
    # A super-admin (Discord allowlist) may manage roles in any workspace even
    # without being a member.
    owner = make_user("Owner SA")
    ws = make_workspace(owner_user_id=owner["id"], slug="mr-sa")
    member = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem SA", "member")

    admin = use_cases.discord_oauth_login("superadmin-disc-1", "PlatformAdmin")

    with patch.dict(os.environ, {"IRONKEEP_SUPERADMIN_DISCORD_IDS": "superadmin-disc-1"}):
        use_cases.set_workspace_member_role(
            guild_workspace_id=ws["id"], actor_user_id=admin["id"],
            target_user_id=member["user_id"], new_role="officer",
        )
    assert _member_role(ws["id"], member["user_id"]) == "officer"


# ---------------------------------------------------------------------------
# 3. Route
# ---------------------------------------------------------------------------

def test_route_owner_promotes_member():
    owner = make_user("Owner RT")
    ws = make_workspace(owner_user_id=owner["id"], slug="mr-rt")
    member = use_cases.add_workspace_member(ws["id"], owner["id"], "Mem RT", "member")

    client = TestClient(app, follow_redirects=False)
    with patch.dict(os.environ, {"IRONKEEP_ENV": "dev"}):
        client.post("/login", data={"display_name": "Owner RT", "next": "/"})
        resp = client.post(
            f"/workspaces/{ws['slug']}/members/{member['user_id']}/role",
            data={"role": "officer"},
        )
    assert resp.status_code == 303
    assert _member_role(ws["id"], member["user_id"]) == "officer"
