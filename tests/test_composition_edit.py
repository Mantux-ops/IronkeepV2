"""
Composition slot template editing tests.

Covers:
  Group 1 — Repository: delete_composition_slot_templates
  Group 2 — Use case: update_composition_slots (happy path and guard rails)
  Group 3 — Route GET: edit form renders pre-filled slots
  Group 4 — Route POST: slot templates replaced, operation_slots unchanged
  Group 5 — Frozen snapshot invariant: existing operation_slots untouched

Intentionally NOT covered here:
  - Full HTML snapshot assertions
  - CSS layout details
  - Planner slot behaviour after the edit (unchanged — already tested in
    test_slot_template_model.py and test_tactical_logic.py)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, PermissionDenied
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace",    "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Daggers",    "priority": "normal"},
]

_REPLACEMENT_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Tombhammer", "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Fallen Staff","priority": "core"},
]

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_setup(owner_name: str, slug: str, slots=None):
    """Workspace → owner user → composition.  Returns (client, owner, ws, comp)."""
    owner = make_user(owner_name)
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = make_composition(ws["id"], slots=slots or _DEFAULT_SLOTS)
    client = TestClient(app)
    _login(client, owner_name)
    return client, owner, ws, comp


def _get_template_rows(ws_id: str, comp_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_composition_slot_templates(db, comp_id, ws_id)


def _get_operation_slots(ws_id: str, op_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_operation_slots(db, op_id, ws_id)


# ---------------------------------------------------------------------------
# Group 1 — Repository: delete_composition_slot_templates
# ---------------------------------------------------------------------------

class TestDeleteCompositionSlotTemplates:
    """Low-level delete behaviour — called inside update_composition_slots."""

    def test_deletes_all_slots_for_composition(self):
        ws   = make_workspace(slug="repo-del-1")
        comp = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        with database.transaction() as db:
            deleted = repositories.delete_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        assert deleted == 3
        assert _get_template_rows(ws["id"], comp["id"]) == []

    def test_returns_zero_when_no_slots(self):
        ws   = make_workspace(slug="repo-del-2")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Empty Comp",
            description=None,
            slots=[{"party_number": 1, "slot_index": 1, "role": "Tank",
                    "build_name": "1H Mace", "priority": "core"}],
        )
        # Delete once so the table is empty.
        with database.transaction() as db:
            repositories.delete_composition_slot_templates(db, comp["id"], ws["id"])
        # Delete again — should return 0, not error.
        with database.transaction() as db:
            deleted = repositories.delete_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        assert deleted == 0

    def test_does_not_touch_other_composition_slots(self):
        ws    = make_workspace(slug="repo-del-3")
        comp1 = make_composition(ws["id"], name="Comp A", slots=_DEFAULT_SLOTS)
        comp2 = make_composition(ws["id"], name="Comp B", slots=_DEFAULT_SLOTS)

        with database.transaction() as db:
            repositories.delete_composition_slot_templates(db, comp1["id"], ws["id"])

        assert _get_template_rows(ws["id"], comp1["id"]) == []
        assert len(_get_template_rows(ws["id"], comp2["id"])) == 3

    def test_does_not_touch_operation_slots(self):
        ws   = make_workspace(slug="repo-del-4")
        comp = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        op   = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        with database.transaction() as db:
            repositories.delete_composition_slot_templates(db, comp["id"], ws["id"])

        assert len(_get_operation_slots(ws["id"], op["id"])) == 3


# ---------------------------------------------------------------------------
# Group 2 — Use case: update_composition_slots
# ---------------------------------------------------------------------------

class TestUpdateCompositionSlots:
    """update_composition_slots business rules and atomic replacement."""

    def test_replaces_slot_templates(self):
        owner = make_user("OwnerUC1")
        ws    = make_workspace(owner_user_id=owner["id"], slug="uc-edit-1")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slots=_REPLACEMENT_SLOTS,
        )

        rows = _get_template_rows(ws["id"], comp["id"])
        assert len(rows) == 2
        build_names = {r["build_name"] for r in rows}
        assert build_names == {"Tombhammer", "Fallen Staff"}

    def test_old_slots_gone_after_replace(self):
        owner = make_user("OwnerUC2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="uc-edit-2")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slots=_REPLACEMENT_SLOTS,
        )

        rows = _get_template_rows(ws["id"], comp["id"])
        old_build_names = {"1H Mace", "Hallowfall", "Daggers"}
        current_build_names = {r["build_name"] for r in rows}
        assert not old_build_names.intersection(current_build_names)

    def test_rejects_wrong_workspace(self):
        ws_a  = make_workspace(slug="uc-edit-ws-a")
        ws_b  = make_workspace(slug="uc-edit-ws-b")
        owner = make_user("OwnerUCWS")
        ws_a  = make_workspace(owner_user_id=owner["id"], slug="uc-edit-ws-a2")
        comp  = make_composition(ws_a["id"], slots=_DEFAULT_SLOTS)

        with pytest.raises((NotFoundError, ConflictError)):
            use_cases.update_composition_slots(
                guild_workspace_id=ws_b["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slots=_REPLACEMENT_SLOTS,
            )

    def test_rejects_retired_composition(self):
        owner = make_user("OwnerRetired")
        ws    = make_workspace(owner_user_id=owner["id"], slug="uc-edit-retired")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])

        with pytest.raises(ConflictError):
            use_cases.update_composition_slots(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slots=_REPLACEMENT_SLOTS,
            )

    def test_rejects_empty_slot_list(self):
        owner = make_user("OwnerEmpty")
        ws    = make_workspace(owner_user_id=owner["id"], slug="uc-edit-empty")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        with pytest.raises(Exception):
            use_cases.update_composition_slots(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slots=[],
            )

    def test_rejects_non_officer(self):
        owner  = make_user("OwnerPerm")
        ws     = make_workspace(owner_user_id=owner["id"], slug="uc-edit-perm")
        comp   = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        # add_workspace_member takes display_name, returns the member row.
        member_row = use_cases.add_workspace_member(
            ws["id"], owner["id"], "MemberPerm", role="member"
        )

        with pytest.raises(PermissionDenied):
            use_cases.update_composition_slots(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=member_row["user_id"],
                slots=_REPLACEMENT_SLOTS,
            )

    def test_rejects_duplicate_party_slot_index(self):
        owner = make_user("OwnerDup")
        ws    = make_workspace(owner_user_id=owner["id"], slug="uc-edit-dup")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        dup_slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "1H Mace", "priority": "core"},
            {"party_number": 1, "slot_index": 1, "role": "Healer",
             "build_name": "Hallowfall", "priority": "core"},
        ]
        with pytest.raises(Exception):
            use_cases.update_composition_slots(
                guild_workspace_id=ws["id"],
                composition_id=comp["id"],
                actor_user_id=owner["id"],
                slots=dup_slots,
            )


# ---------------------------------------------------------------------------
# Group 3 — Route GET: edit form renders pre-filled slots
# ---------------------------------------------------------------------------

class TestGetEditComposition:
    """GET /compositions/{comp_id}/edit renders correctly."""

    def test_returns_200_for_officer(self):
        client, _owner, ws, comp = _make_setup("GetEdit1", "get-edit-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200

    def test_edit_form_contains_existing_build_names(self):
        client, _owner, ws, comp = _make_setup("GetEdit2", "get-edit-2")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "1H Mace" in resp.text
        assert "Hallowfall" in resp.text

    def test_edit_form_contains_existing_roles(self):
        client, _owner, ws, comp = _make_setup("GetEdit3", "get-edit-3")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "Tank" in resp.text
        assert "Healer" in resp.text

    def test_edit_form_posts_to_correct_action(self):
        client, _owner, ws, comp = _make_setup("GetEdit4", "get-edit-4")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        expected_action = f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slots"
        assert expected_action in resp.text

    def test_returns_403_for_unauthenticated(self):
        _client, _owner, ws, comp = _make_setup("GetEdit5", "get-edit-5")
        anon = TestClient(app)
        resp = anon.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 403)

    def test_returns_403_for_retired_composition(self):
        owner = make_user("GetEdit6Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="get-edit-6")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])
        client = TestClient(app)
        _login(client, "GetEdit6Owner")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 403

    def test_active_operations_notice_shown(self):
        owner = make_user("GetEdit7Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="get-edit-7")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        op    = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        client = TestClient(app)
        _login(client, "GetEdit7Owner")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "active operation" in resp.text.lower() or "not affect" in resp.text.lower()

    def test_no_active_operations_notice_absent(self):
        client, _owner, ws, comp = _make_setup("GetEdit8", "get-edit-8")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        # When there are no active operations the notice div should be absent.
        assert "active operation" not in resp.text.lower()


# ---------------------------------------------------------------------------
# Group 4 — Route POST: slot templates are replaced correctly
# ---------------------------------------------------------------------------

class TestPostUpdateCompositionSlots:
    """POST /compositions/{comp_id}/slots replaces templates and redirects."""

    def _post_slots(self, client, ws_slug, comp_id, slots):
        data = {}
        for field in ("party_number", "slot_index", "role", "build_name",
                      "weapon_name", "priority"):
            data[field] = [str(s.get(field, "")) for s in slots]
        return client.post(
            f"/workspaces/{ws_slug}/compositions/{comp_id}/slots",
            data=data,
            follow_redirects=False,
        )

    def test_redirects_to_detail_on_success(self):
        client, _owner, ws, comp = _make_setup("PostEdit1", "post-edit-1")
        resp = self._post_slots(client, ws["slug"], comp["id"], _REPLACEMENT_SLOTS)
        assert resp.status_code in (302, 303)
        assert f"/compositions/{comp['id']}" in resp.headers["location"]

    def test_slot_templates_updated_in_db(self):
        client, _owner, ws, comp = _make_setup("PostEdit2", "post-edit-2")
        self._post_slots(client, ws["slug"], comp["id"], _REPLACEMENT_SLOTS)

        rows = _get_template_rows(ws["id"], comp["id"])
        assert len(rows) == 2
        build_names = {r["build_name"] for r in rows}
        assert build_names == {"Tombhammer", "Fallen Staff"}

    def test_old_templates_gone_after_update(self):
        client, _owner, ws, comp = _make_setup("PostEdit3", "post-edit-3")
        self._post_slots(client, ws["slug"], comp["id"], _REPLACEMENT_SLOTS)

        rows = _get_template_rows(ws["id"], comp["id"])
        build_names = {r["build_name"] for r in rows}
        assert "1H Mace" not in build_names
        assert "Hallowfall" not in build_names
        assert "Daggers" not in build_names

    def test_redirects_to_edit_on_validation_error(self):
        """Empty slot list → redirect back to edit with error."""
        client, _owner, ws, comp = _make_setup("PostEdit4", "post-edit-4")
        # Submit with all empty fields — all rows will be skipped → empty list.
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slots",
            data={"party_number": [""], "slot_index": [""], "role": [""],
                  "build_name": [""], "weapon_name": [""], "priority": ["normal"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "edit" in resp.headers["location"]

    def test_unauthenticated_redirects(self):
        _client, _owner, ws, comp = _make_setup("PostEdit5", "post-edit-5")
        anon = TestClient(app)
        resp = anon.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slots",
            data={"party_number": ["1"], "slot_index": ["1"], "role": ["Tank"],
                  "build_name": ["1H Mace"], "weapon_name": [""], "priority": ["core"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 401, 403)


# ---------------------------------------------------------------------------
# Group 5 — Frozen snapshot invariant
# ---------------------------------------------------------------------------

class TestFrozenSnapshotInvariant:
    """Editing composition slot templates must never modify operation_slots."""

    def _post_slots(self, client, ws_slug, comp_id, slots):
        data = {}
        for field in ("party_number", "slot_index", "role", "build_name",
                      "weapon_name", "priority"):
            data[field] = [str(s.get(field, "")) for s in slots]
        return client.post(
            f"/workspaces/{ws_slug}/compositions/{comp_id}/slots",
            data=data,
            follow_redirects=False,
        )

    def test_operation_slots_unchanged_after_template_edit(self):
        owner = make_user("FrozenOwner1")
        ws    = make_workspace(owner_user_id=owner["id"], slug="frozen-1")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        op    = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        before = _get_operation_slots(ws["id"], op["id"])
        before_builds = {s["build_name"] for s in before}

        # Edit the template — replace entirely different builds.
        client = TestClient(app)
        _login(client, "FrozenOwner1")
        self._post_slots(client, ws["slug"], comp["id"], _REPLACEMENT_SLOTS)

        after = _get_operation_slots(ws["id"], op["id"])
        after_builds = {s["build_name"] for s in after}

        # Operation slots must be exactly the same as before the edit.
        assert before_builds == after_builds
        assert len(after) == len(before)

    def test_operation_slot_build_names_match_original_templates(self):
        owner = make_user("FrozenOwner2")
        ws    = make_workspace(owner_user_id=owner["id"], slug="frozen-2")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        op    = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        # Use case-level edit (bypasses HTTP layer).
        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slots=_REPLACEMENT_SLOTS,
        )

        op_slots = _get_operation_slots(ws["id"], op["id"])
        op_builds = {s["build_name"] for s in op_slots}

        # Operation still shows the original build names.
        assert "1H Mace" in op_builds
        assert "Hallowfall" in op_builds
        # New builds are NOT in operation slots.
        assert "Tombhammer" not in op_builds
        assert "Fallen Staff" not in op_builds

    def test_multiple_operations_both_frozen(self):
        """Two operations sharing a composition both keep their frozen snapshots."""
        owner = make_user("FrozenOwner3")
        ws    = make_workspace(owner_user_id=owner["id"], slug="frozen-3")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        op1 = make_operation(ws["id"], title="Op 1", start="2026-06-01T20:00:00+00:00")
        use_cases.attach_operation_plan(ws["id"], op1["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op1["id"])

        # Detach and re-attach to a second operation.
        op2 = make_operation(ws["id"], title="Op 2", start="2026-06-08T20:00:00+00:00")
        use_cases.attach_operation_plan(ws["id"], op2["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op2["id"])

        # Edit templates.
        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slots=_REPLACEMENT_SLOTS,
        )

        for op_id in (op1["id"], op2["id"]):
            slots = _get_operation_slots(ws["id"], op_id)
            builds = {s["build_name"] for s in slots}
            assert "1H Mace" in builds
            assert "Tombhammer" not in builds


# ---------------------------------------------------------------------------
# Group 6 — Detail and list template affordances
# ---------------------------------------------------------------------------

class TestEditAffordances:
    """Edit link/button renders correctly in detail and list templates."""

    def test_edit_slots_link_on_detail_for_officer(self):
        client, _owner, ws, comp = _make_setup("Afford1", "afford-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}"
        )
        assert f"/compositions/{comp['id']}/edit" in resp.text

    def test_edit_slots_link_absent_for_retired_comp(self):
        owner = make_user("Afford2Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="afford-2")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])
        client = TestClient(app)
        _login(client, "Afford2Owner")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}"
        )
        # Edit link should not appear for retired compositions.
        assert f"/compositions/{comp['id']}/edit" not in resp.text

    def test_edit_link_on_list_for_officer(self):
        client, _owner, ws, comp = _make_setup("Afford3", "afford-3")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions")
        assert f"/compositions/{comp['id']}/edit" in resp.text

    def test_edit_link_absent_on_list_for_retired_comp(self):
        owner = make_user("Afford4Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="afford-4")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])
        client = TestClient(app)
        _login(client, "Afford4Owner")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions?show_deleted=1"
        )
        # The list page with show_deleted includes the retired comp — but edit
        # link must not appear for it.
        assert f"compositions/{comp['id']}/edit" not in resp.text


# ---------------------------------------------------------------------------
# Group 7 — Phase 2 Slot Card System (structural rendering)
# ---------------------------------------------------------------------------

class TestPhase2SlotCardSystem:
    """Verify the slot card system renders correctly on the edit surface.

    Covers:
      - Party groups present in edit template
      - Slot cards present in edit template
      - Role labels visible in rendered cards
      - Build names visible in rendered cards
      - Core badge present for core-priority slots
      - Open badge present for slots missing build_name
      - Party header role tally rendered
      - Form inputs are present and submittable (name attributes intact)
      - POST submission still works (card system does not break form semantics)
      - Keyboard-focusable inputs (aria-label and name attributes present)
    """

    def test_edit_page_has_party_groups(self):
        """GET edit renders .cb-party-group sections for each party."""
        client, _owner, ws, comp = _make_setup("P2PGroup1", "p2-pgroup-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-party-group" in resp.text

    def test_edit_page_has_slot_cards(self):
        """GET edit renders .cb-slot-card elements for each slot template."""
        client, _owner, ws, comp = _make_setup("P2SCard1", "p2-scard-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-slot-card" in resp.text

    def test_edit_page_role_labels_present(self):
        """Role values from slot templates appear in the edit form."""
        client, _owner, ws, comp = _make_setup("P2Role1", "p2-role-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "Tank" in resp.text
        assert "Healer" in resp.text
        assert "DPS" in resp.text

    def test_edit_page_build_names_present(self):
        """Build names from slot templates appear in the edit form."""
        client, _owner, ws, comp = _make_setup("P2Build1", "p2-build-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "1H Mace" in resp.text
        assert "Hallowfall" in resp.text

    def test_core_slots_show_core_badge(self):
        """CORE badge renders for slots with priority=core."""
        client, _owner, ws, comp = _make_setup("P2Core1", "p2-core-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-badge--core" in resp.text

    def test_open_badge_present_for_slot_without_build(self):
        """OPEN badge renders in card HTML for a slot with no build_name set.

        Direct DB insert bypasses use_case validation (which strips empty builds)
        to produce a slot with no build_name — the canonical test for OPEN state.
        """
        import uuid
        from datetime import datetime, timezone

        owner = make_user("P2Open1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p2-open-1")
        # Create with a seed slot (validation requires at least one slot)
        comp  = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "1H Mace", "priority": "normal"},
        ])

        # Insert an additional slot with empty build_name directly — bypasses
        # the use_case validation that strips empty builds from submitted form data.
        now = datetime.now(timezone.utc).isoformat()
        with database.transaction() as db:
            repositories.insert_composition_slot_templates(db, [{
                "id":                    str(uuid.uuid4()),
                "guild_workspace_id":    ws["id"],
                "albion_composition_id": comp["id"],
                "party_number":          1,
                "slot_index":            2,
                "role":                  "Healer",
                "build_name":            "",
                "weapon_name":           None,
                "offhand_name":          None,
                "head_name":             None,
                "armor_name":            None,
                "shoes_name":            None,
                "cape_name":             None,
                "food_name":             None,
                "potion_name":           None,
                "albion_build_id":       None,
                "doctrine_role":         None,
                "priority":              "normal",
                "created_at":            now,
                "updated_at":            now,
            }])

        client = TestClient(app)
        _login(client, "P2Open1Owner")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        # cb-badge--open should appear as rendered HTML for this open slot
        # (not just as a JS string literal — we look for the rendered OPEN text)
        assert "OPEN" in resp.text
        assert "cb-slot-card--open" in resp.text

    def test_assigned_slots_have_assigned_state_class(self):
        """Slots with build_name set render with cb-slot-card--assigned or --core class."""
        client, _owner, ws, comp = _make_setup("P2Assigned1", "p2-assigned-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        # _DEFAULT_SLOTS has core-priority slots → cb-slot-card--core expected
        assert "cb-slot-card--core" in resp.text

    def test_party_header_shows_tally(self):
        """Party header renders cb-tally-item elements for present role families."""
        client, _owner, ws, comp = _make_setup("P2Tally1", "p2-tally-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-tally-item" in resp.text
        # _DEFAULT_SLOTS has tank, healer, dps → tally shows T, H, D
        assert 'data-role="tank"' in resp.text
        assert 'data-role="healer"' in resp.text
        assert 'data-role="dps"' in resp.text

    def test_form_inputs_have_name_attributes(self):
        """All required form inputs carry correct name attributes for POST submission."""
        client, _owner, ws, comp = _make_setup("P2Names1", "p2-names-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        # The parallel-list names the POST handler reads
        assert 'name="role"' in resp.text
        assert 'name="build_name"' in resp.text
        assert 'name="party_number"' in resp.text
        assert 'name="slot_index"' in resp.text
        assert 'name="priority"' in resp.text

    def test_form_inputs_have_aria_labels(self):
        """Form inputs carry aria-label attributes for keyboard/screen-reader access."""
        client, _owner, ws, comp = _make_setup("P2Aria1", "p2-aria-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert 'aria-label="Role' in resp.text
        assert 'aria-label="Build name"' in resp.text
        assert 'aria-label="Party number"' in resp.text

    def test_post_submission_still_works_via_card_layout(self):
        """POST /slots replaces slot templates; card system does not break form semantics."""
        client, owner, ws, comp = _make_setup("P2Post1", "p2-post-1")
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slots",
            data={
                "role":         ["Support", "Healer"],
                "build_name":   ["Lute", "Fallen Staff"],
                "weapon_name":  ["", ""],
                "party_number": ["1", "1"],
                "slot_index":   ["1", "2"],
                "priority":     ["normal", "core"],
            },
            follow_redirects=False,
        )
        # Must redirect (302 or 303) on success
        assert resp.status_code in (302, 303)

        # Verify the new slots are persisted
        from app import database, repositories
        with database.transaction() as db:
            saved = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        roles = {s["role"] for s in saved}
        assert "Support" in roles
        assert "Healer" in roles
        # Old slots gone
        assert "Tank" not in roles
        assert "DPS" not in roles

    def test_composition_editor_class_present(self):
        """.cb-composition-editor wrapper renders in edit template."""
        client, _owner, ws, comp = _make_setup("P2Editor1", "p2-editor-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-composition-editor" in resp.text

    def test_add_party_button_present(self):
        """+ New party button is rendered in the edit template."""
        client, _owner, ws, comp = _make_setup("P2NewParty1", "p2-newparty-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "New party" in resp.text

    def test_no_operation_slots_mutated_after_card_edit(self):
        """POST via card layout does not mutate frozen operation_slots."""
        owner = make_user("P2Frozen1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p2-frozen-1")
        comp  = make_composition(ws["id"], slots=_DEFAULT_SLOTS)

        op = make_operation(ws["id"], title="P2 Op Frozen", start="2026-07-01T20:00:00+00:00")
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        client = TestClient(app)
        _login(client, "P2Frozen1Owner")

        # POST card-style form data
        client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slots",
            data={
                "role":         ["Ranged DPS"],
                "build_name":   ["Warbow"],
                "weapon_name":  [""],
                "party_number": ["1"],
                "slot_index":   ["1"],
                "priority":     ["normal"],
            },
            follow_redirects=False,
        )

        from app import database, repositories
        with database.transaction() as db:
            op_slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        op_builds = {s["build_name"] for s in op_slots}

        # Operation still has original frozen data
        assert "1H Mace" in op_builds
        assert "Warbow" not in op_builds
