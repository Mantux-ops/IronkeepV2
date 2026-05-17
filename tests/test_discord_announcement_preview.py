"""
Tests for the Discord announcement preview section on the operation overview page.

Covers:
- Preview rendered when Discord config is fully set
- Embed colour matches operation status
- Readiness roster field included when snapshot exists
- Readiness roster field absent (no crash) when no snapshot
- Warning shown when discord_guild_id is missing
- Warning shown when discord_announcement_channel_id is missing
- Preview card entirely hidden from members
- GET request produces zero new OperationalEvents (read-only)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.discord.formatters import STATUS_COLORS
from app.main import app
from tests.conftest import make_operation, make_user, make_workspace

_GUILD_ID    = "111122223333444455"
_CHANNEL_ID  = "555566667777888899"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _detail_url(slug: str, op_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}"


_UNSET = object()  # sentinel for optional params


def _set_discord_config(ws_id: str, owner_id: str, *, guild_id=_GUILD_ID, channel_id=_UNSET):
    if channel_id is _UNSET:
        channel_id = _CHANNEL_ID
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_id,
        actor_id=owner_id,
        discord_guild_id=guild_id,
        announcement_channel_id=channel_id,
        officer_channel_id=None,
    )


# ---------------------------------------------------------------------------
# 1. Preview shown when fully configured
# ---------------------------------------------------------------------------

class TestPreviewFullyConfigured:
    def test_embed_title_matches_operation(self):
        owner = make_user("OwnerFull")
        ws    = make_workspace(slug="full-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"], title="Saturday ZvZ")
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerFull")
        resp = client.get(_detail_url("full-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Saturday ZvZ" in resp.content
        assert b"Discord Announcement Preview" in resp.content

    def test_embed_contains_operation_fields(self):
        owner = make_user("OwnerFields")
        ws    = make_workspace(slug="fields-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"], title="Test Op Fields")
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerFields")
        resp = client.get(_detail_url("fields-ws", op["id"]))

        body = resp.text
        assert "Type" in body
        assert "Status" in body
        assert "When" in body

    def test_target_ids_shown_below_embed(self):
        owner = make_user("OwnerTarget")
        ws    = make_workspace(slug="target-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerTarget")
        resp = client.get(_detail_url("target-ws", op["id"]))

        assert _GUILD_ID.encode() in resp.content
        assert _CHANNEL_ID.encode() in resp.content

    def test_officer_sees_preview(self):
        owner = make_user("OwnerOfficerPreview")
        ws    = make_workspace(slug="officer-preview-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "OfficerPreview", role="officer")
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OfficerPreview")
        resp = client.get(_detail_url("officer-preview-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Discord Announcement Preview" in resp.content


# ---------------------------------------------------------------------------
# 2. Embed colour matches operation status
# ---------------------------------------------------------------------------

class TestEmbedColour:
    def _colour_hex(self, status: str) -> str:
        return "#{:06x}".format(STATUS_COLORS.get(status, 0x95A5A6))

    def test_draft_colour(self):
        owner = make_user("OwnerDraftCol")
        ws    = make_workspace(slug="draft-col-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])      # default status: draft
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerDraftCol")
        resp = client.get(_detail_url("draft-col-ws", op["id"]))

        assert self._colour_hex("draft").encode() in resp.content

    def test_planning_colour(self):
        owner = make_user("OwnerPlanCol")
        ws    = make_workspace(slug="plan-col-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerPlanCol")
        resp = client.get(_detail_url("plan-col-ws", op["id"]))

        assert self._colour_hex("planning").encode() in resp.content


# ---------------------------------------------------------------------------
# 3. Readiness roster field
# ---------------------------------------------------------------------------

class TestReadinessInPreview:
    def test_roster_field_present_when_snapshot_exists(self):
        owner = make_user("OwnerReadPrev")
        ws    = make_workspace(slug="read-prev-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        # Plan must be attached while status is draft, before publishing
        from tests.conftest import make_composition
        comp = make_composition(ws["id"])
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
            signup_status="open",
        )
        use_cases.publish_operation(ws["id"], op["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.calculate_readiness_snapshot(ws["id"], op["id"])
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerReadPrev")
        resp = client.get(_detail_url("read-prev-ws", op["id"]))

        assert resp.status_code == 200
        # Roster field must appear in the Discord embed section
        assert b"Roster" in resp.content
        assert b"filled" in resp.content

    def test_no_crash_when_no_snapshot(self):
        owner = make_user("OwnerNoSnap")
        ws    = make_workspace(slug="no-snap-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerNoSnap")
        resp = client.get(_detail_url("no-snap-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Discord Announcement Preview" in resp.content


# ---------------------------------------------------------------------------
# 4. Warning states
# ---------------------------------------------------------------------------

class TestConfigWarnings:
    def test_warning_when_no_guild_id(self):
        owner = make_user("OwnerNoGuild")
        ws    = make_workspace(slug="no-guild-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        # No Discord config set at all

        client = TestClient(app)
        _login(client, "OwnerNoGuild")
        resp = client.get(_detail_url("no-guild-ws", op["id"]))

        assert resp.status_code == 200
        body = resp.text
        assert "Discord Server ID" in body or "discord_guild_id" in body.lower() or "No Discord server" in body
        # Embed mock must NOT be rendered (no color_hex div)
        assert "discord-embed" not in body or "border-left-color: #" not in body

    def test_warning_when_guild_but_no_channel(self):
        owner = make_user("OwnerNoChannel")
        ws    = make_workspace(slug="no-channel-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        # Guild ID set, no announcement channel
        _set_discord_config(ws["id"], owner["id"], channel_id=None)

        client = TestClient(app)
        _login(client, "OwnerNoChannel")
        resp = client.get(_detail_url("no-channel-ws", op["id"]))

        assert resp.status_code == 200
        body = resp.text
        assert "announcement channel" in body.lower() or "No announcement" in body
        assert "border-left-color" not in body

    def test_warning_includes_link_to_settings(self):
        owner = make_user("OwnerSettingsLink")
        ws    = make_workspace(slug="settings-link-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])

        client = TestClient(app)
        _login(client, "OwnerSettingsLink")
        resp = client.get(_detail_url("settings-link-ws", op["id"]))

        assert b"settings/discord" in resp.content


# ---------------------------------------------------------------------------
# 5. Member cannot see the preview card
# ---------------------------------------------------------------------------

class TestMemberAccess:
    def test_member_sees_no_preview_card(self):
        owner = make_user("OwnerMemberHide")
        ws    = make_workspace(slug="member-hide-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "MemberHide", role="member")
        _set_discord_config(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "MemberHide")
        resp = client.get(_detail_url("member-hide-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Discord Announcement Preview" not in resp.content
        # CSS class definition lives in base.html for all pages; check no embed element is rendered
        assert b'class="discord-embed"' not in resp.content

    def test_member_sees_no_warning_card(self):
        owner = make_user("OwnerMemberWarn")
        ws    = make_workspace(slug="member-warn-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "MemberWarn", role="member")
        # No Discord config — would show a warning for officer/owner

        client = TestClient(app)
        _login(client, "MemberWarn")
        resp = client.get(_detail_url("member-warn-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Discord Announcement Preview" not in resp.content


# ---------------------------------------------------------------------------
# 6. Read-only — no domain mutations
# ---------------------------------------------------------------------------

def test_get_produces_no_operational_events():
    owner = make_user("OwnerReadOnly")
    ws    = make_workspace(slug="readonly-ws", owner_user_id=owner["id"])
    op    = make_operation(ws["id"])
    _set_discord_config(ws["id"], owner["id"])

    with database.transaction() as db:
        before = len(repositories.get_operational_events(db, ws["id"], op["id"]))

    client = TestClient(app)
    _login(client, "OwnerReadOnly")
    client.get(_detail_url("readonly-ws", op["id"]))

    with database.transaction() as db:
        after = len(repositories.get_operational_events(db, ws["id"], op["id"]))

    assert after == before


def test_get_writes_no_discord_messages():
    owner = make_user("OwnerNoWrite")
    ws    = make_workspace(slug="nowrite-ws", owner_user_id=owner["id"])
    op    = make_operation(ws["id"])
    _set_discord_config(ws["id"], owner["id"])

    client = TestClient(app)
    _login(client, "OwnerNoWrite")
    client.get(_detail_url("nowrite-ws", op["id"]))

    with database.transaction() as db:
        msg = repositories.get_discord_message(db, ws["id"], op["id"], "announcement")

    assert msg is None
