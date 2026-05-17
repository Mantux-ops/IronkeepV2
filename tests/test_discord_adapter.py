"""
Discord command adapter tests.

Each handler is tested end-to-end against a real isolated DB, using plain
dict payloads. No Discord SDK, no HTTP client, no mocks for use cases.

Test helper flow:
  1. make_workspace + make_discord_member  → workspace + Discord-linked member
  2. link_workspace_to_guild              → workspace.discord_guild_id set
  3. make_operation (+ publish + slots)   → operation in correct state
  4. call handler(payload, db)            → assert response shape
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import database, repositories
from app.application import use_cases
from app.discord.adapter import (
    handle_checkin_command,
    handle_readiness_command,
    handle_roster_command,
    handle_signup_command,
)
from tests.conftest import make_composition, make_operation, make_user, make_workspace

_GUILD_ID      = "123456789012345678"
_DISCORD_UID   = "111222333444555666"
_UNKNOWN_GUILD = "000000000000000001"
_UNKNOWN_DUID  = "000000000000000002"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def link_workspace(ws_id: str, actor_id: str, guild_id: str = _GUILD_ID) -> None:
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_id,
        actor_id=actor_id,
        discord_guild_id=guild_id,
        announcement_channel_id=None,
        officer_channel_id=None,
    )


def make_discord_member(
    ws: dict,
    owner: dict,
    display_name: str,
    discord_user_id: str = _DISCORD_UID,
    role: str = "member",
) -> dict:
    """Create a Discord-auth user and add them as a workspace member."""
    user = {
        "id": str(uuid.uuid4()),
        "display_name": display_name,
        "auth_provider": "discord",
        "provider_user_id": discord_user_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with database.transaction() as db:
        repositories.insert_user(db, user)
        repositories.insert_workspace_member(db, {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "user_id": user["id"],
            "role": role,
            "created_at": _now(),
        })
    return user


def make_ready_operation(ws_id: str) -> tuple[dict, dict]:
    """Create an operation with a plan and generated slots, ready for signups."""
    op = make_operation(ws_id)
    comp = make_composition(ws_id)
    use_cases.attach_operation_plan(ws_id, op["id"], comp["id"])
    use_cases.generate_operation_slots(ws_id, op["id"])
    use_cases.publish_operation(ws_id, op["id"])
    return op, comp


def _payload(operation_id: str, extra_opts: dict | None = None) -> dict:
    opts = {"operation_id": operation_id}
    if extra_opts:
        opts.update(extra_opts)
    return {
        "discord_guild_id": _GUILD_ID,
        "discord_user_id":  _DISCORD_UID,
        "options": opts,
    }


# ---------------------------------------------------------------------------
# Shared setup fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """
    Yields a dict with a linked workspace, a Discord member, a ready operation,
    and an open DB connection for use in tests.
    """
    owner = make_user("AdapterOwner")
    ws    = make_workspace(slug="adapter-ws", owner_user_id=owner["id"])
    link_workspace(ws["id"], owner["id"])
    member = make_discord_member(ws, owner, "AdapterMember")
    op, _  = make_ready_operation(ws["id"])

    with database.transaction() as db:
        yield {"owner": owner, "ws": ws, "member": member, "op": op, "db": db}


# ---------------------------------------------------------------------------
# handle_signup_command
# ---------------------------------------------------------------------------

class TestHandleSignupCommand:
    def test_success_returns_type_4(self, ctx):
        response = handle_signup_command(
            _payload(ctx["op"]["id"], {"role": "Tank"}), ctx["db"]
        )
        assert response["type"] == 4

    def test_success_response_has_embeds(self, ctx):
        response = handle_signup_command(
            _payload(ctx["op"]["id"], {"role": "DPS"}), ctx["db"]
        )
        assert "embeds" in response["data"]

    def test_success_response_is_ephemeral(self, ctx):
        response = handle_signup_command(
            _payload(ctx["op"]["id"], {"role": "Healer"}), ctx["db"]
        )
        assert response["data"].get("flags") == 64

    def test_signup_stored_in_db(self, ctx):
        handle_signup_command(
            _payload(ctx["op"]["id"], {"role": "Tank", "build": "1H Mace"}), ctx["db"]
        )
        with database.transaction() as db:
            signups = repositories.get_signups_with_display_names(
                db, ctx["op"]["id"], ctx["ws"]["id"]
            )
        assert any(s["preferred_role"] == "Tank" for s in signups)

    def test_source_is_discord(self, ctx):
        handle_signup_command(
            _payload(ctx["op"]["id"], {"role": "DPS"}), ctx["db"]
        )
        with database.transaction() as db:
            signups = repositories.get_signups_with_display_names(
                db, ctx["op"]["id"], ctx["ws"]["id"]
            )
        assert all(s["source"] == "discord" for s in signups)

    def test_duplicate_returns_error_response(self, ctx):
        handle_signup_command(_payload(ctx["op"]["id"], {"role": "DPS"}), ctx["db"])
        response = handle_signup_command(
            _payload(ctx["op"]["id"], {"role": "DPS"}), ctx["db"]
        )
        assert response["type"] == 4
        assert "content" in response["data"]
        assert "❌" in response["data"]["content"]

    def test_invalid_role_returns_error_response(self, ctx):
        response = handle_signup_command(
            _payload(ctx["op"]["id"], {"role": ""}), ctx["db"]
        )
        assert "❌" in response["data"]["content"]

    def test_guild_not_linked_returns_error_response(self, ctx):
        payload = {**_payload(ctx["op"]["id"], {"role": "Tank"}),
                   "discord_guild_id": _UNKNOWN_GUILD}
        response = handle_signup_command(payload, ctx["db"])
        assert "❌" in response["data"]["content"]

    def test_user_not_linked_returns_error_response(self, ctx):
        payload = {**_payload(ctx["op"]["id"], {"role": "Tank"}),
                   "discord_user_id": _UNKNOWN_DUID}
        response = handle_signup_command(payload, ctx["db"])
        assert "❌" in response["data"]["content"]

    def test_operation_not_found_returns_error(self, ctx):
        response = handle_signup_command(
            _payload(str(uuid.uuid4()), {"role": "Tank"}), ctx["db"]
        )
        assert "❌" in response["data"]["content"]

    def test_optional_build_and_willingness(self, ctx):
        response = handle_signup_command(
            _payload(ctx["op"]["id"], {
                "role": "Support", "build": "Locus",
                "willingness": "fill", "availability": "tentative"
            }),
            ctx["db"],
        )
        assert response["type"] == 4
        assert "embeds" in response["data"]


# ---------------------------------------------------------------------------
# handle_readiness_command
# ---------------------------------------------------------------------------

class TestHandleReadinessCommand:
    def test_success_returns_type_4(self, ctx):
        use_cases.calculate_readiness_snapshot(ctx["ws"]["id"], ctx["op"]["id"])
        response = handle_readiness_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert response["type"] == 4

    def test_success_has_embeds(self, ctx):
        use_cases.calculate_readiness_snapshot(ctx["ws"]["id"], ctx["op"]["id"])
        response = handle_readiness_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert "embeds" in response["data"]

    def test_success_is_ephemeral(self, ctx):
        use_cases.calculate_readiness_snapshot(ctx["ws"]["id"], ctx["op"]["id"])
        response = handle_readiness_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert response["data"].get("flags") == 64

    def test_no_snapshot_returns_error(self, ctx):
        # No calculate_readiness_snapshot called — handler must not calculate
        response = handle_readiness_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert "❌" in response["data"]["content"]

    def test_is_read_only_no_new_events_emitted(self, ctx):
        """Readiness handler must NOT insert new snapshot rows or events."""
        use_cases.calculate_readiness_snapshot(ctx["ws"]["id"], ctx["op"]["id"])
        with database.transaction() as db:
            before = repositories.get_latest_readiness_snapshot(
                db, ctx["op"]["id"], ctx["ws"]["id"]
            )
        handle_readiness_command(_payload(ctx["op"]["id"]), ctx["db"])
        with database.transaction() as db:
            after = repositories.get_latest_readiness_snapshot(
                db, ctx["op"]["id"], ctx["ws"]["id"]
            )
        assert before["id"] == after["id"], "readiness command must not create a new snapshot"

    def test_guild_not_linked_returns_error(self, ctx):
        payload = {**_payload(ctx["op"]["id"]), "discord_guild_id": _UNKNOWN_GUILD}
        response = handle_readiness_command(payload, ctx["db"])
        assert "❌" in response["data"]["content"]


# ---------------------------------------------------------------------------
# handle_roster_command
# ---------------------------------------------------------------------------

class TestHandleRosterCommand:
    def test_success_returns_type_4(self, ctx):
        response = handle_roster_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert response["type"] == 4

    def test_success_has_embeds(self, ctx):
        response = handle_roster_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert "embeds" in response["data"]

    def test_success_is_ephemeral(self, ctx):
        response = handle_roster_command(_payload(ctx["op"]["id"]), ctx["db"])
        assert response["data"].get("flags") == 64

    def test_open_slots_shown(self, ctx):
        response = handle_roster_command(_payload(ctx["op"]["id"]), ctx["db"])
        embed_text = str(response["data"]["embeds"])
        assert "*(open)*" in embed_text

    def test_party_fields_present(self, ctx):
        response = handle_roster_command(_payload(ctx["op"]["id"]), ctx["db"])
        field_names = [f["name"] for f in response["data"]["embeds"][0]["fields"]]
        assert any("Party" in name for name in field_names)

    def test_operation_not_found_returns_error(self, ctx):
        response = handle_roster_command(
            _payload(str(uuid.uuid4())), ctx["db"]
        )
        assert "❌" in response["data"]["content"]

    def test_guild_not_linked_returns_error(self, ctx):
        payload = {**_payload(ctx["op"]["id"]), "discord_guild_id": _UNKNOWN_GUILD}
        response = handle_roster_command(payload, ctx["db"])
        assert "❌" in response["data"]["content"]


# ---------------------------------------------------------------------------
# handle_checkin_command
# ---------------------------------------------------------------------------

class TestHandleCheckinCommand:
    def test_success_returns_type_4(self, ctx):
        response = handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "scout"}), ctx["db"]
        )
        assert response["type"] == 4

    def test_success_is_ephemeral(self, ctx):
        response = handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "support"}), ctx["db"]
        )
        assert response["data"].get("flags") == 64

    def test_success_content_names_role_and_operation(self, ctx):
        response = handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "scout"}), ctx["db"]
        )
        content = response["data"]["content"]
        assert "scout" in content
        assert ctx["op"]["title"] in content

    def test_record_stored_in_db(self, ctx):
        handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "scout"}), ctx["db"]
        )
        with database.transaction() as db:
            counts = repositories.get_scout_attendance_counts(
                db, ctx["op"]["id"], ctx["ws"]["id"]
            )
        assert counts["scout"] == 1

    def test_support_checkin(self, ctx):
        handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "support"}), ctx["db"]
        )
        with database.transaction() as db:
            counts = repositories.get_scout_attendance_counts(
                db, ctx["op"]["id"], ctx["ws"]["id"]
            )
        assert counts["support"] == 1

    def test_invalid_role_type_returns_error(self, ctx):
        response = handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "invalid_role"}), ctx["db"]
        )
        assert "❌" in response["data"]["content"]

    def test_operation_not_found_returns_error(self, ctx):
        response = handle_checkin_command(
            _payload(str(uuid.uuid4()), {"role_type": "scout"}), ctx["db"]
        )
        assert "❌" in response["data"]["content"]

    def test_with_notes(self, ctx):
        response = handle_checkin_command(
            _payload(ctx["op"]["id"], {"role_type": "scout", "notes": "Late arrival"}),
            ctx["db"],
        )
        assert response["type"] == 4
        assert "❌" not in response["data"].get("content", "")


# ---------------------------------------------------------------------------
# Cross-handler properties
# ---------------------------------------------------------------------------

def test_all_error_responses_have_type_4(ctx):
    unlinked_payload = {
        "discord_guild_id": _UNKNOWN_GUILD,
        "discord_user_id":  _DISCORD_UID,
        "options": {"operation_id": str(uuid.uuid4())},
    }
    handlers = [
        handle_signup_command,
        handle_readiness_command,
        handle_roster_command,
        handle_checkin_command,
    ]
    for handler in handlers:
        payload = {**unlinked_payload}
        if handler == handle_signup_command:
            payload["options"]["role"] = "Tank"
        elif handler == handle_checkin_command:
            payload["options"]["role_type"] = "scout"
        response = handler(payload, ctx["db"])
        assert response["type"] == 4, f"{handler.__name__} error response must have type=4"


def test_all_error_responses_are_ephemeral(ctx):
    unlinked_payload = {
        "discord_guild_id": _UNKNOWN_GUILD,
        "discord_user_id":  _DISCORD_UID,
        "options": {"operation_id": str(uuid.uuid4())},
    }
    handlers = [
        handle_signup_command,
        handle_readiness_command,
        handle_roster_command,
        handle_checkin_command,
    ]
    for handler in handlers:
        payload = {**unlinked_payload}
        if handler == handle_signup_command:
            payload["options"]["role"] = "Tank"
        elif handler == handle_checkin_command:
            payload["options"]["role_type"] = "scout"
        response = handler(payload, ctx["db"])
        assert response["data"]["flags"] == 64, (
            f"{handler.__name__} error must be ephemeral (flags=64)"
        )


def test_no_discord_sdk_imported():
    src = Path(__file__).parent.parent / "app" / "discord" / "adapter.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ("import discord", "from discord import"):
        assert forbidden not in text, (
            f"adapter.py must not import the Discord SDK (found '{forbidden}')"
        )
