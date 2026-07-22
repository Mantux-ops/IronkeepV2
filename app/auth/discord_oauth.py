"""
Discord OAuth2 HTTP helpers.

Thin httpx wrapper for the two Discord OAuth endpoints needed:
  1. Token exchange  — POST /oauth2/token
  2. Identity fetch  — GET  /users/@me

Rules:
- No Discord SDK.
- 5-second timeout on every request.
- Non-2xx responses raise DiscordOAuthError.
- httpx.TimeoutException also raises DiscordOAuthError.
- No state management — callers own the state/session flow.
- No database access.

Environment variables read at call time (not at import):
  DISCORD_CLIENT_ID
  DISCORD_CLIENT_SECRET
  DISCORD_OAUTH_REDIRECT_URI
"""

from __future__ import annotations

import os

import httpx

from app.errors import IronkeepError

_DISCORD_API = "https://discord.com/api/v10"
_TOKEN_URL   = "https://discord.com/api/oauth2/token"
_TIMEOUT     = 5.0  # seconds — never hang indefinitely


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class DiscordOAuthError(IronkeepError):
    """Raised when the Discord OAuth flow fails (network, timeout, non-2xx)."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Discord OAuth error: {message}")


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def _oauth_config() -> tuple[str, str, str]:
    """
    Return (client_id, client_secret, redirect_uri) from env.
    Raises DiscordOAuthError with a user-visible message if any are missing.
    """
    client_id     = os.environ.get("DISCORD_CLIENT_ID", "").strip()
    client_secret = os.environ.get("DISCORD_CLIENT_SECRET", "").strip()
    redirect_uri  = os.environ.get("DISCORD_OAUTH_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise DiscordOAuthError(
            "Discord OAuth is not configured on this server. "
            "Set DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and "
            "DISCORD_OAUTH_REDIRECT_URI environment variables."
        )
    return client_id, client_secret, redirect_uri


def is_oauth_configured() -> bool:
    """Return True if all three OAuth env vars are present and non-empty."""
    return all([
        os.environ.get("DISCORD_CLIENT_ID", "").strip(),
        os.environ.get("DISCORD_CLIENT_SECRET", "").strip(),
        os.environ.get("DISCORD_OAUTH_REDIRECT_URI", "").strip(),
    ])


def build_authorization_url(state: str) -> str:
    """
    Build the Discord OAuth2 authorization URL.

    Requests the `identify` and `guilds` scopes:
      - identify: the user's Discord id + display name (no email).
      - guilds:   read-only list of servers the user is a member of, used to
                  auto-grant workspace access for any server that has Ironkeep.
    """
    from urllib.parse import urlencode  # noqa: PLC0415
    client_id, _secret, redirect_uri = _oauth_config()
    params = urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "identify guilds",
        "state":         state,
    })
    return f"https://discord.com/oauth2/authorize?{params}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _do_token_exchange(code: str, redirect_uri: str) -> str:
    """Shared token exchange logic for both login and link flows."""
    client_id, client_secret, _ = _oauth_config()
    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordOAuthError(
            f"Token exchange timed out after {_TIMEOUT}s. Discord may be unavailable."
        )
    if not resp.is_success:
        body = resp.text[:200].strip()
        raise DiscordOAuthError(
            f"Token exchange failed ({resp.status_code}): {body or '(no body)'}"
        )
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        raise DiscordOAuthError("Token exchange response missing access_token.")
    return token


def exchange_code(code: str) -> str:
    """
    Exchange an authorization code for an access token (login flow).

    Uses DISCORD_OAUTH_REDIRECT_URI.
    Returns the access token string.
    Raises DiscordOAuthError on any failure.
    """
    _, _, redirect_uri = _oauth_config()
    return _do_token_exchange(code, redirect_uri)


def exchange_code_with_redirect(code: str, redirect_uri: str) -> str:
    """
    Exchange an authorization code using an explicit redirect_uri.

    Used by the account linking flow where DISCORD_OAUTH_LINK_REDIRECT_URI
    differs from the login redirect URI.
    Raises DiscordOAuthError if redirect_uri is empty or exchange fails.
    """
    if not redirect_uri or not redirect_uri.strip():
        raise DiscordOAuthError(
            "DISCORD_OAUTH_LINK_REDIRECT_URI is not configured."
        )
    return _do_token_exchange(code, redirect_uri.strip())


def fetch_user_identity(access_token: str) -> dict:
    """
    Fetch the authenticated user's Discord identity using a Bearer token.

    Returns a dict with at least:
      id            — Discord user snowflake (stable, never changes)
      username      — Discord username
      global_name   — Display name (may be None on older accounts)
      discriminator — Legacy discriminator (may be "0" for new usernames)

    Raises DiscordOAuthError on any failure or if `id` is absent.
    """
    try:
        resp = httpx.get(
            f"{_DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordOAuthError(
            f"Identity fetch timed out after {_TIMEOUT}s. Discord may be unavailable."
        )
    if not resp.is_success:
        body = resp.text[:200].strip()
        raise DiscordOAuthError(
            f"Identity fetch failed ({resp.status_code}): {body or '(no body)'}"
        )
    data = resp.json()
    if not data.get("id"):
        raise DiscordOAuthError("Discord identity response missing user id.")
    return data


def fetch_user_guilds(access_token: str) -> list[dict]:
    """
    Fetch the list of Discord servers (guilds) the authenticated user belongs to.

    Requires the `guilds` OAuth scope. Returns the raw list of guild dicts, each
    containing at least:
      id    — Discord guild (server) snowflake
      name  — server name

    Returns an empty list if the token lacks the `guilds` scope or the account
    is in no servers. Raises DiscordOAuthError on network/timeout/non-2xx so the
    caller can decide whether to treat guild sync as best-effort.
    """
    try:
        resp = httpx.get(
            f"{_DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordOAuthError(
            f"Guild list fetch timed out after {_TIMEOUT}s. Discord may be unavailable."
        )
    if not resp.is_success:
        body = resp.text[:200].strip()
        raise DiscordOAuthError(
            f"Guild list fetch failed ({resp.status_code}): {body or '(no body)'}"
        )
    data = resp.json()
    if not isinstance(data, list):
        return []
    return data
