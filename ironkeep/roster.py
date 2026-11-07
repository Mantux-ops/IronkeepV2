"""Guild roster snapshots uploaded by the Companion.

The body is canonical JSON, not an attendance report. One guild keeps one
current snapshot. An identical body is a duplicate. A later capturedAt replaces
it. An older or same-time different body does not.
"""

import hashlib
import json
import re
from datetime import datetime, timezone

from . import db

MAX_BYTES = 256 * 1024
MAX_MEMBERS = 500
CLOCK_SKEW_SECONDS = 300
_NAME = re.compile(r"^[\x20-\x7e]{1,64}$")
_GUID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_LABEL = re.compile(r"^[\x20-\x7e]{1,48}$")

_MEMBER_KEYS = ("className", "classToken", "guid", "level", "name", "rankName")


class RosterError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(snapshot):
    """Stable JSON. Key order matches sort_keys and members are ordered by GUID."""
    members = []
    for member in sorted(snapshot["members"], key=lambda item: item["guid"]):
        members.append({key: member[key] for key in _MEMBER_KEYS})
    payload = {
        "capturedAt": snapshot["capturedAt"],
        "members": members,
        "schema": 1,
        "wowGuildName": snapshot["wowGuildName"],
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True)


def parse_body(text):
    if not isinstance(text, str):
        raise RosterError("This roster could not be read.")
    text = text.lstrip("\ufeff").strip()
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise RosterError("This roster is too large.", 413)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise RosterError("This roster could not be read.") from error
    if not isinstance(raw, dict) or set(raw) != {"schema", "wowGuildName", "capturedAt", "members"}:
        raise RosterError("This roster could not be read.")
    if type(raw.get("schema")) is not int or raw.get("schema") != 1:
        raise RosterError("This roster could not be read.")
    name = raw.get("wowGuildName")
    if not isinstance(name, str) or _NAME.fullmatch(name.strip()) is None or not name.strip():
        raise RosterError("This roster could not be read.")
    captured = raw.get("capturedAt")
    if type(captured) is not int or isinstance(captured, bool) or captured < 0:
        raise RosterError("This roster could not be read.")
    members = raw.get("members")
    if not isinstance(members, list) or not members or len(members) > MAX_MEMBERS:
        raise RosterError("This roster could not be read.")
    parsed = []
    guids = set()
    names = set()
    for member in members:
        if not isinstance(member, dict) or set(member) != set(_MEMBER_KEYS):
            raise RosterError("This roster could not be read.")
        guid = member.get("guid")
        person = member.get("name")
        level = member.get("level")
        token = member.get("classToken")
        class_name = member.get("className")
        rank = member.get("rankName")
        if not isinstance(guid, str) or _GUID.fullmatch(guid) is None:
            raise RosterError("This roster could not be read.")
        if not isinstance(person, str) or _LABEL.fullmatch(person) is None or person.strip() == "":
            raise RosterError("This roster could not be read.")
        if type(level) is not int or isinstance(level, bool) or level < 0 or level > 999:
            raise RosterError("This roster could not be read.")
        if not isinstance(token, str) or _LABEL.fullmatch(token) is None or token.strip() == "":
            raise RosterError("This roster could not be read.")
        if not isinstance(class_name, str) or _LABEL.fullmatch(class_name) is None or class_name.strip() == "":
            raise RosterError("This roster could not be read.")
        if not isinstance(rank, str) or _LABEL.fullmatch(rank) is None or rank.strip() == "":
            raise RosterError("This roster could not be read.")
        if guid in guids or person.casefold() in names:
            raise RosterError("This roster could not be read.")
        guids.add(guid)
        names.add(person.casefold())
        parsed.append(
            {
                "guid": guid,
                "name": person,
                "level": level,
                "classToken": token,
                "className": class_name,
                "rankName": rank,
            }
        )
    snapshot = {"schema": 1, "wowGuildName": name.strip(), "capturedAt": captured, "members": parsed}
    body = canonical(snapshot)
    return snapshot, body, digest(body)


def store(guild_id, snapshot, body_hash, now=None):
    """Insert or replace one guild's current roster. Returns duplicate, stored, stale, conflict, or wrong-guild."""
    guild_id = str(guild_id)
    moment = int(datetime.now(timezone.utc).timestamp() if now is None else now)
    if snapshot["capturedAt"] > moment + CLOCK_SKEW_SECONDS:
        raise RosterError("This roster is in the future.")
    received = datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ordered = sorted(snapshot["members"], key=lambda item: item["guid"])
    members_json = json.dumps(ordered, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    name = snapshot["wowGuildName"]
    with db._LOCK:
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure(conn)
            if _hash_exists(conn, guild_id, body_hash):
                conn.rollback()
                return "duplicate"
            current = conn.execute(
                "SELECT wow_guild_name, captured_at, body_hash FROM roster_snapshots WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
            if current is not None and current["wow_guild_name"].casefold() != name.casefold():
                conn.rollback()
                return "wrong-guild"
            if current is not None and snapshot["capturedAt"] < int(current["captured_at"]):
                conn.rollback()
                return "stale"
            if current is not None and snapshot["capturedAt"] == int(current["captured_at"]):
                conn.rollback()
                return "conflict"
            conn.execute(
                "INSERT INTO roster_hashes (guild_id, body_hash, first_seen) VALUES (?, ?, ?)",
                (guild_id, body_hash, received),
            )
            if current is None:
                conn.execute(
                    """INSERT INTO roster_snapshots
                       (guild_id, wow_guild_name, captured_at, received_at, members_json, body_hash)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (guild_id, name, snapshot["capturedAt"], received, members_json, body_hash),
                )
            else:
                conn.execute(
                    """UPDATE roster_snapshots
                       SET captured_at = ?, received_at = ?, members_json = ?, body_hash = ?
                       WHERE guild_id = ?""",
                    (snapshot["capturedAt"], received, members_json, body_hash, guild_id),
                )
            conn.commit()
            return "stored"
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def current(guild_id):
    conn = db.connect()
    try:
        _ensure(conn)
        row = conn.execute(
            "SELECT wow_guild_name, captured_at, received_at, members_json, body_hash FROM roster_snapshots WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    captured = datetime.fromtimestamp(int(row["captured_at"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return {
        "wow_guild_name": row["wow_guild_name"],
        "captured_at": int(row["captured_at"]),
        "captured_label": captured,
        "received_at": row["received_at"],
        "body_hash": row["body_hash"],
        "members": json.loads(row["members_json"]),
    }


def delete_rows(conn, guild_id):
    """Drop this guild's roster when the tables exist. The caller owns the transaction."""
    present = {
        row[0]
        for row in conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name IN ('roster_snapshots', 'roster_hashes')"""
        )
    }
    guild_id = str(guild_id)
    if "roster_hashes" in present:
        conn.execute("DELETE FROM roster_hashes WHERE guild_id = ?", (guild_id,))
    if "roster_snapshots" in present:
        conn.execute("DELETE FROM roster_snapshots WHERE guild_id = ?", (guild_id,))


def _hash_exists(conn, guild_id, body_hash):
    row = conn.execute(
        "SELECT 1 FROM roster_hashes WHERE guild_id = ? AND body_hash = ?",
        (guild_id, body_hash),
    ).fetchone()
    return row is not None


def _ensure(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS roster_snapshots (
            guild_id TEXT PRIMARY KEY,
            wow_guild_name TEXT NOT NULL,
            captured_at INTEGER NOT NULL,
            received_at TEXT NOT NULL,
            members_json TEXT NOT NULL,
            body_hash TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS roster_hashes (
            guild_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            PRIMARY KEY (guild_id, body_hash)
        )"""
    )
