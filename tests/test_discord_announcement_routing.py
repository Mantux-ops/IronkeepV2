"""
Announcement routing — CTAs and smaller events post to separate channels.

A guild runs two kinds of content: CTAs (mid-scale ZvZ) and looser events
(roaming, outposts, ganking, crystal creatures).  Each goes to its own Discord
channel.  Routing is derived from the operation's existing operation_type via a
per-workspace list of "these types are CTAs", so no second type field is added
to an operation.

Covers:
  Domain — parse_cta_operation_types
  1.  Missing/empty JSON falls back to the default ('zvz').
  2.  Corrupt JSON falls back rather than raising.
  3.  A stored list is normalised (case, whitespace).
  4.  An explicitly empty list means "nothing is a CTA".

  Domain — resolve_announcement_channel
  5.  A CTA type resolves to the CTA channel.
  6.  A non-CTA type resolves to the event channel.
  7.  Event channel falls back to the CTA channel when unset.
  8.  Both fall back to the legacy announcement channel.
  9.  Returns None when nothing is configured.
  10. A configured event channel is not used for a CTA type.

  Domain — validate_announcement_routing
  11. Valid input normalises empty strings to None and returns sorted JSON.
  12. An unknown operation type is rejected.
  13. A non-snowflake channel is rejected.
  14. Duplicates collapse.

  REST client — fetch_guild_channels
  15. Returns only postable text/announcement channels.
  16. Orders by category position then channel position.
  17. Raises DiscordApiError on non-2xx.
  18. Raises DiscordApiError on timeout.

  Use case — config save
  19. Routing is persisted.
  20. Omitting routing leaves it untouched.
  21. An invalid type is rejected and nothing is written.

  Use case — posting
  22. A CTA operation posts to the CTA channel.
  23. An event operation posts to the event channel.
  24. A roster follows its operation's channel.
  25. An edit stays in the channel the message was posted to.
  26. Posting fails when the operation's channel is not configured.

  Dispatcher
  27. Readiness resolves to the operation's routed channel.
  28. Noop when the operation's channel is unconfigured.

  Scheduler
  29. Reminder targets the operation's routed channel.
  30. Reminder falls back to the officer channel.

  Route / UI
  31. Settings page renders channel dropdowns from the cache, not ID inputs.
  32. Saving routing from the form persists it.
  33. A channel not in the cached list survives a save.
  34. Settings page warns when no channels are cached.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.discord import dispatcher, rest_client
from app.discord.rest_client import DiscordApiError
from app.domain import guild_operations, guild_workspace
from app.errors import ValidationError
from app.main import app

from tests.conftest import make_operation, make_user, make_workspace, publish_operation

_GUILD_ID = "111222333444555666"
_CTA_CH   = "700000000000000001"
_EVENT_CH = "700000000000000002"
_OFF_CH   = "700000000000000003"
_LEGACY   = "700000000000000009"

_BOT_ENV = {"DISCORD_BOT_TOKEN": "test-bot-token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws_row(**overrides) -> dict:
    """A minimal workspace-shaped dict for pure domain assertions."""
    row = {
        "discord_cta_channel_id": None,
        "discord_event_channel_id": None,
        "discord_announcement_channel_id": None,
        "discord_cta_operation_types_json": '["zvz"]',
    }
    row.update(overrides)
    return row


def _setup_routed_workspace(slug: str, name: str, **routing):
    """Create a workspace with Discord linked and routing configured."""
    owner = make_user(name)
    ws = make_workspace(slug=slug, owner_user_id=owner["id"])
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=routing.pop("announcement_channel_id", None),
        officer_channel_id=routing.pop("officer_channel_id", None),
        routing={
            "cta_channel_id": routing.pop("cta_channel_id", _CTA_CH),
            "event_channel_id": routing.pop("event_channel_id", _EVENT_CH),
            "cta_operation_types": routing.pop("cta_operation_types", ["zvz"]),
        },
    )
    with database.transaction() as db:
        ws = repositories.get_workspace_by_id(db, ws["id"])
    return owner, ws


# ---------------------------------------------------------------------------
# 1-4: parse_cta_operation_types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, ""])
def test_parse_cta_types_defaults_when_absent(raw):
    assert guild_workspace.parse_cta_operation_types(raw) == {"zvz"}


@pytest.mark.parametrize("raw", ["not json", "{}", '"zvz"', "42"])
def test_parse_cta_types_falls_back_on_garbage(raw):
    assert guild_workspace.parse_cta_operation_types(raw) == {"zvz"}


def test_parse_cta_types_normalises_entries():
    assert guild_workspace.parse_cta_operation_types(
        '["ZvZ", " Ganking ", ""]'
    ) == {"zvz", "ganking"}


def test_parse_cta_types_empty_list_means_nothing_is_cta():
    assert guild_workspace.parse_cta_operation_types("[]") == set()


# ---------------------------------------------------------------------------
# 5-10: resolve_announcement_channel
# ---------------------------------------------------------------------------

def test_cta_type_resolves_to_cta_channel():
    ws = _ws_row(discord_cta_channel_id=_CTA_CH, discord_event_channel_id=_EVENT_CH)
    assert guild_workspace.resolve_announcement_channel(ws, "zvz") == _CTA_CH


def test_non_cta_type_resolves_to_event_channel():
    ws = _ws_row(discord_cta_channel_id=_CTA_CH, discord_event_channel_id=_EVENT_CH)
    assert guild_workspace.resolve_announcement_channel(ws, "ganking") == _EVENT_CH


def test_event_channel_falls_back_to_cta_channel():
    ws = _ws_row(discord_cta_channel_id=_CTA_CH)
    assert guild_workspace.resolve_announcement_channel(ws, "roads") is None
    ws = _ws_row(
        discord_cta_channel_id=_CTA_CH,
        discord_announcement_channel_id=_CTA_CH,
    )
    assert guild_workspace.resolve_announcement_channel(ws, "roads") == _CTA_CH


def test_both_fall_back_to_legacy_announcement_channel():
    ws = _ws_row(discord_announcement_channel_id=_LEGACY)
    assert guild_workspace.resolve_announcement_channel(ws, "zvz") == _LEGACY
    assert guild_workspace.resolve_announcement_channel(ws, "ganking") == _LEGACY


def test_resolve_returns_none_when_unconfigured():
    assert guild_workspace.resolve_announcement_channel(_ws_row(), "zvz") is None


def test_event_channel_is_not_used_for_a_cta():
    """An event channel must never absorb a CTA just because CTA is unset."""
    ws = _ws_row(discord_event_channel_id=_EVENT_CH)
    assert guild_workspace.resolve_announcement_channel(ws, "zvz") is None


# ---------------------------------------------------------------------------
# 11-14: validate_announcement_routing
# ---------------------------------------------------------------------------

def test_validate_routing_normalises_and_sorts():
    cta, event, types_json = guild_workspace.validate_announcement_routing(
        _CTA_CH, "", ["ZvZ", "ganking"], guild_operations.VALID_OPERATION_TYPES
    )
    assert cta == _CTA_CH
    assert event is None
    assert types_json == '["ganking", "zvz"]'


def test_validate_routing_rejects_unknown_type():
    with pytest.raises(ValidationError, match="crystal"):
        guild_workspace.validate_announcement_routing(
            _CTA_CH, _EVENT_CH, ["crystal"], guild_operations.VALID_OPERATION_TYPES
        )


def test_validate_routing_rejects_bad_snowflake():
    with pytest.raises(ValidationError):
        guild_workspace.validate_announcement_routing(
            "not-a-snowflake", None, ["zvz"], guild_operations.VALID_OPERATION_TYPES
        )


def test_validate_routing_collapses_duplicates():
    _, _, types_json = guild_workspace.validate_announcement_routing(
        None, None, ["zvz", "zvz", "ZVZ"], guild_operations.VALID_OPERATION_TYPES
    )
    assert types_json == '["zvz"]'


# ---------------------------------------------------------------------------
# 15-18: fetch_guild_channels
# ---------------------------------------------------------------------------

def test_fetch_guild_channels_filters_to_postable_types():
    import httpx  # noqa: PLC0415
    payload = [
        {"id": "1", "name": "text",        "type": 0, "position": 0},
        {"id": "2", "name": "news",        "type": 5, "position": 1},
        {"id": "3", "name": "Voice",       "type": 2, "position": 2},
        {"id": "4", "name": "Category",    "type": 4, "position": 3},
        {"id": "5", "name": "forum",       "type": 15, "position": 4},
    ]
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(200, json=payload)):
        channels = rest_client.fetch_guild_channels(_GUILD_ID)
    assert [c["id"] for c in channels] == ["1", "2"]
    assert channels[1]["channel_type"] == 5


def test_fetch_guild_channels_orders_by_category_then_position():
    import httpx  # noqa: PLC0415
    payload = [
        {"id": "cat_b", "name": "B",      "type": 4, "position": 1},
        {"id": "cat_a", "name": "A",      "type": 4, "position": 0},
        {"id": "in_b",  "name": "in-b",   "type": 0, "position": 0, "parent_id": "cat_b"},
        {"id": "in_a2", "name": "in-a-2", "type": 0, "position": 1, "parent_id": "cat_a"},
        {"id": "in_a1", "name": "in-a-1", "type": 0, "position": 0, "parent_id": "cat_a"},
        {"id": "top",   "name": "top",    "type": 0, "position": 0},
    ]
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(200, json=payload)):
        channels = rest_client.fetch_guild_channels(_GUILD_ID)
    # Uncategorised first, then category A's children in order, then B's.
    assert [c["id"] for c in channels] == ["top", "in_a1", "in_a2", "in_b"]
    assert channels[1]["parent_id"] == "cat_a"


def test_fetch_guild_channels_raises_on_error_status():
    import httpx  # noqa: PLC0415
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", return_value=httpx.Response(403, json={"message": "Missing Access"})):
        with pytest.raises(DiscordApiError):
            rest_client.fetch_guild_channels(_GUILD_ID)


def test_fetch_guild_channels_raises_on_timeout():
    import httpx  # noqa: PLC0415
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(DiscordApiError):
            rest_client.fetch_guild_channels(_GUILD_ID)


# ---------------------------------------------------------------------------
# 19-21: config save
# ---------------------------------------------------------------------------

def test_routing_is_persisted():
    _owner, ws = _setup_routed_workspace(
        "routing-save", "RoutingOwner", cta_operation_types=["zvz", "hellgate"]
    )
    assert ws["discord_cta_channel_id"] == _CTA_CH
    assert ws["discord_event_channel_id"] == _EVENT_CH
    assert guild_workspace.parse_cta_operation_types(
        ws["discord_cta_operation_types_json"]
    ) == {"zvz", "hellgate"}


def test_omitting_routing_leaves_it_untouched():
    """Linking a Discord server must not wipe a configured routing setup."""
    owner, ws = _setup_routed_workspace("routing-keep", "KeepOwner")
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=None,
        officer_channel_id=_OFF_CH,
    )
    with database.transaction() as db:
        fresh = repositories.get_workspace_by_id(db, ws["id"])
    assert fresh["discord_cta_channel_id"] == _CTA_CH
    assert fresh["discord_event_channel_id"] == _EVENT_CH
    assert fresh["discord_officer_channel_id"] == _OFF_CH


def test_invalid_routing_type_writes_nothing():
    owner = make_user("BadRoutingOwner")
    ws = make_workspace(slug="bad-routing", owner_user_id=owner["id"])
    with pytest.raises(ValidationError):
        use_cases.update_workspace_discord_config(
            guild_workspace_id=ws["id"],
            actor_id=owner["id"],
            discord_guild_id=_GUILD_ID,
            announcement_channel_id=None,
            officer_channel_id=None,
            routing={
                "cta_channel_id": _CTA_CH,
                "event_channel_id": _EVENT_CH,
                "cta_operation_types": ["outposts"],
            },
        )
    with database.transaction() as db:
        fresh = repositories.get_workspace_by_id(db, ws["id"])
    assert fresh["discord_guild_id"] is None
    assert fresh["discord_cta_channel_id"] is None


# ---------------------------------------------------------------------------
# 22-26: posting
# ---------------------------------------------------------------------------

def _post_announcement(ws, owner, op):
    """Post an announcement with REST mocked; returns the channel used."""
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("app.discord.rest_client.post_message", return_value="msg-1") as mock_post:
        use_cases.post_discord_announcement(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            actor_id=owner["id"],
        )
    return mock_post.call_args[0][0]


def test_cta_operation_posts_to_cta_channel():
    owner, ws = _setup_routed_workspace("post-cta", "PostCtaOwner")
    op = make_operation(ws["id"], title="Saturday CTA", op_type="zvz")
    publish_operation(ws["id"], op["id"])
    assert _post_announcement(ws, owner, op) == _CTA_CH


def test_event_operation_posts_to_event_channel():
    owner, ws = _setup_routed_workspace("post-event", "PostEventOwner")
    op = make_operation(ws["id"], title="Ganking run", op_type="ganking")
    publish_operation(ws["id"], op["id"])
    assert _post_announcement(ws, owner, op) == _EVENT_CH


def test_roster_follows_operation_channel():
    owner, ws = _setup_routed_workspace("post-roster", "PostRosterOwner")
    op = make_operation(ws["id"], title="Roam", op_type="roads")
    publish_operation(ws["id"], op["id"])
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("app.discord.rest_client.post_message", return_value="msg-2") as mock_post:
        use_cases.post_discord_roster(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            actor_id=owner["id"],
        )
    assert mock_post.call_args[0][0] == _EVENT_CH


def test_edit_stays_in_the_channel_it_was_posted_to():
    """Re-routing in settings must not retarget an existing message."""
    owner, ws = _setup_routed_workspace("post-reroute", "RerouteOwner")
    op = make_operation(ws["id"], title="Ganking run", op_type="ganking")
    publish_operation(ws["id"], op["id"])
    assert _post_announcement(ws, owner, op) == _EVENT_CH

    # Officer now declares ganking a CTA, so routing would pick the CTA channel.
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws["id"],
        actor_id=owner["id"],
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=None,
        officer_channel_id=None,
        routing={
            "cta_channel_id": _CTA_CH,
            "event_channel_id": _EVENT_CH,
            "cta_operation_types": ["zvz", "ganking"],
        },
    )
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("app.discord.rest_client.edit_message") as mock_edit:
        use_cases.post_discord_announcement(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            actor_id=owner["id"],
        )
    assert mock_edit.call_args[0][0] == _EVENT_CH


def test_posting_fails_when_operation_channel_unconfigured():
    owner, ws = _setup_routed_workspace(
        "post-missing", "MissingOwner", event_channel_id=None
    )
    op = make_operation(ws["id"], title="Ganking run", op_type="ganking")
    publish_operation(ws["id"], op["id"])
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("app.discord.rest_client.post_message") as mock_post:
        with pytest.raises(ValidationError, match="must be configured"):
            use_cases.post_discord_announcement(
                guild_workspace_id=ws["id"],
                guild_operation_id=op["id"],
                actor_id=owner["id"],
            )
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 27-28: dispatcher
# ---------------------------------------------------------------------------

def _readiness_event(ws_id: str, op_id: str) -> dict:
    from app.domain import operational_events as ev
    return {
        "event_type": ev.READINESS_SNAPSHOT_CREATED,
        "guild_workspace_id": ws_id,
        "guild_operation_id": op_id,
    }


def _seed_readiness(ws_id: str, op_id: str) -> None:
    with database.transaction() as db:
        repositories.insert_readiness_snapshot(db, {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws_id,
            "guild_operation_id": op_id,
            "total_slots": 5,
            "assigned_slots": 3,
            "open_slots": 2,
            "unassigned_signup_count": 0,
            "missing_roles_json": "[]",
            "missing_builds_json": "[]",
            "attendance_marked_count": 0,
            "attendance_unmarked_count": 0,
            "scout_count": 0,
            "support_count": 0,
            "reserve_count": 0,
            "readiness_state": "forming",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


def test_readiness_resolves_to_routed_channel():
    owner, ws = _setup_routed_workspace("disp-route", "DispOwner")
    op = make_operation(ws["id"], title="Ganking run", op_type="ganking")
    publish_operation(ws["id"], op["id"])
    _seed_readiness(ws["id"], op["id"])
    with database.transaction() as db:
        action = dispatcher.resolve_action(_readiness_event(ws["id"], op["id"]), db)
    assert action["action"] == "post_message"
    assert action["discord_channel_id"] == _EVENT_CH


def test_readiness_noops_when_routed_channel_missing():
    owner, ws = _setup_routed_workspace(
        "disp-missing", "DispMissingOwner", event_channel_id=None
    )
    op = make_operation(ws["id"], title="Ganking run", op_type="ganking")
    publish_operation(ws["id"], op["id"])
    _seed_readiness(ws["id"], op["id"])
    with database.transaction() as db:
        action = dispatcher.resolve_action(_readiness_event(ws["id"], op["id"]), db)
    assert action["action"] == "noop"
    assert "announcement channel" in action["reason"]


# ---------------------------------------------------------------------------
# 29-30: scheduler reminders
# ---------------------------------------------------------------------------

def test_reminder_targets_routed_channel():
    from app.scheduler import jobs
    row = {
        "operation_type": "ganking",
        "discord_cta_channel_id": _CTA_CH,
        "discord_event_channel_id": _EVENT_CH,
        "discord_announcement_channel_id": None,
        "discord_officer_channel_id": _OFF_CH,
        "discord_cta_operation_types_json": '["zvz"]',
    }
    assert jobs._reminder_channel(row) == _EVENT_CH
    assert jobs._reminder_channel({**row, "operation_type": "zvz"}) == _CTA_CH


def test_reminder_falls_back_to_officer_channel():
    from app.scheduler import jobs
    row = {
        "operation_type": "ganking",
        "discord_cta_channel_id": None,
        "discord_event_channel_id": None,
        "discord_announcement_channel_id": None,
        "discord_officer_channel_id": _OFF_CH,
        "discord_cta_operation_types_json": '["zvz"]',
    }
    assert jobs._reminder_channel(row) == _OFF_CH


# ---------------------------------------------------------------------------
# 31-34: route / UI
# ---------------------------------------------------------------------------

def _seed_channel_cache(ws_id: str, entries: list[tuple[str, str]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        for snowflake, name in entries:
            repositories.upsert_discord_metadata(db, {
                "id": str(uuid.uuid4()),
                "guild_workspace_id": ws_id,
                "entity_type": "channel",
                "discord_entity_id": snowflake,
                "name": name,
                "extra_json": '{"channel_type": 0}',
                "fetched_at": now,
            })


def _login(display_name: str) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"display_name": display_name}, follow_redirects=True)
    return client


def test_settings_renders_channel_dropdowns():
    owner, ws = _setup_routed_workspace("ui-drop", "UiDropOwner")
    _seed_channel_cache(ws["id"], [(_CTA_CH, "cta-announcements"), (_EVENT_CH, "events")])
    resp = _login("UiDropOwner").get("/workspaces/ui-drop/settings/discord")
    assert resp.status_code == 200
    body = resp.text
    assert '<select id="cta_channel_id" name="cta_channel_id">' in body
    assert '<select id="event_channel_id" name="event_channel_id">' in body
    assert "#cta-announcements" in body
    assert "#events" in body
    # The legacy free-typed channel ID input is gone.
    assert 'name="announcement_channel_id"' not in body
    # CTA type checkboxes are rendered, with zvz preselected.
    assert 'name="cta_operation_types" value="zvz"' in body


def test_settings_save_persists_routing():
    owner = make_user("UiSaveOwner")
    ws = make_workspace(slug="ui-save", owner_user_id=owner["id"])
    _seed_channel_cache(ws["id"], [(_CTA_CH, "cta"), (_EVENT_CH, "events")])
    client = _login("UiSaveOwner")
    with patch.dict(__import__("os").environ, _BOT_ENV), \
         patch("app.application.use_cases.refresh_discord_metadata"):
        resp = client.post(
            "/workspaces/ui-save/settings/discord",
            data={
                "discord_guild_id": _GUILD_ID,
                "cta_channel_id": _CTA_CH,
                "event_channel_id": _EVENT_CH,
                "officer_channel_id": "",
                "cta_operation_types": ["zvz", "hellgate"],
            },
        )
    assert resp.status_code == 303
    assert "error" not in resp.headers.get("location", "")
    with database.transaction() as db:
        fresh = repositories.get_workspace_by_id(db, ws["id"])
    assert fresh["discord_cta_channel_id"] == _CTA_CH
    assert fresh["discord_event_channel_id"] == _EVENT_CH
    assert guild_workspace.parse_cta_operation_types(
        fresh["discord_cta_operation_types_json"]
    ) == {"zvz", "hellgate"}
    # The legacy column mirrors the CTA channel so any unrouted read still works.
    assert fresh["discord_announcement_channel_id"] == _CTA_CH


def test_uncached_channel_survives_a_save():
    """A configured channel the bot can no longer list must stay selectable."""
    owner, ws = _setup_routed_workspace("ui-uncached", "UiUncachedOwner")
    _seed_channel_cache(ws["id"], [(_EVENT_CH, "events")])
    resp = _login("UiUncachedOwner").get("/workspaces/ui-uncached/settings/discord")
    assert f'<option value="{_CTA_CH}" selected>' in resp.text
    assert "(not in list)" in resp.text


def test_settings_warns_when_no_channels_cached():
    owner, ws = _setup_routed_workspace("ui-empty", "UiEmptyOwner")
    resp = _login("UiEmptyOwner").get("/workspaces/ui-empty/settings/discord")
    assert "No channels loaded yet" in resp.text
