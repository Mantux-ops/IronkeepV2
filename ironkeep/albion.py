"""Public Albion Online gameinfo lookups for trial fame and guild membership.

Fame during a trial is the gain between lifetime snapshots. Albion does not publish
the numbers from before the first snapshot.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from . import db

log = logging.getLogger("ironkeep.albion")

HOSTS = {
    "europe": "https://gameinfo-ams.albiononline.com",
    "americas": "https://gameinfo-west.albiononline.com",
    "asia": "https://gameinfo-east.albiononline.com",
}
STATS = ("pve", "pvp", "gathering", "crafting")


class AlbionError(Exception):
    def __init__(self, status):
        super().__init__(f"Albion HTTP {status}")
        self.status = status


def _get(region, path):
    host = HOSTS.get(region) or HOSTS["europe"]
    request = urllib.request.Request(
        host + path,
        headers={"User-Agent": "Ironkeep (https://ironkeep.gg, 0.1)", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise AlbionError(error.code) from error


def totals_from_player(player):
    life = (player or {}).get("LifetimeStatistics") or {}
    gathering = ((life.get("Gathering") or {}).get("All") or {}).get("Total") or 0
    return {
        "pve": int((life.get("PvE") or {}).get("Total") or 0),
        "pvp": int((player or {}).get("KillFame") or 0),
        "gathering": int(gathering),
        "crafting": int((life.get("Crafting") or {}).get("Total") or 0),
    }


def name_candidates(name):
    raw = (name or "").strip()
    found = []
    for part in [raw, *[raw.split(mark)[0].strip() for mark in ("|", "[", "(", "•") if mark in raw]]:
        if len(part) >= 3 and part.casefold() not in {item.casefold() for item in found}:
            found.append(part)
    return found


def record_snapshot(albion, player, today, watched_guild):
    """Fold one lifetime reading into daily fame and the guild flag."""
    totals = totals_from_player(player)
    point = {"date": today, **totals}
    history = list(albion.get("history") or [])
    if not history:
        history = [point]
    elif history[-1]["date"] == today and len(history) == 1:
        history.append(point)
    elif history[-1]["date"] == today:
        history[-1] = point
    else:
        history.append(point)
    albion = dict(albion)
    albion["history"] = history
    albion["lifetime"] = point
    albion["fame"] = _fame_days(history)
    albion["fame_since"] = albion.get("fame_since") or today
    albion["player_id"] = player.get("Id")
    guild_name = (player.get("GuildName") or "").strip()
    in_guild = bool(watched_guild) and guild_name.casefold() == watched_guild.casefold()
    if in_guild:
        albion["in_guild"] = True
        albion["last_in_guild"] = None
    elif albion.get("in_guild") is True:
        albion["in_guild"] = False
        albion["last_in_guild"] = today
    else:
        albion["in_guild"] = False
    albion["updated_at"] = db.now_stamp()
    return albion


def _fame_days(history):
    days = []
    for previous, current in zip(history, history[1:]):
        days.append(
            {
                "date": current["date"],
                **{key: max(0, int(current[key]) - int(previous[key])) for key in STATS},
            }
        )
    return days


def _exact(items, name):
    wanted = name.casefold()
    matches = [item for item in items or [] if (item.get("Name") or "").casefold() == wanted]
    return matches[0] if len(matches) == 1 else None


def find_player(region, name, guild_members):
    for candidate in name_candidates(name):
        found = _exact(guild_members, candidate)
        if found:
            return found
    for candidate in name_candidates(name):
        quoted = urllib.parse.quote(candidate)
        try:
            payload = _get(region, f"/api/gameinfo/search?q={quoted}")
        except AlbionError as error:
            if error.status == 429:
                raise
            log.warning("Albion search failed for a trial name: %s", error)
            return None
        found = _exact((payload or {}).get("players"), candidate)
        if found and found.get("LifetimeStatistics"):
            return found
        if found and found.get("Id"):
            try:
                return _get(region, f"/api/gameinfo/players/{found['Id']}")
            except AlbionError as error:
                if error.status == 429:
                    raise
                log.warning("Albion player lookup failed: %s", error)
                return None
    return None


def guild_members(region, guild_name):
    if not guild_name:
        return []
    quoted = urllib.parse.quote(guild_name)
    payload = _get(region, f"/api/gameinfo/search?q={quoted}")
    guild = _exact((payload or {}).get("guilds"), guild_name)
    if not guild or not guild.get("Id"):
        return []
    members = _get(region, f"/api/gameinfo/guilds/{guild['Id']}/members")
    return members if isinstance(members, list) else []


def refresh_open_trials():
    """Update every open trial that has an Albion name. Returns how many names matched."""
    matched = 0
    checked = 0
    for guild in db.list_guilds(with_trials=True):
        if guild["approval"] != "approved" or not guild["bot_present"]:
            continue
        settings = guild["settings"]
        albion_settings = settings.get("albion") or {}
        if not albion_settings.get("track_fame", True) and albion_settings.get("guild_check") == "off":
            continue
        region = albion_settings.get("region") or "europe"
        today = db.guild_today(settings).isoformat()
        watched = (albion_settings.get("guild_name") or "").strip()
        try:
            members = guild_members(region, watched)
        except AlbionError as error:
            log.warning("Could not read Albion guild %s: %s", watched or region, error)
            if error.status == 429:
                raise
            members = []
        for trial in guild["trials"]:
            if trial.get("verdict") or trial.get("left_server"):
                continue
            albion = trial.get("albion") or {}
            if not albion.get("name"):
                continue
            checked += 1
            try:
                player = find_player(region, albion["name"], members)
            except AlbionError as error:
                if error.status == 429:
                    raise
                log.warning("Albion lookup failed during refresh: %s", error)
                continue
            if not player:
                continue
            matched += 1
            db.save_albion(trial["id"], record_snapshot(albion, player, today, watched))
    log.info("Albion refresh matched %s of %s open trials", matched, checked)
    return matched, checked
