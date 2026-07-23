"""
Generate the static Albion spell/passive seed for IronkeepV2.

Downloads items.json and localization.json from ao-data/ao-bin-dumps, parses
per-item spell data (ported from IronkeepV1's albion_spells.py), filters it to
the base-types present in the T7/T8 item catalog, and writes a compact static
seed to app/albion/data/spells.json.

This script requires an internet connection and is meant to be run explicitly
by a developer when the spell data needs to be (re)generated. Production runtime
never downloads anything — it only reads the committed seed file.

Usage
-----
  python scripts/generate_spell_seed.py

After running:
  git add app/albion/data/spells.json
  git commit -m "chore: regenerate albion spell seed"
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ITEMS_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json"
_LOC_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/localization.json"
_GH_API_ITEMS = (
    "https://api.github.com/repos/ao-data/ao-bin-dumps/commits?path=items.json&per_page=1"
)
_SPELL_RENDER = "https://render.albiononline.com/v1/spell"
_OUTPUT_PATH = _REPO_ROOT / "app" / "albion" / "data" / "spells.json"
_SEED_SCHEMA = 1

# ---------------------------------------------------------------------------
# Slot label helpers (ported from V1)
# ---------------------------------------------------------------------------

_ACTIVE_LABEL: dict[str, str] = {
    "head": "Active (D)",
    "armor": "Active (R)",
    "shoes": "Active (F)",
}

_SLOT_ORDER = {
    "Q": 0, "W": 1, "E": 2,
    "Active (D)": 3, "Active (R)": 3, "Active (F)": 3,
    "Passive": 9, "Passive II": 10,
}


def _fetch_bytes(url: str, timeout: int = 180) -> bytes:
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Ironkeep/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_json(url: str, timeout: int = 15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Ironkeep/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Localization extraction (EN-US spell names + descriptions)
# ---------------------------------------------------------------------------

def _clean_desc(text: str) -> str:
    if not text:
        return ""
    out = text.replace("<br/>", "\n").replace("<br>", "\n").replace("<br />", "\n")
    out = out.replace("$$", "$")
    out = re.sub(r"\[/?[A-Za-z0-9_]+\]", "", out)
    out = re.sub(r"\${1,3}[A-Za-z0-9_.\[\]-]{2,400}\$", "", out)
    out = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\.[A-Za-z0-9_.\[\]-]{2,}\b", "", out)
    out = re.sub(r"<[^>]+>", "", out)
    out = out.replace("$", "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = out.strip()
    if not out:
        return ""
    return out[:500] + ("…" if len(out) > 500 else "")


def _build_localization_maps(loc_bytes: bytes) -> tuple[dict[str, str], dict[str, str]]:
    data = json.loads(loc_bytes.decode("utf-8"))
    tus = data.get("tmx", {}).get("body", {}).get("tu", [])
    names: dict[str, str] = {}
    descs: dict[str, str] = {}
    for tu in tus:
        tuid: str = tu.get("@tuid", "")
        if not tuid.startswith("@SPELLS_"):
            continue
        key = tuid.removeprefix("@SPELLS_")
        is_desc = key.endswith("_DESC")
        if is_desc:
            key = key[:-5]
        if "_EFFECT" in key or "_V2" in key:
            continue
        tuv = tu.get("tuv", {})
        if isinstance(tuv, list):
            seg = next((t.get("seg", "") for t in tuv if t.get("@xml:lang") == "EN-US"), "")
        elif isinstance(tuv, dict):
            seg = tuv.get("seg", "")
        else:
            seg = ""
        if seg:
            if is_desc:
                descs[key] = _clean_desc(seg)
            else:
                names[key] = seg
    print(f"  Extracted {len(names)} spell names, {len(descs)} descriptions")
    return names, descs


def _fallback_name(uniquename: str) -> str:
    name = uniquename.removeprefix("PASSIVE_")
    name = re.sub(r"\d+$", "", name)
    return name.replace("_", " ").title()


def _resolve_spell_name(uniquename: str, name_map: dict[str, str]) -> str:
    if uniquename in name_map:
        return name_map[uniquename]
    stripped = re.sub(r"\d+$", "", uniquename)
    if stripped != uniquename and stripped in name_map:
        return name_map[stripped]
    parts = uniquename.split("_")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "_".join(parts[:i])
        if candidate in name_map:
            return name_map[candidate]
        cs = re.sub(r"\d+$", "", candidate)
        if cs != candidate and cs in name_map:
            return name_map[cs]
    return _fallback_name(uniquename)


def _resolve_spell_desc(uniquename: str, desc_map: dict[str, str]) -> str:
    if uniquename in desc_map:
        return desc_map[uniquename]
    stripped = re.sub(r"\d+$", "", uniquename)
    if stripped != uniquename and stripped in desc_map:
        return desc_map[stripped]
    parts = uniquename.split("_")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "_".join(parts[:i])
        if candidate in desc_map:
            return desc_map[candidate]
        cs = re.sub(r"\d+$", "", candidate)
        if cs != candidate and cs in desc_map:
            return desc_map[cs]
    return ""


# ---------------------------------------------------------------------------
# items.json parsing (ported from V1)
# ---------------------------------------------------------------------------

def _get_base_type(identifier: str) -> str:
    base = identifier.split("@")[0]
    m = re.match(r"^T\d+_(.*)", base)
    return m.group(1) if m else base


def _item_category(uniquename: str) -> str | None:
    bt = _get_base_type(uniquename)
    if bt.startswith("MAIN_") or bt.startswith("2H_"):
        return "weapon"
    if bt.startswith("HEAD_"):
        return "head"
    if bt.startswith("ARMOR_"):
        return "armor"
    if bt.startswith("SHOES_"):
        return "shoes"
    if bt.startswith("OFF_"):
        return "offhand"
    if bt.startswith("CAPE") or bt.startswith("CAPEITEM"):
        return "cape"
    return None


def _resolve_spells(uniquename, all_items, _visited=None) -> list[dict]:
    if _visited is None:
        _visited = set()
    if uniquename in _visited or uniquename not in all_items:
        return []
    _visited.add(uniquename)
    item = all_items[uniquename]
    csl = item.get("craftingspelllist", {})
    ref = csl.get("@reference", "")
    base_spells: list[dict] = []
    if ref:
        base_spells = _resolve_spells(ref, all_items, _visited)
    remove_raw = csl.get("removespell", [])
    if isinstance(remove_raw, dict):
        remove_raw = [remove_raw]
    remove_names = {r.get("@uniquename") for r in remove_raw}
    if remove_names:
        base_spells = [s for s in base_spells if s.get("@uniquename") not in remove_names]
    add_raw = csl.get("craftspell", [])
    if isinstance(add_raw, dict):
        add_raw = [add_raw]
    base_spells.extend(add_raw)
    return base_spells


def _classify_spell(spell: dict, category: str) -> str:
    uname = spell.get("@uniquename", "")
    slots_val = spell.get("@slots")
    if category == "weapon":
        if slots_val == "1":
            return "Q"
        if slots_val == "2":
            return "W"
        if slots_val == "3":
            return "E"
        return "Passive"
    if uname.startswith("PASSIVE_"):
        if category == "armor" and slots_val == "2":
            return "Passive II"
        return "Passive"
    return _ACTIVE_LABEL.get(category, "Active")


def _field_suffix(label: str) -> str:
    return {
        "Q": "spell_q", "W": "spell_w", "E": "spell_e",
        "Passive": "passive", "Passive II": "passive_2",
    }.get(label, "spell")


def _api_item_type(category: str) -> str:
    if category == "weapon":
        return "weapon"
    if category in ("head", "armor", "shoes"):
        return "armor"
    return "accessory"


def _tier_of(uniquename: str) -> int:
    m = re.match(r"^T(\d+)_", uniquename)
    return int(m.group(1)) if m else 0


def _process_items_json(items_bytes, name_map, desc_map) -> dict[str, dict]:
    data = json.loads(items_bytes.decode("utf-8"))
    weapons = data.get("items", {}).get("weapon", [])
    equipment = data.get("items", {}).get("equipmentitem", [])
    transformations = data.get("items", {}).get("transformationweapon", [])
    if isinstance(transformations, dict):
        transformations = [transformations]

    all_items: dict[str, dict] = {}
    for group in (weapons, equipment, transformations):
        for it in group:
            all_items[it["@uniquename"]] = it

    candidates: dict[str, str] = {}
    for uniquename, item in all_items.items():
        active = int(item.get("@activespellslots", "0"))
        passive = int(item.get("@passivespellslots", "0"))
        if active + passive == 0:
            continue
        if not _item_category(uniquename):
            continue
        base_type = _get_base_type(uniquename)
        if base_type not in candidates or _tier_of(uniquename) > _tier_of(candidates[base_type]):
            candidates[base_type] = uniquename

    out: dict[str, dict] = {}
    for base_type, uniquename in candidates.items():
        category = _item_category(uniquename)
        if not category:
            continue
        raw_spells = _resolve_spells(uniquename, all_items)
        if not raw_spells:
            continue
        slot_groups: dict[str, list[dict]] = {}
        for sp in raw_spells:
            label = _classify_spell(sp, category)
            uname = sp.get("@uniquename", "")
            display = _resolve_spell_name(uname, name_map)
            desc = _resolve_spell_desc(uname, desc_map) or "Description unavailable from Albion data."
            icon_id = uname or display
            icon_url = (
                f"{_SPELL_RENDER}/{urllib.parse.quote(icon_id)}.png?size=40" if icon_id else ""
            )
            slot_groups.setdefault(label, []).append({
                "name": display,
                "description": desc,
                "icon_id": icon_id,
                "icon_url": icon_url,
            })
        slots_list = [
            {"label": label, "field_suffix": _field_suffix(label), "spells": spells}
            for label, spells in slot_groups.items()
        ]
        slots_list.sort(key=lambda s: _SLOT_ORDER.get(s["label"], 5))
        out[base_type] = {"item_category": _api_item_type(category), "slots": slots_list}

    print(f"  Processed {len(out)} base-types with spell data")
    return out


def _catalog_base_types() -> set[str]:
    """Base-types present in the T7/T8 item catalog for spell-bearing slots."""
    from app.albion.item_catalog import get_catalog
    spell_slots = {"main_hand", "off_hand", "head", "chest", "shoes", "cape"}
    bases: set[str] = set()
    for e in get_catalog()._entries:
        if e["slot"] in spell_slots:
            bases.add(_get_base_type(e["item_id"]))
    return bases


def main() -> int:
    print("Generating Albion spell seed …")
    items_bytes = _fetch_bytes(_ITEMS_URL)
    print(f"  items.json: {len(items_bytes):,} bytes")
    loc_bytes = _fetch_bytes(_LOC_URL, timeout=300)
    print(f"  localization.json: {len(loc_bytes):,} bytes")

    name_map, desc_map = _build_localization_maps(loc_bytes)
    del loc_bytes
    all_spells = _process_items_json(items_bytes, name_map, desc_map)
    del items_bytes

    catalog_bases = _catalog_base_types()
    filtered = {bt: v for bt, v in all_spells.items() if bt in catalog_bases}
    missing = sorted(catalog_bases - set(filtered))
    print(f"  Catalog base-types (spell slots): {len(catalog_bases)}")
    print(f"  Seed entries after filtering: {len(filtered)}")
    if missing:
        print(f"  NOTE: {len(missing)} catalog base-types have no spell data: "
              f"{', '.join(missing[:20])}{' …' if len(missing) > 20 else ''}")

    commit = _fetch_json(_GH_API_ITEMS)
    sha = commit[0].get("sha", "") if isinstance(commit, list) and commit else ""

    payload = {
        "schema": _SEED_SCHEMA,
        "source": "ao-bin-dumps",
        "source_commit": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spells": filtered,
    }
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  Written: {_OUTPUT_PATH} ({_OUTPUT_PATH.stat().st_size:,} bytes)")
    print()
    print("Next steps:")
    print("  git add app/albion/data/spells.json")
    print("  git commit -m 'chore: regenerate albion spell seed'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
