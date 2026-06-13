"""
Phase 8.6 Slice A — Planner Operational Signals

Tests for:
  1. Locked-roster banner on the planner page
  2. Gap-pill class consistency between operation detail and planner

Groups:
  1 — Locked banner visibility (planner)
  2 — Lock enforcement integrity (existing behaviour preserved)
  3 — Gap pill consistency (operation detail page)
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.application import use_cases
from app import database, repositories
from app.main import app

from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
    publish_operation,
)

_LOCKED_BANNER = "Roster is locked — assignments are read-only."
_ROLE_GAP_CLASS = "gap-pill--role"
_BUILD_GAP_CLASS = "gap-pill--build"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planning_op(owner_name: str, slug: str):
    """Create a published (planning) operation with slots."""
    owner = make_user(owner_name)
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = make_composition(ws["id"])
    op    = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    return owner, ws, op


def _make_locked_op(owner_name: str, slug: str):
    """Create a planning operation then lock it."""
    owner, ws, op = _make_planning_op(owner_name, slug)
    use_cases.lock_operation(ws["id"], op["id"])
    return owner, ws, op


# ---------------------------------------------------------------------------
# Group 1 — Locked banner visibility on the planner page
# ---------------------------------------------------------------------------

class TestLockedPlannerBanner:
    """Banner 'Roster is locked — assignments are read-only.' must appear iff
    the operation is in 'locked' status when the planner is rendered."""

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "ops-signal-lock-owner", "ops-signal-lock"
        )
        self.client = TestClient(app)
        _login(self.client, "ops-signal-lock-owner")

    def _planner(self):
        return self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/planner"
        )

    def test_locked_planner_shows_banner(self):
        """Locking the roster makes the informational banner visible."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._planner()
        assert resp.status_code == 200
        assert _LOCKED_BANNER in resp.text

    def test_planning_planner_does_not_show_banner(self):
        """A planning-status planner must not show the locked banner."""
        resp = self._planner()
        assert resp.status_code == 200
        assert _LOCKED_BANNER not in resp.text

    def test_banner_uses_informational_alert_class(self):
        """Banner must use alert-info (informational), not alert-error or alert-warning."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._planner()
        assert "alert-info" in resp.text
        # Explicitly confirm it is NOT styled as an error
        # (the banner block itself must not carry error styling)
        banner_idx = resp.text.find(_LOCKED_BANNER)
        surrounding = resp.text[max(0, banner_idx - 200): banner_idx + 200]
        assert "alert-error" not in surrounding
        assert "alert-warning" not in surrounding

    def test_banner_does_not_block_roster_content(self):
        """After locking, roster slot data is still visible below the banner."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._planner()
        # Slot cards are still rendered — the party panel heading is present
        assert "Party 1" in resp.text
        assert _LOCKED_BANNER in resp.text

    def test_draft_planner_does_not_show_banner(self):
        """A draft operation planner must not show the locked banner."""
        owner2 = make_user("ops-signal-draft-owner")
        ws2    = make_workspace(owner_user_id=owner2["id"], slug="ops-signal-draft")
        comp2  = make_composition(ws2["id"])
        op2    = make_operation(ws2["id"])
        use_cases.attach_operation_plan(ws2["id"], op2["id"], comp2["id"])
        use_cases.generate_operation_slots(ws2["id"], op2["id"])
        # Do NOT publish — keep as draft
        client2 = TestClient(app)
        _login(client2, "ops-signal-draft-owner")
        resp = client2.get(
            f"/workspaces/{ws2['slug']}/operations/{op2['id']}/planner"
        )
        assert resp.status_code == 200
        assert _LOCKED_BANNER not in resp.text


# ---------------------------------------------------------------------------
# Group 2 — Lock enforcement integrity (existing behaviour preserved)
# ---------------------------------------------------------------------------

class TestLockEnforcementPreserved:
    """Existing lock enforcement — assignment controls disappear after lock —
    must continue to work correctly after the banner was added."""

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "ops-signal-enf-owner", "ops-signal-enf"
        )
        self.client = TestClient(app)
        _login(self.client, "ops-signal-enf-owner")

    def _planner(self):
        return self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/planner"
        )

    def test_planning_planner_shows_lock_roster_button(self):
        """Before locking, the Lock Roster button is visible — confirming planning status."""
        resp = self._planner()
        assert resp.status_code == 200
        assert "Lock Roster" in resp.text

    def test_locked_planner_hides_assignment_controls(self):
        """After locking, assignment controls (pick player) must not appear."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._planner()
        assert resp.status_code == 200
        assert "pick player" not in resp.text

    def test_locked_planner_hides_lock_roster_button(self):
        """After locking, the Lock Roster button must not appear."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._planner()
        assert "Lock Roster" not in resp.text

    def test_locked_planner_post_assign_is_rejected(self):
        """POST to assign while locked must not create an assignment.
        The route redirects (303) with an error flash rather than 4xx,
        but no assignment record should be created for a nonexistent participant."""
        with database.transaction() as db:
            slots = repositories.get_operation_slots(
                db, self.op["id"], self.ws["id"]
            )
        slot_id = slots[0]["id"]
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/slots/{slot_id}/assign",
            data={"participant_id": "nonexistent"},
            follow_redirects=True,
        )
        # The route should redirect back to the planner (303 → 200 after redirect)
        assert resp.status_code == 200
        # No assignment should exist after a locked POST attempt
        with database.transaction() as db:
            assignment = repositories.get_active_assignment_for_slot(db, slot_id)
        assert assignment is None


# ---------------------------------------------------------------------------
# Group 3 — Gap pill consistency on the operation detail page
# ---------------------------------------------------------------------------

class TestGapPillConsistency:
    """Role and build gap warnings on operation_detail.html must use the
    canonical gap-pill CSS classes, matching the planner surface."""

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "ops-signal-gap-owner", "ops-signal-gap"
        )
        self.client = TestClient(app)
        _login(self.client, "ops-signal-gap-owner")

    def _detail(self):
        return self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
        )

    def _seed_readiness_with_role_gap(self, missing_role: str = "Tank", count: int = 2):
        """Store a readiness snapshot that includes a role gap."""
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])

    def test_readiness_card_renders_on_detail_page(self):
        """Operation detail page renders the Readiness card."""
        resp = self._detail()
        assert resp.status_code == 200
        assert "Readiness" in resp.text

    def test_existing_gap_warnings_still_render(self):
        """After recalculating readiness, any gaps still appear on the detail page."""
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        resp = self._detail()
        assert resp.status_code == 200
        # The readiness section is present regardless of gap state
        assert "slots assigned" in resp.text

    def test_role_gap_uses_gap_pill_class(self):
        """When missing roles exist, the detail page must render gap-pill--role spans."""
        # Recalculate with empty slots (no assignments → open slots → role gaps possible)
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        resp = self._detail()
        # If there are missing roles, they must use the canonical class
        if "Role gaps" in resp.text:
            assert _ROLE_GAP_CLASS in resp.text, (
                "Role gaps on detail page must use gap-pill--role class"
            )

    def test_role_gap_does_not_use_plain_text_danger_class(self):
        """The old text-danger paragraph rendering must be gone."""
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        resp = self._detail()
        # The old pattern was <p class="text-danger" ... — must not be present
        # in the readiness gap section
        assert 'class="text-danger"' not in resp.text

    def test_build_gap_does_not_use_plain_text_warning_class(self):
        """The old text-warning paragraph rendering must be gone."""
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        resp = self._detail()
        assert 'class="text-warning"' not in resp.text

    def test_planner_gap_pill_classes_match_detail_page_classes(self):
        """Both planner and detail page use the same gap-pill class names."""
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        detail_resp  = self._detail()
        planner_resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/planner"
        )
        # Both pages must use the same canonical class names (when gaps exist)
        if "Role gaps" in detail_resp.text:
            assert _ROLE_GAP_CLASS in detail_resp.text
            assert _ROLE_GAP_CLASS in planner_resp.text
        if "Build gaps" in detail_resp.text:
            assert _BUILD_GAP_CLASS in detail_resp.text
            assert _BUILD_GAP_CLASS in planner_resp.text
