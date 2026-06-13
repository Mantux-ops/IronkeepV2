"""
Discord announcement signup URL — formatter + route/preview tests.

Covers:
  1. format_operation_announcement includes signup URL in embed description.
  2. URL structure contains workspace slug, operation id, /signup.
  3. Existing announcement content (title, type, status, when) still present.
  4. No signup_url → default description unchanged (no bare URL injected).
  5. format_roster behavior unchanged — no signup URL in roster embed description.
  6. Operation detail preview shows the signup URL.
  7. Announcement button ("Open Signup Page") also present with URL.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.application import use_cases
from app.discord.formatters import format_operation_announcement, format_roster
from app.main import app

from tests.conftest import make_user, make_workspace, make_operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "https://ironkeep.example.com"
_SLUG = "test-ws"
_OP_ID = "op-abc-123"
_SIGNUP_URL = f"{_BASE}/workspaces/{_SLUG}/operations/{_OP_ID}/signup"


def _op(title="Saturday ZvZ", status="planning", op_id=_OP_ID) -> dict:
    return {
        "id":                 op_id,
        "title":              title,
        "operation_type":     "zvz",
        "status":             status,
        "scheduled_start_at": "2026-05-30T20:00:00",
    }


def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


_GUILD_ID   = "111122223333444455"
_CHANNEL_ID = "555566667777888899"


def _set_discord_config(ws_id, owner_id):
    use_cases.update_workspace_discord_config(
        guild_workspace_id=ws_id,
        actor_id=owner_id,
        discord_guild_id=_GUILD_ID,
        announcement_channel_id=_CHANNEL_ID,
        officer_channel_id=None,
    )


# ---------------------------------------------------------------------------
# 1. Signup URL in embed description
# ---------------------------------------------------------------------------

class TestSignupUrlInDescription:

    def test_description_contains_signup_url(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        desc = result["embeds"][0]["description"]
        assert _SIGNUP_URL in desc

    def test_description_contains_sign_up_label(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        desc = result["embeds"][0]["description"]
        assert "Sign up" in desc

    def test_no_signup_url_gives_generic_description(self):
        result = format_operation_announcement(_op(), signup_url=None)
        desc = result["embeds"][0]["description"]
        assert "web dashboard" in desc.lower()
        assert "http" not in desc  # no URL in generic form


# ---------------------------------------------------------------------------
# 2. URL structure is correct
# ---------------------------------------------------------------------------

class TestSignupUrlStructure:

    def test_url_contains_signup_segment(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        desc = result["embeds"][0]["description"]
        assert "/signup" in desc

    def test_url_contains_workspace_slug(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        desc = result["embeds"][0]["description"]
        assert _SLUG in desc

    def test_url_contains_operation_id(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        desc = result["embeds"][0]["description"]
        assert _OP_ID in desc


# ---------------------------------------------------------------------------
# 3. Existing content unchanged
# ---------------------------------------------------------------------------

class TestExistingContentPreserved:

    def test_title_still_in_embed(self):
        result = format_operation_announcement(_op(title="Friday HG"), signup_url=_SIGNUP_URL)
        assert result["embeds"][0]["title"] == "Friday HG"

    def test_type_field_still_present(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        names = [f["name"] for f in result["embeds"][0]["fields"]]
        assert "Type" in names

    def test_status_field_still_present(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        names = [f["name"] for f in result["embeds"][0]["fields"]]
        assert "Status" in names

    def test_when_field_still_present(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        names = [f["name"] for f in result["embeds"][0]["fields"]]
        assert "When" in names

    def test_footer_still_present(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        assert result["embeds"][0]["footer"]["text"] == "IronkeepV2"

    def test_open_signup_button_also_present(self):
        result = format_operation_announcement(_op(), signup_url=_SIGNUP_URL)
        btns = result["components"][0]["components"]
        labels = [b["label"] for b in btns]
        assert "Open Signup Page" in labels


# ---------------------------------------------------------------------------
# 4. format_roster embed description unaffected
# ---------------------------------------------------------------------------

class TestRosterUnchanged:

    def _roster(self, signup_url=None):
        return format_roster(
            operation=_op(),
            slots=[],
            assignments=[],
            signup_url=signup_url,
        )

    def test_roster_embed_has_no_description_key_without_url(self):
        result = self._roster()
        # format_roster never sets a description field; signup URL in announcement
        # must not bleed into roster formatter.
        assert "description" not in result["embeds"][0]

    def test_roster_embed_has_no_description_key_with_url(self):
        result = self._roster(signup_url=_SIGNUP_URL)
        assert "description" not in result["embeds"][0]

    def test_roster_still_has_components(self):
        result = self._roster(signup_url=_SIGNUP_URL)
        assert "components" in result
        assert result["components"][0]["type"] == 1


# ---------------------------------------------------------------------------
# 5. Operation detail preview includes signup URL
# ---------------------------------------------------------------------------

class TestPreviewShowsSignupUrl:

    def setup_method(self):
        self.owner = make_user("da-preview-owner")
        self.ws    = make_workspace(slug="da-preview-ws", owner_user_id=self.owner["id"])
        self.op    = make_operation(self.ws["id"], title="Preview ZvZ")
        _set_discord_config(self.ws["id"], self.owner["id"])
        self.client = TestClient(app)

    def test_preview_description_contains_signup_path(self):
        _login(self.client, "da-preview-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}")
        assert resp.status_code == 200
        assert "/signup" in resp.text

    def test_preview_description_contains_operation_id(self):
        _login(self.client, "da-preview-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}")
        assert resp.status_code == 200
        assert self.op["id"] in resp.text

    def test_preview_description_contains_workspace_slug(self):
        _login(self.client, "da-preview-owner")
        resp = self.client.get(f"/workspaces/{self.ws['slug']}/operations/{self.op['id']}")
        assert resp.status_code == 200
        # slug appears in the signup URL embedded in the description
        assert self.ws["slug"] in resp.text
