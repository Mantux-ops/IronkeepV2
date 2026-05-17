"""Workspace membership and role enforcement tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.application import use_cases
from app.main import app
from tests.conftest import make_user, make_workspace


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def test_workspace_create_makes_owner_membership():
    owner = make_user("Owner One")
    ws = make_workspace(owner_user_id=owner["id"], slug="owner-clan")
    client = TestClient(app)
    _login(client, "Owner One")
    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 200


def test_non_member_workspace_is_not_found():
    owner = make_user("Owner Two")
    ws = make_workspace(owner_user_id=owner["id"], slug="private-clan")
    client = TestClient(app)
    _login(client, "Stranger")
    response = client.get(f"/workspaces/{ws['slug']}")
    assert response.status_code == 404


def test_member_can_view_but_not_create_operation():
    owner = make_user("Owner Three")
    ws = make_workspace(owner_user_id=owner["id"], slug="member-view")
    use_cases.add_workspace_member(
        ws["id"], owner["id"], "Member Three", role="member"
    )
    client = TestClient(app)
    _login(client, "Member Three")
    assert client.get(f"/workspaces/{ws['slug']}").status_code == 200
    assert client.get(f"/workspaces/{ws['slug']}/operations/new").status_code == 403


def test_officer_can_create_operation():
    owner = make_user("Owner Four")
    ws = make_workspace(owner_user_id=owner["id"], slug="officer-ops")
    use_cases.add_workspace_member(
        ws["id"], owner["id"], "Officer Four", role="officer"
    )
    client = TestClient(app)
    _login(client, "Officer Four")
    assert client.get(f"/workspaces/{ws['slug']}/operations/new").status_code == 200
