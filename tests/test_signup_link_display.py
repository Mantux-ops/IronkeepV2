"""
Pre-weekend slice: Prominent Signup Link UX — tests.

Verifies that the operation overview page renders a shareable signup URL block
inside the Signups card, alongside the existing "Signup page →" link.

Groups:
  1 — URL block content and structure
  2 — Copy button presence
  3 — Existing "Signup page →" link unchanged
  4 — URL shown on both planning and draft operations (member can always share)
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


def _detail_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}"


# ---------------------------------------------------------------------------
# Group 1 — URL block content and structure
# ---------------------------------------------------------------------------

class TestSignupUrlBlock:

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "siglink-g1-owner", "siglink-g1"
        )
        self.client = TestClient(app)
        _login(self.client, "siglink-g1-owner")

    def _get(self):
        return self.client.get(_detail_url(self.ws["slug"], self.op["id"]))

    def test_signup_url_block_rendered(self):
        resp = self._get()
        assert resp.status_code == 200
        assert "signup-share-url" in resp.text

    def test_url_contains_workspace_slug(self):
        resp = self._get()
        assert f"/workspaces/{self.ws['slug']}/" in resp.text

    def test_url_contains_operation_id(self):
        resp = self._get()
        assert self.op["id"] in resp.text

    def test_url_ends_with_slash_signup(self):
        resp = self._get()
        assert f"/operations/{self.op['id']}/signup" in resp.text

    def test_url_in_readonly_input(self):
        """URL rendered inside a readonly input for easy select-all on click."""
        resp = self._get()
        assert 'class="signup-share-url"' in resp.text
        assert "readonly" in resp.text

    def test_share_link_label_visible(self):
        resp = self._get()
        assert "Share link" in resp.text or "Share" in resp.text


# ---------------------------------------------------------------------------
# Group 2 — Copy button presence
# ---------------------------------------------------------------------------

class TestCopyButton:

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "siglink-g2-owner", "siglink-g2"
        )
        self.client = TestClient(app)
        _login(self.client, "siglink-g2-owner")

    def _get(self):
        return self.client.get(_detail_url(self.ws["slug"], self.op["id"]))

    def test_copy_button_rendered(self):
        resp = self._get()
        assert "signup-share-copy" in resp.text

    def test_copy_button_text(self):
        resp = self._get()
        assert "signup-share-copy" in resp.text
        assert "Copy" in resp.text

    def test_copy_button_uses_clipboard_api(self):
        resp = self._get()
        assert "navigator.clipboard.writeText" in resp.text

    def test_copy_button_is_type_button(self):
        """Must be type=button, not type=submit, to avoid accidental form POST."""
        resp = self._get()
        assert 'type="button"' in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Existing "Signup page →" link unchanged
# ---------------------------------------------------------------------------

class TestExistingSignupLink:

    def setup_method(self):
        self.owner, self.ws, self.op = _make_planning_op(
            "siglink-g3-owner", "siglink-g3"
        )
        self.client = TestClient(app)
        _login(self.client, "siglink-g3-owner")

    def _get(self):
        return self.client.get(_detail_url(self.ws["slug"], self.op["id"]))

    def test_signup_page_link_still_present(self):
        resp = self._get()
        assert "Signup page" in resp.text

    def test_signup_page_link_href(self):
        resp = self._get()
        expected = f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}/signup"
        assert expected in resp.text

    def test_signup_count_still_shown(self):
        resp = self._get()
        assert "signup" in resp.text.lower()


# ---------------------------------------------------------------------------
# Group 4 — URL shown for draft operations too
# ---------------------------------------------------------------------------

class TestSignupUrlOnDraft:

    def setup_method(self):
        self.owner = make_user("siglink-g4-owner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="siglink-g4")
        self.op    = make_operation(self.ws["id"])  # stays in draft
        self.client = TestClient(app)
        _login(self.client, "siglink-g4-owner")

    def test_url_block_visible_on_draft_operation(self):
        resp = self.client.get(_detail_url(self.ws["slug"], self.op["id"]))
        assert resp.status_code == 200
        assert "signup-share-url" in resp.text

    def test_url_contains_correct_path_on_draft(self):
        resp = self.client.get(_detail_url(self.ws["slug"], self.op["id"]))
        assert f"/operations/{self.op['id']}/signup" in resp.text
