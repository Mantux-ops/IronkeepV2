"""
Super-admin ("god-mode") portal test suite.

Feature: a Discord account on the IRONKEEP_SUPERADMIN_DISCORD_IDS allowlist gets
a cross-tenant admin portal (/admin) to list, soft-delete, restore, permanently
delete, rename, and transfer ownership of any workspace, plus owner-level
"god-mode" access to any individual workspace.  Every action is audited.

Test groups:
  1. Identity: superadmin.is_superadmin (env allowlist, discord-only)
  2. Soft delete / restore use cases + list hiding
  3. Hard delete (two-step guard + cascade across child tables)
  4. Rename / transfer ownership use cases
  5. Auth bypass: god-mode owner access + soft-delete hiding
  6. Routes: /admin access control, dashboard, and mutating actions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.auth import superadmin
from app.domain import users
from app.errors import ConflictError, NotFoundError, ValidationError
from app.main import app
from tests.conftest import make_user, make_workspace

_DISCORD_ADMIN_ID = "900000000000000001"
_DISCORD_OTHER_ID = "111111111111111111"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _link_discord_identity(user_id: str, discord_id: str) -> None:
    with database.transaction() as db:
        db.execute(
            """
            INSERT INTO user_auth_identities
                (id, user_id, auth_provider, provider_user_id, created_at)
            VALUES (?, ?, 'discord', ?, ?)
            """,
            (str(uuid.uuid4()), user_id, discord_id, _now_iso()),
        )


def _make_superadmin(monkeypatch, display_name="Support Admin",
                     discord_id=_DISCORD_ADMIN_ID) -> dict:
    """Create a user with an allowlisted Discord identity and enable the allowlist."""
    user = make_user(display_name=display_name)
    _link_discord_identity(user["id"], discord_id)
    monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", discord_id)
    return user


# ===========================================================================
# 1. Identity
# ===========================================================================

class TestIsSuperadmin:
    def test_no_allowlist_means_nobody(self, monkeypatch):
        monkeypatch.delenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", raising=False)
        user = use_cases.discord_oauth_login(_DISCORD_ADMIN_ID, "Admin")
        with database.transaction() as db:
            assert superadmin.is_superadmin(db, user) is False

    def test_allowlisted_discord_user_is_superadmin(self, monkeypatch):
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        user = use_cases.discord_oauth_login(_DISCORD_ADMIN_ID, "Admin")
        with database.transaction() as db:
            assert superadmin.is_superadmin(db, user) is True

    def test_discord_user_not_on_allowlist(self, monkeypatch):
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        user = use_cases.discord_oauth_login(_DISCORD_OTHER_ID, "Other")
        with database.transaction() as db:
            assert superadmin.is_superadmin(db, user) is False

    def test_dev_user_without_discord_never_superadmin(self, monkeypatch):
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        user = make_user(display_name="Plain Dev")
        with database.transaction() as db:
            assert superadmin.is_superadmin(db, user) is False

    def test_allowlist_supports_multiple_comma_separated(self, monkeypatch):
        monkeypatch.setenv(
            "IRONKEEP_SUPERADMIN_DISCORD_IDS",
            f" {_DISCORD_OTHER_ID}, {_DISCORD_ADMIN_ID} ",
        )
        user = use_cases.discord_oauth_login(_DISCORD_ADMIN_ID, "Admin")
        with database.transaction() as db:
            assert superadmin.is_superadmin(db, user) is True

    def test_none_user_is_not_superadmin(self, monkeypatch):
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        with database.transaction() as db:
            assert superadmin.is_superadmin(db, None) is False


# ===========================================================================
# 2. Soft delete / restore
# ===========================================================================

class TestSoftDeleteRestore:
    def test_soft_delete_hides_from_owner_list_and_audits(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        owner = make_user(display_name="Guild Owner")
        ws = make_workspace(name="Alpha", slug="alpha", owner_user_id=owner["id"])

        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )

        with database.transaction() as db:
            row = repositories.get_workspace_by_id(db, ws["id"])
            assert row["deleted_at"] is not None
            assert row["deleted_by"] == admin["id"]
            # Hidden from the owner's normal workspace list.
            visible = repositories.get_workspaces_for_user(db, owner["id"])
            assert all(w["id"] != ws["id"] for w in visible)
            # Audited.
            log = repositories.list_superadmin_audit_log(db)
            assert log[0]["action"] == "workspace.soft_delete"
            assert log[0]["target_workspace_id"] == ws["id"]
            assert log[0]["actor_discord_id"] == _DISCORD_ADMIN_ID

    def test_restore_makes_workspace_visible_again(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        owner = make_user(display_name="Guild Owner")
        ws = make_workspace(name="Beta", slug="beta", owner_user_id=owner["id"])

        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )
        use_cases.superadmin_restore_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )

        with database.transaction() as db:
            row = repositories.get_workspace_by_id(db, ws["id"])
            assert row["deleted_at"] is None
            visible = repositories.get_workspaces_for_user(db, owner["id"])
            assert any(w["id"] == ws["id"] for w in visible)

    def test_double_soft_delete_raises_conflict(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        ws = make_workspace(slug="gamma")
        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )
        with pytest.raises(ConflictError):
            use_cases.superadmin_soft_delete_workspace(
                actor_user_id=admin["id"], workspace_id=ws["id"]
            )

    def test_restore_non_deleted_raises_validation(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        ws = make_workspace(slug="delta")
        with pytest.raises(ValidationError):
            use_cases.superadmin_restore_workspace(
                actor_user_id=admin["id"], workspace_id=ws["id"]
            )

    def test_soft_delete_missing_workspace_raises_notfound(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        with pytest.raises(NotFoundError):
            use_cases.superadmin_soft_delete_workspace(
                actor_user_id=admin["id"], workspace_id="does-not-exist"
            )


# ===========================================================================
# 3. Hard delete
# ===========================================================================

class TestHardDelete:
    def test_hard_delete_requires_soft_delete_first(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        ws = make_workspace(slug="epsilon")
        with pytest.raises(ValidationError):
            use_cases.superadmin_hard_delete_workspace(
                actor_user_id=admin["id"], workspace_id=ws["id"]
            )

    def test_hard_delete_removes_workspace_and_child_rows(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        owner = make_user(display_name="Guild Owner")
        ws = make_workspace(name="Zeta", slug="zeta", owner_user_id=owner["id"])
        # Add a member and an operation so child tables have rows.
        member = make_user(display_name="Grunt")
        use_cases.add_workspace_member(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            display_name="Grunt",
        )
        op = use_cases.create_guild_operation(
            guild_workspace_id=ws["id"],
            title="Test Op",
            operation_type="zvz",
            scheduled_start_at="2026-08-01T20:00:00+00:00",
        )

        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )
        result = use_cases.superadmin_hard_delete_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )

        assert result["workspace_name"] == "Zeta"
        with database.transaction() as db:
            assert repositories.get_workspace_by_id(db, ws["id"]) is None
            assert repositories.list_workspace_members(db, ws["id"]) == []
            assert repositories.get_guild_operation(db, op["id"], ws["id"]) is None
            # Audit row survives the delete (no FK to guild_workspaces).
            log = repositories.list_superadmin_audit_log(db)
            actions = [row["action"] for row in log]
            assert "workspace.hard_delete" in actions

    def test_hard_delete_does_not_touch_other_workspaces(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        keep = make_workspace(name="Keep", slug="keep-ws")
        doomed = make_workspace(name="Doomed", slug="doomed-ws")

        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=admin["id"], workspace_id=doomed["id"]
        )
        use_cases.superadmin_hard_delete_workspace(
            actor_user_id=admin["id"], workspace_id=doomed["id"]
        )

        with database.transaction() as db:
            assert repositories.get_workspace_by_id(db, keep["id"]) is not None


# ===========================================================================
# 4. Rename / transfer ownership
# ===========================================================================

class TestRenameAndTransfer:
    def test_rename_updates_name_and_slug(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        ws = make_workspace(name="Old Name", slug="old-slug")

        use_cases.superadmin_rename_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"],
            name="New Name", slug="new-slug",
        )
        with database.transaction() as db:
            row = repositories.get_workspace_by_id(db, ws["id"])
            assert row["name"] == "New Name"
            assert row["slug"] == "new-slug"

    def test_rename_to_existing_slug_conflicts(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        make_workspace(name="First", slug="taken-slug")
        ws2 = make_workspace(name="Second", slug="free-slug")
        with pytest.raises(ConflictError):
            use_cases.superadmin_rename_workspace(
                actor_user_id=admin["id"], workspace_id=ws2["id"],
                name="Second", slug="taken-slug",
            )

    def test_transfer_ownership_promotes_and_demotes(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        owner = make_user(display_name="Old Owner")
        ws = make_workspace(name="Transfer WS", slug="transfer-ws",
                            owner_user_id=owner["id"])
        newbie = make_user(display_name="Rising Star")
        use_cases.add_workspace_member(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            display_name="Rising Star",
        )

        use_cases.superadmin_transfer_workspace_ownership(
            actor_user_id=admin["id"], workspace_id=ws["id"],
            new_owner_user_id=newbie["id"],
        )

        with database.transaction() as db:
            new_m = repositories.get_workspace_membership(db, ws["id"], newbie["id"])
            old_m = repositories.get_workspace_membership(db, ws["id"], owner["id"])
            assert new_m["role"] == "owner"
            assert old_m["role"] == "officer"

    def test_transfer_to_non_member_raises_validation(self, monkeypatch):
        admin = _make_superadmin(monkeypatch)
        ws = make_workspace(slug="transfer-fail")
        stranger = make_user(display_name="Stranger")
        with pytest.raises(ValidationError):
            use_cases.superadmin_transfer_workspace_ownership(
                actor_user_id=admin["id"], workspace_id=ws["id"],
                new_owner_user_id=stranger["id"],
            )


# ===========================================================================
# 5. Auth bypass (god-mode)
# ===========================================================================

class TestGodModeBypass:
    def test_superadmin_gets_owner_mutator_on_any_workspace(self, monkeypatch):
        from app import routes_auth
        admin = _make_superadmin(monkeypatch)
        ws = make_workspace(slug="bypass-ws")  # admin is NOT a member
        with database.transaction() as db:
            membership = routes_auth.require_workspace_mutator(
                db, admin["id"], ws["id"]
            )
        assert membership["role"] == "owner"
        assert membership["is_superadmin_synthetic"] is True

    def test_non_superadmin_non_member_is_denied(self, monkeypatch):
        from app import routes_auth
        from app.errors import IronkeepError
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        stranger = make_user(display_name="Nobody")
        ws = make_workspace(slug="bypass-ws2")
        with database.transaction() as db:
            with pytest.raises(IronkeepError):
                routes_auth.require_workspace_mutator(db, stranger["id"], ws["id"])


# ===========================================================================
# 6. Routes
# ===========================================================================

def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"},
                follow_redirects=False)


class TestAdminRoutes:
    def test_anonymous_admin_redirects_to_login(self, monkeypatch):
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        client = TestClient(app)
        resp = client.get("/admin", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "/login" in resp.headers["location"]

    def test_non_superadmin_gets_404(self, monkeypatch):
        monkeypatch.setenv("IRONKEEP_SUPERADMIN_DISCORD_IDS", _DISCORD_ADMIN_ID)
        client = TestClient(app)
        _login(client, "Regular User")
        resp = client.get("/admin", follow_redirects=False)
        assert resp.status_code == 404

    def test_superadmin_sees_dashboard(self, monkeypatch):
        _make_superadmin(monkeypatch, display_name="Portal Admin")
        make_workspace(name="Visible WS", slug="visible-ws")
        client = TestClient(app)
        _login(client, "Portal Admin")
        resp = client.get("/admin", follow_redirects=False)
        assert resp.status_code == 200
        assert "Visible WS" in resp.text

    def test_superadmin_can_soft_delete_via_route(self, monkeypatch):
        _make_superadmin(monkeypatch, display_name="Portal Admin")
        owner = make_user(display_name="WS Owner")
        ws = make_workspace(name="Deletable", slug="deletable-ws",
                            owner_user_id=owner["id"])
        client = TestClient(app)
        _login(client, "Portal Admin")
        resp = client.post(
            f"/admin/workspaces/{ws['id']}/soft-delete", follow_redirects=False
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            assert repositories.get_workspace_by_id(db, ws["id"])["deleted_at"] is not None

    def test_hard_delete_route_requires_matching_slug(self, monkeypatch):
        admin = _make_superadmin(monkeypatch, display_name="Portal Admin")
        ws = make_workspace(name="Confirm WS", slug="confirm-ws")
        use_cases.superadmin_soft_delete_workspace(
            actor_user_id=admin["id"], workspace_id=ws["id"]
        )
        client = TestClient(app)
        _login(client, "Portal Admin")
        # Wrong confirmation → workspace still present.
        resp = client.post(
            f"/admin/workspaces/{ws['id']}/hard-delete",
            data={"confirm_slug": "wrong"}, follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            assert repositories.get_workspace_by_id(db, ws["id"]) is not None
        # Correct confirmation → gone.
        resp = client.post(
            f"/admin/workspaces/{ws['id']}/hard-delete",
            data={"confirm_slug": "confirm-ws"}, follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            assert repositories.get_workspace_by_id(db, ws["id"]) is None

    def test_superadmin_god_mode_opens_foreign_workspace(self, monkeypatch):
        _make_superadmin(monkeypatch, display_name="Portal Admin")
        owner = make_user(display_name="WS Owner")
        ws = make_workspace(name="Foreign WS", slug="foreign-ws",
                            owner_user_id=owner["id"])
        client = TestClient(app)
        _login(client, "Portal Admin")  # admin is NOT a member of ws
        resp = client.get(f"/workspaces/{ws['slug']}", follow_redirects=False)
        assert resp.status_code == 200
