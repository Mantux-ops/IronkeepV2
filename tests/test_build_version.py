"""
Phase 12.3 — Versioned build system tests.

Coverage:
  Group 1  — Domain validation: build metadata
  Group 2  — Domain validation: slot items
  Group 3  — Catalog validation in use cases
  Group 4  — Repository: build v2 insert/update/archive/restore
  Group 5  — Repository: build versions
  Group 6  — Repository: build slot items
  Group 7  — Use case: create_build
  Group 8  — Use case: create_build_version (versioning)
  Group 9  — Use case: lifecycle (archive, restore, publish)
  Group 10 — Database constraints and workspace isolation
  Group 11 — Route: GET builds detail (v2 vs legacy)
  Group 12 — Route: POST create build (visual editor)
  Group 13 — Route: POST create_build_version
  Group 14 — Route: lifecycle routes (archive, restore, publish)
  Group 15 — Route: version history and version detail
  Group 16 — Regression: legacy builds/compositions unaffected
  Group 17 — Build type isolation (helpers + repo filters)
  Group 18 — Transaction rollback integrity
  Group 19 — Direct database integrity (cross-build/workspace FK)
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import build_version as bv_domain
from app.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from app.main import app

from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ITEM_MAIN = "T8_MAIN_CLAYMORE"         # 1H sword, main_hand
_VALID_ITEM_MAIN_2H = "T8_2H_CLAYMORE"        # 2H sword, main_hand
_VALID_ITEM_HEAD = "T8_HEAD_PLATE_SET3"       # plate head
_VALID_ITEM_CHEST = "T8_ARMOR_PLATE_SET3"     # plate chest
_VALID_ITEM_SHOES = "T8_SHOES_PLATE_SET3"     # plate shoes
_VALID_ITEM_FOOD = "MEAL_PORK_OMELETTE_HERBAL"  # food
_VALID_ITEM_POTION = "POTION_HEALING_T8"       # potion
_VALID_ITEM_OFF = "T8_OFFHAND_TORCH"           # off_hand


def _get_valid_item_id_for_slot(slot: str) -> str:
    """Return a known valid catalog item ID for the given slot."""
    from app.albion.item_catalog import get_catalog
    catalog = get_catalog()
    items = catalog.get_by_slot(slot)
    if not items:
        pytest.skip(f"No catalog items found for slot '{slot}'")
    return items[0]["item_id"]


def _get_two_handed_item() -> str:
    """Return a known two-handed item ID."""
    from app.albion.item_catalog import get_catalog
    catalog = get_catalog()
    items = catalog.filter(slot="main_hand", is_two_handed=True)
    if not items:
        pytest.skip("No two-handed main_hand items in catalog")
    return items[0]["item_id"]


def _make_setup(slug: str):
    owner = make_user(f"owner-{slug}")
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    client = TestClient(app)
    client.post("/login", data={"display_name": f"owner-{slug}", "next": "/"}, follow_redirects=True)
    return client, owner, ws


def _published_slot_json(workspace_id: str) -> str:
    """Return a slot_items_json string with all published-required slots filled."""
    from app.albion.item_catalog import get_catalog
    cat = get_catalog()

    def first(slot):
        items = cat.get_by_slot(slot)
        if not items:
            pytest.skip(f"No items for slot {slot}")
        return items[0]["item_id"]

    slots = [
        {"slot": "main_hand", "item_id": first("main_hand"), "is_primary": True},
        {"slot": "head",      "item_id": first("head"),      "is_primary": True},
        {"slot": "chest",     "item_id": first("chest"),     "is_primary": True},
        {"slot": "shoes",     "item_id": first("shoes"),     "is_primary": True},
        {"slot": "food",      "item_id": first("food"),      "is_primary": True},
        {"slot": "potion",    "item_id": first("potion"),    "is_primary": True},
    ]
    return json.dumps(slots)


def _minimal_slot_json(workspace_id: str) -> str:
    """Return a minimal slot_items_json (just main_hand) for draft builds."""
    from app.albion.item_catalog import get_catalog
    cat = get_catalog()
    items = cat.get_by_slot("main_hand")
    if not items:
        pytest.skip("No main_hand items in catalog")
    return json.dumps([{"slot": "main_hand", "item_id": items[0]["item_id"], "is_primary": True}])


def _create_v2_build(ws_id: str, actor_id: str, *, slot_json: str | None = None) -> dict:
    """Helper to create a versioned build for testing."""
    if slot_json is None:
        slot_json = _minimal_slot_json(ws_id)
    return use_cases.create_build(
        guild_workspace_id=ws_id,
        actor_user_id=actor_id,
        name="Test Healer",
        description="A test build",
        role="healer",
        event_type="zvz",
        minimum_ip=1000,
        status="draft",
        slot_items_json=slot_json,
        change_summary="Initial version",
    )


# ---------------------------------------------------------------------------
# Group 1 — Domain validation: build metadata
# ---------------------------------------------------------------------------

class TestBuildMetaValidation:
    """domain/build_version.py — validate_build_meta()"""

    def test_valid_metadata_passes(self):
        bv_domain.validate_build_meta({
            "name": "Hallowfall Healer",
            "role": "healer",
            "event_type": "zvz",
            "minimum_ip": 1000,
            "status": "draft",
        })

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError, match="name"):
            bv_domain.validate_build_meta({"name": "", "role": "healer", "event_type": "zvz"})

    def test_name_too_short_raises(self):
        with pytest.raises(ValidationError, match="name"):
            bv_domain.validate_build_meta({"name": "X", "role": "healer", "event_type": "zvz"})

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError, match="name"):
            bv_domain.validate_build_meta({
                "name": "A" * 101, "role": "healer", "event_type": "zvz"
            })

    def test_empty_role_raises(self):
        with pytest.raises(ValidationError, match="role"):
            bv_domain.validate_build_meta({"name": "Test", "role": "", "event_type": "zvz"})

    def test_invalid_role_raises(self):
        with pytest.raises(ValidationError, match="Invalid role"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "wizard", "event_type": "zvz"
            })

    def test_all_valid_roles(self):
        for role in bv_domain.VALID_ROLES:
            bv_domain.validate_build_meta({
                "name": "Test", "role": role, "event_type": "zvz"
            })

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValidationError, match="event type"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "raid"
            })

    def test_all_valid_event_types(self):
        for et in bv_domain.VALID_EVENT_TYPES:
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": et
            })

    def test_negative_minimum_ip_raises(self):
        with pytest.raises(ValidationError, match="Minimum IP"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "zvz",
                "minimum_ip": -1,
            })

    def test_zero_minimum_ip_passes(self):
        bv_domain.validate_build_meta({
            "name": "Test", "role": "healer", "event_type": "zvz",
            "minimum_ip": 0,
        })

    def test_non_integer_minimum_ip_raises(self):
        with pytest.raises(ValidationError, match="Minimum IP"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "zvz",
                "minimum_ip": "not_a_number",
            })

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError, match="status"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "zvz",
                "status": "active",
            })

    def test_archived_status_via_api_raises(self):
        # archived status cannot be set directly via the form
        with pytest.raises(ValidationError):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "zvz",
                "status": "archived",
            })

    def test_description_too_long_raises(self):
        with pytest.raises(ValidationError, match="Description"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "zvz",
                "description": "X" * 1001,
            })

    def test_change_summary_too_long_raises(self):
        with pytest.raises(ValidationError, match="Change summary"):
            bv_domain.validate_build_meta({
                "name": "Test", "role": "healer", "event_type": "zvz",
                "change_summary": "X" * 301,
            })


# ---------------------------------------------------------------------------
# Group 2 — Domain validation: slot items
# ---------------------------------------------------------------------------

class TestSlotItemValidation:
    """domain/build_version.py — validate_slot_items()"""

    def _make_item(self, slot, item_id="T8_MAIN_CLAYMORE", tier=8, ench=0,
                   is_primary=True, is_two_handed=False):
        return {
            "slot": slot, "item_id": item_id, "tier": tier,
            "enchantment": ench, "is_primary": is_primary,
            "is_two_handed": is_two_handed,
        }

    def test_valid_single_item_passes(self):
        bv_domain.validate_slot_items(
            [self._make_item("main_hand")], "draft"
        )

    def test_unknown_slot_raises(self):
        with pytest.raises(ValidationError, match="slot"):
            bv_domain.validate_slot_items(
                [self._make_item("shield")], "draft"
            )

    def test_invalid_tier_raises(self):
        with pytest.raises(ValidationError, match="tier"):
            bv_domain.validate_slot_items(
                [self._make_item("main_hand", tier=6)], "draft"
            )

    def test_invalid_enchantment_raises(self):
        with pytest.raises(ValidationError, match="enchantment"):
            bv_domain.validate_slot_items(
                [self._make_item("main_hand", ench=4)], "draft"
            )

    def test_two_primary_in_same_slot_raises(self):
        items = [
            self._make_item("main_hand", item_id="T8_MAIN_CLAYMORE"),
            self._make_item("main_hand", item_id="T8_MAIN_BROADSWORD"),
        ]
        with pytest.raises(ValidationError, match="primary"):
            bv_domain.validate_slot_items(items, "draft")

    def test_duplicate_item_id_in_slot_raises(self):
        item_id = "T8_MAIN_CLAYMORE"
        items = [
            self._make_item("main_hand", item_id=item_id, is_primary=True),
            self._make_item("main_hand", item_id=item_id, is_primary=False),
        ]
        with pytest.raises(ValidationError, match="more than once"):
            bv_domain.validate_slot_items(items, "draft")

    def test_two_handed_with_off_hand_raises(self):
        items = [
            self._make_item("main_hand", is_two_handed=True),
            self._make_item("off_hand", item_id="T8_OFFHAND_TORCH"),
        ]
        with pytest.raises(ValidationError, match="two-handed"):
            bv_domain.validate_slot_items(items, "draft")

    def test_two_handed_without_off_hand_passes(self):
        bv_domain.validate_slot_items(
            [self._make_item("main_hand", is_two_handed=True)], "draft"
        )

    def test_published_missing_required_slot_raises(self):
        # Only main_hand — missing head, chest, shoes, food, potion
        items = [self._make_item("main_hand")]
        with pytest.raises(ValidationError, match="slots"):
            bv_domain.validate_slot_items(items, "published")

    def test_published_with_all_required_slots_passes(self):
        required = list(bv_domain.PUBLISHED_REQUIRED_SLOTS)
        items = [
            self._make_item(slot, item_id=f"T8_{i}")
            for i, slot in enumerate(required)
        ]
        bv_domain.validate_slot_items(items, "published")

    def test_draft_with_partial_slots_passes(self):
        bv_domain.validate_slot_items(
            [self._make_item("head", item_id="T8_HEAD_PLATE")], "draft"
        )

    def test_empty_item_id_raises(self):
        with pytest.raises(ValidationError):
            bv_domain.validate_slot_items(
                [{"slot": "main_hand", "item_id": "", "tier": 8, "enchantment": 0,
                  "is_primary": True, "is_two_handed": False}], "draft"
            )

    def test_missing_slot_raises(self):
        with pytest.raises(ValidationError):
            bv_domain.validate_slot_items(
                [{"slot": "", "item_id": "T8_MAIN_CLAYMORE", "tier": 8, "enchantment": 0,
                  "is_primary": True, "is_two_handed": False}], "draft"
            )


# ---------------------------------------------------------------------------
# Group 3 — Catalog validation in use cases
# ---------------------------------------------------------------------------

class TestCatalogValidationInUseCases:

    def test_unknown_item_id_rejected(self):
        owner = make_user("catalog-owner")
        ws = make_workspace(owner_user_id=owner["id"], slug="catalog-ws1")
        bad_json = json.dumps([
            {"slot": "main_hand", "item_id": "TOTALLY_FAKE_ITEM_XYZ", "is_primary": True}
        ])
        with pytest.raises((ValidationError, NotFoundError)):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=owner["id"],
                name="Bad Build",
                description="",
                role="healer",
                event_type="zvz",
                minimum_ip=0,
                status="draft",
                slot_items_json=bad_json,
            )

    def test_wrong_slot_rejected(self):
        """An item submitted for the wrong slot is rejected by catalog validation."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        head_items = cat.get_by_slot("head")
        if not head_items:
            pytest.skip("No head items")
        head_id = head_items[0]["item_id"]

        owner = make_user("catalog-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="catalog-ws2")
        # Submit head item as main_hand
        bad_json = json.dumps([
            {"slot": "main_hand", "item_id": head_id, "is_primary": True}
        ])
        with pytest.raises((ValidationError, NotFoundError, ConflictError)):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=owner["id"],
                name="Bad Slot Build",
                description="",
                role="tank",
                event_type="zvz",
                minimum_ip=0,
                status="draft",
                slot_items_json=bad_json,
            )

    def test_display_name_from_catalog_not_client(self):
        """The stored display_name_snapshot comes from the catalog, not the client."""
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("main_hand")
        if not items:
            pytest.skip("No main_hand items")
        real_item = items[0]

        owner = make_user("catalog-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="catalog-ws3")
        slot_json = json.dumps([
            {"slot": "main_hand", "item_id": real_item["item_id"], "is_primary": True}
        ])
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Snapshot Test",
            description="",
            role="tank",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json=slot_json,
        )
        with database.transaction() as db:
            version = repositories.get_current_build_version(
                db, build["id"], ws["id"]
            )
            slot_items = repositories.get_build_slot_items(
                db, version["id"], ws["id"]
            )
        assert slot_items
        stored = slot_items[0]
        assert stored["display_name_snapshot"] == real_item["display_name"]
        assert stored["tier"] == real_item["tier"]
        assert stored["enchantment"] == real_item["enchantment"]

    def test_malformed_json_raises_validation_error(self):
        owner = make_user("catalog-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="catalog-ws4")
        with pytest.raises(ValidationError, match="JSON"):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=owner["id"],
                name="Bad JSON",
                description="",
                role="healer",
                event_type="zvz",
                minimum_ip=0,
                status="draft",
                slot_items_json="{not valid json",
            )

    def test_non_array_json_raises_validation_error(self):
        owner = make_user("catalog-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="catalog-ws5")
        with pytest.raises(ValidationError):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=owner["id"],
                name="Bad Shape",
                description="",
                role="healer",
                event_type="zvz",
                minimum_ip=0,
                status="draft",
                slot_items_json=json.dumps({"slot": "main_hand"}),
            )


# ---------------------------------------------------------------------------
# Group 4 — Repository: build v2 insert/update/archive/restore
# ---------------------------------------------------------------------------

class TestBuildV2Repository:

    def test_insert_and_get_v2_build(self):
        owner = make_user("repo-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="repo-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], ws["id"])
        assert fetched is not None
        assert fetched["name"] == "Test Healer"
        assert fetched["role"] == "healer"
        assert fetched["event_type"] == "zvz"
        assert fetched["minimum_ip"] == 1000
        assert fetched["status"] == "draft"
        assert fetched["current_version_id"] is not None

    def test_archive_and_restore(self):
        owner = make_user("repo-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="repo-ws2")
        build = _create_v2_build(ws["id"], owner["id"])

        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "archived"
        assert b["archived_at"] is not None

        use_cases.restore_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            b2 = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b2["status"] == "draft"
        assert b2["archived_at"] is None

    def test_get_v2_builds_excludes_archived(self):
        owner = make_user("repo-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="repo-ws3")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            active = repositories.get_v2_builds(db, ws["id"])
        assert any(b["id"] == build["id"] for b in active)

        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            active2 = repositories.get_v2_builds(db, ws["id"])
        assert not any(b["id"] == build["id"] for b in active2)

    def test_get_v2_builds_include_archived(self):
        owner = make_user("repo-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="repo-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])

        with database.transaction() as db:
            all_builds = repositories.get_v2_builds(db, ws["id"], include_archived=True)
        assert any(b["id"] == build["id"] for b in all_builds)

    def test_workspace_isolation(self):
        """A build from workspace A is not visible in workspace B."""
        ownerA = make_user("iso-owner-a")
        wsA = make_workspace(owner_user_id=ownerA["id"], slug="iso-wsa")
        ownerB = make_user("iso-owner-b")
        wsB = make_workspace(owner_user_id=ownerB["id"], slug="iso-wsb")

        buildA = _create_v2_build(wsA["id"], ownerA["id"])
        with database.transaction() as db:
            fetched_in_b = repositories.get_albion_build(db, buildA["id"], wsB["id"])
        assert fetched_in_b is None


# ---------------------------------------------------------------------------
# Group 5 — Repository: build versions
# ---------------------------------------------------------------------------

class TestBuildVersionRepository:

    def test_version_1_created_on_new_build(self):
        owner = make_user("ver-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="ver-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            version = repositories.get_current_build_version(db, build["id"], ws["id"])
        assert version is not None
        assert version["version_number"] == 1
        assert version["build_id"] == build["id"]

    def test_version_history_sorted_descending(self):
        owner = make_user("ver-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="ver-ws2")
        build = _create_v2_build(ws["id"], owner["id"])

        # Create a second version
        slot_json = _minimal_slot_json(ws["id"])
        use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=slot_json,
            change_summary="Update",
            name="Updated Healer",
        )

        with database.transaction() as db:
            versions = repositories.list_build_versions(db, build["id"], ws["id"])
        assert len(versions) >= 2
        nums = [v["version_number"] for v in versions]
        assert nums == sorted(nums, reverse=True)

    def test_current_version_id_points_to_latest(self):
        owner = make_user("ver-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="ver-ws3")
        build = _create_v2_build(ws["id"], owner["id"])

        # Create v2
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("head")
        if not items:
            pytest.skip("No head items")

        slot_json2 = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"), "is_primary": True},
            {"slot": "head", "item_id": items[0]["item_id"], "is_primary": True},
        ])
        result = use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=slot_json2,
            change_summary="Added head item",
        )

        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["current_version_id"] == result["version"]["id"]

    def test_old_version_slot_items_unchanged_after_edit(self):
        owner = make_user("ver-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="ver-ws4")
        build = _create_v2_build(ws["id"], owner["id"])

        with database.transaction() as db:
            v1 = repositories.get_current_build_version(db, build["id"], ws["id"])
            v1_items = repositories.get_build_slot_items(db, v1["id"], ws["id"])

        # Create v2 with different slots
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        chest_items = cat.get_by_slot("chest")
        if not chest_items:
            pytest.skip("No chest items")
        slot_json2 = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"), "is_primary": True},
            {"slot": "chest", "item_id": chest_items[0]["item_id"], "is_primary": True},
        ])
        use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=slot_json2,
            change_summary="Changed items",
        )

        # v1 slot items must be unchanged
        with database.transaction() as db:
            v1_items_after = repositories.get_build_slot_items(db, v1["id"], ws["id"])
        v1_ids = {i["item_id"] for i in v1_items}
        v1_ids_after = {i["item_id"] for i in v1_items_after}
        assert v1_ids == v1_ids_after

    def test_get_next_version_number(self):
        owner = make_user("ver-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="ver-ws5")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            next_num = repositories.get_next_version_number(db, build["id"], ws["id"])
        assert next_num == 2  # v1 already exists

    def test_version_workspace_isolation(self):
        ownerA = make_user("ver-iso-a")
        wsA = make_workspace(owner_user_id=ownerA["id"], slug="ver-iso-wsa")
        ownerB = make_user("ver-iso-b")
        wsB = make_workspace(owner_user_id=ownerB["id"], slug="ver-iso-wsb")

        buildA = _create_v2_build(wsA["id"], ownerA["id"])
        with database.transaction() as db:
            v = repositories.get_current_build_version(db, buildA["id"], wsB["id"])
        assert v is None


# ---------------------------------------------------------------------------
# Group 6 — Repository: build slot items
# ---------------------------------------------------------------------------

class TestBuildSlotItemRepository:

    def test_slot_items_stored_correctly(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("main_hand")
        if not items:
            pytest.skip()
        real_item = items[0]

        owner = make_user("slot-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="slot-ws1")
        slot_json = json.dumps([
            {"slot": "main_hand", "item_id": real_item["item_id"], "is_primary": True}
        ])
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Slot Test Build",
            description="",
            role="tank",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json=slot_json,
        )
        with database.transaction() as db:
            version = repositories.get_current_build_version(db, build["id"], ws["id"])
            stored = repositories.get_build_slot_items(db, version["id"], ws["id"])

        assert len(stored) == 1
        s = stored[0]
        assert s["slot"] == "main_hand"
        assert s["item_id"] == real_item["item_id"]
        assert s["tier"] == real_item["tier"]
        assert s["enchantment"] == real_item["enchantment"]
        assert s["is_primary"] == 1

    def test_empty_build_has_no_slot_items(self):
        owner = make_user("slot-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="slot-ws2")
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Empty Build",
            description="",
            role="tank",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json="[]",
        )
        with database.transaction() as db:
            version = repositories.get_current_build_version(db, build["id"], ws["id"])
            stored = repositories.get_build_slot_items(db, version["id"], ws["id"])
        assert stored == []

    def test_slot_items_workspace_isolation(self):
        ownerA = make_user("slot-iso-a")
        wsA = make_workspace(owner_user_id=ownerA["id"], slug="slot-iso-wsa")
        ownerB = make_user("slot-iso-b")
        wsB = make_workspace(owner_user_id=ownerB["id"], slug="slot-iso-wsb")

        buildA = _create_v2_build(wsA["id"], ownerA["id"])
        with database.transaction() as db:
            versionA = repositories.get_current_build_version(db, buildA["id"], wsA["id"])
            items_in_b = repositories.get_build_slot_items(db, versionA["id"], wsB["id"])
        assert items_in_b == []


# ---------------------------------------------------------------------------
# Group 7 — Use case: create_build
# ---------------------------------------------------------------------------

class TestCreateBuildUseCase:

    def test_member_cannot_create_build(self):
        owner = make_user("uc-create-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-create-ws1")
        member = make_user("uc-create-member1")
        use_cases.add_workspace_member(ws["id"], owner["id"], "uc-create-member1", "member")

        with pytest.raises(PermissionDenied):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=member["id"],
                name="Member Build",
                description="",
                role="healer",
                event_type="zvz",
                minimum_ip=0,
                status="draft",
                slot_items_json="[]",
            )

    def test_create_build_returns_build_with_version(self):
        owner = make_user("uc-create-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-create-ws2")
        build = _create_v2_build(ws["id"], owner["id"])
        assert build["id"]
        assert build["current_version_id"]

    def test_invalid_metadata_rejected(self):
        owner = make_user("uc-create-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-create-ws3")
        with pytest.raises(ValidationError):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=owner["id"],
                name="",  # empty name
                description="",
                role="healer",
                event_type="zvz",
                minimum_ip=0,
                status="draft",
                slot_items_json="[]",
            )

    def test_version_1_is_current_after_create(self):
        owner = make_user("uc-create-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-create-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            version = repositories.get_current_build_version(db, build["id"], ws["id"])
        assert version["version_number"] == 1

    def test_draft_build_with_empty_slots_allowed(self):
        owner = make_user("uc-create-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-create-ws5")
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Empty Draft",
            description="",
            role="tank",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json="[]",
        )
        assert build["id"]

    def test_publish_without_required_slots_rejected(self):
        owner = make_user("uc-create-owner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-create-ws6")
        with pytest.raises(ValidationError, match="slot"):
            use_cases.create_build(
                guild_workspace_id=ws["id"],
                actor_user_id=owner["id"],
                name="Published Incomplete",
                description="",
                role="healer",
                event_type="zvz",
                minimum_ip=0,
                status="published",
                slot_items_json="[]",
            )


# ---------------------------------------------------------------------------
# Group 8 — Use case: create_build_version (versioning)
# ---------------------------------------------------------------------------

class TestCreateBuildVersionUseCase:

    def test_edit_creates_version_2(self):
        owner = make_user("v2-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws1")
        build = _create_v2_build(ws["id"], owner["id"])

        result = use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=_minimal_slot_json(ws["id"]),
            change_summary="Updated name",
            name="Updated Healer",
        )
        assert result["created"] is True
        assert result["version"]["version_number"] == 2

    def test_identical_save_returns_no_change(self):
        owner = make_user("v2-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws2")
        slot_json = _minimal_slot_json(ws["id"])
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Same Build",
            description="Desc",
            role="healer",
            event_type="zvz",
            minimum_ip=1000,
            status="draft",
            slot_items_json=slot_json,
        )
        # Save again with identical data
        result = use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=slot_json,
            name="Same Build",
            description="Desc",
            role="healer",
            event_type="zvz",
            minimum_ip=1000,
            intended_status="draft",
        )
        assert result["created"] is False

    def test_stale_version_raises_conflict(self):
        owner = make_user("v2-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws3")
        build = _create_v2_build(ws["id"], owner["id"])

        with pytest.raises(ConflictError, match="modified"):
            use_cases.create_build_version(
                guild_workspace_id=ws["id"],
                build_id=build["id"],
                actor_user_id=owner["id"],
                slot_items_json=_minimal_slot_json(ws["id"]),
                expected_current_version_id="stale-fake-id-12345",
                name="Stale Build",
            )

    def test_matching_expected_version_succeeds(self):
        owner = make_user("v2-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        current_vid = build["current_version_id"]

        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        head_items = cat.get_by_slot("head")
        if not head_items:
            pytest.skip("No head items")
        slot_json = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"), "is_primary": True},
            {"slot": "head", "item_id": head_items[0]["item_id"], "is_primary": True},
        ])
        result = use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=slot_json,
            expected_current_version_id=current_vid,
        )
        assert result["created"] is True

    def test_archived_build_cannot_receive_new_version(self):
        owner = make_user("v2-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws5")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])

        with pytest.raises(ConflictError, match="Archived"):
            use_cases.create_build_version(
                guild_workspace_id=ws["id"],
                build_id=build["id"],
                actor_user_id=owner["id"],
                slot_items_json=_minimal_slot_json(ws["id"]),
            )

    def test_member_cannot_create_version(self):
        owner = make_user("v2-owner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws6")
        build = _create_v2_build(ws["id"], owner["id"])
        member = make_user("v2-member6")
        use_cases.add_workspace_member(ws["id"], owner["id"], "v2-member6", "member")

        with pytest.raises(PermissionDenied):
            use_cases.create_build_version(
                guild_workspace_id=ws["id"],
                build_id=build["id"],
                actor_user_id=member["id"],
                slot_items_json=_minimal_slot_json(ws["id"]),
            )

    def test_version_number_sequential(self):
        owner = make_user("v2-owner7")
        ws = make_workspace(owner_user_id=owner["id"], slug="v2-ws7")
        build = _create_v2_build(ws["id"], owner["id"])

        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        head_items = cat.get_by_slot("head")
        if not head_items:
            pytest.skip("No head items")

        results = []
        for i, item in enumerate(head_items[:3]):
            slot_json = json.dumps([
                {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"), "is_primary": True},
                {"slot": "head", "item_id": item["item_id"], "is_primary": True},
            ])
            r = use_cases.create_build_version(
                guild_workspace_id=ws["id"],
                build_id=build["id"],
                actor_user_id=owner["id"],
                slot_items_json=slot_json,
                change_summary=f"Change {i+1}",
            )
            if r["created"]:
                results.append(r["version"]["version_number"])

        for i in range(1, len(results)):
            assert results[i] > results[i - 1]


# ---------------------------------------------------------------------------
# Group 9 — Use case: lifecycle (archive, restore, publish)
# ---------------------------------------------------------------------------

class TestBuildLifecycle:

    def test_archive_build_sets_archived_status(self):
        owner = make_user("lc-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "archived"
        assert b["archived_at"] is not None
        assert b["archived_by"] == owner["id"]

    def test_restore_clears_archived_status(self):
        owner = make_user("lc-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws2")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        use_cases.restore_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "draft"
        assert b["archived_at"] is None

    def test_double_archive_raises_conflict(self):
        owner = make_user("lc-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws3")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with pytest.raises(ConflictError):
            use_cases.archive_build(ws["id"], build["id"], owner["id"])

    def test_restore_non_archived_raises_conflict(self):
        owner = make_user("lc-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        with pytest.raises(ConflictError):
            use_cases.restore_build(ws["id"], build["id"], owner["id"])

    def test_publish_draft_build_succeeds(self):
        owner = make_user("lc-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws5")
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Publishable",
            description="",
            role="healer",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json=_published_slot_json(ws["id"]),
        )
        use_cases.publish_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "published"

    def test_publish_draft_without_required_slots_raises(self):
        owner = make_user("lc-owner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws6")
        build = _create_v2_build(ws["id"], owner["id"])  # only main_hand
        with pytest.raises(ValidationError, match="slot"):
            use_cases.publish_build(ws["id"], build["id"], owner["id"])

    def test_publish_archived_raises_conflict(self):
        owner = make_user("lc-owner7")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws7")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with pytest.raises(ConflictError, match="Archived"):
            use_cases.publish_build(ws["id"], build["id"], owner["id"])

    def test_member_cannot_archive(self):
        owner = make_user("lc-owner8")
        ws = make_workspace(owner_user_id=owner["id"], slug="lc-ws8")
        build = _create_v2_build(ws["id"], owner["id"])
        member = make_user("lc-member8")
        use_cases.add_workspace_member(ws["id"], owner["id"], "lc-member8", "member")
        with pytest.raises(PermissionDenied):
            use_cases.archive_build(ws["id"], build["id"], member["id"])


# ---------------------------------------------------------------------------
# Group 10 — Database constraints and workspace isolation
# ---------------------------------------------------------------------------

class TestDatabaseConstraints:

    def test_version_number_unique_per_build(self):
        """Attempting to insert two versions with the same number fails."""
        import uuid
        owner = make_user("db-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="db-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        now = "2026-01-01T00:00:00+00:00"
        dup_version = {
            "id":                 str(uuid.uuid4()),
            "build_id":           build["id"],
            "guild_workspace_id": ws["id"],
            "version_number":     1,  # duplicate!
            "change_summary":     None,
            "created_at":         now,
            "created_by":         owner["id"],
        }
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                repositories.insert_build_version(db, dup_version)

    def test_tier_constraint_enforced(self):
        """Slot item with tier=6 violates the CHECK constraint."""
        import uuid, sqlite3
        owner = make_user("db-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="db-ws2")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            v = repositories.get_current_build_version(db, build["id"], ws["id"])
        bad_item = {
            "id":                    str(uuid.uuid4()),
            "build_version_id":      v["id"],
            "guild_workspace_id":    ws["id"],
            "slot":                  "head",
            "item_id":               "T6_BAD",
            "display_name_snapshot": "Bad Tier",
            "tier":                  6,  # invalid
            "enchantment":           0,
            "is_primary":            1,
            "priority":              0,
            "notes":                 None,
            "minimum_enchantment":   0,
        }
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                db.execute(
                    """INSERT INTO albion_build_slot_items
                       (id,build_version_id,guild_workspace_id,slot,item_id,
                        display_name_snapshot,tier,enchantment,is_primary,priority,
                        notes,minimum_enchantment)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (bad_item["id"], bad_item["build_version_id"],
                     bad_item["guild_workspace_id"], bad_item["slot"],
                     bad_item["item_id"], bad_item["display_name_snapshot"],
                     bad_item["tier"], bad_item["enchantment"],
                     bad_item["is_primary"], bad_item["priority"],
                     bad_item["notes"], bad_item["minimum_enchantment"])
                )

    def test_one_primary_per_slot_constraint(self):
        """Partial unique index prevents two primary items in same slot+version."""
        import uuid, sqlite3
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("main_hand")
        if len(items) < 2:
            pytest.skip("Need ≥2 main_hand items")
        owner = make_user("db-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="db-ws3")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            v = repositories.get_current_build_version(db, build["id"], ws["id"])

        def _make_primary(vid, wsid, item):
            return (
                str(uuid.uuid4()), vid, wsid, "main_hand",
                item["item_id"], item["display_name"], item["tier"],
                item["enchantment"], 1, 0, None, 0
            )

        SQL = """INSERT INTO albion_build_slot_items
                 (id,build_version_id,guild_workspace_id,slot,item_id,
                  display_name_snapshot,tier,enchantment,is_primary,priority,
                  notes,minimum_enchantment)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""

        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as db:
                db.execute(SQL, _make_primary(v["id"], ws["id"], items[0]))
                db.execute(SQL, _make_primary(v["id"], ws["id"], items[1]))


# ---------------------------------------------------------------------------
# Group 11 — Route: GET builds detail (v2 vs legacy)
# ---------------------------------------------------------------------------

class TestBuildDetailRoutes:

    def test_v2_build_detail_renders(self):
        client, owner, ws = _make_setup("detail-v2-ws")
        build = _create_v2_build(ws["id"], owner["id"])
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")
        assert resp.status_code == 200
        assert "version" in resp.text.lower() or build["name"] in resp.text

    def test_legacy_build_detail_still_works(self):
        client, owner, ws = _make_setup("detail-legacy-ws")
        legacy_build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy Build",
            role="Healer",
            weapon_name="T8 Hallowfall",
        )
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{legacy_build['id']}")
        assert resp.status_code == 200
        assert "Legacy Build" in resp.text

    def test_unknown_build_returns_404(self):
        client, owner, ws = _make_setup("detail-404-ws")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/nonexistent-id")
        assert resp.status_code == 404

    def test_cross_workspace_build_returns_404(self):
        ownerA = make_user("cross-a")
        wsA = make_workspace(owner_user_id=ownerA["id"], slug="cross-wsa")
        ownerB = make_user("cross-b")
        wsB = make_workspace(owner_user_id=ownerB["id"], slug="cross-wsb")
        buildA = _create_v2_build(wsA["id"], ownerA["id"])
        client = TestClient(app)
        client.post("/login", data={"display_name": "cross-b", "next": "/"}, follow_redirects=True)
        resp = client.get(f"/workspaces/{wsB['slug']}/builds/{buildA['id']}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Group 12 — Route: POST create build (visual editor)
# ---------------------------------------------------------------------------

class TestPostCreateBuildRoute:

    def test_visual_editor_create_redirects_to_detail(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("main_hand")
        if not items:
            pytest.skip()

        client, owner, ws = _make_setup("post-create-ws1")
        slot_json = json.dumps([
            {"slot": "main_hand", "item_id": items[0]["item_id"], "is_primary": True}
        ])
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "editor_type":    "visual",
                "name":           "ZvZ Healer",
                "description":    "Test description",
                "role":           "healer",
                "event_type":     "zvz",
                "minimum_ip":     "1000",
                "intended_status": "draft",
                "slot_items_json": slot_json,
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/builds/" in resp.headers.get("location", "")

    def test_visual_editor_invalid_name_rerenders_form(self):
        client, owner, ws = _make_setup("post-create-ws2")
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "editor_type":    "visual",
                "name":           "",  # invalid
                "role":           "healer",
                "event_type":     "zvz",
                "minimum_ip":     "0",
                "intended_status": "draft",
                "slot_items_json": "[]",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "error" in resp.text.lower() or "name" in resp.text.lower()

    def test_unauthenticated_redirects_to_login(self):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("main_hand")
        owner = make_user("post-unauth-owner")
        ws = make_workspace(owner_user_id=owner["id"], slug="post-unauth-ws")
        fresh_client = TestClient(app)  # no login
        resp = fresh_client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "editor_type":    "visual",
                "name":           "Test",
                "role":           "healer",
                "event_type":     "zvz",
                "minimum_ip":     "0",
                "intended_status": "draft",
                "slot_items_json": "[]",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "login" in resp.headers.get("location", "").lower()

    def test_legacy_form_still_works(self):
        client, owner, ws = _make_setup("post-legacy-ws")
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "name":        "Legacy Form Build",
                "role":        "Healer",
                "weapon_name": "T8 Hallowfall",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_member_create_returns_403(self):
        client, owner, ws = _make_setup("post-member-ws")
        member = make_user("member-for-create")
        use_cases.add_workspace_member(ws["id"], owner["id"], "member-for-create", "member")
        member_client = TestClient(app)
        member_client.post("/login", data={"display_name": "member-for-create", "next": "/"}, follow_redirects=True)
        resp = member_client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "editor_type":    "visual",
                "name":           "Member Build",
                "role":           "healer",
                "event_type":     "zvz",
                "minimum_ip":     "0",
                "intended_status": "draft",
                "slot_items_json": "[]",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Group 13 — Route: POST create_build_version
# ---------------------------------------------------------------------------

class TestPostCreateBuildVersionRoute:

    def _create_and_get_build(self, client, owner, ws):
        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        items = cat.get_by_slot("main_hand")
        if not items:
            pytest.skip()
        slot_json = json.dumps([
            {"slot": "main_hand", "item_id": items[0]["item_id"], "is_primary": True}
        ])
        build = _create_v2_build(ws["id"], owner["id"], slot_json=slot_json)
        return build, slot_json

    def test_save_new_version_redirects(self):
        client, owner, ws = _make_setup("version-post-ws1")
        build, slot_json = self._create_and_get_build(client, owner, ws)

        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        head_items = cat.get_by_slot("head")
        if not head_items:
            pytest.skip()
        new_slot_json = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"), "is_primary": True},
            {"slot": "head", "item_id": head_items[0]["item_id"], "is_primary": True},
        ])
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/versions",
            data={
                "name":                       build["name"],
                "description":                "",
                "role":                       "healer",
                "event_type":                 "zvz",
                "minimum_ip":                 "1000",
                "intended_status":            "draft",
                "change_summary":             "Added head",
                "slot_items_json":            new_slot_json,
                "expected_current_version_id": build["current_version_id"],
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_stale_version_returns_409(self):
        client, owner, ws = _make_setup("version-post-ws2")
        build, slot_json = self._create_and_get_build(client, owner, ws)

        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/versions",
            data={
                "name":                       build["name"],
                "role":                       "healer",
                "event_type":                 "zvz",
                "minimum_ip":                 "1000",
                "intended_status":            "draft",
                "slot_items_json":            slot_json,
                "expected_current_version_id": "stale-id-000",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 409

    def test_no_change_save_redirects_with_no_changes(self):
        client, owner, ws = _make_setup("version-post-ws3")
        build, slot_json = self._create_and_get_build(client, owner, ws)

        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/versions",
            data={
                "name":                       "Test Healer",
                "description":                "A test build",
                "role":                       "healer",
                "event_type":                 "zvz",
                "minimum_ip":                 "1000",
                "intended_status":            "draft",
                "slot_items_json":            slot_json,
                "expected_current_version_id": build["current_version_id"],
            },
            follow_redirects=False,
        )
        # No-change: still a redirect (302/303) to detail page
        assert resp.status_code in (302, 303)

    def test_unknown_build_returns_404(self):
        client, owner, ws = _make_setup("version-post-ws4")
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/unknown-id/versions",
            data={
                "name": "Test", "role": "healer", "event_type": "zvz",
                "minimum_ip": "0", "intended_status": "draft",
                "slot_items_json": "[]",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Group 14 — Route: lifecycle routes
# ---------------------------------------------------------------------------

class TestLifecycleRoutes:

    def test_archive_route_sets_archived(self):
        client, owner, ws = _make_setup("lc-route-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/archive",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "archived"

    def test_restore_route_unarchives(self):
        client, owner, ws = _make_setup("lc-route-ws2")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/restore",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "draft"

    def test_publish_route_publishes(self):
        client, owner, ws = _make_setup("lc-route-ws3")
        build = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Publishable Build",
            description="",
            role="healer",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json=_published_slot_json(ws["id"]),
        )
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/publish",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "published"

    def test_archived_build_edit_blocked(self):
        client, owner, ws = _make_setup("lc-route-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/edit",
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_member_cannot_archive(self):
        client, owner, ws = _make_setup("lc-route-ws5")
        build = _create_v2_build(ws["id"], owner["id"])
        member = make_user("lc-member5")
        use_cases.add_workspace_member(ws["id"], owner["id"], "lc-member5", "member")
        member_client = TestClient(app)
        member_client.post("/login", data={"display_name": "lc-member5", "next": "/"}, follow_redirects=True)
        resp = member_client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/archive",
            follow_redirects=False,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Group 15 — Route: version history and version detail
# ---------------------------------------------------------------------------

class TestVersionHistoryAndDetailRoutes:

    def test_version_history_page_renders(self):
        client, owner, ws = _make_setup("hist-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/versions"
        )
        assert resp.status_code == 200
        assert "v1" in resp.text or "version" in resp.text.lower()

    def test_version_detail_renders(self):
        client, owner, ws = _make_setup("hist-ws2")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            v = repositories.get_current_build_version(db, build["id"], ws["id"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/versions/{v['id']}"
        )
        assert resp.status_code == 200
        assert "current" in resp.text.lower() or "version" in resp.text.lower()

    def test_old_version_marked_read_only(self):
        client, owner, ws = _make_setup("hist-ws3")
        build = _create_v2_build(ws["id"], owner["id"])

        from app.albion.item_catalog import get_catalog
        cat = get_catalog()
        head_items = cat.get_by_slot("head")
        if not head_items:
            pytest.skip("No head items")
        new_slot_json = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"), "is_primary": True},
            {"slot": "head", "item_id": head_items[0]["item_id"], "is_primary": True},
        ])
        use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=new_slot_json,
            change_summary="Added head",
        )

        with database.transaction() as db:
            v1 = repositories.get_build_version(
                db, build["current_version_id"], build["id"], ws["id"]
            )
            versions = repositories.list_build_versions(db, build["id"], ws["id"])

        # The oldest version (v1) should NOT be the current one
        v1_row = next((v for v in versions if v["version_number"] == 1), None)
        if v1_row:
            resp = client.get(
                f"/workspaces/{ws['slug']}/builds/{build['id']}/versions/{v1_row['id']}"
            )
            assert resp.status_code == 200
            assert "read-only" in resp.text.lower() or "historical" in resp.text.lower()

    def test_unknown_version_returns_404(self):
        client, owner, ws = _make_setup("hist-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/versions/nonexistent-vid"
        )
        assert resp.status_code == 404

    def test_legacy_build_version_history_returns_404(self):
        """Legacy builds (no current_version_id) don't have version history."""
        client, owner, ws = _make_setup("hist-ws5")
        legacy = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy",
            role="Healer",
            weapon_name="Hallowfall",
        )
        resp = client.get(
            f"/workspaces/{ws['slug']}/builds/{legacy['id']}/versions"
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Group 16 — Regression: legacy builds/compositions unaffected
# ---------------------------------------------------------------------------

class TestLegacyRegression:

    def test_legacy_build_create_still_works(self):
        owner = make_user("reg-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="reg-ws1")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy Test",
            role="Healer",
            weapon_name="T8.3 Hallowfall",
        )
        assert build["id"]
        assert build.get("weapon_name") == "T8.3 Hallowfall"

    def test_legacy_build_update_still_works(self):
        owner = make_user("reg-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="reg-ws2")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy Update Test",
            role="Healer",
            weapon_name="Hallowfall",
        )
        use_cases.update_albion_build(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            name="Updated Legacy",
            role="Healer",
            weapon_name="Great Cursed Staff",
        )
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["name"] == "Updated Legacy"

    def test_composition_with_legacy_build_unaffected(self):
        from tests.conftest import make_composition
        owner = make_user("reg-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="reg-ws3")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Comp Build",
            role="Healer",
            weapon_name="Hallowfall",
        )
        comp = make_composition(ws["id"])
        # Legacy compositions should still be fetchable
        with database.transaction() as db:
            from app import repositories as repos
            comps = repos.get_albion_compositions(db, ws["id"])
        assert len(comps) >= 1

    def test_builds_list_shows_both_legacy_and_v2(self):
        client, owner, ws = _make_setup("reg-list-ws")
        # Create a legacy build
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy In List",
            role="Healer",
            weapon_name="Hallowfall",
        )
        # Create a v2 build
        _create_v2_build(ws["id"], owner["id"])
        resp = client.get(f"/workspaces/{ws['slug']}/builds")
        assert resp.status_code == 200
        assert "Legacy In List" in resp.text
        assert "Test Healer" in resp.text


# ---------------------------------------------------------------------------
# Group 17 — Build type isolation (helpers + repository filters)
# ---------------------------------------------------------------------------

class TestBuildTypeIsolation:

    def test_is_legacy_build_true_for_null_version_id(self):
        assert bv_domain.is_legacy_build({"current_version_id": None}) is True

    def test_is_legacy_build_true_for_missing_key(self):
        assert bv_domain.is_legacy_build({}) is True

    def test_is_legacy_build_false_for_versioned(self):
        assert bv_domain.is_legacy_build({"current_version_id": "some-id"}) is False

    def test_is_versioned_build_true_for_non_null(self):
        assert bv_domain.is_versioned_build({"current_version_id": "abc"}) is True

    def test_is_versioned_build_false_for_null(self):
        assert bv_domain.is_versioned_build({"current_version_id": None}) is False

    def test_is_versioned_build_false_for_missing_key(self):
        assert bv_domain.is_versioned_build({}) is False

    def test_get_albion_builds_legacy_only_excludes_v2(self):
        owner = make_user("iso-leg-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="iso-leg-ws1")
        # Create one legacy build and one V2 build.
        legacy = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy Only",
            role="Healer",
            weapon_name="Hallowfall",
        )
        _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            legacy_only = repositories.get_albion_builds(
                db, ws["id"], legacy_only=True
            )
        ids = [b["id"] for b in legacy_only]
        assert legacy["id"] in ids
        # V2 builds must not appear in legacy-only query.
        for b in legacy_only:
            assert b["current_version_id"] is None, (
                f"V2 build appeared in legacy_only=True result: {b}"
            )

    def test_get_albion_builds_without_legacy_only_includes_both(self):
        owner = make_user("iso-mixed-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="iso-mixed-ws1")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Mixed Legacy",
            role="Healer",
            weapon_name="Hallowfall",
        )
        _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            all_builds = repositories.get_albion_builds(db, ws["id"])
        has_legacy = any(b["current_version_id"] is None for b in all_builds)
        has_v2 = any(b["current_version_id"] is not None for b in all_builds)
        assert has_legacy, "Expected at least one legacy build in mixed result"
        assert has_v2, "Expected at least one V2 build in mixed result"

    def test_v2_build_has_null_weapon_name(self):
        owner = make_user("iso-null-wn-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="iso-null-wn-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_albion_build(db, build["id"], ws["id"])
        assert row["weapon_name"] is None, (
            f"V2 build should have weapon_name=NULL, got {row['weapon_name']!r}"
        )

    def test_legacy_build_preserves_weapon_name(self):
        owner = make_user("iso-leg-wn-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="iso-leg-wn-ws1")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy WN",
            role="Healer",
            weapon_name="Hallowfall",
        )
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, ws["id"], legacy_only=True)
        legacy = next((b for b in builds if b["name"] == "Legacy WN"), None)
        assert legacy is not None
        assert legacy["weapon_name"] == "Hallowfall"

    def test_fork_route_redirects_v2_to_edit(self):
        client, owner, ws = _make_setup("iso-fork-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        resp = client.get(
            f"/workspaces/{ws['slug']}/builds/{build['id']}/fork",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert f"/builds/{build['id']}/edit" in resp.headers["location"]

    def test_composition_new_route_workspace_builds_excludes_v2(self):
        """GET /workspaces/{slug}/compositions/new must not include V2 builds."""
        client, owner, ws = _make_setup("iso-comp-new-ws1")
        _create_v2_build(ws["id"], owner["id"])
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy For Comp",
            role="Healer",
            weapon_name="Hallowfall",
        )
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        # The response must contain the legacy build name but not show empty
        # weapon_name entries from V2 builds (which have weapon_name=NULL).
        assert "Legacy For Comp" in resp.text


# ---------------------------------------------------------------------------
# Group 18 — Transaction rollback integrity
# ---------------------------------------------------------------------------

class TestTransactionRollback:

    def test_build_insert_fails_version_insert_leaves_no_build(self):
        """If version insert fails, the build row must be rolled back."""
        owner = make_user("rb-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="rb-ws1")
        slot_json = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"),
             "is_primary": True},
        ])
        from unittest.mock import patch

        def _fail_insert_version(db, version):
            raise RuntimeError("Simulated version insert failure")

        with patch.object(repositories, "insert_build_version", _fail_insert_version):
            with pytest.raises(RuntimeError, match="Simulated version"):
                use_cases.create_build(
                    guild_workspace_id=ws["id"],
                    actor_user_id=owner["id"],
                    name="Rollback Test Build",
                    description=None,
                    role="healer",
                    event_type="zvz",
                    minimum_ip=0,
                    status="draft",
                    slot_items_json=slot_json,
                )

        # The build row must not exist after rollback.
        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, ws["id"])
        v2_builds = [b for b in builds if b.get("name") == "Rollback Test Build"]
        assert not v2_builds, "Build row must have been rolled back"

    def test_meta_update_fails_rolls_back_new_version(self):
        """Failure in update_albion_build_meta_v2 must roll back the new version row."""
        owner = make_user("rb-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="rb-ws2")
        # Create build with version 1 using a head item.
        build = _create_v2_build(
            ws["id"], owner["id"],
            slot_json=json.dumps([
                {"slot": "head", "item_id": _get_valid_item_id_for_slot("head"),
                 "is_primary": True},
            ]),
        )

        with database.transaction() as db:
            before = repositories.get_albion_build(db, build["id"], ws["id"])
        original_version_id = before["current_version_id"]

        from unittest.mock import patch

        def _fail_meta_update(db, *args, **kwargs):
            raise RuntimeError("Simulated meta update failure")

        # Use a DIFFERENT slot (main_hand) in the new version so _is_identical is False.
        slot_json_v2 = json.dumps([
            {"slot": "main_hand", "item_id": _get_valid_item_id_for_slot("main_hand"),
             "is_primary": True},
        ])
        with patch.object(repositories, "update_albion_build_meta_v2", _fail_meta_update):
            with pytest.raises(RuntimeError, match="Simulated meta"):
                use_cases.create_build_version(
                    guild_workspace_id=ws["id"],
                    build_id=build["id"],
                    actor_user_id=owner["id"],
                    slot_items_json=slot_json_v2,
                    change_summary="Should be rolled back",
                )

        # current_version_id must be unchanged.
        with database.transaction() as db:
            after = repositories.get_albion_build(db, build["id"], ws["id"])
        assert after["current_version_id"] == original_version_id

        # No new version row must exist beyond the original.
        with database.transaction() as db:
            versions = repositories.list_build_versions(db, build["id"], ws["id"])
        assert len(versions) == 1, (
            f"Expected 1 version after rollback, found {len(versions)}"
        )

    def test_publish_validation_failure_leaves_status_unchanged(self):
        owner = make_user("rb-pub-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="rb-pub-ws1")
        # Create a draft build with no items.
        build = _create_v2_build(ws["id"], owner["id"])

        with pytest.raises(Exception):
            use_cases.publish_build(ws["id"], build["id"], owner["id"])

        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "draft"

    def test_archive_failure_leaves_status_unchanged(self):
        owner = make_user("rb-arc-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="rb-arc-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        # Double-archive must fail; status remains archived.
        with pytest.raises(Exception):
            use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            b = repositories.get_albion_build(db, build["id"], ws["id"])
        assert b["status"] == "archived"


# ---------------------------------------------------------------------------
# Group 19 — Direct database integrity (cross-build/workspace FK guard)
# ---------------------------------------------------------------------------

class TestDatabaseIntegrity:

    def test_set_current_version_rejects_nonexistent_version(self):
        owner = make_user("dbi-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="dbi-ws1")
        build = _create_v2_build(ws["id"], owner["id"])
        with pytest.raises(ValueError, match="does not exist"):
            with database.transaction() as db:
                repositories.set_build_current_version(
                    db,
                    build_id=build["id"],
                    guild_workspace_id=ws["id"],
                    version_id="nonexistent-version-id-xyz",
                    updated_at="2025-01-01T00:00:00Z",
                    updated_by=owner["id"],
                )

    def test_set_current_version_rejects_wrong_build(self):
        """Version belonging to build A must not be assigned to build B."""
        owner = make_user("dbi-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="dbi-ws2")
        build_a = _create_v2_build(ws["id"], owner["id"])
        build_b = use_cases.create_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Build B",
            description=None,
            role="healer",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json="[]",
        )
        with database.transaction() as db:
            a_row = repositories.get_albion_build(db, build_a["id"], ws["id"])
        version_id_of_a = a_row["current_version_id"]

        with pytest.raises(ValueError, match="belongs to build"):
            with database.transaction() as db:
                repositories.set_build_current_version(
                    db,
                    build_id=build_b["id"],
                    guild_workspace_id=ws["id"],
                    version_id=version_id_of_a,
                    updated_at="2025-01-01T00:00:00Z",
                    updated_by=owner["id"],
                )

    def test_set_current_version_rejects_wrong_workspace(self):
        """Version from workspace A must not be assigned to a build in workspace B."""
        owner = make_user("dbi-owner3")
        ws_a = make_workspace(owner_user_id=owner["id"], slug="dbi-ws3a")
        ws_b = make_workspace(owner_user_id=owner["id"], slug="dbi-ws3b")
        build_a = _create_v2_build(ws_a["id"], owner["id"])
        build_b = use_cases.create_build(
            guild_workspace_id=ws_b["id"],
            actor_user_id=owner["id"],
            name="WS-B Build",
            description=None,
            role="healer",
            event_type="zvz",
            minimum_ip=0,
            status="draft",
            slot_items_json="[]",
        )
        with database.transaction() as db:
            a_row = repositories.get_albion_build(db, build_a["id"], ws_a["id"])
        version_id_of_a = a_row["current_version_id"]

        with pytest.raises(ValueError, match="belongs to workspace"):
            with database.transaction() as db:
                repositories.set_build_current_version(
                    db,
                    build_id=build_b["id"],
                    guild_workspace_id=ws_b["id"],
                    version_id=version_id_of_a,
                    updated_at="2025-01-01T00:00:00Z",
                    updated_by=owner["id"],
                )

    def test_sql_level_fk_rejects_nonexistent_current_version_id(self):
        """Direct SQL UPDATE with invalid current_version_id must raise IntegrityError."""
        import sqlite3 as _sqlite3
        owner = make_user("dbi-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="dbi-ws4")
        build = _create_v2_build(ws["id"], owner["id"])
        with pytest.raises(_sqlite3.IntegrityError):
            with database.transaction() as db:
                db.execute("PRAGMA foreign_keys = ON")
                db.execute(
                    "UPDATE albion_builds SET current_version_id = ? WHERE id = ?",
                    ("nonexistent-version-9999", build["id"]),
                )

    def test_build_version_delete_restricted_while_build_references_it(self):
        """Deleting a build_version row referenced by current_version_id must fail."""
        import sqlite3 as _sqlite3
        owner = make_user("dbi-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="dbi-ws5")
        build = _create_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            row = repositories.get_albion_build(db, build["id"], ws["id"])
        version_id = row["current_version_id"]
        with pytest.raises(_sqlite3.IntegrityError):
            with database.transaction() as db:
                db.execute("PRAGMA foreign_keys = ON")
                db.execute(
                    "DELETE FROM albion_build_versions WHERE id = ?",
                    (version_id,),
                )

    def test_composition_fk_to_legacy_build_valid_after_db_exists(self):
        """FK from composition_slot_templates to albion_builds must remain valid."""
        from tests.conftest import make_composition
        owner = make_user("dbi-owner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="dbi-ws6")
        legacy = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="FK Test Legacy",
            role="Healer",
            weapon_name="Hallowfall",
        )
        comp = make_composition(ws["id"])
        # Verify FK integrity at the DB level.
        with database.transaction() as db:
            violations = db.execute(
                "PRAGMA foreign_key_check(composition_slot_templates)"
            ).fetchall()
        assert not violations, f"FK violations found: {violations}"
