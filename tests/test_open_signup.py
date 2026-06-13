"""
M1 — Open operation signup to authenticated non-members.

Covers:
  Group 1 — GET signup: non-member access
  Group 2 — POST signup: non-member submission
  Group 3 — Existing member / officer flows unchanged
  Group 4 — Auth guards (unauthenticated, bad workspace)
  Group 5 — Access context: non-member cannot see officer affordances

Invariants verified:
  - No workspace membership rows are created for signing-up non-members
  - Existing officer/member signup flows are unaffected
  - Non-members may withdraw their own signups (ownership verified by user ID)
  - Signup appears in the signups list after non-member submission
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_user, make_workspace, make_operation, publish_operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _signup_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/signup"


def _make_published_op(ws_id: str) -> dict:
    """Create and publish an operation so signups are open."""
    op = make_operation(ws_id)
    publish_operation(ws_id, op["id"])
    return op


# ---------------------------------------------------------------------------
# Group 1 — GET signup: non-member access
# ---------------------------------------------------------------------------

class TestGetSignupNonMember:

    def setup_method(self):
        self.owner    = make_user("opsignup-g1-owner")
        self.ws       = make_workspace(owner_user_id=self.owner["id"], slug="opsignup-g1")
        self.op       = _make_published_op(self.ws["id"])
        self.outsider = make_user("opsignup-g1-outsider")
        self.client   = TestClient(app)

    def test_non_member_gets_200(self):
        _login(self.client, "opsignup-g1-outsider")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200

    def test_non_member_sees_signup_form(self):
        _login(self.client, "opsignup-g1-outsider")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert 'name="display_name"' in resp.text
        assert 'name="preferred_role"' in resp.text

    def test_non_member_sees_existing_signups(self):
        # Officer submits a signup first.
        _login(self.client, "opsignup-g1-owner")
        self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={"display_name": "AlreadySigned", "preferred_role": "Tank",
                  "willingness": "fill", "availability": "confirmed"},
        )
        # Outsider loads the page and sees the existing signup.
        _login(self.client, "opsignup-g1-outsider")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert "AlreadySigned" in resp.text

    def test_non_member_does_not_see_ledger_tab(self):
        _login(self.client, "opsignup-g1-outsider")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        # Ledger tab is can_mutate-gated.
        assert "Ledger" not in resp.text

    def test_non_member_does_not_create_workspace_membership(self):
        _login(self.client, "opsignup-g1-outsider")
        self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        with database.transaction() as db:
            mem = repositories.get_workspace_membership(
                db, self.ws["id"], self.outsider["id"]
            )
        assert mem is None


# ---------------------------------------------------------------------------
# Group 2 — POST signup: non-member submission
# ---------------------------------------------------------------------------

class TestPostSignupNonMember:

    def setup_method(self):
        self.owner    = make_user("opsignup-g2-owner")
        self.ws       = make_workspace(owner_user_id=self.owner["id"], slug="opsignup-g2")
        self.op       = _make_published_op(self.ws["id"])
        self.outsider = make_user("opsignup-g2-outsider")
        self.client   = TestClient(app)

    def _post_signup(self, display_name: str, role: str = "Healer"):
        return self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={
                "display_name":       display_name,
                "preferred_role":     role,
                "preferred_build_name": "",
                "willingness":        "flexible",
                "availability":       "confirmed",
            },
            follow_redirects=True,
        )

    def test_non_member_signup_succeeds(self):
        _login(self.client, "opsignup-g2-outsider")
        resp = self._post_signup("AlliancePlayer")
        assert resp.status_code == 200

    def test_non_member_signup_recorded(self):
        _login(self.client, "opsignup-g2-outsider")
        self._post_signup("AlliancePlayer")
        with database.transaction() as db:
            signups = repositories.get_signups_with_display_names(
                db, self.op["id"], self.ws["id"]
            )
        names = [s["display_name"] for s in signups]
        assert "AlliancePlayer" in names

    def test_non_member_signup_appears_in_page(self):
        _login(self.client, "opsignup-g2-outsider")
        self._post_signup("AlliancePlayer")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert "AlliancePlayer" in resp.text

    def test_non_member_signup_flash_success(self):
        _login(self.client, "opsignup-g2-outsider")
        resp = self._post_signup("AlliancePlayer")
        assert "AlliancePlayer" in resp.text or "Signup recorded" in resp.text

    def test_non_member_duplicate_signup_rejected(self):
        _login(self.client, "opsignup-g2-outsider")
        self._post_signup("AlliancePlayer")
        resp = self._post_signup("AlliancePlayer")
        # Second signup should fail with an error flash.
        assert "error" in str(resp.url).lower() or "already" in resp.text.lower()

    def test_non_member_signup_does_not_create_membership(self):
        _login(self.client, "opsignup-g2-outsider")
        self._post_signup("AlliancePlayer")
        with database.transaction() as db:
            mem = repositories.get_workspace_membership(
                db, self.ws["id"], self.outsider["id"]
            )
        assert mem is None

    def test_signup_with_optional_build_name(self):
        _login(self.client, "opsignup-g2-outsider")
        resp = self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={
                "display_name":         "AlliancePlayer2",
                "preferred_role":       "Healer",
                "preferred_build_name": "T8.3 Hallowfall",
                "willingness":          "specific",
                "availability":         "confirmed",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with database.transaction() as db:
            signups = repositories.get_signups_with_display_names(
                db, self.op["id"], self.ws["id"]
            )
        builds = [s.get("preferred_build_name") for s in signups]
        assert "T8.3 Hallowfall" in builds


# ---------------------------------------------------------------------------
# Group 3 — Existing officer/member flows unchanged
# ---------------------------------------------------------------------------

class TestExistingFlowsUnchanged:

    def setup_method(self):
        self.owner  = make_user("opsignup-g3-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="opsignup-g3")
        self.op     = _make_published_op(self.ws["id"])
        self.member = make_user("opsignup-g3-member")
        use_cases.add_workspace_member(
            self.ws["id"], self.owner["id"], "opsignup-g3-member", "member"
        )
        self.client = TestClient(app)

    def test_owner_can_get_signup_page(self):
        _login(self.client, "opsignup-g3-owner")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200

    def test_member_can_get_signup_page(self):
        _login(self.client, "opsignup-g3-member")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200

    def test_member_can_post_signup(self):
        _login(self.client, "opsignup-g3-member")
        resp = self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={
                "display_name":   "opsignup-g3-member",
                "preferred_role": "Tank",
                "willingness":    "fill",
                "availability":   "confirmed",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with database.transaction() as db:
            signups = repositories.get_signups_with_display_names(
                db, self.op["id"], self.ws["id"]
            )
        assert any(s["display_name"] == "opsignup-g3-member" for s in signups)

    def test_owner_sees_ledger_tab(self):
        """Officers retain access to the officer-gated Ledger tab."""
        _login(self.client, "opsignup-g3-owner")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert "Ledger" in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Auth guards
# ---------------------------------------------------------------------------

class TestAuthGuards:

    def setup_method(self):
        self.owner  = make_user("opsignup-g4-owner")
        self.ws     = make_workspace(owner_user_id=self.owner["id"], slug="opsignup-g4")
        self.op     = _make_published_op(self.ws["id"])
        self.client = TestClient(app)

    def test_unauthenticated_get_redirects_to_login(self):
        resp = self.client.get(
            _signup_url(self.ws["slug"], self.op["id"]),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_unauthenticated_post_redirects_to_login(self):
        resp = self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={"display_name": "Ghost", "preferred_role": "Tank",
                  "willingness": "fill", "availability": "confirmed"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

    def test_nonexistent_workspace_returns_404(self):
        self.client.post(
            "/login",
            data={"display_name": "opsignup-g4-owner", "next": "/"},
            follow_redirects=True,
        )
        resp = self.client.get(
            f"/workspaces/this-slug-does-not-exist/operations/{self.op['id']}/signup"
        )
        assert resp.status_code == 404

    def test_nonexistent_operation_returns_404(self):
        _login(self.client, "opsignup-g4-owner")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/operations/00000000-0000-0000-0000-000000000000/signup"
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Group 5 — Access context: non-member officer affordances hidden
# ---------------------------------------------------------------------------

class TestNonMemberAccessContext:

    def setup_method(self):
        self.owner    = make_user("opsignup-g5-owner")
        self.ws       = make_workspace(owner_user_id=self.owner["id"], slug="opsignup-g5")
        self.op       = _make_published_op(self.ws["id"])
        self.outsider = make_user("opsignup-g5-outsider")
        self.client   = TestClient(app)

    def test_non_member_cannot_see_withdraw_button_for_others(self):
        """Withdraw button for other players is hidden when can_mutate=False."""
        # Owner signs up someone.
        _login(self.client, "opsignup-g5-owner")
        self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={"display_name": "SomePlayer", "preferred_role": "Tank",
                  "willingness": "fill", "availability": "confirmed"},
        )
        # Outsider views page — should NOT see the Withdraw button for SomePlayer.
        _login(self.client, "opsignup-g5-outsider")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        # The withdraw form only appears for can_mutate OR is_own.
        # Outsider is neither officer nor SomePlayer, so no button.
        assert "SomePlayer" in resp.text  # sees the row
        # The withdraw form submits to /signups/{id}/withdraw — not present for others
        assert "/withdraw" not in resp.text

    def test_non_member_sees_own_withdraw_button(self):
        """Non-members can withdraw their own signup (is_own check by display_name)."""
        _login(self.client, "opsignup-g5-outsider")
        self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={"display_name": "opsignup-g5-outsider", "preferred_role": "Healer",
                  "willingness": "flexible", "availability": "confirmed"},
        )
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert "/withdraw" in resp.text

    def test_officer_still_sees_withdraw_for_all(self):
        """Officers retain the ability to withdraw any signup."""
        _login(self.client, "opsignup-g5-outsider")
        self.client.post(
            _signup_url(self.ws["slug"], self.op["id"]),
            data={"display_name": "opsignup-g5-outsider", "preferred_role": "Healer",
                  "willingness": "flexible", "availability": "confirmed"},
        )
        _login(self.client, "opsignup-g5-owner")
        resp = self.client.get(_signup_url(self.ws["slug"], self.op["id"]))
        assert "/withdraw" in resp.text
