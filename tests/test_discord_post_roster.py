"""
Tests for the Discord roster preview + explicit roster post action.

All Discord REST calls are mocked — no real network calls.

Covers:
- First post creates discord_messages row with message_type="roster"
- First post emits discord_roster.posted event
- Second post calls edit_message, not post_message
- Second post emits discord_roster.updated event
- REST failure writes no discord_messages row and no event
- Member raises PermissionDenied
- Missing Discord config raises ValidationError
- Route success redirects to planner with ?success=
- Route failure redirects to planner with ?error=
- Unauthenticated user redirected to /login
- "Post Roster to Discord" button shown in planner HTML when config complete + slots exist
- Button label changes to "Update Roster Post" after first post
- Button hidden from members
- Preview not shown when no slots generated
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.discord.rest_client import DiscordApiError
from app.main import app
from tests.conftest import make_composition, make_operation, make_user, make_workspace

_GUILD_ID   = "111122223333444455"
_CHANNEL_ID = "555566667777888899"
_MSG_ID     = "444433332222111100"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _planner_url(slug: str, op_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}/planner"


def _post_url(slug: str, op_id: str) -> str:
    return f"/workspaces/{slug}/operations/{op_id}/discord/roster"


def _configure_discord(ws_id: str, owner_id: str) -> None:
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_id,
        actor_id=owner_id,
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=_CHANNEL_ID,
        officer_channel_id=None,
    )


def _setup_with_slots(slug: str):
    """Create workspace + published operation + composition + slots. Returns (owner, ws, op)."""
    owner = make_user(f"Owner-{slug}")
    ws    = make_workspace(slug=slug, owner_user_id=owner["id"])
    op    = make_operation(ws["id"])
    comp  = make_composition(ws["id"])
    use_cases.attach_operation_plan(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        albion_composition_id=comp["id"],
        signup_status="open",
    )
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    return owner, ws, op


# ---------------------------------------------------------------------------
# 1. Use-case level: first post
# ---------------------------------------------------------------------------

class TestFirstPost:
    def test_creates_discord_messages_row(self):
        owner, ws, op = _setup_with_slots("roster-post1")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            result = use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        assert result["action"] == "posted"
        assert result["discord_message_id"] == _MSG_ID

        with database.transaction() as db:
            msg = repositories.get_discord_message(db, ws["id"], op["id"], "roster")

        assert msg is not None
        assert msg["discord_message_id"] == _MSG_ID
        assert msg["discord_channel_id"] == _CHANNEL_ID
        assert msg["message_type"] == "roster"

    def test_emits_posted_event(self):
        owner, ws, op = _setup_with_slots("roster-post2")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])

        assert any(e["event_type"] == "discord_roster.posted" for e in events)

    def test_calls_post_message_with_correct_channel(self):
        owner, ws, op = _setup_with_slots("roster-post3")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID) as mock_post:
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        mock_post.assert_called_once()
        assert mock_post.call_args[0][0] == _CHANNEL_ID


# ---------------------------------------------------------------------------
# 2. Use-case level: second post (edit)
# ---------------------------------------------------------------------------

class TestEditExisting:
    def test_second_post_calls_edit_not_post(self):
        owner, ws, op = _setup_with_slots("roster-edit1")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with patch("app.discord.rest_client.edit_message") as mock_edit, \
             patch("app.discord.rest_client.post_message") as mock_post:
            result = use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        mock_edit.assert_called_once()
        mock_post.assert_not_called()
        assert result["action"] == "updated"
        assert result["discord_message_id"] == _MSG_ID

    def test_second_post_emits_updated_event(self):
        owner, ws, op = _setup_with_slots("roster-edit2")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with patch("app.discord.rest_client.edit_message"):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            events = repositories.get_operational_events(db, ws["id"], op["id"])

        assert any(e["event_type"] == "discord_roster.updated" for e in events)

    def test_edit_passes_existing_message_id_to_discord(self):
        owner, ws, op = _setup_with_slots("roster-edit3")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with patch("app.discord.rest_client.edit_message") as mock_edit:
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        assert mock_edit.call_args[0][1] == _MSG_ID


# ---------------------------------------------------------------------------
# 3. REST failure — nothing is written
# ---------------------------------------------------------------------------

class TestRestFailure:
    def test_api_error_writes_no_message_row(self):
        owner, ws, op = _setup_with_slots("roster-fail1")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message",
                   side_effect=DiscordApiError(403, "Missing Permissions")):
            with pytest.raises(DiscordApiError):
                use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            msg = repositories.get_discord_message(db, ws["id"], op["id"], "roster")
        assert msg is None

    def test_api_error_emits_no_event(self):
        owner, ws, op = _setup_with_slots("roster-fail2")
        _configure_discord(ws["id"], owner["id"])

        with database.transaction() as db:
            before = len(repositories.get_operational_events(db, ws["id"], op["id"]))

        with patch("app.discord.rest_client.post_message",
                   side_effect=DiscordApiError(500, "Internal Server Error")):
            with pytest.raises(DiscordApiError):
                use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        with database.transaction() as db:
            after = len(repositories.get_operational_events(db, ws["id"], op["id"]))

        assert after == before


# ---------------------------------------------------------------------------
# 4. Permission and config guards
# ---------------------------------------------------------------------------

class TestGuards:
    def test_member_raises_permission_denied(self):
        from app.errors import PermissionDenied
        owner, ws, op = _setup_with_slots("roster-guard1")
        membership = use_cases.add_workspace_member(
            ws["id"], owner["id"], "RosterMember", role="member"
        )
        _configure_discord(ws["id"], owner["id"])

        with pytest.raises(PermissionDenied):
            use_cases.post_discord_roster(ws["id"], op["id"], membership["user_id"])

    def test_missing_config_raises_validation_error(self):
        from app.errors import ValidationError
        owner, ws, op = _setup_with_slots("roster-guard2")
        # No Discord config

        with pytest.raises(ValidationError, match="Discord"):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])


# ---------------------------------------------------------------------------
# 5. Route level — HTTP behavior
# ---------------------------------------------------------------------------

class TestRoute:
    def test_success_redirects_to_planner_with_flash(self):
        owner, ws, op = _setup_with_slots("roster-route1")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app, follow_redirects=False)
        _login(client, f"Owner-roster-route1")

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            resp = client.post(_post_url("roster-route1", op["id"]))

        assert resp.status_code in (302, 303)
        loc = resp.headers["location"]
        assert "planner" in loc
        assert "success=" in loc

    def test_rest_failure_redirects_to_planner_with_error(self):
        owner, ws, op = _setup_with_slots("roster-route2")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app, follow_redirects=False)
        _login(client, f"Owner-roster-route2")

        with patch("app.discord.rest_client.post_message",
                   side_effect=DiscordApiError(403, "Missing Permissions")):
            resp = client.post(_post_url("roster-route2", op["id"]))

        assert resp.status_code in (302, 303)
        loc = resp.headers["location"]
        assert "planner" in loc
        assert "error=" in loc

    def test_unauthenticated_redirected_to_login(self):
        owner, ws, op = _setup_with_slots("roster-route3")

        client = TestClient(app, follow_redirects=False)
        resp = client.post(_post_url("roster-route3", op["id"]))

        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]

    def test_member_gets_error_or_403(self):
        owner, ws, op = _setup_with_slots("roster-route4")
        use_cases.add_workspace_member(ws["id"], owner["id"], "RosterMemberR", role="member")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app, follow_redirects=False)
        _login(client, "RosterMemberR")
        resp = client.post(_post_url("roster-route4", op["id"]))

        assert resp.status_code in (302, 303, 403)


# ---------------------------------------------------------------------------
# 6. Template — button display and preview visibility
# ---------------------------------------------------------------------------

class TestTemplateDisplay:
    def test_post_button_shown_when_config_complete_and_slots_exist(self):
        owner, ws, op = _setup_with_slots("roster-btn1")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, f"Owner-roster-btn1")
        resp = client.get(_planner_url("roster-btn1", op["id"]))

        assert resp.status_code == 200
        assert b"Post Roster to Discord" in resp.content
        assert b"Discord Roster Preview" in resp.content

    def test_update_button_shown_after_first_post(self):
        owner, ws, op = _setup_with_slots("roster-btn2")
        _configure_discord(ws["id"], owner["id"])

        with patch("app.discord.rest_client.post_message", return_value=_MSG_ID):
            use_cases.post_discord_roster(ws["id"], op["id"], owner["id"])

        client = TestClient(app)
        _login(client, f"Owner-roster-btn2")
        resp = client.get(_planner_url("roster-btn2", op["id"]))

        assert resp.status_code == 200
        assert b"Update Roster Post" in resp.content
        assert b"Post Roster to Discord" not in resp.content

    def test_button_hidden_from_members(self):
        owner, ws, op = _setup_with_slots("roster-btn3")
        use_cases.add_workspace_member(ws["id"], owner["id"], "RosterMemberB", role="member")
        _configure_discord(ws["id"], owner["id"])

        client = TestClient(app)
        _login(client, "RosterMemberB")
        resp = client.get(_planner_url("roster-btn3", op["id"]))

        assert resp.status_code == 200
        assert b"Post Roster to Discord" not in resp.content
        assert b"Update Roster Post" not in resp.content
        assert b"discord/roster" not in resp.content

    def test_no_preview_when_no_slots(self):
        owner = make_user("OwnerNoSlots")
        ws    = make_workspace(slug="roster-noslots", owner_user_id=owner["id"])
        op    = make_operation(ws["id"])
        _configure_discord(ws["id"], owner["id"])
        # No plan attached, no slots generated

        client = TestClient(app)
        _login(client, "OwnerNoSlots")
        resp = client.get(_planner_url("roster-noslots", op["id"]))

        assert resp.status_code == 200
        # Preview embed should not be rendered (no slots → no embed)
        assert b"Post Roster to Discord" not in resp.content
        assert b"border-left-color: #" not in resp.content
