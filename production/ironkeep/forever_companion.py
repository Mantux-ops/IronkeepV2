"""Forever Companion dungeon list and drop tables.

Quests, rares and reputations stay out.
Group size, banners and Discord mentions stay in Ironkeep.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("ironkeep.companion")

ORIGIN = "https://forevercompanion.io"
FRESH_FOR = timedelta(hours=6)
_SLUG = re.compile(r"[a-z0-9-]{1,60}")
_reader = None


def cache_path():
    override = os.environ.get("IRONKEEP_COMPANION_CACHE")
    if override:
        return Path(override)
    state = Path("/var/lib/ironkeep")
    if state.is_dir():
        return state / "forever_companion.json"
    return None


def _read():
    path = cache_path()
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def dungeons():
    rows = _read().get("dungeons")
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict) and item.get("id")]


def loot():
    """Drop tables keyed by the Companion dungeon id. Empty until a refresh stores them."""
    rows = _read().get("loot")
    if not isinstance(rows, dict):
        return {}
    return rows


def refresh_if_stale():
    path = cache_path()
    if path is not None and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        fetched = _fetched_at(payload or {})
        if fetched is not None and _loot_ready(payload) and datetime.now(timezone.utc) - fetched < FRESH_FOR:
            return dungeons()
    try:
        return refresh()["dungeons"]
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, KeyError):
        log.warning("Forever Companion dungeon list unavailable", exc_info=True)
        return dungeons()


def refresh():
    payload = _get_json("/api/v1/dungeons")
    rows = []
    for item in payload.get("data") or []:
        record = _dungeon(item)
        if record is not None:
            rows.append(record)
    if not rows:
        raise ValueError("dungeons")
    previous = _read().get("loot")
    stored = dict(previous) if isinstance(previous, dict) else {}
    for record in rows:
        if not record["is_new"]:
            continue
        try:
            stored[record["id"]] = _dungeon_loot(record["id"])
        except (OSError, urllib.error.URLError, TimeoutError, ValueError):
            log.warning("Forever Companion loot unavailable for %s", record["id"])
    _attach_item_facts(stored)
    meta = payload.get("meta") or {}
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": meta.get("updatedAt") or "",
        "attribution": meta.get("attribution") or "Data from Forever Companion (https://forevercompanion.io).",
        "dungeons": rows,
        "loot": stored,
    }
    _write(snapshot)
    counted = sum(len(items) for items in stored.values() if isinstance(items, list))
    typed = sum(
        1
        for items in stored.values()
        if isinstance(items, list)
        for item in items
        if item.get("armor") or item.get("weapon")
    )
    log.info("Forever Companion dungeons: %s, drops: %s, typed: %s", len(rows), counted, typed)
    return snapshot


def _loot_ready(payload):
    loot = (payload or {}).get("loot")
    if not isinstance(loot, dict):
        return False
    for items in loot.values():
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or "armor" not in item or "weapon" not in item or "icon" not in item:
                return False
    return True


def _attach_item_facts(stored):
    missing = 0
    for items in stored.values():
        if not isinstance(items, list):
            continue
        for item in items:
            key = str(item.get("key") or "")
            if not key.isdigit():
                _remember_details(item, _empty_fact())
                continue
            try:
                fact = _item_fact(int(key))
            except (OSError, urllib.error.URLError, TimeoutError, ValueError):
                missing += 1
                _remember_details(item, _empty_fact(), keep=True)
                continue
            _remember_details(item, fact)
    if missing:
        log.warning("Forever Companion item details missing: %s", missing)


def _empty_fact():
    return {
        "armor": "",
        "weapon": "",
        "slot": "",
        "icon": "",
        "quality": "",
        "item_level": None,
        "required_level": None,
        "stats": [],
        "classic_only": False,
    }


def _remember_details(item, fact, keep=False):
    item["armor"] = fact["armor"] or (item.get("armor") if keep else "") or ""
    item["weapon"] = fact["weapon"] or (item.get("weapon") if keep else "") or ""
    if fact["slot"]:
        item["slot"] = fact["slot"]
    item["icon"] = fact["icon"] or (item.get("icon") if keep else "") or ""
    if fact["quality"]:
        item["quality"] = fact["quality"]
    item["item_level"] = fact["item_level"] if fact["item_level"] is not None else (item.get("item_level") if keep else None)
    item["required_level"] = fact["required_level"] if fact["required_level"] is not None else (item.get("required_level") if keep else None)
    if fact["stats"] or not keep:
        item["stats"] = fact["stats"]
    elif not isinstance(item.get("stats"), list):
        item["stats"] = []
    item["classic_only"] = bool(fact["classic_only"] or (item.get("classic_only") if keep else False))


def _item_fact(item_id):
    try:
        payload = _get_json(f"/api/v1/items/{item_id}")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return _empty_fact()
        raise
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return _empty_fact()
    fact = _empty_fact()
    fact["armor"] = data.get("armor") if data.get("armor") in ("cloth", "leather", "mail", "plate") else ""
    fact["weapon"] = " ".join(str(data.get("weaponType") or "").split())[:40]
    fact["slot"] = " ".join(str(data.get("slot") or "").split())[:40]
    icon = str(data.get("icon") or "")
    if re.fullmatch(r"[a-z0-9_]{1,64}", icon):
        fact["icon"] = icon
    if data.get("quality") in ("poor", "common", "uncommon", "rare", "epic", "legendary"):
        fact["quality"] = data["quality"]
    if isinstance(data.get("itemLevel"), int) and 0 < data["itemLevel"] < 1000:
        fact["item_level"] = data["itemLevel"]
    if isinstance(data.get("requiredLevel"), int) and 0 < data["requiredLevel"] < 1000:
        fact["required_level"] = data["requiredLevel"]
    fact["stats"] = _stat_lines(data.get("tooltip"))
    fact["classic_only"] = bool(data.get("classicOnly"))
    return fact


def _stat_lines(tooltip):
    lines = []
    if not isinstance(tooltip, list):
        return lines
    for line in tooltip:
        if not isinstance(line, dict):
            continue
        left = " ".join(str(line.get("left") or "").split())
        if not left or len(left) > 80 or left in lines:
            continue
        if left.startswith(("+", "Equip:", "Use:", "Chance on hit:")) or line.get("kind") == "green":
            lines.append(left)
        if len(lines) == 6:
            break
    return lines


def _dungeon_loot(slug):
    try:
        payload = _get_json(f"/api/v1/dungeons/{slug}")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        raise
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = []
    seen = set()
    for item in (data or {}).get("loot") or []:
        record = _loot_item(item)
        if record is None or record["key"] in seen:
            continue
        seen.add(record["key"])
        rows.append(record)
    return rows


def _loot_item(item):
    if not isinstance(item, dict):
        return None
    name = " ".join(str(item.get("name") or "").split())
    if not name or len(name) > 80:
        return None
    item_id = item.get("itemId")
    if isinstance(item_id, int) and item_id > 0:
        key = str(item_id)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
        if not slug:
            return None
        key = f"n:{slug}"
    slot = " ".join(str(item.get("slot") or "").split())[:40]
    source = " ".join(str(item.get("source") or "").split())[:80]
    quality = item.get("quality") if item.get("quality") in ("poor", "common", "uncommon", "rare", "epic", "legendary") else ""
    return {"key": key, "name": name, "slot": slot, "source": source, "quality": quality}


def _dungeon(item):
    if not isinstance(item, dict):
        return None
    slug = str(item.get("id") or "")
    name = " ".join(str(item.get("name") or "").split())
    if not _SLUG.fullmatch(slug) or not name or len(name) > 80:
        return None
    status = item.get("status") if item.get("status") in ("launch", "announced") else ""
    return {
        "id": slug,
        "name": name,
        "status": status,
        "beta_locked": bool(item.get("betaLocked")),
        "is_new": bool(item.get("isNew")),
        "min_level": item.get("minLevel") if isinstance(item.get("minLevel"), int) else None,
        "max_level": item.get("maxLevel") if isinstance(item.get("maxLevel"), int) else None,
    }


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
