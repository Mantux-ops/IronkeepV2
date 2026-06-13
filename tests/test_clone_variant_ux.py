"""
Composition variant cloning UX polish tests.

Covers discoverability and usability improvements to the existing clone workflow:
- ?variant= query param pre-fills the composition name as "{source} — {variant}"
- Clone route passes build/weapon datalist suggestions
- compositions_new.html shows a "Starting from …" banner when cloned_from_name is set
- compositions_list.html shows a Clone link for active compositions
- compositions_detail.html shows Brawl / Kite / Anti-Clap variant quick-links

Groups:
  Group 1 — Clone route: query param + context
  Group 2 — Clone banner in compositions_new.html
  Group 3 — Clone affordance in compositions_list.html
  Group 4 — Variant quick-links in compositions_detail.html
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

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _setup(slug: str) -> tuple[dict, dict, dict]:
    owner = make_user(f"cv-owner-{slug}")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp  = make_composition(ws["id"], name="ZvZ 5-Man")
    return owner, ws, comp


def _clone_url(slug: str, comp_id: str, variant: str = "") -> str:
    url = f"/workspaces/{slug}/compositions/{comp_id}/clone"
    if variant:
        url += f"?variant={variant}"
    return url


# ---------------------------------------------------------------------------
# Group 1 — Clone route: query param + context
# ---------------------------------------------------------------------------

class TestCloneRouteQueryParam:
    """GET /compositions/{comp_id}/clone respects ?variant= and passes suggestions."""

    def test_variant_param_prefills_name_with_suffix(self):
        slug = "cv-route-1"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(_clone_url(slug, comp["id"], variant="Brawl"))

        assert resp.status_code == 200
        assert "ZvZ 5-Man — Brawl" in resp.text

    def test_no_variant_param_keeps_copy_of_prefix(self):
        slug = "cv-route-2"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(_clone_url(slug, comp["id"]))

        assert resp.status_code == 200
        assert "Copy of ZvZ 5-Man" in resp.text

    def test_empty_variant_param_keeps_copy_of_prefix(self):
        slug = "cv-route-3"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(_clone_url(slug, comp["id"], variant=""))

        assert resp.status_code == 200
        assert "Copy of ZvZ 5-Man" in resp.text

    def test_clone_route_passes_build_name_datalist(self):
        """build-name-list datalist is rendered (even if empty) — no KeyError."""
        slug = "cv-route-4"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(_clone_url(slug, comp["id"]))

        assert resp.status_code == 200
        assert 'id="build-name-list"' in resp.text
        assert 'id="weapon-name-list"' in resp.text


# ---------------------------------------------------------------------------
# Group 2 — Clone banner in compositions_new.html
# ---------------------------------------------------------------------------

class TestCloneBanner:
    """compositions_new.html shows the clone banner when cloned_from_name is set."""

    def test_clone_form_shows_starting_from_banner(self):
        slug = "cv-banner-1"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(_clone_url(slug, comp["id"]))

        assert resp.status_code == 200
        assert "Starting from" in resp.text
        assert "ZvZ 5-Man" in resp.text

    def test_fresh_new_composition_form_has_no_clone_banner(self):
        slug = "cv-banner-2"
        owner, ws, _comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(f"/workspaces/{slug}/compositions/new")

        assert resp.status_code == 200
        assert "Starting from" not in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Clone affordance in compositions_list.html
# ---------------------------------------------------------------------------

class TestListCloneAffordance:
    """compositions_list.html shows Clone link for active comps, not for retired."""

    def test_active_composition_row_shows_clone_link(self):
        slug = "cv-list-1"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(f"/workspaces/{slug}/compositions")

        assert resp.status_code == 200
        assert f"/compositions/{comp['id']}/clone" in resp.text
        assert "Clone" in resp.text

    def test_retired_composition_row_has_no_clone_link(self):
        slug = "cv-list-2"
        owner, ws, comp = _setup(slug)
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        # Show retired rows in the list
        resp = client.get(f"/workspaces/{slug}/compositions?show_deleted=1")

        assert resp.status_code == 200
        # The clone link must not appear anywhere in the page for the retired comp
        assert f"/compositions/{comp['id']}/clone" not in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Variant quick-links in compositions_detail.html
# ---------------------------------------------------------------------------

class TestDetailVariantQuickLinks:
    """compositions_detail.html shows Brawl/Kite/Anti-Clap quick-links for active comps."""

    def test_active_composition_shows_variant_quick_links(self):
        slug = "cv-detail-1"
        owner, ws, comp = _setup(slug)
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(f"/workspaces/{slug}/compositions/{comp['id']}")

        assert resp.status_code == 200
        assert "variant=Brawl" in resp.text
        assert "variant=Kite" in resp.text
        assert "variant=Anti-Clap" in resp.text

    def test_retired_composition_has_no_variant_quick_links(self):
        slug = "cv-detail-2"
        owner, ws, comp = _setup(slug)
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )
        client = TestClient(app)
        _login(client, f"cv-owner-{slug}")

        resp = client.get(f"/workspaces/{slug}/compositions/{comp['id']}")

        assert resp.status_code == 200
        assert "variant=Brawl" not in resp.text
        assert "variant=Kite" not in resp.text
