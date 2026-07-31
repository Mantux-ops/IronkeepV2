"""
Library builds as the source for composition slots.

Before this slice the composition slot picker was filtered to legacy flat builds,
so every build produced by the visual editor was invisible there and officers had
to retype the loadout as text.  Slots now draw from the library — legacy builds
plus published versioned ones — and a versioned build's equipment is flattened
from its current version into the slot snapshot.

Covers:
  Group 1 — Domain: item label formatting + slot item flattening
  Group 2 — Repository: get_composition_eligible_builds filtering
  Group 3 — Use case: list_composition_build_options resolves loadouts
  Group 4 — Attaching a versioned build snapshots its equipment onto the slot
  Group 5 — A slot may be submitted with only an albion_build_id
  Group 6 — Build Snapshot Invariant holds for versioned builds
  Group 7 — Routes render the picker and read-only derived fields

Intentionally NOT covered here:
  - CSS / visual rendering
  - The planner's inline build edit, which stays free-typed by design
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import build_version as bv_domain
from app.errors import ValidationError
from app.main import app

from tests.conftest import make_composition, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _full_loadout_json() -> str:
    """Slot items covering every slot a published build requires, plus an off-hand."""
    from app.albion.item_catalog import get_catalog

    cat = get_catalog()
    items = []
    for slot in ("main_hand", "off_hand", "head", "chest", "shoes", "cape", "food", "potion"):
        pool = [
            e for e in cat.get_by_slot(slot)
            if slot != "main_hand" or not e["is_two_handed"]
        ]
        if not pool:
            pytest.skip(f"No {slot} items in catalog")
        items.append({"slot": slot, "item_id": pool[0]["item_id"], "is_primary": True})
    return json.dumps(items)


def _make_v2_build(
    ws_id: str,
    actor_id: str,
    *,
    name: str = "Editor Healer",
    role: str = "healer",
    status: str = "published",
) -> dict:
    return use_cases.create_build(
        guild_workspace_id=ws_id,
        actor_user_id=actor_id,
        name=name,
        description="Made in the visual editor",
        role=role,
        event_type="zvz",
        minimum_ip=1400,
        status=status,
        slot_items_json=_full_loadout_json(),
        change_summary="Initial version",
    )


def _expected_labels(build_id: str, ws_id: str) -> dict[str, str]:
    """The flat equipment labels a slot should snapshot for a versioned build."""
    with database.transaction() as db:
        version = repositories.get_current_build_version(db, build_id, ws_id)
        slot_items = repositories.get_build_slot_items(db, version["id"], ws_id)
    return bv_domain.flatten_slot_items_to_legacy_fields(slot_items)


# ---------------------------------------------------------------------------
# Group 1 — Domain: label formatting + flattening
# ---------------------------------------------------------------------------

class TestItemLabelFormatting:

    def test_tier_and_enchantment_prefix(self):
        assert bv_domain.format_item_label(8, 3, "Hallowfall") == "T8.3 Hallowfall"

    def test_base_enchantment_renders_as_zero(self):
        assert bv_domain.format_item_label(7, 0, "Great Axe") == "T7.0 Great Axe"

    def test_missing_enchantment_treated_as_base(self):
        assert bv_domain.format_item_label(8, None, "Bedrock Mace") == "T8.0 Bedrock Mace"

    def test_missing_tier_falls_back_to_bare_name(self):
        assert bv_domain.format_item_label(None, None, "Hallowfall") == "Hallowfall"

    def test_empty_name_yields_empty_label(self):
        assert bv_domain.format_item_label(8, 3, "   ") == ""


class TestFlattenSlotItems:

    def test_maps_slots_onto_legacy_field_names(self):
        flat = bv_domain.flatten_slot_items_to_legacy_fields([
            {"slot": "main_hand", "tier": 8, "enchantment": 3,
             "display_name_snapshot": "Hallowfall", "is_primary": 1},
            {"slot": "chest", "tier": 8, "enchantment": 2,
             "display_name_snapshot": "Cleric Robe", "is_primary": 1},
        ])
        assert flat == {
            "weapon_name": "T8.3 Hallowfall",
            "armor_name":  "T8.2 Cleric Robe",
        }

    def test_alternates_are_ignored(self):
        """Only the primary item per slot fits the single-value legacy shape."""
        flat = bv_domain.flatten_slot_items_to_legacy_fields([
            {"slot": "main_hand", "tier": 8, "enchantment": 3,
             "display_name_snapshot": "Hallowfall", "is_primary": 1},
            {"slot": "main_hand", "tier": 8, "enchantment": 1,
             "display_name_snapshot": "Blight Staff", "is_primary": 0},
        ])
        assert flat == {"weapon_name": "T8.3 Hallowfall"}

    def test_bag_and_mount_have_no_legacy_field(self):
        flat = bv_domain.flatten_slot_items_to_legacy_fields([
            {"slot": "bag", "tier": 8, "enchantment": 0,
             "display_name_snapshot": "Bag", "is_primary": 1},
            {"slot": "mount", "tier": 8, "enchantment": 0,
             "display_name_snapshot": "Swiftclaw", "is_primary": 1},
        ])
        assert flat == {}

    def test_absent_slots_are_omitted_not_blanked(self):
        flat = bv_domain.flatten_slot_items_to_legacy_fields([])
        assert flat == {}

    def test_every_legacy_field_is_a_slot_snapshot_column(self):
        assert set(bv_domain.LEGACY_SLOT_FIELDS.values()) == {
            "weapon_name", "offhand_name", "head_name", "armor_name",
            "shoes_name", "cape_name", "food_name", "potion_name",
        }


# ---------------------------------------------------------------------------
# Group 2 — Repository: eligibility filtering
# ---------------------------------------------------------------------------

class TestCompositionEligibleBuilds:

    def test_published_versioned_build_is_eligible(self):
        owner = make_user("elig-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="elig-ws1")
        build = _make_v2_build(ws["id"], owner["id"])
        with database.transaction() as db:
            rows = repositories.get_composition_eligible_builds(db, ws["id"])
        assert [r["id"] for r in rows] == [build["id"]]

    def test_draft_versioned_build_is_withheld(self):
        """A half-finished loadout must not be attachable to an operation."""
        owner = make_user("elig-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="elig-ws2")
        _make_v2_build(ws["id"], owner["id"], status="draft")
        with database.transaction() as db:
            rows = repositories.get_composition_eligible_builds(db, ws["id"])
        assert rows == []

    def test_archived_versioned_build_is_excluded(self):
        owner = make_user("elig-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="elig-ws3")
        build = _make_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])
        with database.transaction() as db:
            rows = repositories.get_composition_eligible_builds(db, ws["id"])
        assert rows == []

    def test_legacy_build_is_eligible_regardless_of_status(self):
        """Legacy rows carry the default 'draft' status but predate the concept."""
        owner = make_user("elig-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="elig-ws4")
        legacy = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy Tombhammer",
            role="Tank",
            weapon_name="T8.3 Tombhammer",
        )
        with database.transaction() as db:
            rows = repositories.get_composition_eligible_builds(db, ws["id"])
        assert [r["id"] for r in rows] == [legacy["id"]]

    def test_retired_legacy_build_is_excluded(self):
        owner = make_user("elig-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="elig-ws5")
        legacy = use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Retired Build",
            role="Tank",
            weapon_name="T8.3 Tombhammer",
        )
        use_cases.retire_albion_build(ws["id"], legacy["id"], owner["id"])
        with database.transaction() as db:
            rows = repositories.get_composition_eligible_builds(db, ws["id"])
        assert rows == []

    def test_other_workspace_builds_are_not_returned(self):
        owner_a = make_user("elig-owner6a")
        ws_a = make_workspace(owner_user_id=owner_a["id"], slug="elig-ws6a")
        owner_b = make_user("elig-owner6b")
        ws_b = make_workspace(owner_user_id=owner_b["id"], slug="elig-ws6b")
        _make_v2_build(ws_b["id"], owner_b["id"])
        with database.transaction() as db:
            rows = repositories.get_composition_eligible_builds(db, ws_a["id"])
        assert rows == []


# ---------------------------------------------------------------------------
# Group 3 — Use case: build options carry resolved loadouts
# ---------------------------------------------------------------------------

class TestListCompositionBuildOptions:

    def test_versioned_build_option_carries_flat_equipment(self):
        owner = make_user("opt-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="opt-ws1")
        build = _make_v2_build(ws["id"], owner["id"])
        expected = _expected_labels(build["id"], ws["id"])
        with database.transaction() as db:
            options = use_cases.list_composition_build_options(db, ws["id"])
        assert len(options) == 1
        option = options[0]
        assert option["weapon_name"] == expected["weapon_name"]
        assert option["armor_name"] == expected["armor_name"]
        assert option["weapon_name"].startswith("T")

    def test_versioned_build_role_is_human_readable(self):
        """Slots carry display roles; the picker must not leak enum keys."""
        owner = make_user("opt-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="opt-ws2")
        _make_v2_build(ws["id"], owner["id"], role="melee_dps")
        with database.transaction() as db:
            options = use_cases.list_composition_build_options(db, ws["id"])
        assert options[0]["role"] == bv_domain.ROLE_DISPLAY["melee_dps"]

    def test_legacy_build_option_passes_through_unchanged(self):
        owner = make_user("opt-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="opt-ws3")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            name="Legacy Lute",
            role="Support",
            weapon_name="T8.3 Lute",
        )
        with database.transaction() as db:
            options = use_cases.list_composition_build_options(db, ws["id"])
        assert options[0]["weapon_name"] == "T8.3 Lute"
        assert options[0]["role"] == "Support"

    def test_empty_workspace_returns_no_options(self):
        owner = make_user("opt-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="opt-ws4")
        with database.transaction() as db:
            assert use_cases.list_composition_build_options(db, ws["id"]) == []


# ---------------------------------------------------------------------------
# Group 4 — Attaching a versioned build snapshots its equipment
# ---------------------------------------------------------------------------

class TestVersionedBuildAttachment:

    def test_create_composition_snapshots_versioned_loadout(self):
        owner = make_user("attach-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="attach-ws1")
        build = _make_v2_build(ws["id"], owner["id"])
        expected = _expected_labels(build["id"], ws["id"])

        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="V2 Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "", "albion_build_id": build["id"],
                "priority": "core",
            }],
        )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        slot = slots[0]
        assert slot["build_name"] == "Editor Healer"
        assert slot["albion_build_id"] == build["id"]
        assert slot["weapon_name"] == expected["weapon_name"]
        assert slot["head_name"] == expected["head_name"]
        assert slot["armor_name"] == expected["armor_name"]
        assert slot["shoes_name"] == expected["shoes_name"]
        assert slot["food_name"] == expected["food_name"]
        assert slot["potion_name"] == expected["potion_name"]

    def test_quick_update_snapshots_versioned_loadout(self):
        owner = make_user("attach-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="attach-ws2")
        build = _make_v2_build(ws["id"], owner["id"])
        expected = _expected_labels(build["id"], ws["id"])
        comp = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Old Text Build", "priority": "core"},
        ])
        with database.transaction() as db:
            slot_id = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]["id"]

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot_id,
            build_name="",
            albion_build_id=build["id"],
        )
        with database.transaction() as db:
            slot = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]
        assert slot["build_name"] == "Editor Healer"
        assert slot["weapon_name"] == expected["weapon_name"]
        assert slot["cape_name"] == expected["cape_name"]

    def test_archived_build_fk_is_rejected_and_cleared(self):
        owner = make_user("attach-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="attach-ws3")
        build = _make_v2_build(ws["id"], owner["id"])
        use_cases.archive_build(ws["id"], build["id"], owner["id"])

        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Archived FK Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "Manually typed", "albion_build_id": build["id"],
                "priority": "normal",
            }],
        )
        with database.transaction() as db:
            slot = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]
        assert slot["albion_build_id"] is None
        assert slot["build_name"] == "Manually typed"


# ---------------------------------------------------------------------------
# Group 5 — A slot needs no typed name when it carries a build FK
# ---------------------------------------------------------------------------

class TestSlotAcceptedWithBuildIdOnly:

    def test_create_accepts_fk_without_build_name(self):
        owner = make_user("fkonly-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="fkonly-ws1")
        build = _make_v2_build(ws["id"], owner["id"], name="FK Only Build")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="FK Only Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "albion_build_id": build["id"], "build_name": "",
                "priority": "normal",
            }],
        )
        with database.transaction() as db:
            slot = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]
        assert slot["build_name"] == "FK Only Build"

    def test_edit_accepts_fk_without_build_name(self):
        owner = make_user("fkonly-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="fkonly-ws2")
        build = _make_v2_build(ws["id"], owner["id"], name="Edit FK Build")
        comp = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Old", "priority": "core"},
        ])
        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "albion_build_id": build["id"], "build_name": "",
                "priority": "core",
            }],
        )
        with database.transaction() as db:
            slot = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]
        assert slot["build_name"] == "Edit FK Build"

    def test_slot_without_name_or_resolvable_fk_is_rejected(self):
        """An unresolvable FK must fail loudly, not insert a nameless slot."""
        owner = make_user("fkonly-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="fkonly-ws3")
        with pytest.raises(ValidationError, match="build_name"):
            use_cases.create_albion_composition(
                guild_workspace_id=ws["id"],
                name="Bogus FK Comp",
                description=None,
                slots=[{
                    "party_number": 1, "slot_index": 1, "role": "Healer",
                    "albion_build_id": "does-not-exist", "build_name": "",
                    "priority": "normal",
                }],
            )

    def test_rejected_slot_set_leaves_existing_slots_intact(self):
        """Validation after resolution must still roll the replace back."""
        owner = make_user("fkonly-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="fkonly-ws4")
        comp = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Keep Me", "priority": "core"},
        ])
        with pytest.raises(ValidationError):
            use_cases.update_composition_slots(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slots=[{
                    "party_number": 1, "slot_index": 1, "role": "Healer",
                    "albion_build_id": "does-not-exist", "build_name": "",
                    "priority": "core",
                }],
            )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        assert len(slots) == 1
        assert slots[0]["build_name"] == "Keep Me"


# ---------------------------------------------------------------------------
# Group 6 — Build Snapshot Invariant for versioned builds
# ---------------------------------------------------------------------------

class TestSnapshotInvariantWithVersionedBuilds:

    def test_new_build_version_does_not_change_attached_slot(self):
        owner = make_user("snap-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="snap-ws1")
        build = _make_v2_build(ws["id"], owner["id"])
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Snapshot Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "", "albion_build_id": build["id"],
                "priority": "core",
            }],
        )
        with database.transaction() as db:
            before = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]

        use_cases.create_build_version(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            slot_items_json=_full_loadout_json(),
            change_summary="Renamed",
            name="Renamed Healer",
        )

        with database.transaction() as db:
            after = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]
        assert after["build_name"] == before["build_name"]
        assert after["weapon_name"] == before["weapon_name"]
        assert after["armor_name"] == before["armor_name"]


# ---------------------------------------------------------------------------
# Group 7 — Route rendering
# ---------------------------------------------------------------------------

class TestCompositionSurfacesOfferLibraryBuilds:

    def _client(self, name: str) -> TestClient:
        client = TestClient(app)
        _login(client, name)
        return client

    def test_new_composition_lists_published_versioned_build(self):
        owner = make_user("route-owner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws1")
        build = _make_v2_build(ws["id"], owner["id"], name="Visual Healer")
        resp = self._client("route-owner1").get(
            f"/workspaces/{ws['slug']}/compositions/new"
        )
        assert resp.status_code == 200
        assert build["id"] in resp.text
        assert "Visual Healer" in resp.text

    def test_new_composition_omits_draft_versioned_build(self):
        owner = make_user("route-owner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws2")
        build = _make_v2_build(ws["id"], owner["id"], name="Draft Healer", status="draft")
        resp = self._client("route-owner2").get(
            f"/workspaces/{ws['slug']}/compositions/new"
        )
        assert resp.status_code == 200
        assert build["id"] not in resp.text

    def test_build_name_field_is_read_only(self):
        owner = make_user("route-owner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws3")
        _make_v2_build(ws["id"], owner["id"])
        resp = self._client("route-owner3").get(
            f"/workspaces/{ws['slug']}/compositions/new"
        )
        assert resp.status_code == 200
        assert 'name="build_name"' in resp.text
        assert "readonly" in resp.text

    def test_empty_library_points_officer_at_the_build_editor(self):
        owner = make_user("route-owner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws4")
        resp = self._client("route-owner4").get(
            f"/workspaces/{ws['slug']}/compositions/new"
        )
        assert resp.status_code == 200
        assert f"/workspaces/{ws['slug']}/builds/editor" in resp.text

    def test_edit_composition_lists_published_versioned_build(self):
        owner = make_user("route-owner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws5")
        build = _make_v2_build(ws["id"], owner["id"], name="Edit Visual Healer")
        comp = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Legacy Text", "priority": "core"},
        ])
        resp = self._client("route-owner5").get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert build["id"] in resp.text
        assert "Edit Visual Healer" in resp.text
        # The legacy slot keeps the name it was saved with.
        assert "Legacy Text" in resp.text

    def test_detail_quick_edit_lists_published_versioned_build(self):
        owner = make_user("route-owner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws6")
        build = _make_v2_build(ws["id"], owner["id"], name="Detail Visual Healer")
        comp = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Legacy Text", "priority": "core"},
        ])
        resp = self._client("route-owner6").get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}"
        )
        assert resp.status_code == 200
        assert build["id"] in resp.text
        assert "Detail Visual Healer" in resp.text

    def test_posting_a_slot_with_only_a_build_id_creates_the_slot(self):
        """The read-only name field means the browser may submit it empty."""
        owner = make_user("route-owner7")
        ws = make_workspace(owner_user_id=owner["id"], slug="route-ws7")
        build = _make_v2_build(ws["id"], owner["id"], name="Posted Healer")
        client = self._client("route-owner7")
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":            "Posted Comp",
                "description":     "",
                "role":            ["Healer"],
                "build_name":      [""],
                "weapon_name":     [""],
                "albion_build_id": [build["id"]],
                "doctrine_role":   [""],
                "party_number":    ["1"],
                "slot_index":      ["1"],
                "priority":        ["core"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        with database.transaction() as db:
            comps = repositories.get_albion_compositions(db, ws["id"])
            comp = next(c for c in comps if c["name"] == "Posted Comp")
            slots = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        assert len(slots) == 1
        assert slots[0]["build_name"] == "Posted Healer"
        assert slots[0]["albion_build_id"] == build["id"]
