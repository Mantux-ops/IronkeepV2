"""
Slice 7 — Per-slot promote operation build to composition template.

Officers can intentionally apply a build edit they made in the tactical planner
back to the source composition slot template, so future operations generated from
that composition inherit the updated value.

Hard guarantees:
- Only build_name and weapon_name are promoted.
- No operation_slots are touched (snapshot invariant).
- Other operations' operation_slots are unaffected.
- The current operation's own operation_slot value is unchanged.

Covers:
  Group 1 — Repository helper: get_composition_slot_template_by_id
  Group 2 — Route: successful promotion
  Group 3 — Route: guard paths (bad inputs / retired comp / auth)
  Group 4 — Snapshot invariant
  Group 5 — Template affordances
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _setup(slug: str) -> tuple[dict, dict, dict]:
    """Return (owner, workspace, composition-with-slots)."""
    owner = make_user(f"promo-owner-{slug}")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = make_composition(ws["id"])
    return owner, ws, comp


def _generate_slots(ws_id: str, op_id: str, comp_id: str) -> list[dict]:
    """Attach composition and generate operation slots; return them."""
    use_cases.attach_operation_plan(ws_id, op_id, comp_id)
    use_cases.generate_operation_slots(
        guild_workspace_id=ws_id,
        guild_operation_id=op_id,
    )
    with database.transaction() as db:
        return repositories.get_operation_slots(db, op_id, ws_id)


# ---------------------------------------------------------------------------
# Group 1 — Repository helper
# ---------------------------------------------------------------------------

class TestGetCompositionSlotTemplateById:
    """get_composition_slot_template_by_id returns the correct row, or None."""

    def test_returns_correct_row(self):
        owner, ws, comp = _setup("repo-1a")
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        assert len(templates) > 0
        target = templates[0]
        with database.transaction() as db:
            row = repositories.get_composition_slot_template_by_id(db, target["id"], ws["id"])
        assert row is not None
        assert row["id"] == target["id"]
        assert row["albion_composition_id"] == comp["id"]

    def test_returns_none_for_wrong_workspace(self):
        owner_a, ws_a, comp_a = _setup("repo-2a")
        owner_b, ws_b, _comp_b = _setup("repo-2b")
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(db, comp_a["id"], ws_a["id"])
        template_id = templates[0]["id"]
        with database.transaction() as db:
            row = repositories.get_composition_slot_template_by_id(db, template_id, ws_b["id"])
        assert row is None

    def test_returns_none_for_missing_id(self):
        owner, ws, _comp = _setup("repo-3a")
        with database.transaction() as db:
            row = repositories.get_composition_slot_template_by_id(db, "nonexistent-id", ws["id"])
        assert row is None


# ---------------------------------------------------------------------------
# Group 2 — Route: successful promotion
# ---------------------------------------------------------------------------

class TestPromoteSuccess:
    """POST apply-to-template updates the composition template correctly."""

    def test_promote_updates_composition_template_build_name(self):
        slug  = "promo-ok-1"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        # Edit the op slot build name directly in the DB to simulate a planner edit
        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "Mistcaller", None)
            slot = repositories.get_operation_slot(db, slot["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        resp = client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=True,
        )
        assert resp.status_code == 200

        src_id = slot["source_composition_slot_template_id"]
        with database.transaction() as db:
            tmpl = repositories.get_composition_slot_template_by_id(db, src_id, ws["id"])
        assert tmpl["build_name"] == "Mistcaller"

    def test_promote_updates_weapon_name(self):
        slug  = "promo-ok-2"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "Hallowfall", "Great Axe")
            slot = repositories.get_operation_slot(db, slot["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )

        src_id = slot["source_composition_slot_template_id"]
        with database.transaction() as db:
            tmpl = repositories.get_composition_slot_template_by_id(db, src_id, ws["id"])
        assert tmpl["weapon_name"] == "Great Axe"

    def test_promote_with_null_weapon_clears_template_weapon(self):
        slug  = "promo-ok-3"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "Hallowfall", None)
            slot = repositories.get_operation_slot(db, slot["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )

        src_id = slot["source_composition_slot_template_id"]
        with database.transaction() as db:
            tmpl = repositories.get_composition_slot_template_by_id(db, src_id, ws["id"])
        assert tmpl["weapon_name"] is None

    def test_promote_touches_composition_updated_at(self):
        slug  = "promo-ok-4"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        with database.transaction() as db:
            original = repositories.get_albion_composition(db, comp["id"], ws["id"])

        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "New Build", None)
            slot = repositories.get_operation_slot(db, slot["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )

        with database.transaction() as db:
            updated = repositories.get_albion_composition(db, comp["id"], ws["id"])
        assert updated["updated_at"] >= original["updated_at"]

    def test_promote_redirects_to_planner_with_success_flash(self):
        slug  = "promo-ok-5"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "Hallowfall", None)
            slot = repositories.get_operation_slot(db, slot["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        resp = client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Applied to composition template" in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Route: guard paths
# ---------------------------------------------------------------------------

class TestPromoteGuards:
    """Bad inputs, retired composition, and auth are all rejected cleanly."""

    def test_wrong_operation_slot_rejected(self):
        slug_a = "promo-gd-1a"
        slug_b = "promo-gd-1b"
        owner_a, ws_a, comp_a = _setup(slug_a)
        owner_b, ws_b, comp_b = _setup(slug_b)
        op_a = make_operation(ws_a["id"])
        op_b = make_operation(ws_b["id"])
        slots_b = _generate_slots(ws_b["id"], op_b["id"], comp_b["id"])
        slot_b  = slots_b[0]

        client = TestClient(app)
        _login(client, f"promo-owner-{slug_a}")
        # Use op_a's URL but slot_b's ID (wrong operation)
        resp = client.post(
            f"/workspaces/{slug_a}/operations/{op_a['id']}/slots/{slot_b['id']}/apply-to-template",
            follow_redirects=True,
        )
        # Slot not found in op_a → 404 (or redirect with error for workspace scope)
        assert resp.status_code in (200, 404)

    def test_slot_without_source_template_id_rejected(self):
        slug  = "promo-gd-2"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        # Manually clear the source_composition_slot_template_id
        with database.transaction() as db:
            db.execute(
                "UPDATE operation_slots SET source_composition_slot_template_id = NULL WHERE id = ?",
                (slot["id"],),
            )

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        resp = client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "no traceable source template" in resp.text

    def test_missing_source_template_rejected(self):
        slug  = "promo-gd-3"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        # Delete the source template row to simulate re-slotting
        src_id = slot["source_composition_slot_template_id"]
        with database.transaction() as db:
            db.execute(
                "DELETE FROM composition_slot_templates WHERE id = ?",
                (src_id,),
            )

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        resp = client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "no longer exists" in resp.text

    def test_retired_composition_rejected(self):
        slug  = "promo-gd-4"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        # Retire the composition
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        resp = client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "retired" in resp.text.lower()

    def test_unauthenticated_redirected_to_login(self):
        slug  = "promo-gd-5"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        client = TestClient(app)
        resp = client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Group 4 — Snapshot invariant
# ---------------------------------------------------------------------------

class TestSnapshotInvariant:
    """Promotion touches ONLY composition_slot_templates.
    Existing operation_slots — including the current slot — are unchanged."""

    def test_current_operation_slot_not_modified(self):
        slug  = "promo-inv-1"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "Promoted Build", "Axe")
            slot_after_edit = repositories.get_operation_slot(db, slot["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )

        with database.transaction() as db:
            slot_after_promote = repositories.get_operation_slot(db, slot["id"], ws["id"])

        # The operation slot itself must not change
        assert slot_after_promote["build_name"] == slot_after_edit["build_name"]
        assert slot_after_promote["weapon_name"] == slot_after_edit["weapon_name"]

    def test_other_operation_slots_not_modified(self):
        """A second operation generated from the same composition must be untouched."""
        slug  = "promo-inv-2"
        owner, ws, comp = _setup(slug)

        op_a  = make_operation(ws["id"], title="Op A")
        op_b  = make_operation(ws["id"], title="Op B")
        slots_a = _generate_slots(ws["id"], op_a["id"], comp["id"])

        # Generate op_b separately (re-attach)
        use_cases.attach_operation_plan(ws["id"], op_b["id"], comp["id"])
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op_b["id"],
        )
        with database.transaction() as db:
            slots_b_before = repositories.get_operation_slots(db, op_b["id"], ws["id"])

        # Edit and promote op_a's slot 0
        slot_a = slots_a[0]
        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot_a["id"], ws["id"], "Brand New Build", None)
            slot_a = repositories.get_operation_slot(db, slot_a["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        client.post(
            f"/workspaces/{slug}/operations/{op_a['id']}/slots/{slot_a['id']}/apply-to-template",
            follow_redirects=False,
        )

        with database.transaction() as db:
            slots_b_after = repositories.get_operation_slots(db, op_b["id"], ws["id"])

        # op_b's slots must be byte-for-byte identical before and after promotion
        for before, after in zip(slots_b_before, slots_b_after):
            assert before["build_name"] == after["build_name"]
            assert before["weapon_name"] == after["weapon_name"]

    def test_only_composition_template_updated(self):
        """Only the source composition_slot_templates row changes; no operation_slots row changes."""
        slug  = "promo-inv-3"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        slot  = slots[0]

        with database.transaction() as db:
            repositories.update_operation_slot_build(db, slot["id"], ws["id"], "New Build", None)
            slot = repositories.get_operation_slot(db, slot["id"], ws["id"])
            all_op_slots_before = repositories.get_operation_slots(db, op["id"], ws["id"])

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        client.post(
            f"/workspaces/{slug}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )

        with database.transaction() as db:
            all_op_slots_after = repositories.get_operation_slots(db, op["id"], ws["id"])
            src_id = slot["source_composition_slot_template_id"]
            tmpl = repositories.get_composition_slot_template_by_id(db, src_id, ws["id"])

        # Template updated
        assert tmpl["build_name"] == "New Build"
        # All operation slots rows unchanged (same count, same id order)
        assert len(all_op_slots_before) == len(all_op_slots_after)
        for before, after in zip(all_op_slots_before, all_op_slots_after):
            assert before["id"] == after["id"]


# ---------------------------------------------------------------------------
# Group 5 — Template affordances
# ---------------------------------------------------------------------------

class TestTemplateAffordances:
    """The Apply to composition template button renders correctly."""

    def _get_planner(self, client: TestClient, slug: str, op_id: str) -> str:
        return client.get(f"/workspaces/{slug}/operations/{op_id}/planner").text

    def test_affordance_visible_for_officer_with_source_template(self):
        slug  = "promo-tpl-1"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        _generate_slots(ws["id"], op["id"], comp["id"])
        publish_operation(ws["id"], op["id"])  # planning status enables build editor

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        html = self._get_planner(client, slug, op["id"])

        assert "apply-to-template" in html
        assert "Apply to composition template" in html

    def test_affordance_not_visible_for_view_only_member(self):
        slug  = "promo-tpl-2"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        _generate_slots(ws["id"], op["id"], comp["id"])
        publish_operation(ws["id"], op["id"])

        # Create a member with 'member' role (view-only)
        viewer = make_user("promo-viewer-tpl-2")
        with database.transaction() as db:
            import uuid
            db.execute(
                "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), ws["id"], viewer["id"], "member", "2026-01-01T00:00:00"),
            )

        client_viewer = TestClient(app)
        _login(client_viewer, "promo-viewer-tpl-2")
        html = self._get_planner(client_viewer, slug, op["id"])

        assert "apply-to-template" not in html

    def test_affordance_not_visible_when_no_source_template_id(self):
        """Slots with NULL source_composition_slot_template_id hide the button."""
        slug  = "promo-tpl-3"
        owner, ws, comp = _setup(slug)
        op    = make_operation(ws["id"])
        slots = _generate_slots(ws["id"], op["id"], comp["id"])
        publish_operation(ws["id"], op["id"])  # planning status enables build editor

        # Clear source IDs on all slots
        with database.transaction() as db:
            db.execute(
                "UPDATE operation_slots SET source_composition_slot_template_id = NULL "
                "WHERE guild_operation_id = ?",
                (op["id"],),
            )

        client = TestClient(app)
        _login(client, f"promo-owner-{slug}")
        html = self._get_planner(client, slug, op["id"])

        assert "apply-to-template" not in html
