"""
IronkeepV2 Albion item catalog importer — reads the V2-internal ao-bin-dumps snapshot.

Primary workflow (no dependency on IronkeepV1):

  data/albion/source/items_snapshot.txt   (version-controlled ao-bin-dumps snapshot)
          ↓
  parse_snapshot()                         parses item IDs and display names
          ↓
  classify_and_group()                     classifies slots, filters T7/T8,
                                           deduplicates by base_type,
                                           detects generate_enchants from raw data
          ↓
  build_seed_entries()                     produces V2 seed records
          ↓
  app/albion/data/items_t7_t8.json        V2-owned, no runtime network access

Usage
-----
  # Regenerate catalog from snapshot
  python scripts/import_albion_catalog.py

  # Verify committed catalog matches what would be generated
  python scripts/import_albion_catalog.py --check

  # Use a different snapshot (e.g. from a fresh fetch)
  python scripts/import_albion_catalog.py --snapshot path/to/items.txt

  # Update snapshot first, then regenerate
  python scripts/fetch_albion_snapshot.py
  python scripts/import_albion_catalog.py

Catalog schema version
----------------------
  Version 2 — generate_enchants derived from raw snapshot; tiers field supported.

generate_enchants policy
------------------------
  Determined from the raw snapshot: if T{n}_ITEM@1 exists in the snapshot,
  generate_enchants is True (default, not written). Otherwise False.

  Confirmed by ao-bin-dumps data (2026-07-13):
    Mounts          → False  (no @enchant variants)
    All others      → True   (capes, food, potions, bags, equipment all have @1/@2/@3)

Slot classification
-------------------
  Derived from item ID prefix using V2's _classify_slot().
  Items not matching any V2 equipment slot are skipped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.albion.item_catalog import _classify_slot, VALID_SLOTS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DEFAULT_SNAPSHOT = _REPO_ROOT / "data" / "albion" / "source" / "items_snapshot.txt"
DEFAULT_OUTPUT = _REPO_ROOT / "app" / "albion" / "data" / "items_t7_t8.json"
METADATA_PATH = _REPO_ROOT / "data" / "albion" / "source" / "source_metadata.json"

ALLOWED_TIERS = frozenset({7, 8})

# Slots we include in the V2 catalog
V2_CATALOG_SLOTS = frozenset(VALID_SLOTS)

# Patterns that identify non-equippable items even if their prefix matches a slot.
# Applied to the base_type (tier-stripped item ID).
_EXCLUDE_PATTERNS = re.compile(
    r"_TOOL_"          # Gathering/crafting tools (e.g. 2H_TOOL_AXE)
    r"|_BP$"           # Cape crafting blueprints (e.g. CAPEITEM_AVALON_BP)
    r"|_SKIN_"         # Cosmetic skins (e.g. MOUNT_ARMORED_HORSE_SKIN_01)
    r"|_NONTRADABLE"   # Non-tradable reward items
)

# Tier-qualified name prefixes to strip → produces base display_name
_TIER_PREFIXES = [
    "Elder's ",         # T8
    "Grandmaster's ",   # T7
    "Master's ",        # T6
    "Expert's ",        # T5
    "Adept's ",         # T4
    "Journeyman's ",    # T3
    "Novice's ",        # T2
]

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(r"^\s*\d+:\s+(\S+)\s+:\s+(.+)$")


def parse_snapshot(snapshot_path: Path) -> dict[str, str]:
    """
    Parse items.txt → {item_id: raw_display_name}.

    Includes all entries (base IDs and @N enchant variants), so callers can
    detect which items have enchanted forms.
    """
    items: dict[str, str] = {}
    for line in snapshot_path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(line)
        if m:
            item_id = m.group(1).strip()
            name = m.group(2).strip()
            items[item_id] = name
    return items


def _strip_tier_prefix(name: str) -> str:
    for prefix in _TIER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


# ---------------------------------------------------------------------------
# Classification and grouping
# ---------------------------------------------------------------------------


def classify_and_group(
    raw_items: dict[str, str],
    *,
    allowed_tiers: frozenset[int] = ALLOWED_TIERS,
) -> dict[str, dict]:
    """
    Filter raw items to V2 equipment slots at T7/T8, grouped by base_type.

    Returns {base_type: {tier: {"display_name": str, "has_enchants": bool}}}.

    Only base IDs (without @N) are keyed; @N variants are used to detect
    whether generate_enchants should be True.
    """
    # Build a set of all item IDs for enchant-detection lookup
    all_ids = frozenset(raw_items.keys())

    grouped: dict[str, dict] = defaultdict(dict)

    for item_id, raw_name in raw_items.items():
        # Skip enchanted variants at this stage
        if "@" in item_id:
            continue

        # Must be T7 or T8
        m = re.match(r"^T(\d+)_(.+)$", item_id)
        if not m:
            continue
        tier = int(m.group(1))
        base_type = m.group(2)
        if tier not in allowed_tiers:
            continue

        # Skip known non-equippable items (tools, blueprints, skins, …)
        if _EXCLUDE_PATTERNS.search(base_type):
            continue

        # Classify slot from the base_type
        try:
            slot = _classify_slot(base_type)
        except ValueError:
            continue  # not a V2 equipment item
        if slot not in V2_CATALOG_SLOTS:
            continue

        display_name = _strip_tier_prefix(raw_name)
        # Detect generate_enchants: True iff @1 variant exists
        has_enchants = f"T{tier}_{base_type}@1" in all_ids

        grouped[base_type][tier] = {
            "display_name": display_name,
            "has_enchants": has_enchants,
        }

    return dict(grouped)


# ---------------------------------------------------------------------------
# Seed entry construction
# ---------------------------------------------------------------------------


def build_seed_entries(
    grouped: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """
    Convert grouped items into V2 seed entries.

    Returns (entries, skipped):
      entries  — valid seed records ready for JSON output
      skipped  — records that could not be imported (with reason)
    """
    entries: list[dict] = []
    skipped: list[dict] = []

    for base_type, tier_data in sorted(grouped.items()):
        # Use T7 record as reference; fall back to T8
        ref = tier_data.get(7) or tier_data.get(8)

        display_name = ref["display_name"].strip()
        if not display_name:
            skipped.append({"base_type": base_type, "reason": "empty display_name"})
            continue

        generate_enchants = ref["has_enchants"]
        available_tiers = sorted(tier_data.keys())
        needs_tiers_field = available_tiers != sorted(ALLOWED_TIERS)

        entry: dict = {"item_type": base_type, "display_name": display_name}
        if not generate_enchants:
            entry["generate_enchants"] = False
        if needs_tiers_field:
            entry["tiers"] = available_tiers

        entries.append(entry)

    return entries, skipped


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def _section_comment(label: str, v2_slot: str, extra: str = "") -> dict:
    parts = [f"slot: {v2_slot}"]
    if extra:
        parts.append(extra)
    return {
        "_comment": f"{label} — {', '.join(parts)}",
        "_section": label.lower().replace(" ", "_"),
    }


def assemble_output(entries: list[dict]) -> list[dict]:
    """
    Group entries by slot with section comments for human readability.
    """
    by_slot: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        try:
            slot = _classify_slot(entry["item_type"])
        except ValueError:
            slot = "unknown"
        by_slot[slot].append(entry)

    output: list[dict] = [
        {
            "_comment": (
                "IronkeepV2 Albion item catalog seed — auto-generated from "
                "ao-bin-dumps (data/albion/source/items_snapshot.txt). "
                "Schema version 2. "
                "Regenerate: python scripts/import_albion_catalog.py. "
                "Verify: python scripts/import_albion_catalog.py --check."
            )
        },
    ]

    # Weapons: 2H then 1H
    weapons = by_slot.get("main_hand", [])
    two_h = sorted([e for e in weapons if e["item_type"].startswith("2H_")], key=lambda e: e["item_type"])
    one_h = sorted([e for e in weapons if e["item_type"].startswith("MAIN_")], key=lambda e: e["item_type"])

    if two_h:
        output.append(_section_comment("Two-handed weapons", "main_hand", "is_two_handed: true"))
        output.extend(two_h)
    if one_h:
        output.append(_section_comment("One-handed weapons", "main_hand", "is_two_handed: false"))
        output.extend(one_h)

    slot_order = ["off_hand", "head", "chest", "shoes", "cape", "bag", "mount", "food", "potion"]
    slot_labels = {
        "off_hand": "Off-hand items",
        "head": "Head armour",
        "chest": "Chest armour",
        "shoes": "Shoes",
        "cape": "Capes",
        "bag": "Bags",
        "mount": "Mounts",
        "food": "Food",
        "potion": "Potions",
    }
    slot_extra = {
        "mount": "generate_enchants: false",
    }

    for slot in slot_order:
        items = sorted(by_slot.get(slot, []), key=lambda e: e["item_type"])
        if not items:
            continue
        label = slot_labels.get(slot, slot)
        extra = slot_extra.get(slot, "")
        output.append(_section_comment(label, slot, extra))
        output.extend(items)

    return output


# ---------------------------------------------------------------------------
# Data entries comparison (for --check)
# ---------------------------------------------------------------------------


def _extract_data_entries(seed: list[dict]) -> list[dict]:
    """Filter out _comment/_section markers, return only item data entries."""
    return [e for e in seed if "_comment" not in e and "_section" not in e]


def _entry_key(e: dict) -> str:
    return e.get("item_type", "")


def check_catalog_up_to_date(
    snapshot_path: Path,
    catalog_path: Path,
) -> tuple[bool, str]:
    """
    Regenerate catalog in memory and compare with committed catalog_path.

    Returns (is_ok, message).
    """
    raw = parse_snapshot(snapshot_path)
    grouped = classify_and_group(raw)
    fresh_entries, skipped = build_seed_entries(grouped)

    if skipped:
        return False, f"Import produced {len(skipped)} skipped entries: {skipped[:3]}"

    committed_raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    committed_entries = _extract_data_entries(committed_raw)

    fresh_by_type = {e["item_type"]: e for e in fresh_entries}
    committed_by_type = {e["item_type"]: e for e in committed_entries}

    only_fresh = set(fresh_by_type) - set(committed_by_type)
    only_committed = set(committed_by_type) - set(fresh_by_type)
    conflicts = [
        (t, fresh_by_type[t], committed_by_type[t])
        for t in fresh_by_type.keys() & committed_by_type.keys()
        if fresh_by_type[t] != committed_by_type[t]
    ]

    if not only_fresh and not only_committed and not conflicts:
        return True, (
            f"Catalog is up to date — {len(fresh_entries)} entries match."
        )

    lines = ["Catalog is OUT OF DATE — differences found:"]
    if only_fresh:
        lines.append(f"  {len(only_fresh)} entries in snapshot but not in committed catalog:")
        for t in sorted(only_fresh)[:5]:
            lines.append(f"    + {t}")
        if len(only_fresh) > 5:
            lines.append(f"    … and {len(only_fresh) - 5} more")
    if only_committed:
        lines.append(f"  {len(only_committed)} entries in committed catalog but not in snapshot:")
        for t in sorted(only_committed)[:5]:
            lines.append(f"    - {t}")
        if len(only_committed) > 5:
            lines.append(f"    … and {len(only_committed) - 5} more")
    if conflicts:
        lines.append(f"  {len(conflicts)} entries with conflicting data:")
        for t, fresh, committed in conflicts[:3]:
            lines.append(f"    ~ {t}: fresh={fresh} committed={committed}")
        if len(conflicts) > 3:
            lines.append(f"    … and {len(conflicts) - 3} more")
    lines.append("")
    lines.append("Fix: python scripts/import_albion_catalog.py")
    return False, "\n".join(lines)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(
    grouped: dict[str, dict],
    entries: list[dict],
    skipped: list[dict],
) -> None:
    from collections import Counter

    print(f"\nBase types from snapshot : {len(grouped)}")
    print(f"V2 seed entries           : {len(entries)}")
    if skipped:
        print(f"Skipped (errors)          : {len(skipped)}")
        for s in skipped:
            print(f"  SKIP: {s}")

    slot_counts: Counter = Counter()
    enchant_true = 0
    enchant_false = 0
    for e in entries:
        try:
            slot_counts[_classify_slot(e["item_type"])] += 1
        except ValueError:
            slot_counts["unknown"] += 1
        if e.get("generate_enchants", True):
            enchant_true += 1
        else:
            enchant_false += 1

    print("\nBase items per V2 slot:")
    for slot, count in sorted(slot_counts.items()):
        print(f"  {slot:12s}: {count}")

    tier_specific = [e for e in entries if "tiers" in e]
    print(f"\nWith tiers field (tier-specific) : {len(tier_specific)}")
    print(f"generate_enchants true           : {enchant_true}")
    print(f"generate_enchants false (mounts) : {enchant_false}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help="Path to ao-bin-dumps items.txt snapshot",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path for V2 seed JSON",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify that the committed catalog matches the snapshot. "
            "Exits 1 if out of date."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report without writing files.",
    )
    args = parser.parse_args(argv)

    if not args.snapshot.exists():
        print(
            f"ERROR: Snapshot not found: {args.snapshot}\n"
            "Run: python scripts/fetch_albion_snapshot.py",
            file=sys.stderr,
        )
        return 1

    if args.check:
        if not args.output.exists():
            print(f"ERROR: Catalog not found: {args.output}", file=sys.stderr)
            return 1
        ok, msg = check_catalog_up_to_date(args.snapshot, args.output)
        print(msg)
        return 0 if ok else 1

    print(f"Reading snapshot: {args.snapshot}")
    raw = parse_snapshot(args.snapshot)
    print(f"  Parsed {len(raw):,} raw entries (including @N variants)")

    grouped = classify_and_group(raw)
    entries, skipped = build_seed_entries(grouped)

    if skipped:
        print(f"\nERROR: {len(skipped)} import errors:", file=sys.stderr)
        for s in skipped:
            print(f"  {s}", file=sys.stderr)
        return 1

    output = assemble_output(entries)
    print_report(grouped, entries, skipped)

    if args.dry_run:
        print("\n[dry-run] No file written.")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(output)} JSON objects to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
