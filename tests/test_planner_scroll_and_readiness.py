"""Phase 8 Slice 1 — Scroll Anchoring + Auto-Readiness on Assignment.

Covers:
  Group 1 — Template: party anchor ids
               a) planner renders id="party-N" on each party section
               b) multiple parties each get a distinct anchor

  Group 2 — Route anchors: assign redirects to #party-N
               a) post_assign redirects with #party-N
               b) post_assign_participant (op-level) redirects with #party-N
               c) post_reassign_slot redirects with #party-N
               d) post_remove_assignment redirects with #party-N
               e) post_quick_assign redirects with #party-N
               f) post_quick_fill_party redirects with #party-N

  Group 3 — Auto-readiness: snapshot created/updated on assign mutations
               a) readiness snapshot exists after assign
               b) readiness snapshot updates after unassign
               c) readiness snapshot updates after reassign
               d) assign_participant_to_operation_slot always recalculates

  Group 4 — Manual "Refresh Readiness" button still works
               a) button renders in planner for eligible operations
               b) posting to /readiness still recalculates and redirects

  Group 5 — "Recalculate Readiness" label renamed to "Refresh Readiness"
               a) template no longer contains "Recalculate Readiness"
               b) template contains "Refresh Readiness"
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
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

def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _setup(slug: str, *, parties: int = 1, slots_per_party: int = 2):
    """
    Create workspace → composition (N parties × M slots) → operation → plan
    → published → slots generated.
    Returns (owner, ws, op, slots).
    """
    owner = make_user(f"Owner-{slug}")
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    slot_specs = [
        {
            "party_number": p + 1,
            "slot_index": s + 1,
            "role": "Healer",
            "build_name": f"Build-P{p+1}S{s+1}",
            "priority": "core",
        }
        for p in range(parties)
        for s in range(slots_per_party)
    ]
    comp = make_composition(ws["id"], name=f"Comp-{slug}", slots=slot_specs)
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    return owner, ws, op, slots


def _signup(ws_id: str, op_id: str, name: str, role: str = "Healer") -> dict:
    return use_cases.submit_signup_intent(ws_id, op_id, name, role)


def _get_slots(op_id: str, ws_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_operation_slots(db, op_id, ws_id)


def _latest_snapshot(ws_id: str, op_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_latest_readiness_snapshot(db, op_id, ws_id)


def _get_assignment_by_slot(op_id: str, ws_id: str, slot_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_active_assignment_for_slot(db, slot_id)


# ---------------------------------------------------------------------------
# Group 1 — Template: party anchor ids
# ---------------------------------------------------------------------------

class TestPlannerPartyAnchors:

    def _render_planner(self, slug: str, parties: int = 1):
        owner, ws, op, _ = _setup(slug, parties=parties)
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        return resp, ws, op

    def test_single_party_renders_anchor(self):
        resp, _, _ = self._render_planner("sa-anchor-1", parties=1)
        assert resp.status_code == 200
        assert 'id="party-1"' in resp.text

    def test_multi_party_each_gets_distinct_anchor(self):
        resp, _, _ = self._render_planner("sa-anchor-2", parties=3)
        assert resp.status_code == 200
        assert 'id="party-1"' in resp.text
        assert 'id="party-2"' in resp.text
        assert 'id="party-3"' in resp.text


# ---------------------------------------------------------------------------
# Group 2 — Route anchors: assignment mutations redirect to #party-N
# ---------------------------------------------------------------------------

class TestAssignmentRedirectAnchors:

    def _setup_client(self, slug: str, *, parties: int = 1):
        owner, ws, op, slots = _setup(slug, parties=parties)
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        return client, ws, op, slots

    def test_post_assign_redirects_with_party_anchor(self):
        client, ws, op, slots = self._setup_client("ra-assign-1")
        s = _signup(ws["id"], op["id"], "PlayerA-assign1")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/assign",
            data={"participant_id": s["participant_id"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_post_assign_participant_redirects_with_party_anchor(self):
        """POST /operations/{op_id}/assign (form body slot_id) includes anchor."""
        client, ws, op, slots = self._setup_client("ra-assign-2")
        s = _signup(ws["id"], op["id"], "PlayerA-assign2")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assign",
            data={"slot_id": slot["id"], "participant_id": s["participant_id"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_post_reassign_slot_redirects_with_party_anchor(self):
        client, ws, op, slots = self._setup_client("ra-reassign-1")
        s_a = _signup(ws["id"], op["id"], "PlayerA-rsn")
        s_b = _signup(ws["id"], op["id"], "PlayerB-rsn")
        slot = slots[0]
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slot["id"], s_a["participant_id"]
        )

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/reassign",
            data={"participant_id": s_b["participant_id"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_post_remove_assignment_redirects_with_party_anchor(self):
        client, ws, op, slots = self._setup_client("ra-remove-1")
        s = _signup(ws["id"], op["id"], "PlayerA-rm")
        slot = slots[0]
        asgn = use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slot["id"], s["participant_id"]
        )

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assignments/{asgn['id']}/remove",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_post_quick_assign_redirects_with_party_anchor(self):
        client, ws, op, slots = self._setup_client("ra-qa-1")
        _signup(ws["id"], op["id"], "PlayerA-qa")
        slot = slots[0]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/quick-assign",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{slot['party_number']}" in location

    def test_post_quick_fill_party_redirects_with_party_anchor(self):
        client, ws, op, slots = self._setup_client("ra-qfp-1")
        _signup(ws["id"], op["id"], "PlayerA-qfp")
        party_number = slots[0]["party_number"]

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/parties/{party_number}/quick-fill",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        location = resp.headers["location"]
        assert "/planner" in location
        assert f"#party-{party_number}" in location

    def test_anchor_reflects_correct_party_for_multi_party_op(self):
        """Anchor targets party 2 when the assigned slot belongs to party 2."""
        client, ws, op, slots = self._setup_client("ra-mp-1", parties=2)
        party2_slot = next(s for s in slots if s["party_number"] == 2)
        s = _signup(ws["id"], op["id"], "PlayerParty2")

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{party2_slot['id']}/assign",
            data={"participant_id": s["participant_id"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "#party-2" in resp.headers["location"]
        assert "#party-1" not in resp.headers["location"]


# ---------------------------------------------------------------------------
# Group 3 — Auto-readiness: snapshot created/updated on assign mutations
# ---------------------------------------------------------------------------

class TestAutoReadiness:

    def test_readiness_snapshot_exists_after_assign(self):
        """assign_participant_to_operation_slot always creates a readiness snapshot."""
        _, ws, op, slots = _setup("ar-assign-1")
        s = _signup(ws["id"], op["id"], "PlayerR1")
        assert _latest_snapshot(ws["id"], op["id"]) is None

        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slots[0]["id"], s["participant_id"]
        )

        snap = _latest_snapshot(ws["id"], op["id"])
        assert snap is not None
        assert snap["assigned_slots"] == 1

    def test_readiness_snapshot_updates_after_unassign(self):
        """remove_assignment triggers a fresh snapshot reflecting the freed slot."""
        _, ws, op, slots = _setup("ar-unassign-1")
        s = _signup(ws["id"], op["id"], "PlayerR2")
        asgn = use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slots[0]["id"], s["participant_id"]
        )
        snap_before = _latest_snapshot(ws["id"], op["id"])
        assert snap_before["assigned_slots"] == 1

        use_cases.remove_assignment(ws["id"], op["id"], asgn["id"])

        snap_after = _latest_snapshot(ws["id"], op["id"])
        assert snap_after["assigned_slots"] == 0
        assert snap_after["open_slots"] >= 1

    def test_readiness_snapshot_updates_after_reassign(self):
        """reassign_slot recalculates; assigned count stays 1 after swap."""
        _, ws, op, slots = _setup("ar-reassign-1")
        s_a = _signup(ws["id"], op["id"], "PlayerRA")
        s_b = _signup(ws["id"], op["id"], "PlayerRB")
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slots[0]["id"], s_a["participant_id"]
        )

        use_cases.reassign_slot(
            ws["id"], op["id"], slots[0]["id"], s_b["participant_id"]
        )

        snap = _latest_snapshot(ws["id"], op["id"])
        assert snap is not None
        assert snap["assigned_slots"] == 1

    def test_assign_without_reserve_cleanup_still_recalculates(self):
        """
        Regression: assign_slot_to_participant previously only recalculated
        readiness when a reserve was cleaned up.  It must now always recalculate.
        """
        _, ws, op, slots = _setup("ar-norec-1")
        s = _signup(ws["id"], op["id"], "PlayerNoReserve")

        # Confirm no reserve exists — pure assign path.
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], slots[0]["id"], s["participant_id"]
        )

        snap = _latest_snapshot(ws["id"], op["id"])
        assert snap is not None
        assert snap["assigned_slots"] == 1


# ---------------------------------------------------------------------------
# Group 4 — Manual "Refresh Readiness" button still works
# ---------------------------------------------------------------------------

class TestManualRefreshReadinessButton:

    def _setup_client(self, slug: str):
        owner, ws, op, _ = _setup(slug)
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        return client, ws, op

    def test_refresh_readiness_button_renders_in_planner(self):
        client, ws, op = self._setup_client("rr-render-1")
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Refresh Readiness" in resp.text

    def test_manual_readiness_post_recalculates_and_redirects(self):
        """POST /readiness still creates a snapshot and redirects to planner."""
        client, ws, op = self._setup_client("rr-post-1")

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/readiness",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/planner" in resp.headers["location"]

        snap = _latest_snapshot(ws["id"], op["id"])
        assert snap is not None


# ---------------------------------------------------------------------------
# Group 5 — Label rename: "Recalculate" → "Refresh"
# ---------------------------------------------------------------------------

class TestReadinessLabelRename:

    def _render_planner(self, slug: str):
        owner, ws, op, _ = _setup(slug)
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        return client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )

    def test_old_label_absent(self):
        resp = self._render_planner("rl-old-1")
        assert resp.status_code == 200
        assert "Recalculate Readiness" not in resp.text

    def test_new_label_present(self):
        resp = self._render_planner("rl-new-1")
        assert resp.status_code == 200
        assert "Refresh Readiness" in resp.text
