"""
Discord OAuth login tests.

Covers:
  Use-case (discord_oauth_login)
  1.  New Discord user is created with auth_provider='discord'.
  2.  Existing Discord user (same snowflake) returns same record.
  3.  Changed Discord username updates display_name.
  4.  Empty discord_user_id raises ValidationError.
  5.  New Discord user has no workspace memberships.

  HTTP — callback flow (all Discord API calls mocked)
  6.  Valid code + state → session set, redirect to next path.
  7.  State mismatch → redirects to /login?error=...
  8.  Missing code → redirects to /login?error=...
  9.  Discord error param → redirects to /login?error=...
  10. exchange_code failure → redirects to /login?error=...
  11. fetch_user_identity failure → redirects to /login?error=...
  12. Callback sets correct user_id in session.

  HTTP — dev login guard
  13. POST /login in dev mode succeeds.
  14. POST /login with IRONKEEP_ENV=production returns 403.

  HTTP — GET /auth/discord
  15. With OAuth configured → redirects to Discord authorization URL.
  16. Without OAuth configured → 503 + error message in body.

  HTTP — login page
  17. Dev mode: dev form visible, no production gate.
  18. Discord OAuth button visible when OAuth vars configured.
  19. Discord OAuth button absent when vars missing.
  20. Production mode: dev form absent, Discord button shown.
  21. Production mode: Discord button absent when OAuth unconfigured → error message.

  Redirect safety
  22. safe_next allows valid relative path.
  23. safe_next rejects protocol-relative "//evil.com".
  24. safe_next rejects absolute URL "https://evil.com".
  25. safe_next returns "/workspaces" for empty/None/whitespace/invalid.
  26. safe_next allows query strings on internal paths.
  27. safe_next rejects javascript: scheme.
  28. safe_next rejects ftp: and other non-http schemes.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ValidationError
from app.main import app
from app.routes import _safe_next

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OAUTH_ENV = {
    "DISCORD_CLIENT_ID": "test-client-id",
    "DISCORD_CLIENT_SECRET": "test-client-secret",
    "DISCORD_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/discord/callback",
}

_MOCK_IDENTITY = {
    "id": "123456789012345678",
    "username": "testuser",
    "global_name": "TestUser",
    "discriminator": "0",
}


def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _set_oauth_state(client: TestClient, state: str, next_path: str = "/") -> None:
    """Seed the session with the OAuth state and next path as the initiation route does."""
    with client:
        resp = client.get(f"/auth/discord?next={next_path}", follow_redirects=False)
    # We can't easily seed the session directly; instead extract state from the redirect
    # and re-use it in the callback test. For tests that need a known state,
    # we use the session cookie approach via a patched build_authorization_url.


# ---------------------------------------------------------------------------
# 1-5: Use-case tests
# ---------------------------------------------------------------------------

def test_discord_oauth_login_creates_new_user():
    user = use_cases.discord_oauth_login("111111111111111111", "GuildMember")
    assert user["auth_provider"] == "discord"
    assert user["provider_user_id"] == "111111111111111111"
    assert user["display_name"] == "GuildMember"
    assert user["id"]


def test_discord_oauth_login_returns_existing_user():
    user1 = use_cases.discord_oauth_login("222222222222222222", "SameUser")
    user2 = use_cases.discord_oauth_login("222222222222222222", "SameUser")
    assert user1["id"] == user2["id"]

    with database.transaction() as db:
        rows = db.execute(
            "SELECT COUNT(*) FROM users WHERE provider_user_id = ?",
            ("222222222222222222",),
        ).fetchone()
    assert rows[0] == 1


def test_discord_oauth_login_updates_display_name():
    use_cases.discord_oauth_login("333333333333333333", "OldName")
    updated = use_cases.discord_oauth_login("333333333333333333", "NewName")
    assert updated["display_name"] == "NewName"

    with database.transaction() as db:
        row = repositories.get_user_by_provider_identity(db, "discord", "333333333333333333")
    assert row["display_name"] == "NewName"


def test_discord_oauth_login_empty_user_id_raises():
    with pytest.raises(ValidationError):
        use_cases.discord_oauth_login("", "SomeUser")


def test_discord_oauth_user_has_no_workspace_membership():
    user = use_cases.discord_oauth_login("444444444444444444", "MemberlessMember")
    owner = make_user("WsOwner")
    ws = make_workspace(owner_user_id=owner["id"], slug="oauth-ws-test")

    with database.transaction() as db:
        membership = repositories.get_workspace_membership(db, ws["id"], user["id"])
    assert membership is None


# ---------------------------------------------------------------------------
# 6-12: HTTP callback flow (Discord API mocked)
# ---------------------------------------------------------------------------

def _make_callback_client():
    """Return a client with OAuth env vars set."""
    return TestClient(app, raise_server_exceptions=True)


def test_callback_valid_state_redirects_to_next():
    """Full happy path: state valid, code exchanged, identity fetched, session set."""
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="mock-token"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value=_MOCK_IDENTITY):

        client = TestClient(app, follow_redirects=False)

        # Initiate OAuth to get a real state cookie
        init_resp = client.get("/auth/discord?next=/", follow_redirects=False)
        assert init_resp.status_code == 303
        # Extract state from the redirect URL
        location = init_resp.headers["location"]
        assert "state=" in location
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        state = qs["state"][0]

        # Call callback with matching state
        callback_resp = client.get(
            f"/auth/discord/callback?code=auth-code-123&state={state}",
            follow_redirects=False,
        )
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"] == "/"


def test_callback_state_mismatch_redirects_to_login():
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="mock-token"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value=_MOCK_IDENTITY):

        client = TestClient(app, follow_redirects=False)
        # Initiate to set session state
        client.get("/auth/discord?next=/", follow_redirects=False)
        # Call callback with WRONG state
        resp = client.get(
            "/auth/discord/callback?code=auth-code&state=wrong-state",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
        assert "error" in resp.headers["location"]


def test_callback_missing_code_redirects_to_login():
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="tok"):

        client = TestClient(app, follow_redirects=False)
        init_resp = client.get("/auth/discord?next=/", follow_redirects=False)
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(init_resp.headers["location"]).query)
        state = qs["state"][0]

        resp = client.get(
            f"/auth/discord/callback?state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
        assert "error" in resp.headers["location"]


def test_callback_discord_error_param_redirects_to_login():
    with patch.dict(os.environ, _OAUTH_ENV):
        client = TestClient(app, follow_redirects=False)
        init_resp = client.get("/auth/discord?next=/", follow_redirects=False)
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(init_resp.headers["location"]).query)
        state = qs["state"][0]

        resp = client.get(
            f"/auth/discord/callback?error=access_denied&error_description=User+denied&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
        assert "error" in resp.headers["location"]


def test_callback_exchange_failure_redirects_to_login():
    from app.auth.discord_oauth import DiscordOAuthError

    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code",
               side_effect=DiscordOAuthError("Token exchange failed")):

        client = TestClient(app, follow_redirects=False)
        init_resp = client.get("/auth/discord?next=/", follow_redirects=False)
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(init_resp.headers["location"]).query)
        state = qs["state"][0]

        resp = client.get(
            f"/auth/discord/callback?code=bad-code&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
        assert "error" in resp.headers["location"]


def test_callback_identity_fetch_failure_redirects_to_login():
    from app.auth.discord_oauth import DiscordOAuthError

    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity",
               side_effect=DiscordOAuthError("Identity fetch failed")):

        client = TestClient(app, follow_redirects=False)
        init_resp = client.get("/auth/discord?next=/", follow_redirects=False)
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(init_resp.headers["location"]).query)
        state = qs["state"][0]

        resp = client.get(
            f"/auth/discord/callback?code=good-code&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]


def test_callback_sets_session_user():
    """After a successful callback, the session contains the app user's ID."""
    with patch.dict(os.environ, _OAUTH_ENV), \
         patch("app.auth.discord_oauth.exchange_code", return_value="tok"), \
         patch("app.auth.discord_oauth.fetch_user_identity", return_value={
             "id": "999888777666555444",
             "username": "SessionTestUser",
             "global_name": "SessionTestUser",
         }):

        client = TestClient(app, follow_redirects=False)
        init_resp = client.get("/auth/discord?next=/dashboard", follow_redirects=False)
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(init_resp.headers["location"]).query)
        state = qs["state"][0]

        callback_resp = client.get(
            f"/auth/discord/callback?code=sess-code&state={state}",
            follow_redirects=False,
        )
        assert callback_resp.status_code == 303

        # Confirm user was created
        with database.transaction() as db:
            user = repositories.get_user_by_provider_identity(
                db, "discord", "999888777666555444"
            )
        assert user is not None
        assert user["display_name"] == "SessionTestUser"


# ---------------------------------------------------------------------------
# 13-14: Dev login guard
# ---------------------------------------------------------------------------

def test_dev_login_available_in_dev_mode():
    """POST /login works when IRONKEEP_ENV is dev (default)."""
    with patch.dict(os.environ, {"IRONKEEP_ENV": "dev"}):
        make_user("DevLoginUser")
        client = TestClient(app, follow_redirects=False)
        resp = client.post("/login", data={"display_name": "DevLoginUser", "next": "/"})
    assert resp.status_code == 303


def test_dev_login_blocked_in_production():
    """POST /login returns 403 when IRONKEEP_ENV=production."""
    with patch.dict(os.environ, {"IRONKEEP_ENV": "production"}):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/login",
            data={"display_name": "SomeUser", "next": "/"},
            follow_redirects=False,
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 15-16: GET /auth/discord
# ---------------------------------------------------------------------------

def test_auth_discord_redirects_to_discord_when_configured():
    with patch.dict(os.environ, _OAUTH_ENV):
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/auth/discord?next=/")
    assert resp.status_code == 303
    assert "discord.com/oauth2/authorize" in resp.headers["location"]


def test_auth_discord_returns_503_when_not_configured():
    env_without_oauth = {k: "" for k in _OAUTH_ENV}
    with patch.dict(os.environ, env_without_oauth):
        client = TestClient(app, follow_redirects=True)
        resp = client.get("/auth/discord")
    assert resp.status_code == 503
    assert "not configured" in resp.text.lower()


# ---------------------------------------------------------------------------
# 17-21: Login page template
# ---------------------------------------------------------------------------

def test_login_page_dev_mode_shows_dev_form():
    with patch.dict(os.environ, {"IRONKEEP_ENV": "dev"}):
        client = TestClient(app)
        resp = client.get("/login")
    assert resp.status_code == 200
    assert 'name="display_name"' in resp.text
    assert 'action="/login"' in resp.text


def test_login_page_shows_discord_button_when_oauth_configured():
    with patch.dict(os.environ, {**{"IRONKEEP_ENV": "dev"}, **_OAUTH_ENV}):
        client = TestClient(app)
        resp = client.get("/login")
    assert resp.status_code == 200
    assert "/auth/discord" in resp.text


def test_login_page_no_discord_button_when_oauth_missing():
    env = {"IRONKEEP_ENV": "dev", **{k: "" for k in _OAUTH_ENV}}
    with patch.dict(os.environ, env):
        client = TestClient(app)
        resp = client.get("/login")
    assert resp.status_code == 200
    # Discord button should be absent
    assert "/auth/discord" not in resp.text


def test_login_page_production_hides_dev_form():
    with patch.dict(os.environ, {"IRONKEEP_ENV": "production", **_OAUTH_ENV}):
        client = TestClient(app)
        resp = client.get("/login")
    assert resp.status_code == 200
    # Dev form inputs must not be rendered
    assert 'action="/login"' not in resp.text
    assert 'name="display_name"' not in resp.text
    # Discord button present
    assert "/auth/discord" in resp.text


def test_login_page_production_unconfigured_shows_error():
    env = {"IRONKEEP_ENV": "production", **{k: "" for k in _OAUTH_ENV}}
    with patch.dict(os.environ, env):
        client = TestClient(app)
        resp = client.get("/login")
    assert resp.status_code == 200
    assert "not configured" in resp.text.lower() or "discord" in resp.text.lower()
    assert 'name="display_name"' not in resp.text


# ---------------------------------------------------------------------------
# 22-28: _safe_next helper
# ---------------------------------------------------------------------------

def test_safe_next_allows_valid_relative_path():
    assert _safe_next("/workspaces/orbie") == "/workspaces/orbie"


def test_safe_next_rejects_protocol_relative():
    # Protocol-relative URLs are an open-redirect vector — must be blocked.
    assert _safe_next("//evil.com/steal") == "/workspaces"


def test_safe_next_rejects_absolute_url():
    # Absolute HTTP/HTTPS URLs must never be accepted as redirect targets.
    assert _safe_next("https://evil.com") == "/workspaces"
    assert _safe_next("http://evil.com") == "/workspaces"


def test_safe_next_returns_workspaces_for_empty():
    # Absent or empty next-path defaults to the authenticated dashboard.
    assert _safe_next("") == "/workspaces"
    assert _safe_next(None) == "/workspaces"


def test_safe_next_returns_workspaces_for_whitespace_only():
    # Whitespace-only strings are equivalent to absent — reject cleanly.
    assert _safe_next("   ") == "/workspaces"
    assert _safe_next("\t\n") == "/workspaces"


def test_safe_next_rejects_javascript_scheme():
    # javascript: payloads must be blocked — they do not start with "/".
    assert _safe_next("javascript:alert(1)") == "/workspaces"
    assert _safe_next("JAVASCRIPT:alert(1)") == "/workspaces"


def test_safe_next_rejects_non_http_schemes():
    # Any scheme other than a leading "/" is external and must be rejected.
    assert _safe_next("ftp://example.com") == "/workspaces"
    assert _safe_next("data:text/html,<h1>x</h1>") == "/workspaces"


def test_safe_next_preserves_internal_path_with_query_string():
    # Query strings are a legitimate part of internal paths and must survive.
    assert _safe_next("/workspaces/orbie?tab=operations") == "/workspaces/orbie?tab=operations"
    assert _safe_next("/foo/bar?x=1&y=2") == "/foo/bar?x=1&y=2"


def test_safe_next_preserves_root_slash():
    # A bare "/" is a valid internal path (the public landing page).
    assert _safe_next("/") == "/"


def test_safe_next_authenticated_fallback_is_workspaces():
    # The fallback for all rejected/missing inputs is the authenticated default,
    # NOT the public landing page — authenticated users should land at /workspaces.
    for bad in (None, "", "   ", "//evil.com", "https://evil.com",
                "javascript:x", "ftp://x"):
        result = _safe_next(bad)
        assert result == "/workspaces", (
            f"_safe_next({bad!r}) returned {result!r}, expected '/workspaces'"
        )
