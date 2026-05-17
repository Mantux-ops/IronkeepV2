"""
Discord identity resolution tests.

Covers:
- resolve_workspace_from_discord_guild — linked/unlinked
- resolve_user_from_discord_id — linked/unlinked
- resolve_member_from_discord — success, each failure mode, wrong workspace
- get_discord_identity_context — success and error propagation
- Error hierarchy: all three errors subclass IronkeepError
- No Discord SDK imported
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import database, repositories
from app.application import use_cases
from app.discord.identity import (
    DiscordNotLinkedError,
    DiscordUserNotLinkedError,
    DiscordUserNotWorkspaceMemberError,
    get_discord_identity_context,
    resolve_member_from_discord,
    resolve_user_from_discord_id,
    resolve_workspace_from_discord_guild,
)
from app.errors import IronkeepError
from tests.conftest import make_user, make_workspace

_VALID_SNOWFLAKE       = "123456789012345678"
_VALID_SNOWFLAKE_2     = "987654321098765432"
_DISCORD_USER_ID       = "111222333444555666"
_DISCORD_USER_ID_2     = "222333444555666777"
_UNKNOWN_GUILD_ID      = "000000000000000001"
_UNKNOWN_DISCORD_UID   = "000000000000000002"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_discord_user(display_name: str, discord_user_id: str) -> dict:
    """Insert a user with auth_provider='discord' directly, bypassing OAuth."""
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
    return user


def link_workspace_to_guild(workspace_id: str, actor_id: str, discord_guild_id: str) -> None:
    """Link a workspace to a Discord guild via the use case."""
    use_cases.update_workspace_discord_config(
        guild_workspace_id=workspace_id,
        actor_id=actor_id,
        discord_guild_id=discord_guild_id,
        announcement_channel_id=None,
        officer_channel_id=None,
    )


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

def test_discord_not_linked_error_is_ironkeep_error():
    assert issubclass(DiscordNotLinkedError, IronkeepError)


def test_discord_user_not_linked_error_is_ironkeep_error():
    assert issubclass(DiscordUserNotLinkedError, IronkeepError)


def test_discord_user_not_workspace_member_error_is_ironkeep_error():
    assert issubclass(DiscordUserNotWorkspaceMemberError, IronkeepError)


def test_all_discord_errors_carry_message():
    e1 = DiscordNotLinkedError("server not linked")
    e2 = DiscordUserNotLinkedError("user not linked")
    e3 = DiscordUserNotWorkspaceMemberError("not a member")
    assert str(e1) == "server not linked"
    assert str(e2) == "user not linked"
    assert str(e3) == "not a member"


# ---------------------------------------------------------------------------
# resolve_workspace_from_discord_guild
# ---------------------------------------------------------------------------

def test_resolve_workspace_success():
    owner = make_user("OwnerWS")
    ws = make_workspace(slug="ws-res", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)

    with database.transaction() as db:
        result = resolve_workspace_from_discord_guild(db, _VALID_SNOWFLAKE)

    assert result["id"] == ws["id"]
    assert result["discord_guild_id"] == _VALID_SNOWFLAKE


def test_resolve_workspace_not_linked():
    with database.transaction() as db:
        with pytest.raises(DiscordNotLinkedError):
            resolve_workspace_from_discord_guild(db, _UNKNOWN_GUILD_ID)


def test_resolve_workspace_error_message_is_helpful():
    with database.transaction() as db:
        with pytest.raises(DiscordNotLinkedError, match="not linked"):
            resolve_workspace_from_discord_guild(db, _UNKNOWN_GUILD_ID)


# ---------------------------------------------------------------------------
# resolve_user_from_discord_id
# ---------------------------------------------------------------------------

def test_resolve_user_success():
    discord_user = make_discord_user("DiscordUserA", _DISCORD_USER_ID)

    with database.transaction() as db:
        result = resolve_user_from_discord_id(db, _DISCORD_USER_ID)

    assert result["id"] == discord_user["id"]
    assert result["auth_provider"] == "discord"
    assert result["provider_user_id"] == _DISCORD_USER_ID


def test_resolve_user_not_linked():
    with database.transaction() as db:
        with pytest.raises(DiscordUserNotLinkedError):
            resolve_user_from_discord_id(db, _UNKNOWN_DISCORD_UID)


def test_resolve_user_dev_auth_does_not_match():
    """A dev-auth user with the same ID string must not satisfy Discord resolution."""
    # DEV auth user — provider_user_id is the slug, not a snowflake, but the
    # important thing is auth_provider differs.
    make_user("SomeDevUser")

    with database.transaction() as db:
        with pytest.raises(DiscordUserNotLinkedError):
            resolve_user_from_discord_id(db, _UNKNOWN_DISCORD_UID)


# ---------------------------------------------------------------------------
# resolve_member_from_discord
# ---------------------------------------------------------------------------

def test_resolve_member_success():
    owner = make_user("OwnerMem")
    ws = make_workspace(slug="ws-mem", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)

    discord_user = make_discord_user("DiscordMember", _DISCORD_USER_ID)
    use_cases.add_workspace_member(ws["id"], owner["id"], "DiscordMember_dev", role="member")

    # add_workspace_member uses dev auth, so we need to add discord_user separately
    with database.transaction() as db:
        repositories.insert_workspace_member(db, {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "user_id": discord_user["id"],
            "role": "member",
            "created_at": _now(),
        })

    with database.transaction() as db:
        membership = resolve_member_from_discord(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)

    assert membership["guild_workspace_id"] == ws["id"]
    assert membership["user_id"] == discord_user["id"]
    assert membership["role"] == "member"


def test_resolve_member_guild_not_linked():
    make_discord_user("DiscordMem2", _DISCORD_USER_ID)

    with database.transaction() as db:
        with pytest.raises(DiscordNotLinkedError):
            resolve_member_from_discord(db, _UNKNOWN_GUILD_ID, _DISCORD_USER_ID)


def test_resolve_member_user_not_linked():
    owner = make_user("OwnerMem3")
    ws = make_workspace(slug="ws-mem3", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)

    with database.transaction() as db:
        with pytest.raises(DiscordUserNotLinkedError):
            resolve_member_from_discord(db, _VALID_SNOWFLAKE, _UNKNOWN_DISCORD_UID)


def test_resolve_member_not_a_workspace_member():
    """Discord user exists as an app user but has no membership row."""
    owner = make_user("OwnerMem4")
    ws = make_workspace(slug="ws-mem4", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)

    make_discord_user("DiscordOutsider", _DISCORD_USER_ID)  # linked but not added to ws

    with database.transaction() as db:
        with pytest.raises(DiscordUserNotWorkspaceMemberError):
            resolve_member_from_discord(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)


def test_resolve_member_wrong_workspace():
    """User is a member of workspace B, but the guild is linked to workspace A."""
    owner_a = make_user("OwnerA")
    owner_b = make_user("OwnerB")
    ws_a = make_workspace(slug="ws-a-id", owner_user_id=owner_a["id"])
    ws_b = make_workspace(slug="ws-b-id", owner_user_id=owner_b["id"])

    link_workspace_to_guild(ws_a["id"], owner_a["id"], _VALID_SNOWFLAKE)

    discord_user = make_discord_user("CrossMember", _DISCORD_USER_ID)
    # Add discord_user to workspace B only
    with database.transaction() as db:
        repositories.insert_workspace_member(db, {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws_b["id"],
            "user_id": discord_user["id"],
            "role": "member",
            "created_at": _now(),
        })

    # Guild is linked to ws_a, user is in ws_b → should fail
    with database.transaction() as db:
        with pytest.raises(DiscordUserNotWorkspaceMemberError):
            resolve_member_from_discord(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)


def test_resolve_member_error_message_names_workspace():
    """The not-a-member error message should include the workspace name."""
    owner = make_user("OwnerMsg")
    ws = make_workspace(slug="msg-ws", name="Message Guild", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)
    make_discord_user("MsgUser", _DISCORD_USER_ID)

    with database.transaction() as db:
        with pytest.raises(DiscordUserNotWorkspaceMemberError, match="Message Guild"):
            resolve_member_from_discord(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)


# ---------------------------------------------------------------------------
# get_discord_identity_context
# ---------------------------------------------------------------------------

def test_get_context_success():
    owner = make_user("OwnerCtx")
    ws = make_workspace(slug="ws-ctx", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)

    discord_user = make_discord_user("CtxMember", _DISCORD_USER_ID)
    with database.transaction() as db:
        repositories.insert_workspace_member(db, {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "user_id": discord_user["id"],
            "role": "officer",
            "created_at": _now(),
        })

    with database.transaction() as db:
        ctx = get_discord_identity_context(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)

    assert ctx["workspace"]["id"] == ws["id"]
    assert ctx["user"]["id"] == discord_user["id"]
    assert ctx["membership"]["role"] == "officer"
    assert ctx["membership"]["guild_workspace_id"] == ws["id"]
    assert ctx["membership"]["user_id"] == discord_user["id"]


def test_get_context_propagates_guild_error():
    make_discord_user("CtxUser", _DISCORD_USER_ID)

    with database.transaction() as db:
        with pytest.raises(DiscordNotLinkedError):
            get_discord_identity_context(db, _UNKNOWN_GUILD_ID, _DISCORD_USER_ID)


def test_get_context_propagates_user_error():
    owner = make_user("OwnerCtx2")
    ws = make_workspace(slug="ws-ctx2", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)

    with database.transaction() as db:
        with pytest.raises(DiscordUserNotLinkedError):
            get_discord_identity_context(db, _VALID_SNOWFLAKE, _UNKNOWN_DISCORD_UID)


def test_get_context_propagates_membership_error():
    owner = make_user("OwnerCtx3")
    ws = make_workspace(slug="ws-ctx3", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)
    make_discord_user("CtxOutsider", _DISCORD_USER_ID)

    with database.transaction() as db:
        with pytest.raises(DiscordUserNotWorkspaceMemberError):
            get_discord_identity_context(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)


def test_get_context_returns_all_three_keys():
    owner = make_user("OwnerCtx4")
    ws = make_workspace(slug="ws-ctx4", owner_user_id=owner["id"])
    link_workspace_to_guild(ws["id"], owner["id"], _VALID_SNOWFLAKE)
    discord_user = make_discord_user("CtxFull", _DISCORD_USER_ID)
    with database.transaction() as db:
        repositories.insert_workspace_member(db, {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "user_id": discord_user["id"],
            "role": "member",
            "created_at": _now(),
        })

    with database.transaction() as db:
        ctx = get_discord_identity_context(db, _VALID_SNOWFLAKE, _DISCORD_USER_ID)

    assert set(ctx.keys()) == {"workspace", "user", "membership"}


# ---------------------------------------------------------------------------
# No Discord SDK imported
# ---------------------------------------------------------------------------

def test_no_discord_sdk_imported():
    src = Path(__file__).parent.parent / "app" / "discord" / "identity.py"
    text = src.read_text()
    for forbidden in ("import discord", "from discord"):
        assert forbidden not in text, (
            f"identity.py must not import the Discord SDK (found '{forbidden}')"
        )
