"""
Discord REST client — thin httpx wrapper over Discord API v10.

Rules:
- No Discord SDK imports.
- Token read from DISCORD_BOT_TOKEN environment variable on every call.
  The bot identity is swappable by changing the env var alone.
- All requests carry an explicit 5-second timeout so the web process
  never hangs indefinitely on a slow or unreachable Discord endpoint.
- Non-2xx responses raise DiscordApiError (an IronkeepError subclass)
  so callers and routes can handle them uniformly.
- httpx.TimeoutException also raises DiscordApiError with a clear message.
"""

from __future__ import annotations

import os

import httpx

from app.errors import IronkeepError

_API_BASE = "https://discord.com/api/v10"
_TIMEOUT  = 5.0   # seconds — web request must not hang indefinitely


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class DiscordApiError(IronkeepError):
    """
    Raised when the Discord REST API returns a non-2xx response or times out.

    Subclasses IronkeepError so routes catch it in their existing
    `except IronkeepError` handlers and display a user-visible flash error.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Discord API error {status_code}: {message}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise DiscordApiError(
            0,
            "DISCORD_BOT_TOKEN is not set. "
            "Configure the environment variable before posting to Discord.",
        )
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


def _raise_for_status(resp: httpx.Response) -> None:
    if not resp.is_success:
        # Truncate body so error messages stay readable in flash alerts.
        body = resp.text[:300].strip()
        raise DiscordApiError(resp.status_code, body or "(no body)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def post_message(channel_id: str, payload: dict) -> str:
    """
    POST a message to a Discord channel.

    Returns the Discord snowflake message ID (str) on success.
    Raises DiscordApiError on non-2xx response or timeout.
    """
    try:
        resp = httpx.post(
            f"{_API_BASE}/channels/{channel_id}/messages",
            headers=_headers(),
            json=payload,
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Request timed out after {_TIMEOUT}s. "
            "Discord may be temporarily unavailable.",
        )
    _raise_for_status(resp)
    return resp.json()["id"]


def fetch_guild_metadata(guild_id: str) -> dict:
    """
    Fetch guild (server) metadata for caching purposes.

    Returns a dict with at least:
      name       — human-readable server name
      icon_hash  — icon hash string or None (for future CDN URL construction)

    Raises DiscordApiError on non-2xx or timeout.
    Callers must treat failure as non-fatal — never roll back a domain write.
    """
    try:
        resp = httpx.get(
            f"{_API_BASE}/guilds/{guild_id}",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Guild metadata fetch timed out after {_TIMEOUT}s.",
        )
    _raise_for_status(resp)
    data = resp.json()
    return {
        "name":      data.get("name", ""),
        "icon_hash": data.get("icon"),  # None when no icon is set
    }


def fetch_channel_metadata(channel_id: str) -> dict:
    """
    Fetch channel metadata for caching purposes.

    Returns a dict with at least:
      name         — channel name (without leading #)
      channel_type — Discord channel type integer (0=text, 5=announcement, etc.)

    Raises DiscordApiError on non-2xx or timeout.
    """
    try:
        resp = httpx.get(
            f"{_API_BASE}/channels/{channel_id}",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Channel metadata fetch timed out after {_TIMEOUT}s.",
        )
    _raise_for_status(resp)
    data = resp.json()
    return {
        "name":         data.get("name", ""),
        "channel_type": data.get("type", 0),
    }


def edit_message(channel_id: str, message_id: str, payload: dict) -> None:
    """
    PATCH (edit) an existing Discord message.

    Raises DiscordApiError on non-2xx response or timeout.
    If Discord returns 404 (message deleted externally) the caller should
    fall back to post_message and save the new ID.
    """
    try:
        resp = httpx.patch(
            f"{_API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers=_headers(),
            json=payload,
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Request timed out after {_TIMEOUT}s. "
            "Discord may be temporarily unavailable.",
        )
    _raise_for_status(resp)
