"""
Phase 10 Slice 3 — Setup-required visibility and setup entry point.

Tests the home-page setup signal, the public /discord/setup landing page,
and regression against existing /discord/setup/continue behaviour.

Coverage map:
  Group 1 — Repository: get_unclaimed_discord_workspaces
  1.  Ownerless Discord-provisioned workspace appears in unclaimed list.
  2.  Claimed (has owner) Discord-provisioned workspace does not appear.
  3.  Manually-created workspace (no discord_provisioned_at) does not appear.
  4.  Multiple ownerless workspaces all appear.
  5.  Empty result when no bot-provisioned workspaces exist.

  Group 2 — Home page (GET /workspaces): setup-required signal
  6.  Ownerless provisioned workspace shows setup-required alert.
  7.  Setup alert includes workspace name.
  8.  Setup alert includes /discord/setup/continue?guild_id=... link.
  9.  Normal manually-created workspace does not trigger the setup alert.
  10. After the guild owner claims the workspace the alert disappears.
  11. Home page still renders own workspaces alongside the setup section.

  Group 3 — GET /discord/setup: public landing page
  12. Returns 200 without login.
  13. Returns 200 when logged in.
  14. With DISCORD_CLIENT_ID set: shows the invite link.
  15. Invite link contains the client_id.
  16. Invite link uses scope=bot and applications.commands.
  17. Without DISCORD_CLIENT_ID: shows not-configured message.
  18. Page never renders DISCORD_CLIENT_SECRET or any token value.
  19. Page includes a link to /discord/setup/continue.

  Group 4 — Regression
  20. Existing /discord/setup/continue tests unaffected.
  21. Home page route still requires login.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GUILD_ID      = "222333444555666777"
_GUILD_NAME    = "Ironkeep Test Guild"
_OWNER_DISC_ID = "444333222111000999"

_FAKE_CLIENT_ID     = "test-client-12345678"
_FAKE_CLIENT_SECRET = "super-secret-value"   # must never appear in rendered HTML


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provision(*, guild_id=_GUILD_ID, name=_GUILD_NAME, owner_id=_OWNER_DISC_ID):
    return use_cases.ensure_workspace_for_discord_guild(
        guild_id, name, discord_guild_owner_id=owner_id
    )


def _discord_user(display_name: str, discord_snowflake: str) -> dict:
    user = make_user(display_name)
    use_cases.link_discord_identity(user["id"], discord_snowflake)
    return user


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _claim(guild_id: str, user_id: str) -> dict:
    return use_cases.complete_discord_workspace_setup(guild_id, user_id)


# ===========================================================================
# Group 1 — Repository: get_unclaimed_discord_workspaces
# ===========================================================================

class TestGetUnclaimedDiscordWorkspaces:
    def test_ownerless_provisioned_workspace_appears(self):
        ws = _provision()
        with database.transaction() as db:
            results = repositories.get_unclaimed_discord_workspaces(db)
        ids = [r["id"] for r in results]
        assert ws["id"] in ids

    def test_claimed_workspace_excluded(self):
        ws    = _provision()
        owner = _discord_user("ClaimOwner1", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        with database.transaction() as db:
            results = repositories.get_unclaimed_discord_workspaces(db)
        ids = [r["id"] for r in results]
        assert ws["id"] not in ids

    def test_manual_workspace_excluded(self):
        owner = make_user("ManualOwner1")
        ws    = make_workspace(slug="manual-excl", owner_user_id=owner["id"])
        with database.transaction() as db:
            results = repositories.get_unclaimed_discord_workspaces(db)
        ids = [r["id"] for r in results]
        assert ws["id"] not in ids

    def test_multiple_ownerless_all_returned(self):
        ws1 = use_cases.ensure_workspace_for_discord_guild("111000111000111001", "Guild A")
        ws2 = use_cases.ensure_workspace_for_discord_guild("111000111000111002", "Guild B")
        with database.transaction() as db:
            results = repositories.get_unclaimed_discord_workspaces(db)
        ids = [r["id"] for r in results]
        assert ws1["id"] in ids
        assert ws2["id"] in ids

    def test_empty_when_none_exist(self):
        with database.transaction() as db:
            results = repositories.get_unclaimed_discord_workspaces(db)
        assert results == []


# ===========================================================================
# Group 2 — Home page: setup-required signal
# ===========================================================================

class TestHomeSetupSignal:
    def _logged_in_client(self, display_name: str) -> TestClient:
        client = TestClient(app, follow_redirects=True)
        _login(client, display_name)
        return client

    def test_setup_alert_shown_for_ownerless_workspace(self):
        _provision()
        client = self._logged_in_client("HomeUser1")
        resp   = client.get("/workspaces")
        assert resp.status_code == 200
        # The template renders an alert for unclaimed workspaces.
        assert "setup required" in resp.text.lower() or "discord setup" in resp.text.lower()

    def test_setup_alert_includes_workspace_name(self):
        _provision()
        client = self._logged_in_client("HomeUser2")
        resp   = client.get("/workspaces")
        assert _GUILD_NAME in resp.text

    def test_setup_alert_includes_continue_link_with_guild_id(self):
        _provision()
        client = self._logged_in_client("HomeUser3")
        resp   = client.get("/workspaces")
        assert "/discord/setup/continue" in resp.text
        assert _GUILD_ID in resp.text

    def test_manual_workspace_no_setup_alert(self):
        owner  = make_user("ManualOwnerHome")
        ws     = make_workspace(slug="manual-home", owner_user_id=owner["id"])
        # Log in AS the owner so the workspace appears in their list too.
        client = TestClient(app, follow_redirects=True)
        _login(client, "ManualOwnerHome")
        resp   = client.get("/workspaces")
        assert resp.status_code == 200
        # No unclaimed workspaces → no setup-required alert section.
        assert "setup required" not in resp.text.lower()

    def test_claimed_workspace_no_setup_alert(self):
        ws    = _provision()
        owner = _discord_user("ClaimedHomeOwner", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        client = TestClient(app, follow_redirects=True)
        _login(client, "ClaimedHomeOwner")
        resp = client.get("/workspaces")
        assert resp.status_code == 200
        assert "setup required" not in resp.text.lower()

    def test_own_workspaces_still_listed(self):
        """Own workspaces are still shown alongside the setup section."""
        owner = make_user("DualOwner")
        ws    = make_workspace(slug="dual-own", owner_user_id=owner["id"])
        _provision()  # also creates an unclaimed workspace
        client = TestClient(app, follow_redirects=True)
        _login(client, "DualOwner")
        resp = client.get("/workspaces")
        assert resp.status_code == 200
        assert ws["name"] in resp.text
        assert "setup required" in resp.text.lower() or "discord setup" in resp.text.lower()


# ===========================================================================
# Group 3 — GET /discord/setup: public landing page
# ===========================================================================

class TestDiscordSetupPage:
    def test_returns_200_without_login(self):
        client = TestClient(app, follow_redirects=False)
        resp   = client.get("/discord/setup")
        assert resp.status_code == 200

    def test_returns_200_when_logged_in(self):
        user   = make_user("SetupPageUser")
        client = TestClient(app, follow_redirects=True)
        _login(client, "SetupPageUser")
        resp = client.get("/discord/setup")
        assert resp.status_code == 200

    def test_configured_shows_invite_link(self):
        env    = {"DISCORD_CLIENT_ID": _FAKE_CLIENT_ID}
        client = TestClient(app, follow_redirects=False)
        with patch.dict(os.environ, env):
            resp = client.get("/discord/setup")
        assert resp.status_code == 200
        assert "discord.com/oauth2/authorize" in resp.text

    def test_invite_link_contains_client_id(self):
        env    = {"DISCORD_CLIENT_ID": _FAKE_CLIENT_ID}
        client = TestClient(app, follow_redirects=False)
        with patch.dict(os.environ, env):
            resp = client.get("/discord/setup")
        assert _FAKE_CLIENT_ID in resp.text

    def test_invite_link_scope_includes_bot(self):
        env    = {"DISCORD_CLIENT_ID": _FAKE_CLIENT_ID}
        client = TestClient(app, follow_redirects=False)
        with patch.dict(os.environ, env):
            resp = client.get("/discord/setup")
        # scope=bot must appear in the link.
        assert "bot" in resp.text
        assert "applications.commands" in resp.text

    def test_not_configured_shows_safe_message(self):
        env    = {"DISCORD_CLIENT_ID": ""}
        client = TestClient(app, follow_redirects=False)
        with patch.dict(os.environ, env, clear=False):
            resp = client.get("/discord/setup")
        assert resp.status_code == 200
        assert "not configured" in resp.text.lower() or "client_id" in resp.text.lower()

    def test_no_secrets_in_page(self):
        """DISCORD_CLIENT_SECRET must never appear in rendered HTML."""
        env = {
            "DISCORD_CLIENT_ID":     _FAKE_CLIENT_ID,
            "DISCORD_CLIENT_SECRET": _FAKE_CLIENT_SECRET,
        }
        client = TestClient(app, follow_redirects=False)
        with patch.dict(os.environ, env):
            resp = client.get("/discord/setup")
        assert _FAKE_CLIENT_SECRET not in resp.text

    def test_page_links_to_setup_continue(self):
        client = TestClient(app, follow_redirects=False)
        resp   = client.get("/discord/setup")
        assert "/discord/setup/continue" in resp.text


# ===========================================================================
# Group 4 — Regression
# ===========================================================================

class TestRegression:
    def test_home_requires_login(self):
        client = TestClient(app, follow_redirects=False)
        resp   = client.get("/workspaces")
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_setup_continue_still_works(self):
        """Existing /discord/setup/continue ownership claim still functions."""
        ws    = _provision()
        owner = _discord_user("RegOwner", _OWNER_DISC_ID)
        result = _claim(_GUILD_ID, owner["id"])
        assert result["status"] == "claimed"

    def test_unclaimed_list_empty_after_claim(self):
        ws    = _provision()
        owner = _discord_user("ClaimCheck", _OWNER_DISC_ID)
        _claim(_GUILD_ID, owner["id"])
        with database.transaction() as db:
            results = repositories.get_unclaimed_discord_workspaces(db)
        ids = [r["id"] for r in results]
        assert ws["id"] not in ids
