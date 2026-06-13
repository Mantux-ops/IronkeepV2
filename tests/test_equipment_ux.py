"""
Phase 4 — Equipment UX Improvements.

Covers:
  Group 1 — Equipment fields persist in composition_slot_templates
  Group 2 — _resolve_build_for_slot populates all equipment fields from build
  Group 3 — generate_operation_slots carries equipment snapshot to operation_slots
  Group 4 — Build Snapshot Invariant: edit build does NOT change existing slots
  Group 5 — Null offhand handled cleanly
  Group 6 — Notes max-length extended to 500
  Group 7 — Build detail page renders doctrine summary
  Group 8 — Build list page renders doctrine summary
  Group 9 — Composition detail slot cards show doctrine when equipment present
  Group 10 — Composition edit slot cards show doctrine preview for attached builds
  Group 11 — Accessibility: labels and semantic grouping present
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import albion_builds as builds_domain
from app.errors import ValidationError
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_build(ws_id: str, actor_id: str, **overrides) -> dict:
    defaults = {
        "guild_workspace_id": ws_id,
        "actor_user_id":      actor_id,
        "name":               "Hallowfall Healer",
        "role":               "Healer",
        "weapon_name":        "T8.3 Hallowfall",
        "offhand_name":       "Mistcaller",
        "head_name":          "Cleric Cowl",
        "armor_name":         "Cleric Robe",
        "shoes_name":         "Scholar Sandals",
        "cape_name":          "Lymhurst Cape",
        "food_name":          "Pork Omelette",
        "potion_name":        "Resistance Potion",
        "notes":              "Priority HoT rotation. Keep Guardian Helmet off-cooldown.",
    }
    return use_cases.create_albion_build(**{**defaults, **overrides})


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name}, follow_redirects=True)


# ---------------------------------------------------------------------------
# Group 1 — Equipment fields persist in composition_slot_templates
# ---------------------------------------------------------------------------

class TestEquipmentFieldsPersist:

    def test_all_equipment_fields_stored_on_slot_template(self):
        """Attaching a full build to a slot stores all equipment fields in the template."""
        owner = make_user("EqPersistOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="eq-persist-1")
        build = _full_build(ws["id"], owner["id"])

        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": build["id"], "priority": "core",
        }])

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        assert len(templates) == 1
        t = templates[0]
        assert t["build_name"]   == build["name"]
        assert t["weapon_name"]  == build["weapon_name"]
        assert t["offhand_name"] == build["offhand_name"]
        assert t["head_name"]    == build["head_name"]
        assert t["armor_name"]   == build["armor_name"]
        assert t["shoes_name"]   == build["shoes_name"]
        assert t["cape_name"]    == build["cape_name"]
        assert t["food_name"]    == build["food_name"]
        assert t["potion_name"]  == build["potion_name"]

    def test_manual_slot_without_build_has_null_equipment(self):
        """A manually entered slot (no albion_build_id) has all equipment fields as None."""
        owner = make_user("EqPersistOwner2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="eq-persist-2")

        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Tank",
            "build_name": "1H Mace Tank", "priority": "normal",
        }])

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        t = templates[0]
        assert t["offhand_name"] is None
        assert t["head_name"]    is None
        assert t["armor_name"]   is None
        assert t["shoes_name"]   is None
        assert t["cape_name"]    is None
        assert t["food_name"]    is None
        assert t["potion_name"]  is None


# ---------------------------------------------------------------------------
# Group 2 — _resolve_build_for_slot populates all equipment fields from build
# ---------------------------------------------------------------------------

class TestResolveBuildForSlot:

    def test_resolves_all_equipment_fields_from_build(self):
        """When a valid albion_build_id is provided, all equipment fields are populated."""
        owner = make_user("ResolveEqOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="resolve-eq-1")
        build = _full_build(ws["id"], owner["id"])

        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Resolve Eq Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1,
                "role": "Healer", "build_name": "placeholder",
                "albion_build_id": build["id"], "priority": "normal",
            }],
        )

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        t = templates[0]
        assert t["offhand_name"] == "Mistcaller"
        assert t["head_name"]    == "Cleric Cowl"
        assert t["armor_name"]   == "Cleric Robe"
        assert t["shoes_name"]   == "Scholar Sandals"
        assert t["cape_name"]    == "Lymhurst Cape"
        assert t["food_name"]    == "Pork Omelette"
        assert t["potion_name"]  == "Resistance Potion"

    def test_cleared_equipment_when_build_not_found(self):
        """If albion_build_id doesn't resolve, equipment fields fall through from slot (None)."""
        owner = make_user("ResolveEqOwner2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="resolve-eq-2")

        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="No Build Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1,
                "role": "Tank", "build_name": "Manual Entry",
                "albion_build_id": "non-existent-id", "priority": "normal",
            }],
        )

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        t = templates[0]
        # FK cleared, equipment falls through as None (slot had no explicit values)
        assert t["albion_build_id"] is None
        assert t["head_name"] is None
        assert t["food_name"] is None


# ---------------------------------------------------------------------------
# Group 3 — generate_operation_slots carries equipment snapshot to operation_slots
# ---------------------------------------------------------------------------

class TestEquipmentSnapshotInOperationSlots:

    def test_operation_slots_carry_full_equipment_snapshot(self):
        """Equipment fields are copied from slot templates into frozen operation_slots."""
        owner = make_user("OpSlotEqOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="op-slot-eq-1")
        build = _full_build(ws["id"], owner["id"])

        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": build["id"], "priority": "core",
        }])
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        with database.transaction() as db:
            slots = repositories.get_operation_slots(db, op["id"], ws["id"])

        assert len(slots) == 1
        s = slots[0]
        assert s["weapon_name"]  == build["weapon_name"]
        assert s["offhand_name"] == build["offhand_name"]
        assert s["head_name"]    == build["head_name"]
        assert s["armor_name"]   == build["armor_name"]
        assert s["shoes_name"]   == build["shoes_name"]
        assert s["cape_name"]    == build["cape_name"]
        assert s["food_name"]    == build["food_name"]
        assert s["potion_name"]  == build["potion_name"]

    def test_operation_slots_equipment_is_null_for_manual_build(self):
        """Operation slots have null equipment fields when no build entity was attached."""
        owner = make_user("OpSlotEqOwner2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="op-slot-eq-2")

        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Tank",
            "build_name": "1H Mace Tank", "priority": "normal",
        }])
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        with database.transaction() as db:
            slots = repositories.get_operation_slots(db, op["id"], ws["id"])

        s = slots[0]
        assert s["build_name"] == "1H Mace Tank"
        assert s["offhand_name"] is None
        assert s["head_name"]    is None
        assert s["food_name"]    is None


# ---------------------------------------------------------------------------
# Group 4 — Build Snapshot Invariant: edit build does NOT change existing slots
# ---------------------------------------------------------------------------

class TestEquipmentSnapshotInvariant:

    def test_edit_build_equipment_does_not_change_slot_templates(self):
        """Updating a build's equipment does not retroactively update composition slots."""
        owner = make_user("SnapshotEqOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="snapshot-eq-1")
        build = _full_build(ws["id"], owner["id"])

        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": build["id"], "priority": "core",
        }])

        # Record equipment snapshot state before editing the build
        with database.transaction() as db:
            before = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]

        # Edit the build's equipment
        use_cases.update_albion_build(
            ws["id"], build["id"], owner["id"],
            name=build["name"], role=build["role"],
            weapon_name="T8.3 Hallowfall (updated)",
            head_name="Cultist Cowl",
            food_name="Beef Stew",
        )

        # Slot template must not have changed
        with database.transaction() as db:
            after = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )[0]

        assert after["weapon_name"] == before["weapon_name"]
        assert after["head_name"]   == before["head_name"]
        assert after["food_name"]   == before["food_name"]

    def test_edit_build_equipment_does_not_change_operation_slots(self):
        """Updating a build's equipment does not change frozen operation_slots."""
        owner = make_user("SnapshotEqOwner2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="snapshot-eq-2")
        build = _full_build(ws["id"], owner["id"])

        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": build["id"], "priority": "core",
        }])
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        with database.transaction() as db:
            before = repositories.get_operation_slots(db, op["id"], ws["id"])[0]

        # Edit the build
        use_cases.update_albion_build(
            ws["id"], build["id"], owner["id"],
            name=build["name"], role=build["role"],
            weapon_name="Completely Different Weapon",
            head_name="Different Head",
            food_name="Different Food",
        )

        with database.transaction() as db:
            after = repositories.get_operation_slots(db, op["id"], ws["id"])[0]

        assert after["weapon_name"] == before["weapon_name"]
        assert after["head_name"]   == before["head_name"]
        assert after["food_name"]   == before["food_name"]


# ---------------------------------------------------------------------------
# Group 5 — Null offhand handled cleanly
# ---------------------------------------------------------------------------

class TestNullOffhand:

    def test_2h_weapon_with_no_offhand_stored_cleanly(self):
        """A build with no offhand stores None for offhand_name."""
        owner = make_user("NoOffhandOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="no-offhand-1")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Great Axe DPS", role="DPS",
            weapon_name="T8 Great Axe",
            # offhand_name intentionally omitted
        )
        assert build["offhand_name"] is None

    def test_slot_with_2h_build_has_null_offhand(self):
        """Slot template has null offhand when build has no offhand."""
        owner = make_user("NoOffhandOwner2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="no-offhand-2")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="2H Axe DPS", role="DPS", weapon_name="T8 Great Axe",
        )
        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "DPS",
            "build_name": "any", "albion_build_id": build["id"], "priority": "normal",
        }])
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        assert templates[0]["offhand_name"] is None

    def test_1h_weapon_with_offhand_stored_correctly(self):
        """A 1h build with offhand stores both weapon_name and offhand_name."""
        owner = make_user("OffhandOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="offhand-1")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Hallowfall Healer", role="Healer",
            weapon_name="T8.3 Hallowfall",
            offhand_name="Mistcaller",
        )
        comp = make_composition(ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": build["id"], "priority": "core",
        }])
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        t = templates[0]
        assert t["weapon_name"]  == "T8.3 Hallowfall"
        assert t["offhand_name"] == "Mistcaller"


# ---------------------------------------------------------------------------
# Group 6 — Notes max-length extended to 500
# ---------------------------------------------------------------------------

class TestNotesMaxLength:

    def test_notes_up_to_500_chars_accepted(self):
        """A notes field up to 500 characters is accepted without error."""
        long_note = "R" * 500
        builds_domain.validate_build({
            "name": "Long Note Build", "role": "DPS", "weapon_name": "Bow",
            "notes": long_note,
        })  # must not raise

    def test_notes_over_500_chars_rejected(self):
        """A notes field over 500 characters raises ValidationError."""
        too_long = "R" * 501
        with pytest.raises(ValidationError, match="notes"):
            builds_domain.validate_build({
                "name": "Too Long Build", "role": "DPS", "weapon_name": "Bow",
                "notes": too_long,
            })

    def test_equipment_field_over_120_still_rejected(self):
        """Equipment fields still enforce the 120-char limit."""
        with pytest.raises(ValidationError, match="head_name"):
            builds_domain.validate_build({
                "name": "Long Head Build", "role": "DPS", "weapon_name": "Bow",
                "head_name": "H" * 121,
            })


# ---------------------------------------------------------------------------
# Group 7 — Build detail page renders doctrine summary
# ---------------------------------------------------------------------------

class TestBuildDetailDoctrine:

    def setup_method(self):
        self.owner = make_user("BldDetailOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="bld-detail-p4")
        self.build = _full_build(self.ws["id"], self.owner["id"])
        self.client = TestClient(app)
        _login(self.client, "BldDetailOwner")

    def test_build_detail_shows_weapon_in_doctrine_summary(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert resp.status_code == 200
        assert "T8.3 Hallowfall" in resp.text

    def test_build_detail_shows_offhand_in_doctrine_summary(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert "Mistcaller" in resp.text

    def test_build_detail_shows_armour_in_doctrine_summary(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert "Cleric Cowl" in resp.text
        assert "Cleric Robe" in resp.text
        assert "Scholar Sandals" in resp.text
        assert "Lymhurst Cape" in resp.text

    def test_build_detail_shows_consumables_in_doctrine_summary(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert "Pork Omelette" in resp.text
        assert "Resistance Potion" in resp.text

    def test_build_detail_shows_notes(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert "Priority HoT rotation" in resp.text

    def test_build_detail_no_offhand_section_absent_when_empty(self):
        """Offhand section not shown when build has no offhand."""
        build_no_oh = use_cases.create_albion_build(
            guild_workspace_id=self.ws["id"], actor_user_id=self.owner["id"],
            name="2H Axe", role="DPS", weapon_name="T8 Great Axe",
        )
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{build_no_oh['id']}")
        assert resp.status_code == 200
        assert "Offhand" not in resp.text

    def test_build_detail_contains_doctrine_css_class(self):
        """Doctrine summary element is present in the page."""
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert "bld-doctrine" in resp.text


# ---------------------------------------------------------------------------
# Group 8 — Build list page renders doctrine summary
# ---------------------------------------------------------------------------

class TestBuildListDoctrine:

    def setup_method(self):
        self.owner = make_user("BldListDocOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="bld-list-doc")
        self.build = _full_build(self.ws["id"], self.owner["id"])
        self.client = TestClient(app)
        _login(self.client, "BldListDocOwner")

    def test_build_list_shows_weapon_name(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert resp.status_code == 200
        assert "T8.3 Hallowfall" in resp.text

    def test_build_list_shows_doctrine_summary_class(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "bld-doctrine" in resp.text

    def test_build_list_shows_armour_in_card(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "Cleric Cowl" in resp.text

    def test_build_list_shows_consumables_in_card(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds")
        assert "Pork Omelette" in resp.text


# ---------------------------------------------------------------------------
# Group 9 — Composition detail slot cards show doctrine when equipment present
# ---------------------------------------------------------------------------

class TestCompositionDetailDoctrine:

    def setup_method(self):
        self.owner = make_user("CompDetailDocOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="comp-detail-doc")
        self.build = _full_build(self.ws["id"], self.owner["id"])
        self.comp  = make_composition(self.ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": self.build["id"], "priority": "core",
        }])
        self.client = TestClient(app)
        _login(self.client, "CompDetailDocOwner")

    def test_composition_detail_shows_armour_doctrine(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}"
        )
        assert resp.status_code == 200
        assert "Cleric Cowl" in resp.text

    def test_composition_detail_shows_consumables_doctrine(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}"
        )
        assert "Pork Omelette" in resp.text

    def test_composition_detail_slot_card_has_doctrine_class(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}"
        )
        assert "slot-doctrine" in resp.text or "bld-doctrine" in resp.text

    def test_composition_detail_no_doctrine_for_manual_slot(self):
        """Slot without equipment data has no doctrine section."""
        comp2 = make_composition(self.ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Tank",
            "build_name": "Manual Tank", "priority": "normal",
        }])
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp2['id']}"
        )
        assert resp.status_code == 200
        # No doctrine armour text for this manual-entry slot
        assert "Cleric Cowl" not in resp.text


# ---------------------------------------------------------------------------
# Group 10 — Composition edit cards show doctrine preview for attached builds
# ---------------------------------------------------------------------------

class TestCompositionEditDoctrine:

    def setup_method(self):
        self.owner = make_user("CompEditDocOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="comp-edit-doc")
        self.build = _full_build(self.ws["id"], self.owner["id"])
        self.comp  = make_composition(self.ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": self.build["id"], "priority": "core",
        }])
        self.client = TestClient(app)
        _login(self.client, "CompEditDocOwner")

    def test_edit_surface_shows_doctrine_preview_for_attached_slot(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-slot-doctrine-preview" in resp.text

    def test_edit_surface_shows_armour_in_preview(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}/edit"
        )
        assert "Cleric Cowl" in resp.text

    def test_edit_surface_shows_consumables_in_preview(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}/edit"
        )
        assert "Pork Omelette" in resp.text

    def test_edit_surface_workspace_builds_json_has_all_equipment_fields(self):
        """WORKSPACE_BUILDS JSON includes equipment fields for JS doctrine preview."""
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}/edit"
        )
        assert resp.status_code == 200
        # All equipment fields should appear in the injected JSON blob
        assert "head_name" in resp.text
        assert "armor_name" in resp.text
        assert "food_name" in resp.text
        assert "potion_name" in resp.text

    def test_doctrine_preview_empty_for_slot_without_build(self):
        """Slots without equipment data have an empty doctrine preview container."""
        comp2 = make_composition(self.ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Tank",
            "build_name": "Manual Tank", "priority": "normal",
        }])
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp2['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-slot-doctrine-preview" in resp.text


# ---------------------------------------------------------------------------
# Group 11 — Accessibility
# ---------------------------------------------------------------------------

class TestEquipmentAccessibility:

    def setup_method(self):
        self.owner = make_user("EqA11yOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="eq-a11y")
        self.build = _full_build(self.ws["id"], self.owner["id"])
        self.client = TestClient(app)
        _login(self.client, "EqA11yOwner")

    def test_build_detail_has_section_labels(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}")
        assert resp.status_code == 200
        # Equipment section titles present
        assert "Armour" in resp.text
        assert "Consumables" in resp.text

    def test_build_new_form_has_accessible_labels(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/new")
        assert resp.status_code == 200
        assert 'for="bld-name"' in resp.text
        assert 'for="bld-weapon"' in resp.text
        assert 'for="bld-notes"' in resp.text

    def test_build_new_form_notes_maxlength_is_500(self):
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/builds/new")
        assert 'maxlength="500"' in resp.text

    def test_build_edit_form_notes_maxlength_is_500(self):
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/builds/{self.build['id']}/edit"
        )
        assert resp.status_code == 200
        assert 'maxlength="500"' in resp.text

    def test_composition_edit_doctrine_preview_has_aria_label(self):
        comp = make_composition(self.ws["id"], slots=[{
            "party_number": 1, "slot_index": 1, "role": "Healer",
            "build_name": "any", "albion_build_id": self.build["id"], "priority": "core",
        }])
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'aria-label="Equipment summary"' in resp.text
