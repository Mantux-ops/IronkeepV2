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

    home = client.get("/")
    assert home.status_code == 200
    assert b"Alice Caller" in home.content


def test_logout_clears_session():
    client = TestClient(app)
    client.post("/login", data={"display_name": "Bob Caller", "next": "/"}, follow_redirects=False)
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"].startswith("/login")
