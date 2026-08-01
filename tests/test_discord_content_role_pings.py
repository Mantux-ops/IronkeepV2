"""
Content-role pings — announcements mention the roles that care.

Content roles live in Discord: members self-assign them there and Ironkeep
stores only their snowflakes. A CTA always pings one fixed role; a smaller event
pings a per-operation selection drawn from the workspace's curated content-role
list.

Covers:
  Domain — parse_role_ids
  1.  Missing/corrupt JSON yields an empty list, never raises.
  2.  Order is preserved and duplicates collapse.

  Domain — validate_ping_role_config
  3.  Normalises empty strings and returns a JSON array.
  4.  Rejects a non-snowflake role.
  5.  Duplicates collapse, order preserved.

  Domain — resolve_ping_role_ids
  6.  A CTA pings the single configured CTA role.
  7.  A CTA ignores the operation's own selection.
  8.  A CTA with no configured role pings nobody.
  9.  An event pings its selected roles.
  10. An event's selection is filtered to the curated content-role list.
  11. An event with no selection pings nobody.

  Formatters
  12. Role mentions render as <@&id>.
  13. allowed_mentions restricts pings to exactly those roles.
  14. Mentions go in content, not the embed — embed text never pings.
  15. No roles: no content key, but allowed_mentions still suppresses @everyone.

  REST client — fetch_guild_roles
  16. Excludes @everyone and managed roles.
  17. Orders highest position first.
  18. Raises DiscordApiError on failure.
  18a. Reports the role colour so pickers can tint each role.

  Use case — config
  19. Ping config is persisted from the settings form.
  20. Omitting routing leaves ping config untouched.

  Use case — operations
  21. create_guild_operation stores ping roles.
  22. Operations default to no ping roles.
  23. update_operation_ping_roles replaces the selection.
  24. A member cannot change ping roles.
  25. Ping roles are workspace-scoped.

  Use case — posting
  26. A CTA announcement mentions the CTA role.
  27. An event announcement mentions its selected roles.
  28. A role removed from settings stops being mentioned.

  Route / UI
  29. Settings page renders the role pickers.
  29a. Roles render as pill toggles tinted with their Discord colour.
  29b. A colourless role gets no inline tint.
  30. Settings save persists ping config.
  31. New-operation form offers the curated content roles.
  32. Operation detail shows who will be pinged and saves a change.
"""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.discord import rest_client
from app.discord.formatters import (
    build_allowed_mentions,
    format_operation_announcement,
    format_role_mentions,
)
from app.discord.rest_client import DiscordApiError
from app.domain import guild_workspace
from app.errors import PermissionDenied, ValidationError
from app.main import app

from tests.conftest import make_operation, make_user, make_workspace, publish_operation

_GUILD_ID = "111222333444555666"
_CTA_CH   = "700000000000000001"
_EVENT_CH = "700000000000000002"

_CTA_ROLE   = "800000000000000001"
_ROAM_ROLE  = "800000000000000002"
_GANK_ROLE  = "800000000000000003"
_OTHER_ROLE = "800000000000000004"

_BOT_ENV = {"DISCORD_BOT_TOKEN": "test-bot-token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws_row(**overrides) -> dict:
    row = {
        "discord_cta_ping_role_id": None,
        "discord_content_role_ids_json": "[]",
        "discord_cta_operation_types_json": '["zvz"]',
    }
    row.update(overrides)
    return row


def _setup_pinging_workspace(slug: str, name: str, **overrides):
    owner = make_user(name)
    ws = make_workspace(slug=slug, owner_user_id=owner["id"])
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        # A Discord server links to exactly one workspace, so callers that build
        # two workspaces must pass distinct guild IDs.
        discord_guild_id=overrides.pop("discord_guild_id", _GUILD_ID),
        announcement_channel_id=None,
        officer_channel_id=None,
        routing={
            "cta_channel_id": _CTA_CH,
            "event_channel_id": _EVENT_CH,
            "cta_operation_types": overrides.pop("cta_operation_types", ["zvz"]),
            "cta_ping_role_id": overrides.pop("cta_ping_role_id", _CTA_ROLE),
            "content_role_ids": overrides.pop(
                "content_role_ids", [_ROAM_ROLE, _GANK_ROLE]
            ),
        },
    )
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, ws["id"])
    return owner, ws


def _seed_role_cache(
    ws_id: str,
    entries: list[tuple[str, str]],
    *,
    colour: int = 0,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        for snowflake, role_name in entries:
            repositories.upsert_discord_metadata(db, {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": ws_id,
                "entity_type": "role",
                "discord_entity_id": snowflake,
                "name": role_name,
                "extra_json": _json.dumps(
                    {"mentionable": True, "color": colour}
                ),
                "fetched_at": now,
            })


def _login(display_name: str) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"display_name": display_name}, follow_redirects=True)
    return client


# ---------------------------------------------------------------------------
# 1-2: parse_role_ids
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", "nope", "{}", '"x"', "7"])
def test_parse_role_ids_degrades_to_empty(raw):
    assert guild_workspace.parse_role_ids(raw) == []


def test_parse_role_ids_preserves_order_and_dedupes():
    assert guild_workspace.parse_role_ids(
        f'["{_GANK_ROLE}", "{_ROAM_ROLE}", "{_GANK_ROLE}", ""]'
    ) == [_GANK_ROLE, _ROAM_ROLE]


# ---------------------------------------------------------------------------
# 3-5: validate_ping_role_config
# ---------------------------------------------------------------------------

def test_validate_ping_config_normalises():
    cta, content_json = guild_workspace.validate_ping_role_config("", [])
    assert cta is None
    assert content_json == "[]"


def test_validate_ping_config_rejects_bad_role():
    with pytest.raises(ValidationError, match="Content role"):
        guild_workspace.validate_ping_role_config(None, ["nope"])


def test_validate_ping_config_dedupes_preserving_order():
    _, content_json = guild_workspace.validate_ping_role_config(
        _CTA_ROLE, [_GANK_ROLE, _ROAM_ROLE, _GANK_ROLE]
    )
    assert content_json == f'["{_GANK_ROLE}", "{_ROAM_ROLE}"]'


# ---------------------------------------------------------------------------
# 6-11: resolve_ping_role_ids
# ---------------------------------------------------------------------------

def test_cta_pings_the_configured_cta_role():
    ws = _ws_row(discord_cta_ping_role_id=_CTA_ROLE)
    op = {"operation_type": "zvz", "discord_ping_role_ids_json": "[]"}
    assert guild_workspace.resolve_ping_role_ids(ws, op) == [_CTA_ROLE]


def test_cta_ignores_operation_selection():
    """A call to arms reaches the CTA role, not whatever was ticked per event."""
    ws = _ws_row(
        discord_cta_ping_role_id=_CTA_ROLE,
        discord_content_role_ids_json=f'["{_ROAM_ROLE}"]',
    )
    op = {"operation_type": "zvz", "discord_ping_role_ids_json": f'["{_ROAM_ROLE}"]'}
    assert guild_workspace.resolve_ping_role_ids(ws, op) == [_CTA_ROLE]


def test_cta_without_role_pings_nobody():
    op = {"operation_type": "zvz", "discord_ping_role_ids_json": "[]"}
    assert guild_workspace.resolve_ping_role_ids(_ws_row(), op) == []


def test_event_pings_its_selected_roles():
    ws = _ws_row(discord_content_role_ids_json=f'["{_ROAM_ROLE}", "{_GANK_ROLE}"]')
    op = {
        "operation_type": "ganking",
        "discord_ping_role_ids_json": f'["{_GANK_ROLE}"]',
    }
    assert guild_workspace.resolve_ping_role_ids(ws, op) == [_GANK_ROLE]


def test_event_selection_is_filtered_to_curated_roles():
    """Dropping a role in settings must stop it being pinged everywhere."""
    ws = _ws_row(discord_content_role_ids_json=f'["{_ROAM_ROLE}"]')
    op = {
        "operation_type": "ganking",
        "discord_ping_role_ids_json": f'["{_ROAM_ROLE}", "{_OTHER_ROLE}"]',
    }
    assert guild_workspace.resolve_ping_role_ids(ws, op) == [_ROAM_ROLE]


def test_event_without_selection_pings_nobody():
    ws = _ws_row(discord_content_role_ids_json=f'["{_ROAM_ROLE}"]')
    op = {"operation_type": "ganking", "discord_ping_role_ids_json": "[]"}
    assert guild_workspace.resolve_ping_role_ids(ws, op) == []


# ---------------------------------------------------------------------------
# 12-15: formatters
# ---------------------------------------------------------------------------

def test_format_role_mentions():
    assert format_role_mentions([_ROAM_ROLE, _GANK_ROLE]) == (
        f"<@&{_ROAM_ROLE}> <@&{_GANK_ROLE}>"
    )
    assert format_role_mentions([]) == ""
    assert format_role_mentions(None) == ""


def test_allowed_mentions_restricts_to_roles():
    assert build_allowed_mentions([_ROAM_ROLE]) == {
        "parse": [], "roles": [_ROAM_ROLE]
    }


def test_mentions_live_in_content_not_the_embed():
    op = {
        "id": "op-1", "title": "Roam", "operation_type": "roads",
        "status": "planning", "scheduled_start_at": "2026-06-07T20:00:00+00:00",
    }
    payload = format_operation_announcement(op, ping_role_ids=[_ROAM_ROLE])
    assert payload["content"] == f"<@&{_ROAM_ROLE}>"
    assert payload["allowed_mentions"] == {"parse": [], "roles": [_ROAM_ROLE]}
    assert f"<@&{_ROAM_ROLE}>" not in str(payload["embeds"])


def test_no_roles_still_suppresses_everyone():
    op = {
        "id": "op-1", "title": "@everyone bait", "operation_type": "roads",
        "status": "planning", "scheduled_start_at": "2026-06-07T20:00:00+00:00",
    }
    payload = format_operation_announcement(op)
    assert "content" not in payload
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}


# ---------------------------------------------------------------------------
# 16-18: fetch_guild_roles
# ---------------------------------------------------------------------------

def test_fetch_guild_roles_excludes_everyone_and_managed():
    import httpx  # noqa: PLC0415
    payload = [
        {"id": _GUILD_ID,  "name": "@everyone", "position": 0, "managed": False},
        {"id": _ROAM_ROLE, "name": "Roaming",   "position": 3, "managed": False,
         "mentionable": True},
        {"id": _GANK_ROLE, "name": "SomeBot",   "position": 5, "managed": True},
    ]
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(200, json=payload)):
        roles = rest_client.fetch_guild_roles(_GUILD_ID)
    assert [r["id"] for r in roles] == [_ROAM_ROLE]
    assert roles[0]["mentionable"] is True


def test_fetch_guild_roles_orders_highest_first():
    import httpx  # noqa: PLC0415
    payload = [
        {"id": "low",  "name": "Low",  "position": 1},
        {"id": "high", "name": "High", "position": 9},
        {"id": "mid",  "name": "Mid",  "position": 5},
    ]
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(200, json=payload)):
        roles = rest_client.fetch_guild_roles(_GUILD_ID)
    assert [r["id"] for r in roles] == ["high", "mid", "low"]


def test_fetch_guild_roles_reports_colour():
    """The role colour is what makes a picker recognisable at a glance."""
    import httpx  # noqa: PLC0415
    payload = [
        {"id": _ROAM_ROLE, "name": "Roaming", "position": 3, "color": 0x9B59B6},
        {"id": _GANK_ROLE, "name": "Ganking", "position": 2},
    ]
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(200, json=payload)):
        roles = rest_client.fetch_guild_roles(_GUILD_ID)
    assert roles[0]["color"] == 0x9B59B6
    # Discord omits or zeroes the field for "no colour set".
    assert roles[1]["color"] == 0


def test_fetch_guild_roles_raises_on_failure():
    import httpx  # noqa: PLC0415
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(403, json={})):
        with pytest.raises(DiscordApiError):
            rest_client.fetch_guild_roles(_GUILD_ID)


# ---------------------------------------------------------------------------
# 19-20: workspace config
# ---------------------------------------------------------------------------

def test_ping_config_is_persisted():
    _owner, ws = _setup_pinging_workspace("ping-save", "PingSaveOwner")
    assert ws["discord_cta_ping_role_id"] == _CTA_ROLE
    assert guild_workspace.parse_role_ids(
        ws["discord_content_role_ids_json"]
    ) == [_ROAM_ROLE, _GANK_ROLE]


def test_omitting_routing_leaves_ping_config_untouched():
    owner, ws = _setup_pinging_workspace("ping-keep", "PingKeepOwner")
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=None,
        officer_channel_id=None,
    )
    with database.transaction() as db:
        fresh = repositories.get_workspace_by_id(db, ws["id"])
    assert fresh["discord_cta_ping_role_id"] == _CTA_ROLE
    assert guild_workspace.parse_role_ids(
        fresh["discord_content_role_ids_json"]
    ) == [_ROAM_ROLE, _GANK_ROLE]


# ---------------------------------------------------------------------------
# 21-25: operation ping roles
# ---------------------------------------------------------------------------

def test_create_operation_stores_ping_roles():
    _owner, ws = _setup_pinging_workspace("op-ping-create", "OpPingOwner")
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws["id"],
        title="Ganking run",
        operation_type="ganking",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
        ping_role_ids=[_GANK_ROLE],
    )
    assert guild_workspace.parse_role_ids(
        op["discord_ping_role_ids_json"]
    ) == [_GANK_ROLE]


def test_operations_default_to_no_ping_roles():
    _owner, ws = _setup_pinging_workspace("op-ping-default", "OpDefaultOwner")
    op = make_operation(ws["id"])
    assert op["discord_ping_role_ids_json"] == "[]"


def test_update_operation_ping_roles_replaces_selection():
    owner, ws = _setup_pinging_workspace("op-ping-update", "OpUpdateOwner")
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws["id"],
        title="Ganking run",
        operation_type="ganking",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
        ping_role_ids=[_GANK_ROLE],
    )
    updated = use_cases.update_operation_ping_roles(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        actor_id=owner["id"],
        ping_role_ids=[_ROAM_ROLE],
    )
    assert guild_workspace.parse_role_ids(
        updated["discord_ping_role_ids_json"]
    ) == [_ROAM_ROLE]


def test_member_cannot_change_ping_roles():
    owner, ws = _setup_pinging_workspace("op-ping-rbac", "OpRbacOwner")
    member = make_user("OpRbacMember")
    use_cases.add_workspace_member(ws["id"], owner["id"], "OpRbacMember", "member")
    op = make_operation(ws["id"], op_type="ganking")
    with pytest.raises(PermissionDenied):
        use_cases.update_operation_ping_roles(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            actor_id=member["id"],
            ping_role_ids=[_ROAM_ROLE],
        )


def test_ping_roles_are_workspace_scoped():
    owner_a, ws_a = _setup_pinging_workspace("op-ping-ws-a", "PingOwnerA")
    _owner_b, ws_b = _setup_pinging_workspace(
        "op-ping-ws-b", "PingOwnerB", discord_guild_id="111222333444555777"
    )
    op_b = make_operation(ws_b["id"], op_type="ganking")
    from app.errors import NotFoundError
    with pytest.raises(NotFoundError):
        use_cases.update_operation_ping_roles(
            guild_workspace_id=ws_a["id"],
            guild_operation_id=op_b["id"],
            actor_id=owner_a["id"],
            ping_role_ids=[_ROAM_ROLE],
        )


# ---------------------------------------------------------------------------
# 26-28: posting
# ---------------------------------------------------------------------------

def _posted_payload(ws, owner, op) -> dict:
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("app.discord.rest_client.post_message", return_value="msg-1") as mock:
        use_cases.post_discord_announcement(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            actor_id=owner["id"],
        )
    return mock.call_args[0][1]


def test_cta_announcement_mentions_cta_role():
    owner, ws = _setup_pinging_workspace("post-cta-ping", "PostCtaPingOwner")
    op = make_operation(ws["id"], op_type="zvz")
    publish_operation(ws["id"], op["id"])
    payload = _posted_payload(ws, owner, op)
    assert payload["content"] == f"<@&{_CTA_ROLE}>"
    assert payload["allowed_mentions"]["roles"] == [_CTA_ROLE]


def test_event_announcement_mentions_selected_roles():
    owner, ws = _setup_pinging_workspace("post-event-ping", "PostEventPingOwner")
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws["id"],
        title="Ganking run",
        operation_type="ganking",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
        ping_role_ids=[_GANK_ROLE, _ROAM_ROLE],
    )
    publish_operation(ws["id"], op["id"])
    payload = _posted_payload(ws, owner, op)
    assert payload["content"] == f"<@&{_GANK_ROLE}> <@&{_ROAM_ROLE}>"


def test_role_removed_from_settings_is_not_mentioned():
    owner, ws = _setup_pinging_workspace("post-ping-revoked", "PostRevokedOwner")
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws["id"],
        title="Ganking run",
        operation_type="ganking",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
        ping_role_ids=[_GANK_ROLE],
    )
    publish_operation(ws["id"], op["id"])
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=None,
        officer_channel_id=None,
        routing={
            "cta_channel_id": _CTA_CH,
            "event_channel_id": _EVENT_CH,
            "cta_operation_types": ["zvz"],
            "cta_ping_role_id": _CTA_ROLE,
            "content_role_ids": [_ROAM_ROLE],   # ganking role withdrawn
        },
    )
    payload = _posted_payload(ws, owner, op)
    assert "content" not in payload
    assert payload["allowed_mentions"]["roles"] == []


# ---------------------------------------------------------------------------
# 29-32: route / UI
# ---------------------------------------------------------------------------

def test_settings_renders_role_pickers():
    _owner, ws = _setup_pinging_workspace("ui-roles", "UiRolesOwner")
    _seed_role_cache(ws["id"], [
        (_CTA_ROLE, "CTA"), (_ROAM_ROLE, "Roaming"), (_GANK_ROLE, "Ganking"),
    ])
    resp = _login("UiRolesOwner").get("/workspaces/ui-roles/settings/discord")
    assert resp.status_code == 200
    body = resp.text
    assert '<select id="cta_ping_role_id" name="cta_ping_role_id">' in body
    assert "@Roaming" in body
    assert f'name="content_role_ids" value="{_GANK_ROLE}"' in body


def test_role_pickers_render_as_tinted_pill_toggles():
    """Roles are picked as pills carrying their Discord colour, not bare checkboxes.

    The native checkbox must stay in the markup: the pill is styling only, so the
    form keeps submitting a plain repeated field with no JavaScript involved.
    """
    _owner, ws = _setup_pinging_workspace("ui-role-pills", "UiRolePillsOwner")
    _seed_role_cache(ws["id"], [(_ROAM_ROLE, "Roaming")], colour=0x9B59B6)
    resp = _login("UiRolePillsOwner").get("/workspaces/ui-role-pills/settings/discord")
    assert resp.status_code == 200
    body = resp.text
    assert 'class="pill-toggles"' in body
    assert f'name="content_role_ids" value="{_ROAM_ROLE}"' in body
    assert "--pill-accent: #9b59b6" in body


def test_colourless_role_pill_has_no_inline_tint():
    """A role with Discord's default colour falls back to the stylesheet."""
    _owner, ws = _setup_pinging_workspace("ui-role-plain", "UiRolePlainOwner")
    _seed_role_cache(ws["id"], [(_ROAM_ROLE, "Roaming")], colour=0)
    resp = _login("UiRolePlainOwner").get("/workspaces/ui-role-plain/settings/discord")
    assert resp.status_code == 200
    assert "@Roaming" in resp.text
    assert "--pill-accent" not in resp.text


def test_settings_save_persists_ping_config():
    owner = make_user("UiPingSaveOwner")
    ws = make_workspace(slug="ui-ping-save", owner_user_id=owner["id"])
    client = _login("UiPingSaveOwner")
    with patch("app.application.use_cases.refresh_discord_metadata"):
        resp = client.post(
            "/workspaces/ui-ping-save/settings/discord",
            data={
                "discord_guild_id": _GUILD_ID,
                "cta_channel_id": _CTA_CH,
                "event_channel_id": _EVENT_CH,
                "officer_channel_id": "",
                "cta_operation_types": ["zvz"],
                "cta_ping_role_id": _CTA_ROLE,
                "content_role_ids": [_ROAM_ROLE, _GANK_ROLE],
            },
        )
    assert resp.status_code == 303
    assert "error" not in resp.headers.get("location", "")
    with database.transaction() as db:
        fresh = repositories.get_workspace_by_id(db, ws["id"])
    assert fresh["discord_cta_ping_role_id"] == _CTA_ROLE
    assert guild_workspace.parse_role_ids(
        fresh["discord_content_role_ids_json"]
    ) == [_ROAM_ROLE, _GANK_ROLE]


def test_new_operation_form_offers_content_roles():
    _owner, ws = _setup_pinging_workspace("ui-op-new", "UiOpNewOwner")
    _seed_role_cache(ws["id"], [(_ROAM_ROLE, "Roaming"), (_GANK_ROLE, "Ganking")])
    resp = _login("UiOpNewOwner").get("/workspaces/ui-op-new/operations/new")
    assert resp.status_code == 200
    body = resp.text
    assert f'name="ping_role_ids" value="{_ROAM_ROLE}"' in body
    assert "@Ganking" in body
    # The CTA role is not offered per event — it is fixed in settings.
    assert f'name="ping_role_ids" value="{_CTA_ROLE}"' not in body


def test_operation_detail_shows_and_saves_ping_roles():
    _owner, ws = _setup_pinging_workspace("ui-op-detail", "UiOpDetailOwner")
    _seed_role_cache(ws["id"], [(_ROAM_ROLE, "Roaming"), (_GANK_ROLE, "Ganking")])
    op = use_cases.create_guild_operation(
        guild_workspace_id=ws["id"],
        title="Ganking run",
        operation_type="ganking",
        scheduled_start_at="2026-06-07T20:00:00+00:00",
        ping_role_ids=[_GANK_ROLE],
    )
    client = _login("UiOpDetailOwner")
    detail_url = f"/workspaces/ui-op-detail/operations/{op['id']}"
    resp = client.get(detail_url)
    assert resp.status_code == 200
    assert "Ganking" in resp.text
    assert f'name="ping_role_ids" value="{_ROAM_ROLE}"' in resp.text

    resp = client.post(f"{detail_url}/discord/ping-roles",
                       data={"ping_role_ids": [_ROAM_ROLE]})
    assert resp.status_code == 303
    assert "error" not in resp.headers.get("location", "")
    with database.transaction() as db:
        fresh = repositories.get_guild_operation(db, op["id"], ws["id"])
    assert guild_workspace.parse_role_ids(
        fresh["discord_ping_role_ids_json"]
    ) == [_ROAM_ROLE]
