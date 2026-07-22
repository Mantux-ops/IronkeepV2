"""
Albion Online REST client.

Pure HTTP layer — no SQLite, no Discord, no domain imports.

Base URL: https://gameinfo.albiononline.com/api/gameinfo

Rate limit: 1 request per second (lightweight token-bucket via threading lock).
Timeout:    15 seconds per request (the Albion gameinfo API is frequently slow;
            search in particular can take ~8s+). Search uses a longer timeout.
Errors:     AlbionApiError on timeout or non-200 HTTP status.
Retries:    none inside this module — callers decide.
"""

from __future__ import annotations

import json
import re
import threading
import time

import httpx

_BASE_URL = "https://gameinfo.albiononline.com/api/gameinfo"
_TIMEOUT = 15.0         # seconds — default per-request timeout
_SEARCH_TIMEOUT = 25.0  # seconds — /search is notably slower than other endpoints

# ---------------------------------------------------------------------------
# Known Albion server API base URLs.
# The same guild name can exist on different servers; IDs are server-specific.
# Note: regional availability depends on Albion Online's infrastructure.
# ---------------------------------------------------------------------------
#
# IMPORTANT: the host suffix does NOT correspond to the region name.
# Albion's live server hosts are:
#   - https://gameinfo.albiononline.com      -> Americas (West)   [no suffix]
#   - https://gameinfo-ams.albiononline.com  -> Europe (Amsterdam)
#   - https://gameinfo-sgp.albiononline.com  -> Asia (Singapore)
# (A previous version had europe/americas swapped, which made every Europe
#  search hit the Americas server and silently return no/incorrect results.)
ALBION_SERVERS: dict[str, str] = {
    "americas": "https://gameinfo.albiononline.com/api/gameinfo",
    "europe":   "https://gameinfo-ams.albiononline.com/api/gameinfo",
    "asia":     "https://gameinfo-sgp.albiononline.com/api/gameinfo",
}
ALBION_SERVER_LABELS: dict[str, str] = {
    "europe":   "Europe",
    "americas": "Americas",
    "asia":     "Asia",
}
_DEFAULT_SERVER = "europe"

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

def _get(path: str, params: dict | None = None,
         timeout: float = _TIMEOUT, server: str = _DEFAULT_SERVER) -> dict | list:
    base = ALBION_SERVERS.get(server) or ALBION_SERVERS[_DEFAULT_SERVER]
    _rate_limit()
    url = f"{base}{path}"
    try:
        response = httpx.get(url, params=params, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise AlbionApiError(f"Albion API timed out: {path}") from exc
    except httpx.RequestError as exc:
        raise AlbionApiError(f"Albion API request error: {exc}") from exc
    if response.status_code != 200:
        raise AlbionApiError(
            f"Albion API returned HTTP {response.status_code} for {path}"
        )
    return response.json()


def _get_from(base_url: str, path: str, params: dict | None = None,
              timeout: float = _TIMEOUT) -> dict | list:
    """Like _get() but queries *base_url* instead of the module-level _BASE_URL."""
    _rate_limit()
    url = f"{base_url}{path}"
    try:
        response = httpx.get(url, params=params, timeout=timeout)
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

def _normalise_guild(raw: dict) -> dict:
    """Convert a raw API guild record to a clean internal dict."""
    return {
        "albion_guild_id": raw.get("Id") or raw.get("id") or "",
        "guild_name":      raw.get("Name") or raw.get("name") or "",
        "alliance_id":     raw.get("AllianceId") or raw.get("allianceId") or None,
        "alliance_name":   raw.get("AllianceName") or raw.get("allianceName") or None,
        "member_count":    raw.get("MemberCount") or raw.get("memberCount") or 0,
        "extra_json":      json.dumps(raw),
    }


# ---------------------------------------------------------------------------
# Public API — guild endpoints
# ---------------------------------------------------------------------------

def search_albion_guilds(name: str, server: str = _DEFAULT_SERVER) -> list[dict]:
    """
    Search for Albion guilds by (partial) name on the given server.

    *server* must be one of the keys in ALBION_SERVERS ("europe", "americas",
    "asia").  Defaults to "europe" (the original base URL).  Unknown server
    keys fall back to "europe".

    Uses the Albion gameinfo ``/search`` endpoint, which returns an object of
    the form ``{"guilds": [...], "players": [...]}``.  (There is no
    ``/guilds/search`` endpoint — that path hangs.)  Only the guilds array is
    used here.  Note: search results do not include member counts.

    Each returned dict includes a "server" field set to the queried server key
    so callers can display which server the result came from.

    Returns a list of normalised guild dicts — may be empty.
    Raises AlbionApiError on HTTP error or timeout.
    """
    base = ALBION_SERVERS.get(server) or ALBION_SERVERS[_DEFAULT_SERVER]
    raw = _get_from(base, "/search", params={"q": name}, timeout=_SEARCH_TIMEOUT)
    # The /search endpoint returns {"guilds": [...], "players": [...]}.
    # Fall back gracefully for other shapes (and for tests that mock a raw list).
    if isinstance(raw, dict):
        guilds_raw = raw.get("guilds") or raw.get("Guilds") or []
    elif isinstance(raw, list):
        guilds_raw = raw
    else:
        return []
    results = [_normalise_guild(g) for g in guilds_raw if g.get("Id") or g.get("id")]
    for r in results:
        r["server"] = server
    return results


# Albion internal IDs are exactly 22 URL-safe base64 characters, e.g.
# "bkH9XhQFRFG5gcoOLJgSoQ".  Used to tell "this input is a guild ID" apart
# from "this input is a guild name" in the import/preview flow.
_ALBION_ID_RE = re.compile(r"[A-Za-z0-9_-]{22}")


def looks_like_albion_id(value: str) -> bool:
    """True when *value* looks like a raw Albion entity ID (22 base64url chars)."""
    return bool(_ALBION_ID_RE.fullmatch((value or "").strip()))


def fetch_albion_guild(guild_id: str, server: str = _DEFAULT_SERVER) -> dict:
    """
    Fetch a single Albion guild directly by its stable guild ID via /guilds/{id}.

    Unlike name search, this always finds the guild if the ID is valid, so it is
    the reliable path for guilds the Albion /search index does not return.

    Returns a normalised guild dict (with a "server" field).
    Raises AlbionApiError on HTTP error, timeout, or missing guild ID.
    """
    base = ALBION_SERVERS.get(server) or ALBION_SERVERS[_DEFAULT_SERVER]
    raw = _get_from(base, f"/guilds/{guild_id}")
    if not isinstance(raw, dict):
        raise AlbionApiError(f"Unexpected response type for guild {guild_id}")
    result = _normalise_guild(raw)
    if not result["albion_guild_id"]:
        raise AlbionApiError(f"Guild ID missing from response for {guild_id}")
    result["server"] = server
    return result


def fetch_albion_guild_members(guild_id: str,
                               server: str = _DEFAULT_SERVER) -> list[dict]:
    """
    Fetch all current members of an Albion guild by stable guild ID.

    *server* selects which regional Albion server to query and MUST match the
    server the guild lives on, otherwise the API returns 404/empty.

    Returns a list of normalised player dicts — may be empty for guilds
    that exist but have no members.
    Raises AlbionApiError on HTTP error, timeout, or unexpected response.
    """
    raw = _get(f"/guilds/{guild_id}/members", server=server)
    if not isinstance(raw, list):
        raise AlbionApiError(
            f"Unexpected response type for guild members {guild_id}"
        )
    return [_normalise_player(p) for p in raw if p.get("Id") or p.get("id")]


# ---------------------------------------------------------------------------
# Public API — alliance endpoints
# ---------------------------------------------------------------------------

def _normalise_alliance(raw: dict) -> dict:
    """
    Convert a raw /alliances/{id} API response to a clean internal dict.

    The Guilds array in the response contains basic guild stubs (Id + Name).
    Member counts are NOT available here — fetching them would require one
    /guilds/{id} call per guild (N+1).  Callers should display them only when
    already stored locally.
    """
    guilds_raw = raw.get("Guilds") or raw.get("guilds") or []
    guilds = [
        {
            "albion_guild_id": g.get("Id") or g.get("id") or "",
            "guild_name":      g.get("Name") or g.get("name") or "",
        }
        for g in guilds_raw
        if g.get("Id") or g.get("id")
    ]
    return {
        "alliance_id":   raw.get("Id") or raw.get("id") or "",
        "alliance_name": raw.get("AllianceName") or raw.get("allianceName") or "",
        "alliance_tag":  raw.get("AllianceTag") or raw.get("allianceTag") or "",
        "founded_at":    raw.get("Founded") or raw.get("founded"),
        "num_players":   raw.get("NumPlayers") or raw.get("numPlayers") or 0,
        "guilds":        guilds,
    }


def fetch_albion_alliance(alliance_id: str, server: str = _DEFAULT_SERVER) -> dict:
    """
    Fetch alliance metadata and its member guild list from the Albion API.

    *server* must be one of the keys in ALBION_SERVERS.  Defaults to "europe".

    Returns a normalised alliance dict:
        {
          "alliance_id":   str,
          "alliance_name": str,
          "alliance_tag":  str,
          "founded_at":    str | None,
          "num_players":   int,
          "guilds":        [{"albion_guild_id": str, "guild_name": str}, ...],
          "server":        str,
        }

    Raises AlbionApiError on HTTP error, timeout, or missing alliance ID.
    """
    base = ALBION_SERVERS.get(server) or ALBION_SERVERS[_DEFAULT_SERVER]
    raw = _get_from(base, f"/alliances/{alliance_id}")
    if not isinstance(raw, dict):
        raise AlbionApiError(
            f"Unexpected response type for alliance {alliance_id}"
        )
    result = _normalise_alliance(raw)
    if not result["alliance_id"]:
        raise AlbionApiError(
            f"Alliance ID missing from response for {alliance_id}"
        )
    result["server"] = server
    return result


# ---------------------------------------------------------------------------
# Public API — player endpoints
# ---------------------------------------------------------------------------

def search_albion_characters(name: str,
                             server: str = _DEFAULT_SERVER) -> list[dict]:
    """
    Search for Albion players by (partial) name on the given *server*.

    Returns a list of normalised player dicts — may be empty.
    Raises AlbionApiError on HTTP error or timeout.
    """
    raw = _get("/search", params={"q": name}, timeout=_SEARCH_TIMEOUT, server=server)
    # /search returns {"guilds": [...], "players": [...]}.
    if isinstance(raw, dict):
        players_raw = raw.get("players") or raw.get("Players") or []
    elif isinstance(raw, list):
        players_raw = raw
    else:
        return []
    return [_normalise_player(p) for p in players_raw if p.get("Id") or p.get("id")]


def fetch_albion_character(albion_player_id: str,
                           server: str = _DEFAULT_SERVER) -> dict:
    """
    Fetch a single Albion player by stable player ID on the given *server*.

    Returns a normalised player dict.
    Raises AlbionApiError on HTTP error, timeout, or missing data.
    """
    raw = _get(f"/players/{albion_player_id}", server=server)
    if not isinstance(raw, dict):
        raise AlbionApiError(
            f"Unexpected response type for player {albion_player_id}"
        )
    result = _normalise_player(raw)
    if not result["albion_player_id"]:
        raise AlbionApiError(f"Player ID missing from response for {albion_player_id}")
    return result
