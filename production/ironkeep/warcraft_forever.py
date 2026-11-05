"""Warcraft Forever class catalog.

The public catalog at warcraftforever.com supplies class names, order and icons.
Talent trees are not loaded. `talent_layout` is the only function signup needs
when a tree becomes useful: return a revision and the trees for one class.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("ironkeep.warcraft")

ORIGIN = "https://warcraftforever.com"
FRESH_FOR = timedelta(hours=24)
_SLUG = re.compile(r"[a-z0-9-]{1,40}")
_DATASET = re.compile(r"[A-Za-z0-9._-]{1,80}")
_reader = None


def cache_path():
    override = os.environ.get("IRONKEEP_WOW_CATALOG")
    if override:
        return Path(override)
    state = Path("/var/lib/ironkeep")
    if state.is_dir():
        return state / "warcraft_forever.json"
    return None


def talent_layout(class_slug):
    """A class talent layout, or None while trees stay unloaded.

    The saved catalog already keeps `talents_dataset`. A later reader can load
    that dataset and return {"revision": str, "trees": [{"id", "name"}]} for
    this class. Signup keeps its own specialization ids and roles either way.
    """
    return None


def class_records():
    path = cache_path()
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("classes")
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict) and item.get("id")]


def refresh_if_stale():
    path = cache_path()
    if path is not None and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        fetched = _fetched_at(payload or {})
        if fetched is not None and datetime.now(timezone.utc) - fetched < FRESH_FOR:
            return class_records()
    try:
        return refresh()["classes"]
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, KeyError):
        log.warning("Warcraft Forever class list unavailable", exc_info=True)
        return class_records()


def refresh():
    catalog = _get_json("/api/catalog/v1/manifest")
    channel_name = catalog["defaultChannel"]
    dataset = catalog["channels"][channel_name]["dataset"]
    if not _DATASET.fullmatch(str(dataset)):
        raise ValueError("dataset")
    classes = _get_json(f"/api/catalog/v1/{dataset}/enUS/classes")
    data = _get_json("/api/data/v1/manifest")
    talents = data["channels"][data["defaultChannel"]]["datasets"].get("talents") or ""
    if not _DATASET.fullmatch(str(talents)):
        talents = ""
    records = []
    for item in classes.get("data") or []:
        record = _class_record(item)
        if record is not None:
            records.append(record)
    if not records:
        raise ValueError("classes")
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dataset": classes.get("dataset") or dataset,
        "build": classes.get("build") or "",
        "channel": classes.get("channel") or channel_name,
        "locale": classes.get("locale") or "enUS",
        "talents_dataset": talents,
        "classes": records,
    }
    _write(snapshot)
    log.info("Warcraft Forever classes: %s from build %s", len(records), snapshot["build"])
    return snapshot


def _class_record(item):
    if not isinstance(item, dict):
        return None
    slug = str(item.get("slug") or "")
    name = " ".join(str(item.get("name") or "").split())
    if not _SLUG.fullmatch(slug) or not name or len(name) > 40:
        return None
    icon = str(item.get("iconUrl") or "")
    if not icon.startswith(f"{ORIGIN}/"):
        icon = ""
    client_id = item.get("id")
    if not isinstance(client_id, int):
        client_id = None
    return {"id": slug, "client_id": client_id, "name": name, "icon_url": icon}


def _fetched_at(payload):
    try:
        moment = datetime.fromisoformat(str(payload.get("fetched_at") or ""))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _write(snapshot):
    path = cache_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(snapshot), encoding="utf-8")
    temporary.replace(path)


def _get_json(path):
    if _reader is not None:
        return _reader(path)
    request = urllib.request.Request(ORIGIN + path, headers={"User-Agent": "Ironkeep"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)
