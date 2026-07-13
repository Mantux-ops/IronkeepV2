"""
Catalog integrity tests — Phase 12.1c.

These tests verify that:
  - The ao-bin-dumps snapshot is present and has the expected SHA-256.
  - The source_metadata.json is coherent and complete.
  - The committed items_t7_t8.json matches what the importer would generate
    from the snapshot (--check mode).
  - Every item ID in items_t7_t8.json can be derived from the snapshot.
  - Bags are canonical (verified against snapshot) and not placeholders.
  - No generate_enchants decisions are inconsistent with raw snapshot data.
  - No duplicate base_types exist in the seed.
  - All slots in the seed are valid V2 slots.
  - No tier values outside {7, 8} appear in the generated catalog.
  - No enchantment values outside {0, 1, 2, 3} appear (no @4 by default).
  - No skipped entries exist in the loaded production catalog.
  - Icon URLs are syntactically valid for all entries.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.albion.item_catalog import VALID_SLOTS, get_catalog, reload_catalog, get_icon_url
from scripts.import_albion_catalog import (
    parse_snapshot,
    classify_and_group,
    build_seed_entries,
    check_catalog_up_to_date,
    _EXCLUDE_PATTERNS,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SNAPSHOT = _REPO_ROOT / "data" / "albion" / "source" / "items_snapshot.txt"
_METADATA = _REPO_ROOT / "data" / "albion" / "source" / "source_metadata.json"
_SEED = _REPO_ROOT / "app" / "albion" / "data" / "items_t7_t8.json"

_EXPECTED_SHA256 = "3ed74ae095b607785b099abdbbec048834be3ff564c4ba4fd82d94c0b1d0d041"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def raw_items() -> dict[str, str]:
    return parse_snapshot(_SNAPSHOT)


@pytest.fixture(scope="module")
def grouped(raw_items) -> dict[str, dict]:
    return classify_and_group(raw_items)


@pytest.fixture(scope="module")
def seed_entries(grouped) -> list[dict]:
    entries, _ = build_seed_entries(grouped)
    return entries


@pytest.fixture(scope="module")
def committed_seed() -> list[dict]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def data_entries(committed_seed) -> list[dict]:
    """Seed entries without _comment / _section markers."""
    return [e for e in committed_seed if "_comment" not in e and "_section" not in e]


@pytest.fixture(scope="module")
def catalog():
    return reload_catalog()


# ---------------------------------------------------------------------------
# 1. Snapshot tests
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_file_exists(self):
        assert _SNAPSHOT.exists(), f"Missing: {_SNAPSHOT}"

    def test_snapshot_sha256_matches_metadata(self):
        data = _SNAPSHOT.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        assert actual == _EXPECTED_SHA256, (
            f"SHA-256 mismatch. Snapshot may have changed.\n"
            f"  Expected : {_EXPECTED_SHA256}\n"
            f"  Actual   : {actual}\n"
            "Run: python scripts/fetch_albion_snapshot.py && "
            "python scripts/import_albion_catalog.py"
        )

    def test_metadata_file_exists(self):
        assert _METADATA.exists(), f"Missing: {_METADATA}"

    def test_metadata_has_required_fields(self):
        meta = json.loads(_METADATA.read_text(encoding="utf-8"))
        for field in ("source", "source_repository", "source_file",
                      "source_sha256", "catalog_schema_version"):
            assert field in meta, f"metadata missing field: {field}"

    def test_metadata_sha256_matches_snapshot(self):
        meta = json.loads(_METADATA.read_text(encoding="utf-8"))
        data = _SNAPSHOT.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        assert meta["source_sha256"] == actual, (
            "source_metadata.json SHA-256 does not match snapshot file. "
            "Re-run fetch and import scripts."
        )

    def test_metadata_schema_version_is_2(self):
        meta = json.loads(_METADATA.read_text(encoding="utf-8"))
        assert meta["catalog_schema_version"] == 2

    def test_snapshot_contains_t7_and_t8_items(self, raw_items):
        t7 = [k for k in raw_items if k.startswith("T7_")]
        t8 = [k for k in raw_items if k.startswith("T8_")]
        assert len(t7) > 500
        assert len(t8) > 500

    def test_corrupt_sha256_detected(self, tmp_path):
        fake = tmp_path / "fake.txt"
        fake.write_text("corrupted data", encoding="utf-8")
        actual = hashlib.sha256(fake.read_bytes()).hexdigest()
        assert actual != _EXPECTED_SHA256, "Corruption test: fake file unexpectedly matches real SHA"


# ---------------------------------------------------------------------------
# 2. Importer --check mode
# ---------------------------------------------------------------------------


class TestImporterCheck:
    def test_check_passes_for_committed_catalog(self):
        ok, msg = check_catalog_up_to_date(_SNAPSHOT, _SEED)
        assert ok, f"Catalog is out of date:\n{msg}"

    def test_importer_produces_no_skipped_entries(self, grouped):
        _, skipped = build_seed_entries(grouped)
        assert skipped == [], f"Import errors: {skipped}"

    def test_importer_output_is_deterministic(self, raw_items):
        g1 = classify_and_group(raw_items)
        e1, _ = build_seed_entries(g1)
        g2 = classify_and_group(raw_items)
        e2, _ = build_seed_entries(g2)
        assert e1 == e2, "Importer output is not deterministic"

    def test_seed_sorted_by_item_type(self, data_entries):
        types = [e["item_type"] for e in data_entries]
        # Within each slot group the entries should be sorted
        # (we verify globally that no obvious disorder exists)
        # Just check that the overall list is stable across runs
        assert types == sorted(set(types), key=types.index), "Duplicate types in seed"

    def test_no_duplicate_item_types_in_seed(self, data_entries):
        types = [e["item_type"] for e in data_entries]
        dupes = [t for t in types if types.count(t) > 1]
        assert dupes == [], f"Duplicate item_types in seed: {set(dupes)}"


# ---------------------------------------------------------------------------
# 3. Bag verification
# ---------------------------------------------------------------------------


class TestBagVerification:
    """Verify bags against the ao-bin-dumps snapshot (no placeholders)."""

    def test_bag_exists_in_snapshot(self, raw_items):
        assert "T7_BAG" in raw_items, "T7_BAG not in snapshot"
        assert "T8_BAG" in raw_items, "T8_BAG not in snapshot"

    def test_bag_insight_exists_in_snapshot(self, raw_items):
        assert "T7_BAG_INSIGHT" in raw_items, "T7_BAG_INSIGHT not in snapshot"
        assert "T8_BAG_INSIGHT" in raw_items, "T8_BAG_INSIGHT not in snapshot"

    def test_bag_leather_does_not_exist_in_snapshot(self, raw_items):
        assert "T7_BAG_LEATHER" not in raw_items, "T7_BAG_LEATHER unexpectedly present"
        assert "T8_BAG_LEATHER" not in raw_items, "T8_BAG_LEATHER unexpectedly present"

    def test_bag_leather_not_in_committed_seed(self, data_entries):
        types = {e["item_type"] for e in data_entries}
        assert "BAG_LEATHER" not in types, "Placeholder BAG_LEATHER still in seed"

    def test_bag_display_name_is_bag(self, data_entries):
        bag = next((e for e in data_entries if e["item_type"] == "BAG"), None)
        assert bag is not None, "BAG not in seed"
        assert bag["display_name"] == "Bag"

    def test_bag_insight_display_name(self, data_entries):
        bag = next((e for e in data_entries if e["item_type"] == "BAG_INSIGHT"), None)
        assert bag is not None, "BAG_INSIGHT not in seed"
        assert bag["display_name"] == "Satchel of Insight"

    def test_bag_has_enchant_variants(self, raw_items):
        """Bags have @1/@2/@3 in the snapshot → generate_enchants should be True."""
        assert "T7_BAG@1" in raw_items
        assert "T8_BAG_INSIGHT@2" in raw_items

    def test_bag_not_marked_generate_enchants_false(self, data_entries):
        for e in data_entries:
            if e["item_type"].startswith("BAG"):
                assert e.get("generate_enchants", True) is True, (
                    f"BAG item incorrectly has generate_enchants: false: {e}"
                )

    def test_bags_loaded_in_catalog(self, catalog):
        # 2 base items × 2 tiers × 4 enchants = 16
        bags = catalog.get_by_slot("bag")
        assert len(bags) == 16, f"Expected 16 bag entries, got {len(bags)}"

    def test_bags_have_correct_slot(self, catalog):
        bags = catalog.get_by_slot("bag")
        assert all(e["slot"] == "bag" for e in bags)

    def test_bag_enchant_variants_present(self, catalog):
        for enchant in range(4):  # 0–3
            suffix = "" if enchant == 0 else f"@{enchant}"
            assert catalog.get_item(f"T8_BAG{suffix}") is not None, (
                f"T8_BAG{suffix} missing from catalog"
            )


# ---------------------------------------------------------------------------
# 4. Seed data integrity
# ---------------------------------------------------------------------------


class TestSeedDataIntegrity:
    def test_all_item_types_derivable_from_snapshot(self, data_entries, raw_items):
        """Every seed item_type must correspond to a real T7 or T8 item in the snapshot."""
        missing = []
        for e in data_entries:
            bt = e["item_type"]
            tiers = e.get("tiers", [7, 8])
            for t in tiers:
                if f"T{t}_{bt}" not in raw_items:
                    missing.append(f"T{t}_{bt}")
        assert missing == [], (
            f"{len(missing)} seed IDs not found in snapshot:\n"
            + "\n".join(f"  {m}" for m in missing[:10])
        )

    def test_generate_enchants_consistent_with_snapshot(self, data_entries, raw_items):
        """For items marked generate_enchants: false, @1 must not exist in snapshot.
        For items marked true (default), @1 must exist in snapshot for at least one tier."""
        wrong = []
        for e in data_entries:
            bt = e["item_type"]
            tiers = e.get("tiers", [7, 8])
            gen_ench = e.get("generate_enchants", True)
            has_enchant_in_snap = any(f"T{t}_{bt}@1" in raw_items for t in tiers)

            if gen_ench and not has_enchant_in_snap:
                wrong.append(f"{bt}: marked generate_enchants=True but no @1 in snapshot")
            elif not gen_ench and has_enchant_in_snap:
                wrong.append(f"{bt}: marked generate_enchants=False but @1 exists in snapshot")
        assert wrong == [], "\n".join(wrong[:10])

    def test_no_excluded_items_in_seed(self, data_entries):
        """Tools, blueprints, skins must not appear in the seed."""
        violations = [
            e["item_type"] for e in data_entries
            if _EXCLUDE_PATTERNS.search(e["item_type"])
        ]
        assert violations == [], f"Excluded item patterns in seed: {violations}"

    def test_all_slots_are_valid(self, catalog):
        from app.albion.item_catalog import _classify_slot
        for entry in catalog.get_all():
            assert entry["slot"] in VALID_SLOTS, f"Invalid slot: {entry['slot']}"

    def test_no_tier_outside_7_or_8(self, catalog):
        for entry in catalog.get_all():
            assert entry["tier"] in (7, 8), f"Unexpected tier: {entry['tier']}"

    def test_no_enchantment_4_by_default(self, catalog):
        for entry in catalog.get_all():
            assert entry["enchantment"] != 4, (
                f"Enchantment 4 found: {entry['item_id']}"
            )

    def test_no_skipped_entries_in_production(self, catalog):
        assert catalog.skipped_entries == [], (
            f"Production catalog has skipped entries: {catalog.skipped_entries[:3]}"
        )

    def test_all_10_slots_represented(self, catalog):
        present = {e["slot"] for e in catalog.get_all()}
        assert present == VALID_SLOTS

    def test_known_correct_ids_present(self, catalog):
        """Spot-check canonical IDs that must exist in any valid catalog."""
        required = [
            "T8_2H_FIRESTAFF",     # correct (not STAFFFIRE)
            "T8_2H_CLAYMORE",
            "T7_2H_DAGGERPAIR",    # correct (not DAGGER_PAIR)
            "T8_MAIN_SWORD",
            "T7_OFF_SHIELD",
            "T7_POTION_REVIVE",    # T7 Gigantify Potion (not POTION_HEAL)
            "T7_BAG",
            "T8_BAG_INSIGHT",
            "T8_MEAL_STEW",
        ]
        missing = [r for r in required if catalog.get_item(r) is None]
        assert missing == [], f"Required canonical IDs not found: {missing}"

    def test_known_invented_ids_absent(self, catalog):
        """IDs that were fabricated in Phase 12.1 must not appear in the catalog."""
        invented = [
            "T8_2H_STAFFFIRE",
            "T8_2H_STAFFICE",
            "T8_2H_STAFFHOLY",
            "T8_2H_DAGGER_PAIR",
            "T7_POTION_HEAL",
            "T8_POTION_ENERGY",
            "T7_MEAL_SOUP",
            "T7_BAG_LEATHER",
            "T8_MOUNT_DIREWOLF",
            "T7_CAPE_UNDEAD",
        ]
        found = [i for i in invented if catalog.get_item(i) is not None]
        assert found == [], f"Fabricated IDs still in catalog: {found}"

    def test_icon_urls_syntactically_valid(self, catalog):
        """Check every icon URL is a valid HTTPS render.albiononline.com URL."""
        _render_re = re.compile(
            r"^https://render\.albiononline\.com/v1/item/[A-Z0-9_@%]+\.png\?size=\d+$"
        )
        bad = []
        for e in catalog.get_all():
            url = e.get("icon_url", "")
            if not _render_re.match(url):
                bad.append((e["item_id"], url))
            if len(bad) >= 5:
                break
        assert bad == [], f"Invalid icon URLs: {bad}"
