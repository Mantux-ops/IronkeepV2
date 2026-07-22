"""
Discord-guild-based workspace auto-join test suite.

Feature: being a member of a Discord server that has Ironkeep installed grants
automatic membership of the linked workspace. On Discord login the callback
reads the user's servers (via the `guilds` OAuth scope) and calls
``sync_discord_guild_memberships`` to add a ``workspace_members`` row for every
matching, active workspace.

Test groups:
  1. OAuth: authorization URL requests the `guilds` scope
  2. OAuth: fetch_user_guilds parses / errors correctly
  3. Use case: sync_discord_guild_memberships (join / idempotent / skip)
  4. HTTP: login callback auto-joins the user
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.auth import discord_oauth
from app.main import app
from tests.conftest import make_user, make_workspace


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _link_workspace_to_guild(ws_id: str, discord_guild_id: str) -> None:
    with database.transaction() as db:
        repositories.set_workspace_discord_guild_id(
            db, ws_id, discord_guild_id, _now_iso()
        )


class _FakeResponse:
    def __init__(self, *, is_success=True, status_code=200, json_data=None, text=""):
        self.is_success = is_success
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


# ---------------------------------------------------------------------------
# 1. Authorization URL requests the guilds scope
# ---------------------------------------------------------------------------

_OAUTH_ENV = {
    "DISCORD_CLIENT_ID": "test-client-id",
    "DISCORD_CLIENT_SECRET": "test-client-secret",
    "DISCORD_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/discord/callback",
}


def test_authorization_url_requests_guilds_scope():
    with patch.dict(os.environ, _OAUTH_ENV):
        url = discord_oauth.build_authorization_url("state123")
    # Scope is URL-encoded: "identify guilds" -> "identify+guilds" or "%20".
    assert "identify" in url
    assert "guilds" in url


# ---------------------------------------------------------------------------
# 2. fetch_user_guilds
# ---------------------------------------------------------------------------

def test_fetch_user_guilds_parses_list():
    payload = [
        {"id": "111", "name": "Dutch Chaos"},
        {"id": "222", "name": "Other Server"},
    ]
    with patch("app.auth.discord_oauth.httpx.get",
               return_value=_FakeResponse(json_data=payload)):
        guilds = discord_oauth.fetch_user_guilds("tok")
    assert [g["id"] for g in guilds] == ["111", "222"]


def test_fetch_user_guilds_non_list_returns_empty():
    with patch("app.auth.discord_oauth.httpx.get",
               return_value=_FakeResponse(json_data={"message": "nope"})):
        assert discord_oauth.fetch_user_guilds("tok") == []


def test_fetch_user_guilds_non_2xx_raises():
    with patch("app.auth.discord_oauth.httpx.get",
               return_value=_FakeResponse(is_success=False, status_code=401, text="unauthorized")):
        with pytest.raises(discord_oauth.DiscordOAuthError):
            discord_oauth.fetch_user_guilds("tok")


# ---------------------------------------------------------------------------
# 3. Use case: sync_discord_guild_memberships
# ---------------------------------------------------------------------------

class TestSyncDiscordGuildMemberships:

    def test_joins_workspace_for_matching_guild(self):
        owner = make_user("Owner A")
        ws = make_workspace(owner_user_id=owner["id"], slug="dga-1")
        _link_workspace_to_guild(ws["id"], "discord-guild-1")
        user = make_user("Newcomer A")

        result = use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=["discord-guild-1"]
        )

        assert [w["id"] for w in result["joined"]] == [ws["id"]]
        with database.transaction() as db:
            m = repositories.get_workspace_membership(db, ws["id"], user["id"])
        assert m is not None
        assert m["role"] == "member"

    def test_emits_autojoin_event(self):
        owner = make_user("Owner B")
        ws = make_workspace(owner_user_id=owner["id"], slug="dga-2")
        _link_workspace_to_guild(ws["id"], "discord-guild-2")
        user = make_user("Newcomer B")

        use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=["discord-guild-2"]
        )

        with database.transaction() as db:
            rows = db.execute(
                "SELECT event_type FROM operational_events "
                "WHERE guild_workspace_id = ? AND actor_id = ?",
                (ws["id"], user["id"]),
            ).fetchall()
        assert any(r[0] == "workspace.member.discord_autojoined" for r in rows)

    def test_idempotent_no_duplicate_membership(self):
        owner = make_user("Owner C")
        ws = make_workspace(owner_user_id=owner["id"], slug="dga-3")
        _link_workspace_to_guild(ws["id"], "discord-guild-3")
        user = make_user("Newcomer C")

        use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=["discord-guild-3"]
        )
        second = use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=["discord-guild-3"]
        )
        assert second["joined"] == []
        with database.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM workspace_members "
                "WHERE guild_workspace_id = ? AND user_id = ?",
                (ws["id"], user["id"]),
            ).fetchone()[0]
        assert count == 1

    def test_existing_owner_role_preserved(self):
        # The workspace creator is already an owner; syncing their own guild
        # membership must not demote them to 'member'.
        owner = make_user("Owner D")
        ws = make_workspace(owner_user_id=owner["id"], slug="dga-4")
        _link_workspace_to_guild(ws["id"], "discord-guild-4")

        result = use_cases.sync_discord_guild_memberships(
            user_id=owner["id"], discord_guild_ids=["discord-guild-4"]
        )
        assert result["joined"] == []
        with database.transaction() as db:
            m = repositories.get_workspace_membership(db, ws["id"], owner["id"])
        assert m["role"] == "owner"

    def test_unknown_guild_id_no_membership(self):
        user = make_user("Nomad")
        result = use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=["guild-with-no-workspace"]
        )
        assert result["joined"] == []

    def test_soft_deleted_workspace_skipped(self):
        owner = make_user("Owner E")
        ws = make_workspace(owner_user_id=owner["id"], slug="dga-5")
        _link_workspace_to_guild(ws["id"], "discord-guild-5")
        # Soft-delete the workspace directly.
        with database.transaction() as db:
            db.execute(
                "UPDATE guild_workspaces SET deleted_at = ? WHERE id = ?",
                (_now_iso(), ws["id"]),
            )
        user = make_user("Newcomer E")

        result = use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=["discord-guild-5"]
        )
        assert result["joined"] == []
        with database.transaction() as db:
            m = repositories.get_workspace_membership(db, ws["id"], user["id"])
        assert m is None

    def test_multiple_guilds_join_all(self):
        owner = make_user("Owner F")
        ws1 = make_workspace(owner_user_id=owner["id"], slug="dga-6a", name="WS 6A")
        ws2 = make_workspace(owner_user_id=owner["id"], slug="dga-6b", name="WS 6B")
        _link_workspace_to_guild(ws1["id"], "discord-guild-6a")
        _link_workspace_to_guild(ws2["id"], "discord-guild-6b")
        user = make_user("Newcomer F")

        result = use_cases.sync_discord_guild_memberships(
            user_id=user["id"],
            discord_guild_ids=["discord-guild-6a", "discord-guild-6b", "unknown"],
        )
        joined_ids = {w["id"] for w in result["joined"]}
        assert joined_ids == {ws1["id"], ws2["id"]}

    def test_empty_guild_ids_returns_empty(self):
        user = make_user("Empty")
        assert use_cases.sync_discord_guild_memberships(
            user_id=user["id"], discord_guild_ids=[]
        ) == {"joined": []}


# ---------------------------------------------------------------------------
# 4. HTTP callback auto-joins the user
# ---------------------------------------------------------------------------

def _run_callback(next_path: str = "/") -> TestClient:
    client = TestClient(app, follow_redirects=False)
    init_resp = client.get(f"/auth/discord?next={next_path}", follow_redirects=False)
    import urllib.parse
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(init_resp.headers["location"]).query)
    state = qs["state"][0]
    resp = client.get(
        f"/auth/discord/callback?code=code-123&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return client


def test_callback_autojoins_workspace_of_shared_discord_server():
    owner = make_user("Callback Owner")
    ws = make_workspace(owner_user_id=owner["id"], slug="dga-cb")
    _link_workspace_to_guild(ws["id"], "discord-guild-cb")

    identity = {"id": "555000111222333444", "username": "cbuser", "global_name": "CBUser"}
    guilds = [{"id": "discord-guild-cb", "name": "Dutch Chaos"}]

    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value=identity), \
         patch("app.auth.discord_oauth.fetch_user_guilds", return_value=guilds):
        _run_callback()

    with database.transaction() as db:
        user = repositories.get_user_by_provider_identity(db, "discord", "555000111222333444")
        m = repositories.get_workspace_membership(db, ws["id"], user["id"])
    assert m is not None
    assert m["role"] == "member"


def test_callback_login_succeeds_when_guild_fetch_fails():
    # A failure to read the guild list must never block login.
    identity = {"id": "555000111222333999", "username": "failuser", "global_name": "FailUser"}

    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value=identity), \
         patch("app.auth.discord_oauth.fetch_user_guilds",
               side_effect=discord_oauth.DiscordOAuthError("boom")):
        _run_callback()

    with database.transaction() as db:
        user = repositories.get_user_by_provider_identity(db, "discord", "555000111222333999")
    assert user is not None
