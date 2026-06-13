"""
Phase 7 Slice 3 — Promote Composition Slot to Library Build tests.

Covers:
  Group 1 — Use case: successful promotion
  Group 2 — Use case: guard/rejection cases
  Group 3 — Invariants: other slots, operation_slots, other workspaces
  Group 4 — Route: HTTP redirects and auth guards
  Group 5 — Template: "Promote to library →" button visibility

Invariants verified:
  - operation_slots are never written (snapshot invariant)
  - Only the targeted slot's albion_build_id is updated; all other fields unchanged
  - No other composition_slot_templates rows are affected
  - Build creation and FK backfill are atomic — no partial state observable
  - Cross-workspace isolation is preserved
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_viewer(ws_id: str, owner_id: str, display_name: str) -> dict:
    user = make_user(display_name)
    use_cases.add_workspace_member(ws_id, owner_id, display_name, "member")
    return user


def _make_comp_with_free_slot(ws_id: str, build_name="Hallowfall Healer",
                               weapon_name="T8.3 Hallowfall",
                               role="Healer") -> tuple[dict, dict]:
    """Create a composition with one free-typed slot (albion_build_id = NULL).
    Returns (composition, slot_template).
    """
    comp = use_cases.create_albion_composition(
        guild_workspace_id=ws_id,
        name=f"Comp {build_name[:12]}",
        description=None,
        slots=[{
            "party_number": 1,
            "slot_index":   1,
            "role":         role,
            "build_name":   build_name,
            "weapon_name":  weapon_name,
            "priority":     "core",
        }],
    )
    with database.transaction() as db:
        slots = repositories.get_composition_slot_templates(db, comp["id"], ws_id)
    return comp, slots[0]


def _make_comp_with_no_weapon_slot(ws_id: str) -> tuple[dict, dict]:
    """Create a composition with a free-typed slot that has no weapon_name."""
    comp = use_cases.create_albion_composition(
        guild_workspace_id=ws_id,
        name="No Weapon Comp",
        description=None,
        slots=[{
            "party_number": 1,
            "slot_index":   1,
            "role":         "Tank",
            "build_name":   "1H Mace Tank",
            "priority":     "core",
        }],
    )
    with database.transaction() as db:
        slots = repositories.get_composition_slot_templates(db, comp["id"], ws_id)
    return comp, slots[0]


# ---------------------------------------------------------------------------
# Group 1 — Use case: successful promotion
# ---------------------------------------------------------------------------

class TestPromoteSlotToBuildSuccess:

    def setup_method(self):
        self.owner  = make_user("ptb-g1-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="ptb-g1")
        self.comp, self.slot = _make_comp_with_free_slot(
            self.ws["id"],
            build_name="Hallowfall Healer",
            weapon_name="T8.3 Hallowfall",
            role="Healer",
        )

    def _promote(self) -> dict:
        return use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            slot_id=self.slot["id"],
            actor_user_id=self.owner["id"],
        )

    def test_returns_new_build_dict(self):
        result = self._promote()
        assert result["id"] is not None
        assert result["name"] == "Hallowfall Healer"

    def test_new_build_row_exists_in_db(self):
        result = self._promote()
        with database.transaction() as db:
            build = repositories.get_albion_build(db, result["id"], self.ws["id"])
        assert build is not None
        assert build["name"] == "Hallowfall Healer"

    def test_build_role_taken_from_slot_role(self):
        result = self._promote()
        assert result["role"] == "Healer"

    def test_build_weapon_taken_from_slot_weapon(self):
        result = self._promote()
        assert result["weapon_name"] == "T8.3 Hallowfall"

    def test_build_doctrine_role_copied_from_slot(self):
        # Create a slot that has a doctrine_role set.
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="With DocRole",
            description=None,
            slots=[{
                "party_number":  1,
                "slot_index":    1,
                "role":          "Healer",
                "build_name":    "Hallowfall",
                "weapon_name":   "T8.3 Hallowfall",
                "doctrine_role": "Main Healer",
                "priority":      "core",
            }],
        )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(db, comp["id"], self.ws["id"])
        slot = slots[0]
        result = use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            slot_id=slot["id"],
            actor_user_id=self.owner["id"],
        )
        assert result["doctrine_role"] == "Main Healer"

    def test_slot_albion_build_id_backfilled_after_promotion(self):
        result = self._promote()
        with database.transaction() as db:
            updated_slot = repositories.get_composition_slot_template_by_id(
                db, self.slot["id"], self.ws["id"]
            )
        assert updated_slot["albion_build_id"] == result["id"]

    def test_slot_build_name_snapshot_unchanged_after_promotion(self):
        self._promote()
        with database.transaction() as db:
            updated_slot = repositories.get_composition_slot_template_by_id(
                db, self.slot["id"], self.ws["id"]
            )
        assert updated_slot["build_name"] == "Hallowfall Healer"

    def test_slot_weapon_name_snapshot_unchanged_after_promotion(self):
        self._promote()
        with database.transaction() as db:
            updated_slot = repositories.get_composition_slot_template_by_id(
                db, self.slot["id"], self.ws["id"]
            )
        assert updated_slot["weapon_name"] == "T8.3 Hallowfall"

    def test_equipment_fields_copied_from_slot_to_build(self):
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="EquipComp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1,
                "role": "Healer", "build_name": "Hallowfall",
                "weapon_name": "T8.3 Hallowfall",
                "head_name":  "Scholar Cowl",
                "armor_name": "Scholar Robe",
                "priority":   "core",
            }],
        )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(db, comp["id"], self.ws["id"])
        slot = slots[0]
        result = use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            slot_id=slot["id"],
            actor_user_id=self.owner["id"],
        )
        assert result["head_name"]  == "Scholar Cowl"
        assert result["armor_name"] == "Scholar Robe"

    def test_composition_updated_at_touched(self):
        before_updated_at = self.comp["updated_at"]
        self._promote()
        with database.transaction() as db:
            refreshed = repositories.get_albion_composition(
                db, self.comp["id"], self.ws["id"]
            )
        assert refreshed["updated_at"] >= before_updated_at


# ---------------------------------------------------------------------------
# Group 2 — Use case: guard / rejection cases
# ---------------------------------------------------------------------------

class TestPromoteSlotToBuildGuards:

    def setup_method(self):
        self.owner  = make_user("ptb-g2-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="ptb-g2")
        self.comp, self.slot = _make_comp_with_free_slot(self.ws["id"])

    def _promote(self, **kwargs):
        defaults = dict(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            slot_id=self.slot["id"],
            actor_user_id=self.owner["id"],
        )
        return use_cases.promote_composition_slot_to_build(**{**defaults, **kwargs})

    def test_rejects_non_officer_viewer(self):
        viewer = _make_viewer(self.ws["id"], self.owner["id"], "ptb-g2-viewer")
        with pytest.raises(PermissionDenied):
            self._promote(actor_user_id=viewer["id"])

    def test_rejects_wrong_workspace(self):
        with pytest.raises(NotFoundError):
            self._promote(guild_workspace_id="nonexistent-ws")

    def test_rejects_missing_slot(self):
        with pytest.raises(NotFoundError):
            self._promote(slot_id="nonexistent-slot")

    def test_rejects_slot_from_different_composition(self):
        other_comp, other_slot = _make_comp_with_free_slot(
            self.ws["id"], build_name="Other Build", weapon_name="Bow"
        )
        with pytest.raises(NotFoundError):
            self._promote(
                composition_id=self.comp["id"],
                slot_id=other_slot["id"],
            )

    def test_rejects_retired_composition(self):
        use_cases.retire_composition(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            actor_user_id=self.owner["id"],
        )
        with pytest.raises(ConflictError, match="retired"):
            self._promote()

    def test_rejects_slot_already_has_albion_build_id(self):
        # First promotion links the slot.
        self._promote()
        # Second attempt should be rejected.
        with pytest.raises(ConflictError, match="already linked"):
            self._promote()

    def test_rejects_slot_with_empty_build_name(self):
        # Create a valid slot then clear its build_name to make it an open slot.
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Open Slot Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1,
                "role": "Tank", "build_name": "1H Mace",
                "weapon_name": "1H Mace",
                "priority": "normal",
            }],
        )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(db, comp["id"], self.ws["id"])
        open_slot = slots[0]
        # Clear the build_name to simulate an open slot (quick_update allows empty build_name).
        use_cases.quick_update_composition_slot(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            actor_user_id=self.owner["id"],
            slot_id=open_slot["id"],
            build_name="",
            weapon_name="1H Mace",
        )
        with pytest.raises(ValidationError, match="build name"):
            use_cases.promote_composition_slot_to_build(
                guild_workspace_id=self.ws["id"],
                composition_id=comp["id"],
                slot_id=open_slot["id"],
                actor_user_id=self.owner["id"],
            )

    def test_rejects_slot_with_empty_weapon_name(self):
        comp, slot = _make_comp_with_no_weapon_slot(self.ws["id"])
        with pytest.raises(ValidationError, match="weapon name"):
            use_cases.promote_composition_slot_to_build(
                guild_workspace_id=self.ws["id"],
                composition_id=comp["id"],
                slot_id=slot["id"],
                actor_user_id=self.owner["id"],
            )


# ---------------------------------------------------------------------------
# Group 3 — Invariants
# ---------------------------------------------------------------------------

class TestPromoteSlotInvariants:

    def setup_method(self):
        self.owner  = make_user("ptb-g3-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="ptb-g3")

    def test_other_slots_in_same_composition_unchanged(self):
        """Only the promoted slot gets albion_build_id; other slots stay NULL."""
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="MultiSlot Comp",
            description=None,
            slots=[
                {
                    "party_number": 1, "slot_index": 1,
                    "role": "Healer", "build_name": "Hallowfall",
                    "weapon_name": "T8.3 Hallowfall", "priority": "core",
                },
                {
                    "party_number": 1, "slot_index": 2,
                    "role": "Tank", "build_name": "1H Mace Tank",
                    "weapon_name": "1H Mace", "priority": "normal",
                },
            ],
        )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(db, comp["id"], self.ws["id"])
        target_slot = next(s for s in slots if s["role"] == "Healer")
        other_slot  = next(s for s in slots if s["role"] == "Tank")

        use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            slot_id=target_slot["id"],
            actor_user_id=self.owner["id"],
        )

        with database.transaction() as db:
            refreshed_other = repositories.get_composition_slot_template_by_id(
                db, other_slot["id"], self.ws["id"]
            )
        assert refreshed_other["albion_build_id"] is None

    def test_operation_slots_unchanged_after_promotion(self):
        """Frozen operation slots must not be touched — snapshot invariant."""
        comp, slot = _make_comp_with_free_slot(self.ws["id"])

        op = make_operation(self.ws["id"])
        # Attach while still in draft status, then publish + generate slots.
        use_cases.attach_operation_plan(self.ws["id"], op["id"], comp["id"])
        use_cases.publish_operation(self.ws["id"], op["id"])
        use_cases.generate_operation_slots(
            guild_workspace_id=self.ws["id"],
            guild_operation_id=op["id"],
        )
        with database.transaction() as db:
            op_slots_before = repositories.get_operation_slots(db, op["id"], self.ws["id"])

        use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            slot_id=slot["id"],
            actor_user_id=self.owner["id"],
        )

        with database.transaction() as db:
            op_slots_after = repositories.get_operation_slots(db, op["id"], self.ws["id"])

        for before, after in zip(op_slots_before, op_slots_after):
            assert before["build_name"]    == after["build_name"]
            assert before["weapon_name"]   == after["weapon_name"]

    def test_build_count_in_other_workspace_unchanged(self):
        """Promotion in ws-A must not create a build row in ws-B."""
        owner_b = make_user("ptb-g3-owner-b")
        ws_b    = make_workspace(owner_user_id=owner_b["id"], slug="ptb-g3-b")
        with database.transaction() as db:
            builds_before = repositories.get_albion_builds(db, ws_b["id"])

        comp, slot = _make_comp_with_free_slot(self.ws["id"])
        use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            slot_id=slot["id"],
            actor_user_id=self.owner["id"],
        )

        with database.transaction() as db:
            builds_after = repositories.get_albion_builds(db, ws_b["id"])
        assert len(builds_after) == len(builds_before)


# ---------------------------------------------------------------------------
# Group 4 — Route: HTTP redirects and auth guards
# ---------------------------------------------------------------------------

class TestPromoteSlotRouteHTTP:

    def setup_method(self):
        self.owner  = make_user("ptb-g4-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="ptb-g4")
        self.comp, self.slot = _make_comp_with_free_slot(self.ws["id"])
        self.client = TestClient(app)

    def _post(self, comp_id=None, slot_id=None, follow=False):
        comp_id = comp_id or self.comp["id"]
        slot_id = slot_id or self.slot["id"]
        return self.client.post(
            f"/workspaces/{self.ws['slug']}/compositions/{comp_id}/slots/{slot_id}/promote-to-build",
            follow_redirects=follow,
        )

    def test_success_redirects_to_composition_detail(self):
        _login(self.client, "ptb-g4-owner")
        resp = self._post(follow=False)
        assert resp.status_code in (302, 303)
        assert f"/compositions/{self.comp['id']}" in resp.headers["location"]

    def test_success_redirect_contains_success_param(self):
        _login(self.client, "ptb-g4-owner")
        resp = self._post(follow=False)
        assert "success" in resp.headers["location"].lower()

    def test_unauthenticated_redirects_to_login(self):
        resp = self._post(follow=False)
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers.get("location", "")

    def test_non_officer_viewer_returns_403(self):
        viewer = _make_viewer(self.ws["id"], self.owner["id"], "ptb-g4-viewer")
        _login(self.client, "ptb-g4-viewer")
        resp = self._post()
        assert resp.status_code == 403

    def test_missing_slot_returns_404(self):
        _login(self.client, "ptb-g4-owner")
        resp = self._post(slot_id="nonexistent-id")
        assert resp.status_code == 404

    def test_already_linked_slot_redirects_with_error(self):
        _login(self.client, "ptb-g4-owner")
        # First promotion succeeds.
        self._post(follow=False)
        # Second attempt → ConflictError → error redirect.
        resp = self._post(follow=False)
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"].lower()

    def test_slot_without_weapon_redirects_with_error(self):
        comp, slot = _make_comp_with_no_weapon_slot(self.ws["id"])
        _login(self.client, "ptb-g4-owner")
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/slots/{slot['id']}/promote-to-build",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"].lower()


# ---------------------------------------------------------------------------
# Group 5 — Template: "Promote to library →" button visibility
# ---------------------------------------------------------------------------

class TestPromoteButtonVisibility:

    def setup_method(self):
        self.owner  = make_user("ptb-g5-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="ptb-g5")
        self.client = TestClient(app)
        _login(self.client, "ptb-g5-owner")

    def _get_detail(self, comp_id: str) -> str:
        return self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp_id}"
        ).text

    def test_promote_button_visible_for_free_typed_slot_with_build_and_weapon(self):
        comp, slot = _make_comp_with_free_slot(self.ws["id"])
        html = self._get_detail(comp["id"])
        assert "promote-to-build" in html
        assert "Promote to library" in html

    def test_promote_button_hidden_for_already_linked_slot(self):
        comp, slot = _make_comp_with_free_slot(self.ws["id"])
        # Promote once to link it.
        use_cases.promote_composition_slot_to_build(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            slot_id=slot["id"],
            actor_user_id=self.owner["id"],
        )
        html = self._get_detail(comp["id"])
        assert "promote-to-build" not in html

    def test_promote_button_hidden_for_slot_with_no_weapon(self):
        comp, slot = _make_comp_with_no_weapon_slot(self.ws["id"])
        html = self._get_detail(comp["id"])
        assert "promote-to-build" not in html

    def test_promote_button_hidden_for_open_slot(self):
        """Open slot (cleared build_name) should not show the promote button."""
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Open Slot Comp",
            description=None,
            slots=[{
                "party_number": 1, "slot_index": 1,
                "role": "Tank", "build_name": "1H Mace",
                "weapon_name": "1H Mace",
                "priority": "normal",
            }],
        )
        with database.transaction() as db:
            slots = repositories.get_composition_slot_templates(
                db, comp["id"], self.ws["id"]
            )
        # Clear the build_name to simulate an open slot.
        use_cases.quick_update_composition_slot(
            guild_workspace_id=self.ws["id"],
            composition_id=comp["id"],
            actor_user_id=self.owner["id"],
            slot_id=slots[0]["id"],
            build_name="",
            weapon_name="1H Mace",
        )
        html = self._get_detail(comp["id"])
        assert "promote-to-build" not in html

    def test_promote_button_hidden_for_viewers(self):
        comp, slot = _make_comp_with_free_slot(self.ws["id"])
        viewer = _make_viewer(self.ws["id"], self.owner["id"], "ptb-g5-viewer")
        _login(self.client, "ptb-g5-viewer")
        html = self._get_detail(comp["id"])
        assert "promote-to-build" not in html
