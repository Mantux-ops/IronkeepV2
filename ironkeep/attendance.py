"""The group list the companion sends after logout or /reload."""

import hashlib
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config, db

MAX_BYTES = 65536
MAX_PEOPLE = 40

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

_TOKENS = {}
_REPORTS = {}


class ReportError(Exception):
    pass


def normalize(text):
    if not isinstance(text, str):
        raise ReportError("This report could not be read.")
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()


def digest(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def parse_text(text):
    """Read the copy-list text. The last line is format: ironkeep-group 1."""
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
    if len(place) > 80 or len(started) > 32:
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
        if status not in ("here", "left") or not _plain(name, 48, required=True):
            raise ReportError("This report could not be read.")
        if not _plain(class_name, 32) or not _plain(role, 16) or not _plain(seen, 16):
            raise ReportError("This report could not be read.")
        people.append(
            {
                "name": name,
                "class_name": class_name,
                "role": role,
                "time": seen,
                "here": status == "here",
            }
        )
    if len(people) > MAX_PEOPLE:
        raise ReportError("This report has too many people.")
    return {"place": place or "Unknown", "started": started, "people": people}


def _plain(value, limit, required=False):
    if required and not value:
        return False
    if len(value) > limit:
        return False
    return all(char.isalnum() or char in " '-" for char in value)


def class_color(name):
    return CLASS_COLORS.get((name or "").casefold(), "#8d95a1")


def without_secret(settings):
    copied = dict(settings or {})
    copied.pop("attendance_token", None)
    return copied


def keep_token(existing, incoming):
    """The settings form posts the whole document. The companion key stays on the server."""
    saved = dict(incoming or {})
    saved.pop("attendance_token", None)
    current = str((existing or {}).get("attendance_token") or "")
    if current:
        saved["attendance_token"] = current
    return saved


def token_for(guild, rotate=False):
    if config.live():
        settings = dict(guild.get("settings") or {})
        current = str(settings.get("attendance_token") or "")
        if current and not rotate:
            return current
        fresh = secrets.token_urlsafe(24)
        settings["attendance_token"] = fresh
        db.save_settings(guild["slug"], settings)
        guild["settings"] = settings
        return fresh
    current = _TOKENS.get(guild["id"]) or ""
    if current and not rotate:
        return current
    fresh = secrets.token_urlsafe(24)
    _TOKENS[guild["id"]] = fresh
    return fresh


def token_matches(guild, given):
    if config.live():
        expected = str((guild.get("settings") or {}).get("attendance_token") or "")
    else:
        expected = _TOKENS.get(guild["id"]) or ""
    if not expected or not given:
        return False
    return secrets.compare_digest(expected, given)


def store(guild, report, body_hash):
    item = {
        "place": report["place"],
        "started": report["started"],
        "received_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "people": report["people"],
        "digest": body_hash,
    }
    if config.live():
        if not db.add_attendance(guild["id"], item):
            previous = db.attendance_by_hash(guild["id"], body_hash)
            return previous or item, True
        return item, False
    bucket = _REPORTS.setdefault(guild["id"], [])
    for old in bucket:
        if old.get("digest") == body_hash:
            return old, True
    bucket.append(item)
    del bucket[:-20]
    return item, False


def latest(guild):
    if config.live():
        return db.latest_attendance(guild["id"])
    bucket = _REPORTS.get(guild["id"]) or []
    return bucket[-1] if bucket else None


def present(stored, settings):
    shown = []
    for person in stored["people"]:
        shown.append({**person, "color": class_color(person["class_name"])})
    return {
        "place": stored["place"],
        "started": stored["started"],
        "received_label": _received_label(stored.get("received_at") or "", settings),
        "people": shown,
        "here": sum(1 for person in shown if person["here"]),
        "away": sum(1 for person in shown if not person["here"]),
    }


def _received_label(stamp, settings):
    if not stamp:
        return ""
    name = str((settings or {}).get("timezone") or "Europe/Amsterdam")
    try:
        zone = ZoneInfo(name)
    except Exception:
        zone = ZoneInfo("UTC")
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(zone).strftime("%d %b %Y, %H:%M")
