"""
"New operation from composition" shortcut tests (Slice 4).

Covers:
  Group 1 — GET /operations/new with ?composition_id= query param
  Group 2 — POST /operations with composition_id hidden field
  Group 3 — Template affordances on compositions_detail.html
  Group 4 — Snapshot invariant: operation_slots correctly frozen after auto-attach

Intentionally NOT covered here:
  - Full HTML snapshot assertions
  - CSS layout or visual styling
  - JavaScript behavior
  - Attachment of signup_status / notes via the shortcut (uses defaults)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _setup(slug: str) -> tuple[TestClient, dict, dict, dict]:
    """Returns (client, owner, ws, comp) — active (non-retired) composition."""
    owner = make_user(f"owner-{slug}")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = make_composition(ws["id"], name="ZvZ Comp")
    client = TestClient(app)
    _login(client, f"owner-{slug}")
    return client, owner, ws, comp


def _get_plan(ws_id: str, op_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_operation_plan(db, op_id, ws_id)


def _get_slots(ws_id: str, op_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_operation_slots(db, op_id, ws_id)


# ---------------------------------------------------------------------------
# Group 1 — GET /operations/new with ?composition_id= query param
# ---------------------------------------------------------------------------

class TestGetNewOperationPreset:
    """GET /operations/new renders preset_comp block when composition_id is valid."""

    def test_valid_composition_id_shows_comp_name(self):
        client, _, ws, comp = _setup("gnoc-get-1")
        resp = client.get(
            f"/workspaces/gnoc-get-1/operations/new?composition_id={comp['id']}"
        )
        assert resp.status_code == 200
        assert comp["name"] in resp.text

    def test_valid_composition_id_renders_hidden_field(self):
        client, _, ws, comp = _setup("gnoc-get-2")
        resp = client.get(
            f"/workspaces/gnoc-get-2/operations/new?composition_id={comp['id']}"
        )
        assert resp.status_code == 200
        assert f'name="composition_id"' in resp.text
        assert f'value="{comp["id"]}"' in resp.text

    def test_valid_composition_shows_attach_hint(self):
        client, _, ws, comp = _setup("gnoc-get-3")
        resp = client.get(
            f"/workspaces/gnoc-get-3/operations/new?composition_id={comp['id']}"
        )
        assert resp.status_code == 200
        assert "will be attached after the operation is created" in resp.text

    def test_retired_composition_id_ignored_gracefully(self):
        owner = make_user("owner-gnoc-ret")
        ws    = make_workspace(owner_user_id=owner["id"], slug="gnoc-get-ret")
        comp  = make_composition(ws["id"])
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])
        client = TestClient(app)
        _login(client, "owner-gnoc-ret")
        resp = client.get(
            f"/workspaces/gnoc-get-ret/operations/new?composition_id={comp['id']}"
        )
        assert resp.status_code == 200
        assert f'value="{comp["id"]}"' not in resp.text
        assert "will be attached after the operation is created" not in resp.text

    def test_nonexistent_composition_id_ignored_gracefully(self):
        client, _, ws, _ = _setup("gnoc-get-missing")
        resp = client.get(
            f"/workspaces/gnoc-get-missing/operations/new?composition_id=does-not-exist"
        )
        assert resp.status_code == 200
        assert "will be attached after the operation is created" not in resp.text

    def test_cross_workspace_composition_id_ignored(self):
        """A valid composition in another workspace must not be accepted."""
        owner1 = make_user("owner-ws1-xws")
        ws1    = make_workspace(owner_user_id=owner1["id"], slug="gnoc-xws-1")
        comp1  = make_composition(ws1["id"], name="WS1 Comp")

        owner2 = make_user("owner-ws2-xws")
        ws2    = make_workspace(owner_user_id=owner2["id"], slug="gnoc-xws-2")

        client2 = TestClient(app)
        _login(client2, "owner-ws2-xws")
        resp = client2.get(
            f"/workspaces/gnoc-xws-2/operations/new?composition_id={comp1['id']}"
        )
        assert resp.status_code == 200
        assert comp1["name"] not in resp.text
        assert "will be attached after the operation is created" not in resp.text

    def test_absent_composition_id_renders_form_normally(self):
        client, _, ws, _ = _setup("gnoc-get-absent")
        resp = client.get(f"/workspaces/gnoc-get-absent/operations/new")
        assert resp.status_code == 200
        assert "will be attached after the operation is created" not in resp.text
        assert 'name="composition_id"' not in resp.text
        # Standard form fields must still be present
        assert 'name="title"' in resp.text
        assert 'name="operation_type"' in resp.text


# ---------------------------------------------------------------------------
# Group 2 — POST /operations with composition_id in form body
# ---------------------------------------------------------------------------

class TestPostCreateOperationWithPreset:
    """POST /operations auto-attaches composition when composition_id is present."""

    def _post(self, client: TestClient, slug: str, extra: dict | None = None) -> object:
        data = {
            "title":              "Saturday ZvZ",
            "operation_type":     "zvz",
            "scheduled_start_at": "2026-09-01T20:00",
        }
        if extra:
            data.update(extra)
        return client.post(
            f"/workspaces/{slug}/operations",
            data=data,
            follow_redirects=False,
        )

    def test_valid_composition_id_attaches_plan(self):
        client, _, ws, comp = _setup("gnoc-post-1")
        resp = self._post(client, "gnoc-post-1", {"composition_id": comp["id"]})
        # Should redirect to the new operation detail
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        # Strip query string before extracting op_id
        # URL shape: /workspaces/{slug}/operations/{op_id}?success=...
        op_id = location.split("?")[0].rstrip("/").split("/")[-1]
        plan = _get_plan(ws["id"], op_id)
        assert plan is not None
        assert plan["albion_composition_id"] == comp["id"]

    def test_valid_composition_id_redirects_with_success_message(self):
        client, _, ws, comp = _setup("gnoc-post-2")
        resp = self._post(client, "gnoc-post-2", {"composition_id": comp["id"]})
        assert resp.status_code in (302, 303)
        assert "success=" in resp.headers["location"]

    def test_invalid_composition_id_operation_still_created(self):
        client, _, ws, _ = _setup("gnoc-post-inv")
        resp = self._post(client, "gnoc-post-inv", {"composition_id": "not-a-real-id"})
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        # The error redirect still points to the operation detail, not the new form
        assert "/operations/" in location
        # Confirm operation was actually created by following the redirect
        follow = client.get(location, follow_redirects=True)
        assert follow.status_code == 200

    def test_invalid_composition_id_redirects_with_error_message(self):
        client, _, ws, _ = _setup("gnoc-post-err")
        resp = self._post(client, "gnoc-post-err", {"composition_id": "bad-id"})
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_retired_composition_id_operation_created_attach_skipped(self):
        owner = make_user("owner-post-ret")
        ws    = make_workspace(owner_user_id=owner["id"], slug="gnoc-post-ret")
        comp  = make_composition(ws["id"])
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])
        client = TestClient(app)
        _login(client, "owner-post-ret")
        resp = self._post(client, "gnoc-post-ret", {"composition_id": comp["id"]})
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/operations/" in location
        op_id = location.split("?")[0].rstrip("/").split("/")[-1]
        # Plan was NOT attached (composition is retired)
        plan = _get_plan(ws["id"], op_id)
        assert plan is None

    def test_absent_composition_id_creates_operation_without_plan(self):
        client, _, ws, _ = _setup("gnoc-post-nocomp")
        resp = self._post(client, "gnoc-post-nocomp")
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        op_id = location.rstrip("/").split("/")[-1]
        plan = _get_plan(ws["id"], op_id)
        assert plan is None

    def test_absent_composition_id_plain_redirect(self):
        """Without composition_id, the redirect is a plain URL (no ?success= or ?error=)."""
        client, _, ws, _ = _setup("gnoc-post-plain")
        resp = self._post(client, "gnoc-post-plain")
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "success=" not in location
        assert "error=" not in location


# ---------------------------------------------------------------------------
# Group 3 — Template affordances on compositions_detail.html
# ---------------------------------------------------------------------------

class TestCompositionDetailLinkAffordances:
    """compositions_detail.html New Operation link includes ?composition_id=."""

    def test_active_comp_link_includes_composition_id(self):
        client, _, ws, comp = _setup("gnoc-tmpl-1")
        resp = client.get(f"/workspaces/gnoc-tmpl-1/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert f"?composition_id={comp['id']}" in resp.text

    def test_active_comp_link_still_labeled_new_operation(self):
        client, _, ws, comp = _setup("gnoc-tmpl-2")
        resp = client.get(f"/workspaces/gnoc-tmpl-2/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "New Operation" in resp.text

    def test_retired_comp_hides_new_operation_button(self):
        owner = make_user("owner-tmpl-ret")
        ws    = make_workspace(owner_user_id=owner["id"], slug="gnoc-tmpl-ret")
        comp  = make_composition(ws["id"])
        use_cases.retire_composition(ws["id"], comp["id"], owner["id"])
        client = TestClient(app)
        _login(client, "owner-tmpl-ret")
        resp = client.get(f"/workspaces/gnoc-tmpl-ret/compositions/{comp['id']}")
        assert resp.status_code == 200
        # The guard {% if can_mutate and not comp.deleted_at %} hides the button
        assert f"?composition_id={comp['id']}" not in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Snapshot invariant
# ---------------------------------------------------------------------------

class TestSnapshotInvariantAfterAutoAttach:
    """operation_slots are frozen correctly when plan was attached via the shortcut."""

    def _create_op_with_plan(self, slug: str) -> tuple[dict, dict, dict]:
        """Create operation, auto-attach via POST, then publish + generate slots.
        Returns (ws, comp, op).
        """
        client, owner, ws, comp = _setup(slug)
        resp = client.post(
            f"/workspaces/{slug}/operations",
            data={
                "title":              "Saturday ZvZ",
                "operation_type":     "zvz",
                "scheduled_start_at": "2026-09-01T20:00",
                "composition_id":     comp["id"],
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        op_id = location.split("?")[0].rstrip("/").split("/")[-1]

        with database.transaction() as db:
            op = repositories.get_guild_operation(db, op_id, ws["id"])

        # Publish + generate slots exactly as the normal workflow does.
        use_cases.publish_operation(ws["id"], op_id)
        use_cases.generate_operation_slots(ws["id"], op_id)
        return ws, comp, op

    def test_operation_slots_generated_after_auto_attach(self):
        ws, comp, op = self._create_op_with_plan("gnoc-snap-1")
        slots = _get_slots(ws["id"], op["id"])
        assert len(slots) > 0

    def test_operation_slots_match_composition_templates(self):
        ws, comp, op = self._create_op_with_plan("gnoc-snap-2")
        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        slots = _get_slots(ws["id"], op["id"])
        assert len(slots) == len(templates)
        template_builds = {t["build_name"] for t in templates}
        slot_builds     = {s["build_name"] for s in slots}
        assert template_builds == slot_builds

    def test_editing_composition_after_auto_attach_does_not_change_slots(self):
        ws, comp, op = self._create_op_with_plan("gnoc-snap-3")
        slots_before = _get_slots(ws["id"], op["id"])

        # Modify the composition slot templates.
        # Use a fixed owner from the setup to provide actor_user_id.
        with database.transaction() as db:
            actor = db.execute(
                "SELECT id FROM users LIMIT 1"
            ).fetchone()
        replacement = [
            {"party_number": 1, "slot_index": i, "role": "Tank",
             "build_name": f"NewBuild-{i}", "priority": "core"}
            for i in range(1, len(slots_before) + 1)
        ]
        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=actor["id"],
            slots=replacement,
        )

        slots_after = _get_slots(ws["id"], op["id"])
        # operation_slots must be unchanged — frozen snapshot invariant
        assert [s["build_name"] for s in slots_before] == [
            s["build_name"] for s in slots_after
        ]
