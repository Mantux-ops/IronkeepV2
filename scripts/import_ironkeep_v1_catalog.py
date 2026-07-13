"""
IronkeepV1 → IronkeepV2 item catalog importer  [LEGACY / MIGRATION TOOL].

DEPRECATED: The primary importer is now scripts/import_albion_catalog.py, which
reads directly from the version-controlled ao-bin-dumps snapshot in
data/albion/source/items_snapshot.txt and has no dependency on IronkeepV1.

This script is kept for reference and cross-validation only. It requires an
explicit path to IronkeepV1's static/albion_items.json and must not be used as
the default catalog generation workflow.

Usage
-----
  python scripts/import_ironkeep_v1_catalog.py V1_ITEMS_JSON [--output V2_SEED_JSON]

  Example:
  python scripts/import_ironkeep_v1_catalog.py \
    "C:/Users/emiel/Documents/albion-cta-web/static/albion_items.json" \
    --output /tmp/v1_derived_catalog.json

Note: Pass --output to a temp path; do NOT overwrite app/albion/data/items_t7_t8.json
with this legacy importer. Use scripts/import_albion_catalog.py instead.

V2 output : (no default — must be specified via --output)
  Formerly pointed to: C:/Users/emiel/Documents/albion-cta-web/static/albion_items.json

What this script does
---------------------
1. Reads the V1 item catalog (generated from ao-bin-dumps, authoritative Albion IDs).
2. Filters to T7 and T8 equipment items only.
3. Maps V1 slot names (weapon, offhand, chest, ...) to V2 VALID_SLOTS.
4. Detects two-handed status from the 2H_ ID prefix (V1 doesn't have this field).
5. Deduplicates by base item_type (e.g., T7_2H_CLAYMORE and T8_2H_CLAYMORE → one entry).
6. Sets generate_enchants: false for capes, mounts, food, and potions.
7. Adds "tiers": [n] for items that exist only at T7 or only at T8 in V1 data.
8. Writes the V2 seed JSON sorted deterministically.

The output is IronkeepV2-owned: no runtime dependency on V1 is introduced.

Not imported from V1
--------------------
- Bags: V1 classifies bags as "material"; the catalog JSON has no bag items.
  Bags are added to the end of the output as a manually-curated section.
- T1–T6 items (excluded by tier filter).
- Material / resource / consumable items.
- Enchanted variants: V1 stores base IDs only; V2 generates @1–@3 at load time.

Slot normalisation (V1 → V2)
-----------------------------
  weapon   →  main_hand   (both MAIN_* 1H and 2H_* weapons)
  offhand  →  off_hand
  head     →  head
  chest    →  chest
  shoes    →  shoes
  cape     →  cape
  food     →  food
  potion   →  potion
  mount    →  mount

generate_enchants policy
-------------------------
  main_hand, off_hand, head, chest, shoes  →  true  (default, not written)
  cape, mount, food, potion, bag           →  false  (written explicitly)

Rationale for food/potion: Albion uses separate item IDs per quality tier (e.g.
T7_MEAL_OMELETTE vs T8_MEAL_STEW), NOT the @1/@2/@3 enchant system that weapons
and armour use.  Generating @1/@2/@3 food variants would produce IDs that do not
exist in Albion Online.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Make the project root importable when running this script directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# No default V1 path — V1 source must be supplied explicitly.
# This ensures the script cannot silently depend on a local V1 installation.
DEFAULT_V1_PATH = None
DEFAULT_V2_OUTPUT = Path("/tmp/v1_derived_catalog.json")

# V1 slot names → V2 VALID_SLOTS
V1_TO_V2_SLOT: dict[str, str] = {
    "weapon":  "main_hand",
    "offhand": "off_hand",
    "head":    "head",
    "chest":   "chest",
    "shoes":   "shoes",
    "cape":    "cape",
    "food":    "food",
    "potion":  "potion",
    "mount":   "mount",
}

# Equipment slots we care about (V1 names)
EQUIPMENT_SLOTS_V1 = frozenset(V1_TO_V2_SLOT.keys())

# Slots where Albion does NOT use the @1/@2/@3 enchantment system
NO_ENCHANT_V2_SLOTS = frozenset({"cape", "mount", "food", "potion", "bag"})

ALLOWED_TIERS = frozenset({7, 8})

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _base_type(item_id: str) -> str:
    """Strip the tier prefix: 'T7_2H_CLAYMORE' → '2H_CLAYMORE'."""
    _, _, rest = item_id.partition("_")
    return rest


def _is_two_handed(base_type: str) -> bool:
    return base_type.startswith("2H_")


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


def load_v1_catalog(v1_path: Path) -> list[dict]:
    data = json.loads(v1_path.read_text(encoding="utf-8"))
    return data["items"]


def filter_and_group(
    v1_items: list[dict],
    *,
    allowed_tiers: frozenset[int] = ALLOWED_TIERS,
) -> dict[str, dict]:
    """
    Return {base_type: {tier: v1_item}} for all T7/T8 equipment items.

    Skips non-equipment slots (material, resource, consumable).
    """
    by_base: dict[str, dict] = defaultdict(dict)
    for item in v1_items:
        if item.get("slot") not in EQUIPMENT_SLOTS_V1:
            continue
        tier = item.get("tier")
        if tier not in allowed_tiers:
            continue
        bt = _base_type(item["id"])
        if not bt:
            continue
        by_base[bt][tier] = item
    return dict(by_base)


def build_seed_entries(
    grouped: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """
    Convert grouped V1 items into V2 seed entries.

    Returns (entries, skipped):
      entries  — valid seed objects ready for JSON output
      skipped  — records that could not be imported (with reason)
    """
    entries: list[dict] = []
    skipped: list[dict] = []

    for base_type, tier_items in sorted(grouped.items()):
        # Use T7 record as reference; fall back to T8
        ref = tier_items.get(7) or tier_items.get(8)
        v1_slot = ref["slot"]
        v2_slot = V1_TO_V2_SLOT.get(v1_slot)
        if v2_slot is None:
            skipped.append({
                "base_type": base_type,
                "reason": f"Unknown V1 slot '{v1_slot}'",
            })
            continue

        display_name = ref.get("base_name") or ref.get("name") or ""
        display_name = " ".join(display_name.strip().split())
        if not display_name:
            skipped.append({
                "base_type": base_type,
                "reason": "Missing display name",
            })
            continue

        generate_enchants = v2_slot not in NO_ENCHANT_V2_SLOTS
        available_tiers = sorted(tier_items.keys())
        needs_tiers_field = available_tiers != sorted(ALLOWED_TIERS)

        entry: dict = {"item_type": base_type, "display_name": display_name}
        if not generate_enchants:
            entry["generate_enchants"] = False
        if needs_tiers_field:
            entry["tiers"] = available_tiers

        entries.append(entry)

    return entries, skipped


# Manually curated bag entries (not in V1 catalog; kept from existing V2 seed)
_BAG_SECTION: list[dict] = [
    {
        "_comment": (
            "Bags — slot: bag, generate_enchants: false. "
            "Not present in V1 catalog; IDs retained from existing V2 seed. "
            "Verify against ao-bin-dumps before production use."
        ),
        "_section": "bag",
    },
    {"item_type": "BAG",         "display_name": "Bag",               "generate_enchants": False},
    {"item_type": "BAG_INSIGHT", "display_name": "Expert's Bag",      "generate_enchants": False},
]


def _section_comment(label: str, v2_slot: str, extra: str = "") -> dict:
    parts = [f"slot: {v2_slot}"]
    if extra:
        parts.append(extra)
    return {"_comment": f"{label} — {', '.join(parts)}", "_section": label.lower().replace(" ", "_")}


def assemble_output(entries: list[dict]) -> list[dict]:
    """
    Group entries by slot into a structured, human-readable JSON list with
    section comments.
    """
    from collections import defaultdict

    by_slot: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        from app.albion.item_catalog import _classify_slot
        try:
            slot = _classify_slot(e["item_type"])
        except ValueError:
            slot = "unknown"
        by_slot[slot].append(e)

    output: list[dict] = [
        {"_comment": (
            "IronkeepV2 item catalog seed — auto-generated from IronkeepV1 "
            "(ao-bin-dumps via static/albion_items.json). "
            "Run scripts/import_ironkeep_v1_catalog.py to regenerate."
        )},
    ]

    # Weapons: 2H first, then 1H
    weapons = by_slot.get("main_hand", [])
    two_h = sorted([e for e in weapons if e["item_type"].startswith("2H_")], key=lambda e: e["item_type"])
    one_h = sorted([e for e in weapons if e["item_type"].startswith("MAIN_")], key=lambda e: e["item_type"])

    if two_h:
        output.append(_section_comment("Two-handed weapons", "main_hand", "is_two_handed: true"))
        output.extend(two_h)
    if one_h:
        output.append(_section_comment("One-handed weapons", "main_hand", "is_two_handed: false"))
        output.extend(one_h)

    slot_order = ["off_hand", "head", "chest", "shoes", "cape", "mount", "food", "potion"]
    slot_labels = {
        "off_hand": "Off-hand items",
        "head": "Head armour",
        "chest": "Chest armour",
        "shoes": "Shoes",
        "cape": "Capes",
        "mount": "Mounts",
        "food": "Food",
        "potion": "Potions",
    }
    slot_extra = {
        "cape": "generate_enchants: false",
        "mount": "generate_enchants: false",
        "food": "generate_enchants: false, tier-specific items",
        "potion": "generate_enchants: false, tier-specific items",
    }

    for slot in slot_order:
        items = sorted(by_slot.get(slot, []), key=lambda e: e["item_type"])
        if not items:
            continue
        label = slot_labels.get(slot, slot)
        extra = slot_extra.get(slot, "")
        output.append(_section_comment(label, slot, extra))
        output.extend(items)

    output.extend(_BAG_SECTION)

    return output


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(
    grouped: dict[str, dict],
    entries: list[dict],
    skipped: list[dict],
    v1_path: Path,
    output_path: Path,
) -> None:
    from collections import Counter
    from app.albion.item_catalog import _classify_slot

    print(f"\nV1 source   : {v1_path}")
    print(f"V2 output   : {output_path}")
    print(f"\nV1 T7/T8 base types   : {len(grouped)}")
    print(f"V2 seed entries        : {len(entries)}")
    if skipped:
        print(f"Skipped (import errors): {len(skipped)}")
        for s in skipped:
            print(f"  SKIP: {s}")

    slot_counts: Counter = Counter()
    for e in entries:
        try:
            slot_counts[_classify_slot(e["item_type"])] += 1
        except ValueError:
            slot_counts["unknown"] += 1

    print("\nBase items per V2 slot:")
    for slot, count in sorted(slot_counts.items()):
        print(f"  {slot:12s}: {count}")

    tier_specific = [e for e in entries if "tiers" in e]
    both_tiers = [e for e in entries if "tiers" not in e or e.get("tiers") == [7, 8]]
    no_enchant = [e for e in entries if not e.get("generate_enchants", True)]

    print(f"\nItems with tiers field (tier-specific)  : {len(tier_specific)}")
    print(f"Items valid at both T7 and T8           : {len(both_tiers)}")
    print(f"Items with generate_enchants: false     : {len(no_enchant)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "v1_path",
        type=Path,
        help=(
            "Path to IronkeepV1 static/albion_items.json (required). "
            "Example: /path/to/albion-cta-web/static/albion_items.json"
        ),
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_V2_OUTPUT,
        help="Output path (default: /tmp/v1_derived_catalog.json). "
             "Do NOT point this at app/albion/data/items_t7_t8.json; "
             "use scripts/import_albion_catalog.py for the primary workflow.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report without writing output file",
    )
    args = parser.parse_args(argv)

    if not args.v1_path.exists():
        print(f"ERROR: V1 source not found: {args.v1_path}", file=sys.stderr)
        return 1

    print(f"Reading V1 catalog from: {args.v1_path}")
    v1_items = load_v1_catalog(args.v1_path)

    grouped = filter_and_group(v1_items)
    entries, skipped = build_seed_entries(grouped)
    output = assemble_output(entries)

    print_report(grouped, entries, skipped, args.v1_path, args.output)

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
