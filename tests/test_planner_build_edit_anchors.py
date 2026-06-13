"""Phase 8 Slice 3 — Complete Planner Anchor Coverage.

Extends the S1 scroll-anchor pattern to the two remaining planner
mutation routes that previously redirected to the top of the page.

Covers:
  Group 1 — post_update_slot_build
               a) success redirects to #party-N
               b) anchor reflects correct party in multi-party operation
               c) redirect still targets /planner
               d) missing build_name early guard redirects cleanly (no anchor, no crash)

  Group 2 — post_apply_slot_to_template
               a) success redirects to #party-N
               b) anchor reflects correct party in multi-party operation
               c) redirect still targets /planner
               d) no-source-template error redirect includes anchor
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

def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _setup(slug: str, *, parties: int = 1, slots_per_party: int = 2):
    """
    Create workspace → composition (N parties × M slots) → operation
    → published → slots generated.
    Returns (owner, ws, op, slots).
    """
    owner = make_user(f"Owner-{slug}")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    slot_specs = [
        {
            "party_number": p + 1,
            "slot_index":   s + 1,
            "role":         "Healer",
            "build_name":   f"Build-P{p+1}S{s+1}",
            "priority":     "core",
        }
        for p in range(parties)
        for s in range(slots_per_party)
    ]
    comp = make_composition(ws["id"], name=f"Comp-{slug}", slots=slot_specs)
    op   = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    with database.transaction() as db:
        slots = repositories.get_operation_slots(db, op["id"], ws["id"])
    return owner, ws, op, slots


# ---------------------------------------------------------------------------
# Group 1 — post_update_slot_build
# ---------------------------------------------------------------------------

class TestBuildEditAnchor:

    def _setup_client(self, slug: str, *, parties: int = 1):
        owner, ws, op, slots = _setup(slug, parties=parties)
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        return client, ws, op, slots

    def test_success_redirects_to_party_anchor(self):
        client, ws, op, slots = self._setup_client("be-anchor-1")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/build",
            data={"build_name": "New Build", "weapon_name": "New Weapon"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_anchor_reflects_correct_party_in_multi_party_op(self):
        client, ws, op, slots = self._setup_client("be-mp-1", parties=3)
        party3_slot = next(s for s in slots if s["party_number"] == 3)

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{party3_slot['id']}/build",
            data={"build_name": "Party3 Build"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "#party-3" in location
        assert "#party-1" not in location
        assert "#party-2" not in location

    def test_redirect_still_targets_planner(self):
        client, ws, op, slots = self._setup_client("be-base-1")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/build",
            data={"build_name": "Some Build"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/planner" in resp.headers["location"]

    def test_missing_build_name_early_guard_redirects_cleanly(self):
        """Early guard fires before slot fetch — no anchor, but no crash either."""
        client, ws, op, slots = self._setup_client("be-guard-1")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/build",
            data={"build_name": ""},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        # Guard fires before slot fetch so no anchor expected — must not crash
        assert "/planner" in location
        assert "error" in location


# ---------------------------------------------------------------------------
# Group 2 — post_apply_slot_to_template
# ---------------------------------------------------------------------------

class TestApplyToTemplateAnchor:

    def _setup_client(self, slug: str, *, parties: int = 1):
        owner, ws, op, slots = _setup(slug, parties=parties)
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        return client, ws, op, slots

    def test_success_redirects_to_party_anchor(self):
        client, ws, op, slots = self._setup_client("att-anchor-1")
        slot = slots[0]
        # slot has source_composition_slot_template_id from generate_operation_slots

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_anchor_reflects_correct_party_in_multi_party_op(self):
        client, ws, op, slots = self._setup_client("att-mp-1", parties=3)
        party2_slot = next(s for s in slots if s["party_number"] == 2)

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{party2_slot['id']}/apply-to-template",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "#party-2" in location
        assert "#party-1" not in location
        assert "#party-3" not in location

    def test_redirect_still_targets_planner(self):
        client, ws, op, slots = self._setup_client("att-base-1")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/planner" in resp.headers["location"]

    def test_no_source_template_error_includes_anchor(self):
        """Slot with no source_composition_slot_template_id → error redirect
        still includes the anchor so the officer stays at the right party."""
        client, ws, op, slots = self._setup_client("att-nosrc-1")
        slot = slots[0]

        # Clear the source template link directly in the DB to simulate the condition.
        with database.transaction() as db:
            db.execute(
                "UPDATE operation_slots SET source_composition_slot_template_id = NULL WHERE id = ?",
                (slot["id"],),
            )

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/apply-to-template",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location
        assert "error" in location
