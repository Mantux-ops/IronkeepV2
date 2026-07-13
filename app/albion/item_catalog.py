"""
Albion Online item catalog — T7/T8 equipment for build management.

Responsibilities
----------------
- Parse Albion item IDs into structured metadata (tier, enchantment, slot,
  two-handed status).
- Enforce T7/T8-only filtering server-side; items outside the allowed range
  are never returned to callers.
- Provide icon URLs via the Albion Online render service.
- Support slot-based filtering, name search, and exact ID lookup.
- Detect two-handed weapons so the application layer can enforce the
  off-hand exclusion rule.

Item ID format
--------------
  T{tier}_{CATEGORY}_{subtype}[@{enchant}]

Examples
  T8_2H_CLAYMORE@3          → Tier 8.3, main_hand, two-handed
  T8_MAIN_SWORD@1            → Tier 8.1, main_hand, one-handed
  T7_OFF_SHIELD              → Tier 7.0, off_hand
  T8_HEAD_PLATE_SET1@2       → Tier 8.2, head
  T8_MOUNT_DIREWOLF          → Tier 8.0, mount
  T7_MEAL_STEW               → Tier 7.0, food

Tier variants
  Base (no @suffix) = enchantment 0  (T8.0)
  @1 = enchantment 1 (T8.1)
  @2 = enchantment 2 (T8.2)
  @3 = enchantment 3 (T8.3)
  @4 = enchantment 4 (T8.4) — excluded by default; enable via INCLUDE_ENCHANTMENT_4

Icon source
  https://render.albiononline.com/v1/item/{item_id}.png?size={size}
  Size 217 is the highest standard resolution on the render service.

Thread safety
  get_catalog() and reload_catalog() are not thread-safe during a reload.
  In production init_schema() runs in a single thread before any request
  handler starts, so the singleton is effectively read-only at request time.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Final

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Tiers exposed by the build GUI.  Items outside this set are rejected.
ALLOWED_TIERS: Final[frozenset[int]] = frozenset({7, 8})

#: Standard enchantment levels (0 = unenchanted base item).
ALLOWED_ENCHANTMENTS: Final[frozenset[int]] = frozenset({0, 1, 2, 3})

#: Set to True to also load @4 enchantment variants.
#: T8.4 data in community dumps is unreliable for some item types.
INCLUDE_ENCHANTMENT_4: bool = False

# ---------------------------------------------------------------------------
# Slot classification
# ---------------------------------------------------------------------------

#: All valid equipment slot identifiers used by the build system.
VALID_SLOTS: Final[frozenset[str]] = frozenset({
    "main_hand",
    "off_hand",
    "head",
    "chest",
    "shoes",
    "cape",
    "bag",
    "mount",
    "food",
    "potion",
})

# Maps from item ID category prefix to slot name.
# Order is significant: more specific prefixes must come before shorter ones.
_SLOT_MAP: list[tuple[str, str]] = [
    ("2H_",      "main_hand"),
    ("MAIN_",    "main_hand"),
    ("OFF_",     "off_hand"),
    ("HEAD_",    "head"),
    ("ARMOR_",   "chest"),
    ("SHOES_",   "shoes"),
    ("CAPE",     "cape"),
    ("BAG",      "bag"),
    ("MOUNT_",   "mount"),
    ("MEAL_",    "food"),
    ("FISH_",    "food"),
    ("POTION_",  "potion"),
]

# ---------------------------------------------------------------------------
# Icon render service
# ---------------------------------------------------------------------------

_RENDER_BASE: Final[str] = "https://render.albiononline.com/v1/item"

#: Default icon resolution in pixels.  217 is the highest reliably available
#: size on the render.albiononline.com service.
DEFAULT_ICON_SIZE: Final[int] = 217

# ---------------------------------------------------------------------------
# Item ID parsing
# ---------------------------------------------------------------------------

# Matches: T{tier}_{rest}  with optional @{enchant} suffix.
# Tier must be a positive integer; rest is the category + subtype portion.
_ITEM_ID_RE = re.compile(r"^T(\d+)_([A-Z0-9_]+?)(?:@(\d+))?$")


def parse_item_id(item_id: str) -> dict:
    """
    Parse a raw Albion item ID into structured metadata.

    Returns a dict:
      tier         int   base tier number (e.g. 7 or 8)
      enchantment  int   enchantment level; 0 when no @suffix present
      slot         str   equipment slot (one of VALID_SLOTS)
      is_two_handed bool True when the item occupies both hand slots
      category     str   raw category token (e.g. "2H_CLAYMORE", "HEAD_PLATE_SET1")

    Raises ValueError for items with unrecognisable or unsupported IDs.
    The item need not be in the allowed tier range — callers that require
    range enforcement should call is_allowed_tier() separately.
    """
    normalised = item_id.strip().upper()
    m = _ITEM_ID_RE.match(normalised)
    if not m:
        raise ValueError(
            f"Cannot parse Albion item ID '{item_id}': "
            "expected format T{{tier}}_{{CATEGORY}}[@{{enchant}}]"
        )

    tier = int(m.group(1))
    category = m.group(2)          # e.g. "2H_CLAYMORE", "HEAD_PLATE_SET1"
    enchantment = int(m.group(3)) if m.group(3) is not None else 0

    slot = _classify_slot(category)
    two_handed = category.startswith("2H_")

    return {
        "tier": tier,
        "enchantment": enchantment,
        "slot": slot,
        "is_two_handed": two_handed,
        "category": category,
    }


def _classify_slot(category: str) -> str:
    """Return the slot name for a given item category token."""
    for prefix, slot in _SLOT_MAP:
        if category.startswith(prefix):
            return slot
    raise ValueError(
        f"Cannot classify slot for Albion item category '{category}'. "
        "Add a mapping to _SLOT_MAP if this is a new item type."
    )


# ---------------------------------------------------------------------------
# Icon URL
# ---------------------------------------------------------------------------

def get_icon_url(item_id: str, size: int = DEFAULT_ICON_SIZE) -> str:
    """
    Return the render.albiononline.com URL for an item's icon.

    *size* controls the pixel dimensions of the returned PNG.  217 is the
    highest standard resolution.  64 is useful for thumbnails.

    The URL is deterministic from the item ID — no database lookup required.
    """
    if size < 1 or size > 1024:
        raise ValueError(f"Icon size {size} is out of range (1–1024).")
    return f"{_RENDER_BASE}/{item_id.strip().upper()}.png?size={size}"


# ---------------------------------------------------------------------------
# Tier / enchantment validation
# ---------------------------------------------------------------------------

def is_allowed_tier(
    tier: int,
    enchantment: int,
    *,
    include_t8_4: bool = INCLUDE_ENCHANTMENT_4,
) -> bool:
    """
    Return True when *tier* and *enchantment* are within the allowed range.

    Allowed tiers:       7, 8
    Allowed enchantments: 0, 1, 2, 3  (plus 4 when include_t8_4 is True)

    This is intentionally strict: a tier-6 item with a valid enchantment
    returns False.  Only items that should appear in the build GUI pass.
    """
    if tier not in ALLOWED_TIERS:
        return False
    max_enchant = 4 if include_t8_4 else 3
    return 0 <= enchantment <= max_enchant


# ---------------------------------------------------------------------------
# Catalog entry construction
# ---------------------------------------------------------------------------

def make_catalog_entry(
    item_id: str,
    display_name: str,
    *,
    include_t8_4: bool = INCLUDE_ENCHANTMENT_4,
) -> dict:
    """
    Build a fully-qualified catalog entry from a raw item ID and display name.

    The returned dict is the canonical representation used throughout the
    application:

      item_id       str   canonical (uppercased, trimmed) Albion item ID
      base_item_id  str   item_id without enchantment suffix (groups variants)
      display_name  str   human-readable item name
      tier          int   base tier (7 or 8)
      enchantment   int   0 = base/unenchanted, 1–4 = enchantment level
      slot          str   one of VALID_SLOTS
      is_two_handed bool
      icon_url      str   URL to render.albiononline.com PNG at default size

    Raises ValueError when the item ID cannot be parsed, the tier is outside
    the allowed range, or the enchantment exceeds the configured maximum.
    """
    parsed = parse_item_id(item_id)
    if not is_allowed_tier(parsed["tier"], parsed["enchantment"], include_t8_4=include_t8_4):
        raise ValueError(
            f"Item '{item_id}' has tier {parsed['tier']}.{parsed['enchantment']} "
            f"which is outside the allowed build range (T7.0–T8.3)."
        )
    canonical_id = item_id.strip().upper()
    base_id = canonical_id.split("@")[0]
    return {
        "item_id": canonical_id,
        "base_item_id": base_id,
        "display_name": display_name.strip(),
        "tier": parsed["tier"],
        "enchantment": parsed["enchantment"],
        "slot": parsed["slot"],
        "is_two_handed": parsed["is_two_handed"],
        "icon_url": get_icon_url(item_id),
    }


# ---------------------------------------------------------------------------
# Stable sort key for catalog entries
# ---------------------------------------------------------------------------

def _sort_key(entry: dict) -> tuple:
    return (entry["slot"], entry["tier"], entry["enchantment"], entry["display_name"])


# ---------------------------------------------------------------------------
# AlbionItemCatalog
# ---------------------------------------------------------------------------

class AlbionItemCatalog:
    """
    In-memory item catalog restricted to T7/T8 tiers.

    All public methods return only items within the allowed tier range.
    Tier enforcement happens at load time — the internal list never contains
    out-of-range items.

    The catalog is effectively read-only after construction.
    """

    def __init__(
        self,
        entries: list[dict],
        skipped_entries: list[dict] | None = None,
    ) -> None:
        self._entries: list[dict] = sorted(entries, key=_sort_key)
        self._by_id: dict[str, dict] = {e["item_id"]: e for e in self._entries}
        self._by_slot: dict[str, list[dict]] = {}
        for entry in self._entries:
            self._by_slot.setdefault(entry["slot"], []).append(entry)
        #: Seed entries that were skipped during load (with reason).
        self.skipped_entries: list[dict] = skipped_entries or []

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all(self) -> list[dict]:
        """Return every catalog entry in deterministic sort order."""
        return list(self._entries)

    def list_items(self) -> list[dict]:
        """Alias for get_all(); returns all items in deterministic sort order."""
        return self.get_all()

    def get_item(self, item_id: str) -> dict | None:
        """Look up a single item by canonical ID.  Returns None on miss."""
        return self._by_id.get(item_id.strip().upper())

    def require(self, item_id: str) -> dict:
        """
        Look up a single item by canonical ID.

        Raises NotFoundError when the item is not in the catalog, so callers
        that treat a missing item as a domain error can distinguish it from a
        programming bug without catching KeyError.
        """
        from app.errors import NotFoundError
        item = self.get_item(item_id)
        if item is None:
            raise NotFoundError(
                f"Item '{item_id.strip().upper()}' is not in the T7/T8 item catalog."
            )
        return item

    def get_by_slot(self, slot: str) -> list[dict]:
        """
        Return all items for *slot*.

        Raises ValueError for unknown slot names so callers get a clear
        domain error instead of a silent empty list.
        """
        if slot not in VALID_SLOTS:
            raise ValueError(
                f"Unknown equipment slot '{slot}'. "
                f"Must be one of: {sorted(VALID_SLOTS)}"
            )
        return list(self._by_slot.get(slot, []))

    def search_by_name(
        self,
        query: str,
        *,
        slot: str | None = None,
    ) -> list[dict]:
        """
        Case-insensitive substring search on display_name.

        Internal whitespace in *query* is normalised (multiple spaces → one).
        An empty *query* returns all items (optionally filtered by *slot*).
        *slot* applies the same restriction as get_by_slot().
        """
        pool = self.get_by_slot(slot) if slot else self._entries
        q = " ".join(query.strip().split()).lower()
        if not q:
            return list(pool)
        return [e for e in pool if q in e["display_name"].lower()]

    def filter(  # noqa: A003  (shadows builtin, acceptable as a method name)
        self,
        *,
        slot: str | None = None,
        tier: int | None = None,
        enchantment: int | None = None,
        is_two_handed: bool | None = None,
        q: str = "",
    ) -> list[dict]:
        """
        Combined filter.  All specified parameters are ANDed together.

        Parameters
        ----------
        slot          Must be one of VALID_SLOTS; raises ValueError otherwise.
        tier          Must be 7 or 8; raises ValueError otherwise.
        enchantment   Must be 0–3; raises ValueError otherwise.
        is_two_handed When True, return only two-handed main_hand items.
                      When False, return only one-handed main_hand items.
                      None means no two-handed filter is applied.
        q             Case-insensitive name search (whitespace normalised).

        Returns a deterministically sorted list.
        """
        if slot is not None and slot not in VALID_SLOTS:
            raise ValueError(
                f"Unknown equipment slot '{slot}'. "
                f"Must be one of: {sorted(VALID_SLOTS)}"
            )
        if tier is not None and tier not in ALLOWED_TIERS:
            raise ValueError(
                f"Invalid tier {tier}. Allowed tiers: {sorted(ALLOWED_TIERS)}"
            )
        if enchantment is not None and not (0 <= enchantment <= 3):
            raise ValueError(
                f"Invalid enchantment {enchantment}. Must be 0–3."
            )

        pool: list[dict] = self.get_by_slot(slot) if slot else list(self._entries)

        if tier is not None:
            pool = [e for e in pool if e["tier"] == tier]
        if enchantment is not None:
            pool = [e for e in pool if e["enchantment"] == enchantment]
        if is_two_handed is not None:
            pool = [e for e in pool if e["is_two_handed"] == is_two_handed]

        norm_q = " ".join(q.strip().split()).lower()
        if norm_q:
            pool = [e for e in pool if norm_q in e["display_name"].lower()]

        return sorted(pool, key=_sort_key)

    def filter_by_tier(
        self,
        tier: int,
        enchantment: int | None = None,
    ) -> list[dict]:
        """
        Return all items for a specific *tier*, optionally at one *enchantment* level.

        Results are sorted by slot, then enchantment for stable output.
        """
        results = [e for e in self._entries if e["tier"] == tier]
        if enchantment is not None:
            results = [e for e in results if e["enchantment"] == enchantment]
        return sorted(results, key=_sort_key)

    def get_two_handed_items(self) -> list[dict]:
        """Return all main_hand items that are two-handed."""
        return [e for e in self._by_slot.get("main_hand", []) if e["is_two_handed"]]

    def get_one_handed_items(self) -> list[dict]:
        """Return all main_hand items that are NOT two-handed."""
        return [e for e in self._by_slot.get("main_hand", []) if not e["is_two_handed"]]

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:  # pragma: no cover
        slots = {s: len(v) for s, v in self._by_slot.items()}
        return f"AlbionItemCatalog({len(self)} entries, slots={slots})"


# ---------------------------------------------------------------------------
# Seed file loading
# ---------------------------------------------------------------------------

_DEFAULT_SEED_PATH: Path = Path(__file__).parent / "data" / "items_t7_t8.json"


def _load_seed(
    path: Path,
    *,
    include_t8_4: bool = INCLUDE_ENCHANTMENT_4,
) -> tuple[list[dict], list[dict]]:
    """
    Load and expand the item seed JSON file into a flat list of catalog entries.

    Returns
    -------
    (entries, skipped)
      entries  — fully-qualified catalog dicts, one per tier×enchantment variant
      skipped  — records that could not be loaded, each with keys:
                 item_type, variant_id, reason

    Seed format
    -----------
    The file is a JSON array.  Each element is either:

    1. A regular item object:
       {
         "item_type":       "2H_CLAYMORE",        -- ID without tier prefix
         "display_name":    "Claymore",
         "generate_enchants": true                -- optional, defaults to true
       }

    2. A comment/section marker (ignored):
       {"_comment": "...", "_section": "..."}

    For each regular item, entries are generated for both allowed tiers (7, 8)
    and for each enchantment level (0–3, plus 4 if include_t8_4).

    Items with "generate_enchants": false only produce one variant per tier
    (enchantment = 0), suitable for capes, bags, and mounts that have no
    enchanted variants in Albion Online.

    Duplicate item_ids raise ValueError immediately — this is a programming
    error in the seed, not a data quality issue.

    Entries that raise ValueError for unclassifiable slots are collected in the
    returned *skipped* list rather than crashing the application at startup.
    """
    raw: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict] = []
    skipped: list[dict] = []
    seen_ids: set[str] = set()
    max_enchant = 4 if include_t8_4 else 3

    for obj in raw:
        if "_comment" in obj or "_section" in obj:
            continue

        item_type = (obj.get("item_type") or "").strip().upper()
        display_name = (obj.get("display_name") or "").strip()
        if not item_type or not display_name:
            skipped.append({
                "item_type": item_type or "<missing>",
                "variant_id": "<unknown>",
                "reason": "Missing item_type or display_name",
            })
            continue

        generate_enchants = bool(obj.get("generate_enchants", True))
        enchant_range = range(max_enchant + 1) if generate_enchants else range(1)

        # Optional "tiers" field restricts which tiers are generated.
        # Default: all ALLOWED_TIERS.  Useful for items that only exist at one tier.
        seed_tiers_raw = obj.get("tiers")
        if seed_tiers_raw is not None:
            invalid = [t for t in seed_tiers_raw if t not in ALLOWED_TIERS]
            for t in invalid:
                skipped.append({
                    "item_type": item_type,
                    "variant_id": f"T{t}_{item_type}",
                    "reason": (
                        f"Tier {t} in 'tiers' field is outside the allowed range "
                        f"{sorted(ALLOWED_TIERS)}"
                    ),
                })
            active_tiers = sorted(t for t in seed_tiers_raw if t in ALLOWED_TIERS)
        else:
            active_tiers = sorted(ALLOWED_TIERS)

        for tier in active_tiers:
            for enchant in enchant_range:
                base_id = f"T{tier}_{item_type}"
                variant_id = base_id if enchant == 0 else f"{base_id}@{enchant}"
                try:
                    entry = make_catalog_entry(
                        variant_id,
                        display_name,
                        include_t8_4=include_t8_4,
                    )
                except ValueError as exc:
                    skipped.append({
                        "item_type": item_type,
                        "variant_id": variant_id,
                        "reason": str(exc),
                    })
                    continue

                if entry["item_id"] in seen_ids:
                    raise ValueError(
                        f"Duplicate item_id '{entry['item_id']}' in seed file '{path}'. "
                        "Each item_type must appear only once in the seed."
                    )
                seen_ids.add(entry["item_id"])
                entries.append(entry)

    return entries, skipped


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_catalog_instance: AlbionItemCatalog | None = None


def get_catalog(*, include_t8_4: bool = INCLUDE_ENCHANTMENT_4) -> AlbionItemCatalog:
    """
    Return the shared item catalog singleton.

    The catalog is loaded from the bundled seed file on the first call and
    cached for the lifetime of the process.  Call reload_catalog() to
    force a fresh load (e.g. in tests).
    """
    global _catalog_instance
    if _catalog_instance is None:
        entries, skipped = _load_seed(_DEFAULT_SEED_PATH, include_t8_4=include_t8_4)
        if skipped:
            _log.warning(
                "Item catalog: %d seed entries were skipped. "
                "Run tests to see details via catalog.skipped_entries.",
                len(skipped),
            )
        _catalog_instance = AlbionItemCatalog(entries, skipped_entries=skipped)
    return _catalog_instance


def reload_catalog(
    *,
    seed_path: Path | None = None,
    include_t8_4: bool = INCLUDE_ENCHANTMENT_4,
) -> AlbionItemCatalog:
    """
    Force a catalog reload from *seed_path* (defaults to the bundled seed).

    Use this in tests to get a clean catalog instance without shared state.
    """
    global _catalog_instance
    path = seed_path if seed_path is not None else _DEFAULT_SEED_PATH
    entries, skipped = _load_seed(path, include_t8_4=include_t8_4)
    _catalog_instance = AlbionItemCatalog(entries, skipped_entries=skipped)
    return _catalog_instance
