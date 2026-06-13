"""Phase 6 — Fast Tactical Mutation: regression tests.

Covers:
  Group 1 — use_cases.quick_update_composition_slot
              a) build_name / weapon_name / doctrine_role update and persist
              b) preserves role, priority, party_number, slot_index
              c) allows empty build_name (open slot state)
              d) build FK resolution + equipment propagation
              e) slot-level doctrine_role override preserved when FK set
              f) raises NotFoundError for wrong slot_id
              g) raises ConflictError on retired composition
              h) raises PermissionDenied for non-officer

  Group 2 — Snapshot invariant
              a) quick_update does NOT affect operation_slots
              b) subsequent operation plan generation sees the updated template

  Group 3 — repositories.update_composition_slot_fields
              a) rowcount=1 on valid update
              b) rowcount=0 when slot_id not in composition
              c) cross-workspace write blocked (wrong guild_workspace_id)

  Group 4 — Clone variant independence
              a) clone creates fresh composition with same slot structure
              b) editing clone does NOT mutate original slot templates

  Group 5 — Route: POST /workspaces/{slug}/compositions/{comp_id}/slot/quick
              a) authenticated officer → redirects to detail
              b) wrong slot_id → redirects with error query param
              c) unauthenticated → redirects to login
              d) non-mutating member → 403

  Group 6 — Template affordances (detail + edit pages)
              a) quick-edit panel renders per slot for officers
              b) quick-edit panel absent for non-officers / retired comps
              c) Dup / Clear buttons present in edit page
              d) Clone as Variant button present on detail page
              e) aria-labels present on action buttons
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, PermissionDenied
from app.main import app

from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
    publish_operation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_setup(slug: str = "fm-ws"):
    owner  = make_user("Fast Mutation Officer")
    ws     = make_workspace(owner_user_id=owner["id"], slug=slug)
    client = TestClient(app)
    client.post(
        "/login",
        data={"display_name": "Fast Mutation Officer", "next": "/"},
        follow_redirects=True,
    )
    return client, owner, ws


def _create_build(ws_id: str, actor_id: str, **overrides) -> dict:
    defaults = {
        "guild_workspace_id": ws_id,
        "actor_user_id":      actor_id,
        "name":               "Hallowfall Healer",
        "role":               "Healer",
        "weapon_name":        "T8.3 Hallowfall",
        "head_name":          "Cleric Cowl",
        "armor_name":         "Cleric Robe",
        "shoes_name":         "Cleric Sandals",
    }
    return use_cases.create_albion_build(**{**defaults, **overrides})


def _first_slot(comp_id: str, ws_id: str) -> dict:
    with database.transaction() as db:
        slots = repositories.get_composition_slot_templates(db, comp_id, ws_id)
    return slots[0]


# ---------------------------------------------------------------------------
# Group 1 — quick_update_composition_slot use case
# ---------------------------------------------------------------------------

class TestQuickUpdateUseCase:

    def test_updates_build_name_and_weapon(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-1")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="Dawnsong",
            weapon_name="Dawnsong",
            doctrine_role="Engage",
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["build_name"]   == "Dawnsong"
        assert updated["weapon_name"]  == "Dawnsong"
        assert updated["doctrine_role"] == "Engage"

    def test_preserves_role_priority_party_slot_index(self):
        """Quick update must not change role, priority, party_number, slot_index."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-2")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        original_role      = slot["role"]
        original_priority  = slot["priority"]
        original_party     = slot["party_number"]
        original_idx       = slot["slot_index"]

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="Bedrock",
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["role"]         == original_role
        assert updated["priority"]     == original_priority
        assert updated["party_number"] == original_party
        assert updated["slot_index"]   == original_idx

    def test_allows_empty_build_name_open_slot(self):
        """Empty build_name is valid — creates an open planning slot."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-3")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="",
            weapon_name=None,
            doctrine_role=None,
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert (updated["build_name"] or "") == ""

    def test_build_fk_resolution_propagates_equipment(self):
        """When albion_build_id is supplied the build's equipment fields are resolved."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-4")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])
        build = _create_build(ws["id"], owner["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="",
            albion_build_id=build["id"],
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["build_name"]  == "Hallowfall Healer"
        assert updated["weapon_name"] == "T8.3 Hallowfall"
        assert updated["armor_name"]  == "Cleric Robe"

    def test_slot_level_doctrine_override_preserved_when_fk_set(self):
        """If slot already has doctrine_role set, it must NOT be overwritten by the build default."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-5")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])
        build = _create_build(ws["id"], owner["id"], doctrine_role="Mass Heal")

        # First quick-update sets a slot-level doctrine_role override
        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="",
            albion_build_id=build["id"],
            doctrine_role="Main Heal",  # slot override
        )

        updated = _first_slot(comp["id"], ws["id"])
        # Slot override ("Main Heal") beats build default ("Mass Heal")
        assert updated["doctrine_role"] == "Main Heal"

    def test_raises_not_found_for_wrong_slot_id(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-6")
        comp  = make_composition(ws["id"])

        with pytest.raises(NotFoundError):
            use_cases.quick_update_composition_slot(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slot_id="nonexistent-slot-id",
                build_name="Test",
            )

    def test_raises_conflict_on_retired_composition(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qu-7")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )

        with pytest.raises(ConflictError):
            use_cases.quick_update_composition_slot(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slot_id=slot["id"],
                build_name="Test",
            )

    def test_raises_permission_denied_for_non_officer(self):
        owner  = make_user("Perm Owner")
        ws     = make_workspace(owner_user_id=owner["id"], slug="qu-8")
        viewer = make_user("Plain Viewer")
        # add_workspace_member uses display_name (dev auth model)
        use_cases.add_workspace_member(
            guild_workspace_id=ws["id"],
            actor_user_id=owner["id"],
            display_name="Plain Viewer",
            role="member",
        )
        comp = make_composition(ws["id"])
        slot = _first_slot(comp["id"], ws["id"])

        with pytest.raises(PermissionDenied):
            use_cases.quick_update_composition_slot(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=viewer["id"],
                slot_id=slot["id"],
                build_name="Test",
            )


# ---------------------------------------------------------------------------
# Group 2 — Snapshot invariant
# ---------------------------------------------------------------------------

class TestSnapshotInvariant:

    def test_quick_update_does_not_affect_existing_operation_slots(self):
        """Frozen operation_slots must be unchanged after quick_update."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="snap-1")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        # Generate frozen snapshot (required before operation_slots exist)
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )

        # Capture state of operation_slot before mutation
        with database.transaction() as db:
            op_slots_before = repositories.get_operation_slots(
                db, op["id"], ws["id"]
            )
        build_before = op_slots_before[0]["build_name"]

        # Quick update the template slot
        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="MUTATED BUILD",
            doctrine_role="MUTATED DOCTRINE",
        )

        # Operation slot must be unchanged
        with database.transaction() as db:
            op_slots_after = repositories.get_operation_slots(
                db, op["id"], ws["id"]
            )
        assert op_slots_after[0]["build_name"]   == build_before
        assert op_slots_after[0]["doctrine_role"] != "MUTATED DOCTRINE"

    def test_new_operation_plan_sees_updated_template(self):
        """A NEW operation generated AFTER the quick update gets the updated slot data."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="snap-2")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="Dawnsong Updated",
            doctrine_role="Engage Updated",
        )

        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )

        with database.transaction() as db:
            op_slots = repositories.get_operation_slots(db, op["id"], ws["id"])

        matching = next(
            (s for s in op_slots if s["slot_index"] == slot["slot_index"]), None
        )
        assert matching is not None
        assert matching["build_name"]   == "Dawnsong Updated"
        assert matching["doctrine_role"] == "Engage Updated"


# ---------------------------------------------------------------------------
# Group 3 — repositories.update_composition_slot_fields
# ---------------------------------------------------------------------------

class TestUpdateCompositionSlotFieldsRepo:

    def _fields(self, build_name="Bedrock"):
        return {
            "role":           "",       # empty → preserve existing via SQL CASE expression
            "build_name":     build_name,
            "weapon_name":    None,
            "doctrine_role":  None,
            "albion_build_id": None,
            "offhand_name":   None,
            "head_name":      None,
            "armor_name":     None,
            "shoes_name":     None,
            "cape_name":      None,
            "food_name":      None,
            "potion_name":    None,
        }

    def test_returns_rowcount_one_on_valid_update(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="repo-1")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        with database.transaction() as db:
            rows = repositories.update_composition_slot_fields(
                db,
                slot["id"],
                comp["id"],
                ws["id"],
                self._fields("Bedrock"),
                "2026-01-01T00:00:00",
            )
        assert rows == 1

    def test_returns_rowcount_zero_for_wrong_slot_id(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="repo-2")
        comp  = make_composition(ws["id"])

        with database.transaction() as db:
            rows = repositories.update_composition_slot_fields(
                db,
                "nonexistent-id",
                comp["id"],
                ws["id"],
                self._fields(),
                "2026-01-01T00:00:00",
            )
        assert rows == 0

    def test_cross_workspace_write_blocked(self):
        """Wrong guild_workspace_id in WHERE clause → zero rows updated."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="repo-3")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        ws2 = make_workspace(owner_user_id=owner["id"], slug="repo-3-other")

        with database.transaction() as db:
            rows = repositories.update_composition_slot_fields(
                db,
                slot["id"],
                comp["id"],
                ws2["id"],          # wrong workspace
                self._fields("Hacker Build"),
                "2026-01-01T00:00:00",
            )
        assert rows == 0

        # Confirm original data is untouched
        original = _first_slot(comp["id"], ws["id"])
        assert original["build_name"] != "Hacker Build"


# ---------------------------------------------------------------------------
# Group 4 — Clone variant independence
# ---------------------------------------------------------------------------

class TestCloneVariantIndependence:

    def _clone_via_route(self, client, slug, comp_id, new_name, slots):
        form_data = {"name": new_name, "description": ""}
        for s in slots:
            form_data.setdefault("party_number", [])
            form_data.setdefault("slot_index",   [])
            form_data.setdefault("role",         [])
            form_data.setdefault("build_name",   [])
            form_data.setdefault("priority",     [])
            form_data["party_number"].append(str(s["party_number"]))
            form_data["slot_index"].append(str(s["slot_index"]))
            form_data["role"].append(s["role"])
            form_data["build_name"].append(s["build_name"] or "")
            form_data["priority"].append(s.get("priority", "normal"))
        resp = client.post(
            f"/workspaces/{slug}/compositions",
            data=form_data,
            follow_redirects=False,
        )
        return resp

    def test_clone_creates_independent_composition(self):
        """Slots from a cloned composition are independent rows."""
        owner  = make_user("Clone Owner")
        ws     = make_workspace(owner_user_id=owner["id"], slug="clone-1")
        client = TestClient(app)
        client.post(
            "/login",
            data={"display_name": "Clone Owner", "next": "/"},
            follow_redirects=True,
        )

        comp_a = make_composition(ws["id"], name="Kite Main")

        with database.transaction() as db:
            orig_slots = repositories.get_composition_slot_templates(
                db, comp_a["id"], ws["id"]
            )

        # Create a clone by POSTing to /compositions with same slot data
        resp = self._clone_via_route(
            client, ws["slug"], comp_a["id"],
            "Kite Low Healer", orig_slots
        )
        assert resp.status_code in (302, 303)

        # Find the clone
        with database.transaction() as db:
            all_comps = repositories.get_albion_compositions(db, ws["id"])
        clone_comp = next(c for c in all_comps if c["name"] == "Kite Low Healer")

        # Both comps should have slots
        with database.transaction() as db:
            a_slots = repositories.get_composition_slot_templates(
                db, comp_a["id"], ws["id"]
            )
            b_slots = repositories.get_composition_slot_templates(
                db, clone_comp["id"], ws["id"]
            )

        assert len(a_slots) == len(b_slots) == len(orig_slots)

        # Slot IDs must be different (independent rows)
        a_ids = {s["id"] for s in a_slots}
        b_ids = {s["id"] for s in b_slots}
        assert a_ids.isdisjoint(b_ids)

    def test_editing_clone_does_not_mutate_original(self):
        """quick_update on a cloned slot must not affect original composition."""
        owner  = make_user("Mutate Officer")
        ws     = make_workspace(owner_user_id=owner["id"], slug="clone-2")
        client = TestClient(app)
        client.post(
            "/login",
            data={"display_name": "Mutate Officer", "next": "/"},
            follow_redirects=True,
        )

        comp_a = make_composition(ws["id"], name="Original Comp")
        with database.transaction() as db:
            orig_slots = repositories.get_composition_slot_templates(
                db, comp_a["id"], ws["id"]
            )

        resp = self._clone_via_route(
            client, ws["slug"], comp_a["id"], "Cloned Comp", orig_slots
        )
        assert resp.status_code in (302, 303)

        with database.transaction() as db:
            all_comps = repositories.get_albion_compositions(db, ws["id"])
        clone_comp = next(c for c in all_comps if c["name"] == "Cloned Comp")
        clone_slot = _first_slot(clone_comp["id"], ws["id"])
        orig_build = orig_slots[0]["build_name"]

        # Mutate the clone's first slot
        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=clone_comp["id"],
            actor_user_id=owner["id"],
            slot_id=clone_slot["id"],
            build_name="CLONE MUTATION",
        )

        # Original composition's first slot must be unchanged
        original_after = _first_slot(comp_a["id"], ws["id"])
        assert original_after["build_name"] == orig_build


# ---------------------------------------------------------------------------
# Group 5 — Route: POST /slot/quick
# ---------------------------------------------------------------------------

class TestQuickUpdateRoute:

    def test_officer_redirect_to_detail_on_success(self):
        client, owner, ws = _make_setup("route-1")
        comp = make_composition(ws["id"])
        slot = _first_slot(comp["id"], ws["id"])

        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={
                "slot_id":       slot["id"],
                "build_name":    "Witchwork",
                "weapon_name":   "Witchwork Staff",
                "doctrine_role": "Burst",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert f"/compositions/{comp['id']}" in resp.headers["location"]

    def test_wrong_slot_id_redirects_with_error(self):
        client, owner, ws = _make_setup("route-2")
        comp = make_composition(ws["id"])

        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={
                "slot_id":    "bad-id",
                "build_name": "Test",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]

    def test_unauthenticated_redirects_to_login(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="route-3")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        anon_client = TestClient(app)
        resp = anon_client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={"slot_id": slot["id"], "build_name": "Test"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]

    def test_missing_slot_id_redirects_with_error(self):
        client, owner, ws = _make_setup("route-4")
        comp = make_composition(ws["id"])

        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={"build_name": "Test"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]

    def test_persists_update_end_to_end(self):
        """Full round-trip: POST route → DB → verify slot updated."""
        client, owner, ws = _make_setup("route-5")
        comp = make_composition(ws["id"])
        slot = _first_slot(comp["id"], ws["id"])

        client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={
                "slot_id":       slot["id"],
                "build_name":    "Dawnsong",
                "weapon_name":   "Dawnsong",
                "doctrine_role": "Engage Caller",
            },
            follow_redirects=False,
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["build_name"]    == "Dawnsong"
        assert updated["doctrine_role"] == "Engage Caller"


# ---------------------------------------------------------------------------
# Group 6 — Template affordances
# ---------------------------------------------------------------------------

class TestTemplateAffordances:

    def test_quick_edit_panel_present_for_officer(self):
        """Detail page renders quick-edit <details> per slot for officers."""
        client, owner, ws = _make_setup("tpl-1")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "slot-card__quick-edit" in resp.text

    def test_quick_edit_panel_absent_on_retired_comp(self):
        """Retired compositions must NOT expose the quick-edit form."""
        client, owner, ws = _make_setup("tpl-2")
        comp = make_composition(ws["id"])
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "slot-card__quick-edit" not in resp.text

    def test_dup_button_present_in_edit_page(self):
        """Edit page slot cards include the Dup quick-action button."""
        client, owner, ws = _make_setup("tpl-3")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "cb-slot-dup-btn" in resp.text

    def test_clear_button_present_in_edit_page(self):
        """Edit page slot cards include the Clear quick-action button."""
        client, owner, ws = _make_setup("tpl-4")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "cb-slot-clear-btn" in resp.text

    def test_clone_variant_button_present_on_detail(self):
        """Detail page header includes the 'Clone as Variant' action."""
        client, owner, ws = _make_setup("tpl-5")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Clone as Variant" in resp.text

    def test_quick_edit_form_aria_labels_present(self):
        """Each quick-edit input must carry an aria-label for keyboard accessibility."""
        client, owner, ws = _make_setup("tpl-6")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert 'aria-label="Quick edit slot' in resp.text

    def test_dup_button_aria_label_present(self):
        """Dup button must have an aria-label (accessibility requirement)."""
        client, owner, ws = _make_setup("tpl-7")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert 'aria-label="Duplicate this slot"' in resp.text

    def test_clear_button_aria_label_present(self):
        """Clear button must have an aria-label (accessibility requirement)."""
        client, owner, ws = _make_setup("tpl-8")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert 'aria-label="Clear build from this slot"' in resp.text

    def test_quick_edit_hidden_slot_id_present(self):
        """Each quick-edit form must include the hidden slot_id input."""
        client, owner, ws = _make_setup("tpl-9")
        comp = make_composition(ws["id"])
        slot = _first_slot(comp["id"], ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert f'name="slot_id" value="{slot["id"]}"' in resp.text

    def test_clone_detail_page_pre_fills_copy_name(self):
        """GET /clone must pre-fill the composition name as 'Copy of …'."""
        client, owner, ws = _make_setup("tpl-10")
        comp = make_composition(ws["id"], name="Iron Kite")

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Copy of Iron Kite" in resp.text

    def test_quick_edit_role_input_present(self):
        """Detail page must render the role input field inside each quick-edit panel."""
        client, owner, ws = _make_setup("tpl-11")
        comp = make_composition(ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert 'name="role"' in resp.text

    def test_quick_edit_role_prefilled_with_current_value(self):
        """The role input must be pre-filled with the slot's current role."""
        client, owner, ws = _make_setup("tpl-12")
        comp = make_composition(ws["id"])
        slot = _first_slot(comp["id"], ws["id"])

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert f'value="{slot["role"]}"' in resp.text


# ---------------------------------------------------------------------------
# Group 7 — Quick-edit persistence (all four mutable fields)
# ---------------------------------------------------------------------------

class TestQuickEditPersistenceAll:
    """Explicit coverage for all four fields the user can change via quick-edit.

    1. quick-edit updates build_name
    2. quick-edit updates weapon_name
    3. quick-edit updates doctrine_role
    4. quick-edit updates role
    5. changes visible after fresh GET (route round-trip)
    6. validation errors produce visible error flash
    7. operation_slots remain unchanged after quick-edit
    8. editing one slot does not mutate others
    """

    # ── 1 ──────────────────────────────────────────────────────────────────
    def test_quick_edit_updates_build_name(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qep-1")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="Corrupted Blade",
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["build_name"] == "Corrupted Blade"

    # ── 2 ──────────────────────────────────────────────────────────────────
    def test_quick_edit_updates_weapon_name(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qep-2")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="Iron Axe",
            weapon_name="Great Frost Staff",
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["weapon_name"] == "Great Frost Staff"

    # ── 3 ──────────────────────────────────────────────────────────────────
    def test_quick_edit_updates_doctrine_role(self):
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qep-3")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name=slot["build_name"] or "Build",
            doctrine_role="Main Caller",
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["doctrine_role"] == "Main Caller"

    # ── 4 ──────────────────────────────────────────────────────────────────
    def test_quick_edit_updates_role(self):
        """Passing a non-empty role must overwrite the slot's structural role."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qep-4")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])

        assert slot["role"] == "Tank"

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name=slot["build_name"] or "Build",
            role="Support",
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["role"] == "Support"

    def test_quick_edit_role_preserved_when_not_supplied(self):
        """Omitting role (default '') must leave the existing role unchanged."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qep-4b")
        comp  = make_composition(ws["id"])
        slot  = _first_slot(comp["id"], ws["id"])
        original_role = slot["role"]

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="New Build",
            # role not supplied — defaults to ""
        )

        updated = _first_slot(comp["id"], ws["id"])
        assert updated["role"] == original_role

    # ── 5 ──────────────────────────────────────────────────────────────────
    def test_changes_visible_after_fresh_get(self):
        """All four updated fields must be visible when re-fetching the detail page."""
        client, owner, ws = _make_setup("qep-5")
        comp = make_composition(ws["id"])
        slot = _first_slot(comp["id"], ws["id"])

        client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={
                "slot_id":       slot["id"],
                "role":          "Healer",
                "build_name":    "Hallowfall Build",
                "weapon_name":   "Hallowfall",
                "doctrine_role": "Main Healer",
            },
            follow_redirects=False,
        )

        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Hallowfall Build" in resp.text
        assert "Hallowfall" in resp.text
        assert "Main Healer" in resp.text

    # ── 6 ──────────────────────────────────────────────────────────────────
    def test_validation_error_produces_error_flash(self):
        """A bad slot_id must redirect back with ?error= so the flash renders."""
        client, owner, ws = _make_setup("qep-6")
        comp = make_composition(ws["id"])

        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={
                "slot_id":    "nonexistent-slot-id",
                "build_name": "Ghost Build",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # error flash message must be rendered in the redirected page
        assert "error" in resp.url.path or "error" in str(resp.url) or \
               "not found" in resp.text.lower() or "alert" in resp.text.lower()

    def test_validation_error_redirect_has_error_param(self):
        """Redirect location for bad slot_id must carry ?error=."""
        client, owner, ws = _make_setup("qep-6b")
        comp = make_composition(ws["id"])

        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slot/quick",
            data={
                "slot_id":    "bad-slot-id",
                "build_name": "Ghost Build",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]

    # ── 7 ──────────────────────────────────────────────────────────────────
    def test_operation_slots_unchanged_after_quick_edit(self):
        """Snapshot invariant: quick-edit must not touch operation_slots."""
        owner  = make_user()
        ws     = make_workspace(owner_user_id=owner["id"], slug="qep-7")
        comp   = make_composition(ws["id"])
        slot   = _first_slot(comp["id"], ws["id"])
        op     = make_operation(ws["id"])
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )

        with database.transaction() as db:
            op_slots_before = repositories.get_operation_slots(db, op["id"], ws["id"])
        before_build = {s["id"]: s["build_name"] for s in op_slots_before}

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot["id"],
            build_name="New Exclusive Build",
            role="Support",
        )

        with database.transaction() as db:
            op_slots_after = repositories.get_operation_slots(db, op["id"], ws["id"])
        after_build = {s["id"]: s["build_name"] for s in op_slots_after}

        assert before_build == after_build, (
            "operation_slots must be frozen snapshots — quick-edit must not change them"
        )

    # ── 8 ──────────────────────────────────────────────────────────────────
    def test_editing_one_slot_does_not_mutate_others(self):
        """Updating slot A must leave all other slots in the same composition unchanged."""
        owner = make_user()
        ws    = make_workspace(owner_user_id=owner["id"], slug="qep-8")
        comp  = make_composition(ws["id"])

        with database.transaction() as db:
            all_slots = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])

        slot_a   = all_slots[0]
        others   = all_slots[1:]
        before   = {s["id"]: dict(s) for s in others}

        use_cases.quick_update_composition_slot(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slot_id=slot_a["id"],
            build_name="Isolated Edit",
            weapon_name="Unique Weapon",
            role="Ranged",
        )

        with database.transaction() as db:
            all_slots_after = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        after = {s["id"]: dict(s) for s in all_slots_after if s["id"] != slot_a["id"]}

        for sid, before_slot in before.items():
            after_slot = after[sid]
            assert after_slot["build_name"]    == before_slot["build_name"]
            assert after_slot["weapon_name"]   == before_slot["weapon_name"]
            assert after_slot["doctrine_role"] == before_slot["doctrine_role"]
            assert after_slot["role"]          == before_slot["role"]
