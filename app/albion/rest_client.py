"""
Albion Online REST client.

Pure HTTP layer — no SQLite, no Discord, no domain imports.

Base URL: https://gameinfo.albiononline.com/api/gameinfo

Rate limit: 1 request per second (lightweight token-bucket via threading lock).
Timeout:    5 seconds per request.
Errors:     AlbionApiError on timeout or non-200 HTTP status.
Retries:    none inside this module — callers decide.
"""

from __future__ import annotations

import json
import threading
import time

import httpx

_BASE_URL = "https://gameinfo.albiononline.com/api/gameinfo"
_TIMEOUT = 5.0  # seconds

# ---------------------------------------------------------------------------
# Lightweight 1 req/s rate limiter
# ---------------------------------------------------------------------------
_rate_lock = threading.Lock()
_last_call_at: float = 0.0
_MIN_INTERVAL: float = 1.0  # 1 request per second


def _rate_limit() -> None:
    """Block until at least 1 second has elapsed since the last API call."""
    global _last_call_at
    with _rate_lock:
        elapsed = time.monotonic() - _last_call_at
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_call_at = time.monotonic()


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class AlbionApiError(Exception):
    """Raised when the Albion API returns a non-200 response or times out."""


# ---------------------------------------------------------------------------
# Internal HTTP helper
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> dict | list:
    _rate_limit()
    url = f"{_BASE_URL}{path}"
    try:
        response = httpx.get(url, params=params, timeout=_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise AlbionApiError(f"Albion API timed out: {path}") from exc
    except httpx.RequestError as exc:
        raise AlbionApiError(f"Albion API request error: {exc}") from exc
    if response.status_code != 200:
        raise AlbionApiError(
            f"Albion API returned HTTP {response.status_code} for {path}"
        )
    return response.json()


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_player(raw: dict) -> dict:
    """Convert a raw API player record to a clean internal dict."""
    return {
        "albion_player_id": raw.get("Id") or raw.get("id") or "",
        "character_name":   raw.get("Name") or raw.get("name") or "",
        "guild_id":         raw.get("GuildId") or raw.get("guildId"),
        "guild_name":       raw.get("GuildName") or raw.get("guildName"),
        "kill_fame":        raw.get("KillFame") or raw.get("killFame"),
        "death_fame":       raw.get("DeathFame") or raw.get("deathFame"),
        "extra_json":       json.dumps(raw),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_albion_characters(name: str) -> list[dict]:
    """
    Search for Albion players by (partial) name.

    Returns a list of normalised player dicts — may be empty.
    Raises AlbionApiError on HTTP error or timeout.
    """
    raw = _get("/players/search", params={"q": name})
    if not isinstance(raw, list):
        return []
    return [_normalise_player(p) for p in raw if p.get("Id") or p.get("id")]


def fetch_albion_character(albion_player_id: str) -> dict:
    """
    Fetch a single Albion player by stable player ID.

    Returns a normalised player dict.
    Raises AlbionApiError on HTTP error, timeout, or missing data.
    """
    raw = _get(f"/players/{albion_player_id}")
    if not isinstance(raw, dict):
        raise AlbionApiError(
            f"Unexpected response type for player {albion_player_id}"
        )
    result = _normalise_player(raw)
    if not result["albion_player_id"]:
        raise AlbionApiError(f"Player ID missing from response for {albion_player_id}")
    return result
