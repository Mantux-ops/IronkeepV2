"""Attendance reports uploaded by the desktop Companion.

These rows are the group list from Ironkeep.lua. They are not raid signups
and they are not written into raid_attendance. The raw report text is not
stored; only the parsed fields and a hash of the normalized text are.
"""

import hashlib
import json
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone

from . import db

MAX_BYTES = 65536
MAX_PEOPLE = 40
_LOCK = threading.Lock()
_TIME = re.compile(r"^(?:|<1m|[0-9]{1,4}m|[0-9]{1,4}h [0-9]{1,2}m)$")
_STARTED = re.compile(r"^(?:|\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
_ROLES = {"", "Tank", "Healer", "Damage"}
_HASH = re.compile(r"^[0-9a-f]{64}$")
# Lu/Ll/Lt/Lo are letters. Lm is a modifier letter (phonetic superscripts) and
# is not a character name. One combining mark may follow a letter after NFC.
_NAME_LETTERS = {"Lu", "Ll", "Lt", "Lo"}
_NAME_MIN = 2
_NAME_MAX = 12


class ReportError(Exception):
    pass


def normalize(text):
    if not isinstance(text, str):
        raise ReportError("This report could not be read.")
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()


def digest(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def parse_text(text):
    """Read the Companion group list. The last line is format: ironkeep-group 1."""
    text = normalize(text)
    lines = text.split("\n")
    if not lines or lines[0].strip() != "Ironkeep group":
        raise ReportError("This report could not be read.")
    body = [line.strip() for line in lines[1:]]
    while body and body[-1] == "":
        body.pop()
    if not body or body[-1] != "format: ironkeep-group 1":
        raise ReportError("This report could not be read.")
    body = body[:-1]
    while body and body[-1] == "":
        body.pop()

    place = ""
    started = ""
    header_at = None
    for index, line in enumerate(body):
        if line.startswith("Place: "):
            place = line[7:].strip()
        elif line.startswith("Started: "):
            started = line[9:].strip()
        elif line == "Name | Class | Role | Time | Status":
            header_at = index
    if not _place_ok(place) or _STARTED.fullmatch(started) is None:
        raise ReportError("This report could not be read.")
    if header_at is None:
        if any(line == "Nobody recorded yet." for line in body):
            return {"place": place or "Unknown", "started": started, "people": []}
        raise ReportError("This report could not be read.")

    people = []
    for line in body[header_at + 1 :]:
        if line == "" or line == "Nobody recorded yet.":
            continue
        parts = line.split(" | ")
        if len(parts) != 5:
            raise ReportError("This report could not be read.")
        name, class_name, role, seen, status = parts
        stored_name = _character_name(name)
        if status not in ("here", "left") or stored_name is None:
            raise ReportError("This report could not be read.")
        if role not in _ROLES or not _class_ok(class_name):
            raise ReportError("This report could not be read.")
        if _TIME.fullmatch(seen) is None:
            raise ReportError("This report could not be read.")
        people.append(
            {
                "name": stored_name,
                "class_name": class_name,
                "role": role,
                "time": seen,
                "here": status == "here",
            }
        )
    if len(people) > MAX_PEOPLE:
        raise ReportError("This report has too many people.")
    return {"place": place or "Unknown", "started": started, "people": people}


def _character_name(value):
    """NFC form of a character name copied from UnitFullName, or None.

    The addon writes one given name, or a given name and surname joined by a
    single ASCII space. It does not rewrite the characters the game returns.
    Each part is 2 to 12 letters in Unicode categories Lu, Ll, Lt, or Lo.
    After NFC, a letter may carry one combining mark (category M). Modifier
    letters (Lm), digits, punctuation, symbols, spaces inside a part, and
    control or format characters are rejected. An ASCII name that matched
    the previous letter rule still matches, and the report lines are unchanged.
    """
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value)
    if text == "" or text != text.strip() or "  " in text:
        return None
    parts = text.split(" ")
    if len(parts) > 2:
        return None
    for part in parts:
        if not _name_part(part):
            return None
    return text


def _name_part(part):
    letters = 0
    marks = 0
    for char in part:
        category = unicodedata.category(char)
        if category in _NAME_LETTERS:
            letters += 1
            marks = 0
            if letters > _NAME_MAX:
                return False
            continue
        if category.startswith("M") and letters and marks < 1:
            marks += 1
            continue
        return False
    return _NAME_MIN <= letters <= _NAME_MAX


def _class_ok(value):
    if len(value) > 32 or value.strip() != value:
        return False
    return all(char == " " or char.isalpha() for char in value)


def _place_ok(value):
    if len(value) > 80:
        return False
    for char in value:
        code = ord(char)
        if code < 32 or code == 127:
            return False
    return True


def store(guild_id, report, body_hash):
    """Insert one report. The same normalized text for this guild is kept once.

    Returns True when the hash was already stored. Accepted reports stay until
    the guild is deleted.
    """
    if _HASH.fullmatch(str(body_hash or "")) is None:
        raise ReportError("This report could not be read.")
    guild_id = str(guild_id)
    received = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    people = json.dumps(report["people"], separators=(",", ":"), ensure_ascii=True)
    with _LOCK:
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure(conn)
            try:
                conn.execute(
                    "INSERT INTO companion_report_hashes (guild_id, body_hash, first_seen) VALUES (?, ?, ?)",
                    (guild_id, body_hash, received),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return True
            conn.execute(
                """INSERT INTO companion_reports
                   (guild_id, place, started, received_at, people_json, body_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (guild_id, report["place"], report["started"], received, people, body_hash),
            )
            conn.commit()
            return False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _ensure(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companion_reports (
            id INTEGER PRIMARY KEY,
            guild_id TEXT NOT NULL,
            place TEXT NOT NULL,
            started TEXT NOT NULL,
            received_at TEXT NOT NULL,
            people_json TEXT NOT NULL,
            body_hash TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS companion_reports_guild
           ON companion_reports (guild_id, id)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companion_report_hashes (
            guild_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            PRIMARY KEY (guild_id, body_hash)
        )"""
    )
