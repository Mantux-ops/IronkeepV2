"""
Tests for the Discord announcement post action.

All Discord REST calls are mocked — no real network calls.

Covers:
- First post creates discord_messages row and emits discord_announcement.posted
- Second post calls edit, keeps same message_id, emits discord_announcement.updated
- REST failure creates no discord_messages row and no event
- REST failure shows flash error redirect
- POST success shows flash success redirect
- Member cannot post (PermissionDenied)
- Unauthenticated user redirected to /login
- Missing Discord config raises error
- "Post to Discord" button shown in HTML when config complete
- Button label changes to "Update" when a message row already exists
- Button hidden entirely from members
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.discord.rest_client import DiscordApiError
from app.main import app
from tests.conftest import make_operation, make_user, make_workspace

_GUILD_ID   = "111122223333444455"
_CHANNEL_ID = "555566667777888899"
_MESSAGE_ID = "999988887777666655"   # fake Discord snowflake returned by mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _detail_url(slug: str, op_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}"


def _post_url(slug: str, op_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}/discord/announce"


def _configure_discord(ws_id: str, owner_id: str) -> None:
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_id,
        actor_id=owner_id,
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=_CHANNEL_ID,
        officer_channel_id=None,
    )


# ---------------------------------------------------------------------------
# 1. Use-case level: first post
# ---------------------------------------------------------------------------

class TestFirstPost:
    def test_creates_discord_messages_row(self):
        owner = make_user("OwnerPost1")
        ws    = make_workspace(slug="post1-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            result = use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        assert result["action"] == "posted"
        assert result["discord_message_id"] == _MESSAGE_ID

        with database.transaction() as db:
            msg = repositories.get_discord_message(db, ws["id"], op["id"], "announcement")

        assert msg is not None
        assert msg["discord_message_id"] == _MESSAGE_ID
        assert msg["discord_channel_id"] == _CHANNEL_ID

    def test_emits_posted_event(self):
        owner = make_user("OwnerPost2")
        ws    = make_workspace(slug="post2-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])

        event_types = [e["event_type"] for e in events]
        assert "discord_announcement.posted" in event_types

    def test_calls_post_message_with_correct_channel(self):
        owner = make_user("OwnerPost3")
        ws    = make_workspace(slug="post3-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID) as mock_post:
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        mock_post.assert_called_once()
        called_channel = mock_post.call_args[0][0]
        assert called_channel == _CHANNEL_ID


# ---------------------------------------------------------------------------
# 2. Use-case level: second post (edit)
# ---------------------------------------------------------------------------

class TestEditExisting:
    def test_second_post_calls_edit_not_post(self):
        owner = make_user("OwnerEdit1")
        ws    = make_workspace(slug="edit1-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with patch("app.discord.rest_client.edit_message") as mock_edit, \
             patch("app.discord.rest_client.post_message") as mock_post:
            result = use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        mock_edit.assert_called_once()
        mock_post.assert_not_called()
        assert result["action"] == "updated"
        assert result["discord_message_id"] == _MESSAGE_ID

    def test_second_post_emits_updated_event(self):
        owner = make_user("OwnerEdit2")
        ws    = make_workspace(slug="edit2-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with patch("app.discord.rest_client.edit_message"):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])

        event_types = [e["event_type"] for e in events]
        assert "discord_announcement.updated" in event_types

    def test_edit_passes_existing_message_id(self):
        owner = make_user("OwnerEdit3")
        ws    = make_workspace(slug="edit3-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with patch("app.discord.rest_client.edit_message") as mock_edit:
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        called_message_id = mock_edit.call_args[0][1]
        assert called_message_id == _MESSAGE_ID


# ---------------------------------------------------------------------------
# 3. REST failure — nothing is written
# ---------------------------------------------------------------------------

class TestRestFailure:
    def test_discord_api_error_writes_no_message_row(self):
        owner = make_user("OwnerFail1")
        ws    = make_workspace(slug="fail1-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message",
                   side_effect=DiscordApiError(403, "Missing Permissions")):
            with pytest.raises(DiscordApiError):
                use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            msg = repositories.get_discord_message(db, ws["id"], op["id"], "announcement")
        assert msg is None

    def test_discord_api_error_emits_no_event(self):
        owner = make_user("OwnerFail2")
        ws    = make_workspace(slug="fail2-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with database.transaction() as db:
            before = len(repositories.get_operational_events(db, ws["id"], op["id"]))

        with patch("app.discord.rest_client.post_message",
                   side_effect=DiscordApiError(500, "Internal Server Error")):
            with pytest.raises(DiscordApiError):
                use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            after = len(repositories.get_operational_events(db, ws["id"], op["id"]))

        assert after == before


# ---------------------------------------------------------------------------
# 4. Permission and config guards
# ---------------------------------------------------------------------------

class TestGuards:
    def test_member_raises_permission_denied(self):
        from app.errors import PermissionDenied
        owner = make_user("OwnerGuard1")
        ws    = make_workspace(slug="guard1-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        membership = use_cases.add_workspace_member(ws["id"], owner["id"], "MemberGuard", role="member")
        _configure_discord(ws["id"], owner["id"])

        with pytest.raises(PermissionDenied):
            use_cases.post_discord_announcement(ws["id"], op["id"], membership["user_id"])

    def test_missing_discord_config_raises_validation_error(self):
        from app.errors import ValidationError
        owner = make_user("OwnerGuard2")
        ws    = make_workspace(slug="guard2-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        # No Discord config set

        with pytest.raises(ValidationError, match="Discord"):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])


# ---------------------------------------------------------------------------
# 5. Route level — HTTP behavior
# ---------------------------------------------------------------------------

class TestRoute:
    def test_post_success_redirects_with_flash(self):
        owner = make_user("OwnerRoute1")
        ws    = make_workspace(slug="route1-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app, follow_redirects=False)
        _login(client, "OwnerRoute1")

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            resp = client.post(_post_url("route1-ws", op["id"]))

        assert resp.status_code in (302, 303)
        assert "success=" in resp.headers["location"]

    def test_rest_failure_redirects_with_error(self):
        owner = make_user("OwnerRoute2")
        ws    = make_workspace(slug="route2-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app, follow_redirects=False)
        _login(client, "OwnerRoute2")

        with patch("app.discord.rest_client.post_message",
                   side_effect=DiscordApiError(403, "Missing Permissions")):
            resp = client.post(_post_url("route2-ws", op["id"]))

        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_unauthenticated_redirected_to_login(self):
        owner = make_user("OwnerRoute3")
        ws    = make_workspace(slug="route3-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])

        client = TestClient(app, follow_redirects=False)
        resp = client.post(_post_url("route3-ws", op["id"]))

        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]

    def test_member_gets_error_redirect(self):
        owner = make_user("OwnerRoute4")
        ws    = make_workspace(slug="route4-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "MemberRoute", role="member")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app, follow_redirects=False)
        _login(client, "MemberRoute")
        resp = client.post(_post_url("route4-ws", op["id"]))

        # member cannot even resolve as mutator — gets error or 403 redirect
        assert resp.status_code in (302, 303, 403)


# ---------------------------------------------------------------------------
# 6. Template — button display
# ---------------------------------------------------------------------------

class TestButtonDisplay:
    def test_post_button_shown_when_config_complete(self):
        owner = make_user("OwnerBtn1")
        ws    = make_workspace(slug="btn1-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerBtn1")
        resp = client.get(_detail_url("btn1-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Post to Discord" in resp.content

    def test_button_label_update_when_message_exists(self):
        owner = make_user("OwnerBtn2")
        ws    = make_workspace(slug="btn2-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MESSAGE_ID):
            use_cases.post_discord_announcement(ws["id"], op["id"], owner["id"])

        client = TestClient(app)
        _login(client, "OwnerBtn2")
        resp = client.get(_detail_url("btn2-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Update Discord Announcement" in resp.content
        assert b"Post to Discord" not in resp.content

    def test_button_hidden_from_members(self):
        owner = make_user("OwnerBtn3")
        ws    = make_workspace(slug="btn3-ws", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "MemberBtn", role="member")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "MemberBtn")
        resp = client.get(_detail_url("btn3-ws", op["id"]))

        assert resp.status_code == 200
        assert b"Post to Discord" not in resp.content
        assert b"Update Discord Announcement" not in resp.content
        assert b"discord/announce" not in resp.content
