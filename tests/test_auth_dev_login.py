"""Dev auth login and session tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import database, repositories
from app.main import app


def test_dev_login_creates_user_and_sets_session():
    client = TestClient(app)
    response = client.post(
        "/login",
        data={"display_name": "Alice Caller", "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "ironkeep_session" in response.cookies

    with database.transaction() as db:
        user = repositories.get_user_by_provider_identity(db, "dev", "alice-caller")
    assert user is not None

    home = client.get("/workspaces")
    assert home.status_code == 200
    assert b"Alice Caller" in home.content


def test_logout_clears_session():
    client = TestClient(app)
    client.post("/login", data={"display_name": "Bob Caller", "next": "/"}, follow_redirects=False)
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    home = client.get("/workspaces", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"].startswith("/login")


def test_login_default_redirect_goes_to_workspaces():
    """POST /login with no next param must redirect to /workspaces, not the public landing."""
    client = TestClient(app)
    response = client.post(
        "/login",
        data={"display_name": "Carol Caller"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/workspaces", (
        "Login without an explicit next param must redirect to /workspaces — "
        "not to / (which is the public landing page since Phase 1 migration)"
    )


def test_authenticated_user_can_access_landing_page():
    """GET / must return 200 for authenticated users — the landing page is public."""
    client = TestClient(app)
    client.post("/login", data={"display_name": "Dave Caller", "next": "/"}, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 200, (
        "Authenticated users must be able to visit the public landing page"
    )


def test_logout_redirects_to_public_landing():
    """POST /logout must redirect to / (public landing page), not /workspaces."""
    client = TestClient(app)
    client.post("/login", data={"display_name": "Eve Caller", "next": "/"}, follow_redirects=False)
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/", (
        "Logout must land on the public landing page (/), not the authenticated home"
    )
