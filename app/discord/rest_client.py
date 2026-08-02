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


#: Discord channel types offered as an announcement destination.
#: Plain text channels only (0 = GUILD_TEXT).  Announcement/news channels (5)
#: are postable too but are deliberately left out: their messages can be
#: published to following servers, which is not what a guild operation post is
#: for.  Voice, stage, category, forum and media types cannot take a plain
#: message POST at all.
POSTABLE_CHANNEL_TYPES: frozenset[int] = frozenset({0})


def fetch_guild_channels(guild_id: str) -> list[dict]:
    """
    List the channels an announcement can be posted into.

    Returns channels of POSTABLE_CHANNEL_TYPES ordered the way Discord shows
    them (category position, then channel position), each as:
      id, name, channel_type, parent_id

    Unlike fetch_channel_metadata this needs no channel ID up front, which is
    what lets an officer pick a channel from a list instead of pasting a
    snowflake.  Requires only that the bot is a guild member — no privileged
    intent.

    Raises DiscordApiError on non-2xx or timeout.  Callers must treat failure
    as non-fatal and fall back to whatever is already cached.
    """
    try:
        resp = httpx.get(
            f"{_API_BASE}/guilds/{guild_id}/channels",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Guild channel fetch timed out after {_TIMEOUT}s. "
            "Discord may be temporarily unavailable.",
        )
    _raise_for_status(resp)

    raw = resp.json()
    # Category positions order the groups; a channel's own position orders it
    # within its group.  Categories are type 4 and are never postable.
    category_position = {
        str(c.get("id")): c.get("position") or 0
        for c in raw
        if c.get("type") == 4
    }

    channels = [
        {
            "id":           str(c.get("id")),
            "name":         c.get("name") or "",
            "channel_type": c.get("type", 0),
            "parent_id":    str(c["parent_id"]) if c.get("parent_id") else None,
        }
        for c in raw
        if c.get("type") in POSTABLE_CHANNEL_TYPES
    ]
    position = {
        str(c.get("id")): c.get("position") or 0
        for c in raw
    }
    channels.sort(key=lambda c: (
        category_position.get(c["parent_id"], -1) if c["parent_id"] else -1,
        position.get(c["id"], 0),
        c["name"],
    ))
    return channels


def fetch_guild_roles(guild_id: str) -> list[dict]:
    """
    List the roles an announcement can ping, highest first.

    Returns each role as: id, name, position, mentionable, color

    ``color`` is Discord's packed RGB integer, 0 meaning "no colour set".

    Excluded:
      - @everyone, whose role ID equals the guild ID — pinging it is never a
        content-role decision and would be catastrophic by accident.
      - managed roles (bot and integration roles), which no member self-assigns.

    ``mentionable`` is reported but not filtered on: a bot with Mention Everyone
    permission can ping a non-mentionable role, so hiding those would remove
    valid options.  Requires no privileged intent.

    Raises DiscordApiError on non-2xx or timeout.  Callers must treat failure as
    non-fatal and fall back to whatever is already cached.
    """
    try:
        resp = httpx.get(
            f"{_API_BASE}/guilds/{guild_id}/roles",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Guild role fetch timed out after {_TIMEOUT}s. "
            "Discord may be temporarily unavailable.",
        )
    _raise_for_status(resp)

    roles = [
        {
            "id":          str(r.get("id")),
            "name":        r.get("name") or "",
            "position":    r.get("position") or 0,
            "mentionable": bool(r.get("mentionable")),
            "color":       int(r.get("color") or 0),
        }
        for r in resp.json()
        if str(r.get("id")) != str(guild_id) and not r.get("managed")
    ]
    # Discord's own ordering: highest position first, as shown in server settings.
    roles.sort(key=lambda r: (-r["position"], r["name"]))
    return roles


def fetch_guild_members(guild_id: str, *, page_limit: int = 1000, max_pages: int = 20) -> list[dict]:
    """
    Fetch the full member list of a Discord guild, including server nicknames.

    Uses GET /guilds/{id}/members with snowflake pagination (`after`). Each page
    returns up to `page_limit` members (Discord max is 1000). Stops when a short
    page is returned or `max_pages` is reached (safety cap: 20 * 1000 = 20k).

    IMPORTANT: this endpoint requires the privileged **Server Members Intent**
    (GUILD_MEMBERS) to be enabled for the bot application in the Discord
    Developer Portal. Without it Discord returns 403 and this raises
    DiscordApiError — callers treat that as non-fatal.

    Returns a list of normalized dicts:
      {
        "discord_user_id": str,   # never None
        "nickname":        str | None,   # per-server nick
        "global_name":     str | None,   # account display name
        "username":        str | None,   # legacy username
      }
    Bot accounts are skipped.
    """
    members: list[dict] = []
    after = "0"
    for _ in range(max_pages):
        try:
            resp = httpx.get(
                f"{_API_BASE}/guilds/{guild_id}/members",
                headers=_headers(),
                params={"limit": page_limit, "after": after},
                timeout=15.0,  # member lists can be large / slow
            )
        except httpx.TimeoutException:
            raise DiscordApiError(
                0,
                f"Guild member fetch timed out. Discord may be temporarily unavailable.",
            )
        _raise_for_status(resp)
        page = resp.json()
        if not isinstance(page, list) or not page:
            break

        for m in page:
            user = m.get("user") or {}
            uid = user.get("id")
            if not uid or user.get("bot"):
                continue
            members.append({
                "discord_user_id": str(uid),
                "nickname":        m.get("nick"),
                "global_name":     user.get("global_name"),
                "username":        user.get("username"),
            })

        # Advance the cursor to the highest snowflake seen this page. Compare as
        # integers — snowflakes vary in length so string max() would be wrong.
        after = str(max(int(m.get("user", {}).get("id") or 0) for m in page))
        if len(page) < page_limit:
            break

    return members


#: Threads Discord archives after a week of inactivity.  An operation thread is
#: only interesting until the fight happens, so the shortest useful window keeps
#: channel thread lists from filling up with finished operations.
THREAD_AUTO_ARCHIVE_MINUTES = 1440  # 24 hours


def start_message_thread(channel_id: str, message_id: str, name: str) -> str:
    """
    Start a thread hanging off an existing message and return its channel ID.

    Discord gives a message-started thread the *same* snowflake as its source
    message, so the returned ID always equals ``message_id``.  It is returned
    anyway so callers read like ordinary channel plumbing rather than relying on
    that identity.

    Raises DiscordApiError, including 400 when a thread already exists on the
    message — callers that only want "a thread to post in" should use
    post_thread_message(), which handles that case.
    """
    try:
        resp = httpx.post(
            f"{_API_BASE}/channels/{channel_id}/messages/{message_id}/threads",
            headers=_headers(),
            json={
                "name": name[:100],  # Discord rejects thread names over 100 chars
                "auto_archive_duration": THREAD_AUTO_ARCHIVE_MINUTES,
            },
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Thread creation timed out after {_TIMEOUT}s. "
            "Discord may be temporarily unavailable.",
        )
    _raise_for_status(resp)
    return str(resp.json()["id"])


def post_thread_message(
    channel_id: str,
    message_id: str,
    thread_name: str,
    payload: dict,
) -> str:
    """
    Post into the thread on a message, starting that thread if it has none.

    Tries the thread first because after the first post it always exists, which
    makes the common path a single request.  Discord answers 404 for a thread
    that was never started (the snowflake addresses no channel), and that is the
    only failure worth retrying as "create, then post" — a 403 means missing
    permissions and must surface unchanged.

    Returns the Discord message ID of the posted message.
    """
    try:
        return post_message(message_id, payload)
    except DiscordApiError as exc:
        if exc.status_code != 404:
            raise
    start_message_thread(channel_id, message_id, thread_name)
    return post_message(message_id, payload)


def open_dm_channel(user_id: str) -> str:
    """
    Open (or reuse) the bot's DM channel with a user and return its channel ID.

    Discord treats this as idempotent: repeated calls for the same recipient
    return the same channel, so there is nothing to cache.  Note that success
    here says nothing about being *allowed* to send — a user who blocks DMs from
    server members still yields a channel, and the later post_message fails with
    403.  Callers must handle that separately.
    """
    try:
        resp = httpx.post(
            f"{_API_BASE}/users/@me/channels",
            headers=_headers(),
            json={"recipient_id": str(user_id)},
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise DiscordApiError(
            0,
            f"Opening a DM channel timed out after {_TIMEOUT}s. "
            "Discord may be temporarily unavailable.",
        )
    _raise_for_status(resp)
    return str(resp.json()["id"])


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
