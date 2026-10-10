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


def trial_role_ids(settings):
    settings = settings or {}
    chosen = settings.get("trial_roles")
    if not isinstance(chosen, list) or not chosen:
        legacy = settings.get("trial_role")
        chosen = legacy if isinstance(legacy, list) else ([legacy] if legacy else [])
    return [str(role_id) for role_id in chosen if role_id]


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


def setup_complete(settings):
    """Roles and channels the dashboard actually asks for are filled in.

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
        conn.commit()
        conn.close()


def _loads(value, fallback):
    if not value:
        return fallback
    return json.loads(value)


def _guild_from_row(row, trials=None):
    settings = _loads(row["settings_json"], default_settings())
    settings["trial_roles"] = trial_role_ids(settings)
    settings.pop("trial_role", None)
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "icon_color": row["icon_color"],
        "icon_letter": icon_letter(row["name"]),
        "approval": row["approval"],
        "bot_present": bool(row["bot_present"]),
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


def upsert_guild(discord_id, name, roles, channels, *, added_by=None, added_by_id=None, rejoin=False):
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
                "INSERT INTO errors (at, guild, text, detail, resolved) VALUES (?, ?, ?, ?, 0)",
                (payload["at"], row["slug"], text, text),
            )
        conn.commit()
        conn.close()


def list_errors():
    conn = connect()
    rows = conn.execute("SELECT * FROM errors ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return [dict(row) for row in rows]


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


def cached_roles(user_id, guild_id, max_age_seconds=600):
    conn = connect()
    row = conn.execute(
        "SELECT role_ids_json, checked_at FROM member_cache WHERE user_id = ? AND guild_id = ?",
        (str(user_id), str(guild_id)),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    checked = datetime.strptime(row["checked_at"], "%Y-%m-%dT%H:%M:%S")
    if (datetime.utcnow() - checked).total_seconds() > max_age_seconds:
        return None
    return _loads(row["role_ids_json"], [])


def store_roles(user_id, guild_id, role_ids):
    stamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with _LOCK:
        conn = connect()
        conn.execute(
            """INSERT INTO member_cache (user_id, guild_id, role_ids_json, checked_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET role_ids_json = excluded.role_ids_json, checked_at = excluded.checked_at""",
            (str(user_id), str(guild_id), json.dumps(role_ids), stamp),
        )
        conn.commit()
        conn.close()
