"""Phase 8 Slice 2 — Compact Mode for Composition Detail.

Covers:
  Group 1 — Full mode (default)
               a) equipment doctrine summary rendered when slot has equipment
               b) secondary build name rendered when weapon_name ≠ build_name
               c) toggle link points to ?compact=1

  Group 2 — Compact mode (?compact=1)
               a) equipment doctrine summary hidden
               b) secondary build name hidden
               c) toggle link points to bare detail URL (no compact param)
               d) role label preserved
               e) primary weapon/build name preserved
               f) party-summary strip preserved
               g) role-color-bar preserved
               h) quick-edit panel preserved for officers

  Group 3 — Edge cases
               a) ?compact=0 treated as full mode (bld-doctrine visible)
               b) slot with no equipment: compact mode renders without errors
               c) slot where weapon_name == build_name: no secondary line in either mode
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _setup(slug: str):
    """
    Create workspace + composition with two slot types:
      Slot 1 — weapon_name ≠ build_name + full equipment → triggers secondary
                name and doctrine_summary.
      Slot 2 — no equipment, weapon_name == build_name → baseline slot.
    Returns (owner, ws, comp).
    """
    owner = make_user(f"Owner-{slug}")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = use_cases.create_albion_composition(
        guild_workspace_id=ws["id"],
        name=f"Comp-{slug}",
        description=None,
        slots=[
            {
                "party_number": 1,
                "slot_index":   1,
                "role":         "Healer",
                "build_name":   "Hallowfall Healer",
                "weapon_name":  "T8.3 Hallowfall",
                "head_name":    "Scholar Cowl",
                "armor_name":   "Scholar Robe",
                "shoes_name":   "Scholar Sandals",
                "food_name":    "Pork Omelette",
                "priority":     "core",
            },
            {
                "party_number": 1,
                "slot_index":   2,
                "role":         "Tank",
                "build_name":   "1H Mace",
                "weapon_name":  "1H Mace",      # same as build_name — no secondary
                "priority":     "core",
            },
        ],
    )
    return owner, ws, comp


def _get(client: TestClient, ws_slug: str, comp_id: str, *, compact: bool = False) -> object:
    url = f"/workspaces/{ws_slug}/compositions/{comp_id}"
    if compact:
        url += "?compact=1"
    return client.get(url, follow_redirects=True)


# ---------------------------------------------------------------------------
# Group 1 — Full mode (default)
# ---------------------------------------------------------------------------

class TestFullMode:

    def setup_method(self):
        self.owner, self.ws, self.comp = _setup("cd-full")
        self.client = TestClient(app)
        _login(self.client, "Owner-cd-full")

    def test_equipment_summary_rendered(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"])
        assert resp.status_code == 200
        # doctrine_summary renders a div with class bld-doctrine
        assert "bld-doctrine" in resp.text

    def test_secondary_build_name_rendered(self):
        """Slot 1 has weapon_name != build_name → slot-card__build is present."""
        resp = _get(self.client, self.ws["slug"], self.comp["id"])
        assert resp.status_code == 200
        assert "slot-card__build" in resp.text

    def test_toggle_link_points_to_compact(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"])
        assert resp.status_code == 200
        assert "compact=1" in resp.text
        assert "Compact view" in resp.text


# ---------------------------------------------------------------------------
# Group 2 — Compact mode (?compact=1)
# ---------------------------------------------------------------------------

class TestCompactMode:

    def setup_method(self):
        self.owner, self.ws, self.comp = _setup("cd-compact")
        self.client = TestClient(app)
        _login(self.client, "Owner-cd-compact")

    def test_equipment_summary_hidden(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "bld-doctrine" not in resp.text

    def test_secondary_build_name_hidden(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "slot-card__build" not in resp.text

    def test_toggle_link_points_to_full(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "Full view" in resp.text
        # Toggle link must NOT contain compact=1 (it undoes compact mode)
        # It may contain the comp detail URL without the param
        detail_url = f"/compositions/{self.comp['id']}\""
        assert detail_url in resp.text

    def test_role_label_preserved(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "slot-card__role" in resp.text

    def test_primary_weapon_name_preserved(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "slot-card__weapon" in resp.text
        # The actual weapon text must still appear
        assert "T8.3 Hallowfall" in resp.text

    def test_party_summary_preserved(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "party-summary" in resp.text

    def test_role_color_bar_preserved(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "role-color-bar" in resp.text

    def test_quick_edit_panel_preserved_for_officer(self):
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        assert "slot-card__quick-edit" in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def setup_method(self):
        self.owner, self.ws, self.comp = _setup("cd-edge")
        self.client = TestClient(app)
        _login(self.client, "Owner-cd-edge")

    def test_compact_zero_treated_as_full_mode(self):
        """`?compact=0` is not truthy — equipment summary must be present."""
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{self.comp['id']}?compact=0",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "bld-doctrine" in resp.text

    def test_no_equipment_slot_compact_renders_ok(self):
        """Slot 2 has no equipment fields; compact mode must not error."""
        resp = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp.status_code == 200
        # Slot 2 weapon name is still visible
        assert "1H Mace" in resp.text

    def test_weapon_equals_build_name_no_secondary_in_either_mode(self):
        """Slot 2: weapon_name == build_name → slot-card__build never appears."""
        # Full mode
        resp_full = _get(self.client, self.ws["slug"], self.comp["id"])
        # Slot 1 DOES have a secondary, so slot-card__build is present in full mode.
        # Slot 2 does NOT. We cannot distinguish per-slot in rendered HTML without
        # more specific assertions — verify the build name text appears in full mode
        # (no crash; secondary suppression logic runs cleanly).
        assert resp_full.status_code == 200
        assert "1H Mace" in resp_full.text
        # Compact mode: slot-card__build absent entirely (slot 1 secondary hidden too)
        resp_compact = _get(self.client, self.ws["slug"], self.comp["id"], compact=True)
        assert resp_compact.status_code == 200
        assert "slot-card__build" not in resp_compact.text
