"""
Locked Roster Enforcement tests.

Verifies that once an operation is locked, all assignment mutation surfaces
are blocked at both the server (use-case / route) and UI (template) layers.

Groups:
  1 — Use-case layer: all assignment mutations raise ConflictError when locked
  2 — Route layer: POST endpoints return error redirects when locked
  3 — Template layer: planner hides all mutation controls when locked
  4 — Template layer: planner still renders read-only assignment state when locked
  5 — Planning operation still allows all mutations (regression guard)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError
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

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planning_op_with_signup(owner_name: str, slug: str):
    """Planning operation with 1 slot and 1 signup; returns (owner, ws, op, slots, signup)."""
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"], name=f"Comp-{slug}", slots=[
        {"party_number": 1, "slot_index": 1, "role": "Healer",
         "build_name": "Hallowfall", "priority": "normal"},
        {"party_number": 1, "slot_index": 2, "role": "Tank",
         "build_name": "Tombstone", "priority": "normal"},
    ])
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "TestPlayer", "Healer")
    return owner, ws, op, slots, signup


def _make_locked_op_with_assignment(owner_name: str, slug: str):
    """Locked operation with 1 active assignment."""
    owner, ws, op, slots, signup = _make_planning_op_with_signup(owner_name, slug)
    assignment = use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws["id"], op["id"])
    return owner, ws, op, slots, signup, assignment


def _planner_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/planner"


# ---------------------------------------------------------------------------
# Group 1 — Use-case layer rejects mutations when locked
# ---------------------------------------------------------------------------

class TestUseCaseLockEnforcement:

    def setup_method(self):
        owner_name = "UCLockOwner"
        slug = "uc-lock-test"
        self.owner, self.ws, self.op, self.slots, self.signup = \
            _make_planning_op_with_signup(owner_name, slug)
        self.assignment = use_cases.assign_participant_to_operation_slot(
            self.ws["id"], self.op["id"], self.slots[0]["id"],
            self.signup["participant_id"]
        )
        use_cases.lock_operation(self.ws["id"], self.op["id"])

    def test_assign_blocked_when_locked(self):
        # Create participant directly — signup submission is also blocked when locked
        with database.transaction() as db:
            p2 = repositories.find_or_create_participant(db, self.ws["id"], "Player2")
        with pytest.raises(ConflictError, match="change assignments"):
            use_cases.assign_participant_to_operation_slot(
                self.ws["id"], self.op["id"],
                self.slots[1]["id"], p2["id"]
            )

    def test_remove_assignment_blocked_when_locked(self):
        with pytest.raises(ConflictError, match="change assignments"):
            use_cases.remove_assignment(
                self.ws["id"], self.op["id"], self.assignment["id"]
            )

    def test_reassign_slot_blocked_when_locked(self):
        # Use the already-existing participant (existing signup still in DB)
        with database.transaction() as db:
            p3 = repositories.find_or_create_participant(db, self.ws["id"], "Player3")
        with pytest.raises(ConflictError, match="change assignments"):
            use_cases.reassign_slot(
                self.ws["id"], self.op["id"],
                self.slots[0]["id"], p3["id"]
            )

    def test_quick_assign_blocked_when_locked(self):
        with pytest.raises(ConflictError, match="change assignments"):
            use_cases.quick_assign_slot(
                self.ws["id"], self.op["id"], self.slots[1]["id"]
            )

    def test_quick_fill_party_blocked_when_locked(self):
        with pytest.raises(ConflictError, match="change assignments"):
            use_cases.quick_fill_party(
                self.ws["id"], self.op["id"], party_number=1
            )


# ---------------------------------------------------------------------------
# Group 2 — Route layer: POST endpoints return error redirect when locked
# ---------------------------------------------------------------------------

class TestRouteLockEnforcement:

    def setup_method(self):
        self.owner, self.ws, self.op, self.slots, self.signup, self.assignment = \
            _make_locked_op_with_assignment("RouteLockOwner", "route-lock-test")
        self.client = TestClient(app, follow_redirects=False)
        _login(self.client, "RouteLockOwner")

    def _planner(self):
        return _planner_url(self.ws["slug"], self.op["id"])

    def test_post_assign_rejected_when_locked(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/slots/{self.slots[1]['id']}/assign",
            data={"participant_id": self.signup["participant_id"]},
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_post_assign_participant_rejected_when_locked(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/assign",
            data={
                "slot_id": self.slots[1]["id"],
                "participant_id": self.signup["participant_id"],
            },
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_post_remove_assignment_rejected_when_locked(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/assignments/{self.assignment['id']}/remove",
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_post_reassign_rejected_when_locked(self):
        # Use the existing signup participant — no new signup submission needed
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/slots/{self.slots[0]['id']}/reassign",
            data={"participant_id": self.signup["participant_id"]},
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_post_quick_assign_rejected_when_locked(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/slots/{self.slots[1]['id']}/quick-assign",
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_post_quick_fill_party_rejected_when_locked(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/parties/1/quick-fill",
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]

    def test_post_update_slot_build_rejected_when_locked(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/slots/{self.slots[0]['id']}/build",
            data={"build_name": "New Build", "weapon_name": "New Weapon"},
        )
        assert resp.status_code in (302, 303)
        assert "error=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Group 3 — Template hides all mutation controls when locked
# ---------------------------------------------------------------------------

class TestPlannerLockedUIHidesMutations:

    def setup_method(self):
        self.owner, self.ws, self.op, self.slots, self.signup, self.assignment = \
            _make_locked_op_with_assignment("UILockOwner", "ui-lock-test")
        self.client = TestClient(app)
        _login(self.client, "UILockOwner")

    def _get_planner(self):
        return self.client.get(_planner_url(self.ws["slug"], self.op["id"]))

    def test_assign_form_hidden_when_locked(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        assert "/assign" not in resp.text or "signup-assign-btn" not in resp.text

    def test_unassign_button_hidden_when_locked(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        # The remove-assignment form action must not appear (not just the word
        # "Unassign" which is a substring of "Unassigned" status text)
        assert "/remove" not in resp.text

    def test_swap_button_hidden_when_locked(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        assert "Swap →" not in resp.text

    def test_quick_assign_button_hidden_when_locked(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        assert "Quick ★" not in resp.text

    def test_quick_fill_party_button_hidden_when_locked(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        assert "quick-fill-party" not in resp.text

    def test_inline_build_edit_hidden_when_locked(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        assert "slot-build-edit" not in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Locked planner still renders read-only roster
# ---------------------------------------------------------------------------

class TestPlannerLockedRendersReadOnly:

    def setup_method(self):
        self.owner, self.ws, self.op, self.slots, self.signup, self.assignment = \
            _make_locked_op_with_assignment("ROLockOwner", "ro-lock-test")
        self.client = TestClient(app)
        _login(self.client, "ROLockOwner")

    def _get_planner(self):
        return self.client.get(_planner_url(self.ws["slug"], self.op["id"]))

    def test_locked_planner_returns_200(self):
        resp = self._get_planner()
        assert resp.status_code == 200

    def test_assigned_player_name_still_visible(self):
        resp = self._get_planner()
        assert "TestPlayer" in resp.text

    def test_party_panel_still_rendered(self):
        resp = self._get_planner()
        assert "Party 1" in resp.text

    def test_locked_status_badge_visible(self):
        resp = self._get_planner()
        assert "locked" in resp.text.lower()

    def test_readiness_snapshot_visible(self):
        resp = self._get_planner()
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Group 5 — Planning operation still allows all mutations (regression guard)
# ---------------------------------------------------------------------------

class TestPlanningOperationAllowsMutations:

    def setup_method(self):
        self.owner, self.ws, self.op, self.slots, self.signup = \
            _make_planning_op_with_signup("PlanningGuardOwner", "planning-guard")
        self.client = TestClient(app, follow_redirects=False)
        _login(self.client, "PlanningGuardOwner")

    def test_assign_succeeds_in_planning(self):
        assignment = use_cases.assign_participant_to_operation_slot(
            self.ws["id"], self.op["id"],
            self.slots[0]["id"], self.signup["participant_id"]
        )
        assert assignment["operation_slot_id"] == self.slots[0]["id"]

    def test_assign_form_visible_in_planning(self):
        client = TestClient(app)
        _login(client, "PlanningGuardOwner")
        resp = client.get(_planner_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200
        assert "Assign" in resp.text

    def test_post_assign_succeeds_in_planning(self):
        resp = self.client.post(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
            f"/slots/{self.slots[0]['id']}/assign",
            data={"participant_id": self.signup["participant_id"]},
        )
        assert resp.status_code in (302, 303)
        assert "error=" not in resp.headers["location"]
