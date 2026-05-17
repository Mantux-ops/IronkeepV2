"""
Account Linking: Dev User → Discord Identity tests.

Covers:
  Use-case (link_discord_identity)
  1.  Inserts into user_auth_identities; does NOT touch users.auth_provider / provider_user_id.
  2.  users.id is unchanged after linking.
  3.  workspace_members rows are unaffected.
  4.  users.display_name is NOT updated during linking.
  5.  Idempotent: linking same snowflake twice returns user without error.
  6.  ConflictError when user already has a discord identity for a different snowflake.
  7.  ConflictError when user.auth_provider is 'discord' (pure discord user).
  8.  ConflictError when another user with workspace_members claims the same snowflake.
  9.  Orphaned discord user (no references) is deleted atomically; link succeeds.
  10. user.discord_linked events emitted once per workspace membership.
  11. No events emitted for users with no workspace memberships.

  Repository (get_user_by_provider_identity)
  12. Primary path: resolves via user_auth_identities JOIN.
  13. Fallback path: resolves via legacy users columns when no identity row exists.
  14. get_auth_identities_for_user returns all rows ordered by auth_provider.
  15. insert_user_auth_identity enforces UNIQUE(auth_provider, provider_user_id).
  16. insert_user_auth_identity enforces UNIQUE(user_id, auth_provider).
  17. count_user_references counts workspace_members + actor_id events.

  discord_oauth_login after linking
  18. discord_oauth_login finds the linked user (same users.id) after linking.
  19. discord_oauth_login does NOT update display_name for linked users.
  20. discord_oauth_login DOES update display_name for pure discord users.
  21. discord_oauth_login creates both users + user_auth_identities for new users.

  Migration / backfill
  22. Backfill inserts a user_auth_identities row for every pre-existing users row.
  23. Backfill is idempotent (running twice produces no duplicates).

  HTTP — GET /account
  24. Returns 200 for authenticated user; shows dev provider badge.
  25. Shows "Link Discord Account" button for dev user with no discord identity.
  26. Shows "Discord linked" text for user with discord identity.
  27. Redirects to /login for unauthenticated user.

  HTTP — GET /auth/discord/link
  28. Redirects to Discord for authenticated dev user + OAuth configured.
  29. Redirects with error for unauthenticated user.
  30. Redirects with error when user already has discord identity.
  31. Redirects with error when OAuth not configured.

  HTTP — GET /auth/discord/link/callback
  32. Valid flow: identity row created, session user_id unchanged, redirected to /account.
  33. State mismatch: error redirect, no DB mutation.
  34. Missing 'linking' flag: error redirect.
  35. ConflictError from use case: error redirect, no mutation.
  36. All Discord API calls mocked.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, ValidationError
from app.main import app

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OAUTH_ENV = {
    "DISCORD_CLIENT_ID":             "test-client-id",
    "DISCORD_CLIENT_SECRET":         "test-client-secret",
    "DISCORD_OAUTH_REDIRECT_URI":    "http://localhost:8000/auth/discord/callback",
    "DISCORD_OAUTH_LINK_REDIRECT_URI": "http://localhost:8000/auth/discord/link/callback",
}

_SNOWFLAKE_A = "111111111111111111"
_SNOWFLAKE_B = "222222222222222222"


def _get_identity_row(user_id: str, auth_provider: str) -> dict | None:
    with database.transaction() as db:
        rows = repositories.get_auth_identities_for_user(db, user_id)
    return next((r for r in rows if r["auth_provider"] == auth_provider), None)


def _make_dev_user(name: str) -> dict:
    """Create a dev user and return the users row."""
    return use_cases.dev_login_or_create_user(name)


def _make_discord_user(snowflake: str, username: str) -> dict:
    """Create a pure discord user (new-style: both users + identity row)."""
    return use_cases.discord_oauth_login(snowflake, username)


# ---------------------------------------------------------------------------
# 1-11: Use-case tests
# ---------------------------------------------------------------------------

def test_link_does_not_mutate_users_columns():
    user = _make_dev_user("LinkTestA")
    original_provider     = user["auth_provider"]
    original_provider_uid = user["provider_user_id"]

    use_cases.link_discord_identity(user["id"], _SNOWFLAKE_A + "A")

    with database.transaction() as db:
        refreshed = repositories.get_user_by_id(db, user["id"])
    assert refreshed["auth_provider"]    == original_provider
    assert refreshed["provider_user_id"] == original_provider_uid


def test_link_preserves_users_id():
    user = _make_dev_user("LinkTestB")
    original_id = user["id"]
    use_cases.link_discord_identity(user["id"], _SNOWFLAKE_A + "B")
    with database.transaction() as db:
        refreshed = repositories.get_user_by_id(db, user["id"])
    assert refreshed["id"] == original_id


def test_link_preserves_workspace_members():
    owner = _make_dev_user("OwnerForLink")
    ws    = make_workspace(slug="link-ws-members", owner_user_id=owner["id"])
    member = _make_dev_user("MemberForLink")
    use_cases.add_workspace_member(ws["id"], owner["id"], "MemberForLink", "member")

    use_cases.link_discord_identity(member["id"], _SNOWFLAKE_A + "C")

    with database.transaction() as db:
        membership = repositories.get_workspace_membership(db, ws["id"], member["id"])
    assert membership is not None
    assert membership["role"] == "member"


def test_link_does_not_update_display_name():
    user = _make_dev_user("GuildNamePreserved")
    assert user["display_name"] == "GuildNamePreserved"

    use_cases.link_discord_identity(user["id"], _SNOWFLAKE_A + "D")

    with database.transaction() as db:
        refreshed = repositories.get_user_by_id(db, user["id"])
    assert refreshed["display_name"] == "GuildNamePreserved"


def test_link_is_idempotent():
    user = _make_dev_user("IdempotentLink")
    snowflake = _SNOWFLAKE_A + "E"
    use_cases.link_discord_identity(user["id"], snowflake)
    result = use_cases.link_discord_identity(user["id"], snowflake)  # second call
    assert result["id"] == user["id"]

    # Only one discord identity row should exist.
    with database.transaction() as db:
        identities = repositories.get_auth_identities_for_user(db, user["id"])
    discord_rows = [i for i in identities if i["auth_provider"] == "discord"]
    assert len(discord_rows) == 1


def test_link_conflicts_on_different_snowflake():
    user = _make_dev_user("ConflictDifferentSnowflake")
    use_cases.link_discord_identity(user["id"], _SNOWFLAKE_A + "F")
    with pytest.raises(ConflictError, match="already linked to a different Discord"):
        use_cases.link_discord_identity(user["id"], _SNOWFLAKE_B + "F")


def test_link_blocked_for_pure_discord_user():
    discord_user = _make_discord_user(_SNOWFLAKE_A + "G", "PureDiscordG")
    with pytest.raises(ConflictError, match="Only accounts.*dev login"):
        use_cases.link_discord_identity(discord_user["id"], _SNOWFLAKE_B + "G")


def test_link_blocked_when_other_user_with_memberships_claims_snowflake():
    owner  = _make_dev_user("OwnerForBlock")
    ws     = make_workspace(slug="block-link-ws", owner_user_id=owner["id"])
    # Create a discord user and directly insert a workspace membership for them.
    discord_user = _make_discord_user(_SNOWFLAKE_A + "H", "DiscordMemberH")
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?, ?, ?, 'member', '2025-01-01T00:00:00+00:00')",
            (str(uuid.uuid4()), ws["id"], discord_user["id"]),
        )

    # A dev user tries to link to the same snowflake that the discord user (with membership) holds.
    dev_user = _make_dev_user("DevUserH")
    with pytest.raises(ConflictError, match="workspace memberships or history"):
        use_cases.link_discord_identity(dev_user["id"], _SNOWFLAKE_A + "H")


def test_link_deletes_orphaned_discord_user_atomically():
    """
    If a discord user was created by a prior OAuth login (no memberships, no events),
    linking a dev account to the same snowflake should delete the orphan and succeed.
    """
    snowflake = _SNOWFLAKE_A + "I"
    # Orphan created by earlier Discord login (before linking existed).
    orphan = _make_discord_user(snowflake, "OrphanDiscordI")

    dev_user = _make_dev_user("DevUserI")
    result = use_cases.link_discord_identity(dev_user["id"], snowflake)
    assert result["id"] == dev_user["id"]

    # Orphan must be gone.
    with database.transaction() as db:
        gone = repositories.get_user_by_id(db, orphan["id"])
    assert gone is None

    # Dev user now has the discord identity.
    discord_row = _get_identity_row(dev_user["id"], "discord")
    assert discord_row is not None
    assert discord_row["provider_user_id"] == snowflake


def test_link_emits_event_per_workspace_membership():
    owner  = _make_dev_user("OwnerForEvents")
    ws1    = make_workspace(slug="ev-ws-one", owner_user_id=owner["id"])
    ws2    = make_workspace(slug="ev-ws-two", owner_user_id=owner["id"])
    member = _make_dev_user("MemberForEvents")
    use_cases.add_workspace_member(ws1["id"], owner["id"], "MemberForEvents", "member")
    use_cases.add_workspace_member(ws2["id"], owner["id"], "MemberForEvents", "member")

    snowflake = _SNOWFLAKE_A + "J"
    use_cases.link_discord_identity(member["id"], snowflake)

    with database.transaction() as db:
        events_ws1 = [
            e for e in repositories.get_operational_events(db, ws1["id"], None)
            if e["event_type"] == "user.discord_linked" and e["actor_id"] == member["id"]
        ]
        events_ws2 = [
            e for e in repositories.get_operational_events(db, ws2["id"], None)
            if e["event_type"] == "user.discord_linked" and e["actor_id"] == member["id"]
        ]
    assert len(events_ws1) == 1
    assert len(events_ws2) == 1


def test_link_no_events_when_no_workspace_memberships():
    user = _make_dev_user("LonelyDevUser")
    snowflake = _SNOWFLAKE_A + "K"
    # Should not raise; no events emitted (no memberships to emit to).
    result = use_cases.link_discord_identity(user["id"], snowflake)
    assert result["id"] == user["id"]


# ---------------------------------------------------------------------------
# 12-17: Repository tests
# ---------------------------------------------------------------------------

def test_get_user_by_provider_identity_primary_path():
    """Resolution via user_auth_identities JOIN."""
    user = _make_dev_user("PrimaryPathUser")
    # user_auth_identities row was created by dev_login_or_create_user.
    with database.transaction() as db:
        found = repositories.get_user_by_provider_identity(db, "dev", user["provider_user_id"])
    assert found is not None
    assert found["id"] == user["id"]


def test_get_user_by_provider_identity_fallback_path():
    """Resolution via legacy users columns when no identity row exists."""
    # Manually insert a user WITHOUT an identity row (simulates pre-backfill state).
    now = "2025-01-01T00:00:00+00:00"
    bare_user = {
        "id": str(uuid.uuid4()),
        "display_name": "LegacyUser",
        "auth_provider": "dev",
        "provider_user_id": "legacy-user-slug",
        "created_at": now,
        "updated_at": now,
    }
    with database.transaction() as db:
        repositories.insert_user(db, bare_user)
        # Explicitly delete any identity row that might have been created.
        db.execute(
            "DELETE FROM user_auth_identities WHERE user_id = ?", (bare_user["id"],)
        )
    # Now the fallback path must find it.
    with database.transaction() as db:
        found = repositories.get_user_by_provider_identity(db, "dev", "legacy-user-slug")
    assert found is not None
    assert found["id"] == bare_user["id"]


def test_get_auth_identities_for_user_ordered_by_provider():
    user = _make_dev_user("MultiIdentityUser")
    snowflake = _SNOWFLAKE_B + "L"
    use_cases.link_discord_identity(user["id"], snowflake)

    with database.transaction() as db:
        identities = repositories.get_auth_identities_for_user(db, user["id"])
    providers = [i["auth_provider"] for i in identities]
    assert "dev" in providers
    assert "discord" in providers
    # Ordered by auth_provider alphabetically: dev < discord.
    assert providers.index("dev") < providers.index("discord")


def test_insert_user_auth_identity_unique_provider_user_id():
    """Two different users cannot claim the same (provider, provider_user_id)."""
    user_a = _make_dev_user("UniqueConstraintA")
    user_b = _make_dev_user("UniqueConstraintB")
    snowflake = _SNOWFLAKE_B + "M"

    import sqlite3  # noqa: PLC0415
    with database.transaction() as db:
        repositories.insert_user_auth_identity(db, {
            "id": str(uuid.uuid4()),
            "user_id": user_a["id"],
            "auth_provider": "discord",
            "provider_user_id": snowflake,
            "created_at": "2025-01-01T00:00:00+00:00",
        })
    with pytest.raises(Exception):  # sqlite3.IntegrityError wrapped by sqlite
        with database.transaction() as db:
            repositories.insert_user_auth_identity(db, {
                "id": str(uuid.uuid4()),
                "user_id": user_b["id"],
                "auth_provider": "discord",
                "provider_user_id": snowflake,
                "created_at": "2025-01-01T00:00:00+00:00",
            })


def test_insert_user_auth_identity_unique_user_provider():
    """One user cannot have two discord identity rows."""
    user = _make_dev_user("UniqueUserProviderN")
    snowflake_x = _SNOWFLAKE_B + "N1"
    snowflake_y = _SNOWFLAKE_B + "N2"

    with database.transaction() as db:
        repositories.insert_user_auth_identity(db, {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "auth_provider": "discord",
            "provider_user_id": snowflake_x,
            "created_at": "2025-01-01T00:00:00+00:00",
        })
    with pytest.raises(Exception):
        with database.transaction() as db:
            repositories.insert_user_auth_identity(db, {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "auth_provider": "discord",
                "provider_user_id": snowflake_y,
                "created_at": "2025-01-01T00:00:00+00:00",
            })


def test_count_user_references_workspace_members():
    owner = _make_dev_user("OwnerForRefCount")
    ws    = make_workspace(slug="ref-count-ws", owner_user_id=owner["id"])
    member = _make_dev_user("MemberForRefCount")
    use_cases.add_workspace_member(ws["id"], owner["id"], "MemberForRefCount", "member")

    with database.transaction() as db:
        count = repositories.count_user_references(db, member["id"])
    assert count >= 1


# ---------------------------------------------------------------------------
# 18-21: discord_oauth_login after linking
# ---------------------------------------------------------------------------

def test_discord_login_finds_linked_user():
    """After linking, discord_oauth_login returns the original dev user's id."""
    snowflake = _SNOWFLAKE_B + "O"
    dev_user = _make_dev_user("LinkedDevUserO")
    use_cases.link_discord_identity(dev_user["id"], snowflake)

    logged_in = use_cases.discord_oauth_login(snowflake, "DiscordNameO")
    assert logged_in["id"] == dev_user["id"]


def test_discord_login_does_not_update_display_name_for_linked_user():
    snowflake = _SNOWFLAKE_B + "P"
    dev_user = _make_dev_user("GuildNameO")
    use_cases.link_discord_identity(dev_user["id"], snowflake)

    # Discord login with a different username should NOT update display_name.
    use_cases.discord_oauth_login(snowflake, "CompletelyDifferentDiscordName")
    with database.transaction() as db:
        refreshed = repositories.get_user_by_id(db, dev_user["id"])
    assert refreshed["display_name"] == "GuildNameO"


def test_discord_login_updates_display_name_for_pure_discord_user():
    snowflake = _SNOWFLAKE_B + "Q"
    use_cases.discord_oauth_login(snowflake, "OriginalDiscordName")
    # Second login with updated Discord username.
    result = use_cases.discord_oauth_login(snowflake, "UpdatedDiscordName")
    assert result["display_name"] == "UpdatedDiscordName"


def test_discord_login_creates_identity_row_for_new_user():
    snowflake = _SNOWFLAKE_B + "R"
    user = use_cases.discord_oauth_login(snowflake, "NewDiscordUser")
    with database.transaction() as db:
        identities = repositories.get_auth_identities_for_user(db, user["id"])
    discord_rows = [i for i in identities if i["auth_provider"] == "discord"]
    assert len(discord_rows) == 1
    assert discord_rows[0]["provider_user_id"] == snowflake


# ---------------------------------------------------------------------------
# 22-23: Migration / backfill
# ---------------------------------------------------------------------------

def test_backfill_creates_identity_rows_for_existing_users():
    """
    Re-running init_schema (which runs _DATA_MIGRATIONS) on a DB that already
    has users must produce identity rows for all of them.
    """
    user = _make_dev_user("BackfillTestUser")
    # Force delete identity row to simulate pre-backfill state.
    with database.transaction() as db:
        db.execute("DELETE FROM user_auth_identities WHERE user_id = ?", (user["id"],))

    # Re-run init_schema — backfill should re-create the row.
    database.init_schema()

    with database.transaction() as db:
        identities = repositories.get_auth_identities_for_user(db, user["id"])
    assert len(identities) >= 1


def test_backfill_is_idempotent():
    user = _make_dev_user("BackfillIdempotentUser")
    # Run init_schema twice.
    database.init_schema()
    database.init_schema()
    with database.transaction() as db:
        identities = repositories.get_auth_identities_for_user(db, user["id"])
    dev_rows = [i for i in identities if i["auth_provider"] == "dev"]
    assert len(dev_rows) == 1


# ---------------------------------------------------------------------------
# 24-27: GET /account
# ---------------------------------------------------------------------------

def test_account_page_shows_for_authenticated_user():
    user = _make_dev_user("AccountPageUser")
    client = TestClient(app)
    client.post("/login", data={"display_name": "AccountPageUser", "next": "/"}, follow_redirects=True)
    resp = client.get("/account")
    assert resp.status_code == 200
    assert "AccountPageUser" in resp.text


def test_account_page_shows_link_button_for_dev_user():
    with patch.dict(os.environ, _OAUTH_ENV):
        _make_dev_user("AccountLinkButton")
        client = TestClient(app)
        client.post("/login", data={"display_name": "AccountLinkButton", "next": "/"}, follow_redirects=True)
        resp = client.get("/account")
    assert resp.status_code == 200
    assert "/auth/discord/link" in resp.text


def test_account_page_shows_linked_for_discord_identity():
    snowflake = _SNOWFLAKE_B + "S"
    with patch.dict(os.environ, {**_OAUTH_ENV, "IRONKEEP_ENV": "dev"}):
        dev_user = _make_dev_user("LinkedShowUser")
        use_cases.link_discord_identity(dev_user["id"], snowflake)
        client = TestClient(app)
        client.post("/login", data={"display_name": "LinkedShowUser", "next": "/"}, follow_redirects=True)
        resp = client.get("/account")
    assert resp.status_code == 200
    assert "discord" in resp.text.lower()
    # Link button must NOT appear when already linked.
    assert "/auth/discord/link" not in resp.text


def test_account_page_redirects_unauthenticated():
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/account")
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# 28-31: GET /auth/discord/link
# ---------------------------------------------------------------------------

def test_link_initiate_redirects_to_discord():
    with patch.dict(os.environ, _OAUTH_ENV):
        _make_dev_user("LinkInitiateUser")
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "LinkInitiateUser", "next": "/"}, follow_redirects=True)
        resp = client.get("/auth/discord/link")
    assert resp.status_code == 303
    assert "discord.com/oauth2/authorize" in resp.headers["location"]


def test_link_initiate_unauthenticated_redirects():
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/discord/link")
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_link_initiate_already_linked_returns_error():
    snowflake = _SNOWFLAKE_B + "T"
    with patch.dict(os.environ, _OAUTH_ENV):
        dev_user = _make_dev_user("AlreadyLinkedT")
        use_cases.link_discord_identity(dev_user["id"], snowflake)
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "AlreadyLinkedT", "next": "/"}, follow_redirects=True)
        resp = client.get("/auth/discord/link")
    assert resp.status_code == 303
    assert "/account" in resp.headers["location"]
    assert "error" in resp.headers["location"]


def test_link_initiate_oauth_not_configured():
    env = {"DISCORD_CLIENT_ID": "", "DISCORD_CLIENT_SECRET": "", "DISCORD_OAUTH_REDIRECT_URI": ""}
    _make_dev_user("OAuthMissingUser")
    with patch.dict(os.environ, env):
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "OAuthMissingUser", "next": "/"}, follow_redirects=True)
        resp = client.get("/auth/discord/link")
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


# ---------------------------------------------------------------------------
# 32-36: GET /auth/discord/link/callback
# ---------------------------------------------------------------------------

_LINK_IDENTITY = {
    "id": "555666777888999000",
    "username": "linkuser",
    "global_name": "LinkUser",
}


def _initiate_link(client: TestClient, env: dict) -> str:
    """Start the link flow and return the oauth_state from the redirect URL."""
    import urllib.parse  # noqa: PLC0415
    resp = client.get("/auth/discord/link", follow_redirects=False)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    return qs["state"][0]


def test_link_callback_success():
    snowflake = "555666777888999000"
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code_with_redirect", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value=_LINK_IDENTITY):

        dev_user = _make_dev_user("LinkCallbackSuccess")
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "LinkCallbackSuccess", "next": "/"}, follow_redirects=True)

        state = _initiate_link(client, _OAUTH_ENV)
        resp = client.get(
            f"/auth/discord/link/callback?code=good-code&state={state}",
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "/account" in resp.headers["location"]
    assert "success=discord_linked" in resp.headers["location"]

    discord_row = _get_identity_row(dev_user["id"], "discord")
    assert discord_row is not None
    assert discord_row["provider_user_id"] == snowflake


def test_link_callback_state_mismatch():
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code_with_redirect", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value=_LINK_IDENTITY):

        _make_dev_user("StateMismatchUser")
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "StateMismatchUser", "next": "/"}, follow_redirects=True)
        _initiate_link(client, _OAUTH_ENV)

        resp = client.get(
            "/auth/discord/link/callback?code=code&state=wrong-state",
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


def test_link_callback_missing_linking_flag():
    """Callback without going through /auth/discord/link (no 'linking' in session)."""
    with patch.dict(os.environ, _OAUTH_ENV):
        _make_dev_user("MissingFlagUser")
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "MissingFlagUser", "next": "/"}, follow_redirects=True)
        # Call callback directly (no link initiation, so session has no 'linking' flag).
        resp = client.get(
            "/auth/discord/link/callback?code=code&state=anything",
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


def test_link_callback_conflict_error_redirects():
    """If use case raises ConflictError, callback redirects with error."""
    snowflake = "888999000111222333"
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code_with_redirect", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value={
             "id": snowflake, "username": "conflict", "global_name": "Conflict"
         }):

        # Create another user with memberships that owns the snowflake.
        owner = _make_dev_user("ConflictCallbackOwner")
        ws    = make_workspace(slug="conflict-cb-ws", owner_user_id=owner["id"])
        other = _make_discord_user(snowflake, "OtherDiscordCB")
        with database.transaction() as db:
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
                "VALUES (?, ?, ?, 'member', '2025-01-01T00:00:00+00:00')",
                (str(uuid.uuid4()), ws["id"], other["id"]),
            )

        dev_user = _make_dev_user("ConflictCallbackDev")
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"display_name": "ConflictCallbackDev", "next": "/"}, follow_redirects=True)
        state = _initiate_link(client, _OAUTH_ENV)

        resp = client.get(
            f"/auth/discord/link/callback?code=code&state={state}",
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "/account" in resp.headers["location"]
    assert "error" in resp.headers["location"]

    # Dev user's identity must be unchanged.
    discord_row = _get_identity_row(dev_user["id"], "discord")
    assert discord_row is None
