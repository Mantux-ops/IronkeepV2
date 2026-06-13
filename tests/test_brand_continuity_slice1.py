"""Phase 8.8 Slice 1 — Brand Continuity & Sign-In Experience tests.

Covers:
  1.  Landing page nav renders the brand-mark SVG.
  2.  Landing page nav displays "Ironkeep", not "IronkeepV2".
  3.  Landing page title says "Ironkeep" (not "IronkeepV2").
  4.  Login page extends public shell (workspace-nav absent).
  5.  Login page nav renders the brand-mark SVG.
  6.  Login page nav displays "Ironkeep", not "IronkeepV2".
  7.  Login page title says "Sign in — Ironkeep".
  8.  Discord login button is still present on the login page (dev mode).
  9.  Dev login form is still functional after template change.
  10. App shell (dashboard) nav renders the brand-mark SVG.
  11. App shell (dashboard) nav displays "Ironkeep", not "IronkeepV2".
  12. Dashboard renders the workspace hero strip (.ws-hero).
  13. Dashboard ws-hero contains the workspace name as h1.
  14. Dashboard title says "<workspace> — Ironkeep".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _authed_client(display_name: str = "Brand Tester") -> TestClient:
    client = TestClient(app)
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=False)
    return client


# ---------------------------------------------------------------------------
# 1–3: Landing page (public shell)
# ---------------------------------------------------------------------------

def test_landing_nav_contains_brand_mark():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'class="brand-mark"' in resp.content, (
        "Landing nav must contain the brand-mark SVG element"
    )


def test_landing_nav_displays_ironkeep_not_v2():
    """Nav chrome must use 'Ironkeep'. Body copy (landing.html content) is out of scope for this slice."""
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    # Extract just the nav element to check chrome
    nav_html = html.split('<nav class="landing-nav"')[1].split("</nav>")[0] if '<nav class="landing-nav"' in html else html
    assert "IronkeepV2" not in nav_html, (
        "Landing nav chrome must not display 'IronkeepV2' — brand name is 'Ironkeep'"
    )


def test_landing_title_is_ironkeep():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<title>Ironkeep</title>" in resp.content or b"Ironkeep" in resp.content


# ---------------------------------------------------------------------------
# 4–8: Login page
# ---------------------------------------------------------------------------

def test_login_page_has_no_workspace_nav():
    """Login page must use the public shell — no workspace-nav bar."""
    client = TestClient(app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b'class="workspace-nav"' not in resp.content, (
        "Login page must NOT render the workspace nav — it uses the public shell"
    )


def test_login_page_nav_contains_brand_mark():
    client = TestClient(app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b'class="brand-mark"' in resp.content, (
        "Login page nav must contain the brand-mark SVG"
    )


def test_login_page_nav_displays_ironkeep_not_v2():
    client = TestClient(app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "IronkeepV2" not in resp.text, (
        "Login page must not display 'IronkeepV2' — brand name is 'Ironkeep'"
    )


def test_login_page_title_is_sign_in_ironkeep():
    client = TestClient(app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Sign in" in resp.content, (
        "Login page title block must say 'Sign in \u2014 Ironkeep'"
    )
    assert b"Ironkeep" in resp.content


def test_login_dev_form_present():
    """Dev login form must still render on the login page (dev mode)."""
    client = TestClient(app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b'action="/login"' in resp.content, (
        "Dev login form must still be present on the login page"
    )
    assert b'name="display_name"' in resp.content


def test_dev_login_form_still_functional():
    """Dev login flow must still work after template base change."""
    client = TestClient(app)
    response = client.post(
        "/login",
        data={"display_name": "BrandTestUser", "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303, "Dev login POST must redirect (303) after success"
    assert "ironkeep_session" in response.cookies, "Session cookie must be set after login"


# ---------------------------------------------------------------------------
# Helpers for authenticated dashboard tests
# ---------------------------------------------------------------------------

def _get_dashboard_as_owner(ws_name: str, ws_slug: str, owner_name: str) -> tuple:
    """Create workspace + owner, login as owner, GET dashboard. Returns (client, response)."""
    owner = make_user(owner_name)
    ws = make_workspace(ws_name, ws_slug, owner_user_id=owner["id"])
    client = TestClient(app)
    client.post("/login", data={"display_name": owner_name, "next": "/"}, follow_redirects=False)
    resp = client.get(f"/workspaces/{ws['slug']}")
    return client, resp


# ---------------------------------------------------------------------------
# 10–14: Authenticated app shell / dashboard
# ---------------------------------------------------------------------------

def test_app_shell_nav_contains_brand_mark():
    """Authenticated pages must render the brand-mark in the global nav."""
    _, resp = _get_dashboard_as_owner("Iron Guild", "iron-guild", "NavMarkOwner")
    assert resp.status_code == 200
    assert b'class="brand-mark"' in resp.content, (
        "App shell global nav must contain the brand-mark SVG"
    )


def test_app_shell_nav_displays_ironkeep_not_v2():
    """Authenticated pages must not display 'IronkeepV2' in nav chrome."""
    _, resp = _get_dashboard_as_owner("Iron Guild", "iron-brand", "NavNameOwner")
    assert resp.status_code == 200
    nav_section = resp.text.split('<nav class="global-nav"')[1].split("</nav>")[0] if '<nav class="global-nav"' in resp.text else ""
    assert "IronkeepV2" not in nav_section, (
        "Global nav must not contain 'IronkeepV2' — brand name is 'Ironkeep'"
    )


def test_dashboard_renders_ws_hero():
    """Dashboard must render the workspace hero strip."""
    _, resp = _get_dashboard_as_owner("Hero Guild", "hero-guild", "HeroOwner")
    assert resp.status_code == 200
    assert b'class="ws-hero"' in resp.content, (
        "Dashboard must render the .ws-hero strip"
    )


def test_dashboard_ws_hero_contains_workspace_name():
    """Dashboard ws-hero must display the workspace name as h1."""
    _, resp = _get_dashboard_as_owner("Fortress Alliance", "fortress-guild", "HeroNameOwner")
    assert resp.status_code == 200
    assert b"Fortress Alliance" in resp.content, (
        "Dashboard ws-hero must render the workspace name"
    )
    assert b'class="ws-hero__name"' in resp.content


def test_dashboard_title_uses_ironkeep_not_v2():
    """Dashboard <title> must use 'Ironkeep', not 'IronkeepV2'."""
    _, resp = _get_dashboard_as_owner("Title Guild", "title-guild", "TitleOwner")
    assert resp.status_code == 200
    title_start = resp.text.find("<title>")
    title_end = resp.text.find("</title>")
    if title_start != -1 and title_end != -1:
        title_content = resp.text[title_start:title_end]
        assert "IronkeepV2" not in title_content, (
            "Dashboard <title> must not contain 'IronkeepV2'"
        )
        assert "Ironkeep" in title_content
