"""
M2 — Lock Roster confirmation dialog tests.

Verifies that the Lock Roster button carries a confirm() onclick guard in both:
  - operation_detail.html  (overview page)
  - operation_planner.html (planner page)

The button is only rendered when can_mutate=True AND operation.status='planning',
so tests set up a planning-status operation owned by an officer.

Groups:
  1 — operation_detail.html: confirm dialog present / absent
  2 — operation_planner.html: confirm dialog present / absent
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.application import use_cases
from app.main import app

from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
    publish_operation,
)

_CONFIRM_TEXT = "Lock the roster? Assignment mutations will be disabled"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planning_op(owner_name: str, slug: str):
    owner = make_user(owner_name)
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = make_composition(ws["id"])
    op    = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    return owner, ws, op


# ---------------------------------------------------------------------------
# Group 1 — operation_detail.html
# ---------------------------------------------------------------------------

class TestLockConfirmDetail:

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "lockconf-det-owner", "lockconf-det"
        )
        self.client = TestClient(app)
        _login(self.client, "lockconf-det-owner")

    def _get_detail(self):
        return self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}"
        )

    def test_lock_button_has_confirm_dialog(self):
        resp = self._get_detail()
        assert resp.status_code == 200
        assert _CONFIRM_TEXT in resp.text

    def test_lock_button_uses_return_confirm(self):
        resp = self._get_detail()
        assert "return confirm(" in resp.text

    def test_lock_button_confirm_message_mentions_mutations(self):
        resp = self._get_detail()
        assert "Assignment mutations" in resp.text

    def test_lock_button_confirm_message_mentions_undone(self):
        resp = self._get_detail()
        assert "cannot be undone" in resp.text

    def test_locked_op_does_not_show_lock_button(self):
        """Once locked, the Lock Roster button is not rendered — no confirm needed."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._get_detail()
        assert "Lock Roster" not in resp.text

    def test_draft_op_does_not_show_lock_button(self):
        """Draft operations show Publish, not Lock Roster."""
        owner2, ws2, _ = _make_planning_op("lockconf-det2-owner", "lockconf-det2")
        # Create a fresh draft op (without publishing).
        op_draft = make_operation(ws2["id"])
        client2 = TestClient(app)
        _login(client2, "lockconf-det2-owner")
        resp = client2.get(f"/workspaces/{ws2['slug']}/operations/{op_draft['id']}")
        assert "Lock Roster" not in resp.text


# ---------------------------------------------------------------------------
# Group 2 — operation_planner.html
# ---------------------------------------------------------------------------

class TestLockConfirmPlanner:

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "lockconf-plan-owner", "lockconf-plan"
        )
        self.client = TestClient(app)
        _login(self.client, "lockconf-plan-owner")

    def _get_planner(self):
        return self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/planner"
        )

    def test_lock_button_has_confirm_dialog(self):
        resp = self._get_planner()
        assert resp.status_code == 200
        assert _CONFIRM_TEXT in resp.text

    def test_lock_button_uses_return_confirm(self):
        resp = self._get_planner()
        assert "return confirm(" in resp.text

    def test_lock_button_confirm_message_mentions_mutations(self):
        resp = self._get_planner()
        assert "Assignment mutations" in resp.text

    def test_locked_op_does_not_show_lock_button_in_planner(self):
        """Once locked, the Lock Roster button is absent from the planner header."""
        use_cases.lock_operation(self.ws["id"], self.op["id"])
        resp = self._get_planner()
        assert "Lock Roster" not in resp.text
