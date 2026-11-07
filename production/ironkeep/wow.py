"""World of Warcraft raids. One server, one game. Signup happens in Discord."""

import logging
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

from . import config, db, discord_api, forever_companion, warcraft_forever

log = logging.getLogger("ironkeep.wow")

GAMES = [
    {
        "id": "albion",
        "name": "Albion Online",
        "summary": "Trials, fame, payout and lootsplit.",
    },
    {
        "id": "wow",
        "name": "World of Warcraft",
        "summary": "Raid signups in Discord, and the same list on this site.",
    },
]

TIMEZONES = [
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Berlin",
    "Europe/London",
    "Europe/Oslo",
    "Europe/Warsaw",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Asia/Singapore",
    "UTC",
]

CLASSES = [
    {
        "id": "warrior",
        "name": "Warrior",
        "specs": [
            {"id": "arms", "name": "Arms", "role": "dps"},
            {"id": "fury", "name": "Fury", "role": "dps"},
            {"id": "protection", "name": "Protection", "role": "tank"},
        ],
    },
    {
        "id": "paladin",
        "name": "Paladin",
        "specs": [
            {"id": "holy", "name": "Holy", "role": "healer"},
            {"id": "protection", "name": "Protection", "role": "tank"},
            {"id": "retribution", "name": "Retribution", "role": "dps"},
        ],
    },
    {
        "id": "hunter",
        "name": "Hunter",
        "specs": [
            {"id": "beast-mastery", "name": "Beast Mastery", "role": "dps"},
            {"id": "marksmanship", "name": "Marksmanship", "role": "dps"},
            {"id": "survival", "name": "Survival", "role": "dps"},
        ],
    },
    {
        "id": "rogue",
        "name": "Rogue",
        "specs": [
            {"id": "assassination", "name": "Assassination", "role": "dps"},
            {"id": "combat", "name": "Combat", "role": "dps"},
            {"id": "subtlety", "name": "Subtlety", "role": "dps"},
        ],
    },
    {
        "id": "priest",
        "name": "Priest",
        "specs": [
            {"id": "discipline", "name": "Discipline", "role": "healer"},
            {"id": "holy", "name": "Holy", "role": "healer"},
            {"id": "shadow", "name": "Shadow", "role": "dps"},
        ],
    },
    {
        "id": "shaman",
        "name": "Shaman",
        "specs": [
            {"id": "elemental", "name": "Elemental", "role": "dps"},
            {"id": "enhancement", "name": "Enhancement", "role": "dps"},
            {"id": "restoration", "name": "Restoration", "role": "healer"},
        ],
    },
    {
        "id": "mage",
        "name": "Mage",
        "specs": [
            {"id": "arcane", "name": "Arcane", "role": "dps"},
            {"id": "fire", "name": "Fire", "role": "dps"},
            {"id": "frost", "name": "Frost", "role": "dps"},
        ],
    },
    {
        "id": "warlock",
        "name": "Warlock",
        "specs": [
            {"id": "affliction", "name": "Affliction", "role": "dps"},
            {"id": "demonology", "name": "Demonology", "role": "dps"},
            {"id": "destruction", "name": "Destruction", "role": "dps"},
        ],
    },
    {
        "id": "druid",
        "name": "Druid",
        "specs": [
            {"id": "balance", "name": "Balance", "role": "dps"},
            {"id": "feral", "name": "Feral", "role": None},
            {"id": "restoration", "name": "Restoration", "role": "healer"},
        ],
    },
]

INSTANCES = [
    {"id": "hall-of-thanes", "name": "Hall of Thanes", "kind": "dungeon", "size": 5, "min_level": 13, "max_level": 18, "active": True},
    {"id": "ruins-of-lordaeron", "name": "Ruins of Lordaeron", "kind": "dungeon", "size": 5, "min_level": 15, "max_level": 20, "active": True},
    {"id": "excavation-site", "name": "Excavation Site", "kind": "dungeon", "size": 5, "min_level": 24, "max_level": 29, "active": True},
    {"id": "city-of-dalaran", "name": "City of Dalaran", "kind": "dungeon", "size": 5, "min_level": 28, "max_level": 33, "active": False},
    {"id": "the-drowned-city", "name": "The Drowned City", "kind": "dungeon", "size": 5, "min_level": 35, "max_level": 40, "active": False},
    {"id": "kroldok-stronghold", "name": "Krol'dok Stronghold", "kind": "dungeon", "size": 5, "min_level": 40, "max_level": 45, "active": False},
    {"id": "alcaz-prison", "name": "Alcaz Prison", "kind": "dungeon", "size": 5, "min_level": 48, "max_level": 53, "active": False},
    {"id": "blackmaw-hold", "name": "Blackmaw Hold", "kind": "dungeon", "size": 5, "min_level": 55, "max_level": 60, "active": False},
    {"id": "shapers-terrace", "name": "Shaper's Terrace", "kind": "dungeon", "size": 5, "min_level": 58, "max_level": 60, "active": False},
    {"id": "barrow-deeps", "name": "Barrow Deeps", "kind": "raid", "size": 10, "min_level": 60, "max_level": 60},
    {"id": "hyjal-summit", "name": "Hyjal Summit", "kind": "raid", "size": 20, "min_level": 60, "max_level": 60},
    {"id": "onyxias-lair", "name": "Onyxia's Lair", "kind": "raid", "size": 40, "min_level": 60, "max_level": 60},
    {"id": "event", "name": "Event", "kind": "event", "size": 0},
]

ROLE_LABELS = {
    "tank": "Tank",
    "healer": "Healer",
    "dps": "DPS",
    "melee": "Melee",
    "ranged": "Ranged",
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DUTCH_DAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
DUTCH_MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
CLASS_COLORS = {
    "warrior": "#C79C6E",
    "paladin": "#F58CBA",
    "hunter": "#ABD473",
    "rogue": "#FFF569",
    "priest": "#FFFFFF",
    "shaman": "#0070DE",
    "mage": "#69CCF0",
    "warlock": "#9482C9",
    "druid": "#FF7D0A",
}
CLASS_MARK = {
    "warrior": "<:ik_warrior:1563469880836100136>",
    "paladin": "<:ik_paladin:1563469676619497536>",
    "hunter": "<:ik_hunter:1563469596198051840>",
    "rogue": "<:ik_rogue:1563469757737476176>",
    "priest": "<:ik_priest:1563469717828669440>",
    "shaman": "<:ik_shaman:1563469798057312367>",
    "mage": "<:ik_mage:1563469636719353977>",
    "warlock": "<:ik_warlock:1563469839362949172>",
    "druid": "<:ik_druid:1563469555274096690>",
}
SPEC_MARK = {
    ("warrior", "arms"): "<:ik_warrior_arms:1563469891045036062>",
    ("warrior", "fury"): "<:ik_warrior_fury:1563469900599525469>",
    ("warrior", "protection"): "<:ik_warrior_protection:1563469911957831781>",
    ("paladin", "holy"): "<:ik_paladin_holy:1563469686656602192>",
    ("paladin", "protection"): "<:ik_paladin_protection:1563469696529862706>",
    ("paladin", "retribution"): "<:ik_paladin_retribution:1563469706352922624>",
    ("hunter", "beast-mastery"): "<:ik_hunter_beast_mastery:1563469605924511776>",
    ("hunter", "marksmanship"): "<:ik_hunter_marksmanship:1563469616020193371>",
    ("hunter", "survival"): "<:ik_hunter_survival:1563469626434658345>",
    ("rogue", "assassination"): "<:ik_rogue_assassination:1563469767535370240>",
    ("rogue", "combat"): "<:ik_rogue_combat:1563469777786245151>",
    ("rogue", "subtlety"): "<:ik_rogue_subtlety:1563469788066349076>",
    ("priest", "discipline"): "<:ik_priest_discipline:1563469727618179153>",
    ("priest", "holy"): "<:ik_priest_holy:1563469737701277727>",
    ("priest", "shadow"): "<:ik_priest_shadow:1563469747398516738>",
    ("shaman", "elemental"): "<:ik_shaman_elemental:1563469808022978570>",
    ("shaman", "enhancement"): "<:ik_shaman_enhancement:1563469817896243320>",
    ("shaman", "restoration"): "<:ik_shaman_restoration:1563469829019799627>",
    ("mage", "arcane"): "<:ik_mage_arcane:1563469646534021300>",
    ("mage", "fire"): "<:ik_mage_fire:1563469656440840214>",
    ("mage", "frost"): "<:ik_mage_frost:1563469667127926967>",
    ("warlock", "affliction"): "<:ik_warlock_affliction:1563469849605312546>",
    ("warlock", "demonology"): "<:ik_warlock_demonology:1563469860384808971>",
    ("warlock", "destruction"): "<:ik_warlock_destruction:1563469870853787698>",
    ("druid", "balance"): "<:ik_druid_balance:1563469565642543210>",
    ("druid", "feral"): "<:ik_druid_feral:1563469576061325394>",
    ("druid", "restoration"): "<:ik_druid_restoration:1563469586207211632>",
}
ROLE_MARK = {
    "tank": "<:ik_role_tank:1564028157529424002>",
    "melee": "<:ik_role_dps:1564028155243663450>",
    "ranged": "<:ik_role_dps:1564028155243663450>",
    "healer": "<:ik_role_heal:1564028156451749962>",
}


class PlayerMessage(Exception):
    """A sentence the player can read in Discord."""


_COMPANION_LOCAL = {
    "excavation-site-wetlands": "excavation-site",
    "krol-dok-stronghold": "kroldok-stronghold",
}
_TEN_PLAYER = {"upper-blackrock-spire"}


def _name_key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _instance_note(remote):
    if remote.get("beta_locked"):
        return "closed in the beta"
    if remote.get("status") == "announced":
        return "announced"
    return ""


def _level_text(low, high):
    if not isinstance(low, int) or not isinstance(high, int):
        return ""
    if low == high:
        return str(low)
    return f"{low}\u2013{high}"


def _playable(remote):
    return remote.get("status") == "launch" and not remote.get("beta_locked")


def _raid_is_open(today=None):
    """Barrow Deeps, Hyjal Summit and Onyxia's Lair open on 9 December 2026."""
    from datetime import date

    today = today or date.today()
    return today >= date(2026, 12, 9)


def _with_level(row, remote=None):
    """Level and whether it can be run. Companion status wins over the local copy."""
    item = dict(row)
    if remote is not None:
        low = remote.get("min_level")
        high = remote.get("max_level")
        if isinstance(low, int) and isinstance(high, int):
            item["min_level"] = low
            item["max_level"] = high
        item["active"] = _playable(remote)
    elif item.get("kind") == "raid":
        item["active"] = _raid_is_open()
    item["level"] = _level_text(item.get("min_level"), item.get("max_level"))
    return item


def _menu_description(item):
    parts = []
    if item.get("level"):
        parts.append(str(item["level"]))
    parts.append(f"{item['size']} spelers")
    if item.get("kind") in ("dungeon", "raid"):
        parts.append("actief" if item.get("active") else "inactief")
    return " · ".join(parts)[:100]


def instances():
    """Dungeons follow Forever Companion. Size and raids stay local.

    Classic launch dungeons are included. Upper Blackrock Spire is 10 players.
    Every other dungeon without a local size is 5. A saved mention or banner
    keeps the local id when the companion id differs.
    """
    local = [dict(item, note="") for item in INSTANCES]
    remote = forever_companion.dungeons()
    if not remote:
        return [_with_level(item) for item in local]
    by_id = {item["id"]: item for item in local}
    by_name = {_name_key(item["name"]): item for item in local}
    used = set()
    rows = []
    for item in remote:
        local_id = _COMPANION_LOCAL.get(item["id"], item["id"])
        found = by_id.get(local_id) or by_name.get(_name_key(item["name"]))
        if found is not None:
            if found["id"] in used:
                continue
            rows.append(_with_level({**found, "name": item["name"], "note": _instance_note(item)}, item))
            used.add(found["id"])
            continue
        if not re.fullmatch(r"[a-z0-9-]{1,60}", item["id"]):
            continue
        rows.append(_with_level({
            "id": item["id"],
            "name": item["name"],
            "kind": "dungeon",
            "size": 10 if item["id"] in _TEN_PLAYER else 5,
            "note": _instance_note(item),
        }, item))
    for item in local:
        if item["kind"] == "dungeon" and item["id"] not in used:
            rows.append(_with_level(item))
    rows.extend(_with_level(item) for item in local if item["kind"] == "raid")
    rows.extend(_with_level(item) for item in local if item["kind"] == "event")
    return rows


def instance_source():
    if forever_companion.dungeons():
        return "https://forevercompanion.io"
    return ""


def instance_by_id(instance_id):
    return next((item for item in instances() if item["id"] == instance_id), None)


def is_event(row):
    """An event is a free title and a date. It has no roles and no loot."""
    if not row:
        return False
    if row.get("kind") == "event":
        return True
    return str(row.get("instance_id") or "") == "event"


def loot_catalog():
    """Dungeon drops from the Companion cache, under Ironkeep's dungeon id."""
    stored = forever_companion.loot()
    named = {item["id"]: item["name"] for item in instances()}
    groups = []
    for remote_id, items in stored.items():
        if not isinstance(items, list):
            continue
        local_id = _COMPANION_LOCAL.get(remote_id, remote_id)
        if not re.fullmatch(r"[a-z0-9-]{1,60}", str(local_id)):
            continue
        clean = [item for item in items if isinstance(item, dict) and item.get("key") and item.get("name")]
        if not clean:
            continue
        groups.append({"id": local_id, "name": named.get(local_id, remote_id), "items": clean})
    groups.sort(key=lambda group: group["name"])
    return groups


_ARMOR = {
    "warrior": {"mail", "plate"},
    "paladin": {"mail", "plate"},
    "hunter": {"leather", "mail"},
    "shaman": {"leather", "mail"},
    "rogue": {"leather"},
    "druid": {"leather"},
    "mage": {"cloth"},
    "priest": {"cloth"},
    "warlock": {"cloth"},
}
_ONE_HAND = {
    "warrior": {"axe", "sword", "mace", "dagger", "fist weapon"},
    "paladin": {"sword", "mace"},
    "hunter": {"axe", "sword", "dagger", "fist weapon"},
    "rogue": {"sword", "mace", "dagger", "fist weapon"},
    "priest": {"mace", "dagger"},
    "shaman": {"axe", "mace", "dagger", "fist weapon"},
    "mage": {"sword", "dagger"},
    "warlock": {"sword", "dagger"},
    "druid": {"mace", "dagger", "fist weapon"},
}
_TWO_HAND = {
    "warrior": {"axe", "sword", "mace", "polearm", "staff"},
    "paladin": {"axe", "sword", "mace", "polearm"},
    "hunter": {"axe", "sword", "polearm", "staff"},
    "rogue": set(),
    "priest": {"staff"},
    "shaman": {"axe", "mace", "staff"},
    "mage": {"staff"},
    "warlock": {"staff"},
    "druid": {"mace", "polearm", "staff"},
}
_RANGED = {
    "warrior": {"bow", "gun", "crossbow", "thrown"},
    "paladin": set(),
    "hunter": {"bow", "gun", "crossbow"},
    "rogue": {"bow", "gun", "crossbow", "thrown"},
    "priest": {"wand"},
    "shaman": set(),
    "mage": {"wand"},
    "warlock": {"wand"},
    "druid": set(),
}
_RELIC = {"libram": "paladin", "idol": "druid", "totem": "shaman"}
_UNIVERSAL = {"neck", "back", "finger", "ring", "trinket", "shirt", "tabard"}
_SHIELD = {"warrior", "paladin", "shaman"}


def usable_by(class_id, item):
    """True when this class can equip the item. Unknown armor stays visible."""
    if class_id not in _ARMOR:
        return False
    armor = (item.get("armor") or "").lower()
    weapon = (item.get("weapon") or "").lower()
    slot = (item.get("slot") or "").lower()
    if armor:
        return armor in _ARMOR[class_id]
    if weapon in _RELIC:
        return class_id == _RELIC[weapon]
    if weapon == "shield" or slot == "shield":
        return class_id in _SHIELD
    if weapon:
        if slot in ("two-hand", "two hand"):
            return weapon in _TWO_HAND[class_id]
        if slot in ("main hand", "one-hand", "one hand", "off hand", "off-hand"):
            return weapon in _ONE_HAND[class_id]
        if weapon in _RANGED[class_id]:
            return True
        return weapon in _ONE_HAND[class_id] or weapon in _TWO_HAND[class_id]
    if slot in _UNIVERSAL:
        return True
    if not slot:
        return False
    return True


def loot_for_class(class_id):
    groups = []
    for group in loot_catalog():
        items = [item for item in group["items"] if usable_by(class_id, item)]
        if items:
            groups.append({**group, "items": items})
    return groups


def raid_wants(instance_id, signups):
    """Items wanted by people who signed up with a saved character, for this dungeon only."""
    if not instance_id:
        return []
    group = next((item for item in loot_catalog() if item["id"] == instance_id), None)
    if group is None:
        return []
    ids = [signup.get("character_id") for signup in signups or [] if signup.get("character_id")]
    if not ids:
        return []
    chosen = db.wishes_for_characters(ids)
    wanted = {
        (row["character_id"], row["item_key"])
        for row in chosen
        if row["instance_id"] == instance_id
    }
    rows = []
    for signup in signups or []:
        character_id = signup.get("character_id")
        if not character_id:
            continue
        names = [
            {"name": item["name"], "icon": item.get("icon") or ""}
            for item in group["items"]
            if (character_id, item["key"]) in wanted
        ]
        if names:
            rows.append({"name": signup.get("name") or "Player", "items": names})
    return rows


def instance_by_name(name):
    return next((item for item in instances() if item["name"] == (name or "").strip()), None)


def banner_root():
    """Pictures chosen by a server. Kept beside the database, so a code update leaves them in place."""
    if config.DB_PATH:
        return Path(config.DB_PATH).resolve().parent / "banners"
    return Path(__file__).resolve().parent / "static" / "wow" / "custom"


def _banner_file(guild_id, instance_id, ext):
    if ext not in (".jpg", ".png"):
        raise ValueError("banner")
    if not re.fullmatch(r"\d{1,30}", str(guild_id or "")):
        raise ValueError("banner")
    if not re.fullmatch(r"[a-z0-9-]{1,60}", str(instance_id or "")):
        raise ValueError("banner")
    return banner_root() / str(guild_id) / f"{instance_id}{ext}"


def custom_banner_path(guild_id, instance_id):
    for ext in (".jpg", ".png"):
        try:
            path = _banner_file(guild_id, instance_id, ext)
        except ValueError:
            return None
        if path.is_file():
            return path
    return None


def save_custom_banner(guild_id, instance_id, data):
    """Store a JPG or PNG for this server. The other type is removed."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 32 or len(data) > 8 * 1024 * 1024:
        raise ValueError("banner")
    if data[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    else:
        raise ValueError("banner")
    path = _banner_file(guild_id, instance_id, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(bytes(data))
    temporary.replace(path)
    other = ".png" if ext == ".jpg" else ".jpg"
    leftover = _banner_file(guild_id, instance_id, other)
    if leftover.is_file():
        leftover.unlink()
    return path


def remove_custom_banner(guild_id, instance_id):
    for ext in (".jpg", ".png"):
        try:
            path = _banner_file(guild_id, instance_id, ext)
        except ValueError:
            return
        if path.is_file():
            path.unlink()


def banner_preview(guild, instance_id):
    """Page address of the picture Settings shows, and whether the server replaced it."""
    hidden = instance_id in set(db.wow_settings((guild or {}).get("settings")).get("banner_hidden") or [])
    custom = custom_banner_path((guild or {}).get("id"), instance_id)
    if hidden:
        return "", custom is not None
    if custom is not None:
        return f"/{guild['slug']}/banners/{instance_id}?v={int(custom.stat().st_mtime)}", True
    bundled = Path(__file__).resolve().parent / "static" / "wow" / f"{instance_id}.jpg"
    if bundled.is_file():
        return f"/static/wow/{instance_id}.jpg", False
    return "", False


def banner_path(raid, guild=None):
    instance = instance_by_id(raid.get("instance_id")) or instance_by_name(raid.get("title"))
    if instance is None:
        return None
    if guild is not None:
        hidden = db.wow_settings(guild.get("settings")).get("banner_hidden") or []
        if instance["id"] in hidden:
            return None
        custom = custom_banner_path(guild.get("id"), instance["id"])
        if custom is not None:
            return custom
    path = Path(__file__).resolve().parent / "static" / "wow" / f"{instance['id']}.jpg"
    return path if path.is_file() else None


def mention_roles(guild, raid):
    """Discord roles tagged above the post. Configured per dungeon or raid."""
    instance = instance_by_id(raid.get("instance_id")) or instance_by_name(raid.get("title"))
    if instance is None:
        return []
    mentions = db.wow_settings((guild or {}).get("settings")).get("mentions") or {}
    return [str(role_id) for role_id in mentions.get(instance["id"], []) if role_id]


_NOTE_MENTION = re.compile(r"<@&(\d{15,22})>|<@!?(\d{15,22})>")


def note_mentions(note, guild=None):
    """Role and person tags written in a note. The everyone role never notifies."""
    everyone = {
        str(role.get("id"))
        for role in ((guild or {}).get("roles") or [])
        if role.get("everyone") or (role.get("name") or "").casefold() in {"@everyone", "everyone"}
    }
    roles = []
    users = []
    seen_roles = set()
    seen_users = set()
    for match in _NOTE_MENTION.finditer(note or ""):
        role_id, user_id = match.group(1), match.group(2)
        if role_id and role_id not in everyone and role_id not in seen_roles:
            seen_roles.add(role_id)
            roles.append(role_id)
        elif user_id and user_id not in seen_users:
            seen_users.add(user_id)
            users.append(user_id)
    return roles, users


def _mention_label(name, fallback):
    return " ".join(str(name or fallback).replace("@", "").split()) or fallback


def note_display(note, guild):
    """The note as people read it. Embeds show a raw tag, so the name is written out."""
    text = note or ""
    if not _NOTE_MENTION.search(text):
        return text
    roles = {
        str(role.get("id")): _mention_label(role.get("name"), "role")
        for role in ((guild or {}).get("roles") or [])
    }
    people = {}
    guild_id = (guild or {}).get("id")
    if guild_id:
        for person in db.list_members(guild_id):
            label = person.get("nick") or person.get("name") or person.get("username") or "member"
            people[str(person.get("user_id"))] = _mention_label(label, "member")

    def replace(match):
        role_id, user_id = match.group(1), match.group(2)
        if role_id:
            return "@" + roles.get(role_id, "role")
        return "@" + people.get(user_id, "member")

    return _NOTE_MENTION.sub(replace, text)


def _mention_entries(guild):
    """Readable names that map back to one Discord tag. A shared name is left as text."""
    found = {}
    blocked = set()

    def add(label, token):
        key = label.casefold()
        if not key:
            return
        if key in found and found[key][1] != token:
            blocked.add(key)
        elif key not in found:
            found[key] = (label, token)

    for role in (guild or {}).get("roles") or []:
        role_id = str(role.get("id") or "")
        if not role_id:
            continue
        add(_mention_label(role.get("name"), ""), f"<@&{role_id}>")
    guild_id = (guild or {}).get("id")
    if guild_id:
        for person in db.list_members(guild_id):
            user_id = str(person.get("user_id") or "")
            if not user_id:
                continue
            label = person.get("nick") or person.get("name") or person.get("username") or ""
            add(_mention_label(label, ""), f"<@{user_id}>")
    return [found[key] for key in found if key not in blocked]


def _plain_words(label):
    return re.findall(r"[^\W_]+", str(label or "").casefold(), flags=re.UNICODE)


def _plain_mention_map(entries):
    """Match @tank to a role named with an icon, when that short name is unique."""
    found = {}
    blocked = set()
    for label, token in entries:
        words = _plain_words(label)
        if not words:
            continue
        keys = [" ".join(words)]
        if len(words) > 1:
            keys.append(words[0])
        for key in keys:
            if key in found and found[key] != token:
                blocked.add(key)
            elif key not in found:
                found[key] = token
    for key in blocked:
        found.pop(key, None)
    return found


def note_resolve(note, guild):
    """Turn @Name typed in a note back into the Discord tag, when the name is unique."""
    text = note or ""
    if "@" not in text:
        return text
    entries = sorted(_mention_entries(guild), key=lambda item: len(item[0]), reverse=True)
    if not entries:
        return text
    plain = _plain_mention_map(entries)
    parts = []
    index = 0
    length = len(text)
    while index < length:
        if text[index] == "@" and (index == 0 or text[index - 1].isspace()):
            rest = text[index + 1:]
            matched = None
            for label, token in entries:
                if rest[:len(label)].casefold() != label.casefold():
                    continue
                end = len(label)
                if end < len(rest) and not rest[end].isspace() and rest[end] not in ".,!?:;)":
                    continue
                matched = (token, end)
                break
            if matched is None:
                word = re.match(r"[^\W_]+", rest, flags=re.UNICODE)
                token = plain.get(word.group(0).casefold()) if word else None
                if token:
                    matched = (token, word.end())
            if matched:
                parts.append(matched[0])
                index += 1 + matched[1]
                continue
        parts.append(text[index])
        index += 1
    return "".join(parts)


def note_clean(note, guild):
    """Store a note with real Discord tags, capped so a tag is never cut in half."""
    text = note_resolve(note, guild).strip()
    if len(text) <= 400:
        return text or None
    trimmed = text[:400]
    cut = re.search(r"<@[&!]?\d*$", trimmed)
    if cut:
        trimmed = trimmed[:cut.start()]
    return trimmed.strip() or None


def note_tag_choices(guild):
    """Roles and members an officer can insert into a raid, dungeon or event note."""
    roles = []
    for role in (guild or {}).get("roles") or []:
        if role.get("everyone") or role.get("managed"):
            continue
        if (role.get("name") or "").casefold() in {"@everyone", "everyone"}:
            continue
        role_id = str(role.get("id") or "")
        if not role_id:
            continue
        roles.append({
            "id": role_id,
            "name": ((role.get("name") or "Role").strip() or "Role")[:80],
            "position": int(role.get("position") or 0),
        })
    roles.sort(key=lambda role: (-role["position"], role["name"].casefold()))
    people = []
    guild_id = (guild or {}).get("id")
    if guild_id:
        for person in db.list_members(guild_id):
            user_id = str(person.get("user_id") or "")
            if not user_id:
                continue
            label = (person.get("nick") or person.get("name") or person.get("username") or "Member").strip()
            people.append({"id": user_id, "name": (label or "Member")[:80]})
    people.sort(key=lambda person: person["name"].casefold())
    return [{"id": role["id"], "name": role["name"]} for role in roles], people


def _post_content(guild, raid):
    """Text above the embed. Configured roles, plus anyone tagged in the note."""
    role_ids = mention_roles(guild, raid)
    note_roles, note_users = note_mentions(raid.get("note"), guild)
    seen = set(role_ids)
    extra_roles = [role_id for role_id in note_roles if role_id not in seen]
    parts = [f"<@&{role_id}>" for role_id in role_ids]
    parts.extend(f"<@&{role_id}>" for role_id in extra_roles)
    parts.extend(f"<@{user_id}>" for user_id in note_users)
    text = " ".join(parts)
    mentions = voice_mentions(raid)
    if mentions:
        text = f"{text} {mentions}".strip()
    allowed = {"parse": [], "roles": role_ids + extra_roles}
    if note_users:
        allowed["users"] = note_users
    return text, allowed


def event_channel(wow_config, instance):
    """Dungeons can have their own channel. Events can too. Everything else uses the raid channel."""
    instance = instance or {}
    if is_event(instance) and (wow_config or {}).get("event_channel"):
        return wow_config.get("event_channel")
    if (wow_config or {}).get("channel_mode") == "split" and instance.get("kind") == "dungeon":
        return wow_config.get("dungeon_channel")
    return (wow_config or {}).get("raid_channel")


def creation_log_text(guild, raid, message_id, channel_id):
    """One log line for a dungeon, raid or event that just went up in Discord."""
    instance = instance_by_id((raid or {}).get("instance_id")) or {}
    if is_event(raid) or is_event(instance):
        kind = "Event"
    elif instance.get("kind") == "dungeon":
        kind = "Dungeon"
    else:
        kind = "Raid"
    title = " ".join(str((raid or {}).get("title") or kind).split()) or kind
    when = discord_when(
        raid["starts_at"],
        (guild or {}).get("settings"),
        ends_at=(raid or {}).get("ends_at"),
    )
    who = " ".join(str((raid or {}).get("created_by") or "Ironkeep").split()) or "Ironkeep"
    lines = [
        f"**{kind} geplaatst** · {title}"[:250],
        f"{when} · <#{channel_id}>",
        f"Door {who[:80]}",
    ]
    url = discord_url((guild or {}).get("id"), channel_id, message_id)
    if url:
        lines.append(url)
    return "\n".join(lines)[:2000]


def post_creation_log(guild, raid, message_id, channel_id):
    """Keep a copy in the log channel. A missing channel or a Discord error does not block the signup."""
    log_channel = db.wow_settings((guild or {}).get("settings")).get("log_channel")
    if not log_channel or not message_id or not channel_id:
        return
    try:
        discord_api.send_payload(
            log_channel,
            {
                "content": creation_log_text(guild, raid, message_id, channel_id),
                "allowed_mentions": {"parse": []},
            },
        )
    except discord_api.DiscordError as error:
        log.warning("Could not write the raid log for %s: %s", (raid or {}).get("id"), error.status)


def posting_channel(config, raid):
    """Where this signup is posted. An open post stays in the channel it already uses."""
    if raid.get("status") == "open" and raid.get("channel_id"):
        return str(raid["channel_id"])
    instance = instance_by_id(raid.get("instance_id")) or {"kind": "raid"}
    return str(event_channel(config, instance) or "")


def message_files(raid, guild=None):
    return [(path.name, path.read_bytes()) for path in _attached(raid, guild)]


def _attached(raid, guild=None):
    """Banner first, then the wide strip that gives the roster the same width."""
    paths = []
    banner = banner_path(raid, guild)
    if banner is not None:
        paths.append(banner)
    width = Path(__file__).resolve().parent / "static" / "wow" / "width.png"
    if width.is_file():
        paths.append(width)
    return paths


def instance_groups():
    rows = instances()
    groups = [
        {"label": "Dungeons", "choices": [item for item in rows if item["kind"] == "dungeon"]},
        {"label": "Raids", "choices": [item for item in rows if item["kind"] == "raid"]},
    ]
    events = [item for item in rows if item["kind"] == "event"]
    if events:
        groups.append({"label": "Events", "choices": events})
    return groups


def playable_classes():
    """Classes a player can save. Names follow the Warcraft Forever catalog.

    A class without a local specialization list is left out. The catalog does
    not decide raid roles, and a class it has not published yet stays available
    from the local list.
    """
    local = {item["id"]: item for item in CLASSES}
    remote = {item["id"]: item for item in warcraft_forever.class_records()}
    order = [item["id"] for item in warcraft_forever.class_records()] or list(local)
    merged = []
    seen = set()
    for slug in order:
        base = local.get(slug)
        if base is None:
            continue
        extra = remote.get(slug) or {}
        merged.append({
            "id": base["id"],
            "name": extra.get("name") or base["name"],
            "icon_url": extra.get("icon_url") or "",
            "client_id": extra.get("client_id"),
            "specs": base["specs"],
        })
        seen.add(slug)
    for item in CLASSES:
        if item["id"] not in seen:
            merged.append({**item, "icon_url": "", "client_id": None})
    return merged


def _spec_key(value):
    text = (value or "").strip().lower().replace(" ", "-")
    prefix, separator, rest = text.partition("-")
    if separator and prefix in local_class_ids():
        text = rest
    if text.endswith("-combat") or text.endswith("-magic"):
        text = text[: text.rfind("-")]
    return text


def local_class_ids():
    return {item["id"] for item in CLASSES}


def specializations(klass):
    """Specialization choices for one class.

    Ids and roles stay on the local list, so a saved character keeps its spot.
    When `talent_layout` starts returning trees, only the visible name changes,
    and the tree id is kept beside that same specialization.
    """
    specs = [
        {"id": spec["id"], "name": spec["name"], "role": spec["role"], "tree_id": None}
        for spec in klass["specs"]
    ]
    layout = warcraft_forever.talent_layout(klass["id"])
    trees = (layout or {}).get("trees") or []
    if not trees:
        return specs
    by_key = {}
    for tree in trees:
        if not isinstance(tree, dict):
            continue
        by_key[_spec_key(tree.get("id"))] = tree
        by_key[_spec_key(tree.get("name"))] = tree
    for spec in specs:
        tree = by_key.get(_spec_key(spec["id"])) or by_key.get(_spec_key(spec["name"]))
        if tree is None:
            continue
        name = " ".join(str(tree.get("name") or "").split())
        if name:
            spec["name"] = name
        tree_id = str(tree.get("id") or "")
        if tree_id:
            spec["tree_id"] = tree_id
    return specs


def find_spec(class_id, spec_id):
    klass = next((item for item in playable_classes() if item["id"] == class_id), None)
    if klass is None:
        return None, None
    spec = next((item for item in specializations(klass) if item["id"] == spec_id), None)
    return klass, spec


LANES = {
    "tank": [
        ("warrior", "protection"),
        ("paladin", "protection"),
        ("druid", "feral"),
    ],
    "melee": [
        ("warrior", "arms"),
        ("warrior", "fury"),
        ("paladin", "retribution"),
        ("rogue", "assassination"),
        ("rogue", "combat"),
        ("rogue", "subtlety"),
        ("shaman", "enhancement"),
        ("druid", "feral"),
    ],
    "ranged": [
        ("hunter", "beast-mastery"),
        ("hunter", "marksmanship"),
        ("hunter", "survival"),
        ("priest", "shadow"),
        ("shaman", "elemental"),
        ("mage", "arcane"),
        ("mage", "fire"),
        ("mage", "frost"),
        ("warlock", "affliction"),
        ("warlock", "demonology"),
        ("warlock", "destruction"),
        ("druid", "balance"),
    ],
    "healer": [
        ("paladin", "holy"),
        ("priest", "discipline"),
        ("priest", "holy"),
        ("shaman", "restoration"),
        ("druid", "restoration"),
    ],
}
LANE_ORDER = ("tank", "melee", "ranged", "healer")
SIGNUP_KINDS = ("main", "late", "bench", "tentative", "absent")


def role_for(class_id, spec_id, chosen=None):
    """Protection is tank. Holy, Discipline and Restoration are healer. Feral asks."""
    _klass, spec = find_spec(class_id, spec_id)
    if spec is None:
        return None
    if spec["role"] in ("tank", "healer", "dps"):
        return spec["role"]
    if chosen in ("tank", "dps"):
        return chosen
    return None


def display_lane(signup):
    role = signup.get("role")
    if role in LANES:
        return role
    key = (signup.get("class_id"), signup.get("spec_id"))
    if role == "dps":
        return "melee" if key in set(LANES["melee"]) else "ranged"
    return role


def cap_key(role):
    if role in ("melee", "ranged", "dps"):
        return "dps"
    return role


def choice_names(class_id, spec_id):
    klass, spec = find_spec(class_id, spec_id)
    return (
        klass["name"] if klass else class_id,
        spec["name"] if spec else spec_id,
    )


def class_color(class_id):
    return CLASS_COLORS.get(class_id, "#c9cdd3")


def choice_label(class_id, spec_id):
    class_name, spec_name = choice_names(class_id, spec_id)
    return f"{class_name} · {spec_name}"


def clean_name(name):
    cleaned = " ".join((name or "").replace("\n", " ").split())
    return cleaned[:80] or "Member"


def clean_character_name(name):
    """A Forever character name: first and last, each 2 to 12 letters."""
    parts = (name or "").split()
    if len(parts) != 2:
        return None
    first, last = parts
    if re.fullmatch(r"[A-Za-z]{2,12}", first) and re.fullmatch(r"[A-Za-z]{2,12}", last):
        return f"{first} {last}"
    return None


def character_name_parts(name):
    first, separator, last = (name or "").strip().partition(" ")
    if not separator:
        return first, ""
    return first, last.strip()


def character_command():
    """Slash command payload. The questions come in the prompt that follows, same as /raid."""
    return {
        "name": "character",
        "description": "Sla een karakter op, stap voor stap.",
        "dm_permission": False,
    }


def _command_values(options):
    return {option.get("name"): option.get("value") or "" for option in options or [] if option.get("name")}


def spec_suggestions(class_id, typed):
    klass = next((item for item in playable_classes() if item["id"] == class_id), None)
    if klass is None:
        return []
    needle = (typed or "").strip().casefold()
    rows = []
    for spec in specializations(klass):
        if needle and needle not in spec["name"].casefold() and needle not in spec["id"].casefold():
            continue
        rows.append({"name": spec["name"], "value": spec["id"]})
    return rows[:25]


_CHARACTER_COMMAND_ERRORS = {
    "name": "Gebruik een voornaam en een achternaam, allebei 2 tot 12 letters. Bijvoorbeeld Theron Swiftblade.",
    "choice": "Kies een specialisatie van die class.",
    "duplicate": "Je hebt dit karakter al.",
    "limit": "Je kunt maximaal 9 karakters opslaan.",
    "server": "Dit commando werkt op een World of Warcraft server.",
}


def save_character_command(guild_id, user_id, options):
    """Save a character from /createchar. Same name and class rules as the site."""
    guild = db.guild_by_id(guild_id)
    if guild is None or guild.get("approval") != "approved" or db.guild_game(guild.get("settings")) != "wow":
        return {"ok": False, "text": _CHARACTER_COMMAND_ERRORS["server"]}
    values = _command_values(options)
    name = clean_character_name(values.get("naam") or "")
    if name is None:
        return {"ok": False, "text": _CHARACTER_COMMAND_ERRORS["name"]}
    class_id = values.get("class") or ""
    spec_id = values.get("spec") or ""
    if find_spec(class_id, spec_id)[1] is None:
        return {"ok": False, "text": _CHARACTER_COMMAND_ERRORS["choice"]}
    result = db.save_wow_character(
        guild_id,
        user_id,
        name,
        class_id,
        spec_id,
        role_for(class_id, spec_id) or "",
    )
    if isinstance(result, str):
        return {"ok": False, "text": _CHARACTER_COMMAND_ERRORS.get(result, _CHARACTER_COMMAND_ERRORS["choice"])}
    return {"ok": True, "text": f"**{name}** is opgeslagen als {choice_label(class_id, spec_id)}. Je kunt dit karakter kiezen als je je aanmeldt."}


def answer_character_autocomplete(interaction_id, token, data):
    options = (data or {}).get("options") or []
    focused = next((option for option in options if option.get("focused")), None)
    choices = []
    if (data or {}).get("name") == "createchar" and focused and focused.get("name") == "spec":
        choices = spec_suggestions(_command_values(options).get("class"), focused.get("value") or "")
    discord_api.interaction_callback(interaction_id, token, kind=8, data={"choices": choices})


def _character_payload(draft):
    return dict((draft or {}).get("payload") or {})


def character_draft_apply(draft, action, value):
    """Move one step. A bad answer stays on the same step."""
    payload = _character_payload(draft)
    step = draft.get("step") or "class"
    if action == "class":
        class_id = str(value or "")
        if not any(item["id"] == class_id for item in playable_classes()):
            return draft, "Kies een class."
        if payload.get("class_id") != class_id:
            payload.pop("spec_id", None)
        payload["class_id"] = class_id
        return {"step": "spec", "payload": payload}, ""
    if action == "spec":
        class_id = payload.get("class_id") or ""
        spec_id = str(value or "")
        if find_spec(class_id, spec_id)[1] is None:
            return draft, "Kies een specialisatie van die class."
        payload["spec_id"] = spec_id
        return {"step": "name", "payload": payload}, ""
    if action == "name":
        fields = value or {}
        name = clean_character_name(f"{fields.get('voornaam') or ''} {fields.get('achternaam') or ''}")
        if name is None:
            return draft, _CHARACTER_COMMAND_ERRORS["name"]
        first, last = character_name_parts(name)
        payload["first"] = first
        payload["last"] = last
        return {"step": "confirm", "payload": payload}, ""
    return draft, "Deze stap is voorbij."


def character_name_modal(draft):
    payload = _character_payload(draft)
    return {
        "custom_id": f"ikym:{draft['id']}:name",
        "title": "Naam",
        "components": [
            _draft_text("voornaam", "Voornaam", "Theron", True, 12, payload.get("first") or ""),
            _draft_text("achternaam", "Achternaam", "Swiftblade", True, 12, payload.get("last") or ""),
        ],
    }


def character_draft_view(draft, error=""):
    """The prompt for whatever is still open, plus the answers already given."""
    draft_id = draft["id"]
    payload = _character_payload(draft)
    class_id = payload.get("class_id") or ""
    spec_id = payload.get("spec_id") or ""
    lines = ["**Karakter opslaan**"]
    if class_id:
        class_name, spec_name = choice_names(class_id, spec_id) if spec_id else choice_names(class_id, "")
        lines.append(f"Class: {class_name}" if not spec_id else f"Class: {class_name} · {spec_name}")
    if payload.get("first") and payload.get("last"):
        lines.append(f"Naam: {payload['first']} {payload['last']}")
    step = draft.get("step") or "class"
    question = {
        "class": "Kies een class.",
        "spec": "Kies een specialisatie.",
        "name": "Voornaam en achternaam, allebei 2 tot 12 letters.",
        "confirm": "Opslaan voegt dit karakter toe aan je lijst.",
    }.get(step, "Kies een class.")
    lines.extend(["", question])
    if error:
        lines.append(error)
    cancel = _draft_button("Annuleren", f"ikyx:{draft_id}")
    components = []
    if step == "class":
        options = [
            {"label": item["name"][:100], "value": item["id"][:100]}
            for item in playable_classes()
        ][:25]
        if options:
            components.append(_draft_row([{
                "type": 3,
                "custom_id": f"ikyc:{draft_id}",
                "placeholder": "Kies een class",
                "options": options,
            }]))
        components.append(_draft_row([cancel]))
    elif step == "spec":
        klass = next((item for item in playable_classes() if item["id"] == class_id), None)
        options = []
        if klass is not None:
            options = [
                {"label": spec["name"][:100], "value": spec["id"][:100]}
                for spec in specializations(klass)
            ][:25]
        if options:
            components.append(_draft_row([{
                "type": 3,
                "custom_id": f"ikys:{draft_id}",
                "placeholder": "Kies een specialisatie",
                "options": options,
            }]))
        components.append(_draft_row([cancel]))
    elif step == "name":
        components.append(_draft_row([_draft_button("Naam invullen", f"ikyn:{draft_id}", 1), cancel]))
    else:
        components.append(_draft_row([_draft_button("Opslaan", f"ikyo:{draft_id}", 1), cancel]))
    return {"content": "\n".join(lines)[:2000], "components": components}


def begin_character_prompt(guild_id, user_id):
    guild = db.guild_by_id(guild_id)
    if guild is None or guild.get("approval") != "approved" or db.guild_game(guild.get("settings")) != "wow":
        return {"content": _CHARACTER_COMMAND_ERRORS["server"], "flags": 64}
    draft_id = db.create_command_draft(guild_id, user_id, "character", "class")
    view = character_draft_view(db.command_draft(draft_id))
    view["flags"] = 64
    return view


def continue_character_prompt(guild_id, user_id, custom_id, values, fields):
    """Follow a button, a list or a filled-in name. Returns the Discord callback kind and data."""
    parts = str(custom_id or "").split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        return 4, {"content": "Deze prompt is verlopen. Gebruik /character opnieuw.", "flags": 64}
    action, draft_id, extra = parts[0], int(parts[1]), parts[2] if len(parts) > 2 else ""
    draft = db.command_draft(draft_id)
    guild = db.guild_by_id(guild_id)
    if draft is None or guild is None or draft.get("kind") != "character" or str(draft["guild_id"]) != str(guild_id):
        return 7, {"content": "Deze prompt is verlopen. Gebruik /character opnieuw.", "components": []}
    if str(draft["user_id"]) != str(user_id):
        return 4, {"content": "Dit is niet jouw prompt.", "flags": 64}
    if action == "ikyx":
        db.delete_command_draft(draft_id)
        return 7, {"content": "Geannuleerd.", "components": []}
    if action == "ikyn":
        if draft.get("step") != "name":
            return 7, character_draft_view(draft, "Deze stap is voorbij.")
        return 9, character_name_modal(draft)
    if action == "ikyo":
        payload = _character_payload(draft)
        result = save_character_command(guild_id, user_id, [
            {"name": "naam", "value": f"{payload.get('first') or ''} {payload.get('last') or ''}"},
            {"name": "class", "value": payload.get("class_id") or ""},
            {"name": "spec", "value": payload.get("spec_id") or ""},
        ])
        if result["ok"]:
            db.delete_command_draft(draft_id)
            return 7, {"content": result["text"], "components": []}
        return 7, character_draft_view(draft, result["text"])
    value = None
    change = ""
    if action == "ikyc":
        change, value = "class", (values or [""])[0]
    elif action == "ikys":
        change, value = "spec", (values or [""])[0]
    elif action == "ikym" and extra == "name":
        change, value = "name", fields or {}
    else:
        return 7, character_draft_view(draft, "Deze stap is voorbij.")
    updated, error = character_draft_apply(draft, change, value)
    if not error:
        db.save_command_draft(draft_id, updated["step"], updated["payload"])
        updated = db.command_draft(draft_id) or {**draft, **updated}
    view = character_draft_view(updated if not error else draft, error)
    return 7, view


def answer_create_character(guild_id, user_id, interaction_id, token, data):
    if (data or {}).get("name") not in ("character", "createchar"):
        return
    _draft_callback(interaction_id, token, 4, begin_character_prompt(guild_id, user_id))


def answer_character_prompt(guild_id, user_id, interaction_id, token, custom_id, values=None, fields=None):
    kind, data = continue_character_prompt(guild_id, user_id, custom_id, values, fields)
    _draft_callback(interaction_id, token, kind, data)


def raid_command():
    """Slash command payload. The questions come in the prompt that follows."""
    return {
        "name": "raid",
        "description": "Plan een dungeon of raid, stap voor stap.",
        "dm_permission": False,
    }


def guild_commands():
    """WoW slash commands. Each opens a private prompt: lists for choices, a form when something must be typed."""
    return [character_command(), raid_command()]


def _raw_options(options):
    found = {}
    for option in options or []:
        name = option.get("name")
        if name and "value" in option:
            found[name] = option["value"]
    return found


def _can_post_raid(guild, user_id, role_ids):
    if str(user_id) == str(config.SUPERADMIN_ID):
        return True
    if guild.get("added_by_id") and str(guild["added_by_id"]) == str(user_id):
        return True
    posters = {str(role_id) for role_id in db.wow_settings(guild.get("settings"))["poster_roles"]}
    return bool(posters & {str(role_id) for role_id in role_ids or []})


def _command_cap(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("caps") from None


def prepare_raid_command(guild, user_id, role_ids, options, now=None):
    """Check /raid the same way as the site form. Does not write a raid yet."""
    if guild is None or guild.get("approval") != "approved" or db.guild_game(guild.get("settings")) != "wow":
        return {"ok": False, "text": "Dit commando werkt op een World of Warcraft server."}
    if not _can_post_raid(guild, user_id, role_ids):
        return {"ok": False, "text": "Je hebt niet de rol die nodig is om een raid te plaatsen."}
    if not guild.get("setup_complete"):
        return {"ok": False, "text": "Rond eerst de instellingen af."}
    values = _raw_options(options)
    instance = instance_by_id(str(values.get("dungeon") or ""))
    if instance is None:
        return {"ok": False, "text": "Kies een dungeon of raid."}
    try:
        starts_at = parse_command_when(str(values.get("wanneer") or ""), guild.get("settings"), now)
    except ValueError as error:
        if str(error) == "past":
            return {"ok": False, "text": "Kies een tijdstip in de toekomst."}
        return {"ok": False, "text": "Gebruik een datum zoals 29 okt 20:00 of 29-10 20:00."}
    try:
        given = [_command_cap(values.get(key)) for key in ("tank", "healer", "dps")]
    except ValueError:
        return {"ok": False, "text": "Die plekken passen niet in deze dungeon of raid."}
    if any(cap is None for cap in given):
        if any(cap is not None for cap in given) or int(instance["size"]) != 5:
            return {"ok": False, "text": "Vul tank, healer en dps in."}
        caps = [1, 1, 3]
    else:
        caps = given
    limit = int(instance["size"])
    if any(cap < 0 or cap > limit for cap in caps) or sum(caps) < 1 or sum(caps) > limit:
        return {"ok": False, "text": "Die plekken passen niet in deze dungeon of raid."}
    rule_id = str(values.get("loot") or "") or ("group" if limit == 5 else "mainspec")
    if loot_rule(rule_id) is None:
        return {"ok": False, "text": "Kies een lootregel."}
    weeks = values.get("weken")
    repeat = "once" if weeks in (None, "") else "week"
    starts = collect_starts(starts_at, repeat, weeks or 2, [])
    if not starts:
        return {"ok": False, "text": "Acht raids tegelijk is het maximum."}
    channel_id = event_channel(db.wow_settings(guild.get("settings")), instance)
    sendable = {
        str(channel["id"])
        for channel in guild.get("channels") or []
        if channel.get("bot_can_send")
    }
    if not channel_id or channel_id not in sendable:
        return {"ok": False, "text": "Kies eerst een kanaal in de instellingen."}
    title = str(values.get("titel") or "").strip()[:80] or instance["name"]
    note = note_clean(values.get("notitie"), guild)
    return {
        "ok": True,
        "title": title,
        "note": note,
        "starts": starts,
        "caps": caps,
        "channel_id": channel_id,
        "instance_id": instance["id"],
        "size": limit,
        "loot": rule_id,
    }


def raid_command_reply(guild, title, planned, raids):
    when = discord_when(planned["starts"][0], guild.get("settings"))
    posted = [raid for raid in raids if raid and raid.get("message_id")]
    count = len(planned["starts"])
    link = ""
    if posted:
        url = discord_url(guild["id"], posted[0].get("channel_id"), posted[0].get("message_id"))
        if url:
            link = f"\n{url}"
    if count == 1:
        if posted:
            return f"**{title}** staat in Discord voor {when}.{link}"
        return f"**{title}** staat gepland voor {when}. Hij wacht tot er plek is in Discord."
    text = f"**{title}** is {count} keer gepland, vanaf {when}."
    if posted:
        return f"{text} De eerste staat in Discord.{link}"
    return f"{text} Ze wachten tot er plek is in Discord."


def save_raid_command(guild_id, user_id, created_by, role_ids, options, now=None):
    guild = db.guild_by_id(guild_id)
    planned = prepare_raid_command(guild, user_id, role_ids, options, now)
    if not planned["ok"]:
        return planned
    ids = []
    for starts_at in planned["starts"]:
        ids.append(db.create_raid(
            guild_id,
            planned["title"],
            starts_at,
            planned["caps"][0],
            planned["caps"][1],
            planned["caps"][2],
            planned["channel_id"],
            created_by or "Officer",
            planned["size"],
            planned["instance_id"],
            planned["note"],
            "scheduled",
            planned["loot"],
        ))
    fresh = db.guild_by_id(guild_id)
    try:
        problem = release_raids(fresh)
    except discord_api.DiscordError as error:
        log.warning("Could not post a raid from /raid: %s", error.status)
        problem = "discord"
    if problem:
        return {"ok": False, "text": "Opgeslagen. Discord kon de raid niet plaatsen."}
    return {"ok": True, "text": raid_command_reply(fresh, planned["title"], planned, [db.raid_by_id(raid_id) for raid_id in ids])}


def _draft_button(label, custom_id, style=2):
    return {"type": 2, "style": style, "label": label[:80], "custom_id": custom_id}


def _draft_row(components):
    return {"type": 1, "components": components}


def _draft_text(custom_id, label, placeholder, required, max_length, value=""):
    field = {
        "type": 4,
        "custom_id": custom_id,
        "label": label[:45],
        "style": 1,
        "placeholder": placeholder[:100],
        "required": required,
        "max_length": max_length,
    }
    if value:
        field["value"] = value[:max_length]
    return {"type": 1, "components": [field]}


def raid_draft_options(draft):
    """The same fields the one-step checker already understands."""
    options = [
        {"name": "dungeon", "value": draft.get("instance_id") or ""},
        {"name": "wanneer", "value": draft.get("when_text") or ""},
    ]
    if draft.get("tank_cap") is not None:
        options.extend([
            {"name": "tank", "value": draft["tank_cap"]},
            {"name": "healer", "value": draft["healer_cap"]},
            {"name": "dps", "value": draft["dps_cap"]},
        ])
    if draft.get("loot"):
        options.append({"name": "loot", "value": draft["loot"]})
    if draft.get("title"):
        options.append({"name": "titel", "value": draft["title"]})
    if draft.get("note"):
        options.append({"name": "notitie", "value": draft["note"]})
    if draft.get("weeks") and int(draft["weeks"]) >= 2:
        options.append({"name": "weken", "value": int(draft["weeks"])})
    return options


def raid_draft_apply(draft, guild, action, value, now=None):
    """Move one step. A bad answer stays on the same step."""
    updated = dict(draft)
    instance = instance_by_id(draft.get("instance_id") or "")
    if action == "dungeon":
        found = instance_by_id(str(value or ""))
        if found is None:
            return draft, "Kies een dungeon of raid."
        updated["instance_id"] = found["id"]
        updated["step"] = "when"
        return updated, ""
    if action == "when":
        if isinstance(value, dict):
            typed = " ".join(str(value.get("when") or "").split())
            day = str(value.get("day") or "").strip()
            clock = str(value.get("time") or "").strip()
            if typed:
                text = typed
            elif day and clock:
                text = f"{day} {clock}"
            else:
                return draft, "Kies een dag en een tijd, of typ een datum."
        else:
            text = " ".join(str(value or "").split())
        try:
            parse_command_when(text, guild.get("settings"), now)
        except ValueError as error:
            if str(error) == "past":
                return draft, "Kies een tijdstip in de toekomst."
            return draft, "Gebruik een datum zoals 29 okt 20:00 of 29-10 20:00."
        updated["when_text"] = text
        updated["step"] = "caps"
        return updated, ""
    if action == "caps_keep":
        if instance is None or int(instance["size"]) != 5:
            return draft, "Vul tank, healer en dps in."
        updated["tank_cap"] = 1
        updated["healer_cap"] = 1
        updated["dps_cap"] = 3
        updated["step"] = "loot"
        return updated, ""
    if action == "caps":
        if instance is None:
            return draft, "Kies eerst een dungeon of raid."
        try:
            caps = [_command_cap((value or {}).get(key)) for key in ("tank", "healer", "dps")]
        except ValueError:
            return draft, "Die plekken passen niet in deze dungeon of raid."
        if any(cap is None for cap in caps):
            return draft, "Vul tank, healer en dps in."
        limit = int(instance["size"])
        if any(cap < 0 or cap > limit for cap in caps) or sum(caps) < 1 or sum(caps) > limit:
            return draft, "Die plekken passen niet in deze dungeon of raid."
        updated["tank_cap"], updated["healer_cap"], updated["dps_cap"] = caps
        updated["step"] = "loot"
        return updated, ""
    if action in ("loot_keep", "loot"):
        if instance is None:
            return draft, "Kies eerst een dungeon of raid."
        rule_id = "group" if int(instance["size"]) == 5 else "mainspec"
        if action == "loot":
            rule_id = str(value or "")
        if loot_rule(rule_id) is None:
            return draft, "Kies een lootregel."
        updated["loot"] = rule_id
        updated["step"] = "title"
        return updated, ""
    if action == "title_keep":
        updated["title"] = None
        updated["note"] = None
        updated["step"] = "weeks"
        return updated, ""
    if action == "title":
        updated["title"] = str((value or {}).get("titel") or "").strip()[:80] or None
        updated["note"] = note_clean((value or {}).get("notitie"), guild)
        updated["step"] = "weeks"
        return updated, ""
    if action == "weeks":
        try:
            weeks = int(value)
        except (TypeError, ValueError):
            return draft, "Kies hoeveel weken."
        if weeks < 1 or weeks > 8:
            return draft, "Kies hoeveel weken."
        updated["weeks"] = weeks
        updated["step"] = "confirm"
        return updated, ""
    return draft, "Deze stap is voorbij."


def raid_when_choices(settings, now=None):
    """The next 24 days, and raid times from 18:00 to 23:45."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    if now is None:
        now = datetime.now(zone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)
    start = now.date()
    days = []
    for offset in range(24):
        local = start + timedelta(days=offset)
        label = f"{DUTCH_DAYS[local.weekday()]} {local.day} {DUTCH_MONTHS[local.month - 1]}"
        option = {"label": label, "value": f"{local.year:04d}-{local.month:02d}-{local.day:02d}"}
        if local.year != start.year:
            option["description"] = str(local.year)
        days.append(option)
    times = []
    minute = 18 * 60
    while minute <= 23 * 60 + 45:
        label = f"{minute // 60:02d}:{minute % 60:02d}"
        times.append({"label": label, "value": label})
        minute += 15
    return days, times


def _draft_label(label, component, description=""):
    row = {"type": 18, "label": label[:45], "component": component}
    if description:
        row["description"] = description[:100]
    return row


def raid_draft_modal(draft, guild=None, now=None):
    draft_id = draft["id"]
    instance = instance_by_id(draft.get("instance_id") or "")
    step = draft.get("step")
    if step == "when":
        days, times = raid_when_choices((guild or {}).get("settings"), now)
        return {
            "custom_id": f"ikrm:{draft_id}:when",
            "title": "Datum",
            "components": [
                _draft_label("Dag", {
                    "type": 3,
                    "custom_id": "day",
                    "placeholder": "Kies een dag",
                    "required": False,
                    "min_values": 0,
                    "options": days,
                }),
                _draft_label("Tijd", {
                    "type": 3,
                    "custom_id": "time",
                    "placeholder": "Kies een tijd",
                    "required": False,
                    "min_values": 0,
                    "options": times,
                }),
                _draft_label(
                    "Of typ zelf",
                    {
                        "type": 4,
                        "custom_id": "when",
                        "style": 1,
                        "placeholder": "15 dec 20:15",
                        "required": False,
                        "max_length": 32,
                    },
                    "Dit vervangt de keuzes hierboven",
                ),
            ],
        }
    if step == "caps":
        filled = ("1", "1", "3") if instance and int(instance["size"]) == 5 else ("", "", "")
        return {
            "custom_id": f"ikrm:{draft_id}:caps",
            "title": "Plekken",
            "components": [
                _draft_text("tank", "Tank", "1", True, 2, filled[0]),
                _draft_text("healer", "Healer", "1", True, 2, filled[1]),
                _draft_text("dps", "DPS", "3", True, 2, filled[2]),
            ],
        }
    if step == "title":
        shown_note = note_display(draft.get("note"), guild)[:400]
        return {
            "custom_id": f"ikrm:{draft_id}:text",
            "title": "Titel en notitie",
            "components": [
                _draft_text("titel", "Titel", (instance or {}).get("name") or "Titel", False, 80, draft.get("title") or ""),
                {
                    "type": 1,
                    "components": [{
                        "type": 4,
                        "custom_id": "notitie",
                        "label": "Notitie",
                        "style": 2,
                        "placeholder": "Typ @ en de naam van een rol of iemand",
                        "required": False,
                        "max_length": 400,
                        **({"value": shown_note} if shown_note else {}),
                    }],
                },
            ],
        }
    return None


def raid_draft_view(draft, guild, error=""):
    """The prompt for whatever is still open, plus the answers already given."""
    draft_id = draft["id"]
    instance = instance_by_id(draft.get("instance_id") or "") if draft.get("instance_id") else None
    lines = ["**Raid plannen**"]
    if instance:
        lines.append(f"Dungeon: {instance['name']} · {instance['size']}")
    if draft.get("when_text"):
        shown = draft["when_text"]
        try:
            shown = discord_when(parse_command_when(draft["when_text"], guild.get("settings")), guild.get("settings"))
        except ValueError:
            pass
        lines.append(f"Wanneer: {shown}")
    if draft.get("tank_cap") is not None:
        lines.append(f"Plekken: {draft['tank_cap']} tank · {draft['healer_cap']} healer · {draft['dps_cap']} DPS")
    if draft.get("loot"):
        rule = loot_rule(draft["loot"])
        lines.append(f"Loot: {rule['discord'] if rule else draft['loot']}")
    if draft.get("step") in ("weeks", "confirm"):
        lines.append(f"Titel: {draft.get('title') or (instance['name'] if instance else '—')}")
        lines.append(f"Notitie: {note_display(draft.get('note'), guild) or 'geen'}")
    if draft.get("weeks"):
        weeks = int(draft["weeks"])
        lines.append("Weken: alleen deze datum" if weeks < 2 else f"Weken: {weeks}")
    step = draft.get("step") or "dungeon"
    question = {
        "dungeon": "Kies een dungeon of raid.",
        "when": "Kies een dag en een tijd. Een andere datum typ je zelf.",
        "caps": "Plekken staan op 1 tank, 1 healer en 3 DPS." if instance and int(instance["size"]) == 5 else "Vul tank, healer en DPS in.",
        "loot": f"Loot staat op {(loot_rule('group' if instance and int(instance['size']) == 5 else 'mainspec') or {}).get('discord', '')}.",
        "title": f"De titel wordt {(instance or {}).get('name') or 'de dungeon'}. Een notitie is niet nodig.",
        "weeks": "Eén datum, of een paar weken achter elkaar?",
        "confirm": "Plaatsen maakt de raid aan.",
    }.get(step, "Kies een dungeon of raid.")
    lines.extend(["", question])
    if error:
        lines.append(error)
    cancel = _draft_button("Annuleren", f"ikrx:{draft_id}")
    components = []
    if step == "dungeon":
        # Discord allows 25 choices per menu and 5 rows. One row is Cancel.
        # Raids and dungeons stay in their own menus.
        catalog = instances()
        menus = [
            ("Kies een raid", "Meer raids", [item for item in catalog if item["kind"] == "raid"]),
            ("Kies een dungeon", "Meer dungeons", [item for item in catalog if item["kind"] == "dungeon"]),
        ]
        index = 0
        for first_label, more_label, items in menus:
            chunks = [items[start:start + 25] for start in range(0, len(items), 25)]
            for chunk_index, chunk in enumerate(chunks):
                if index >= 4 or not chunk:
                    break
                options = [
                    {"label": item["name"][:100], "value": item["id"][:100], "description": _menu_description(item)}
                    for item in chunk
                ]
                components.append(_draft_row([{
                    "type": 3,
                    "custom_id": f"ikrd:{draft_id}" if index == 0 else f"ikrd:{draft_id}:{index}",
                    "placeholder": first_label if chunk_index == 0 else more_label,
                    "options": options,
                }]))
                index += 1
        components.append(_draft_row([cancel]))
    elif step == "when":
        components.append(_draft_row([_draft_button("Dag en tijd kiezen", f"ikrw:{draft_id}", 1), cancel]))
    elif step == "caps" and instance and int(instance["size"]) == 5:
        components.append(_draft_row([
            _draft_button("Zo laten", f"ikrc:{draft_id}", 1),
            _draft_button("Aanpassen", f"ikra:{draft_id}"),
            cancel,
        ]))
    elif step == "caps":
        components.append(_draft_row([_draft_button("Plekken invullen", f"ikra:{draft_id}", 1), cancel]))
    elif step == "loot":
        components.append(_draft_row([{
            "type": 3,
            "custom_id": f"ikrl:{draft_id}",
            "placeholder": "Kies een andere lootregel",
            "options": [{"label": item["discord"][:100], "value": item["id"]} for item in LOOT_RULES],
        }]))
        components.append(_draft_row([_draft_button("Zo laten", f"ikrk:{draft_id}", 1), cancel]))
    elif step == "title":
        components.append(_draft_row([
            _draft_button("Zo laten", f"ikrt:{draft_id}", 1),
            _draft_button("Aanpassen", f"ikrb:{draft_id}"),
            cancel,
        ]))
    elif step == "weeks":
        components.append(_draft_row([{
            "type": 3,
            "custom_id": f"ikrn:{draft_id}",
            "placeholder": "Hoeveel weken",
            "options": [{"label": "Alleen deze datum", "value": "1"}] + [
                {"label": f"{count} weken", "value": str(count)} for count in range(2, 9)
            ],
        }]))
        components.append(_draft_row([cancel]))
    else:
        components.append(_draft_row([_draft_button("Plaatsen", f"ikrp:{draft_id}", 1), cancel]))
    return {
        "content": "\n".join(lines)[:2000],
        "components": components,
        "allowed_mentions": {"parse": []},
    }


def _draft_callback(interaction_id, token, kind, data):
    discord_api.interaction_callback(interaction_id, token, kind=kind, data=data)


def begin_raid_prompt(guild_id, user_id, created_by, role_ids):
    guild = db.guild_by_id(guild_id)
    if guild is None or guild.get("approval") != "approved" or db.guild_game(guild.get("settings")) != "wow":
        return {"content": "Dit commando werkt op een World of Warcraft server.", "flags": 64}
    if not _can_post_raid(guild, user_id, role_ids):
        return {"content": "Je hebt niet de rol die nodig is om een raid te plaatsen.", "flags": 64}
    if not guild.get("setup_complete"):
        return {"content": "Rond eerst de instellingen af.", "flags": 64}
    draft_id = db.create_raid_draft(guild_id, user_id, created_by)
    view = raid_draft_view(db.raid_draft(draft_id), guild)
    view["flags"] = 64
    return view


def continue_raid_prompt(guild_id, user_id, role_ids, custom_id, values, fields):
    """Follow a button, a list or a filled-in form. Returns the Discord callback kind and data."""
    parts = str(custom_id or "").split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        return 4, {"content": "Deze prompt is verlopen. Gebruik /raid opnieuw.", "flags": 64}
    action, draft_id, extra = parts[0], int(parts[1]), parts[2] if len(parts) > 2 else ""
    draft = db.raid_draft(draft_id)
    guild = db.guild_by_id(guild_id)
    if draft is None or guild is None or str(draft["guild_id"]) != str(guild_id):
        return 7, {"content": "Deze prompt is verlopen. Gebruik /raid opnieuw.", "components": []}
    if str(draft["user_id"]) != str(user_id):
        return 4, {"content": "Dit is niet jouw prompt.", "flags": 64}
    if not _can_post_raid(guild, user_id, role_ids):
        return 7, {"content": "Je hebt niet de rol die nodig is om een raid te plaatsen.", "components": []}
    if action == "ikrx":
        db.delete_raid_draft(draft_id)
        return 7, {"content": "Geannuleerd.", "components": []}
    if action in ("ikrw", "ikra", "ikrb"):
        modal = raid_draft_modal(draft, guild)
        if modal is None:
            view = raid_draft_view(draft, guild, "Deze stap is voorbij.")
            return 7, view
        return 9, modal
    if action == "ikrp":
        result = save_raid_command(guild_id, user_id, draft.get("created_by"), role_ids, raid_draft_options(draft))
        if result["ok"]:
            db.delete_raid_draft(draft_id)
            return 7, {"content": result["text"], "components": []}
        view = raid_draft_view(draft, guild, result["text"])
        return 7, view
    value = None
    change = ""
    if action == "ikrd":
        # ikrd:{draft}:2 is the second menu. The extra part is ignored.
        change, value = "dungeon", (values or [""])[0]
    elif action == "ikrm" and extra == "when":
        change, value = "when", fields or {}
    elif action == "ikrc":
        change = "caps_keep"
    elif action == "ikrm" and extra == "caps":
        change, value = "caps", fields or {}
    elif action == "ikrk":
        change = "loot_keep"
    elif action == "ikrl":
        change, value = "loot", (values or [""])[0]
    elif action == "ikrt":
        change = "title_keep"
    elif action == "ikrm" and extra == "text":
        change, value = "title", fields or {}
    elif action == "ikrn":
        change, value = "weeks", (values or [""])[0]
    else:
        view = raid_draft_view(draft, guild, "Deze stap is voorbij.")
        return 7, view
    updated, error = raid_draft_apply(draft, guild, change, value)
    if not error:
        db.save_raid_draft(draft_id, **{
            key: updated[key]
            for key in (
                "instance_id", "when_text", "tank_cap", "healer_cap", "dps_cap",
                "loot", "title", "note", "weeks", "step",
            )
        })
        updated = db.raid_draft(draft_id) or updated
    view = raid_draft_view(updated, guild, error)
    return 7, view


def answer_create_raid(guild_id, user_id, created_by, role_ids, interaction_id, token, data):
    if (data or {}).get("name") != "raid":
        return
    _draft_callback(interaction_id, token, 4, begin_raid_prompt(guild_id, user_id, created_by, role_ids))


def answer_raid_prompt(guild_id, user_id, role_ids, interaction_id, token, custom_id, values=None, fields=None):
    kind, data = continue_raid_prompt(guild_id, user_id, role_ids, custom_id, values, fields)
    _draft_callback(interaction_id, token, kind, data)


def class_choices():
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "specs": [{"id": spec["id"], "name": spec["name"]} for spec in specializations(item)],
        }
        for item in playable_classes()
    ]


def format_when(starts_at, settings):
    local = _local_start(starts_at, settings)
    return f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]} {local.year} · {local:%H:%M}"


def format_span(starts_at, ends_at, settings):
    """Start on its own, or start through end. The same day keeps one date."""
    start = format_when(starts_at, settings)
    if not ends_at:
        return start
    start_local = _local_start(starts_at, settings)
    end_local = _local_start(ends_at, settings)
    if start_local.date() == end_local.date():
        return f"{start}–{end_local:%H:%M}"
    return f"{start} – {format_when(ends_at, settings)}"


def parse_starts(value, settings):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    raw = (value or "").strip()
    if not raw:
        raise ValueError("when")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is not None:
        raise ValueError("when")
    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    return moment.replace(tzinfo=zone).isoformat()


def parse_ends(value, settings, starts_at):
    """Blank is no end time. A filled end has to be later than the start."""
    raw = (value or "").strip()
    if not raw:
        return None
    ends_at = parse_starts(raw, settings)
    if _aware(ends_at) <= _aware(starts_at):
        raise ValueError("end")
    return ends_at


_COMMAND_MONTHS = {name: index for index, name in enumerate(DUTCH_MONTHS, 1)}
for _index, _name in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1):
    _COMMAND_MONTHS.setdefault(_name, _index)
for _index, _name in enumerate(
    ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"],
    1,
):
    _COMMAND_MONTHS[_name] = _index


def parse_command_when(text, settings, now=None):
    """Parse '29 okt 20:00' or '29-10 20:00' in the guild timezone. A missing year rolls forward."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    raw = " ".join((text or "").casefold().split())
    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    if now is None:
        now = datetime.now(zone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)
    year = month = day = hour = minute = None
    matched = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", raw)
    if matched:
        year, month, day, hour, minute = matched.groups()
    matched = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s+(\d{1,2}):(\d{2})", raw)
    if matched:
        day, month, year, hour, minute = matched.groups()
    matched = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})", raw)
    if matched:
        day, month, hour, minute = matched.groups()
    matched = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})", raw)
    if matched:
        day, month_name, year, hour, minute = matched.groups()
        month = _COMMAND_MONTHS.get(month_name)
    matched = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\s+(\d{1,2}):(\d{2})", raw)
    if matched:
        day, month_name, hour, minute = matched.groups()
        month = _COMMAND_MONTHS.get(month_name)
    if month is None or day is None:
        raise ValueError("when")
    try:
        hour = int(hour)
        minute = int(minute)
        month = int(month)
        day = int(day)
    except (TypeError, ValueError):
        raise ValueError("when") from None
    if hour > 23 or minute > 59:
        raise ValueError("when")

    def build(at_year):
        try:
            return datetime(int(at_year), month, day, hour, minute, tzinfo=zone)
        except ValueError:
            return None

    if year is None:
        candidate = build(now.year)
        if candidate is None or candidate <= now:
            candidate = build(now.year + 1)
    else:
        candidate = build(year)
    if candidate is None:
        raise ValueError("when")
    if candidate <= now:
        raise ValueError("past")
    return candidate.isoformat()


def input_when(starts_at, settings):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    moment = datetime.fromisoformat(starts_at)
    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone).strftime("%Y-%m-%dT%H:%M")


def _aware(value, settings=None):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        zone = ZoneInfo((settings or {}).get("timezone") or "UTC") if settings else timezone.utc
        moment = moment.replace(tzinfo=zone)
    return moment


def may_sign(settings, role_ids):
    """An empty signup role list means anyone who can see the channel."""
    needed = set(db.wow_settings(settings).get("signup_roles") or [])
    if not needed:
        return True
    return bool(needed & {str(role_id) for role_id in (role_ids or [])})


def reminder_plan(raid, settings, now):
    """Which reminder to send now.

    Returns minutes, whether to mark the first reminder done, and whether to mark the second.
    A raid created after a reminder moment does not get that one. When the closer reminder
    is already due, the earlier one is marked done without a second ping.
    """
    from datetime import timedelta

    if raid.get("status") != "open":
        return 0, False, False
    first = db.parse_reminder_minutes(raid.get("reminder_minutes"))
    second = db.parse_second_reminder(raid.get("reminder_2_minutes"), first)
    start = _aware(raid["starts_at"], settings)
    created = _aware(raid["created_at"])

    def due(minutes, sent):
        if not minutes or sent:
            return False
        moment = start - timedelta(minutes=minutes)
        if created >= moment:
            return False
        return moment <= now < start

    first_due = due(first, raid.get("reminder_sent"))
    second_due = due(second, raid.get("reminder_2_sent"))
    if second_due:
        return second, bool(first_due), True
    if first_due:
        return first, True, False
    return 0, False, False


def reminder_skips(raid, settings, now):
    """A raid posted after a reminder moment does not send that reminder later."""
    from datetime import timedelta

    first = db.parse_reminder_minutes(raid.get("reminder_minutes"))
    second = db.parse_second_reminder(raid.get("reminder_2_minutes"), first)
    start = _aware(raid["starts_at"], settings)
    skip_first = bool(first) and now >= start - timedelta(minutes=first)
    skip_second = bool(second) and now >= start - timedelta(minutes=second)
    return skip_first, skip_second


def reminder_lead(minutes):
    if int(minutes) == 60:
        return "Over een uur"
    return f"Over {int(minutes)} minuten"


def close_due(raid, settings, now):
    if not db.wow_settings(settings).get("close_at_start") or raid.get("status") != "open":
        return False
    return now >= _aware(raid["starts_at"], settings)


def icon_url(guild):
    icon_hash = guild.get("icon_hash") or ""
    if not re.fullmatch(r"a_[0-9a-fA-F]{16,}|[0-9a-fA-F]{16,}", icon_hash):
        return None
    extension = "gif" if icon_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/icons/{guild['id']}/{icon_hash}.{extension}"


def discord_url(guild_id, channel_id, message_id):
    if not message_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


_LANE_NAMES = {"tank": "Tank", "melee": "Melee", "ranged": "Ranged", "healer": "Healer"}


def party_total(raid):
    try:
        count = int((raid or {}).get("party_count") or 1)
    except (TypeError, ValueError):
        count = 1
    return min(db.MAX_PARTIES, max(1, count))


def column_party(target):
    """A roster column is party 1's role, reserve, or p3tank for a later party."""
    if target == "reserve":
        return 1, "reserve"
    if target in LANE_ORDER:
        return 1, target
    matched = re.fullmatch(r"p(\d+)(tank|melee|ranged|healer)", target or "")
    if not matched:
        return None
    party_no = int(matched.group(1))
    if party_no < 2 or party_no > db.MAX_PARTIES:
        return None
    return party_no, matched.group(2)


def move_label(target):
    found = column_party(target)
    if found is None:
        return None
    party_no, lane = found
    if lane == "reserve":
        return "Reserve"
    name = _LANE_NAMES[lane]
    if party_no <= 1:
        return name
    return f"Party {party_no} · {name}"


def spec_lanes(class_id, spec_id):
    key = (class_id, spec_id)
    return [lane for lane in LANE_ORDER if key in LANES[lane]]


def roster_column(signup):
    if signup.get("state") == "reserve":
        return "reserve"
    lane = display_lane(signup)
    if lane not in LANE_ORDER:
        return ""
    party_no = int(signup.get("party") or 1)
    if party_no >= 2:
        return f"p{party_no}{lane}"
    return lane


def move_plan(raid, signup, signups, target):
    """Where an officer drop lands. A full role lands on reserve. Late stays late when a spot is open."""
    if not raid or raid.get("status") != "open":
        return None
    found = column_party(target)
    if found is None:
        return None
    if signup.get("state") not in ("main", "late", "reserve"):
        return None
    source = roster_column(signup)
    if column_party(source) is None:
        return None
    party_no, target_lane = found
    if party_no > party_total(raid):
        return None
    if target_lane == "reserve":
        if source == "reserve":
            return None
        role = display_lane(signup)
        if role not in LANE_ORDER:
            return None
        return {"role": role, "state": "reserve", "party": 1, "source": source, "landed": "reserve"}
    if target_lane not in spec_lanes(signup.get("class_id"), signup.get("spec_id")):
        return None
    bucket = cap_key(target_lane)
    caps = {"tank": raid.get("tank_cap") or 0, "healer": raid.get("healer_cap") or 0, "dps": raid.get("dps_cap") or 0}
    taken = sum(
        1
        for other in signups or []
        if str(other.get("user_id")) != str(signup.get("user_id"))
        and other.get("state") in ("main", "late")
        and int(other.get("party") or 1) == party_no
        and cap_key(other.get("role")) == bucket
    )
    if taken < int(caps.get(bucket) or 0):
        state = "late" if signup.get("state") == "late" else "main"
    else:
        state = "reserve"
    landed = "reserve" if state == "reserve" else target
    current_role = signup.get("role") if signup.get("role") in LANE_ORDER else display_lane(signup)
    same_party = int(signup.get("party") or 1) == (1 if state == "reserve" else party_no)
    if landed == source and target_lane == current_role and state == signup.get("state") and same_party:
        return None
    return {
        "role": target_lane,
        "state": state,
        "party": 1 if state == "reserve" else party_no,
        "source": source,
        "landed": landed,
    }


def move_notice(user_id, source, landed, role):
    who = f"<@{user_id}>"
    if source != landed:
        return f"{who} is verplaatst van {move_label(source)} naar {move_label(landed)}."
    return f"{who} staat in de reserve als {move_label(role)}."


def announce_move(raid, signup, plan):
    """Tell the raid channel, or the question thread when that raid has one."""
    channel_id = raid.get("thread_id") or raid.get("channel_id")
    if not channel_id:
        return
    discord_api.send_payload(
        channel_id,
        {
            "content": move_notice(signup["user_id"], plan["source"], plan["landed"], plan["role"])[:2000],
            "allowed_mentions": {"parse": [], "users": [str(signup["user_id"])]},
        },
    )


def _roster_person(signup, party_count):
    class_name, spec_name = choice_names(signup.get("class_id"), signup.get("spec_id"))
    column = roster_column(signup)
    movable = signup.get("state") in ("main", "late", "reserve") and column_party(column) is not None
    lanes = spec_lanes(signup.get("class_id"), signup.get("spec_id"))
    allowed = []
    if movable:
        allowed = list(lanes)
        for party_no in range(2, party_count + 1):
            allowed.extend(f"p{party_no}{lane}" for lane in lanes)
        allowed.append("reserve")
    return {
        "user_id": str(signup.get("user_id") or ""),
        "name": signup["name"],
        "class_id": signup.get("class_id") or "",
        "class_name": class_name,
        "class_color": class_color(signup.get("class_id")),
        "spec_id": signup.get("spec_id") or "",
        "spec_name": spec_name,
        "role": signup.get("role"),
        "role_label": ROLE_LABELS.get(display_lane(signup), signup.get("role") or ""),
        "late": signup.get("state") == "late",
        "note": signup.get("note") or "",
        "lanes": ",".join(allowed),
        "moves": [{"id": lane, "label": move_label(lane)} for lane in allowed if lane != column],
    }


def _role_groups(raid, buckets, prefix=""):
    return [
        {"label": f"Tank {len(buckets['tank'])}/{raid['tank_cap']}", "people": buckets["tank"], "reserve": False, "lane": prefix + "tank"},
        {"label": f"Melee {len(buckets['melee'])}", "people": buckets["melee"], "reserve": False, "lane": prefix + "melee"},
        {"label": f"Ranged {len(buckets['ranged'])}", "people": buckets["ranged"], "reserve": False, "lane": prefix + "ranged"},
        {"label": f"Healer {len(buckets['healer'])}/{raid['healer_cap']}", "people": buckets["healer"], "reserve": False, "lane": prefix + "healer"},
    ]


def _event_groups(signups):
    coming = []
    tentative = []
    absent = []
    for signup in signups or []:
        person = _roster_person(signup, 1)
        state = signup.get("state")
        if state in ("main", "late"):
            coming.append(person)
        elif state == "tentative":
            tentative.append(person)
        elif state == "absent":
            absent.append(person)
    groups = [{"label": f"Signed up {len(coming)}", "people": coming, "reserve": False, "lane": ""}]
    if tentative:
        groups.append({"label": f"Tentative {len(tentative)}", "people": tentative, "reserve": False, "lane": ""})
    if absent:
        groups.append({"label": f"Absent {len(absent)}", "people": absent, "reserve": False, "lane": ""})
    return groups


def roster_groups(raid, signups):
    if is_event(raid):
        return _event_groups(signups)
    party_count = party_total(raid)
    first = {key: [] for key in ("tank", "melee", "ranged", "healer", "reserve", "bench", "tentative", "absent")}
    extras = {party_no: {key: [] for key in LANE_ORDER} for party_no in range(2, party_count + 1)}
    for signup in signups or []:
        person = _roster_person(signup, party_count)
        state = signup.get("state")
        if state == "reserve":
            first["reserve"].append(person)
        elif state == "bench":
            first["bench"].append(person)
        elif state == "tentative":
            first["tentative"].append(person)
        elif state == "absent":
            first["absent"].append(person)
        else:
            lane = display_lane(signup)
            party_no = int(signup.get("party") or 1)
            home = extras.get(party_no, first)
            if lane in home:
                home[lane].append(person)
    groups = _role_groups(raid, first)
    groups.append({"label": f"Reserve {len(first['reserve'])}", "people": first["reserve"], "reserve": True, "lane": "reserve"})
    if first["bench"]:
        groups.append({"label": f"Bench {len(first['bench'])}", "people": first["bench"], "reserve": False, "lane": ""})
    if first["tentative"]:
        groups.append({"label": f"Tentative {len(first['tentative'])}", "people": first["tentative"], "reserve": False, "lane": ""})
    if first["absent"]:
        groups.append({"label": f"Absent {len(first['absent'])}", "people": first["absent"], "reserve": False, "lane": ""})
    if party_count < 2:
        return groups
    roster = [{"label": "Party 1", "people": [], "reserve": False, "lane": "", "heading": True}] + groups
    for party_no in range(2, party_count + 1):
        roster.append({"label": f"Party {party_no}", "people": [], "reserve": False, "lane": "", "heading": True})
        roster.extend(_role_groups(raid, extras[party_no], f"p{party_no}"))
    return roster


def relative_when(moment, now):
    """Dutch distance until the raid, counted from now."""
    seconds = int((moment - now).total_seconds())
    if seconds <= -3600:
        return "geweest"
    if seconds <= 0:
        return "begonnen"
    if seconds < 3600:
        count = max(1, (seconds + 59) // 60)
        unit = "minuut" if count == 1 else "minuten"
        return f"over {count} {unit}"
    if seconds < 86400:
        count = max(1, seconds // 3600)
        return f"over {count} uur"
    count = max(1, seconds // 86400)
    unit = "dag" if count == 1 else "dagen"
    return f"over {count} {unit}"


def _local_start(starts_at, settings):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    moment = datetime.fromisoformat(starts_at)
    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone)


def discord_when(starts_at, settings, now=None, ends_at=None):
    unix = int(_local_start(starts_at, settings).timestamp())
    date = f"<t:{unix}:D>"
    clock = f"<t:{unix}:t>"
    if ends_at:
        end_unix = int(_local_start(ends_at, settings).timestamp())
        clock = f"<t:{unix}:t>–<t:{end_unix}:t>"
        if _local_start(starts_at, settings).date() != _local_start(ends_at, settings).date():
            date = f"<t:{unix}:D>–<t:{end_unix}:D>"
    return f"{date} · {clock} · <t:{unix}:R>"


def _when_fields(starts_at, settings, ends_at=None):
    unix = int(_local_start(starts_at, settings).timestamp())
    date = f"\U0001F4C5 <t:{unix}:D>"
    clock = f"\U0001F550 <t:{unix}:t>"
    if ends_at:
        end_unix = int(_local_start(ends_at, settings).timestamp())
        clock = f"\U0001F550 <t:{unix}:t> – <t:{end_unix}:t>"
        if _local_start(starts_at, settings).date() != _local_start(ends_at, settings).date():
            date = f"\U0001F4C5 <t:{unix}:D> – <t:{end_unix}:D>"
    return [
        {"name": "\u200b", "value": date, "inline": True},
        {"name": "\u200b", "value": clock, "inline": True},
        {"name": "\u200b", "value": f"\u23F3 <t:{unix}:R>", "inline": True},
    ]


def _person_line(signup, *, reserve=False, grouped=False):
    parts = []
    class_icon = CLASS_MARK.get(signup.get("class_id"))
    spec_icon = SPEC_MARK.get((signup.get("class_id"), signup.get("spec_id")))
    if class_icon:
        parts.append(class_icon)
    if spec_icon:
        parts.append(spec_icon)
    mark = "".join(parts) or "▪️"
    text = f"{mark} **{signup['name']}**"
    if signup.get("state") == "late":
        text += " · Laat"
    if reserve:
        text += f" · {ROLE_LABELS.get(signup.get('role'), signup.get('role') or '')}"
    return text[:200]


def _absence_lines(signups):
    """A reason is only shown when someone signed off. Plain absence has no reason."""
    lines = []
    for signup in signups:
        reason = (signup.get("note") or "").strip()
        text = f"**{signup['name']}**"
        if reason:
            text += f" — {reason}"
        lines.append(text[:200])
    return lines or ["\u2014"]


def _roster_lines(signups, *, reserve=False, grouped=False):
    return [_person_line(signup, reserve=reserve, grouped=grouped) for signup in signups]


def _chunks(lines):
    if not lines:
        return ["\u2014"]
    blocks = []
    current = ""
    for line in lines:
        piece = line[:1000]
        if current and len(current) + 1 + len(piece) > 1000:
            blocks.append(current)
            current = piece
        elif current:
            current = current + "\n" + piece
        else:
            current = piece
    if current:
        blocks.append(current)
    return blocks


LOOT_RULES = [
    {
        "id": "group",
        "label": "Group loot",
        "detail": "Need, Greed, Pass",
        "discord": "Groepsloot · Need, Greed, Pass",
        "help": "Everyone can roll Need, Greed or Pass. The highest roll wins the item.",
    },
    {
        "id": "mainspec",
        "label": "Main spec over off spec",
        "detail": "",
        "discord": "Main spec boven off spec",
        "help": "A main spec takes the item before an off spec. People roll in chat.",
    },
    {
        "id": "softres",
        "label": "Soft reserve",
        "detail": "",
        "discord": "Soft reserve",
        "help": "Each player names one item beforehand. That item is theirs if it drops.",
    },
    {
        "id": "hardres",
        "label": "Hard reserve",
        "detail": "",
        "discord": "Hard reserve",
        "help": "One item is already promised to someone before the raid starts.",
    },
    {
        "id": "council",
        "label": "Loot council",
        "detail": "",
        "discord": "Loot council",
        "help": "Officers choose the player the item helps most.",
    },
]


def loot_rule(rule_id):
    for item in LOOT_RULES:
        if item["id"] == rule_id:
            return item
    return None


def loot_label(rule_id):
    rule = loot_rule(rule_id)
    if rule is None:
        return ""
    if rule["detail"]:
        return f"{rule['label']} · {rule['detail']}"
    return rule["label"]


def _two_column_fields(labels, lines_for):
    """Two roles per row. Both rows end with the same blank column, so Melee lines up with Healer."""
    fields = []
    overflow = []
    for keys in (("tank", "melee"), ("ranged", "healer")):
        for key in keys:
            blocks = _chunks(lines_for(key))
            fields.append({"name": labels[key][:256], "value": blocks[0], "inline": True})
            overflow.extend((f"{labels[key]} (continued)", block) for block in blocks[1:])
        fields.append({"name": "\u200b", "value": "\u200b", "inline": True})
    return fields, overflow


def _lane_fields(raid, people, grouped):
    buckets = {key: [] for key in LANE_ORDER}
    for signup in people:
        lane = display_lane(signup)
        if lane in buckets:
            buckets[lane].append(signup)
    class_order = {item["id"]: index for index, item in enumerate(playable_classes())}
    for group in buckets.values():
        group.sort(key=lambda signup: (class_order.get(signup.get("class_id"), 99), signup.get("name") or ""))
    labels = {
        "tank": f"Tank {len(buckets['tank'])}/{raid['tank_cap']}",
        "melee": f"Melee {len(buckets['melee'])}",
        "ranged": f"Ranged {len(buckets['ranged'])}",
        "healer": f"Healer {len(buckets['healer'])}/{raid['healer_cap']}",
    }
    fields, overflow = _two_column_fields(labels, lambda key: _roster_lines(buckets[key], grouped=grouped))
    fields.extend({"name": name[:256], "value": block, "inline": False} for name, block in overflow)
    return fields, buckets


def _event_rows(raid_id):
    def button(label, custom_id, style):
        return {"type": 2, "style": style, "label": label, "custom_id": custom_id}

    return [{
        "type": 1,
        "components": [
            button("Aanmelden", f"ikj:{raid_id}", 1),
            button("Voorlopig", f"ikv:{raid_id}", 2),
            button("Afwezig", f"ika:{raid_id}", 2),
            button("Afmelden", f"ikl:{raid_id}", 2),
            {"type": 2, "style": 2, "emoji": {"name": "\u2699\ufe0f"}, "custom_id": f"ike:{raid_id}"},
        ],
    }]


def _event_payload(guild, raid, signups):
    coming = []
    tentative = []
    absent = []
    for signup in signups or []:
        state = signup.get("state")
        if state in ("main", "late"):
            coming.append(signup)
        elif state == "tentative":
            tentative.append(signup)
        elif state == "absent":
            absent.append(signup)
    coming.sort(key=lambda row: (row.get("name") or "").casefold())
    tentative.sort(key=lambda row: (row.get("name") or "").casefold())
    absent.sort(key=lambda row: (row.get("name") or "").casefold())
    fields = _when_fields(raid["starts_at"], guild.get("settings"), raid.get("ends_at"))

    def add_block(title, lines):
        blocks = _chunks(lines)
        fields.append({"name": title[:256], "value": blocks[0], "inline": False})
        for block in blocks[1:]:
            fields.append({"name": f"{title} (continued)"[:256], "value": block, "inline": False})

    coming_lines = [
        f"**{signup.get('name') or 'Member'}**" + (" · Laat" if signup.get("state") == "late" else "")
        for signup in coming
    ]
    add_block(f"Aanwezig {len(coming)}", coming_lines)
    if tentative:
        add_block(
            f"Voorlopig {len(tentative)}",
            [f"**{signup.get('name') or 'Member'}**" for signup in tentative],
        )
    if absent:
        add_block(f"Afwezig {len(absent)}", _absence_lines(absent))
    note = note_display((raid.get("note") or "").strip(), guild)
    lines = []
    if note:
        lines.append(note[:400])
    if raid.get("status") != "open":
        lines.append("Gesloten")
    author = {"name": (guild.get("name") or "Ironkeep")[:256]}
    icon = icon_url(guild)
    if icon:
        author["icon_url"] = icon
    content = {
        "author": author,
        "title": (raid.get("title") or "Event")[:256],
        "color": 0xC6A15A,
        "fields": fields[:25],
    }
    description = "\n\n".join(lines)
    if description:
        content["description"] = description[:4096]
    embeds = [content]
    attached = _attached(raid, guild)
    attachments = [{"id": index, "filename": path.name} for index, path in enumerate(attached)]
    if any(path.name == "width.png" for path in attached):
        content["image"] = {"url": "attachment://width.png"}
    if any(path.name != "width.png" for path in attached):
        banner = next(path for path in attached if path.name != "width.png")
        embeds.insert(0, {"color": 0xC6A15A, "image": {"url": f"attachment://{banner.name}"}})
    text, allowed = _post_content(guild, raid)
    return {
        "content": text,
        "embeds": embeds,
        "attachments": attachments,
        "allowed_mentions": allowed,
        "components": [] if raid.get("status") != "open" else _event_rows(raid["id"]),
    }


def message_payload(guild, raid, signups):
    if is_event(raid):
        return _event_payload(guild, raid, signups)
    grouped = int(raid.get("size") or 0) >= 10
    party_count = party_total(raid)
    buckets = {key: [] for key in ("tank", "melee", "ranged", "healer", "reserve", "bench", "tentative", "absent")}
    extras = {party_no: [] for party_no in range(2, party_count + 1)}
    for signup in signups:
        state = signup.get("state")
        party_no = int(signup.get("party") or 1)
        if party_no in extras and state in ("main", "late"):
            extras[party_no].append(signup)
            continue
        if state == "reserve":
            buckets["reserve"].append(signup)
        elif state == "bench":
            buckets["bench"].append(signup)
        elif state == "tentative":
            buckets["tentative"].append(signup)
        elif state == "absent":
            buckets["absent"].append(signup)
        else:
            lane = display_lane(signup)
            if lane in buckets:
                buckets[lane].append(signup)
    class_order = {item["id"]: index for index, item in enumerate(playable_classes())}
    for people in buckets.values():
        people.sort(key=lambda signup: (class_order.get(signup.get("class_id"), 99), signup.get("name") or ""))
    dps_count = len(buckets["melee"]) + len(buckets["ranged"])
    labels = {
        "tank": f"Tank {len(buckets['tank'])}/{raid['tank_cap']}",
        "melee": f"Melee {len(buckets['melee'])}",
        "ranged": f"Ranged {len(buckets['ranged'])}",
        "healer": f"Healer {len(buckets['healer'])}/{raid['healer_cap']}",
        "reserve": f"Reserve {len(buckets['reserve'])}",
        "bench": f"Bank {len(buckets['bench'])}",
        "tentative": f"Voorlopig {len(buckets['tentative'])}",
        "absent": f"Afwezig {len(buckets['absent'])}",
    }
    fields, overflow = _two_column_fields(
        labels,
        lambda key: _roster_lines(buckets[key], grouped=grouped),
    )
    reserve_blocks = _chunks(_roster_lines(buckets["reserve"], reserve=True, grouped=grouped))
    fields.append({"name": labels["reserve"][:256], "value": reserve_blocks[0], "inline": False})
    overflow.extend((f"{labels['reserve']} (continued)", block) for block in reserve_blocks[1:])
    for name, block in overflow:
        fields.append({"name": name[:256], "value": block, "inline": False})
    for key in ("bench", "tentative", "absent"):
        if not buckets[key]:
            continue
        lines = _absence_lines(buckets[key]) if key == "absent" else _roster_lines(buckets[key], grouped=grouped)
        for block_index, block in enumerate(_chunks(lines)):
            name = labels[key] if block_index == 0 else f"{labels[key]} (continued)"
            fields.append({"name": name[:256], "value": block, "inline": False})
    fields = (_when_fields(raid["starts_at"], guild.get("settings"), raid.get("ends_at")) + fields)[:25]
    details = []
    if party_count >= 2 and raid.get("size"):
        seated = len(buckets["tank"]) + len(buckets["melee"]) + len(buckets["ranged"]) + len(buckets["healer"])
        details.append(f"Party 1 · {seated}/{raid['size']}")
    if raid.get("size"):
        details.append(f"{raid['size']} spelers")
    details.append(f"DPS {dps_count}/{raid['dps_cap']}")
    if raid["status"] != "open":
        details.append("Gesloten")
    when = " · ".join(details)
    note = note_display((raid.get("note") or "").strip(), guild)
    lines = []
    rule = loot_rule(raid.get("loot_rule"))
    if rule:
        lines.append(f"Loot · {rule['discord']}")
    if note:
        lines.append(note[:400])
    lines.append(when)
    description = "\n\n".join(lines)
    author = {"name": (guild.get("name") or "Ironkeep")[:256]}
    icon = icon_url(guild)
    if icon:
        author["icon_url"] = icon
    content = {
        "author": author,
        "title": (raid["title"] or "Raid")[:256],
        "description": description[:4096],
        "color": 0xC6A15A,
        "fields": fields,
    }
    embeds = [content]
    attached = _attached(raid, guild)
    attachments = [{"id": index, "filename": path.name} for index, path in enumerate(attached)]
    if any(path.name == "width.png" for path in attached):
        content["image"] = {"url": "attachment://width.png"}
    if any(path.name != "width.png" for path in attached):
        banner = next(path for path in attached if path.name != "width.png")
        embeds.insert(0, {"color": 0xC6A15A, "image": {"url": f"attachment://{banner.name}"}})
    for party_no in range(2, party_count + 1):
        party_fields, party_buckets = _lane_fields(raid, extras[party_no], grouped)
        party_taken = sum(len(party_buckets[key]) for key in LANE_ORDER)
        party_dps = len(party_buckets["melee"]) + len(party_buckets["ranged"])
        party_line = f"{party_taken}/{raid.get('size') or party_taken} · DPS {party_dps}/{raid['dps_cap']} · {discord_when(raid['starts_at'], guild.get('settings'), ends_at=raid.get('ends_at'))}"
        embeds.append({
            "title": f"Party {party_no}",
            "description": party_line[:4096],
            "color": 0xC6A15A,
            "fields": party_fields[:25],
        })
    text, allowed = _post_content(guild, raid)
    payload = {
        "content": text,
        "embeds": embeds,
        "attachments": attachments,
        "allowed_mentions": allowed,
        "components": [] if raid["status"] != "open" else _action_rows(raid["id"]),
    }
    return payload


def _mark_emoji(mark):
    matched = re.fullmatch(r"<:([A-Za-z0-9_]+):(\d+)>", mark or "")
    if not matched:
        return None
    return {"name": matched.group(1), "id": matched.group(2)}


def _role_button(label, custom_id, style, lane):
    row = {"type": 2, "style": style, "label": label, "custom_id": custom_id}
    emoji = _mark_emoji(ROLE_MARK.get(lane))
    if emoji:
        row["emoji"] = emoji
    return row


def _action_rows(raid_id):
    def button(label, custom_id, style):
        return {"type": 2, "style": style, "label": label, "custom_id": custom_id}

    return [
        {
            "type": 1,
            "components": [
                _role_button("Tank", f"ikt:{raid_id}", 1, "tank"),
                _role_button("Melee", f"ikm:{raid_id}", 4, "melee"),
                _role_button("Ranged", f"ikn:{raid_id}", 4, "ranged"),
                _role_button("Healer", f"ikh:{raid_id}", 3, "healer"),
                {"type": 2, "style": 2, "emoji": {"name": "\u2699\ufe0f"}, "custom_id": f"ike:{raid_id}"},
            ],
        },
        {
            "type": 1,
            "components": [
                button("Bank", f"ikb:{raid_id}", 2),
                button("Laat", f"ikd:{raid_id}", 2),
                button("Voorlopig", f"ikv:{raid_id}", 2),
                button("Afwezig", f"ika:{raid_id}", 2),
                button("Afmelden", f"ikl:{raid_id}", 2),
            ],
        },
    ]


def _option_emoji(class_id, spec_id):
    return _mark_emoji(SPEC_MARK.get((class_id, spec_id)))


def _spec_choices(lane):
    allowed = set(LANES[lane])
    options = []
    for klass in playable_classes():
        for spec in specializations(klass):
            if (klass["id"], spec["id"]) not in allowed:
                continue
            option = {"label": spec["name"][:100], "value": f"{klass['id']}:{spec['id']}", "description": klass["name"][:100]}
            emoji = _option_emoji(klass["id"], spec["id"])
            if emoji:
                option["emoji"] = emoji
            options.append(option)
    return options


def _choice_text(lane, instruction):
    return f"{ROLE_LABELS.get(lane, lane)}: {instruction}"


def _spec_prompt(raid_id, lane, kind):
    return {
        "content": _choice_text(lane, "kies een specialization."),
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "custom_id": f"ikp:{raid_id}:{lane}:{kind}",
                        "placeholder": "Specialization",
                        "options": _spec_choices(lane),
                    }
                ],
            }
        ],
    }


def _lane_prompt(raid_id, kind):
    text = {"bench": "Bank: kies een rol.", "late": "Laat: kies een rol.", "tentative": "Voorlopig: kies een rol."}[kind]
    return {
        "content": text,
        "components": [
            {
                "type": 1,
                "components": [
                    _role_button("Tank", f"ikg:{raid_id}:tank:{kind}", 1, "tank"),
                    _role_button("Melee", f"ikg:{raid_id}:melee:{kind}", 4, "melee"),
                    _role_button("Ranged", f"ikg:{raid_id}:ranged:{kind}", 4, "ranged"),
                    _role_button("Healer", f"ikg:{raid_id}:healer:{kind}", 3, "healer"),
                ],
            }
        ],
    }


def _character_prompt(raid_id, lane, kind, characters):
    options = []
    for character in characters[:25]:
        option = {
            "label": character["name"][:100],
            "value": str(character["id"]),
            "description": choice_label(character["class_id"], character["spec_id"])[:100],
        }
        emoji = _option_emoji(character["class_id"], character["spec_id"])
        if emoji:
            option["emoji"] = emoji
        options.append(option)
    return {
        "content": _choice_text(lane, "kies een personage."),
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "custom_id": f"ikw:{raid_id}:{lane}:{kind}",
                        "placeholder": "Personage",
                        "options": options,
                    }
                ],
            },
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 2,
                        "label": "Andere specialisatie",
                        "custom_id": f"ikc:{raid_id}:{lane}:{kind}",
                    }
                ],
            },
        ],
    }


def _signup_for(raid_id, user_id):
    user_id = str(user_id)
    for signup in db.signups_for(raid_id):
        if str(signup.get("user_id")) == user_id:
            return signup
    return None


def _signed_text(class_id, spec_id, state, character_name=None):
    label = choice_label(class_id, spec_id)
    if character_name:
        label = f"{character_name} ({label})"
    if state == "reserve":
        return f"De rol is vol. Je staat op de reserve als {label}."
    if state == "late":
        return f"Je bent aangemeld als {label}, maar je bent laat."
    if state == "bench":
        return f"Je staat op de bank als {label}."
    if state == "tentative":
        return f"Je staat voorlopig als {label}."
    return f"Je bent aangemeld als {label}."


def _raid_for(guild_id, raid_id):
    try:
        raid_id = int(raid_id)
    except (TypeError, ValueError):
        raise PlayerMessage("Deze raid bestaat niet meer.") from None
    raid = db.raid_by_id(raid_id)
    guild = db.guild_by_id(guild_id) if guild_id else None
    if raid is None or guild is None or str(raid["guild_id"]) != str(guild["id"]) or guild.get("game") != "wow":
        raise PlayerMessage("Deze raid bestaat niet meer.")
    return guild, raid


def _require_signup(guild, role_ids):
    if may_sign(guild.get("settings"), role_ids):
        return
    raise PlayerMessage("Je hebt niet de rol die nodig is om aan te melden.")


def _require_open(guild, raid):
    from datetime import datetime, timezone

    if raid["status"] == "open" and close_due(raid, guild.get("settings"), datetime.now(timezone.utc)):
        db.close_raid(raid["id"])
        raid["status"] = "closed"
        try:
            publish(guild, db.raid_by_id(raid["id"]))
        except Exception:
            log.warning("Could not close raid %s when it started", raid.get("id"))
    if raid["status"] != "open":
        raise PlayerMessage("Deze raid is gesloten.")


def _gate(guild, raid, role_ids):
    _require_open(guild, raid)
    _require_signup(guild, role_ids)


def _require_poster(guild, user_id, role_ids):
    if _can_post_raid(guild, user_id, role_ids):
        return
    raise PlayerMessage("Je hebt niet de rol die nodig is om een raid aan te passen.")


def _command_stamp(starts_at, settings, now=None):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    moment = datetime.fromisoformat(starts_at)
    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    local = moment.astimezone(zone)
    if now is None:
        now = datetime.now(zone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    month = DUTCH_MONTHS[local.month - 1]
    if local.year != now.year:
        return f"{local.day} {month} {local.year} {local:%H:%M}"
    return f"{local.day} {month} {local:%H:%M}"


def _settings_text(guild, raid):
    lines = [raid.get("title") or "Raid", discord_when(raid["starts_at"], guild.get("settings"), ends_at=raid.get("ends_at"))]
    note = note_display((raid.get("note") or "").strip(), guild)
    if note:
        lines.append(note[:400])
    if is_event(raid):
        return "\n".join(lines)[:2000]
    rule = loot_rule(raid.get("loot_rule"))
    if rule:
        lines.append(f"Loot · {rule['discord']}")
    lines.append(f"Tank {raid['tank_cap']} · Healer {raid['healer_cap']} · DPS {raid['dps_cap']}")
    count = party_total(raid)
    if count >= 2:
        lines.append(f"{count} party's staan open.")
    return "\n".join(lines)[:2000]


def _settings_payload(guild, raid, note=""):
    count = party_total(raid)
    text = _settings_text(guild, raid)
    if note:
        text = f"{note}\n{text}"
    buttons = [
        {"type": 2, "style": 1, "label": "Aanpassen", "custom_id": f"ikea:{raid['id']}"},
        {"type": 2, "style": 2, "label": "Sluiten", "custom_id": f"ikes:{raid['id']}"},
    ]
    if not is_event(raid):
        if count < db.MAX_PARTIES:
            buttons.insert(1, {
                "type": 2,
                "style": 3,
                "label": "Party toevoegen",
                "custom_id": f"ikep:{raid['id']}",
            })
        if count > 1:
            buttons.insert(-1, {
                "type": 2,
                "style": 4,
                "label": "Party weghalen",
                "custom_id": f"iked:{raid['id']}",
            })
    return {
        "content": text[:2000],
        "components": [{"type": 1, "components": buttons}],
        "allowed_mentions": {"parse": []},
    }


def _settings_modal(guild, raid):
    current = raid.get("loot_rule") or ""
    options = []
    for rule in LOOT_RULES:
        option = {"label": rule["discord"][:100], "value": rule["id"]}
        if rule["id"] == current:
            option["default"] = True
        options.append(option)
    shown_note = note_display(raid.get("note"), guild)[:400]
    note_input = {
        "type": 4,
        "custom_id": "note",
        "style": 2,
        "required": False,
        "max_length": 400,
        "placeholder": "Leeg laten haalt de notitie weg",
    }
    if shown_note:
        note_input["value"] = shown_note
    end_input = {
        "type": 4,
        "custom_id": "until",
        "style": 1,
        "required": False,
        "max_length": 40,
        "placeholder": "31 okt 23:00",
    }
    if raid.get("ends_at"):
        end_input["value"] = _command_stamp(raid["ends_at"], guild.get("settings"))[:40]
    components = [
        _draft_label(
            "Tijd",
            {
                "type": 4,
                "custom_id": "when",
                "style": 1,
                "required": True,
                "max_length": 40,
                "value": _command_stamp(raid["starts_at"], guild.get("settings"))[:40],
                "placeholder": "31 okt 20:00",
            },
        ),
        _draft_label("Eindtijd", end_input, "Leeg laten haalt de eindtijd weg"),
        _draft_label(
            "Notitie",
            note_input,
            "Typ @ en de naam. Op de site zoek je een rol terwijl je typt.",
        ),
    ]
    if not is_event(raid):
        components.extend([
            _draft_label("Loot", {"type": 3, "custom_id": "loot", "required": True, "options": options}),
            _draft_label(
                "Tank, healer, DPS",
                {
                    "type": 4,
                    "custom_id": "spots",
                    "style": 1,
                    "required": True,
                    "max_length": 20,
                    "value": f"{raid['tank_cap']} {raid['healer_cap']} {raid['dps_cap']}",
                    "placeholder": "2 2 6",
                },
            ),
        ])
    return {
        "custom_id": f"ikem:{raid['id']}",
        "title": "Event aanpassen" if is_event(raid) else "Raid aanpassen",
        "components": components,
    }


def _public_edit(guild, raid):
    fresh = db.raid_by_id(raid["id"])
    if fresh is None or not fresh.get("message_id"):
        return None
    return {
        "channel_id": fresh["channel_id"],
        "message_id": fresh["message_id"],
        "payload": message_payload(guild, fresh, db.signups_for(fresh["id"])),
        "files": message_files(fresh, guild),
    }


def _enroll_event(guild, raid, user_id, name, kind):
    if not is_event(raid):
        raise PlayerMessage("Dit is geen event.")
    if kind not in ("main", "tentative"):
        raise PlayerMessage("Die keuze bestaat niet.")
    state = db.place_signup(raid, user_id, clean_name(name), "", "", "event", kind=kind)
    if state is None:
        raise PlayerMessage("Dit event is gesloten.")
    text = "Je staat voorlopig." if kind == "tentative" else "Je bent aangemeld."
    return {"content": text}, _public_edit(guild, raid)


def _enroll(guild, raid, user_id, name, class_id, spec_id, lane, kind, character_id=None):
    if lane not in LANES or (class_id, spec_id) not in set(LANES[lane]):
        raise PlayerMessage("Die keuze bestaat niet.")
    if kind not in ("main", "late", "bench", "tentative"):
        raise PlayerMessage("Die keuze bestaat niet.")
    state = db.place_signup(
        raid, user_id, clean_name(name), class_id, spec_id, lane, kind=kind, character_id=character_id
    )
    if state is None:
        raise PlayerMessage("Deze raid is gesloten.")
    shown = name if character_id else None
    return {"content": _signed_text(class_id, spec_id, state, shown)}, _public_edit(guild, raid)


def _open_lane(guild, raid, user_id, lane, kind):
    fits = [
        character
        for character in db.wow_characters_for(guild["id"], user_id)
        if (character["class_id"], character["spec_id"]) in set(LANES[lane])
    ]
    if fits:
        return _character_prompt(raid["id"], lane, kind, fits), None
    return _spec_prompt(raid["id"], lane, kind), None


def _action(guild_id, user_id, name, kind, args, values, role_ids=None):
    if kind in {"ike", "ikea", "ikep", "iked", "ikes"}:
        guild, raid = _raid_for(guild_id, args[0] if args else "")
        _require_open(guild, raid)
        _require_poster(guild, user_id, role_ids)
        if kind == "ike":
            return _settings_payload(guild, raid), None
        if kind == "ikea":
            return {"modal": _settings_modal(guild, raid)}, None
        if kind == "ikes":
            return {"content": "Gesloten.", "components": []}, None
        if is_event(raid):
            raise PlayerMessage("Een event heeft geen extra party's.")
        count = party_total(raid)
        if kind == "ikep":
            if count >= db.MAX_PARTIES:
                raise PlayerMessage("Vier party's is het maximum.")
            opened = count + 1
        else:
            if count <= 1:
                raise PlayerMessage("Er is maar één party.")
            opened = count - 1
        if not db.set_party_count(raid["id"], opened):
            raise PlayerMessage("Deze raid is gesloten.")
        fresh = db.raid_by_id(raid["id"])
        try:
            _ensure_party_voice(guild, fresh)
        except Exception:
            log.exception("Could not sync party voice for raid %s", raid["id"])
        fresh = db.raid_by_id(raid["id"]) or fresh
        notice = f"Party {count + 1} staat open." if kind == "ikep" else f"Party {count} is weggehaald."
        return _settings_payload(guild, fresh, notice), _public_edit(guild, fresh)
    lanes = {"ikt": "tank", "ikm": "melee", "ikn": "ranged", "ikh": "healer"}
    statuses = {"ikb": "bench", "ikd": "late", "ikv": "tentative"}
    if kind in lanes:
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        return _open_lane(guild, raid, user_id, lanes[kind], "main")
    if kind == "ikj":
        guild, raid = _raid_for(guild_id, args[0] if args else "")
        _gate(guild, raid, role_ids)
        return _enroll_event(guild, raid, user_id, name, "main")
    if kind in statuses:
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        if kind == "ikv" and is_event(raid):
            return _enroll_event(guild, raid, user_id, name, "tentative")
        return _lane_prompt(raid["id"], statuses[kind]), None
    if kind == "ika":
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        state = db.place_signup(raid, user_id, clean_name(name), "", "", "absent", kind="absent")
        if state is None:
            raise PlayerMessage("Deze raid is gesloten.")
        return {"content": "Je staat als afwezig."}, _public_edit(guild, raid)
    if kind == "ikl":
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        if not db.remove_signup(raid["id"], user_id):
            raise PlayerMessage("Je stond niet aangemeld.")
        return {"content": "Je bent afgemeld."}, _public_edit(guild, raid)
    if kind == "ikg":
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        if len(args) < 3 or args[1] not in LANES or args[2] not in ("late", "bench", "tentative"):
            raise PlayerMessage("Die keuze bestaat niet.")
        return _open_lane(guild, raid, user_id, args[1], args[2])
    if kind == "ikc":
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        if len(args) < 3 or args[1] not in LANES:
            raise PlayerMessage("Die keuze bestaat niet.")
        return _spec_prompt(raid["id"], args[1], args[2]), None
    if kind == "iku" or kind == "ikw":
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        if len(args) < 3 or args[1] not in LANES:
            raise PlayerMessage("Die keuze bestaat niet.")
        character_id = (values or [""])[0] if kind == "ikw" else None
        if kind == "iku":
            fits = [
                character
                for character in db.wow_characters_for(guild["id"], user_id)
                if (character["class_id"], character["spec_id"]) in set(LANES[args[1]])
            ]
            character = fits[0] if len(fits) == 1 else None
        else:
            character = db.wow_character_owned(guild["id"], user_id, character_id)
        if character is None or (character["class_id"], character["spec_id"]) not in set(LANES[args[1]]):
            return _spec_prompt(raid["id"], args[1], args[2]), None
        return _enroll(
            guild, raid, user_id, character["name"], character["class_id"], character["spec_id"], args[1], args[2], character["id"]
        )
    if kind == "ikp":
        guild, raid = _raid_for(guild_id, args[0])
        _gate(guild, raid, role_ids)
        if len(args) < 3 or args[1] not in LANES:
            raise PlayerMessage("Die keuze bestaat niet.")
        picked = (values or [""])[0]
        class_id, separator, spec_id = str(picked).partition(":")
        if not separator:
            raise PlayerMessage("Die specialization bestaat niet.")
        return _enroll(guild, raid, user_id, name, class_id, spec_id, args[1], args[2])
    raise PlayerMessage("Deze knop werkt niet meer.")


# Buttons on the raid post open a new private reply. Kind 6 would leave that button spinning.
_FRESH_KINDS = {"ikt", "ikm", "ikn", "ikh", "ikb", "ikd", "ikv", "ika", "ike", "ikj", "ikl"}
_MODAL_KINDS = {"ikea"}


def _interaction_payload(data):
    payload = dict(data or {})
    payload.pop("flags", None)
    payload.pop("modal", None)
    payload.setdefault("components", [])
    content = payload.get("content")
    if content:
        payload["content"] = str(content)[:2000]
    return payload


def _defer(interaction_id, token, update):
    """Tell Discord we saw the click before the roster upload, which can take longer than three seconds."""
    if update:
        discord_api.interaction_callback(interaction_id, token, kind=6)
        return
    discord_api.interaction_callback(interaction_id, token, kind=5, data={"flags": 64})


def _finish(token, data):
    discord_api.edit_original_interaction(token, _interaction_payload(data))


def _safe_finish(token, data):
    try:
        _finish(token, data)
    except (discord_api.DiscordError, OSError):
        log.warning("Could not update the raid interaction")


def _deliver_public(guild_id, raid_id, edit):
    """Push the roster after the player already has an answer."""
    if not edit:
        return ""
    try:
        guild = db.guild_by_id(guild_id)
        raid = db.raid_by_id(raid_id) if raid_id else None
        if not edit_public(guild, raid):
            discord_api.edit_message(
                edit["channel_id"], edit["message_id"], edit["payload"], files=edit.get("files")
            )
            db.clear_last_error(guild_id, _RAID_MESSAGE_ERRORS)
    except discord_api.DiscordError as error:
        log.warning(
            "Could not update raid message %s (HTTP %s): %s",
            edit.get("message_id"),
            error.status,
            error.body,
        )
        db.set_last_error(guild_id, "Could not update a raid message.")
        return "\nHet bericht in het kanaal kon niet worden bijgewerkt."
    except Exception:
        log.exception("Could not update raid message %s", edit.get("message_id"))
        db.set_last_error(guild_id, "Could not update a raid message.")
        return "\nHet bericht in het kanaal kon niet worden bijgewerkt."
    return ""


def _refresh_quiet(guild_id, raid_id):
    if not raid_id:
        return
    try:
        edit_public(db.guild_by_id(guild_id), db.raid_by_id(raid_id))
    except Exception:
        log.warning("Could not refresh raid %s after a failed interaction", raid_id)


def _reply_modal(interaction_id, token, data):
    if data.get("modal"):
        discord_api.interaction_callback(interaction_id, token, kind=9, data=data["modal"])
        return
    discord_api.interaction_callback(
        interaction_id, token, kind=4, data={**_interaction_payload(data), "flags": 64}
    )


def _reply_notice(interaction_id, token, content):
    try:
        discord_api.interaction_callback(
            interaction_id,
            token,
            kind=4,
            data={"content": content[:2000], "components": [], "flags": 64},
        )
    except (discord_api.DiscordError, OSError):
        log.warning("Could not answer the raid interaction")


def handle_component(guild_id, user_id, name, custom_id, values, interaction_id, token, role_ids=None):
    kind, _, rest = (custom_id or "").partition(":")
    args = [part for part in rest.split(":") if part != ""]
    raid_id = args[0] if args else ""
    if kind in _MODAL_KINDS:
        try:
            data, _edit = _action(guild_id, user_id, name, kind, args, values, role_ids)
            _reply_modal(interaction_id, token, data)
        except PlayerMessage as error:
            _reply_notice(interaction_id, token, str(error))
        except Exception:
            log.exception("Raid signup failed")
            _reply_notice(interaction_id, token, "Er ging iets mis. Probeer het opnieuw.")
        return
    try:
        _defer(interaction_id, token, kind not in _FRESH_KINDS)
    except (discord_api.DiscordError, OSError):
        log.warning("Could not acknowledge the raid interaction")
        return
    try:
        data, edit = _action(guild_id, user_id, name, kind, args, values, role_ids)
    except PlayerMessage as error:
        _safe_finish(token, {"content": str(error)})
        return
    except Exception:
        log.exception("Raid signup failed")
        _safe_finish(token, {"content": "Er ging iets mis. Probeer het opnieuw."})
        _refresh_quiet(guild_id, raid_id)
        return
    if data.get("modal"):
        _safe_finish(token, {"content": "Dit formulier kon niet openen. Probeer het opnieuw."})
        return
    _safe_finish(token, data)
    warning = _deliver_public(guild_id, raid_id, edit)
    if warning:
        warned = dict(data)
        warned["content"] = (warned.get("content") or "") + warning
        _safe_finish(token, warned)


def answer_raid_settings(guild_id, user_id, role_ids, interaction_id, token, custom_id, fields):
    """Save the gear modal onto the raid and refresh the private settings card."""
    raid_id = ""
    try:
        _defer(interaction_id, token, True)
    except (discord_api.DiscordError, OSError):
        log.warning("Could not acknowledge the raid settings")
        return
    try:
        parts = str(custom_id or "").split(":")
        if len(parts) < 2 or parts[0] != "ikem":
            raise PlayerMessage("Dit formulier werkt niet meer.")
        raid_id = parts[1]
        guild, raid = _raid_for(guild_id, raid_id)
        _require_open(guild, raid)
        _require_poster(guild, user_id, role_ids)
        try:
            starts_at = parse_command_when((fields or {}).get("when") or "", guild.get("settings"))
        except ValueError as error:
            if str(error) == "past":
                raise PlayerMessage("Kies een tijdstip in de toekomst.") from None
            raise PlayerMessage("Gebruik een datum zoals 31 okt 20:00.") from None
        submitted = fields or {}
        if "until" not in submitted:
            ends_at = db._KEEP
        else:
            raw_end = (submitted.get("until") or "").strip()
            if not raw_end:
                ends_at = None
            else:
                try:
                    ends_at = parse_command_when(raw_end, guild.get("settings"))
                except ValueError as error:
                    if str(error) == "past":
                        raise PlayerMessage("Kies een eindtijd in de toekomst.") from None
                    raise PlayerMessage("Gebruik een eindtijd zoals 31 okt 23:00.") from None
                if _aware(ends_at) <= _aware(starts_at):
                    raise PlayerMessage("De eindtijd moet na de start liggen.")
        note = note_clean(submitted.get("note"), guild)
        if is_event(raid):
            caps = [0, 0, 0]
            rule_id = None
        else:
            rule_id = (fields or {}).get("loot") or ""
            if loot_rule(rule_id) is None:
                raise PlayerMessage("Kies een lootregel.")
            spots = re.findall(r"\d+", (fields or {}).get("spots") or "")
            if len(spots) != 3:
                raise PlayerMessage("Vul tank, healer en DPS in, bijvoorbeeld 2 2 6.")
            caps = [int(spot) for spot in spots]
            limit = int(raid.get("size") or 0)
            if any(cap < 0 or cap > limit for cap in caps) or sum(caps) < 1 or sum(caps) > limit:
                raise PlayerMessage("Die plekken passen niet in deze dungeon of raid.")
        if not db.update_raid(raid["id"], guild["id"], starts_at, caps[0], caps[1], caps[2], note, rule_id, ends_at):
            raise PlayerMessage("Dit event is gesloten." if is_event(raid) else "Deze raid is gesloten.")
        if not is_event(raid) and party_total(raid) >= 2:
            db.fill_open_parties(raid["id"])
        fresh = db.raid_by_id(raid["id"])
        _safe_finish(token, _settings_payload(guild, fresh, "Opgeslagen."))
        warning = _deliver_public(guild_id, raid["id"], _public_edit(guild, fresh))
        if warning:
            _safe_finish(token, _settings_payload(guild, fresh, "Opgeslagen." + warning))
    except PlayerMessage as error:
        _safe_finish(token, {"content": str(error)})
    except Exception:
        log.exception("Raid settings failed")
        _safe_finish(token, {"content": "Er ging iets mis. Probeer het opnieuw."})
        _refresh_quiet(guild_id, raid_id)


def handle_absence(guild_id, user_id, name, custom_id, reason, interaction_id, token, role_ids=None):
    kind, _, rest = (custom_id or "").partition(":")
    args = [part for part in rest.split(":") if part != ""]
    raid_id = args[0] if args else ""
    try:
        _defer(interaction_id, token, False)
    except (discord_api.DiscordError, OSError):
        log.warning("Could not acknowledge the absence form")
        return
    try:
        if kind not in ("ikz", "ikx"):
            raise PlayerMessage("Dit formulier werkt niet meer.")
        guild, raid = _raid_for(guild_id, args[0] if args else "")
        _gate(guild, raid, role_ids)
        reason = (reason or "").strip()
        if not reason:
            raise PlayerMessage("Vul een reden in.")
        if kind == "ikx":
            if not db.remove_signup(raid["id"], user_id):
                raise PlayerMessage("Je stond niet aangemeld.")
            done = "Je bent afgemeld."
        else:
            state = db.place_signup(
                raid, user_id, clean_name(name), "", "", "absent", kind="absent", note=reason[:200]
            )
            if state is None:
                raise PlayerMessage("Deze raid is gesloten.")
            done = "Je staat als afwezig."
        _safe_finish(token, {"content": done})
        warning = _deliver_public(guild_id, raid["id"], _public_edit(guild, raid))
        if warning:
            _safe_finish(token, {"content": done + warning})
    except PlayerMessage as error:
        _safe_finish(token, {"content": str(error)})
    except Exception:
        log.exception("Absence signup failed")
        _safe_finish(token, {"content": "Er ging iets mis. Probeer het opnieuw."})
        _refresh_quiet(guild_id, raid_id)


def refresh_posted():
    """Put the current embed, including the banner, back on messages already in Discord."""
    for guild in db.list_guilds():
        if guild.get("game") != "wow":
            continue
        for raid in db.raids_for_guild(guild["id"]):
            if not raid.get("message_id"):
                continue
            try:
                publish(guild, raid)
            except Exception as error:
                detail = getattr(error, "body", None) or error
                log.warning("Could not refresh raid %s: %s", raid.get("id"), detail)


_RAID_MESSAGE_ERRORS = (
    "Could not update the raid message after a move.",
    "Could not update a raid message.",
    "Could not close the raid message in Discord.",
)
_publish_locks = {}
_publish_guard = threading.Lock()


def _message_lock(message_id):
    key = str(message_id)
    with _publish_guard:
        lock = _publish_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _publish_locks[key] = lock
        return lock


def edit_public(guild, raid):
    """Push the saved roster to Discord. Edits of one message wait in line, and the latest roster is what gets sent."""
    if guild is None or raid is None:
        return False
    preview = _public_edit(guild, raid)
    if preview is None:
        return False
    with _message_lock(preview["message_id"]):
        edit = _public_edit(guild, raid)
        if edit is None:
            return False
        discord_api.edit_message(
            edit["channel_id"], edit["message_id"], edit["payload"], files=edit.get("files")
        )
        db.clear_last_error(guild["id"], _RAID_MESSAGE_ERRORS)
    return True


def publish(guild, raid):
    edit_public(guild, raid)


def reminder_message(guild, raid, minutes):
    roles = mention_roles(guild, raid)
    text = f"{reminder_lead(minutes)} begint **{raid['title']}**."
    if raid.get("ends_at"):
        end_unix = int(_local_start(raid["ends_at"], guild.get("settings")).timestamp())
        same_day = _local_start(raid["starts_at"], guild.get("settings")).date() == _local_start(raid["ends_at"], guild.get("settings")).date()
        text += f" Tot <t:{end_unix}:{'t' if same_day else 'f'}>."
    link = discord_url(guild["id"], raid.get("channel_id"), raid.get("message_id"))
    if link:
        text = f"{text}\n{link}"
    mentions = voice_mentions(raid)
    if mentions:
        text = f"{text}\n{mentions}"
    mentions = " ".join(f"<@&{role_id}>" for role_id in roles)
    content = f"{mentions}\n{text}" if mentions else text
    return content, roles


def send_reminder(guild, raid, minutes):
    content, roles = reminder_message(guild, raid, minutes)
    discord_api.send_payload(
        raid["channel_id"],
        {"content": content[:2000], "allowed_mentions": {"parse": [], "roles": roles}},
    )


QUESTION_THREAD = "Stel hier je vragen en deel informatie over deze raid."
_OLD_QUESTION_THREAD = "Vragen en plaatjes voor deze raid horen hier."
_notice_cleared = set()
_notice_missed = set()
_note_updated = set()


def thread_name(raid, settings):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    moment = datetime.fromisoformat(raid["starts_at"])
    zone = ZoneInfo((settings or {}).get("timezone") or "UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    local = moment.astimezone(zone)
    title = re.sub(r"\s+", " ", raid.get("title") or "").strip() or "Raid"
    return f"{title} · {local.day} {DUTCH_MONTHS[local.month - 1]}"[:100]


def clear_thread_notice(raid, settings):
    """Drop the 'started a thread' line. One miss is retried, then we stop looking."""
    raid_id = raid.get("id")
    if raid_id in _notice_cleared or not raid.get("channel_id"):
        return
    try:
        found = discord_api.delete_thread_notice(raid["channel_id"], thread_name(raid, settings))
    except discord_api.DiscordError as error:
        log.warning("Could not remove the thread notice for raid %s: %s", raid_id, error)
        return
    if found or raid_id in _notice_missed:
        if not found:
            log.warning("Thread notice for raid %s was not in the latest channel messages", raid_id)
        _notice_cleared.add(raid_id)
        _notice_missed.discard(raid_id)
        return
    _notice_missed.add(raid_id)


def refresh_thread_note(raid):
    """Replace the previous opening line in a thread that is already open."""
    raid_id = raid.get("id")
    thread_id = raid.get("thread_id")
    if not thread_id or raid_id in _note_updated:
        return
    try:
        discord_api.replace_message_text(thread_id, _OLD_QUESTION_THREAD, QUESTION_THREAD)
    except discord_api.DiscordError as error:
        log.warning("Could not update the thread note for raid %s: %s", raid_id, error)
        return
    _note_updated.add(raid_id)


def open_question_thread(guild, raid):
    """One public thread on the signup message. Waiting raids get one when they are posted."""
    if not db.wow_settings(guild.get("settings")).get("question_thread"):
        return None
    if raid.get("status") != "open" or raid.get("thread_id") or not raid.get("message_id") or not raid.get("channel_id"):
        return None
    created = discord_api.create_public_thread(
        raid["channel_id"], raid["message_id"], thread_name(raid, guild.get("settings"))
    )
    thread_id = str(created.get("id") or "")
    if not thread_id:
        return None
    db.set_raid_thread(raid["id"], thread_id)
    clear_thread_notice(raid, guild.get("settings"))
    try:
        discord_api.send_payload(
            thread_id,
            {"content": QUESTION_THREAD, "allowed_mentions": {"parse": []}},
        )
    except discord_api.DiscordError as error:
        log.warning("Could not post in question thread %s: %s", thread_id, error)
    return thread_id


def ensure_question_threads(guild):
    if not db.wow_settings(guild.get("settings")).get("question_thread"):
        return
    for raid in db.raids_for_guild(guild["id"]):
        if raid.get("status") != "open":
            continue
        if raid.get("thread_id"):
            clear_thread_notice(raid, guild.get("settings"))
            refresh_thread_note(raid)
            continue
        try:
            open_question_thread(guild, raid)
        except discord_api.DiscordError as error:
            log.warning("Could not open a question thread for raid %s: %s", raid.get("id"), error)


def archive_question_thread(raid):
    """Closing a raid locks its thread. The signup message stays."""
    thread_id = raid.get("thread_id")
    if not thread_id:
        return
    discord_api.archive_thread(thread_id)


def remove_discord_raid(raid):
    """Delete the signup message. Discord removes the thread with that message. A leftover thread is deleted too."""
    if raid.get("message_id") and raid.get("channel_id"):
        try:
            discord_api.delete_message(raid["channel_id"], raid["message_id"])
        except discord_api.DiscordError as error:
            if error.status != 404:
                raise
    if raid.get("thread_id"):
        try:
            discord_api.delete_channel(raid["thread_id"])
        except discord_api.DiscordError as error:
            if error.status != 404:
                log.warning("Could not delete question thread %s: %s", raid.get("thread_id"), error)


def shift_end(start, end, new_start):
    """Move an end by the same amount as its start. A weekly run keeps the same length."""
    if not end:
        return None
    from datetime import datetime

    origin = datetime.fromisoformat(start)
    finish = datetime.fromisoformat(end)
    moved = datetime.fromisoformat(new_start)
    return (moved + (finish - origin)).isoformat()


def collect_starts(first, repeat, count, extras):
    """The first date, plus a weekly run or extra dates. Eight raids is the limit."""
    from datetime import datetime, timedelta

    moment = datetime.fromisoformat(first)
    clock = moment.replace(tzinfo=None)
    zone = moment.tzinfo
    steps = 1
    if repeat == "week":
        try:
            steps = int(count)
        except (TypeError, ValueError):
            steps = 2
        steps = min(8, max(2, steps))
    dates = [(clock + timedelta(days=7 * step)).replace(tzinfo=zone).isoformat() for step in range(steps)]
    seen = set(dates)
    for extra in extras:
        if extra in seen:
            continue
        if len(dates) >= 8:
            return None
        seen.add(extra)
        dates.append(extra)
    dates.sort(key=lambda value: _aware(value))
    return dates


def raid_is_archived(raid):
    """A closed raid leaves the live list once its attendance has been saved."""
    return raid.get("status") == "closed" and raid.get("voice_state") == "done"


def raid_list(raids, settings):
    """Soonest upcoming raid first, whether it is already in Discord or still waiting. Closed raids follow, newest first."""
    def when(raid):
        return _aware(raid["starts_at"], settings)

    upcoming = [raid for raid in raids if raid["status"] in ("open", "scheduled")]
    closed = [raid for raid in raids if raid["status"] not in ("open", "scheduled")]
    return sorted(upcoming, key=when) + sorted(closed, key=when, reverse=True)


def queue_plan(raids, settings, now, limit):
    """Which future raids should be posted, and which posted raids are too late to keep the slot."""
    future = []
    for raid in raids:
        if raid["status"] not in ("open", "scheduled"):
            continue
        if _aware(raid["starts_at"], settings) <= now:
            continue
        future.append(raid)
    future.sort(key=lambda raid: (_aware(raid["starts_at"], settings), raid["id"]))
    show = future[:limit]
    post = [raid for raid in show if raid["status"] == "scheduled"]
    hold = [
        raid for raid in future[limit:]
        if raid["status"] == "open" and raid.get("message_id") and raid.get("voice_state") != "done"
    ]
    return post, hold


def release_raids(guild, now=None):
    """Discord shows the soonest raids, up to the chosen number. A later one makes room when an earlier raid is waiting."""
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    settings = guild.get("settings")
    config = db.wow_settings(settings)
    limit = config["posted_ahead"]
    for raid in db.raids_for_guild(guild["id"]):
        if raid["status"] == "scheduled" and _aware(raid["starts_at"], settings) <= now:
            db.close_raid(raid["id"])
    buckets = {}
    for raid in db.raids_for_guild(guild["id"]):
        buckets.setdefault(posting_channel(config, raid), []).append(raid)
    post, hold = [], []
    for group in buckets.values():
        group_post, group_hold = queue_plan(group, settings, now, limit)
        post.extend(group_post)
        hold.extend(group_hold)
    for raid in hold:
        try:
            if raid.get("voice_state") == "open":
                discard_voice(raid)
            remove_discord_raid(raid)
        except discord_api.DiscordError as error:
            log.warning("Could not make room for an earlier raid %s: %s", raid.get("id"), error.status)
            continue
        db.hold_raid(raid["id"])
    for raid in post:
        fresh = db.raid_by_id(raid["id"])
        if fresh is None or fresh["status"] != "scheduled":
            continue
        instance = instance_by_id(fresh.get("instance_id")) or {"kind": "raid"}
        channel_id = event_channel(config, instance)
        if not channel_id:
            return "channel"
        posting = dict(fresh)
        posting["status"] = "open"
        posting["channel_id"] = channel_id
        signups = db.signups_for(fresh["id"])
        message = discord_api.send_payload(
            channel_id, message_payload(guild, posting, signups), files=message_files(posting, guild)
        )
        skip_first, skip_second = reminder_skips(fresh, settings, now)
        db.mark_raid_posted(fresh["id"], message["id"], channel_id, skip_first, skip_second)
        post_creation_log(guild, fresh, message["id"], channel_id)
        try:
            open_question_thread(guild, db.raid_by_id(fresh["id"]))
        except discord_api.DiscordError as error:
            log.warning("Could not open a question thread for raid %s: %s", fresh["id"], error)
    ensure_question_threads(guild)
    return None


VOICE_BEFORE = timedelta(hours=1)
VOICE_GRACE = timedelta(minutes=2)
VOICE_MINIMUM = timedelta(minutes=3)
VOICE_UNUSED_AFTER = timedelta(minutes=15)
VOICE_GIVE_UP = timedelta(hours=3)
_voice_retry = {}


def voice_due(raid, now, settings):
    """An open posted raid gets its channels from one hour before start until three hours after."""
    if not db.wow_settings(settings).get("voice_category"):
        return False
    if raid.get("status") != "open" or raid.get("voice_state") == "done":
        return False
    start = _aware(raid["starts_at"], settings)
    return start - VOICE_BEFORE <= now <= start + VOICE_GIVE_UP


def voice_party_name(raid, settings, party, count):
    """One party keeps the dated name. Further parties are named after the raid, one channel each."""
    if int(count or 1) <= 1:
        return thread_name(raid, settings)
    title = re.sub(r"\s+", " ", raid.get("title") or "").strip() or "Raid"
    suffix = f" - PT {int(party)}"
    return f"{title[:100 - len(suffix)]}{suffix}"


def voice_mentions(raid):
    """Channel links for the raid post. One link per open party."""
    if raid.get("voice_state") != "open":
        return ""
    rows = db.raid_voice_channels(raid["id"])
    if not rows and raid.get("voice_channel_id"):
        rows = [{"party": 1, "channel_id": raid["voice_channel_id"]}]
    return " ".join(
        f"<#{row['channel_id']}>"
        for row in sorted(rows, key=lambda row: int(row["party"]))
        if row.get("channel_id")
    )


def voice_should_drop(raid, now, settings, occupants):
    """Drop a used channel after it stays empty. Drop an unused one after the raid, or three hours on."""
    if not raid.get("voice_channel_id") or raid.get("voice_state") != "open" or occupants:
        return False
    start = _aware(raid["starts_at"], settings)
    if raid.get("voice_seen"):
        empty = raid.get("voice_empty_at")
        return bool(empty) and _aware(empty) <= now - VOICE_GRACE
    if now >= start + VOICE_GIVE_UP:
        return True
    return raid.get("status") == "closed" and now >= start + VOICE_UNUSED_AFTER


def present_people(stays, minimum=VOICE_MINIMUM):
    from datetime import datetime, timezone

    totals = {}
    names = {}
    for stay in stays:
        if not stay.get("left_at"):
            continue
        joined = datetime.fromisoformat(stay["joined_at"])
        left = datetime.fromisoformat(stay["left_at"])
        if joined.tzinfo is None:
            joined = joined.replace(tzinfo=timezone.utc)
        if left.tzinfo is None:
            left = left.replace(tzinfo=timezone.utc)
        totals[stay["user_id"]] = totals.get(stay["user_id"], 0) + max(0, (left - joined).total_seconds())
        names[stay["user_id"]] = stay["name"]
    needed = minimum.total_seconds()
    return [
        {"user_id": user_id, "name": names[user_id]}
        for user_id, seconds in totals.items()
        if seconds >= needed
    ]


_retired_voice = {}


def _raid_for_voice(channel_id):
    """The open raid that owns this channel, including one just removed."""
    raid = db.raid_by_voice_channel(channel_id)
    if raid:
        return raid
    retired = _retired_voice.get(str(channel_id or ""))
    if not retired:
        return None
    raid_id, seen = retired
    if time.monotonic() - seen > 180:
        _retired_voice.pop(str(channel_id), None)
        return None
    raid = db.raid_by_id(raid_id)
    if raid and raid.get("voice_state") == "open":
        return raid
    return None


def note_voice(guild_id, user_id, name, left_channel, joined_channel, now=None):
    """Record a move into or out of a raid voice channel. The channel itself stays until it is empty."""
    from datetime import datetime, timezone

    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).isoformat()
    if left_channel and left_channel != joined_channel:
        raid = _raid_for_voice(left_channel)
        if raid and str(raid["guild_id"]) == str(guild_id):
            db.end_voice_stay(raid["id"], user_id, stamp)
            if db.open_voice_count(raid["id"]) == 0 and raid.get("voice_seen"):
                db.mark_voice_empty(raid["id"], stamp)
    if joined_channel and joined_channel != left_channel:
        raid = _raid_for_voice(joined_channel)
        if raid and str(raid["guild_id"]) == str(guild_id):
            db.begin_voice_stay(raid["id"], user_id, name, stamp)
            db.mark_voice_seen(raid["id"])
            db.clear_voice_empty(raid["id"])


def _voice_rows(raid):
    rows = db.raid_voice_channels(raid["id"])
    if rows:
        return rows
    if raid.get("voice_channel_id") and raid.get("voice_state") == "open":
        return [{"party": 1, "channel_id": raid["voice_channel_id"], "name": ""}]
    return []


def _remove_voice_channel(raid_id, channel_id):
    try:
        discord_api.delete_channel(channel_id)
    except discord_api.DiscordError as error:
        if error.status != 404:
            log.warning("Could not remove voice channel %s: %s", channel_id, error)
            return False
    _retired_voice[str(channel_id)] = (str(raid_id), time.monotonic())
    return True


def _remove_all_voice_channels(raid):
    removed = True
    for row in _voice_rows(raid):
        if not _remove_voice_channel(raid["id"], row["channel_id"]):
            removed = False
    return removed


def _ensure_party_voice(guild, raid):
    """Bring party channels in line when an officer opens or closes a party."""
    from datetime import datetime, timezone

    settings = guild.get("settings")
    category_id = db.wow_settings(settings).get("voice_category")
    if not category_id or raid.get("status") != "open" or raid.get("voice_state") == "done":
        return
    now = datetime.now(timezone.utc)
    has_voice = raid.get("voice_state") == "open" and bool(raid.get("voice_channel_id"))
    if has_voice or voice_due(raid, now, settings):
        _sync_party_voice(guild, raid, category_id, force=True)


def _sync_party_voice(guild, raid, category_id, force=False):
    """Open one channel per party, and drop a channel when that party is closed."""
    raid_id = raid["id"]
    if not force and raid_id in _voice_retry and time.monotonic() - _voice_retry[raid_id] < 600:
        return
    settings = guild.get("settings")
    count = party_total(raid)
    wanted = [(party, voice_party_name(raid, settings, party, count)) for party in range(1, count + 1)]
    existing = {int(row["party"]): row for row in _voice_rows(raid)}
    if (
        sorted(existing) == [party for party, _name in wanted]
        and all((existing[party].get("name") or "") == name for party, name in wanted)
    ):
        return
    kept = []
    failed = False
    ids_changed = False
    for party, name in wanted:
        row = existing.get(party)
        if row:
            applied = row.get("name") or ""
            if applied != name:
                if not applied and count <= 1:
                    applied = name
                else:
                    try:
                        discord_api.edit_channel(row["channel_id"], {"name": name})
                        applied = name
                    except discord_api.DiscordError as error:
                        if error.status != 404:
                            failed = True
                            log.warning("Could not rename voice channel %s: %s", row["channel_id"], error)
                            kept.append((party, row["channel_id"], applied))
                            continue
                        row = None
            if row:
                kept.append((party, row["channel_id"], applied))
                continue
        try:
            created = discord_api.create_voice_channel(guild["id"], category_id, name)
        except discord_api.DiscordError as error:
            failed = True
            log.warning("Could not open a voice channel for raid %s party %s: %s", raid_id, party, error)
            continue
        kept.append((party, created["id"], name))
        ids_changed = True
    for party, row in existing.items():
        if party <= count and any(item[0] == party for item in kept):
            continue
        if _remove_voice_channel(raid_id, row["channel_id"]):
            ids_changed = True
        else:
            failed = True
            kept.append((party, row["channel_id"], row.get("name") or ""))
    if kept:
        db.save_raid_voice(raid_id, kept)
    if failed:
        _voice_retry[raid_id] = time.monotonic()
    else:
        _voice_retry.pop(raid_id, None)
    if not ids_changed:
        return
    try:
        publish(guild, db.raid_by_id(raid_id))
    except discord_api.DiscordError as error:
        log.warning("Could not add the voice channel to raid %s: %s", raid_id, error)


def settle_attendance(guild, raid, now=None):
    """Save who stayed at least three minutes and remove the voice channel."""
    from datetime import datetime, timezone

    if raid.get("voice_state") == "done":
        return "done"
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).isoformat()
    if _voice_rows(raid) and not _remove_all_voice_channels(raid):
        return "channel"
    for stay in db.voice_stays(raid["id"]):
        if not stay.get("left_at"):
            db.end_voice_stay(raid["id"], stay["user_id"], stamp)
    if not db.finish_voice(raid["id"], present_people(db.voice_stays(raid["id"]))):
        return "done"
    fresh = db.raid_by_id(raid["id"])
    if fresh and fresh.get("message_id"):
        try:
            publish(guild, fresh)
        except discord_api.DiscordError as error:
            log.warning("Could not clear the voice channel on raid %s: %s", raid["id"], error)
    return None


def attendance_preview(raid, now=None):
    """Who would be saved if attendance were processed now, including anyone still in the channel."""
    from datetime import datetime, timezone

    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).isoformat()
    stays = []
    for stay in db.voice_stays(raid["id"]):
        copy = dict(stay)
        if not copy.get("left_at"):
            copy["left_at"] = stamp
        stays.append(copy)
    return present_people(stays)


def _drop_voice(guild, raid):
    if not _remove_all_voice_channels(raid):
        return
    people = present_people(db.voice_stays(raid["id"]))
    if not db.finish_voice(raid["id"], people):
        return
    fresh = db.raid_by_id(raid["id"])
    if fresh and fresh.get("message_id"):
        try:
            publish(guild, fresh)
        except discord_api.DiscordError as error:
            log.warning("Could not clear the voice channel on raid %s: %s", raid["id"], error)


def discard_voice(raid):
    """Delete the channels because the raid itself is being removed. Attendance is removed with the raid."""
    _remove_all_voice_channels(raid)


def sync_voice(guild, now):
    settings = guild.get("settings")
    category_id = db.wow_settings(settings).get("voice_category")
    for raid in db.raids_for_guild(guild["id"]):
        if voice_should_drop(raid, now, settings, db.open_voice_count(raid["id"])):
            _drop_voice(guild, raid)
            continue
        if not category_id or raid.get("status") != "open" or raid.get("voice_state") == "done":
            continue
        has_voice = raid.get("voice_state") == "open" and bool(_voice_rows(raid) or raid.get("voice_channel_id"))
        if has_voice or voice_due(raid, now, settings):
            _sync_party_voice(guild, raid, category_id)


VIEW_CHANNEL = 1 << 10
CONNECT = 1 << 20
MOVE_MEMBERS = 1 << 24
BOT_ALLOW = VIEW_CHANNEL | CONNECT | MOVE_MEMBERS
_hub_seen = {}
_bot_id = None


def _self_id():
    global _bot_id
    if _bot_id is None:
        _bot_id = str(discord_api.bot_user()["id"])
    return _bot_id


def _bot_overwrite(guild):
    """Only grant bits the bot actually has. Discord rejects the whole channel otherwise."""
    bits = discord_api.bot_permissions(guild["id"])
    if bits is None:
        bits = VIEW_CHANNEL | CONNECT
    return {"id": _self_id(), "type": 1, "allow": str(BOT_ALLOW & bits), "deny": "0"}


def temp_room_name(prefix, person):
    who = clean_name(person)
    label = " ".join((prefix or "").split())
    if label:
        return f"{label} · {who}"[:100]
    return who[:100]


def _with_bot(guild, overwrites):
    """Keep the category's permissions and make sure the bot can see the channel."""
    bot_id = _self_id()
    rows = []
    for row in overwrites or []:
        if str(row.get("id")) == bot_id and int(row.get("type") or 0) == 1:
            continue
        rows.append(
            {
                "id": str(row.get("id")),
                "type": int(row.get("type") or 0),
                "allow": str(int(row.get("allow") or 0)),
                "deny": str(int(row.get("deny") or 0)),
            }
        )
    rows.append(_bot_overwrite(guild))
    return rows


def _category_overwrites(guild):
    channels = discord_api.guild_channels(guild["id"])
    category_id = str(db.wow_settings(guild.get("settings"))["temp_voice_category"])
    category = next((channel for channel in channels if str(channel.get("id")) == category_id), None)
    return (category or {}).get("permission_overwrites")


def _hub_overwrites(guild, role_ids):
    """The category's rules, plus the bot. Chosen roles are the only ones who can join."""
    rows = _with_bot(guild, _category_overwrites(guild))
    if not role_ids:
        return rows
    present = {row["id"] for row in rows}
    everyone = str(guild["id"])
    if everyone not in present:
        rows.append({"id": everyone, "type": 0, "allow": "0", "deny": str(CONNECT)})
    for role_id in role_ids:
        role_id = str(role_id)
        rows = [row for row in rows if row["id"] != role_id]
        rows.append({"id": role_id, "type": 0, "allow": str(CONNECT | VIEW_CHANNEL), "deny": "0"})
    return rows


def _overwrites_match(current, wanted):
    def norm(rows):
        found = set()
        for row in rows or []:
            found.add((str(row.get("id")), int(row.get("type") or 0), int(row.get("allow") or 0), int(row.get("deny") or 0)))
        return found

    return norm(current) == norm(wanted)


def ensure_temp_hub(guild):
    """Create or update the channel people click to open their own room."""
    import time

    config_wow = db.wow_settings(guild.get("settings"))
    if not config_wow["temp_voice"] or not config_wow["temp_voice_category"]:
        return None
    body = {
        "name": config_wow["temp_voice_hub"][:100],
        "parent_id": str(config_wow["temp_voice_category"]),
        "user_limit": 0,
        "permission_overwrites": _hub_overwrites(guild, config_wow["temp_voice_roles"]),
        "position": 0,
    }
    hub_id = config_wow.get("temp_voice_hub_id")
    if not hub_id:
        for channel in discord_api.guild_channels(guild["id"]):
            if (
                channel.get("type") == 2
                and channel.get("name") == body["name"]
                and str(channel.get("parent_id") or "") == body["parent_id"]
            ):
                hub_id = str(channel["id"])
                db.set_temp_voice_hub_id(guild["id"], hub_id)
                break
    if hub_id:
        try:
            current = discord_api.get_channel(hub_id)
        except discord_api.DiscordError as error:
            current = None
            if error.status == 403:
                _hub_seen[str(guild["id"])] = time.monotonic()
                return hub_id
            if error.status != 404:
                raise
        if current and current.get("type") == 2:
            same = (
                current.get("name") == body["name"]
                and str(current.get("parent_id") or "") == body["parent_id"]
                and int(current.get("user_limit") or 0) == 0
                and _overwrites_match(current.get("permission_overwrites"), body["permission_overwrites"])
            )
            if not same:
                discord_api.edit_channel(hub_id, body)
            _hub_seen[str(guild["id"])] = time.monotonic()
            return hub_id
    created = discord_api.create_voice_channel(
        guild["id"],
        config_wow["temp_voice_category"],
        config_wow["temp_voice_hub"],
        user_limit=0,
        overwrites=body["permission_overwrites"],
        position=0,
    )
    db.set_temp_voice_hub_id(guild["id"], created["id"])
    _hub_seen[str(guild["id"])] = time.monotonic()
    return created["id"]


def _drop_temp_room(channel_id):
    try:
        discord_api.delete_channel(channel_id)
    except discord_api.DiscordError as error:
        if error.status != 404:
            log.warning("Could not remove voice room %s: %s", channel_id, error)
            return
    db.delete_temp_room(channel_id)


def _disconnect(guild_id, user_id):
    try:
        discord_api.move_member(guild_id, user_id, None)
    except discord_api.DiscordError as error:
        log.warning("Could not move %s out of the join channel: %s", user_id, error)


def _open_temp_room(guild, config_wow, user_id, name, role_ids):
    allowed = set(config_wow["temp_voice_roles"])
    if allowed and not allowed.intersection(role_ids):
        _disconnect(guild["id"], user_id)
        return
    if len(db.temp_rooms(guild["id"])) >= config_wow["temp_voice_max"]:
        _disconnect(guild["id"], user_id)
        return
    room_name = temp_room_name(config_wow["temp_voice_prefix"], name)
    try:
        channel = discord_api.create_voice_channel(
            guild["id"],
            config_wow["temp_voice_category"],
            room_name,
            user_limit=config_wow["temp_voice_limit"],
            overwrites=_with_bot(guild, _category_overwrites(guild)),
        )
    except discord_api.DiscordError as error:
        log.warning("Could not open a voice room for %s: %s", user_id, error)
        return
    db.add_temp_room(guild["id"], channel["id"], user_id)
    try:
        discord_api.move_member(guild["id"], user_id, channel["id"])
    except discord_api.DiscordError as error:
        log.warning("Could not move %s into %s: %s", user_id, channel["id"], error)
        _drop_temp_room(channel["id"])


def handle_temp_voice(guild_id, user_id, name, role_ids, left_id, joined_id, left_remaining):
    """Open a room when someone joins the click channel, and remember when a room goes empty."""
    from datetime import datetime, timezone

    guild = db.guild_by_id(guild_id)
    if guild is None or db.guild_game(guild.get("settings")) != "wow":
        return
    config_wow = db.wow_settings(guild.get("settings"))
    if not config_wow["temp_voice"]:
        return
    hub_id = str(config_wow.get("temp_voice_hub_id") or "")
    stamp = datetime.now(timezone.utc).isoformat()
    if left_id and left_id != hub_id:
        room = db.temp_room(left_id)
        if room and str(room["guild_id"]) == str(guild_id):
            if left_remaining:
                db.clear_temp_room_empty(left_id)
            elif config_wow["temp_voice_empty"] <= 0:
                _drop_temp_room(left_id)
            else:
                db.mark_temp_room_empty(left_id, stamp)
    if joined_id and joined_id == hub_id:
        _open_temp_room(guild, config_wow, user_id, name, role_ids or [])
    elif joined_id:
        room = db.temp_room(joined_id)
        if room and str(room["guild_id"]) == str(guild_id):
            db.clear_temp_room_empty(joined_id)


def settle_temp_rooms(guild, now, voice=None):
    """Remove a room after it has stayed empty for the configured number of minutes.

    voice maps a guild id to the channels the bot can currently see and how many
    people are in each. A visible room with nobody in it starts that timer even
    when the leave event never recorded the empty moment. Someone walking in
    clears the timer. The caller does not count bots as people.
    """
    from datetime import timezone

    config_wow = db.wow_settings(guild.get("settings"))
    if not config_wow["temp_voice"]:
        return
    wait = timedelta(minutes=config_wow["temp_voice_empty"])
    seen = None if voice is None else voice.get(str(guild["id"]))
    for room in db.temp_rooms(guild["id"]):
        channel_id = str(room["channel_id"])
        empty = room.get("empty_at")
        if seen is not None and channel_id in seen.get("channels", ()):
            occupied = int((seen.get("counts") or {}).get(channel_id, 0) or 0)
            if occupied:
                if empty:
                    db.clear_temp_room_empty(channel_id)
                continue
            if not empty:
                db.mark_temp_room_empty(channel_id, now.astimezone(timezone.utc).isoformat())
                continue
        if empty and _aware(empty) <= now - wait:
            _drop_temp_room(channel_id)


def sync_temp_voice(guild, now, voice=None):
    """Keep the click channel present, and remove rooms that stayed empty."""
    import time

    config_wow = db.wow_settings(guild.get("settings"))
    if not config_wow["temp_voice"] or not config_wow["temp_voice_category"]:
        return
    guild_id = str(guild["id"])
    if not config_wow.get("temp_voice_hub_id") or time.monotonic() - _hub_seen.get(guild_id, 0) > 60:
        try:
            ensure_temp_hub(guild)
        except Exception as error:
            _hub_seen[guild_id] = time.monotonic()
            detail = getattr(error, "body", None) or error
            log.warning("Could not open the join channel for %s: %s", guild_id, detail)
    settle_temp_rooms(guild, now, voice)


_ATTENDANCE_STATE = {
    "main": "Signed up",
    "late": "Signed up · Late",
    "reserve": "Reserve",
    "bank": "Bank",
    "tentative": "Tentative",
    "absent": "Absent",
}


def _attendance_detail(signup, display_name):
    if not signup:
        return "Not on the signup"
    label = _ATTENDANCE_STATE.get(signup.get("state"), "Not on the signup")
    parts = [] if label == "Not on the signup" else [label]
    character = (signup.get("name") or "").strip()
    if character and character.casefold() != (display_name or "").casefold():
        parts.append(character)
    if signup.get("class_id") and signup.get("spec_id"):
        parts.append(choice_label(signup["class_id"], signup["spec_id"]))
    return " · ".join(parts) if parts else "Not on the signup"


def attendance_sheet(signups, marks, members):
    """Present people, signups that were not counted, and members who can still be added."""
    by_user = {str(signup["user_id"]): signup for signup in signups or []}
    member_name = {
        str(member["user_id"]): member.get("nick") or member.get("name") or "Discord member"
        for member in members or []
    }
    present = []
    present_ids = set()
    for mark in marks or []:
        if not mark.get("present"):
            continue
        user_id = str(mark["user_id"])
        present_ids.add(user_id)
        name = member_name.get(user_id) or mark.get("name") or "Discord member"
        present.append({
            "user_id": user_id,
            "name": name,
            "detail": _attendance_detail(by_user.get(user_id), name),
        })
    present.sort(key=lambda row: row["name"].casefold())
    missing = []
    had_signups = False
    for signup in signups or []:
        if signup.get("state") not in ("main", "late", "reserve"):
            continue
        had_signups = True
        user_id = str(signup["user_id"])
        if user_id in present_ids:
            continue
        name = member_name.get(user_id) or signup.get("name") or "Discord member"
        missing.append({
            "user_id": user_id,
            "name": name,
            "detail": _attendance_detail(signup, name),
        })
    missing.sort(key=lambda row: row["name"].casefold())
    listed = present_ids | {row["user_id"] for row in missing}
    others = [
        {"user_id": user_id, "name": name}
        for user_id, name in member_name.items()
        if user_id not in listed
    ]
    others.sort(key=lambda row: row["name"].casefold())
    return {"present": present, "missing": missing, "others": others, "had_signups": had_signups}


def member_rows(members, characters):
    """One row per Discord member. Icons are unique. The server nickname wins over the Discord name."""
    grouped = {}
    for character in characters:
        grouped.setdefault(str(character["user_id"]), []).append(character)
    order = {item["id"]: index for index, item in enumerate(CLASSES)}
    rows = []
    for member in members:
        chars = grouped.get(str(member["user_id"]), [])
        chars = sorted(chars, key=lambda item: (order.get(item.get("class_id"), 99), item.get("name") or ""))
        classes = []
        specs = []
        seen_class = set()
        seen_spec = set()
        detailed = []
        roles = set()
        for character in chars:
            class_id = character.get("class_id")
            spec_id = character.get("spec_id")
            class_name, spec_name = choice_names(class_id, spec_id)
            for lane in spec_lanes(class_id, spec_id):
                if lane == "tank":
                    roles.add("tank")
                elif lane == "healer":
                    roles.add("healer")
                elif lane in ("melee", "ranged"):
                    roles.add("dps")
            if class_id not in seen_class:
                seen_class.add(class_id)
                classes.append({"id": class_id, "color": class_color(class_id)})
            if (class_id, spec_id) not in seen_spec:
                seen_spec.add((class_id, spec_id))
                specs.append({"class_id": class_id, "spec_id": spec_id})
            detailed.append({
                "name": character.get("name"),
                "class_id": class_id,
                "class_name": class_name,
                "class_color": class_color(class_id),
                "spec_id": spec_id,
                "spec_name": spec_name,
            })
        rows.append({
            "user_id": str(member["user_id"]),
            "discord_name": member.get("nick") or member.get("name") or "Discord member",
            "count": len(chars),
            "classes": classes,
            "specs": specs,
            "characters": detailed,
            "roles": [role for role in ("tank", "healer", "dps") if role in roles],
        })
    rows.sort(key=lambda row: row["discord_name"].casefold())
    return rows


def member_filter_counts(rows):
    """How many members can play each role. One person can count for more than one."""
    counts = {"all": len(rows or []), "tank": 0, "healer": 0, "dps": 0}
    for row in rows or []:
        for role in row.get("roles") or []:
            if role in counts:
                counts[role] += 1
    return counts


ATTENDANCE_PARTS = (
    ("present", "Present"),
    ("unsigned", "Not signed up"),
    ("late", "Late"),
    ("missed", "Missed"),
)


def _attendance_bucket(signup, present):
    """One closed raid, one person. The four results add up to every closed raid."""
    state = (signup or {}).get("state") or ""
    if state == "late" and present:
        return "late"
    if present:
        return "present"
    if state in ("main", "late"):
        return "missed"
    return "unsigned"


def attendance_charts(user_ids, raids, signups, marks, settings):
    """Per member: how the closed raids split, oldest raid first."""
    closed = [raid for raid in raids if raid.get("status") == "closed"]
    closed.sort(key=lambda raid: (raid.get("starts_at") or "", raid.get("id") or 0))
    signup_at = {(row["raid_id"], str(row["user_id"])): row for row in signups}
    present_at = {
        (row["raid_id"], str(row["user_id"]))
        for row in marks
        if row.get("present")
    }
    labels = dict(ATTENDANCE_PARTS)
    charts = {}
    for user_id in user_ids:
        user_id = str(user_id)
        counts = {key: 0 for key, _label in ATTENDANCE_PARTS}
        bars = []
        for raid in closed:
            bucket = _attendance_bucket(
                signup_at.get((raid["id"], user_id)),
                (raid["id"], user_id) in present_at,
            )
            counts[bucket] += 1
            bars.append({
                "title": raid.get("title") or "Raid",
                "when": format_span(raid.get("starts_at"), raid.get("ends_at"), settings),
                "bucket": bucket,
                "label": labels[bucket],
            })
        charts[user_id] = {
            "total": len(closed),
            "present": counts["present"],
            "unsigned": counts["unsigned"],
            "late": counts["late"],
            "missed": counts["missed"],
            "parts": [
                {"id": key, "label": label, "count": counts[key]}
                for key, label in ATTENDANCE_PARTS
            ],
            "bars": bars,
        }
    return charts


def member_history(signups, marks, settings):
    """Newest raid first, for the member panel. Closed raids say whether voice counted them."""
    present = {
        (row["raid_id"], row["user_id"]): row
        for row in marks
        if row.get("present")
    }
    by_user = {}
    seen = set()
    for row in signups:
        key = (row["raid_id"], row["user_id"])
        seen.add(key)
        item = {
            "title": row["title"] or "Raid",
            "when": format_span(row["starts_at"], row.get("ends_at"), settings),
            "starts_at": row["starts_at"] or "",
            "status": row["status"] or "",
            "state": row["state"] or "",
            "name": row["name"] or "",
            "class_id": row["class_id"] or "",
            "spec_id": row["spec_id"] or "",
            "present": key in present,
        }
        class_name, spec_name = choice_names(item["class_id"], item["spec_id"]) if item["class_id"] else ("", "")
        item["class_name"] = class_name
        item["spec_name"] = spec_name
        item["class_color"] = class_color(item["class_id"]) if item["class_id"] else ""
        item["result"], item["tone"] = _history_result(item)
        by_user.setdefault(row["user_id"], []).append(item)
    for row in marks:
        if not row.get("present"):
            continue
        key = (row["raid_id"], row["user_id"])
        if key in seen:
            continue
        item = {
            "title": row["title"] or "Raid",
            "when": format_span(row["starts_at"], row.get("ends_at"), settings),
            "starts_at": row["starts_at"] or "",
            "status": row["status"] or "",
            "state": "",
            "name": "",
            "class_id": "",
            "spec_id": "",
            "present": True,
        }
        item["class_name"] = ""
        item["spec_name"] = ""
        item["class_color"] = ""
        item["result"], item["tone"] = _history_result(item)
        by_user.setdefault(row["user_id"], []).append(item)
    for items in by_user.values():
        items.sort(key=lambda item: item["starts_at"], reverse=True)
    return by_user


def _history_result(item):
    state = item["state"]
    closed = item["status"] == "closed"
    if closed and state in ("main", "late"):
        return ("Present", "green") if item["present"] else ("Missed", "red")
    if item["present"] and not state:
        return "Present", "green"
    if state == "late":
        return "Late", "accent"
    if state == "main":
        return "Signed up", "accent"
    if state == "reserve":
        return "Reserve", "grey"
    if state == "absent":
        return "Absent", "grey"
    if state == "bench":
        return "Bench", "grey"
    if state == "tentative":
        return "Tentative", "grey"
    if item["present"]:
        return "Present", "green"
    return "", "grey"


def run_schedule(now=None, voice=None):
    """Close signup when a raid starts, and send the reminders saved on that raid."""
    from datetime import datetime, timezone

    forever_companion.refresh_if_stale()
    now = now or datetime.now(timezone.utc)
    for guild in db.list_guilds():
        if guild.get("game") != "wow" or guild.get("approval") != "approved" or not guild.get("bot_present"):
            continue
        try:
            sync_voice(guild, now)
        except Exception as error:
            detail = getattr(error, "body", None) or error
            log.warning("Could not sync voice for %s: %s", guild.get("id"), detail)
        try:
            sync_temp_voice(guild, now, voice)
        except Exception as error:
            detail = getattr(error, "body", None) or error
            log.warning("Could not sync temporary voice for %s: %s", guild.get("id"), detail)
        for raid in db.raids_for_guild(guild["id"]):
            if raid.get("status") != "open":
                continue
            if close_due(raid, guild.get("settings"), now):
                db.close_raid(raid["id"])
                try:
                    publish(guild, db.raid_by_id(raid["id"]))
                except Exception as error:
                    detail = getattr(error, "body", None) or error
                    log.warning("Could not close raid %s at start: %s", raid.get("id"), detail)
                try:
                    archive_question_thread(raid)
                except Exception as error:
                    detail = getattr(error, "body", None) or error
                    log.warning("Could not archive the question thread for raid %s: %s", raid.get("id"), detail)
                continue
            fresh = db.raid_by_id(raid["id"]) or raid
            minutes, mark_first, mark_second = reminder_plan(fresh, guild.get("settings"), now)
            if not minutes:
                continue
            try:
                send_reminder(guild, fresh, minutes)
            except Exception as error:
                detail = getattr(error, "body", None) or error
                log.warning("Could not remind raid %s: %s", raid.get("id"), detail)
                continue
            db.mark_reminders(raid["id"], first=mark_first, second=mark_second)
        try:
            release_raids(guild, now)
        except Exception as error:
            detail = getattr(error, "body", None) or error
            log.warning("Could not post the next raid for %s: %s", guild.get("id"), detail)
