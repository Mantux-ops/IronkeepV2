"""
Tests for app/albion/item_catalog.py — Phase 12.1 Item Catalog Foundation.

Coverage
--------
- parse_item_id: two-handed, one-handed, off-hand, armor slots, enchantments
- get_icon_url: format and size parameter
- is_allowed_tier: boundary conditions and T8.4 flag
- make_catalog_entry: happy path and rejection of out-of-range items
- AlbionItemCatalog: get_all, get_item, get_by_slot, search_by_name,
                     filter_by_tier, get_two_handed_items, get_one_handed_items
- _load_seed: comment stripping, enchant generation, generate_enchants=false
- get_catalog / reload_catalog: singleton and forced reload
- Server-side tier enforcement: items below T7 never appear in catalog
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.albion.item_catalog import (
    ALLOWED_TIERS,
    DEFAULT_ICON_SIZE,
    VALID_SLOTS,
    AlbionItemCatalog,
    get_catalog,
    get_icon_url,
    is_allowed_tier,
    make_catalog_entry,
    parse_item_id,
    reload_catalog,
)
from app.errors import NotFoundError


# ---------------------------------------------------------------------------
# parse_item_id
# ---------------------------------------------------------------------------

class TestParseItemId:
    def test_two_handed_claymore(self):
        result = parse_item_id("T8_2H_CLAYMORE@3")
        assert result["tier"] == 8
        assert result["enchantment"] == 3
        assert result["slot"] == "main_hand"
        assert result["is_two_handed"] is True
        assert result["category"] == "2H_CLAYMORE"

    def test_one_handed_sword(self):
        result = parse_item_id("T8_MAIN_SWORD@1")
        assert result["tier"] == 8
        assert result["enchantment"] == 1
        assert result["slot"] == "main_hand"
        assert result["is_two_handed"] is False

    def test_offhand_shield(self):
        result = parse_item_id("T7_OFF_SHIELD")
        assert result["slot"] == "off_hand"
        assert result["is_two_handed"] is False
        assert result["enchantment"] == 0

    def test_head_armor(self):
        result = parse_item_id("T8_HEAD_PLATE_SET1@2")
        assert result["slot"] == "head"
        assert result["tier"] == 8
        assert result["enchantment"] == 2

    def test_chest_armor(self):
        result = parse_item_id("T8_ARMOR_LEATHER_SET2@1")
        assert result["slot"] == "chest"

    def test_shoes(self):
        result = parse_item_id("T7_SHOES_CLOTH_SET1")
        assert result["slot"] == "shoes"
        assert result["enchantment"] == 0

    def test_cape(self):
        result = parse_item_id("T8_CAPE")
        assert result["slot"] == "cape"
        assert result["is_two_handed"] is False

    def test_bag(self):
        result = parse_item_id("T7_BAG")
        assert result["slot"] == "bag"

    def test_mount(self):
        result = parse_item_id("T8_MOUNT_DIREWOLF")
        assert result["slot"] == "mount"

    def test_food_meal(self):
        result = parse_item_id("T7_MEAL_STEW")
        assert result["slot"] == "food"

    def test_food_fish(self):
        result = parse_item_id("T7_FISH_STEW")
        assert result["slot"] == "food"

    def test_potion(self):
        result = parse_item_id("T8_POTION_HEAL")
        assert result["slot"] == "potion"

    def test_no_enchantment_defaults_to_zero(self):
        result = parse_item_id("T8_2H_CLAYMORE")
        assert result["enchantment"] == 0

    def test_enchantment_four(self):
        result = parse_item_id("T8_2H_CLAYMORE@4")
        assert result["enchantment"] == 4

    def test_lowercase_accepted(self):
        result = parse_item_id("t8_2h_claymore@2")
        assert result["tier"] == 8
        assert result["slot"] == "main_hand"
        assert result["is_two_handed"] is True

    def test_whitespace_stripped(self):
        result = parse_item_id("  T7_MAIN_SWORD  ")
        assert result["tier"] == 7

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_item_id("INVALID_ITEM")

    def test_no_tier_prefix_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_item_id("MAIN_SWORD")

    def test_unclassifiable_category_raises(self):
        with pytest.raises(ValueError, match="classify slot"):
            parse_item_id("T8_UNKNOWN_THING")


# ---------------------------------------------------------------------------
# get_icon_url
# ---------------------------------------------------------------------------

class TestGetIconUrl:
    def test_default_size(self):
        url = get_icon_url("T8_2H_CLAYMORE@3")
        assert url == f"https://render.albiononline.com/v1/item/T8_2H_CLAYMORE@3.png?size={DEFAULT_ICON_SIZE}"

    def test_custom_size(self):
        url = get_icon_url("T7_MAIN_SWORD", size=64)
        assert url.endswith("?size=64")

    def test_item_id_uppercased(self):
        url = get_icon_url("t8_off_shield")
        assert "T8_OFF_SHIELD" in url

    def test_url_contains_png(self):
        url = get_icon_url("T8_HEAD_PLATE_SET1")
        assert ".png" in url

    def test_url_starts_with_render_service(self):
        url = get_icon_url("T8_MAIN_SWORD")
        assert url.startswith("https://render.albiononline.com/v1/item/")

    def test_invalid_size_raises(self):
        with pytest.raises(ValueError):
            get_icon_url("T8_MAIN_SWORD", size=0)

    def test_oversized_raises(self):
        with pytest.raises(ValueError):
            get_icon_url("T8_MAIN_SWORD", size=9999)


# ---------------------------------------------------------------------------
# is_allowed_tier
# ---------------------------------------------------------------------------

class TestIsAllowedTier:
    def test_t7_enchant0(self):
        assert is_allowed_tier(7, 0) is True

    def test_t7_enchant3(self):
        assert is_allowed_tier(7, 3) is True

    def test_t8_enchant0(self):
        assert is_allowed_tier(8, 0) is True

    def test_t8_enchant3(self):
        assert is_allowed_tier(8, 3) is True

    def test_t6_rejected(self):
        assert is_allowed_tier(6, 3) is False

    def test_t9_rejected(self):
        assert is_allowed_tier(9, 0) is False

    def test_t4_rejected(self):
        assert is_allowed_tier(4, 0) is False

    def test_enchant4_excluded_by_default(self):
        assert is_allowed_tier(8, 4) is False

    def test_enchant4_allowed_when_flag_set(self):
        assert is_allowed_tier(8, 4, include_t8_4=True) is True

    def test_t7_enchant4_allowed_when_flag_set(self):
        assert is_allowed_tier(7, 4, include_t8_4=True) is True

    def test_negative_enchant_rejected(self):
        assert is_allowed_tier(8, -1) is False


# ---------------------------------------------------------------------------
# make_catalog_entry
# ---------------------------------------------------------------------------

class TestMakeCatalogEntry:
    def test_valid_entry(self):
        entry = make_catalog_entry("T8_2H_CLAYMORE@3", "Claymore")
        assert entry["item_id"] == "T8_2H_CLAYMORE@3"
        assert entry["display_name"] == "Claymore"
        assert entry["tier"] == 8
        assert entry["enchantment"] == 3
        assert entry["slot"] == "main_hand"
        assert entry["is_two_handed"] is True
        assert "icon_url" in entry
        assert "render.albiononline.com" in entry["icon_url"]

    def test_item_id_normalised_to_uppercase(self):
        entry = make_catalog_entry("t8_main_sword", "Broadsword")
        assert entry["item_id"] == "T8_MAIN_SWORD"

    def test_display_name_stripped(self):
        entry = make_catalog_entry("T7_OFF_SHIELD", "  Shield  ")
        assert entry["display_name"] == "Shield"

    def test_t6_item_rejected(self):
        with pytest.raises(ValueError, match="outside the allowed"):
            make_catalog_entry("T6_2H_CLAYMORE", "Claymore")

    def test_t9_item_rejected(self):
        with pytest.raises(ValueError, match="outside the allowed"):
            make_catalog_entry("T9_MAIN_SWORD", "Sword")

    def test_enchant4_rejected_by_default(self):
        with pytest.raises(ValueError, match="outside the allowed"):
            make_catalog_entry("T8_2H_CLAYMORE@4", "Claymore")

    def test_enchant4_accepted_when_flag_set(self):
        entry = make_catalog_entry("T8_2H_CLAYMORE@4", "Claymore", include_t8_4=True)
        assert entry["enchantment"] == 4

    def test_base_item_id_field_present(self):
        entry = make_catalog_entry("T8_2H_CLAYMORE@3", "Claymore")
        assert "base_item_id" in entry
        assert entry["base_item_id"] == "T8_2H_CLAYMORE"

    def test_base_item_id_unenchanted(self):
        entry = make_catalog_entry("T8_2H_CLAYMORE", "Claymore")
        assert entry["base_item_id"] == "T8_2H_CLAYMORE"
        assert entry["base_item_id"] == entry["item_id"]


# ---------------------------------------------------------------------------
# AlbionItemCatalog — constructed directly for unit testing
# ---------------------------------------------------------------------------

def _make_test_catalog() -> AlbionItemCatalog:
    """Build a small, predictable catalog for unit tests."""
    entries = [
        make_catalog_entry("T8_2H_CLAYMORE",     "Claymore"),
        make_catalog_entry("T8_2H_CLAYMORE@1",   "Claymore"),
        make_catalog_entry("T8_2H_CLAYMORE@2",   "Claymore"),
        make_catalog_entry("T8_2H_CLAYMORE@3",   "Claymore"),
        make_catalog_entry("T7_2H_CLAYMORE",     "Claymore"),
        make_catalog_entry("T8_MAIN_SWORD",      "Broadsword"),
        make_catalog_entry("T8_MAIN_SWORD@1",    "Broadsword"),
        make_catalog_entry("T7_MAIN_SWORD",      "Broadsword"),
        make_catalog_entry("T8_OFF_SHIELD",      "Shield"),
        make_catalog_entry("T7_OFF_SHIELD",      "Shield"),
        make_catalog_entry("T8_HEAD_PLATE_SET1", "Guardian Helmet"),
        make_catalog_entry("T8_ARMOR_PLATE_SET1","Guardian Armor"),
        make_catalog_entry("T8_SHOES_PLATE_SET1","Guardian Boots"),
        make_catalog_entry("T8_CAPE",            "Cape"),
        make_catalog_entry("T8_BAG",             "Bag"),
        make_catalog_entry("T8_MOUNT_DIREWOLF",  "Direwolf"),
        make_catalog_entry("T7_MEAL_STEW",       "Beef Stew"),
        make_catalog_entry("T8_MEAL_STEW",       "Beef Stew"),
        make_catalog_entry("T7_POTION_HEAL",     "Healing Potion"),
        make_catalog_entry("T8_POTION_HEAL",     "Healing Potion"),
    ]
    return AlbionItemCatalog(entries)


class TestAlbionItemCatalog:
    @pytest.fixture
    def catalog(self):
        return _make_test_catalog()

    def test_get_all_returns_all_entries(self, catalog):
        assert len(catalog.get_all()) == len(catalog)

    def test_get_item_by_id(self, catalog):
        item = catalog.get_item("T8_2H_CLAYMORE@3")
        assert item is not None
        assert item["display_name"] == "Claymore"
        assert item["tier"] == 8
        assert item["enchantment"] == 3

    def test_get_item_case_insensitive_lookup(self, catalog):
        item = catalog.get_item("t8_2h_claymore@3")
        assert item is not None

    def test_get_item_unknown_returns_none(self, catalog):
        assert catalog.get_item("T8_2H_UNKNOWN_WEAPON@2") is None

    def test_get_by_slot_main_hand(self, catalog):
        items = catalog.get_by_slot("main_hand")
        assert len(items) > 0
        assert all(i["slot"] == "main_hand" for i in items)

    def test_get_by_slot_off_hand(self, catalog):
        items = catalog.get_by_slot("off_hand")
        assert all(i["slot"] == "off_hand" for i in items)

    def test_get_by_slot_unknown_raises(self, catalog):
        with pytest.raises(ValueError, match="Unknown equipment slot"):
            catalog.get_by_slot("weapon")

    def test_get_by_slot_empty_returns_empty_list(self):
        # Build a catalog with only main_hand items to verify missing slots return []
        minimal = AlbionItemCatalog([make_catalog_entry("T8_2H_CLAYMORE", "Claymore")])
        assert minimal.get_by_slot("off_hand") == []
        assert minimal.get_by_slot("shoes") == []

    def test_get_two_handed_items_all_two_handed(self, catalog):
        items = catalog.get_two_handed_items()
        assert len(items) > 0
        assert all(i["is_two_handed"] for i in items)
        assert all(i["slot"] == "main_hand" for i in items)

    def test_get_one_handed_items_none_two_handed(self, catalog):
        items = catalog.get_one_handed_items()
        assert len(items) > 0
        assert all(not i["is_two_handed"] for i in items)
        assert all(i["slot"] == "main_hand" for i in items)

    def test_search_by_name_case_insensitive(self, catalog):
        results = catalog.search_by_name("claymore")
        assert len(results) > 0
        assert all("Claymore" in r["display_name"] for r in results)

    def test_search_by_name_partial_match(self, catalog):
        results = catalog.search_by_name("broad")
        assert all("Broadsword" in r["display_name"] for r in results)

    def test_search_by_name_with_slot_filter(self, catalog):
        results = catalog.search_by_name("sword", slot="main_hand")
        assert all(r["slot"] == "main_hand" for r in results)

    def test_search_by_name_empty_returns_all(self, catalog):
        all_items = catalog.get_all()
        results = catalog.search_by_name("")
        assert len(results) == len(all_items)

    def test_search_by_name_empty_with_slot_returns_slot_items(self, catalog):
        off_hand = catalog.get_by_slot("off_hand")
        results = catalog.search_by_name("", slot="off_hand")
        assert len(results) == len(off_hand)

    def test_search_by_name_no_match_returns_empty(self, catalog):
        results = catalog.search_by_name("nonexistentweaponxyz")
        assert results == []

    def test_filter_by_tier_8(self, catalog):
        results = catalog.filter_by_tier(8)
        assert all(r["tier"] == 8 for r in results)

    def test_filter_by_tier_7(self, catalog):
        results = catalog.filter_by_tier(7)
        assert all(r["tier"] == 7 for r in results)

    def test_filter_by_tier_with_enchantment(self, catalog):
        results = catalog.filter_by_tier(8, enchantment=2)
        assert all(r["tier"] == 8 and r["enchantment"] == 2 for r in results)

    def test_filter_by_tier_6_returns_empty(self, catalog):
        # T6 items can't be in the catalog — always empty
        assert catalog.filter_by_tier(6) == []

    def test_len(self, catalog):
        assert len(catalog) == 20

    def test_catalog_entry_has_icon_url(self, catalog):
        item = catalog.get_item("T8_2H_CLAYMORE")
        assert "icon_url" in item
        assert "render.albiononline.com" in item["icon_url"]

    def test_two_handed_and_one_handed_counts(self, catalog):
        two_h = catalog.get_two_handed_items()
        one_h = catalog.get_one_handed_items()
        all_main = catalog.get_by_slot("main_hand")
        assert len(two_h) + len(one_h) == len(all_main)

    def test_list_items_same_as_get_all(self, catalog):
        assert catalog.list_items() == catalog.get_all()

    def test_get_all_is_deterministically_sorted(self, catalog):
        first = catalog.get_all()
        second = catalog.get_all()
        assert first == second

    def test_require_returns_item(self, catalog):
        item = catalog.require("T8_2H_CLAYMORE@3")
        assert item["item_id"] == "T8_2H_CLAYMORE@3"

    def test_require_case_insensitive(self, catalog):
        item = catalog.require("t8_2h_claymore@3")
        assert item is not None

    def test_require_unknown_raises_not_found(self, catalog):
        with pytest.raises(NotFoundError):
            catalog.require("T8_UNKNOWN_WEAPON@1")

    def test_filter_by_slot(self, catalog):
        results = catalog.filter(slot="off_hand")
        assert len(results) > 0
        assert all(e["slot"] == "off_hand" for e in results)

    def test_filter_by_tier(self, catalog):
        results = catalog.filter(tier=7)
        assert all(e["tier"] == 7 for e in results)

    def test_filter_by_enchantment(self, catalog):
        results = catalog.filter(enchantment=2)
        assert all(e["enchantment"] == 2 for e in results)

    def test_filter_by_is_two_handed_true(self, catalog):
        results = catalog.filter(is_two_handed=True)
        assert len(results) > 0
        assert all(e["is_two_handed"] for e in results)

    def test_filter_by_is_two_handed_false(self, catalog):
        results = catalog.filter(is_two_handed=False)
        assert len(results) > 0
        assert all(not e["is_two_handed"] for e in results)

    def test_filter_name_search_case_insensitive(self, catalog):
        results = catalog.filter(q="CLAYMORE")
        assert len(results) > 0
        assert all("Claymore" in e["display_name"] for e in results)

    def test_filter_combined(self, catalog):
        results = catalog.filter(slot="main_hand", tier=8, enchantment=3)
        assert all(
            e["slot"] == "main_hand" and e["tier"] == 8 and e["enchantment"] == 3
            for e in results
        )

    def test_filter_empty_q_returns_all(self, catalog):
        assert len(catalog.filter(q="")) == len(catalog)

    def test_filter_no_match_returns_empty(self, catalog):
        assert catalog.filter(q="xyznonexistent") == []

    def test_filter_invalid_slot_raises(self, catalog):
        with pytest.raises(ValueError, match="Unknown equipment slot"):
            catalog.filter(slot="weapon")

    def test_filter_invalid_tier_raises(self, catalog):
        with pytest.raises(ValueError, match="Invalid tier"):
            catalog.filter(tier=6)

    def test_filter_invalid_enchantment_raises(self, catalog):
        with pytest.raises(ValueError, match="Invalid enchantment"):
            catalog.filter(enchantment=5)

    def test_filter_result_is_deterministically_sorted(self, catalog):
        a = catalog.filter(slot="main_hand")
        b = catalog.filter(slot="main_hand")
        assert a == b

    def test_skipped_entries_empty_for_valid_catalog(self, catalog):
        assert catalog.skipped_entries == []


# ---------------------------------------------------------------------------
# Seed loading (_load_seed via reload_catalog with a temp file)
# ---------------------------------------------------------------------------

def _write_seed(items: list[dict]) -> Path:
    """Write a seed JSON to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(items, tmp)
    tmp.close()
    return Path(tmp.name)


class TestSeedLoading:
    def test_comment_section_markers_are_skipped(self):
        seed = [
            {"_comment": "weapons section", "_section": "swords"},
            {"item_type": "2H_CLAYMORE", "display_name": "Claymore"},
        ]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        # Only the actual item generates entries (T7×4 + T8×4 = 8)
        assert len(cat) == 8

    def test_generates_t7_and_t8_variants(self):
        seed = [{"item_type": "MAIN_SWORD", "display_name": "Broadsword"}]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        tiers = {e["tier"] for e in cat.get_all()}
        assert tiers == {7, 8}

    def test_generates_enchant_0_through_3(self):
        seed = [{"item_type": "2H_CLAYMORE", "display_name": "Claymore"}]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        enchants = {e["enchantment"] for e in cat.get_all()}
        assert enchants == {0, 1, 2, 3}

    def test_generate_enchants_false_produces_base_only(self):
        seed = [{"item_type": "CAPE", "display_name": "Cape", "generate_enchants": False}]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        # T7 + T8, both base (enchant=0)
        assert len(cat) == 2
        assert all(e["enchantment"] == 0 for e in cat.get_all())

    def test_t8_4_excluded_by_default(self):
        seed = [{"item_type": "2H_CLAYMORE", "display_name": "Claymore"}]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path, include_t8_4=False)
        enchants = {e["enchantment"] for e in cat.get_all()}
        assert 4 not in enchants

    def test_t8_4_included_when_flag_set(self):
        seed = [{"item_type": "2H_CLAYMORE", "display_name": "Claymore"}]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path, include_t8_4=True)
        enchants = {e["enchantment"] for e in cat.get_all()}
        assert 4 in enchants

    def test_entries_below_t7_never_loaded(self):
        # Seed format never generates T1-T6; verify by checking that all entries
        # from the seed are T7 or T8.
        seed = [{"item_type": "2H_CLAYMORE", "display_name": "Claymore"}]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        assert all(e["tier"] in ALLOWED_TIERS for e in cat.get_all())

    def test_missing_display_name_skipped(self):
        seed = [
            {"item_type": "2H_CLAYMORE", "display_name": ""},
            {"item_type": "MAIN_SWORD",  "display_name": "Broadsword"},
        ]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        names = {e["display_name"] for e in cat.get_all()}
        assert "Broadsword" in names
        # Empty display_name entry should produce no entries (skipped)
        assert "" not in names

    def test_missing_item_type_skipped(self):
        seed = [
            {"item_type": "", "display_name": "Orphan"},
            {"item_type": "MAIN_SWORD", "display_name": "Broadsword"},
        ]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        # Only Broadsword entries
        assert all(e["display_name"] == "Broadsword" for e in cat.get_all())

    def test_unclassifiable_slot_collected_in_skipped(self):
        seed = [
            {"item_type": "UNKNOWN_THING", "display_name": "Mystery"},
            {"item_type": "MAIN_SWORD",    "display_name": "Broadsword"},
        ]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        # UNKNOWN_THING raises ValueError → skipped (with reason), not raised
        assert all(e["display_name"] == "Broadsword" for e in cat.get_all())
        # generate_enchants defaults to True: T7×4 + T8×4 = 8 skipped variants
        assert len(cat.skipped_entries) == 8
        assert any("UNKNOWN_THING" in s["item_type"] for s in cat.skipped_entries)

    def test_duplicate_item_id_raises(self):
        seed = [
            {"item_type": "2H_CLAYMORE", "display_name": "Claymore"},
            {"item_type": "2H_CLAYMORE", "display_name": "Claymore Duplicate"},
        ]
        path = _write_seed(seed)
        with pytest.raises(ValueError, match="Duplicate item_id"):
            reload_catalog(seed_path=path)

    def test_missing_display_name_in_skipped(self):
        seed = [
            {"item_type": "2H_CLAYMORE", "display_name": ""},
            {"item_type": "MAIN_SWORD",  "display_name": "Broadsword"},
        ]
        path = _write_seed(seed)
        cat = reload_catalog(seed_path=path)
        assert len(cat.skipped_entries) == 1
        assert cat.skipped_entries[0]["item_type"] == "2H_CLAYMORE"


# ---------------------------------------------------------------------------
# Bundled seed integration test
# ---------------------------------------------------------------------------

class TestBundledSeed:
    """Integration tests against the actual bundled items_t7_t8.json seed."""

    @pytest.fixture(autouse=True)
    def fresh_catalog(self):
        """Always reload from bundled seed for isolation."""
        reload_catalog()

    def test_catalog_loads_without_error(self):
        cat = get_catalog()
        assert len(cat) > 0

    def test_all_entries_have_required_fields(self):
        cat = get_catalog()
        required = {"item_id", "display_name", "tier", "enchantment", "slot", "is_two_handed", "icon_url"}
        for entry in cat.get_all():
            assert required.issubset(entry.keys()), f"Entry missing fields: {entry}"

    def test_all_tiers_are_7_or_8(self):
        cat = get_catalog()
        assert all(e["tier"] in {7, 8} for e in cat.get_all())

    def test_no_enchantment_4_by_default(self):
        cat = get_catalog()
        assert all(e["enchantment"] <= 3 for e in cat.get_all())

    def test_two_handed_items_in_main_hand_slot(self):
        cat = get_catalog()
        two_h = cat.get_two_handed_items()
        assert len(two_h) > 0
        assert all(i["slot"] == "main_hand" and i["is_two_handed"] for i in two_h)

    def test_one_handed_items_in_main_hand_slot(self):
        cat = get_catalog()
        one_h = cat.get_one_handed_items()
        assert len(one_h) > 0
        assert all(i["slot"] == "main_hand" and not i["is_two_handed"] for i in one_h)

    def test_off_hand_items_not_two_handed(self):
        cat = get_catalog()
        off = cat.get_by_slot("off_hand")
        assert len(off) > 0
        assert all(not i["is_two_handed"] for i in off)

    def test_all_10_slot_types_represented(self):
        cat = get_catalog()
        present_slots = {e["slot"] for e in cat.get_all()}
        # All VALID_SLOTS should appear in the bundled seed
        assert present_slots == VALID_SLOTS, (
            f"Missing slots in bundled seed: {VALID_SLOTS - present_slots}"
        )

    def test_icon_urls_point_to_render_service(self):
        cat = get_catalog()
        for entry in cat.get_all():
            assert entry["icon_url"].startswith("https://render.albiononline.com/v1/item/")

    def test_icon_url_includes_item_id(self):
        cat = get_catalog()
        item = next(iter(cat.get_all()))
        assert item["item_id"] in item["icon_url"]

    def test_get_catalog_returns_singleton(self):
        cat1 = get_catalog()
        cat2 = get_catalog()
        assert cat1 is cat2

    def test_search_claymore_returns_only_claymores(self):
        cat = get_catalog()
        results = cat.search_by_name("claymore")
        assert len(results) > 0
        assert all("Claymore" in r["display_name"] for r in results)

    def test_filter_tier_7_contains_only_t7(self):
        cat = get_catalog()
        t7 = cat.filter_by_tier(7)
        assert len(t7) > 0
        assert all(e["tier"] == 7 for e in t7)

    def test_filter_tier_8_enchant_3(self):
        cat = get_catalog()
        t8e3 = cat.filter_by_tier(8, enchantment=3)
        assert len(t8e3) > 0
        assert all(e["tier"] == 8 and e["enchantment"] == 3 for e in t8e3)

    def test_t8_claymore_all_enchant_variants_present(self):
        cat = get_catalog()
        for enchant in range(4):
            suffix = "" if enchant == 0 else f"@{enchant}"
            item = cat.get_item(f"T8_2H_CLAYMORE{suffix}")
            assert item is not None, f"T8_2H_CLAYMORE@{enchant} missing from catalog"

    def test_slot_filter_returns_only_requested_slot(self):
        cat = get_catalog()
        for slot in VALID_SLOTS:
            items = cat.get_by_slot(slot)
            assert all(i["slot"] == slot for i in items), f"Slot mismatch in {slot}"

    def test_no_skipped_entries_in_bundled_seed(self):
        cat = get_catalog()
        assert cat.skipped_entries == [], (
            f"Bundled seed has invalid entries: {cat.skipped_entries}"
        )

    def test_all_entries_have_base_item_id(self):
        cat = get_catalog()
        for entry in cat.get_all():
            assert "base_item_id" in entry, f"Missing base_item_id in {entry['item_id']}"
            assert "@" not in entry["base_item_id"], (
                f"base_item_id should not contain @: {entry['base_item_id']}"
            )

    def test_get_all_is_sorted(self):
        cat = get_catalog()
        all_items = cat.get_all()
        slots = [e["slot"] for e in all_items]
        assert slots == sorted(slots), "get_all() must return items sorted by slot"

    def test_require_known_item(self):
        cat = get_catalog()
        item = cat.require("T8_2H_CLAYMORE@3")
        assert item["item_id"] == "T8_2H_CLAYMORE@3"

    def test_require_unknown_raises_not_found(self):
        cat = get_catalog()
        with pytest.raises(NotFoundError):
            cat.require("T8_INVENTED_WEAPON@1")

    def test_filter_combined_slot_tier_enchantment_q(self):
        cat = get_catalog()
        results = cat.filter(slot="main_hand", tier=8, enchantment=3, q="claymore")
        assert len(results) > 0
        assert all(
            e["slot"] == "main_hand"
            and e["tier"] == 8
            and e["enchantment"] == 3
            and "Claymore" in e["display_name"]
            for e in results
        )

    def test_list_items_same_length_as_get_all(self):
        cat = get_catalog()
        assert len(cat.list_items()) == len(cat.get_all())

    def test_no_t6_or_t9_items(self):
        cat = get_catalog()
        assert all(e["tier"] in {7, 8} for e in cat.get_all())
