"""SQLite storage for live guilds. Unused while the site is still on sample data."""

import json
import os
import re
import secrets
import sqlite3
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config
from .mock_data import DEFAULT_MESSAGES

_LOCK = threading.Lock()
MAX_PARTIES = 4
PALETTE = ["#d97706", "#b91c1c", "#7e22ce", "#0284c7", "#0f766e", "#1d4ed8", "#b45309", "#be123c"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def human_date(value):
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def guild_today(settings):
    name = (settings or {}).get("timezone") or "UTC"
    try:
        zone = ZoneInfo(name)
    except Exception:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def now_stamp(settings=None):
    name = (settings or {}).get("timezone") or "UTC"
    try:
        zone = ZoneInfo(name)
    except Exception:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).strftime("%Y-%m-%dT%H:%M:%S")


def icon_letter(name):
    parts = re.findall(r"[A-Za-z0-9]+", name or "")
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return "?"


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:32]
    return slug or "guild"


def valid_slug(slug):
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?", slug or "")) and slug not in config.RESERVED_SLUGS


def default_settings():
    messages = deepcopy(DEFAULT_MESSAGES)
    for message in messages.values():
        message["channel"] = None
    return {
        "timezone": "Europe/Amsterdam",
        "trial_days": 14,
        "reminder_day": 7,
        "recruitment_roles": [],
        "trial_roles": [],
        "content_roles": [],
        "member_filters": [],
        "lootsplit_roles": [],
        "payout_view_roles": [],
        "lootsplit_access_roles": [],
        "lootsplit_access_users": [],
        "companion_roles": [],
        "channels": {"perms": None, "trial_info": None, "recruiter_overview": None},
        "messages": messages,
        "accept": {"add": [], "remove": []},
        "reject": {"remove": []},
        "albion": {
            "region": "europe",
            "guild_name": "",
            "guild_members": 0,
            "name_source": "nickname",
            "guild_check": "dashboard",
            "track_fame": True,
        },
        "overview_enabled": True,
    }


def companion_role_ids(settings):
    """Roles that may connect the Companion. Missing means none.

    Recruitment roles and World of Warcraft poster roles are not read here.
    """
    return _role_id_list(settings, "companion_roles")


def trial_role_ids(settings):
    settings = settings or {}
    chosen = settings.get("trial_roles")
    if not isinstance(chosen, list) or not chosen:
        legacy = settings.get("trial_role")
        chosen = legacy if isinstance(legacy, list) else ([legacy] if legacy else [])
    return [str(role_id) for role_id in chosen if role_id]


def member_filter_ids(settings):
    """Roles chosen in settings to appear as filters on the Members page."""
    chosen = (settings or {}).get("member_filters")
    if not isinstance(chosen, list):
        return []
    return [str(role_id) for role_id in chosen if role_id]


def lootsplit_role_ids(settings):
    """Roles whose members can be picked when booking a lootsplit."""
    return _role_id_list(settings, "lootsplit_roles")


def payout_view_role_ids(settings):
    """Roles that may open their own payout page."""
    return _role_id_list(settings, "payout_view_roles")


def lootsplit_access_role_ids(settings):
    """Roles that may open the lootsplit page."""
    return _role_id_list(settings, "lootsplit_access_roles")


def lootsplit_access_user_ids(settings):
    """People who may open the lootsplit page even without one of the roles above."""
    return _role_id_list(settings, "lootsplit_access_users")


def _role_id_list(settings, key):
    chosen = (settings or {}).get(key)
    if not isinstance(chosen, list):
        return []
    return [str(role_id) for role_id in chosen if role_id]


def _banner_hidden(wow):
    found = []
    for item in (wow or {}).get("banner_hidden") or []:
        text = str(item or "")
        if re.fullmatch(r"[a-z0-9-]{1,60}", text) and text not in found:
            found.append(text)
    return found


def _mention_map(wow):
    raw = (wow or {}).get("mentions") or {}
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for instance_id, roles in raw.items():
        if not instance_id or not isinstance(roles, list):
            continue
        ids = []
        for role_id in roles:
            text = str(role_id or "")
            if text and text not in ids:
                ids.append(text)
        if ids:
            cleaned[str(instance_id)] = ids
    return cleaned


def member_role_ids(settings):
    """Roles given when a trial is accepted. Holding one means the person is a full member."""
    accept = (settings or {}).get("accept") or {}
    return [str(role_id) for role_id in (accept.get("add") or []) if role_id]


def active_trial_role_ids(settings):
    """Trial roles, without roles that already mean the person was accepted."""
    trial_ids = set(trial_role_ids(settings))
    pure = trial_ids - set(member_role_ids(settings))
    return pure or trial_ids


def _message_channel_ok(settings, key):
    """An enabled channel message is configured once it has a channel. A DM reminder does not need one."""
    message = ((settings or {}).get("messages") or {}).get(key) or {}
    if not message.get("enabled"):
        return True
    if key == "reminder" and message.get("delivery") == "dm":
        return True
    return bool(message.get("channel"))


def _albion_setup_complete(settings):
    """Roles and channels the Albion dashboard actually asks for are filled in.

    Welcome and trial messages used to store their channel under settings.channels.
    Settings now stores those on the message itself, so either place counts.
    """
    settings = settings or {}
    channels = settings.get("channels") or {}
    welcome_ok = bool(channels.get("perms")) or _message_channel_ok(settings, "welcome")
    trial_ok = bool(channels.get("trial_info")) or _message_channel_ok(settings, "trial_started")
    overview_ok = not settings.get("overview_enabled", True) or bool(channels.get("recruiter_overview"))
    return bool(
        trial_role_ids(settings)
        and settings.get("recruitment_roles")
        and welcome_ok
        and trial_ok
        and overview_ok
        and all(_message_channel_ok(settings, key) for key in ("reminder", "accepted", "rejected"))
    )


def guild_game(settings):
    """The game this server uses. A finished Albion setup stays Albion without asking again."""
    settings = settings or {}
    game = settings.get("game")
    if game in ("albion", "wow"):
        return game
    if _albion_setup_complete(settings):
        return "albion"
    return None


def parse_reminder_minutes(value):
    """Minutes before the start. The old hour choice is 60. Anything else is off."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value in (0, 15, 30, 45, 60):
        return value
    text = str(value or "").strip().lower()
    if text == "hour":
        return 60
    if text in ("15", "30", "45", "60"):
        return int(text)
    return 0


def parse_second_reminder(value, first):
    """A second reminder only when it is 15 or 30 minutes and closer than the first."""
    first = parse_reminder_minutes(first)
    if isinstance(value, str) and value.strip().lower() == "off":
        return 0
    minutes = parse_reminder_minutes(value)
    if minutes not in (15, 30) or minutes >= first:
        return 0
    return minutes


def known_reminder(value):
    """A recognised reminder choice, or None when the value should be ignored."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return None if value not in (0, 15, 30, 45, 60) else ("off" if value == 0 else str(value))
    text = str(value or "").strip().lower()
    if text == "hour":
        return "60"
    if text == "off":
        return "off"
    if text in ("15", "30", "45", "60"):
        return text
    return None


def reminder_choice(value):
    return known_reminder(value) or "off"


def second_reminder_choice(value, first):
    minutes = parse_second_reminder(value, first)
    return "off" if minutes == 0 else str(minutes)


def _temp_voice_limit(value):
    """A room size from 0 to 99. Zero means no limit."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return min(99, max(0, number))


def _temp_voice_minutes(value):
    """How long an empty room stays, in minutes."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 2
    return min(30, max(0, number))


def _temp_voice_max(value):
    """How many rooms can be open at once."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 10
    return min(25, max(1, number))


def _temp_voice_label(value, limit, fallback=""):
    text = " ".join(str(value or "").replace("\n", " ").split())
    text = "".join(char for char in text if char.isprintable())
    text = text[:limit].strip(" .")
    return text or fallback


def wow_settings(settings):
    wow = (settings or {}).get("wow") or {}
    mode = wow.get("channel_mode") or "one"
    if mode not in ("one", "split"):
        mode = "one"
    reminder = reminder_choice(wow.get("reminder"))
    return {
        "channel_mode": mode,
        "raid_channel": wow.get("raid_channel") or None,
        "dungeon_channel": wow.get("dungeon_channel") or None,
        "event_channel": wow.get("event_channel") or None,
        "log_channel": str(wow.get("log_channel") or "") or None,
        "poster_roles": _role_id_list(wow, "poster_roles"),
        "signup_roles": _role_id_list(wow, "signup_roles"),
        "attendance_roles": _role_id_list(wow, "attendance_roles"),
        "settings_roles": _role_id_list(wow, "settings_roles"),
        "mentions": _mention_map(wow),
        "reminder": reminder,
        "reminder_2": second_reminder_choice(wow.get("reminder_2"), reminder),
        "close_at_start": bool(wow.get("close_at_start")),
        "posted_ahead": 2 if wow.get("posted_ahead") in (2, "2") else 1,
        "question_thread": bool(wow["question_thread"]) if "question_thread" in wow else True,
        "voice_category": wow.get("voice_category") or None,
        "banner_hidden": _banner_hidden(wow),
        "temp_voice": bool(wow.get("temp_voice")),
        "temp_voice_category": wow.get("temp_voice_category") or None,
        "temp_voice_limit": _temp_voice_limit(wow.get("temp_voice_limit")),
        "temp_voice_hub": _temp_voice_label(wow.get("temp_voice_hub"), 100, "Join to Create"),
        "temp_voice_prefix": _temp_voice_label(wow.get("temp_voice_prefix"), 40),
        "temp_voice_roles": _role_id_list(wow, "temp_voice_roles"),
        "temp_voice_empty": _temp_voice_minutes(wow.get("temp_voice_empty")),
        "temp_voice_max": _temp_voice_max(wow.get("temp_voice_max")),
        "temp_voice_hub_id": str(wow.get("temp_voice_hub_id") or "") or None,
    }


def wow_setup_complete(settings):
    wow = wow_settings(settings)
    if not wow["raid_channel"] or not wow["poster_roles"]:
        return False
    if wow["channel_mode"] == "split" and not wow["dungeon_channel"]:
        return False
    return True


def setup_complete(settings):
    game = guild_game(settings)
    if game == "wow":
        return wow_setup_complete(settings)
    if game == "albion":
        return _albion_setup_complete(settings)
    return False


def empty_albion():
    return {"name": None, "link": None, "in_guild": None, "last_in_guild": None, "fame_since": None, "fame": []}


def connect():
    directory = os.path.dirname(config.DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    if not config.DB_PATH:
        return
    with _LOCK:
        conn = connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS guilds (
                id TEXT PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                icon_color TEXT NOT NULL,
                approval TEXT NOT NULL,
                bot_present INTEGER NOT NULL DEFAULT 1,
                added_by TEXT,
                added_by_id TEXT,
                added_at TEXT NOT NULL,
                roles_json TEXT NOT NULL,
                channels_json TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                last_error_json TEXT,
                needs_scan INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS trials (
                id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                username TEXT NOT NULL,
                color TEXT NOT NULL,
                start TEXT,
                extra_days INTEGER NOT NULL DEFAULT 0,
                content_roles_json TEXT NOT NULL,
                ping_sent_at TEXT,
                lost_content_role INTEGER NOT NULL DEFAULT 0,
                verdict TEXT,
                verdict_at TEXT,
                verdict_by TEXT,
                action_error TEXT,
                left_server INTEGER NOT NULL DEFAULT 0,
                timeline_json TEXT NOT NULL,
                albion_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                username TEXT NOT NULL,
                access_token TEXT,
                refresh_token TEXT,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS member_cache (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                role_ids_json TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS members (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                username TEXT NOT NULL,
                nick TEXT,
                role_ids_json TEXT NOT NULL,
                joined_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY,
                at TEXT NOT NULL,
                guild TEXT NOT NULL,
                text TEXT NOT NULL,
                detail TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        _migrate(conn)
        conn.commit()
        conn.close()


def _migrate(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS wow_characters (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            class_id TEXT NOT NULL,
            spec_id TEXT NOT NULL,
            role TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS raids (
            id INTEGER PRIMARY KEY,
            guild_id TEXT NOT NULL,
            title TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            tank_cap INTEGER NOT NULL,
            healer_cap INTEGER NOT NULL,
            dps_cap INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            message_id TEXT,
            size INTEGER,
            status TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS character_wishes (
            character_id INTEGER NOT NULL,
            guild_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            PRIMARY KEY (character_id, instance_id, item_key)
        );
        CREATE TABLE IF NOT EXISTS raid_signups (
            raid_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            class_id TEXT NOT NULL,
            spec_id TEXT NOT NULL,
            role TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (raid_id, user_id)
        );
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(guilds)")}
    if "icon_hash" not in columns:
        conn.execute("ALTER TABLE guilds ADD COLUMN icon_hash TEXT")
    raid_columns = {row[1] for row in conn.execute("PRAGMA table_info(raids)")}
    if "size" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN size INTEGER")
    if "instance_id" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN instance_id TEXT")
    if "note" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN note TEXT")
    signup_columns = {row[1] for row in conn.execute("PRAGMA table_info(raid_signups)")}
    if "note" not in signup_columns:
        conn.execute("ALTER TABLE raid_signups ADD COLUMN note TEXT")
    if "character_id" not in signup_columns:
        conn.execute("ALTER TABLE raid_signups ADD COLUMN character_id INTEGER")
    if "reminder_sent" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0")
    if "thread_id" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN thread_id TEXT")
    if "loot_rule" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN loot_rule TEXT")
    if "voice_channel_id" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN voice_channel_id TEXT")
    if "voice_state" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN voice_state TEXT")
    if "voice_seen" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN voice_seen INTEGER NOT NULL DEFAULT 0")
    if "voice_empty_at" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN voice_empty_at TEXT")
    if "party_count" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN party_count INTEGER NOT NULL DEFAULT 1")
    if "ends_at" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN ends_at TEXT")
    if "reminder_minutes" not in raid_columns:
        conn.execute("ALTER TABLE raids ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE raids ADD COLUMN reminder_2_minutes INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE raids ADD COLUMN reminder_2_sent INTEGER NOT NULL DEFAULT 0")
        _snapshot_raid_reminders(conn)
    if "party" not in signup_columns:
        conn.execute("ALTER TABLE raid_signups ADD COLUMN party INTEGER NOT NULL DEFAULT 1")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS voice_stays (
            id INTEGER PRIMARY KEY,
            raid_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            left_at TEXT
        );
        CREATE TABLE IF NOT EXISTS raid_attendance (
            raid_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            present INTEGER NOT NULL,
            PRIMARY KEY (raid_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS command_drafts (
            id INTEGER PRIMARY KEY,
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            step TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS temp_rooms (
            channel_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            empty_at TEXT
        );
        CREATE INDEX IF NOT EXISTS temp_rooms_guild ON temp_rooms (guild_id);
        CREATE TABLE IF NOT EXISTS raid_voice_channels (
            raid_id INTEGER NOT NULL,
            party INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (raid_id, party)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS raid_voice_channels_channel ON raid_voice_channels (channel_id);
        CREATE TABLE IF NOT EXISTS raid_drafts (
            id INTEGER PRIMARY KEY,
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            instance_id TEXT,
            when_text TEXT,
            tank_cap INTEGER,
            healer_cap INTEGER,
            dps_cap INTEGER,
            loot TEXT,
            title TEXT,
            note TEXT,
            weeks INTEGER,
            step TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    cache_columns = {row[1] for row in conn.execute("PRAGMA table_info(member_cache)")}
    if "member" not in cache_columns:
        conn.execute("ALTER TABLE member_cache ADD COLUMN member INTEGER NOT NULL DEFAULT 1")
    error_columns = {row[1] for row in conn.execute("PRAGMA table_info(errors)")}
    if "status" not in error_columns:
        conn.execute("ALTER TABLE errors ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        conn.execute("UPDATE errors SET status = 'solved' WHERE resolved = 1")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            number INTEGER NOT NULL,
            topic TEXT NOT NULL,
            opener_id TEXT NOT NULL,
            opener_name TEXT NOT NULL,
            status TEXT NOT NULL,
            channel_id TEXT,
            welcome_id TEXT,
            claimed_by_id TEXT,
            claimed_by_name TEXT,
            opened_at TEXT NOT NULL,
            closed_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_one_active
        ON tickets (guild_id, opener_id)
        WHERE status IN ('open', 'claimed');
        """
    )
    ticket_columns = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    if ticket_columns and "details" not in ticket_columns:
        conn.execute("ALTER TABLE tickets ADD COLUMN details TEXT")
    if ticket_columns and "opener_username" not in ticket_columns:
        conn.execute("ALTER TABLE tickets ADD COLUMN opener_username TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY,
            ticket_id TEXT NOT NULL,
            discord_id TEXT,
            author_id TEXT,
            author_name TEXT NOT NULL,
            body TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ticket_messages_discord
        ON ticket_messages (discord_id)
        WHERE discord_id IS NOT NULL;
        """
    )
    _migrate_characters(conn)
    for row in conn.execute("SELECT id, settings_json FROM guilds").fetchall():
        settings = _loads(row["settings_json"], {})
        if settings.get("game") in ("albion", "wow"):
            continue
        if _albion_setup_complete(settings):
            settings["game"] = "albion"
            conn.execute("UPDATE guilds SET settings_json = ? WHERE id = ?", (json.dumps(settings), row["id"]))


def _migrate_characters(conn):
    """One Discord account can keep several characters. Older rows stay as the first character."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(wow_characters)")}
    if "id" not in columns:
        conn.executescript(
            """
            CREATE TABLE wow_characters_next (
                id INTEGER PRIMARY KEY,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                class_id TEXT NOT NULL,
                spec_id TEXT NOT NULL,
                role TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO wow_characters_next (guild_id, user_id, name, class_id, spec_id, role, updated_at)
            SELECT guild_id, user_id, name, class_id, spec_id, role, updated_at FROM wow_characters;
            DROP TABLE wow_characters;
            ALTER TABLE wow_characters_next RENAME TO wow_characters;
            """
        )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS wow_characters_owner_name
           ON wow_characters (guild_id, user_id, name COLLATE NOCASE)"""
    )


def _snapshot_raid_reminders(conn):
    """Copy the current guild default onto raids that did not have their own choice yet."""
    rows = conn.execute("SELECT id, settings_json FROM guilds").fetchall()
    for row in rows:
        settings = _loads(row["settings_json"], {})
        wow = (settings.get("wow") or {}) if isinstance(settings, dict) else {}
        first = parse_reminder_minutes(wow.get("reminder"))
        second = parse_second_reminder(wow.get("reminder_2"), first)
        conn.execute(
            "UPDATE raids SET reminder_minutes = ?, reminder_2_minutes = ? WHERE guild_id = ?",
            (first, second, str(row["id"])),
        )


def _loads(value, fallback):
    if not value:
        return fallback
    return json.loads(value)


def _guild_from_row(row, trials=None):
    settings = _loads(row["settings_json"], default_settings())
    settings["trial_roles"] = trial_role_ids(settings)
    settings.pop("trial_role", None)
    settings["companion_roles"] = companion_role_ids(settings)
    game = guild_game(settings)
    if game:
        settings["game"] = game
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "icon_color": row["icon_color"],
        "icon_letter": icon_letter(row["name"]),
        "icon_hash": row["icon_hash"] if "icon_hash" in row.keys() else None,
        "approval": row["approval"],
        "bot_present": bool(row["bot_present"]),
        "game": game,
        "setup_complete": setup_complete(settings),
        "added_by": row["added_by"] or "Unknown",
        "added_by_id": row["added_by_id"],
        "added_at": row["added_at"],
        "last_error": _loads(row["last_error_json"], None),
        "roles": _loads(row["roles_json"], []),
        "channels": _loads(row["channels_json"], []),
        "settings": settings,
        "trials": trials if trials is not None else [],
        "needs_scan": bool(row["needs_scan"]),
    }


def _trial_from_row(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "username": row["username"],
        "color": row["color"],
        "start": row["start"],
        "extra_days": row["extra_days"],
        "content_roles": _loads(row["content_roles_json"], []),
        "ping_sent_at": row["ping_sent_at"],
        "lost_content_role": bool(row["lost_content_role"]),
        "verdict": row["verdict"],
        "verdict_at": row["verdict_at"],
        "verdict_by": row["verdict_by"],
        "action_error": row["action_error"],
        "left_server": bool(row["left_server"]),
        "timeline": _loads(row["timeline_json"], []),
        "albion": _loads(row["albion_json"], empty_albion()),
    }


def _unique_slug(conn, name, discord_id):
    base = slugify(name)
    slug = base
    n = 2
    while slug in config.RESERVED_SLUGS or conn.execute("SELECT 1 FROM guilds WHERE slug = ? AND id != ?", (slug, discord_id)).fetchone():
        slug = f"{base[:28]}{n}"
        n += 1
    return slug


def upsert_guild(discord_id, name, roles, channels, *, added_by=None, added_by_id=None, rejoin=False, icon_hash=None):
    discord_id = str(discord_id)
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT * FROM guilds WHERE id = ?", (discord_id,)).fetchone()
        if row is None:
            slug = _unique_slug(conn, name, discord_id)
            conn.execute(
                """INSERT INTO guilds
                   (id, slug, name, icon_color, approval, bot_present, added_by, added_by_id, added_at, roles_json, channels_json, settings_json)
                   VALUES (?, ?, ?, ?, 'pending', 1, ?, ?, ?, ?, ?, ?)""",
                (
                    discord_id,
                    slug,
                    name,
                    PALETTE[int(discord_id) % len(PALETTE)],
                    added_by,
                    added_by_id,
                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                    json.dumps(roles),
                    json.dumps(channels),
                    json.dumps(default_settings()),
                ),
            )
        else:
            approval = "pending" if rejoin and row["approval"] == "rejected" else row["approval"]
            conn.execute(
                """UPDATE guilds
                   SET name = ?, roles_json = ?, channels_json = ?, bot_present = 1, approval = ?,
                       added_by = COALESCE(?, added_by), added_by_id = COALESCE(?, added_by_id)
                   WHERE id = ?""",
                (name, json.dumps(roles), json.dumps(channels), approval, added_by, added_by_id, discord_id),
            )
        if icon_hash is not None:
            conn.execute("UPDATE guilds SET icon_hash = ? WHERE id = ?", (icon_hash or None, discord_id))
        conn.commit()
        conn.close()


def replace_roles(discord_id, roles):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE guilds SET roles_json = ? WHERE id = ?", (json.dumps(roles), str(discord_id)))
        conn.commit()
        conn.close()


def mark_bot_left(discord_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE guilds SET bot_present = 0 WHERE id = ?", (str(discord_id),))
        conn.commit()
        conn.close()


def delete_guild(slug):
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT id FROM guilds WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            conn.close()
            return
        guild_id = row["id"]
        conn.execute("DELETE FROM trials WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM member_cache WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM raid_signups WHERE raid_id IN (SELECT id FROM raids WHERE guild_id = ?)", (guild_id,))
        conn.execute(
            "DELETE FROM voice_stays WHERE raid_id IN (SELECT id FROM raids WHERE guild_id = ?)",
            (guild_id,),
        )
        conn.execute(
            "DELETE FROM raid_attendance WHERE raid_id IN (SELECT id FROM raids WHERE guild_id = ?)",
            (guild_id,),
        )
        conn.execute("DELETE FROM raids WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM wow_characters WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM character_wishes WHERE guild_id = ?", (guild_id,))
        conn.execute("DELETE FROM errors WHERE guild = ?", (slug,))
        conn.execute("DELETE FROM guilds WHERE id = ?", (guild_id,))
        conn.commit()
        conn.close()


def mark_missing_guilds(present_ids):
    present = {str(item) for item in present_ids}
    with _LOCK:
        conn = connect()
        rows = conn.execute("SELECT id FROM guilds WHERE bot_present = 1").fetchall()
        for row in rows:
            if row["id"] not in present:
                conn.execute("UPDATE guilds SET bot_present = 0 WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()


def list_guilds(with_trials=False):
    conn = connect()
    rows = conn.execute("SELECT * FROM guilds ORDER BY name").fetchall()
    guilds = []
    for row in rows:
        trials = _trials_for(conn, row["id"]) if with_trials else []
        guilds.append(_guild_from_row(row, trials))
    conn.close()
    return guilds


def guild_by_slug(slug, with_trials=False):
    conn = connect()
    row = conn.execute("SELECT * FROM guilds WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        conn.close()
        return None
    trials = _trials_for(conn, row["id"]) if with_trials else []
    guild = _guild_from_row(row, trials)
    conn.close()
    return guild


def guild_by_id(discord_id, with_trials=False):
    conn = connect()
    row = conn.execute("SELECT * FROM guilds WHERE id = ?", (str(discord_id),)).fetchone()
    if row is None:
        conn.close()
        return None
    trials = _trials_for(conn, row["id"]) if with_trials else []
    guild = _guild_from_row(row, trials)
    conn.close()
    return guild


def guilds_needing_scan():
    return [g for g in list_guilds() if g["needs_scan"] and g["approval"] == "approved"]


def set_approval(slug, approval, *, needs_scan=False):
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE guilds SET approval = ?, needs_scan = ? WHERE slug = ?",
            (approval, 1 if needs_scan else 0, slug),
        )
        conn.commit()
        conn.close()


def request_scan(slug):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE guilds SET needs_scan = 1 WHERE slug = ?", (slug,))
        conn.commit()
        conn.close()


def clear_scan(discord_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE guilds SET needs_scan = 0 WHERE id = ?", (str(discord_id),))
        conn.commit()
        conn.close()


def save_settings(slug, settings, new_slug=None):
    with _LOCK:
        conn = connect()
        if new_slug:
            conn.execute("UPDATE guilds SET slug = ? WHERE slug = ?", (new_slug, slug))
            slug = new_slug
        conn.execute("UPDATE guilds SET settings_json = ? WHERE slug = ?", (json.dumps(settings), slug))
        conn.commit()
        conn.close()
    return slug


def slug_taken(slug, except_slug=None):
    conn = connect()
    row = conn.execute("SELECT slug FROM guilds WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row is not None and row["slug"] != except_slug


def set_last_error(discord_id, text):
    payload = {"at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"), "text": text}
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT slug FROM guilds WHERE id = ?", (str(discord_id),)).fetchone()
        conn.execute("UPDATE guilds SET last_error_json = ? WHERE id = ?", (json.dumps(payload), str(discord_id)))
        if row:
            conn.execute(
                "INSERT INTO errors (at, guild, text, detail, resolved, status) VALUES (?, ?, ?, ?, 0, 'open')",
                (payload["at"], row["slug"], text, text),
            )
        conn.commit()
        conn.close()


def clear_last_error(discord_id, texts):
    """Remove the red guild line when it is one of these messages. The errors log stays."""
    allowed = set(texts)
    with _LOCK:
        conn = connect()
        row = conn.execute(
            "SELECT last_error_json FROM guilds WHERE id = ?",
            (str(discord_id),),
        ).fetchone()
        if row and row["last_error_json"]:
            try:
                current = json.loads(row["last_error_json"])
            except json.JSONDecodeError:
                current = None
            if isinstance(current, dict) and current.get("text") in allowed:
                conn.execute(
                    "UPDATE guilds SET last_error_json = NULL WHERE id = ?",
                    (str(discord_id),),
                )
                conn.commit()
        conn.close()


ERROR_STATUSES = ("open", "progress", "solved")


def list_errors():
    conn = connect()
    rows = conn.execute("SELECT * FROM errors ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def set_error_status(error_id, status):
    """Set one logged error to open, progress, or solved. Solved no longer counts as open."""
    if status not in ERROR_STATUSES:
        return False
    resolved = 1 if status == "solved" else 0
    with _LOCK:
        conn = connect()
        changed = conn.execute(
            "UPDATE errors SET status = ?, resolved = ? WHERE id = ?",
            (status, resolved, int(error_id)),
        ).rowcount
        conn.commit()
        conn.close()
    return changed == 1


def _trials_for(conn, guild_id):
    rows = conn.execute("SELECT * FROM trials WHERE guild_id = ? ORDER BY id", (guild_id,)).fetchall()
    return [_trial_from_row(row) for row in rows]


def replace_members(guild_id, people):
    guild_id = str(guild_id)
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM members WHERE guild_id = ?", (guild_id,))
        conn.executemany(
            """INSERT INTO members (guild_id, user_id, name, username, nick, role_ids_json, joined_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    guild_id,
                    person["user_id"],
                    person["name"],
                    person["username"],
                    person.get("nick"),
                    json.dumps(person.get("role_ids") or []),
                    person.get("joined_at"),
                )
                for person in people
            ],
        )
        conn.commit()
        conn.close()


def upsert_member(guild_id, person):
    with _LOCK:
        conn = connect()
        conn.execute(
            """INSERT INTO members (guild_id, user_id, name, username, nick, role_ids_json, joined_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                 name = excluded.name,
                 username = excluded.username,
                 nick = excluded.nick,
                 role_ids_json = excluded.role_ids_json,
                 joined_at = excluded.joined_at""",
            (
                str(guild_id),
                person["user_id"],
                person["name"],
                person["username"],
                person.get("nick"),
                json.dumps(person.get("role_ids") or []),
                person.get("joined_at"),
            ),
        )
        conn.commit()
        conn.close()


def remove_member(guild_id, user_id):
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM members WHERE guild_id = ? AND user_id = ?", (str(guild_id), str(user_id)))
        conn.commit()
        conn.close()


def list_members(guild_id):
    conn = connect()
    rows = conn.execute("SELECT * FROM members WHERE guild_id = ? ORDER BY name COLLATE NOCASE", (str(guild_id),)).fetchall()
    conn.close()
    people = []
    for row in rows:
        people.append(
            {
                "user_id": row["user_id"],
                "name": row["name"],
                "username": row["username"],
                "nick": row["nick"],
                "role_ids": _loads(row["role_ids_json"], []),
                "joined_at": row["joined_at"],
            }
        )
    return people


def full_member_user_ids(guild_id, settings):
    wanted = set(member_role_ids(settings))
    if not wanted:
        return set()
    return {person["user_id"] for person in list_members(guild_id) if wanted & set(person["role_ids"])}


def delete_trial(trial_id):
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM trials WHERE id = ? AND verdict IS NULL", (trial_id,))
        conn.commit()
        conn.close()


def open_trial(guild_id, user_id):
    conn = connect()
    row = conn.execute(
        "SELECT * FROM trials WHERE guild_id = ? AND user_id = ? AND verdict IS NULL AND left_server = 0 ORDER BY id DESC LIMIT 1",
        (str(guild_id), str(user_id)),
    ).fetchone()
    conn.close()
    return _trial_from_row(row) if row else None


def create_trial(guild, user_id, name, username, *, start, content_roles, albion_name, text):
    settings = guild["settings"]
    albion = empty_albion()
    if albion_name:
        albion["name"] = albion_name
        albion["link"] = "nickname"
    timeline = [{"type": "system", "at": now_stamp(settings), "text": text}]
    color = PALETTE[int(user_id) % len(PALETTE)]
    with _LOCK:
        conn = connect()
        cur = conn.execute(
            """INSERT INTO trials
               (guild_id, user_id, name, username, color, start, content_roles_json, timeline_json, albion_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                guild["id"],
                str(user_id),
                name,
                username,
                color,
                start,
                json.dumps(content_roles),
                json.dumps(timeline),
                json.dumps(albion),
            ),
        )
        conn.commit()
        trial_id = cur.lastrowid
        conn.close()
    return trial_id


def sync_trial_identity(guild_id, user_id, name, username, settings):
    """Keep an open trial's Discord name in step with a nickname or username change."""
    trial = open_trial(guild_id, user_id)
    name = (name or "").strip()
    username = (username or "").strip()
    if trial is None or not name:
        return
    if name == trial["name"] and username == trial["username"]:
        return
    timeline = list(trial["timeline"])
    if name != trial["name"]:
        timeline.append({"type": "system", "at": now_stamp(settings), "text": f"Discord name changed from {trial['name']} to {name}"})
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE trials SET name = ?, username = ?, timeline_json = ? WHERE id = ?",
            (name, username or trial["username"], json.dumps(timeline), trial["id"]),
        )
        conn.commit()
        conn.close()


def update_trial_roles(trial_id, content_roles, lost_content_role, timeline_text, settings):
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT timeline_json FROM trials WHERE id = ?", (trial_id,)).fetchone()
        timeline = _loads(row["timeline_json"], [])
        if timeline_text:
            timeline.append({"type": "system", "at": now_stamp(settings), "text": timeline_text})
        conn.execute(
            "UPDATE trials SET content_roles_json = ?, lost_content_role = ?, timeline_json = ? WHERE id = ?",
            (json.dumps(content_roles), 1 if lost_content_role else 0, json.dumps(timeline), trial_id),
        )
        conn.commit()
        conn.close()


def mark_ping_sent(trial_id, settings, note="Day reminder sent"):
    stamp = now_stamp(settings)
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT timeline_json FROM trials WHERE id = ?", (trial_id,)).fetchone()
        timeline = _loads(row["timeline_json"], [])
        timeline.append({"type": "system", "at": stamp, "text": note})
        conn.execute(
            "UPDATE trials SET ping_sent_at = ?, timeline_json = ? WHERE id = ?",
            (stamp, json.dumps(timeline), trial_id),
        )
        conn.commit()
        conn.close()


def mark_left(guild_id, user_id, settings):
    trial = open_trial(guild_id, user_id)
    if not trial:
        return
    with _LOCK:
        conn = connect()
        timeline = trial["timeline"]
        timeline.append({"type": "system", "at": now_stamp(settings), "text": "Left the server"})
        conn.execute(
            "UPDATE trials SET left_server = 1, timeline_json = ? WHERE id = ?",
            (json.dumps(timeline), trial["id"]),
        )
        conn.commit()
        conn.close()


def save_albion(trial_id, albion):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE trials SET albion_json = ? WHERE id = ?", (json.dumps(albion), trial_id))
        conn.commit()
        conn.close()


def get_trial(trial_id):
    conn = connect()
    row = conn.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
    conn.close()
    return _trial_from_row(row) if row else None


def save_trial(trial_id, fields):
    current = get_trial(trial_id)
    if current is None:
        return None
    timeline = fields.get("timeline", current["timeline"])
    albion = fields.get("albion", current["albion"])
    if isinstance(albion, dict) and (current.get("albion") or {}).get("name") == albion.get("name"):
        stored = current.get("albion") or {}
        for key in ("history", "lifetime", "player_id", "updated_at", "fame", "fame_since", "in_guild", "last_in_guild"):
            if key in stored:
                albion[key] = stored[key]
    with _LOCK:
        conn = connect()
        conn.execute(
            """UPDATE trials SET start = ?, extra_days = ?, timeline_json = ?, albion_json = ?,
               lost_content_role = ?, ping_sent_at = ? WHERE id = ?""",
            (
                fields.get("start", current["start"]) if "start" in fields else current["start"],
                int(fields.get("extra_days", current["extra_days"]) or 0),
                json.dumps(timeline),
                json.dumps(albion),
                1 if fields.get("lost_content_role", current["lost_content_role"]) else 0,
                fields.get("ping_sent_at", current["ping_sent_at"]),
                trial_id,
            ),
        )
        conn.commit()
        conn.close()
    return get_trial(trial_id)


def record_verdict(trial_id, *, kind, by, reason, role_note, message_note, action_error, settings):
    trial = get_trial(trial_id)
    timeline = trial["timeline"]
    stamp = now_stamp(settings)
    if action_error:
        timeline.append({"type": "error", "at": stamp, "text": action_error})
        with _LOCK:
            conn = connect()
            conn.execute(
                "UPDATE trials SET action_error = ?, timeline_json = ? WHERE id = ?",
                (action_error, json.dumps(timeline), trial_id),
            )
            conn.commit()
            conn.close()
        return get_trial(trial_id)
    label = "Accepted" if kind == "accepted" else "Rejected"
    timeline.append({"type": "system", "at": stamp, "text": f"{label} by {by}" + (f": {reason}" if reason else "")})
    if role_note:
        timeline.append({"type": "system", "at": stamp, "text": role_note})
    if message_note:
        timeline.append({"type": "system", "at": stamp, "text": message_note})
    with _LOCK:
        conn = connect()
        conn.execute(
            """UPDATE trials SET verdict = ?, verdict_at = ?, verdict_by = ?, action_error = NULL, timeline_json = ?
               WHERE id = ?""",
            (kind, stamp, by, json.dumps(timeline), trial_id),
        )
        conn.commit()
        conn.close()
    return get_trial(trial_id)


def open_trials():
    conn = connect()
    rows = conn.execute("SELECT * FROM trials WHERE verdict IS NULL AND left_server = 0").fetchall()
    conn.close()
    return [_trial_from_row(row) for row in rows]


def create_session(user_id, name, username, access_token, refresh_token, expires_in):
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(seconds=int(expires_in or 604800))).strftime("%Y-%m-%dT%H:%M:%S")
    with _LOCK:
        conn = connect()
        conn.execute(
            "INSERT INTO sessions (token, user_id, name, username, access_token, refresh_token, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, str(user_id), name, username, access_token, refresh_token, expires),
        )
        conn.commit()
        conn.close()
    return token


def get_session(token):
    if not config.DB_PATH or not token:
        return None
    conn = connect()
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    if row is None:
        return None
    if row["expires_at"] < datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"):
        delete_session(token)
        return None
    return dict(row)


def update_session_tokens(token, access_token, refresh_token, expires_in):
    expires = (datetime.utcnow() + timedelta(seconds=int(expires_in or 604800))).strftime("%Y-%m-%dT%H:%M:%S")
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE sessions SET access_token = ?, refresh_token = ?, expires_at = ? WHERE token = ?",
            (access_token, refresh_token, expires, token),
        )
        conn.commit()
        conn.close()


def delete_session(token):
    if not config.DB_PATH or not token:
        return
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()


def cached_member(user_id, guild_id, max_age_seconds=600):
    """None when the check is missing or old. Otherwise whether this login is in the server, and its roles."""
    conn = connect()
    row = conn.execute(
        "SELECT role_ids_json, checked_at, member FROM member_cache WHERE user_id = ? AND guild_id = ?",
        (str(user_id), str(guild_id)),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    checked = datetime.strptime(row["checked_at"], "%Y-%m-%dT%H:%M:%S")
    if (datetime.utcnow() - checked).total_seconds() > max_age_seconds:
        return None
    present = row["member"] if "member" in row.keys() else 1
    return {"member": bool(present), "roles": _loads(row["role_ids_json"], [])}


def _utc_stamp():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def set_game(slug, game):
    """Lock the game for a server that has not chosen yet. Returns False when the choice already exists."""
    if game not in ("albion", "wow"):
        return False
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT settings_json FROM guilds WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            conn.close()
            return False
        settings = _loads(row["settings_json"], default_settings())
        if guild_game(settings) is not None:
            conn.close()
            return False
        settings["game"] = game
        if game == "wow":
            settings["wow"] = {"raid_channel": None, "poster_roles": []}
        conn.execute("UPDATE guilds SET settings_json = ? WHERE slug = ?", (json.dumps(settings), slug))
        conn.commit()
        conn.close()
    return True


def ticket_settings(settings):
    """Guild ticket setup. Stored beside the WoW settings so a raid save does not remove it."""
    raw = (settings or {}).get("tickets") or {}
    if not isinstance(raw, dict):
        raw = {}
    language = raw.get("language") if raw.get("language") in ("en", "nl") else "en"
    topics = []
    seen = set()
    for item in raw.get("topics") or []:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or "").split())
        message = item.get("message") or ""
        if not label or label in seen:
            continue
        seen.add(label)
        message = str(message or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        raw_roles = item.get("roles")
        if not isinstance(raw_roles, list):
            raw_roles = [item.get("role_id")] if item.get("role_id") else []
        roles = []
        for role_id in raw_roles:
            role_id = str(role_id or "")
            if role_id.isdigit() and role_id not in roles:
                roles.append(role_id)
            if len(roles) >= 20:
                break
        topics.append({"label": label[:100], "message": message[:2000], "roles": roles})
        if len(topics) >= 25:
            break
    return {
        "enabled": bool(raw.get("enabled")),
        "language": language,
        "category_id": str(raw.get("category_id") or "") or None,
        "panel_channel_id": str(raw.get("panel_channel_id") or "") or None,
        "staff_roles": _role_id_list(raw, "staff_roles"),
        "log_roles": _role_id_list(raw, "log_roles"),
        "topics": topics,
        "panel_message_id": str(raw.get("panel_message_id") or "") or None,
    }


def save_wow_settings(
    slug,
    raid_channel,
    poster_roles,
    timezone,
    channel_mode="one",
    dungeon_channel=None,
    mentions=None,
    signup_roles=None,
    reminder=None,
    close_at_start=None,
    posted_ahead=None,
    question_thread=None,
    voice_category=None,
    attendance_roles=None,
    settings_roles=None,
    banner_hidden=None,
    reminder_2=None,
    temp_voice=None,
    temp_voice_category=None,
    temp_voice_limit=None,
    temp_voice_hub=None,
    temp_voice_prefix=None,
    temp_voice_roles=None,
    temp_voice_empty=None,
    temp_voice_max=None,
    event_channel=None,
    log_channel=None,
    tickets=None,
    companion_roles=None,
):
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT settings_json FROM guilds WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            conn.close()
            return False
        settings = _loads(row["settings_json"], default_settings())
        if guild_game(settings) != "wow":
            conn.close()
            return False
        settings["game"] = "wow"
        if channel_mode not in ("one", "split"):
            channel_mode = "one"
        current = settings.get("wow") or {}
        if mentions is None:
            mentions = _mention_map(current)
        if signup_roles is None:
            signup_roles = _role_id_list(current, "signup_roles")
        if attendance_roles is None:
            attendance_roles = _role_id_list(current, "attendance_roles")
        if settings_roles is None:
            settings_roles = _role_id_list(current, "settings_roles")
        if banner_hidden is None:
            banner_hidden = _banner_hidden(current)
        else:
            banner_hidden = _banner_hidden({"banner_hidden": banner_hidden})
        chosen = known_reminder(reminder)
        if chosen is None:
            chosen = known_reminder(current.get("reminder")) or "off"
        reminder = chosen
        if reminder_2 is None:
            reminder_2 = current.get("reminder_2")
        reminder_2 = second_reminder_choice(reminder_2, reminder)
        if close_at_start is None:
            close_at_start = bool(current.get("close_at_start"))
        if posted_ahead not in (1, 2):
            posted_ahead = 2 if current.get("posted_ahead") in (2, "2") else 1
        if question_thread is None:
            question_thread = current.get("question_thread", True)
        if voice_category is None:
            voice_category = current.get("voice_category") or None
        elif not str(voice_category).strip():
            voice_category = None
        if temp_voice is None:
            temp_voice = bool(current.get("temp_voice"))
        if temp_voice_category is None:
            temp_voice_category = current.get("temp_voice_category") or None
        elif not str(temp_voice_category).strip():
            temp_voice_category = None
        if temp_voice_limit is None:
            temp_voice_limit = _temp_voice_limit(current.get("temp_voice_limit"))
        else:
            temp_voice_limit = _temp_voice_limit(temp_voice_limit)
        if temp_voice_hub is None:
            temp_voice_hub = _temp_voice_label(current.get("temp_voice_hub"), 100, "Join to Create")
        else:
            temp_voice_hub = _temp_voice_label(temp_voice_hub, 100, "Join to Create")
        if temp_voice_prefix is None:
            temp_voice_prefix = _temp_voice_label(current.get("temp_voice_prefix"), 40)
        else:
            temp_voice_prefix = _temp_voice_label(temp_voice_prefix, 40)
        if temp_voice_roles is None:
            temp_voice_roles = _role_id_list(current, "temp_voice_roles")
        if temp_voice_empty is None:
            temp_voice_empty = _temp_voice_minutes(current.get("temp_voice_empty"))
        else:
            temp_voice_empty = _temp_voice_minutes(temp_voice_empty)
        if temp_voice_max is None:
            temp_voice_max = _temp_voice_max(current.get("temp_voice_max"))
        else:
            temp_voice_max = _temp_voice_max(temp_voice_max)
        if event_channel is None:
            event_channel = current.get("event_channel") or None
        elif not str(event_channel).strip():
            event_channel = None
        else:
            event_channel = str(event_channel)
        if log_channel is None:
            log_channel = str(current.get("log_channel") or "") or None
        elif not str(log_channel).strip():
            log_channel = None
        else:
            log_channel = str(log_channel)
        temp_voice_hub_id = str(current.get("temp_voice_hub_id") or "") or None
        settings["wow"] = {
            "channel_mode": channel_mode,
            "raid_channel": raid_channel,
            "dungeon_channel": dungeon_channel if channel_mode == "split" else None,
            "event_channel": event_channel,
            "log_channel": log_channel,
            "poster_roles": poster_roles,
            "signup_roles": signup_roles,
            "attendance_roles": attendance_roles,
            "settings_roles": settings_roles,
            "mentions": mentions,
            "reminder": reminder,
            "reminder_2": reminder_2,
            "close_at_start": bool(close_at_start),
            "posted_ahead": posted_ahead,
            "question_thread": bool(question_thread),
            "voice_category": voice_category,
            "banner_hidden": banner_hidden,
            "temp_voice": bool(temp_voice),
            "temp_voice_category": temp_voice_category,
            "temp_voice_limit": temp_voice_limit,
            "temp_voice_hub": temp_voice_hub,
            "temp_voice_prefix": temp_voice_prefix,
            "temp_voice_roles": temp_voice_roles,
            "temp_voice_empty": temp_voice_empty,
            "temp_voice_max": temp_voice_max,
            "temp_voice_hub_id": temp_voice_hub_id,
        }
        if tickets is not None:
            settings["tickets"] = tickets
        if timezone:
            settings["timezone"] = timezone
        if companion_roles is not None:
            settings["companion_roles"] = _role_id_list({"companion_roles": list(companion_roles)}, "companion_roles")
        conn.execute("UPDATE guilds SET settings_json = ? WHERE slug = ?", (json.dumps(settings), slug))
        conn.commit()
        conn.close()
    return True


def set_temp_voice_hub_id(guild_id, channel_id):
    """Remember the Join channel. Other voice settings stay as they are."""
    guild_id = str(guild_id)
    channel_id = str(channel_id or "") or None
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT settings_json FROM guilds WHERE id = ?", (guild_id,)).fetchone()
        if row is None:
            conn.close()
            return False
        settings = _loads(row["settings_json"], default_settings())
        wow = dict(settings.get("wow") or {})
        wow["temp_voice_hub_id"] = channel_id
        settings["wow"] = wow
        conn.execute("UPDATE guilds SET settings_json = ? WHERE id = ?", (json.dumps(settings), guild_id))
        conn.commit()
        conn.close()
    return True


def add_temp_room(guild_id, channel_id, owner_id):
    with _LOCK:
        conn = connect()
        conn.execute(
            "INSERT OR REPLACE INTO temp_rooms (channel_id, guild_id, owner_id, empty_at) VALUES (?, ?, ?, NULL)",
            (str(channel_id), str(guild_id), str(owner_id)),
        )
        conn.commit()
        conn.close()


def temp_room(channel_id):
    conn = connect()
    row = conn.execute("SELECT * FROM temp_rooms WHERE channel_id = ?", (str(channel_id),)).fetchone()
    conn.close()
    if row is None:
        return None
    return {"channel_id": row["channel_id"], "guild_id": row["guild_id"], "owner_id": row["owner_id"], "empty_at": row["empty_at"]}


def temp_rooms(guild_id):
    conn = connect()
    rows = conn.execute("SELECT * FROM temp_rooms WHERE guild_id = ?", (str(guild_id),)).fetchall()
    conn.close()
    return [
        {"channel_id": row["channel_id"], "guild_id": row["guild_id"], "owner_id": row["owner_id"], "empty_at": row["empty_at"]}
        for row in rows
    ]


def mark_temp_room_empty(channel_id, empty_at):
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE temp_rooms SET empty_at = ? WHERE channel_id = ? AND empty_at IS NULL",
            (empty_at, str(channel_id)),
        )
        conn.commit()
        conn.close()


def clear_temp_room_empty(channel_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE temp_rooms SET empty_at = NULL WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()


def delete_temp_room(channel_id):
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM temp_rooms WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()


def _raid_from_row(row):
    return {
        "id": row["id"],
        "guild_id": row["guild_id"],
        "title": row["title"],
        "starts_at": row["starts_at"],
        "ends_at": row["ends_at"] if "ends_at" in row.keys() else None,
        "tank_cap": row["tank_cap"],
        "healer_cap": row["healer_cap"],
        "dps_cap": row["dps_cap"],
        "size": row["size"] if "size" in row.keys() else None,
        "instance_id": row["instance_id"] if "instance_id" in row.keys() else None,
        "note": row["note"] if "note" in row.keys() else None,
        "channel_id": row["channel_id"],
        "message_id": row["message_id"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "reminder_sent": row["reminder_sent"] if "reminder_sent" in row.keys() else 0,
        "reminder_minutes": row["reminder_minutes"] if "reminder_minutes" in row.keys() else 0,
        "reminder_2_minutes": row["reminder_2_minutes"] if "reminder_2_minutes" in row.keys() else 0,
        "reminder_2_sent": row["reminder_2_sent"] if "reminder_2_sent" in row.keys() else 0,
        "thread_id": row["thread_id"] if "thread_id" in row.keys() else None,
        "loot_rule": row["loot_rule"] if "loot_rule" in row.keys() else None,
        "voice_channel_id": row["voice_channel_id"] if "voice_channel_id" in row.keys() else None,
        "voice_state": row["voice_state"] if "voice_state" in row.keys() else None,
        "voice_seen": row["voice_seen"] if "voice_seen" in row.keys() else 0,
        "voice_empty_at": row["voice_empty_at"] if "voice_empty_at" in row.keys() else None,
        "party_count": row["party_count"] if "party_count" in row.keys() else 1,
    }


def _signup_from_row(row):
    return {
        "raid_id": row["raid_id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "class_id": row["class_id"],
        "spec_id": row["spec_id"],
        "role": row["role"],
        "state": row["state"],
        "note": row["note"] if "note" in row.keys() else None,
        "character_id": row["character_id"] if "character_id" in row.keys() else None,
        "party": row["party"] if "party" in row.keys() else 1,
        "created_at": row["created_at"],
    }


def _signups(conn, raid_id):
    rows = conn.execute(
        "SELECT * FROM raid_signups WHERE raid_id = ? ORDER BY created_at, user_id",
        (raid_id,),
    ).fetchall()
    return [_signup_from_row(row) for row in rows]


def _draft_from_row(row):
    return {
        "id": row["id"],
        "guild_id": row["guild_id"],
        "user_id": row["user_id"],
        "created_by": row["created_by"],
        "instance_id": row["instance_id"],
        "when_text": row["when_text"],
        "tank_cap": row["tank_cap"],
        "healer_cap": row["healer_cap"],
        "dps_cap": row["dps_cap"],
        "loot": row["loot"],
        "title": row["title"],
        "note": row["note"],
        "weeks": row["weeks"],
        "step": row["step"],
    }


def set_banner_hidden(slug, instance_id, hidden):
    """Hide or show the Discord picture for one dungeon or raid."""
    instance_id = str(instance_id or "")
    if not re.fullmatch(r"[a-z0-9-]{1,60}", instance_id):
        return False
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT settings_json FROM guilds WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            conn.close()
            return False
        settings = _loads(row["settings_json"], default_settings())
        if guild_game(settings) != "wow":
            conn.close()
            return False
        wow = dict(settings.get("wow") or {})
        current = _banner_hidden(wow)
        if hidden and instance_id not in current:
            current.append(instance_id)
        if not hidden:
            current = [item for item in current if item != instance_id]
        wow["banner_hidden"] = current
        settings["wow"] = wow
        conn.execute("UPDATE guilds SET settings_json = ? WHERE slug = ?", (json.dumps(settings), slug))
        conn.commit()
        conn.close()
    return True


def create_command_draft(guild_id, user_id, kind, step, payload=None):
    """One open prompt of this kind per person. Starting again drops the previous one."""
    guild_id = str(guild_id)
    user_id = str(user_id)
    with _LOCK:
        conn = connect()
        conn.execute(
            "DELETE FROM command_drafts WHERE guild_id = ? AND user_id = ? AND kind = ?",
            (guild_id, user_id, kind),
        )
        cursor = conn.execute(
            """INSERT INTO command_drafts (guild_id, user_id, kind, step, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, kind, step, json.dumps(payload or {}), _utc_stamp()),
        )
        draft_id = cursor.lastrowid
        conn.commit()
        conn.close()
    return draft_id


def command_draft(draft_id):
    conn = connect()
    row = conn.execute("SELECT * FROM command_drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "guild_id": row["guild_id"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "step": row["step"],
        "payload": _loads(row["payload_json"], {}),
        "created_at": row["created_at"],
    }


def save_command_draft(draft_id, step, payload):
    with _LOCK:
        conn = connect()
        cursor = conn.execute(
            "UPDATE command_drafts SET step = ?, payload_json = ? WHERE id = ?",
            (step, json.dumps(payload or {}), draft_id),
        )
        saved = cursor.rowcount > 0
        conn.commit()
        conn.close()
    return saved


def delete_command_draft(draft_id):
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM command_drafts WHERE id = ?", (draft_id,))
        conn.commit()
        conn.close()


def create_raid_draft(guild_id, user_id, created_by):
    """One open prompt per person. Starting again drops the previous one."""
    guild_id = str(guild_id)
    user_id = str(user_id)
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM raid_drafts WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        cursor = conn.execute(
            """INSERT INTO raid_drafts
               (guild_id, user_id, created_by, step, created_at)
               VALUES (?, ?, ?, 'dungeon', ?)""",
            (guild_id, user_id, created_by or "Officer", _utc_stamp()),
        )
        draft_id = cursor.lastrowid
        conn.commit()
        conn.close()
    return draft_id


def raid_draft(draft_id):
    conn = connect()
    row = conn.execute("SELECT * FROM raid_drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    return _draft_from_row(row) if row else None


def save_raid_draft(draft_id, **fields):
    allowed = (
        "instance_id", "when_text", "tank_cap", "healer_cap", "dps_cap",
        "loot", "title", "note", "weeks", "step",
    )
    sets = []
    values = []
    for key in allowed:
        if key in fields:
            sets.append(f"{key} = ?")
            values.append(fields[key])
    if not sets:
        return False
    values.append(draft_id)
    with _LOCK:
        conn = connect()
        cursor = conn.execute(
            f"UPDATE raid_drafts SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        saved = cursor.rowcount > 0
        conn.commit()
        conn.close()
    return saved


def delete_raid_draft(draft_id):
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM raid_drafts WHERE id = ?", (draft_id,))
        conn.commit()
        conn.close()


def create_raid(guild_id, title, starts_at, tank_cap, healer_cap, dps_cap, channel_id, created_by, size, instance_id=None, note=None, status="open", loot_rule=None, ends_at=None, reminder_minutes=None, reminder_2_minutes=None):
    stamp = _utc_stamp()
    if status not in ("open", "scheduled"):
        status = "open"
    if reminder_minutes is None or reminder_2_minutes is None:
        guild = guild_by_id(guild_id)
        config = wow_settings((guild or {}).get("settings"))
        if reminder_minutes is None:
            reminder_minutes = parse_reminder_minutes(config["reminder"])
        if reminder_2_minutes is None:
            reminder_2_minutes = parse_second_reminder(config["reminder_2"], reminder_minutes)
    reminder_minutes = parse_reminder_minutes(reminder_minutes)
    reminder_2_minutes = parse_second_reminder(reminder_2_minutes, reminder_minutes)
    with _LOCK:
        conn = connect()
        cursor = conn.execute(
            """INSERT INTO raids
               (guild_id, title, starts_at, ends_at, tank_cap, healer_cap, dps_cap, channel_id, message_id, size, instance_id, note, status, created_by, created_at, loot_rule, reminder_minutes, reminder_2_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(guild_id),
                title,
                starts_at,
                ends_at,
                tank_cap,
                healer_cap,
                dps_cap,
                str(channel_id),
                size,
                instance_id,
                note,
                status,
                created_by,
                stamp,
                loot_rule,
                reminder_minutes,
                reminder_2_minutes,
            ),
        )
        raid_id = cursor.lastrowid
        conn.commit()
        conn.close()
    return raid_id


def set_raid_thread(raid_id, thread_id):
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE raids SET thread_id = ? WHERE id = ? AND thread_id IS NULL",
            (str(thread_id), raid_id),
        )
        conn.commit()
        conn.close()


def set_raid_voice(raid_id, channel_id):
    with _LOCK:
        conn = connect()
        conn.execute(
            """UPDATE raids
               SET voice_channel_id = ?, voice_state = 'open', voice_seen = 0, voice_empty_at = NULL
               WHERE id = ? AND (voice_state IS NULL OR voice_state = 'open')""",
            (str(channel_id), raid_id),
        )
        conn.commit()
        conn.close()


def raid_voice_channels(raid_id):
    conn = connect()
    rows = conn.execute(
        "SELECT party, channel_id, name FROM raid_voice_channels WHERE raid_id = ? ORDER BY party",
        (raid_id,),
    ).fetchall()
    conn.close()
    return [
        {"party": row["party"], "channel_id": row["channel_id"], "name": row["name"]}
        for row in rows
    ]


def save_raid_voice(raid_id, channels):
    """Store one voice channel per party. Party 1 stays the channel linked on the raid."""
    ordered = sorted(channels, key=lambda item: int(item[0]))
    primary = str(ordered[0][1]) if ordered else None
    for party, channel_id, _name in ordered:
        if int(party) == 1:
            primary = str(channel_id)
            break
    with _LOCK:
        conn = connect()
        current = conn.execute("SELECT voice_state FROM raids WHERE id = ?", (raid_id,)).fetchone()
        if current is None or current["voice_state"] == "done":
            conn.close()
            return False
        conn.execute("DELETE FROM raid_voice_channels WHERE raid_id = ?", (raid_id,))
        conn.executemany(
            "INSERT INTO raid_voice_channels (raid_id, party, channel_id, name) VALUES (?, ?, ?, ?)",
            [(raid_id, int(party), str(channel_id), name or "") for party, channel_id, name in ordered],
        )
        if current["voice_state"] == "open":
            conn.execute("UPDATE raids SET voice_channel_id = ? WHERE id = ?", (primary, raid_id))
        else:
            conn.execute(
                """UPDATE raids
                   SET voice_channel_id = ?, voice_state = 'open', voice_seen = 0, voice_empty_at = NULL
                   WHERE id = ? AND voice_state IS NULL""",
                (primary, raid_id),
            )
        conn.commit()
        conn.close()
    return True


def mark_voice_seen(raid_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE raids SET voice_seen = 1 WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()


def mark_voice_empty(raid_id, stamp):
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE raids SET voice_empty_at = ? WHERE id = ? AND voice_empty_at IS NULL",
            (stamp, raid_id),
        )
        conn.commit()
        conn.close()


def clear_voice_empty(raid_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE raids SET voice_empty_at = NULL WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()


def raid_by_voice_channel(channel_id):
    conn = connect()
    row = conn.execute(
        """SELECT raids.* FROM raid_voice_channels
           JOIN raids ON raids.id = raid_voice_channels.raid_id
           WHERE raid_voice_channels.channel_id = ? AND raids.voice_state = 'open'""",
        (str(channel_id),),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM raids WHERE voice_channel_id = ? AND voice_state = 'open'",
            (str(channel_id),),
        ).fetchone()
    conn.close()
    return _raid_from_row(row) if row else None


def begin_voice_stay(raid_id, user_id, name, joined_at):
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE voice_stays SET left_at = ? WHERE raid_id = ? AND user_id = ? AND left_at IS NULL",
            (joined_at, raid_id, str(user_id)),
        )
        conn.execute(
            "INSERT INTO voice_stays (raid_id, user_id, name, joined_at, left_at) VALUES (?, ?, ?, ?, NULL)",
            (raid_id, str(user_id), name, joined_at),
        )
        conn.commit()
        conn.close()


def end_voice_stay(raid_id, user_id, left_at):
    with _LOCK:
        conn = connect()
        conn.execute(
            "UPDATE voice_stays SET left_at = ? WHERE raid_id = ? AND user_id = ? AND left_at IS NULL",
            (left_at, raid_id, str(user_id)),
        )
        conn.commit()
        conn.close()


def open_voice_count(raid_id):
    conn = connect()
    row = conn.execute(
        "SELECT COUNT(DISTINCT user_id) AS n FROM voice_stays WHERE raid_id = ? AND left_at IS NULL",
        (raid_id,),
    ).fetchone()
    conn.close()
    return row["n"]


def voice_stays(raid_id):
    conn = connect()
    rows = conn.execute(
        "SELECT user_id, name, joined_at, left_at FROM voice_stays WHERE raid_id = ? ORDER BY id",
        (raid_id,),
    ).fetchall()
    conn.close()
    return [
        {"user_id": row["user_id"], "name": row["name"], "joined_at": row["joined_at"], "left_at": row["left_at"]}
        for row in rows
    ]


def finish_voice(raid_id, people):
    """Freeze who stayed long enough, then forget the channel id."""
    with _LOCK:
        conn = connect()
        current = conn.execute("SELECT voice_state FROM raids WHERE id = ?", (raid_id,)).fetchone()
        if current is None or current["voice_state"] == "done":
            conn.close()
            return False
        conn.execute("DELETE FROM raid_attendance WHERE raid_id = ?", (raid_id,))
        conn.executemany(
            "INSERT INTO raid_attendance (raid_id, user_id, name, present) VALUES (?, ?, ?, 1)",
            [(raid_id, person["user_id"], person["name"]) for person in people],
        )
        conn.execute("DELETE FROM raid_voice_channels WHERE raid_id = ?", (raid_id,))
        conn.execute(
            """UPDATE raids
               SET voice_state = 'done', voice_channel_id = NULL, voice_empty_at = NULL
               WHERE id = ?""",
            (raid_id,),
        )
        conn.commit()
        conn.close()
    return True


def attendance_for(raid_id):
    conn = connect()
    rows = conn.execute(
        "SELECT user_id, name, present FROM raid_attendance WHERE raid_id = ? ORDER BY name COLLATE NOCASE",
        (raid_id,),
    ).fetchall()
    conn.close()
    return [{"user_id": row["user_id"], "name": row["name"], "present": bool(row["present"])} for row in rows]


def set_attendance(raid_id, user_id, name, present):
    with _LOCK:
        conn = connect()
        conn.execute(
            """INSERT INTO raid_attendance (raid_id, user_id, name, present) VALUES (?, ?, ?, ?)
               ON CONFLICT(raid_id, user_id) DO UPDATE SET name = excluded.name, present = excluded.present""",
            (raid_id, str(user_id), name, 1 if present else 0),
        )
        conn.commit()
        conn.close()


def member_activity(guild_id):
    """Signups and attendance marks for every raid of this server."""
    conn = connect()
    signups = conn.execute(
        """SELECT raids.id AS raid_id, raids.title AS title, raids.starts_at AS starts_at, raids.ends_at AS ends_at, raids.status AS status,
                  raid_signups.user_id AS user_id, raid_signups.state AS state, raid_signups.name AS name,
                  raid_signups.class_id AS class_id, raid_signups.spec_id AS spec_id
           FROM raid_signups
           JOIN raids ON raids.id = raid_signups.raid_id
           WHERE raids.guild_id = ?
           ORDER BY raids.starts_at DESC, raids.id DESC""",
        (str(guild_id),),
    ).fetchall()
    marks = conn.execute(
        """SELECT raids.id AS raid_id, raids.title AS title, raids.starts_at AS starts_at, raids.ends_at AS ends_at, raids.status AS status,
                  raid_attendance.user_id AS user_id, raid_attendance.present AS present
           FROM raid_attendance
           JOIN raids ON raids.id = raid_attendance.raid_id
           WHERE raids.guild_id = ?""",
        (str(guild_id),),
    ).fetchall()
    conn.close()
    return (
        [
            {
                "raid_id": row["raid_id"],
                "title": row["title"],
                "starts_at": row["starts_at"],
                "ends_at": row["ends_at"],
                "status": row["status"],
                "user_id": str(row["user_id"]),
                "state": row["state"] or "",
                "name": row["name"] or "",
                "class_id": row["class_id"] or "",
                "spec_id": row["spec_id"] or "",
            }
            for row in signups
        ],
        [
            {
                "raid_id": row["raid_id"],
                "title": row["title"],
                "starts_at": row["starts_at"],
                "ends_at": row["ends_at"],
                "status": row["status"],
                "user_id": str(row["user_id"]),
                "present": bool(row["present"]),
            }
            for row in marks
        ],
    )


def closed_raids(guild_id):
    """Closed raids only, oldest first. Used to score who was there."""
    conn = connect()
    rows = conn.execute(
        """SELECT id, title, starts_at, ends_at, status FROM raids
           WHERE guild_id = ? AND status = 'closed'
           ORDER BY starts_at, id""",
        (str(guild_id),),
    ).fetchall()
    conn.close()
    return [
        {"id": row["id"], "title": row["title"], "starts_at": row["starts_at"], "ends_at": row["ends_at"], "status": row["status"]}
        for row in rows
    ]


def attendance_counts(guild_id):
    """Present marks against signups that took a spot on a closed raid."""
    conn = connect()
    signed = conn.execute(
        """SELECT raid_signups.user_id AS user_id, COUNT(*) AS n
           FROM raid_signups
           JOIN raids ON raids.id = raid_signups.raid_id
           WHERE raids.guild_id = ? AND raids.status = 'closed'
             AND raid_signups.state IN ('main', 'late')
           GROUP BY raid_signups.user_id""",
        (str(guild_id),),
    ).fetchall()
    present = conn.execute(
        """SELECT raid_attendance.user_id AS user_id, COUNT(*) AS n
           FROM raid_attendance
           JOIN raids ON raids.id = raid_attendance.raid_id
           WHERE raids.guild_id = ? AND raid_attendance.present = 1
           GROUP BY raid_attendance.user_id""",
        (str(guild_id),),
    ).fetchall()
    conn.close()
    counts = {}
    for row in signed:
        counts[row["user_id"]] = {"signed": row["n"], "present": 0}
    for row in present:
        slot = counts.setdefault(row["user_id"], {"signed": 0, "present": 0})
        slot["present"] = row["n"]
    return counts


def set_raid_message(raid_id, message_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE raids SET message_id = ? WHERE id = ?", (str(message_id), raid_id))
        conn.commit()
        conn.close()


def delete_raid(raid_id):
    with _LOCK:
        conn = connect()
        conn.execute("DELETE FROM raid_signups WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM voice_stays WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM raid_attendance WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM raid_voice_channels WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM raids WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()


def hold_raid(raid_id):
    """Take a posted raid out of Discord and put it back in the queue. Signups stay."""
    with _LOCK:
        conn = connect()
        current = conn.execute(
            "SELECT voice_state FROM raids WHERE id = ? AND status = 'open'",
            (raid_id,),
        ).fetchone()
        if current is not None and current["voice_state"] != "done":
            conn.execute("DELETE FROM raid_voice_channels WHERE raid_id = ?", (raid_id,))
        conn.execute(
            """UPDATE raids
               SET status = 'scheduled', message_id = NULL, thread_id = NULL, reminder_sent = 0, reminder_2_sent = 0,
                   voice_channel_id = CASE WHEN voice_state = 'done' THEN voice_channel_id ELSE NULL END,
                   voice_state = CASE WHEN voice_state = 'done' THEN voice_state ELSE NULL END,
                   voice_seen = CASE WHEN voice_state = 'done' THEN voice_seen ELSE 0 END,
                   voice_empty_at = CASE WHEN voice_state = 'done' THEN voice_empty_at ELSE NULL END
               WHERE id = ? AND status = 'open'""",
            (raid_id,),
        )
        conn.commit()
        conn.close()


def close_raid(raid_id):
    with _LOCK:
        conn = connect()
        conn.execute("UPDATE raids SET status = 'closed' WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()


def mark_raid_posted(raid_id, message_id, channel_id, reminder_sent=0, reminder_2_sent=0):
    """A waiting raid is now the Discord post. A moment that has already passed is not reminded."""
    with _LOCK:
        conn = connect()
        conn.execute(
            """UPDATE raids
               SET status = 'open', message_id = ?, channel_id = ?, reminder_sent = ?, reminder_2_sent = ?
               WHERE id = ? AND status = 'scheduled'""",
            (str(message_id), str(channel_id), 1 if reminder_sent else 0, 1 if reminder_2_sent else 0, raid_id),
        )
        conn.commit()
        conn.close()


_KEEP = object()


def update_raid(raid_id, guild_id, starts_at, tank_cap, healer_cap, dps_cap, note, loot_rule=_KEEP, ends_at=_KEEP, reminder_minutes=_KEEP, reminder_2_minutes=_KEEP):
    """Change the time, end, note, loot rule, reminders and spots. A new start can send the reminders again."""
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT * FROM raids WHERE id = ?", (raid_id,)).fetchone()
        if row is None or str(row["guild_id"]) != str(guild_id) or row["status"] not in ("open", "scheduled"):
            conn.close()
            return False
        reminded = row["reminder_sent"] if "reminder_sent" in row.keys() else 0
        reminded_2 = row["reminder_2_sent"] if "reminder_2_sent" in row.keys() else 0
        if row["starts_at"] != starts_at:
            reminded = 0
            reminded_2 = 0
        if loot_rule is _KEEP:
            loot_rule = row["loot_rule"] if "loot_rule" in row.keys() else None
        if ends_at is _KEEP:
            ends_at = row["ends_at"] if "ends_at" in row.keys() else None
        if reminder_minutes is _KEEP:
            reminder_minutes = row["reminder_minutes"] if "reminder_minutes" in row.keys() else 0
        reminder_minutes = parse_reminder_minutes(reminder_minutes)
        if reminder_2_minutes is _KEEP:
            reminder_2_minutes = row["reminder_2_minutes"] if "reminder_2_minutes" in row.keys() else 0
        reminder_2_minutes = parse_second_reminder(reminder_2_minutes, reminder_minutes)
        conn.execute(
            """UPDATE raids
               SET starts_at = ?, ends_at = ?, tank_cap = ?, healer_cap = ?, dps_cap = ?, note = ?,
                   reminder_sent = ?, reminder_2_sent = ?, loot_rule = ?, reminder_minutes = ?, reminder_2_minutes = ?
               WHERE id = ?""",
            (
                starts_at,
                ends_at,
                tank_cap,
                healer_cap,
                dps_cap,
                note,
                reminded,
                reminded_2,
                loot_rule,
                reminder_minutes,
                reminder_2_minutes,
                raid_id,
            ),
        )
        conn.commit()
        conn.close()
    return True


def mark_reminders(raid_id, first=False, second=False):
    parts = []
    if first:
        parts.append("reminder_sent = 1")
    if second:
        parts.append("reminder_2_sent = 1")
    if not parts:
        return
    with _LOCK:
        conn = connect()
        conn.execute(f"UPDATE raids SET {', '.join(parts)} WHERE id = ?", (raid_id,))
        conn.commit()
        conn.close()


def mark_reminder_sent(raid_id, second=False):
    mark_reminders(raid_id, first=not second, second=second)


def raid_by_id(raid_id):
    conn = connect()
    row = conn.execute("SELECT * FROM raids WHERE id = ?", (raid_id,)).fetchone()
    raid = _raid_from_row(row) if row else None
    conn.close()
    return raid


def raids_for_guild(guild_id):
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM raids WHERE guild_id = ? ORDER BY starts_at DESC, id DESC",
        (str(guild_id),),
    ).fetchall()
    raids = []
    for row in rows:
        raid = _raid_from_row(row)
        raid["signups"] = _signups(conn, raid["id"])
        raids.append(raid)
    conn.close()
    return raids


def signups_for(raid_id):
    conn = connect()
    signups = _signups(conn, raid_id)
    conn.close()
    return signups


def _character_from_row(row):
    return {
        "id": row["id"],
        "guild_id": row["guild_id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "class_id": row["class_id"],
        "spec_id": row["spec_id"],
        "role": row["role"],
        "updated_at": row["updated_at"],
    }


def wow_characters_for(guild_id, user_id):
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM wow_characters
           WHERE guild_id = ? AND user_id = ?
           ORDER BY name COLLATE NOCASE""",
        (str(guild_id), str(user_id)),
    ).fetchall()
    conn.close()
    return [_character_from_row(row) for row in rows]


def wow_character_owned(guild_id, user_id, character_id):
    conn = connect()
    row = conn.execute(
        "SELECT * FROM wow_characters WHERE id = ? AND guild_id = ? AND user_id = ?",
        (character_id, str(guild_id), str(user_id)),
    ).fetchone()
    conn.close()
    return _character_from_row(row) if row else None


def wow_characters(guild_id):
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM wow_characters WHERE guild_id = ? ORDER BY name COLLATE NOCASE",
        (str(guild_id),),
    ).fetchall()
    conn.close()
    return [_character_from_row(row) for row in rows]


def save_wow_character(guild_id, user_id, name, class_id, spec_id, role, character_id=None):
    """Save one character for this Discord account. Returns an id, or duplicate, limit, or missing."""
    guild_id = str(guild_id)
    user_id = str(user_id)
    stamp = _utc_stamp()
    with _LOCK:
        conn = connect()
        taken = conn.execute(
            """SELECT id FROM wow_characters
               WHERE guild_id = ? AND user_id = ? AND name = ? COLLATE NOCASE""",
            (guild_id, user_id, name),
        ).fetchone()
        if character_id is None:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM wow_characters WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()["n"]
            if count >= 9:
                conn.close()
                return "limit"
            if taken is not None:
                conn.close()
                return "duplicate"
            cursor = conn.execute(
                """INSERT INTO wow_characters
                   (guild_id, user_id, name, class_id, spec_id, role, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (guild_id, user_id, name, class_id, spec_id, role, stamp),
            )
            character_id = cursor.lastrowid
        else:
            owned = conn.execute(
                "SELECT id FROM wow_characters WHERE id = ? AND guild_id = ? AND user_id = ?",
                (character_id, guild_id, user_id),
            ).fetchone()
            if owned is None:
                conn.close()
                return "missing"
            if taken is not None and int(taken["id"]) != int(character_id):
                conn.close()
                return "duplicate"
            conn.execute(
                """UPDATE wow_characters
                   SET name = ?, class_id = ?, spec_id = ?, role = ?, updated_at = ?
                   WHERE id = ? AND guild_id = ? AND user_id = ?""",
                (name, class_id, spec_id, role, stamp, character_id, guild_id, user_id),
            )
        conn.commit()
        conn.close()
    return int(character_id)


def delete_wow_character(guild_id, user_id, character_id, any_owner=False):
    """Remove one character. any_owner is for someone who can edit settings."""
    with _LOCK:
        conn = connect()
        if any_owner:
            cursor = conn.execute(
                "DELETE FROM wow_characters WHERE id = ? AND guild_id = ?",
                (character_id, str(guild_id)),
            )
        else:
            cursor = conn.execute(
                "DELETE FROM wow_characters WHERE id = ? AND guild_id = ? AND user_id = ?",
                (character_id, str(guild_id), str(user_id)),
            )
        deleted = cursor.rowcount > 0
        if deleted:
            conn.execute("DELETE FROM character_wishes WHERE character_id = ?", (character_id,))
        conn.commit()
        conn.close()
    return deleted


WISH_LIMIT = 10


def character_wishes(character_id):
    conn = connect()
    rows = conn.execute(
        """SELECT instance_id, item_key FROM character_wishes
           WHERE character_id = ? ORDER BY instance_id, item_key""",
        (character_id,),
    ).fetchall()
    conn.close()
    return [{"instance_id": row["instance_id"], "item_key": row["item_key"]} for row in rows]


def wish_counts(character_ids):
    ids = [int(item) for item in character_ids]
    if not ids:
        return {}
    conn = connect()
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT character_id, COUNT(*) AS n FROM character_wishes WHERE character_id IN ({marks}) GROUP BY character_id",
        ids,
    ).fetchall()
    conn.close()
    return {row["character_id"]: row["n"] for row in rows}


def wishes_for_characters(character_ids):
    ids = [int(item) for item in character_ids if item]
    if not ids:
        return []
    conn = connect()
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT character_id, instance_id, item_key FROM character_wishes
            WHERE character_id IN ({marks})""",
        ids,
    ).fetchall()
    conn.close()
    return [
        {"character_id": row["character_id"], "instance_id": row["instance_id"], "item_key": row["item_key"]}
        for row in rows
    ]


def save_character_wishes(guild_id, user_id, character_id, choices):
    """Replace this character's wanted items. More than 10 is rejected."""
    unique = []
    seen = set()
    for instance_id, item_key in choices:
        pair = (str(instance_id), str(item_key))
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    if len(unique) > WISH_LIMIT:
        return "wish_limit"
    with _LOCK:
        conn = connect()
        owned = conn.execute(
            "SELECT id FROM wow_characters WHERE id = ? AND guild_id = ? AND user_id = ?",
            (character_id, str(guild_id), str(user_id)),
        ).fetchone()
        if owned is None:
            conn.close()
            return "missing"
        conn.execute("DELETE FROM character_wishes WHERE character_id = ?", (character_id,))
        conn.executemany(
            """INSERT INTO character_wishes (character_id, guild_id, instance_id, item_key)
               VALUES (?, ?, ?, ?)""",
            [(character_id, str(guild_id), instance_id, item_key) for instance_id, item_key in unique],
        )
        conn.commit()
        conn.close()
    return None


def place_signup(raid, user_id, name, class_id, spec_id, role, kind="main", note=None, character_id=None):
    """One Discord account keeps one spot. Main and late fill a role. Bench, tentative and absent do not."""
    user_id = str(user_id)
    caps = {"tank": raid["tank_cap"], "healer": raid["healer_cap"], "dps": raid["dps_cap"]}
    bucket = "dps" if role in ("melee", "ranged", "dps") else role
    occupies = kind in ("main", "late")
    stamp = _utc_stamp()
    with _LOCK:
        conn = connect()
        current = conn.execute("SELECT status FROM raids WHERE id = ?", (raid["id"],)).fetchone()
        if current is None or current["status"] != "open":
            conn.close()
            return None
        existing = conn.execute(
            "SELECT role, state, party, created_at FROM raid_signups WHERE raid_id = ? AND user_id = ?",
            (raid["id"], user_id),
        ).fetchone()
        party_count = int(raid.get("party_count") or 1)
        kept = (
            existing
            and _same_cap(existing["role"], role)
            and existing["state"] in ("main", "late", "reserve")
            and not (existing["state"] != "reserve" and int(existing["party"] or 1) > party_count)
        )
        event = str(raid.get("instance_id") or "") == "event"
        if not occupies:
            state = kind
            party = 1
            created_at = existing["created_at"] if existing else stamp
        elif event:
            state = "late" if kind == "late" else "main"
            party = 1
            created_at = existing["created_at"] if existing else stamp
        elif kept:
            if existing["state"] == "reserve":
                state = "reserve"
                party = 1
            else:
                state = "late" if kind == "late" else "main"
                party = int(existing["party"] or 1)
                if party > party_count:
                    party = 1
            created_at = existing["created_at"]
        else:
            rows = conn.execute(
                """SELECT role, party FROM raid_signups
                   WHERE raid_id = ? AND state IN ('main', 'late') AND user_id != ?""",
                (raid["id"], user_id),
            ).fetchall()
            state = "reserve"
            party = 1
            for party_no in range(1, party_count + 1):
                count = sum(
                    1
                    for row in rows
                    if int(row["party"] or 1) == party_no and _same_cap(row["role"], role)
                )
                if count < caps.get(bucket, 0):
                    state = "late" if kind == "late" else "main"
                    party = party_no
                    break
            created_at = stamp
        conn.execute(
            """INSERT INTO raid_signups
               (raid_id, user_id, name, class_id, spec_id, role, state, note, character_id, party, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(raid_id, user_id) DO UPDATE SET
                 name = excluded.name,
                 class_id = excluded.class_id,
                 spec_id = excluded.spec_id,
                 role = excluded.role,
                 state = excluded.state,
                 note = excluded.note,
                 character_id = excluded.character_id,
                 party = excluded.party,
                 created_at = excluded.created_at""",
            (raid["id"], user_id, name, class_id, spec_id, role, state, note, character_id, party, created_at),
        )
        conn.commit()
        conn.close()
    return state


def _same_cap(left, right):
    def bucket(role):
        return "dps" if role in ("melee", "ranged", "dps") else role

    return bucket(left) == bucket(right)


def set_signup_lane(raid_id, user_id, role, state, party=1):
    """Officer move. Keeps the character, the note and whether they were late when the caller says so."""
    if role not in ("tank", "melee", "ranged", "healer") or state not in ("main", "late", "reserve"):
        return False
    party = 1 if state == "reserve" else int(party or 1)
    with _LOCK:
        conn = connect()
        current = conn.execute("SELECT status FROM raids WHERE id = ?", (raid_id,)).fetchone()
        if current is None or current["status"] != "open":
            conn.close()
            return False
        cursor = conn.execute(
            """UPDATE raid_signups SET role = ?, state = ?, party = ?
               WHERE raid_id = ? AND user_id = ? AND state IN ('main', 'late', 'reserve')""",
            (role, state, party, raid_id, str(user_id)),
        )
        moved = cursor.rowcount > 0
        conn.commit()
        conn.close()
    return moved


def _cap_bucket(role):
    return "dps" if role in ("melee", "ranged", "dps") else role


def _fill_party(conn, raid_id, party_no, tank_cap, healer_cap, dps_cap):
    """Move the earliest reserves into one party while a matching spot is open."""
    party_no = int(party_no)
    if party_no < 2:
        return
    caps = {"tank": int(tank_cap or 0), "healer": int(healer_cap or 0), "dps": int(dps_cap or 0)}
    counts = {"tank": 0, "healer": 0, "dps": 0}
    seated = conn.execute(
        """SELECT role FROM raid_signups
           WHERE raid_id = ? AND party = ? AND state IN ('main', 'late')""",
        (raid_id, party_no),
    ).fetchall()
    for seated_row in seated:
        bucket = _cap_bucket(seated_row["role"])
        if bucket in counts:
            counts[bucket] += 1
    waiting = conn.execute(
        """SELECT user_id, role FROM raid_signups
           WHERE raid_id = ? AND state = 'reserve'
           ORDER BY created_at, user_id""",
        (raid_id,),
    ).fetchall()
    for person in waiting:
        bucket = _cap_bucket(person["role"])
        if bucket not in counts or counts[bucket] >= caps[bucket]:
            continue
        conn.execute(
            """UPDATE raid_signups SET state = 'main', party = ?
               WHERE raid_id = ? AND user_id = ? AND state = 'reserve'""",
            (party_no, raid_id, person["user_id"]),
        )
        counts[bucket] += 1


def set_party_count(raid_id, count):
    """Open parties up to the cap. A new party fills from the reserve. A removed party goes back there."""
    count = int(count)
    if count < 1 or count > MAX_PARTIES:
        return False
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT * FROM raids WHERE id = ?", (raid_id,)).fetchone()
        if row is None or row["status"] != "open":
            conn.close()
            return False
        current = int(row["party_count"] or 1)
        if count == current:
            conn.close()
            return True
        if count < current:
            conn.execute(
                """UPDATE raid_signups SET state = 'reserve', party = 1
                   WHERE raid_id = ? AND party > ? AND state IN ('main', 'late')""",
                (raid_id, count),
            )
        conn.execute("UPDATE raids SET party_count = ? WHERE id = ?", (count, raid_id))
        if count > current:
            for party_no in range(2, count + 1):
                _fill_party(conn, raid_id, party_no, row["tank_cap"], row["healer_cap"], row["dps_cap"])
        conn.commit()
        conn.close()
    return True


def set_second_party(raid_id, enabled):
    """Older call. Opens party 2, or leaves only party 1."""
    return set_party_count(raid_id, 2 if enabled else 1)


def fill_open_parties(raid_id):
    """After the spots grow, pull reserves into party 2 and then the later parties."""
    with _LOCK:
        conn = connect()
        row = conn.execute("SELECT * FROM raids WHERE id = ?", (raid_id,)).fetchone()
        count = 0 if row is None or row["status"] != "open" else int(row["party_count"] or 1)
        if count < 2:
            conn.close()
            return False
        for party_no in range(2, min(count, MAX_PARTIES) + 1):
            _fill_party(conn, raid_id, party_no, row["tank_cap"], row["healer_cap"], row["dps_cap"])
        conn.commit()
        conn.close()
    return True


def fill_second_party(raid_id):
    return fill_open_parties(raid_id)


def remove_signup(raid_id, user_id):
    """Free the spot. Someone on the reserve stays there."""
    with _LOCK:
        conn = connect()
        cursor = conn.execute(
            "DELETE FROM raid_signups WHERE raid_id = ? AND user_id = ?",
            (raid_id, str(user_id)),
        )
        removed = cursor.rowcount > 0
        conn.commit()
        conn.close()
    return removed


def drop_open_signups(guild_id, user_id):
    """Remove this account from open raids. Returns those raids so their messages can be rewritten."""
    with _LOCK:
        conn = connect()
        rows = conn.execute(
            """SELECT raids.* FROM raids
               JOIN raid_signups ON raid_signups.raid_id = raids.id
               WHERE raids.guild_id = ? AND raids.status = 'open' AND raid_signups.user_id = ?""",
            (str(guild_id), str(user_id)),
        ).fetchall()
        raids = [_raid_from_row(row) for row in rows]
        if raids:
            conn.execute(
                """DELETE FROM raid_signups
                   WHERE user_id = ? AND raid_id IN (
                     SELECT id FROM raids WHERE guild_id = ? AND status = 'open'
                   )""",
                (str(user_id), str(guild_id)),
            )
        conn.commit()
        conn.close()
    return raids


def rename_wow_player(guild_id, user_id, name):
    """A nickname change updates signups that used the Discord name. Saved characters keep their own name."""
    with _LOCK:
        conn = connect()
        rows = conn.execute(
            """SELECT raids.* FROM raids
               JOIN raid_signups ON raid_signups.raid_id = raids.id
               WHERE raids.guild_id = ? AND raids.status = 'open'
                 AND raid_signups.user_id = ? AND raid_signups.character_id IS NULL""",
            (str(guild_id), str(user_id)),
        ).fetchall()
        raids = [_raid_from_row(row) for row in rows]
        if raids:
            conn.execute(
                """UPDATE raid_signups SET name = ?
                   WHERE user_id = ? AND character_id IS NULL AND raid_id IN (
                     SELECT id FROM raids WHERE guild_id = ? AND status = 'open'
                   )""",
                (name, str(user_id), str(guild_id)),
            )
        conn.commit()
        conn.close()
    return raids


def store_member(user_id, guild_id, member, role_ids):
    stamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with _LOCK:
        conn = connect()
        conn.execute(
            """INSERT INTO member_cache (user_id, guild_id, role_ids_json, checked_at, member) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET
                 role_ids_json = excluded.role_ids_json,
                 checked_at = excluded.checked_at,
                 member = excluded.member""",
            (str(user_id), str(guild_id), json.dumps(role_ids), stamp, 1 if member else 0),
        )
        conn.commit()
        conn.close()
