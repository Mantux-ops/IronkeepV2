"""
Phase 10 Slice 4 — Landing page setup CTA.

Targeted UI tests for the "Add to Discord" CTA on the public landing page.

Coverage:
  1. Landing page contains /discord/setup link.
  2. Landing nav contains "Add to Discord" link.
  3. Login link remains present on the landing page.
  4. /discord/setup still renders correctly (regression).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _landing() -> str:
    client = TestClient(app, follow_redirects=False)
    resp   = client.get("/")
    assert resp.status_code == 200
    return resp.text


def test_landing_contains_discord_setup_link():
    assert "/discord/setup" in _landing()


def test_landing_nav_contains_add_to_discord():
    assert "Add to Discord" in _landing()


def test_landing_login_link_remains():
    assert "/login" in _landing()


def test_discord_setup_page_still_renders():
    client = TestClient(app, follow_redirects=False)
    resp   = client.get("/discord/setup")
    assert resp.status_code == 200
