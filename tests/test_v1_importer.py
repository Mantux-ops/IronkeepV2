"""
Tests for scripts/import_ironkeep_v1_catalog.py — Phase 12.1b V1→V2 importer.

Coverage
--------
- V1 record parsing
- Slot normalisation (V1 → V2)
- Two-handed detection
- generate_enchants policy
- Tiers field for tier-specific items
- Duplicate item_type detection
- Invalid records (missing ID, missing name, invalid slot, out-of-range tier)
- Determinism (same input → same output, stable sort)
- Comparison: known correct V1 items present, known V2 placeholders absent
- Integration: generated seed loads into AlbionItemCatalog without errors
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Make the scripts package importable from the repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.import_ironkeep_v1_catalog import (
    _base_type,
    _is_two_handed,
    build_seed_entries,
    filter_and_group,
    load_v1_catalog,
)
from app.albion.item_catalog import reload_catalog, VALID_SLOTS, AlbionItemCatalog

# ---------------------------------------------------------------------------
# Path to the real V1 catalog (skip integration tests if not available)
# ---------------------------------------------------------------------------

_V1_PATH = Path("C:/Users/emiel/Documents/albion-cta-web/static/albion_items.json")
_V1_AVAILABLE = _V1_PATH.exists()

requires_v1 = pytest.mark.skipif(
    not _V1_AVAILABLE,
    reason="IronkeepV1 albion_items.json not available at expected path",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_v1_catalog(*items: dict) -> dict:
    """Build a minimal V1 catalog dict for testing."""
    return {"_version": 4, "items": list(items)}


def _v1_item(
    item_id: str,
    base_name: str,
    slot: str,
    tier: int,
    name: str | None = None,
) -> dict:
    return {
        "id": item_id,
        "name": name or f"T{tier} {base_name}",
        "base_name": base_name,
        "slot": slot,
        "tier": tier,
    }


def _run(v1_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run filter_and_group + build_seed_entries on a list of V1 items."""
    grouped = filter_and_group(v1_items)
    return build_seed_entries(grouped)


# ---------------------------------------------------------------------------
# Unit tests — _base_type
# ---------------------------------------------------------------------------

class TestBaseType:
    def test_strips_t7_prefix(self):
        assert _base_type("T7_2H_CLAYMORE") == "2H_CLAYMORE"

    def test_strips_t8_prefix(self):
        assert _base_type("T8_MAIN_SWORD") == "MAIN_SWORD"

    def test_complex_id(self):
        assert _base_type("T7_ARMOR_PLATE_SET1") == "ARMOR_PLATE_SET1"

    def test_cape_item(self):
        assert _base_type("T7_CAPEITEM_AVALON") == "CAPEITEM_AVALON"

    def test_mount(self):
        assert _base_type("T8_MOUNT_HORSE") == "MOUNT_HORSE"


# ---------------------------------------------------------------------------
# Unit tests — _is_two_handed
# ---------------------------------------------------------------------------

class TestIsTwoHanded:
    def test_2h_prefix_true(self):
        assert _is_two_handed("2H_CLAYMORE") is True

    def test_2h_firestaff_true(self):
        assert _is_two_handed("2H_FIRESTAFF") is True

    def test_main_prefix_false(self):
        assert _is_two_handed("MAIN_SWORD") is False

    def test_off_prefix_false(self):
        assert _is_two_handed("OFF_SHIELD") is False

    def test_armor_false(self):
        assert _is_two_handed("ARMOR_PLATE_SET1") is False


# ---------------------------------------------------------------------------
# Unit tests — filter_and_group
# ---------------------------------------------------------------------------

class TestFilterAndGroup:
    def test_filters_to_t7_t8_only(self):
        items = [
            _v1_item("T6_2H_CLAYMORE", "Claymore", "weapon", 6),
            _v1_item("T7_2H_CLAYMORE", "Claymore", "weapon", 7),
            _v1_item("T8_2H_CLAYMORE", "Claymore", "weapon", 8),
            _v1_item("T9_2H_CLAYMORE", "Claymore", "weapon", 9),
        ]
        grouped = filter_and_group(items)
        assert "2H_CLAYMORE" in grouped
        assert set(grouped["2H_CLAYMORE"].keys()) == {7, 8}

    def test_excludes_material_slot(self):
        items = [
            _v1_item("T7_RUNE", "Rune", "material", 7),
            _v1_item("T7_2H_CLAYMORE", "Claymore", "weapon", 7),
        ]
        grouped = filter_and_group(items)
        assert "RUNE" not in grouped
        assert "2H_CLAYMORE" in grouped

    def test_excludes_resource_slot(self):
        items = [_v1_item("T7_WOOD", "Wood", "resource", 7)]
        grouped = filter_and_group(items)
        assert not grouped

    def test_deduplicates_same_base_type(self):
        items = [
            _v1_item("T7_MAIN_SWORD", "Broadsword", "weapon", 7),
            _v1_item("T8_MAIN_SWORD", "Broadsword", "weapon", 8),
        ]
        grouped = filter_and_group(items)
        assert len(grouped) == 1
        assert "MAIN_SWORD" in grouped
        assert set(grouped["MAIN_SWORD"].keys()) == {7, 8}

    def test_tracks_tier_specific_items(self):
        items = [_v1_item("T7_MEAL_PIE", "Pork Pie", "food", 7)]
        grouped = filter_and_group(items)
        assert "MEAL_PIE" in grouped
        assert list(grouped["MEAL_PIE"].keys()) == [7]


# ---------------------------------------------------------------------------
# Unit tests — build_seed_entries
# ---------------------------------------------------------------------------

class TestBuildSeedEntries:
    def test_weapon_maps_to_main_hand(self):
        items = [_v1_item("T8_2H_CLAYMORE", "Claymore", "weapon", 8)]
        entries, skipped = _run(items)
        assert len(entries) == 1
        assert entries[0]["item_type"] == "2H_CLAYMORE"
        assert "display_name" in entries[0]
        assert not skipped

    def test_offhand_maps_to_off_hand_in_v2(self):
        # The item_type (2H_CLAYMORE, MAIN_SWORD, OFF_SHIELD etc.) goes directly
        # into the seed; V2's _classify_slot determines the slot at load time.
        items = [_v1_item("T8_OFF_SHIELD", "Shield", "offhand", 8)]
        entries, skipped = _run(items)
        assert entries[0]["item_type"] == "OFF_SHIELD"

    def test_display_name_uses_base_name(self):
        items = [_v1_item("T7_2H_CLAYMORE", "Claymore", "weapon", 7, name="Grandmaster's Claymore")]
        entries, skipped = _run(items)
        assert entries[0]["display_name"] == "Claymore"

    def test_cape_has_generate_enchants_false(self):
        items = [_v1_item("T7_CAPE", "Cape", "cape", 7)]
        entries, skipped = _run(items)
        assert entries[0].get("generate_enchants") is False

    def test_mount_has_generate_enchants_false(self):
        items = [_v1_item("T7_MOUNT_HORSE", "Riding Horse", "mount", 7)]
        entries, skipped = _run(items)
        assert entries[0].get("generate_enchants") is False

    def test_food_has_generate_enchants_false(self):
        items = [_v1_item("T7_MEAL_PIE", "Pork Pie", "food", 7)]
        entries, skipped = _run(items)
        assert entries[0].get("generate_enchants") is False

    def test_potion_has_generate_enchants_false(self):
        items = [_v1_item("T7_POTION_REVIVE", "Gigantify Potion", "potion", 7)]
        entries, skipped = _run(items)
        assert entries[0].get("generate_enchants") is False

    def test_weapon_no_generate_enchants_field(self):
        # Weapons default to true — field should not be written
        items = [_v1_item("T8_2H_CLAYMORE", "Claymore", "weapon", 8)]
        entries, skipped = _run(items)
        assert "generate_enchants" not in entries[0]

    def test_armor_no_generate_enchants_field(self):
        items = [_v1_item("T8_ARMOR_PLATE_SET1", "Guardian Armor", "chest", 8)]
        entries, skipped = _run(items)
        assert "generate_enchants" not in entries[0]

    def test_both_tiers_no_tiers_field(self):
        items = [
            _v1_item("T7_2H_CLAYMORE", "Claymore", "weapon", 7),
            _v1_item("T8_2H_CLAYMORE", "Claymore", "weapon", 8),
        ]
        entries, skipped = _run(items)
        assert "tiers" not in entries[0]

    def test_only_t7_sets_tiers_field(self):
        items = [_v1_item("T7_MEAL_PIE", "Pork Pie", "food", 7)]
        entries, skipped = _run(items)
        assert entries[0]["tiers"] == [7]

    def test_only_t8_sets_tiers_field(self):
        items = [_v1_item("T8_MEAL_STEW", "Beef Stew", "food", 8)]
        entries, skipped = _run(items)
        assert entries[0]["tiers"] == [8]

    def test_missing_display_name_skipped(self):
        items = [{"id": "T7_2H_CLAYMORE", "base_name": "", "slot": "weapon", "tier": 7}]
        entries, skipped = _run(items)
        assert entries == []
        assert len(skipped) == 1

    def test_unknown_v1_slot_skipped(self):
        items = [{"id": "T7_THING", "base_name": "Mystery", "slot": "consumable", "tier": 7}]
        # consumable is not in EQUIPMENT_SLOTS_V1 → filtered out before build_seed_entries
        grouped = filter_and_group(items)
        assert not grouped  # filtered at the group stage

    def test_output_sorted_by_item_type(self):
        items = [
            _v1_item("T7_2H_SPEAR", "Pike", "weapon", 7),
            _v1_item("T7_2H_CLAYMORE", "Claymore", "weapon", 7),
            _v1_item("T7_2H_AXE", "Greataxe", "weapon", 7),
        ]
        entries, _ = _run(items)
        types = [e["item_type"] for e in entries]
        assert types == sorted(types)

    def test_determinism(self):
        items = [
            _v1_item("T7_2H_CLAYMORE", "Claymore", "weapon", 7),
            _v1_item("T8_2H_CLAYMORE", "Claymore", "weapon", 8),
            _v1_item("T7_OFF_SHIELD", "Shield", "offhand", 7),
        ]
        a, _ = _run(items)
        b, _ = _run(items)
        assert a == b


# ---------------------------------------------------------------------------
# Integration tests — new V2 seed loaded into AlbionItemCatalog
# ---------------------------------------------------------------------------

class TestNewSeedIntegration:
    """Verify the importer-generated seed loads correctly into the V2 catalog."""

    @pytest.fixture(autouse=True)
    def fresh_catalog(self):
        reload_catalog()

    def test_catalog_loads_without_errors(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        assert len(cat) > 0

    def test_no_skipped_entries(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        assert cat.skipped_entries == [], (
            f"Generated seed has invalid entries: {cat.skipped_entries[:3]}"
        )

    def test_all_10_slots_represented(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        present = {e["slot"] for e in cat.get_all()}
        assert present == VALID_SLOTS

    def test_correct_staff_ids_from_v1(self):
        """V1-derived IDs use FIRESTAFF not STAFFFIRE."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        # Correct V1 IDs
        assert cat.get_item("T8_2H_FIRESTAFF") is not None, "2H_FIRESTAFF missing"
        assert cat.get_item("T8_2H_FROSTSTAFF") is not None, "2H_FROSTSTAFF missing"
        assert cat.get_item("T8_2H_HOLYSTAFF") is not None, "2H_HOLYSTAFF missing"
        assert cat.get_item("T8_2H_CURSEDSTAFF") is not None, "2H_CURSEDSTAFF missing"
        assert cat.get_item("T8_2H_ARCANESTAFF") is not None, "2H_ARCANESTAFF missing"
        assert cat.get_item("T8_2H_NATURESTAFF") is not None, "2H_NATURESTAFF missing"
        # Incorrect old V2 placeholder IDs must NOT exist
        assert cat.get_item("T8_2H_STAFFFIRE") is None, "Fake 2H_STAFFFIRE should not exist"
        assert cat.get_item("T8_2H_STAFFICE") is None, "Fake 2H_STAFFICE should not exist"

    def test_correct_dagger_pair_id(self):
        """V1 uses 2H_DAGGERPAIR (no underscore between DAGGER and PAIR)."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        assert cat.get_item("T8_2H_DAGGERPAIR") is not None, "2H_DAGGERPAIR missing"
        assert cat.get_item("T8_2H_DAGGER_PAIR") is None, "Fake 2H_DAGGER_PAIR should not exist"

    def test_correct_potion_ids_from_v1(self):
        """V1 T7 potions: POTION_REVIVE (Gigantify), POTION_STONESKIN (Resistance)."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        assert cat.get_item("T7_POTION_REVIVE") is not None, "T7_POTION_REVIVE missing"
        assert cat.get_item("T7_POTION_STONESKIN") is not None, "T7_POTION_STONESKIN missing"
        # V2 placeholder potion IDs must NOT exist
        assert cat.get_item("T7_POTION_HEAL") is None, "Fake T7_POTION_HEAL should not exist"
        assert cat.get_item("T8_POTION_ENERGY") is None, "Fake T8_POTION_ENERGY should not exist"

    def test_meal_food_has_enchant_variants(self):
        """MEAL_ food items have @1/@2/@3 variants (confirmed in ao-bin-dumps)."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        # T7_MEAL_OMELETTE@1 must be present (confirmed in snapshot)
        assert cat.get_item("T7_MEAL_OMELETTE@1") is not None, (
            "T7_MEAL_OMELETTE@1 should exist (meal items have enchanted variants)"
        )

    def test_potion_has_enchant_variants(self):
        """Potion items have @1/@2/@3 variants (confirmed in ao-bin-dumps)."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        # T7_POTION_REVIVE@2 must be present
        assert cat.get_item("T7_POTION_REVIVE@2") is not None, (
            "T7_POTION_REVIVE@2 should exist (potions have enchanted variants)"
        )

    def test_mount_no_enchant_variants(self):
        """Mount items must not have @1/@2/@3 variants (confirmed in ao-bin-dumps)."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        mounts = cat.get_by_slot("mount")
        assert all(e["enchantment"] == 0 for e in mounts)

    def test_weapon_has_enchant_variants(self):
        """Weapons must have @0 through @3 variants."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        for enchant in range(4):
            suffix = "" if enchant == 0 else f"@{enchant}"
            item_id = f"T8_2H_CLAYMORE{suffix}"
            assert cat.get_item(item_id) is not None, f"{item_id} missing"

    def test_tiers_field_restricts_generation(self):
        """T7-only food should not appear at T8, and vice versa."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        # MEAL_PIE is T7-only in V1 data
        t7_pie = cat.get_item("T7_MEAL_PIE")
        t8_pie = cat.get_item("T8_MEAL_PIE")
        assert t7_pie is not None, "T7_MEAL_PIE should be in catalog"
        assert t8_pie is None, "T8_MEAL_PIE should not be in catalog (T7-only)"
        # MEAL_STEW is T8-only in V1 data
        t7_stew = cat.get_item("T7_MEAL_STEW")
        t8_stew = cat.get_item("T8_MEAL_STEW")
        assert t8_stew is not None, "T8_MEAL_STEW should be in catalog"
        assert t7_stew is None, "T7_MEAL_STEW should not be in catalog (T8-only)"

    def test_capeitem_prefix_classified_as_cape(self):
        """V1 uses CAPEITEM_ prefix; V2 slot classification must handle it."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        capes = cat.get_by_slot("cape")
        cape_ids = [e["item_id"] for e in capes]
        assert any("CAPEITEM" in id_ for id_ in cape_ids), (
            "No CAPEITEM_ entries found in cape slot"
        )

    def test_two_handed_weapons_flagged_correctly(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        claymore = cat.get_item("T8_2H_CLAYMORE")
        assert claymore is not None
        assert claymore["is_two_handed"] is True
        sword = cat.get_item("T8_MAIN_SWORD")
        assert sword is not None
        assert sword["is_two_handed"] is False

    def test_catalog_larger_than_old_v2(self):
        """New V1-derived catalog should be substantially larger than the old 143-item seed."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        assert len(cat) > 1000, f"Expected >1000 entries, got {len(cat)}"


# ---------------------------------------------------------------------------
# V1-sourced integration tests (require V1 file on disk)
# ---------------------------------------------------------------------------

@requires_v1
class TestV1SourceIntegration:
    """
    Tests that read directly from the V1 albion_items.json.

    LEGACY: The V1 importer (import_ironkeep_v1_catalog.py) is a migration tool
    that was used during Phase 12.1b. The primary workflow is now
    scripts/import_albion_catalog.py (reading ao-bin-dumps snapshot directly).

    These tests verify that V1 data can still be parsed correctly for
    cross-validation purposes, but they do NOT affect the production catalog.
    """

    def test_v1_catalog_loads(self):
        items = load_v1_catalog(_V1_PATH)
        assert len(items) > 2000

    def test_filter_produces_308_base_types(self):
        items = load_v1_catalog(_V1_PATH)
        grouped = filter_and_group(items)
        assert len(grouped) == 308

    def test_all_v1_equipment_slots_present_in_grouped(self):
        items = load_v1_catalog(_V1_PATH)
        grouped = filter_and_group(items)
        entries, _ = build_seed_entries(grouped)
        from app.albion.item_catalog import _classify_slot
        slots_present = set()
        for e in entries:
            try:
                slots_present.add(_classify_slot(e["item_type"]))
            except ValueError:
                pass
        assert "main_hand" in slots_present
        assert "off_hand" in slots_present
        assert "cape" in slots_present
        assert "food" in slots_present
        assert "potion" in slots_present

    def test_known_bad_v2_ids_absent_from_v1_grouped(self):
        """These V2 placeholder IDs do not appear in V1's authoritative data."""
        items = load_v1_catalog(_V1_PATH)
        grouped = filter_and_group(items)
        bad_v2_types = [
            "2H_STAFFFIRE", "2H_STAFFICE", "2H_STAFFARCANE",
            "2H_STAFFNATURE", "2H_STAFFCURSE", "2H_STAFFHOLY",
            "2H_DAGGER_PAIR",
            "POTION_HEAL", "POTION_ENERGY",
            "MEAL_SOUP", "MEAL_SALAD",
            "CAPE_UNDEAD", "CAPE_KEEPER", "CAPE_MORGANA",
            "MOUNT_DIREWOLF", "MOUNT_SWIFTCLAW", "MOUNT_MOOSE",
        ]
        found = [t for t in bad_v2_types if t in grouped]
        assert found == [], f"These bad V2 IDs appeared in V1 data: {found}"

    def test_importer_output_is_deterministic(self):
        items = load_v1_catalog(_V1_PATH)
        grouped1 = filter_and_group(items)
        entries1, _ = build_seed_entries(grouped1)
        grouped2 = filter_and_group(items)
        entries2, _ = build_seed_entries(grouped2)
        assert entries1 == entries2

    def test_no_import_errors(self):
        items = load_v1_catalog(_V1_PATH)
        grouped = filter_and_group(items)
        entries, skipped = build_seed_entries(grouped)
        assert skipped == [], f"Unexpected import errors: {skipped}"

    def test_v1_importer_requires_explicit_path(self):
        """The legacy V1 importer must not have a default V1 path."""
        from scripts.import_ironkeep_v1_catalog import DEFAULT_V1_PATH
        assert DEFAULT_V1_PATH is None, (
            "DEFAULT_V1_PATH must be None — V1 path must be supplied explicitly "
            "to prevent silent dependency on a local V1 installation."
        )
