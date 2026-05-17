"""
Tests for Discord message-component check-in interactions.

Covers adapter.handle_component_interaction:
- Scout button success → attendance row written, ephemeral success response
- Support button success → attendance row written, ephemeral success response
- Attendance row written and correct role_type stored
- Invalid custom_id (wrong prefix, wrong segment count) → ephemeral error
- Invalid role_type (e.g. "dps") → ephemeral error
- Guild not linked → ephemeral error (DiscordNotLinkedError)
- User not linked → ephemeral error (DiscordUserNotLinkedError)
- Non-member user → ephemeral error (DiscordUserNotWorkspaceMemberError)
- Operation not found → ephemeral error
- All success responses are type=4 and ephemeral
- All error responses are type=4 and ephemeral
- No assignment rows changed
- No planner state mutated

Formatter component tests (also covered in test_discord_formatters.py for shape;
here we just verify JSON serialisability of full payloads with components).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import database, repositories
from app.application import use_cases
from app.discord import adapter
from app.discord.identity import (
    DiscordNotLinkedError,
    DiscordUserNotLinkedError,
    DiscordUserNotWorkspaceMemberError,
)
from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
)


def _add_discord_member(ws_id: str, discord_user_id_row: str, role: str = "member") -> None:
    """Insert a workspace membership for a user whose ID is already in the DB."""
    with database.transaction() as db:
        repositories.insert_workspace_member(db, {
            "id":                 str(uuid.uuid4()),
            "guild_workspace_id": ws_id,
            "user_id":            discord_user_id_row,
            "role":               role,
            "created_at":         _now(),
        })


_GUILD_ID        = "111122223333444455"
_CHANNEL_ID      = "555566667777888899"
_DISCORD_USER_ID = "111222333444555666"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_discord_user(display_name: str, discord_user_id: str) -> dict:
    """Insert a user whose auth_provider is 'discord'."""
    user = {
        "id":               str(uuid.uuid4()),
        "display_name":     display_name,
        "auth_provider":    "discord",
        "provider_user_id": discord_user_id,
        "created_at":       _now(),
        "updated_at":       _now(),
    }
    with database.transaction() as db:
        repositories.insert_user(db, user)
    return user


def _configure_discord(ws_id: str, actor_id: str) -> None:
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_id,
        actor_id=actor_id,
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=_CHANNEL_ID,
        officer_channel_id=None,
    )


def _setup_linked_member(slug_suffix: str) -> tuple[dict, dict, dict, dict]:
    """
    Full happy-path fixture:
      workspace linked to _GUILD_ID
      discord_user linked to workspace as member
      published operation
    Returns (owner, ws, discord_user_row, op)
    """
    owner = make_user(f"Owner-{slug_suffix}")
    ws    = make_workspace(slug=f"ws-{slug_suffix}", owner_user_id=owner["id"])

    _configure_discord(ws["id"], owner["id"])

    discord_user = _make_discord_user(f"Adventurer-{slug_suffix}", _DISCORD_USER_ID)
    _add_discord_member(ws["id"], discord_user["id"])

    op = make_operation(ws["id"], title="Saturday ZvZ")
    use_cases.publish_operation(ws["id"], op["id"])

    return owner, ws, discord_user, op


def _payload(op_id: str, role_type: str = "scout", custom_id: str | None = None) -> dict:
    if custom_id is None:
        custom_id = f"checkin:{role_type}:{op_id}"
    return {
        "discord_guild_id": _GUILD_ID,
        "discord_user_id":  _DISCORD_USER_ID,
        "custom_id":        custom_id,
    }


def _call(payload: dict) -> dict:
    with database.transaction() as db:
        return adapter.handle_component_interaction(payload, db)


def _is_ephemeral(response: dict) -> bool:
    return bool(response.get("data", {}).get("flags", 0) & 64)


def _scout_records(ws_id: str, op_id: str) -> list[dict]:
    with database.transaction() as db:
        return db.execute(
            "SELECT * FROM scout_attendance_records "
            "WHERE guild_workspace_id = ? AND guild_operation_id = ?",
            (ws_id, op_id),
        ).fetchall()


def _assignment_count(op_id: str) -> int:
    with database.transaction() as db:
        row = db.execute(
            "SELECT COUNT(*) FROM assignments WHERE guild_operation_id = ?",
            (op_id,),
        ).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# 1. Happy path: scout check-in
# ---------------------------------------------------------------------------

class TestScoutCheckin:
    def test_response_type_is_4(self):
        _, _, _, op = _setup_linked_member("scout1")
        resp = _call(_payload(op["id"], "scout"))
        assert resp["type"] == 4

    def test_response_is_ephemeral(self):
        _, _, _, op = _setup_linked_member("scout2")
        resp = _call(_payload(op["id"], "scout"))
        assert _is_ephemeral(resp)

    def test_response_content_mentions_scout(self):
        _, _, _, op = _setup_linked_member("scout3")
        resp = _call(_payload(op["id"], "scout"))
        content = resp["data"]["content"]
        assert "scout" in content.lower()

    def test_response_content_mentions_operation_title(self):
        _, _, _, op = _setup_linked_member("scout4")
        resp = _call(_payload(op["id"], "scout"))
        content = resp["data"]["content"]
        assert op["title"] in content

    def test_attendance_row_written(self):
        _, ws, _, op = _setup_linked_member("scout5")
        _call(_payload(op["id"], "scout"))
        records = _scout_records(ws["id"], op["id"])
        assert len(records) == 1

    def test_attendance_row_has_scout_role(self):
        _, ws, _, op = _setup_linked_member("scout6")
        _call(_payload(op["id"], "scout"))
        records = _scout_records(ws["id"], op["id"])
        assert records[0]["role_type"] == "scout"


# ---------------------------------------------------------------------------
# 2. Happy path: support check-in
# ---------------------------------------------------------------------------

class TestSupportCheckin:
    def test_response_type_is_4(self):
        _, _, _, op = _setup_linked_member("sup1")
        resp = _call(_payload(op["id"], "support"))
        assert resp["type"] == 4

    def test_response_is_ephemeral(self):
        _, _, _, op = _setup_linked_member("sup2")
        resp = _call(_payload(op["id"], "support"))
        assert _is_ephemeral(resp)

    def test_response_content_mentions_support(self):
        _, _, _, op = _setup_linked_member("sup3")
        resp = _call(_payload(op["id"], "support"))
        content = resp["data"]["content"]
        assert "support" in content.lower()

    def test_attendance_row_written(self):
        _, ws, _, op = _setup_linked_member("sup4")
        _call(_payload(op["id"], "support"))
        records = _scout_records(ws["id"], op["id"])
        assert len(records) == 1

    def test_attendance_row_has_support_role(self):
        _, ws, _, op = _setup_linked_member("sup5")
        _call(_payload(op["id"], "support"))
        records = _scout_records(ws["id"], op["id"])
        assert records[0]["role_type"] == "support"

    def test_no_assignments_changed(self):
        _, _, _, op = _setup_linked_member("sup6")
        before = _assignment_count(op["id"])
        _call(_payload(op["id"], "support"))
        assert _assignment_count(op["id"]) == before


# ---------------------------------------------------------------------------
# 3. Re-checkin is an upsert (not a duplicate row)
# ---------------------------------------------------------------------------

class TestRecheckin:
    def test_double_checkin_does_not_create_duplicate_row(self):
        _, ws, _, op = _setup_linked_member("recheck1")
        _call(_payload(op["id"], "scout"))
        _call(_payload(op["id"], "scout"))
        records = _scout_records(ws["id"], op["id"])
        assert len(records) == 1

    def test_role_type_change_updates_existing_row(self):
        _, ws, _, op = _setup_linked_member("recheck2")
        _call(_payload(op["id"], "scout"))
        _call(_payload(op["id"], "support"))
        records = _scout_records(ws["id"], op["id"])
        assert len(records) == 1
        assert records[0]["role_type"] == "support"


# ---------------------------------------------------------------------------
# 4. Invalid custom_id formats
# ---------------------------------------------------------------------------

class TestInvalidCustomId:
    def _error_response(self, custom_id: str) -> dict:
        _, _, _, op = _setup_linked_member(f"inv-{uuid.uuid4().hex[:8]}")
        p = {
            "discord_guild_id": _GUILD_ID,
            "discord_user_id":  _DISCORD_USER_ID,
            "custom_id":        custom_id,
        }
        with database.transaction() as db:
            return adapter.handle_component_interaction(p, db)

    def test_wrong_prefix_returns_error(self):
        resp = self._error_response("unknown:scout:abc")
        assert resp["type"] == 4
        assert _is_ephemeral(resp)
        assert "❌" in resp["data"]["content"]

    def test_too_few_segments_returns_error(self):
        resp = self._error_response("checkin:scout")
        assert resp["type"] == 4
        assert _is_ephemeral(resp)

    def test_too_many_segments_returns_error(self):
        resp = self._error_response("checkin:scout:op-id:extra")
        assert resp["type"] == 4
        assert _is_ephemeral(resp)

    def test_empty_custom_id_returns_error(self):
        resp = self._error_response("")
        assert resp["type"] == 4
        assert _is_ephemeral(resp)


# ---------------------------------------------------------------------------
# 5. Invalid role_type
# ---------------------------------------------------------------------------

class TestInvalidRoleType:
    def test_dps_role_type_returns_error(self):
        _, _, _, op = _setup_linked_member("role1")
        resp = _call(_payload(op["id"], custom_id=f"checkin:dps:{op['id']}"))
        assert resp["type"] == 4
        assert _is_ephemeral(resp)
        assert "❌" in resp["data"]["content"]

    def test_healer_role_type_returns_error(self):
        _, _, _, op = _setup_linked_member("role2")
        resp = _call(_payload(op["id"], custom_id=f"checkin:healer:{op['id']}"))
        assert resp["type"] == 4
        assert _is_ephemeral(resp)

    def test_invalid_role_no_attendance_written(self):
        _, ws, _, op = _setup_linked_member("role3")
        _call(_payload(op["id"], custom_id=f"checkin:tank:{op['id']}"))
        assert len(_scout_records(ws["id"], op["id"])) == 0


# ---------------------------------------------------------------------------
# 6. Discord identity errors
# ---------------------------------------------------------------------------

class TestDiscordIdentityErrors:
    def test_guild_not_linked_returns_error(self):
        """Workspace exists but discord_guild_id not configured."""
        owner = make_user("Owner-notlinked")
        ws    = make_workspace(slug="ws-notlinked", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        p = {
            "discord_guild_id": "999988887777666655",
            "discord_user_id":  _DISCORD_USER_ID,
            "custom_id":        f"checkin:scout:{op['id']}",
        }
        with database.transaction() as db:
            resp = adapter.handle_component_interaction(p, db)

        assert resp["type"] == 4
        assert _is_ephemeral(resp)
        assert "❌" in resp["data"]["content"]

    def test_user_not_linked_returns_error(self):
        """Guild linked but Discord user has no app user account."""
        owner = make_user("Owner-usrlink")
        ws    = make_workspace(slug="ws-usrlink", owner_user_id=owner["id"])
        _configure_discord(ws["id"], owner["id"])
        op    = make_operation(ws["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        p = {
            "discord_guild_id": _GUILD_ID,
            "discord_user_id":  "000000000000000099",  # unknown discord user
            "custom_id":        f"checkin:scout:{op['id']}",
        }
        with database.transaction() as db:
            resp = adapter.handle_component_interaction(p, db)

        assert resp["type"] == 4
        assert _is_ephemeral(resp)
        assert "❌" in resp["data"]["content"]

    def test_non_member_returns_error(self):
        """Discord user has an app account but is not a member of this workspace."""
        owner   = make_user("Owner-nonmem")
        ws      = make_workspace(slug="ws-nonmem", owner_user_id=owner["id"])
        _configure_discord(ws["id"], owner["id"])
        op      = make_operation(ws["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        # Discord user exists but is NOT added to this workspace
        _make_discord_user("Outsider", _DISCORD_USER_ID)

        p = {
            "discord_guild_id": _GUILD_ID,
            "discord_user_id":  _DISCORD_USER_ID,
            "custom_id":        f"checkin:scout:{op['id']}",
        }
        with database.transaction() as db:
            resp = adapter.handle_component_interaction(p, db)

        assert resp["type"] == 4
        assert _is_ephemeral(resp)
        assert "❌" in resp["data"]["content"]


# ---------------------------------------------------------------------------
# 7. Operation not found
# ---------------------------------------------------------------------------

class TestOperationNotFound:
    def test_nonexistent_operation_returns_ephemeral_error(self):
        _, _, _, _ = _setup_linked_member("opnf1")
        fake_op_id = str(uuid.uuid4())
        resp       = _call(_payload(fake_op_id, "scout"))
        assert resp["type"] == 4
        assert _is_ephemeral(resp)
        assert "❌" in resp["data"]["content"]

    def test_no_attendance_row_on_not_found(self):
        owner = make_user("Owner-opnf2")
        ws    = make_workspace(slug="ws-opnf2", owner_user_id=owner["id"])
        _configure_discord(ws["id"], owner["id"])
        du    = _make_discord_user("Adventurer-opnf2", _DISCORD_USER_ID)
        use_cases.add_workspace_member(ws["id"], owner["id"], du["display_name"])

        fake_op_id = str(uuid.uuid4())
        _call(_payload(fake_op_id, "scout"))

        # No attendance rows for any operation
        with database.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM scout_attendance_records WHERE guild_workspace_id = ?",
                (ws["id"],),
            ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# 8. No planner state mutated
# ---------------------------------------------------------------------------

class TestNoPlannerMutation:
    def test_scout_checkin_does_not_create_assignments(self):
        _, _, _, op = _setup_linked_member("nomut1")
        _call(_payload(op["id"], "scout"))
        assert _assignment_count(op["id"]) == 0

    def test_support_checkin_does_not_create_assignments(self):
        _, _, _, op = _setup_linked_member("nomut2")
        _call(_payload(op["id"], "support"))
        assert _assignment_count(op["id"]) == 0

    def test_checkin_does_not_change_operation_status(self):
        _, ws, _, op = _setup_linked_member("nomut3")
        _call(_payload(op["id"], "scout"))
        with database.transaction() as db:
            updated = repositories.get_guild_operation(db, op["id"], ws["id"])
        assert updated["status"] == "planning"


# ---------------------------------------------------------------------------
# 9. No Discord SDK imported by adapter
# ---------------------------------------------------------------------------

def test_adapter_does_not_import_discord_sdk():
    src = Path(__file__).parent.parent / "app" / "discord" / "adapter.py"
    text = src.read_text(encoding="utf-8")
    forbidden = ["import discord", "from discord"]
    for pattern in forbidden:
        assert pattern not in text, (
            f"adapter.py contains '{pattern}' — Discord SDK must not be imported in app/"
        )
