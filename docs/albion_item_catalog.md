# Albion Item Catalog

IronkeepV2 ships a static, version-controlled item catalog that powers slot filtering, icon URLs, and guild-build selection. This document explains the complete data pipeline.

---

## 1. Source of Data

The catalog is derived from **[ao-bin-dumps](https://github.com/ao-data/ao-bin-dumps)**, a community-maintained mirror of Albion Online's game data published by the Albion Online Data Project.

The specific file used is `formatted/items.txt`, which contains every item ID and its localised display name.

The snapshot currently in the repository was fetched on **2026-07-13** from commit `a49c3dd2efef4ccd952d57e8bcb180f17d6c0b6e` of ao-bin-dumps.

---

## 2. Repository Layout

```
data/
  albion/
    source/
      items_snapshot.txt     ← version-controlled ao-bin-dumps snapshot
      source_metadata.json   ← provenance: SHA-256, commit, fetch date

app/
  albion/
    data/
      items_t7_t8.json       ← generated catalog seed (version-controlled)
    item_catalog.py          ← runtime catalog (loads seed at startup)

scripts/
  fetch_albion_snapshot.py   ← downloads a fresh snapshot (requires internet)
  import_albion_catalog.py   ← generates items_t7_t8.json from snapshot
  import_ironkeep_v1_catalog.py  ← LEGACY migration tool (not primary workflow)
```

### What is `items_snapshot.txt`?

A verbatim copy of `formatted/items.txt` from ao-bin-dumps. It is **version-controlled** so that a fresh clone of IronkeepV2 can regenerate the catalog without any network access.

### What is `items_t7_t8.json`?

A processed JSON seed that lists every T7/T8 equippable item the build editor should know about. The runtime catalog (`AlbionItemCatalog`) loads this seed at application startup and expands it into all tier + enchantment variants.

---

## 3. How to Refresh the Snapshot

Run this when ao-bin-dumps has been updated and you want to pick up new or changed items:

```bash
# Step 1: download the latest snapshot (requires internet)
python scripts/fetch_albion_snapshot.py

# Step 2: regenerate the catalog seed
python scripts/import_albion_catalog.py

# Step 3: verify the catalog matches the new snapshot
python scripts/import_albion_catalog.py --check

# Step 4: commit both files
git add data/albion/source/ app/albion/data/items_t7_t8.json
git commit -m "chore: refresh albion item catalog snapshot (ao-bin-dumps <commit>)"
```

---

## 4. How to Run the Importer

```bash
# Default: reads data/albion/source/items_snapshot.txt
#          writes app/albion/data/items_t7_t8.json
python scripts/import_albion_catalog.py

# Dry run (print report, no file written)
python scripts/import_albion_catalog.py --dry-run

# Custom snapshot path
python scripts/import_albion_catalog.py --snapshot /path/to/items.txt

# Custom output path
python scripts/import_albion_catalog.py --output /tmp/my_catalog.json
```

The importer:
- Reads the snapshot and parses all item IDs and display names.
- Applies slot classification via V2's `_classify_slot()`.
- Filters to T7 and T8 equippable items only.
- Excludes tools, blueprints, cosmetic skins, and non-tradable items.
- Detects `generate_enchants` automatically: if `T7_ITEM@1` exists in the snapshot, enchant variants will be generated at runtime.
- Adds a `tiers` field for items that exist only at T7 or only at T8.
- Writes a deterministic, sorted JSON seed with section comments.

---

## 5. How to Run --check

```bash
python scripts/import_albion_catalog.py --check
```

This mode regenerates the catalog in memory and compares it against the committed `items_t7_t8.json`. It exits with code 1 if they differ.

Use this in CI to catch cases where the snapshot or importer was changed without regenerating the catalog:

```yaml
# Example GitHub Actions step
- name: Verify catalog is up to date
  run: python scripts/import_albion_catalog.py --check
```

---

## 6. How to Resolve Validation Failures

If `--check` fails:

```
Catalog is OUT OF DATE — differences found:
  3 entries in snapshot but not in committed catalog:
    + SOME_NEW_ITEM
Fix: python scripts/import_albion_catalog.py
```

Run the importer and commit the result:

```bash
python scripts/import_albion_catalog.py
git add app/albion/data/items_t7_t8.json
git commit -m "chore: update catalog seed"
```

If the snapshot itself has changed (new ao-bin-dumps commit):

```bash
python scripts/fetch_albion_snapshot.py
python scripts/import_albion_catalog.py
python scripts/import_albion_catalog.py --check
git add data/albion/source/ app/albion/data/items_t7_t8.json
git commit -m "chore: refresh albion item catalog snapshot"
```

---

## 7. Why Runtime Has No Downloads

IronkeepV2 never downloads item data at runtime. Reasons:

1. **Reproducibility** — the catalog is deterministic from a version-controlled file.
2. **Reliability** — no network failure can break the build editor.
3. **Testability** — all catalog tests run offline.
4. **Auditability** — every item in the catalog is traceable to a specific snapshot commit.

---

## 8. generate_enchants Policy

Determined automatically from the ao-bin-dumps snapshot:

| Category | Rule | Rationale |
|---|---|---|
| Weapons, armour, off-hands, capes, bags, food (meals), potions | `generate_enchants: true` | @1/@2/@3 variants confirmed in snapshot |
| Mounts | `generate_enchants: false` | No @enchant variants in snapshot |
| Fish items | `generate_enchants: false` | No @enchant variants in snapshot |

**Important correction from Phase 12.1b**: Capes, food (meal items), potions, and bags all have @1/@2/@3 enchanted variants in Albion Online and in ao-bin-dumps. Phase 12.1b incorrectly set these to `generate_enchants: false`. Phase 12.1c corrects this.

---

## 9. tiers Field

Items that only exist at T7 or only at T8 carry an explicit `tiers` field in the seed:

```json
{"item_type": "MEAL_PIE", "display_name": "Pork Pie", "tiers": [7]}
{"item_type": "MEAL_STEW", "display_name": "Beef Stew", "tiers": [8]}
```

Without `tiers`, the runtime generates both T7 and T8 variants (default).

This prevents generating IDs like `T8_MEAL_PIE` that do not exist in Albion Online.

---

## 10. How Phase 12.2 Uses the Catalog

Phase 12.2 (Build Domain Model) consumes the catalog via the Python API:

```python
from app.albion.item_catalog import get_catalog

catalog = get_catalog()

# Validate a slot assignment
item = catalog.get_item("T8_2H_CLAYMORE@2")   # → dict or None
catalog.require("T8_2H_CLAYMORE@2")           # → dict or raises NotFoundError

# Filter
catalog.filter(slot="main_hand", tier=8, is_two_handed=True)

# Search
catalog.search_by_name("claymore")
```

The HTTP API (Phase 12.1) exposes:

```
GET /api/catalog/slots
GET /api/catalog/items
GET /api/catalog/items/{item_id}
```

See `app/routes_catalog.py` for endpoint details.
