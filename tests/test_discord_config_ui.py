"""
Discord workspace configuration UI tests.

Covers:
- Snowflake domain validation
- update_workspace_discord_config use case
- Route access control (owner/officer vs member)
- HTTP GET/POST behaviour
- discord_guild_id uniqueness
- Audit event emission
- DISPATCHABLE_EVENT_TYPES exclusion
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import guild_workspace
from app.domain.operational_events import WORKSPACE_DISCORD_CONFIG_UPDATED
from app.errors import ConflictError, ValidationError
from app.events import DISPATCHABLE_EVENT_TYPES
from app.main import app
from tests.conftest import make_user, make_workspace

_VALID_SNOWFLAKE = "123456789012345678"
_VALID_SNOWFLAKE_2 = "987654321098765432"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _settings_url(slug: str) -> str:
    return f"/workspaces/{slug}/settings/discord"


# ---------------------------------------------------------------------------
# 1. Snowflake domain validation
# ---------------------------------------------------------------------------

class TestSnowflakeValidation:
    def test_none_returns_none(self):
        assert guild_workspace.validate_discord_snowflake(None) is None

    def test_empty_string_returns_none(self):
        assert guild_workspace.validate_discord_snowflake("") is None

    def test_whitespace_only_returns_none(self):
        assert guild_workspace.validate_discord_snowflake("   ") is None

    def test_valid_17_digit(self):
        result = guild_workspace.validate_discord_snowflake("12345678901234567")
        assert result == "12345678901234567"

    def test_valid_18_digit(self):
        result = guild_workspace.validate_discord_snowflake(_VALID_SNOWFLAKE)
        assert result == _VALID_SNOWFLAKE

    def test_valid_15_digit_boundary(self):
        result = guild_workspace.validate_discord_snowflake("123456789012345")
        assert result == "123456789012345"

    def test_valid_20_digit_boundary(self):
        result = guild_workspace.validate_discord_snowflake("12345678901234567890")
        assert result == "12345678901234567890"

    def test_strips_whitespace(self):
        result = guild_workspace.validate_discord_snowflake(f"  {_VALID_SNOWFLAKE}  ")
        assert result == _VALID_SNOWFLAKE

    def test_letters_raise(self):
        with pytest.raises(ValidationError, match="Discord snowflake"):
            guild_workspace.validate_discord_snowflake("abc123456789012345")

    def test_too_short_raises(self):
        with pytest.raises(ValidationError):
            guild_workspace.validate_discord_snowflake("12345")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError):
            guild_workspace.validate_discord_snowflake("123456789012345678901")  # 21 digits

    def test_mixed_alphanumeric_raises(self):
        with pytest.raises(ValidationError):
            guild_workspace.validate_discord_snowflake("12345678901234X678")

    def test_hyphens_raise(self):
        with pytest.raises(ValidationError):
            guild_workspace.validate_discord_snowflake("12345-6789012-3456")

    def test_field_name_appears_in_error(self):
        with pytest.raises(ValidationError, match="Officer Channel ID"):
            guild_workspace.validate_discord_snowflake("bad", "Officer Channel ID")

    def test_validate_discord_config_returns_tuple(self):
        gid, ann, off = guild_workspace.validate_discord_config(
            _VALID_SNOWFLAKE, _VALID_SNOWFLAKE_2, None
        )
        assert gid == _VALID_SNOWFLAKE
        assert ann == _VALID_SNOWFLAKE_2
        assert off is None

    def test_validate_discord_config_clears_empty_strings(self):
        gid, ann, off = guild_workspace.validate_discord_config("", "", "")
        assert gid is None
        assert ann is None
        assert off is None

    def test_validate_discord_config_propagates_error(self):
        with pytest.raises(ValidationError):
            guild_workspace.validate_discord_config("bad_server_id", None, None)


# ---------------------------------------------------------------------------
# 2. Use case — happy path
# ---------------------------------------------------------------------------

def test_update_discord_config_happy_path():
    owner = make_user("OwnerHappy")
    ws = make_workspace(slug="happy-ws", owner_user_id=owner["id"])

    result = use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=_VALID_SNOWFLAKE_2,
        officer_channel_id=None,
    )

    assert result["discord_guild_id"] == _VALID_SNOWFLAKE
    assert result["discord_announcement_channel_id"] == _VALID_SNOWFLAKE_2
    assert result["discord_officer_channel_id"] is None


def test_update_discord_config_persists_to_db():
    owner = make_user("OwnerPersist")
    ws = make_workspace(slug="persist-ws", owner_user_id=owner["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=None,
        officer_channel_id=_VALID_SNOWFLAKE_2,
    )

    with database.transaction() as db:
        stored = repositories.get_workspace_by_id(db, ws["id"])

    assert stored["discord_guild_id"] == _VALID_SNOWFLAKE
    assert stored["discord_officer_channel_id"] == _VALID_SNOWFLAKE_2


def test_update_discord_config_clears_values():
    owner = make_user("OwnerClear")
    ws = make_workspace(slug="clear-ws", owner_user_id=owner["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=_VALID_SNOWFLAKE_2,
        officer_channel_id=_VALID_SNOWFLAKE_2,
    )

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=None,
        announcement_channel_id=None,
        officer_channel_id=None,
    )

    with database.transaction() as db:
        stored = repositories.get_workspace_by_id(db, ws["id"])

    assert stored["discord_guild_id"] is None
    assert stored["discord_announcement_channel_id"] is None
    assert stored["discord_officer_channel_id"] is None


# ---------------------------------------------------------------------------
# 3. Audit event
# ---------------------------------------------------------------------------

def test_update_discord_config_emits_event():
    owner = make_user("OwnerEvent")
    ws = make_workspace(slug="event-ws", owner_user_id=owner["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=None,
        officer_channel_id=None,
    )

    with database.transaction() as db:
        events = repositories.get_operational_events(db, ws["id"], None)

    discord_events = [
        e for e in events if e["event_type"] == WORKSPACE_DISCORD_CONFIG_UPDATED
    ]
    assert len(discord_events) == 1
    ev = discord_events[0]
    assert ev["actor_id"] == owner["id"]
    assert ev["entity_type"] == "guild_workspace"
    assert ev["entity_id"] == ws["id"]


def test_discord_config_updated_is_not_dispatchable():
    assert WORKSPACE_DISCORD_CONFIG_UPDATED not in DISPATCHABLE_EVENT_TYPES


# ---------------------------------------------------------------------------
# 4. discord_guild_id uniqueness
# ---------------------------------------------------------------------------

def test_discord_guild_id_uniqueness_conflict():
    owner_a = make_user("OwnerA")
    owner_b = make_user("OwnerB")
    ws_a = make_workspace(slug="ws-a", owner_user_id=owner_a["id"])
    ws_b = make_workspace(slug="ws-b", owner_user_id=owner_b["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_a["id"],
        actor_id=owner_a["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=None,
        officer_channel_id=None,
    )

    with pytest.raises(ConflictError, match="already linked"):
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws_b["id"],
            actor_id=owner_b["id"],
            discord_guild_id=_VALID_SNOWFLAKE,
            announcement_channel_id=None,
            officer_channel_id=None,
        )


def test_discord_guild_id_same_workspace_does_not_conflict():
    owner = make_user("OwnerRelink")
    ws = make_workspace(slug="relink-ws", owner_user_id=owner["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=None,
        officer_channel_id=None,
    )

    # Saving the same guild_id again on the same workspace must succeed
    result = use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=_VALID_SNOWFLAKE_2,
        officer_channel_id=None,
    )
    assert result["discord_guild_id"] == _VALID_SNOWFLAKE
    assert result["discord_announcement_channel_id"] == _VALID_SNOWFLAKE_2


# ---------------------------------------------------------------------------
# 5. Route access control
# ---------------------------------------------------------------------------

def test_discord_settings_get_requires_login():
    ws = make_workspace(slug="auth-ws")
    client = TestClient(app, follow_redirects=False)
    response = client.get(_settings_url("auth-ws"))
    assert response.status_code in (302, 303)
    assert "/login" in response.headers["location"]


def test_discord_settings_get_requires_mutator():
    owner = make_user("OwnerGuard")
    ws = make_workspace(slug="guard-ws", owner_user_id=owner["id"])
    use_cases.add_workspace_member(ws["id"], owner["id"], "MemberGuard", role="member")

    client = TestClient(app)
    _login(client, "MemberGuard")
    response = client.get(_settings_url("guard-ws"))
    assert response.status_code == 403


def test_discord_settings_post_requires_mutator():
    owner = make_user("OwnerPostGuard")
    ws = make_workspace(slug="post-guard-ws", owner_user_id=owner["id"])
    use_cases.add_workspace_member(ws["id"], owner["id"], "MemberPostGuard", role="member")

    client = TestClient(app)
    _login(client, "MemberPostGuard")
    response = client.post(
        _settings_url("post-guard-ws"),
        data={"discord_guild_id": _VALID_SNOWFLAKE},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_discord_settings_get_renders_for_owner():
    owner = make_user("OwnerRender")
    ws = make_workspace(slug="render-ws", owner_user_id=owner["id"])

    client = TestClient(app)
    _login(client, "OwnerRender")
    response = client.get(_settings_url("render-ws"))
    assert response.status_code == 200
    assert b"discord_guild_id" in response.content
    assert b"Announcement Channel ID" in response.content
    assert b"Officer Channel ID" in response.content


def test_discord_settings_get_renders_for_officer():
    owner = make_user("OwnerOfficer")
    ws = make_workspace(slug="officer-ws", owner_user_id=owner["id"])
    use_cases.add_workspace_member(ws["id"], owner["id"], "OfficerRender", role="officer")

    client = TestClient(app)
    _login(client, "OfficerRender")
    response = client.get(_settings_url("officer-ws"))
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 6. Route HTTP behaviour — GET pre-fills current values
# ---------------------------------------------------------------------------

def test_discord_settings_get_prefills_current_values():
    owner = make_user("OwnerPrefill")
    ws = make_workspace(slug="prefill-ws", owner_user_id=owner["id"])
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=_VALID_SNOWFLAKE_2,
        officer_channel_id=None,
    )

    client = TestClient(app)
    _login(client, "OwnerPrefill")
    response = client.get(_settings_url("prefill-ws"))
    assert response.status_code == 200
    body = response.text
    assert _VALID_SNOWFLAKE in body
    assert _VALID_SNOWFLAKE_2 in body


# ---------------------------------------------------------------------------
# 7. Route HTTP behaviour — POST success
# ---------------------------------------------------------------------------

def test_discord_settings_post_success_saves_and_redirects():
    owner = make_user("OwnerPost")
    ws = make_workspace(slug="post-ws", owner_user_id=owner["id"])

    client = TestClient(app, follow_redirects=False)
    _login(client, "OwnerPost")
    response = client.post(
        _settings_url("post-ws"),
        data={
            "discord_guild_id": _VALID_SNOWFLAKE,
            "announcement_channel_id": _VALID_SNOWFLAKE_2,
            "officer_channel_id": "",
        },
    )
    assert response.status_code == 303
    assert "settings/discord" in response.headers["location"]
    assert "success" in response.headers["location"]

    with database.transaction() as db:
        stored = repositories.get_workspace_by_id(db, ws["id"])
    assert stored["discord_guild_id"] == _VALID_SNOWFLAKE
    assert stored["discord_announcement_channel_id"] == _VALID_SNOWFLAKE_2
    assert stored["discord_officer_channel_id"] is None


# ---------------------------------------------------------------------------
# 8. Route HTTP behaviour — POST validation error
# ---------------------------------------------------------------------------

def test_discord_settings_post_invalid_snowflake_redirects_with_error():
    owner = make_user("OwnerInvalid")
    ws = make_workspace(slug="invalid-ws", owner_user_id=owner["id"])

    client = TestClient(app, follow_redirects=False)
    _login(client, "OwnerInvalid")
    response = client.post(
        _settings_url("invalid-ws"),
        data={"discord_guild_id": "not-a-snowflake", "announcement_channel_id": "", "officer_channel_id": ""},
    )
    assert response.status_code == 303
    assert "error" in response.headers["location"]

    with database.transaction() as db:
        stored = repositories.get_workspace_by_id(db, ws["id"])
    assert stored["discord_guild_id"] is None


def test_discord_settings_post_conflict_redirects_with_error():
    owner_a = make_user("OwnerConflictA")
    owner_b = make_user("OwnerConflictB")
    ws_a = make_workspace(slug="conflict-a", owner_user_id=owner_a["id"])
    ws_b = make_workspace(slug="conflict-b", owner_user_id=owner_b["id"])

    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_a["id"],
        actor_id=owner_a["id"],
        discord_guild_id=_VALID_SNOWFLAKE,
        announcement_channel_id=None,
        officer_channel_id=None,
    )

    client = TestClient(app, follow_redirects=False)
    _login(client, "OwnerConflictB")
    response = client.post(
        _settings_url("conflict-b"),
        data={"discord_guild_id": _VALID_SNOWFLAKE, "announcement_channel_id": "", "officer_channel_id": ""},
    )
    assert response.status_code == 303
    assert "error" in response.headers["location"]

    with database.transaction() as db:
        stored_b = repositories.get_workspace_by_id(db, ws_b["id"])
    assert stored_b["discord_guild_id"] is None


# ---------------------------------------------------------------------------
# 9. Settings nav link visibility
# ---------------------------------------------------------------------------

def test_settings_nav_link_visible_to_owner():
    owner = make_user("OwnerNav")
    ws = make_workspace(slug="nav-ws", owner_user_id=owner["id"])

    client = TestClient(app)
    _login(client, "OwnerNav")
    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert b"settings/discord" in response.content


def test_settings_nav_link_hidden_from_member():
    owner = make_user("OwnerNavHide")
    ws = make_workspace(slug="nav-hide-ws", owner_user_id=owner["id"])
    use_cases.add_workspace_member(ws["id"], owner["id"], "MemberNav", role="member")

    client = TestClient(app)
    _login(client, "MemberNav")
    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200
    assert b"settings/discord" not in response.content
