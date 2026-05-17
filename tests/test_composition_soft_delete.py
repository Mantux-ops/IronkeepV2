"""
AlbionComposition soft-delete tests.

Covers:
  Use case:
    1.  retire_composition sets deleted_at on the composition.
    2.  Retiring an already-retired composition raises ConflictError.
    3.  Retiring a non-existent composition raises NotFoundError.
    4.  A plain member cannot retire a composition → PermissionDenied.
    5.  albion_composition.deleted event emitted with correct payload.
    6.  Composition slot templates are untouched after retirement.
    7.  Existing operation plan survives retirement (FK intact, plan row unchanged).
    8.  Existing operation_slots (frozen) are untouched.

  Repository:
    9.  get_albion_compositions excludes retired by default.
    10. get_albion_compositions(include_deleted=True) returns all.
    11. count_deleted_albion_compositions returns correct count.
    12. get_albion_composition (single-row) still returns retired compositions.
    13. Retiring does not delete composition_slot_templates.

  HTTP / template:
    14. Compositions list hides retired by default.
    15. ?show_deleted=1 shows retired with "retired" badge.
    16. Retire POST → success flash + composition marked deleted.
    17. Retire POST by member → denied.
    18. Second retire POST → error flash (already retired).
    19. Operation detail with retired composition does not crash.
    20. Operation detail shows "retired" tag next to composition name.
    21. Attach-plan dropdown on operation detail excludes retired compositions.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError, PermissionDenied
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _get_owner_id(ws_id: str) -> str:
    with database.transaction() as db:
        members = repositories.list_workspace_members(db, ws_id)
    for m in members:
        if m["role"] == "owner":
            return m["user_id"]
    raise AssertionError("No owner found")


def _get_composition(comp_id: str, ws_id: str) -> dict | None:
    with database.transaction() as db:
        return repositories.get_albion_composition(db, comp_id, ws_id)


def _get_events(ws_id: str, event_type: str) -> list[dict]:
    with database.transaction() as db:
        rows = db.execute(
            "SELECT * FROM operational_events WHERE guild_workspace_id = ? AND event_type = ?",
            (ws_id, event_type),
        ).fetchall()
    return [dict(r) for r in rows]


def _get_slot_templates(comp_id: str, ws_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_composition_slot_templates(db, comp_id, ws_id)


# ---------------------------------------------------------------------------
# Use case tests
# ---------------------------------------------------------------------------

def test_retire_sets_deleted_at():
    ws = make_workspace(slug="ret-sets-dat")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Retire Me")

    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    row = _get_composition(comp["id"], ws["id"])
    assert row is not None
    assert row["deleted_at"] is not None


def test_retire_twice_raises_conflict():
    ws = make_workspace(slug="ret-twice")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Retire Twice")

    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    with pytest.raises(ConflictError, match="already retired"):
        use_cases.retire_composition(ws["id"], comp["id"], owner_id)


def test_retire_nonexistent_raises_not_found():
    ws = make_workspace(slug="ret-notfound")
    owner_id = _get_owner_id(ws["id"])

    with pytest.raises(NotFoundError):
        use_cases.retire_composition(ws["id"], "00000000-0000-0000-0000-000000000000", owner_id)


def test_member_cannot_retire_composition():
    owner = make_user("RetOwner1")
    ws = make_workspace(owner_user_id=owner["id"], slug="ret-member-deny")
    comp = make_composition(ws["id"], name="Member Deny Comp")
    use_cases.add_workspace_member(ws["id"], owner["id"], "RetMember1", role="member")

    with database.transaction() as db:
        member_user = repositories.get_user_by_provider_identity(db, "dev", "retmember1")
    assert member_user

    with pytest.raises(PermissionDenied):
        use_cases.retire_composition(ws["id"], comp["id"], member_user["id"])


def test_retire_emits_event():
    ws = make_workspace(slug="ret-event")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Event Comp")

    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    events = _get_events(ws["id"], "albion_composition.deleted")
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload["composition_id"] == comp["id"]
    assert payload["composition_name"] == "Event Comp"


def test_retire_does_not_delete_slot_templates():
    ws = make_workspace(slug="ret-templates")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Template Comp")

    templates_before = _get_slot_templates(comp["id"], ws["id"])
    assert len(templates_before) > 0

    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    templates_after = _get_slot_templates(comp["id"], ws["id"])
    assert len(templates_after) == len(templates_before)


def test_retire_does_not_break_existing_operation_plan():
    ws = make_workspace(slug="ret-plan-intact")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Plan Intact Comp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])

    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    with database.transaction() as db:
        plan = repositories.get_operation_plan(db, op["id"], ws["id"])
    assert plan is not None
    assert plan["albion_composition_id"] == comp["id"]


def test_retire_does_not_mutate_operation_slots():
    ws = make_workspace(slug="ret-slots-intact")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Slots Intact Comp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots_before = use_cases.generate_operation_slots(ws["id"], op["id"])
    assert len(slots_before) > 0

    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    with database.transaction() as db:
        slots_after = repositories.get_operation_slots(db, op["id"], ws["id"])
    assert len(slots_after) == len(slots_before)


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

def test_repo_get_compositions_excludes_retired_by_default():
    ws = make_workspace(slug="repo-excl")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Active Comp")
    retired = make_composition(ws["id"], name="Retired Comp")
    use_cases.retire_composition(ws["id"], retired["id"], owner_id)

    with database.transaction() as db:
        result = repositories.get_albion_compositions(db, ws["id"])

    ids = {c["id"] for c in result}
    assert comp["id"] in ids
    assert retired["id"] not in ids


def test_repo_get_compositions_include_deleted_returns_all():
    ws = make_workspace(slug="repo-incl")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Active Comp 2")
    retired = make_composition(ws["id"], name="Retired Comp 2")
    use_cases.retire_composition(ws["id"], retired["id"], owner_id)

    with database.transaction() as db:
        result = repositories.get_albion_compositions(db, ws["id"], include_deleted=True)

    ids = {c["id"] for c in result}
    assert comp["id"] in ids
    assert retired["id"] in ids


def test_repo_count_deleted_returns_correct_count():
    ws = make_workspace(slug="repo-count-del")
    owner_id = _get_owner_id(ws["id"])
    comp1 = make_composition(ws["id"], name="Del Comp A")
    comp2 = make_composition(ws["id"], name="Del Comp B")
    _keep = make_composition(ws["id"], name="Active Keep")
    use_cases.retire_composition(ws["id"], comp1["id"], owner_id)
    use_cases.retire_composition(ws["id"], comp2["id"], owner_id)

    with database.transaction() as db:
        count = repositories.count_deleted_albion_compositions(db, ws["id"])

    assert count == 2


def test_repo_single_get_returns_retired_composition():
    ws = make_workspace(slug="repo-single-ret")
    owner_id = _get_owner_id(ws["id"])
    comp = make_composition(ws["id"], name="Single Ret Comp")
    use_cases.retire_composition(ws["id"], comp["id"], owner_id)

    with database.transaction() as db:
        result = repositories.get_albion_composition(db, comp["id"], ws["id"])

    assert result is not None
    assert result["deleted_at"] is not None


# ---------------------------------------------------------------------------
# HTTP / template tests
# ---------------------------------------------------------------------------

def test_http_list_hides_retired_by_default():
    owner = make_user("HttpRetOwner1")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-default")
    active = make_composition(ws["id"], name="Active HTTP Comp")
    retired = make_composition(ws["id"], name="Retired HTTP Comp")
    use_cases.retire_composition(ws["id"], retired["id"], owner["id"])

    client = TestClient(app)
    _login(client, "HttpRetOwner1")

    resp = client.get(f"/workspaces/{ws['slug']}/compositions")
    assert resp.status_code == 200
    assert "Active HTTP Comp" in resp.text
    assert "Retired HTTP Comp" not in resp.text


def test_http_list_shows_retired_with_toggle():
    owner = make_user("HttpRetOwner2")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-toggle")
    active = make_composition(ws["id"], name="Active Toggle Comp")
    retired = make_composition(ws["id"], name="Retired Toggle Comp")
    use_cases.retire_composition(ws["id"], retired["id"], owner["id"])

    client = TestClient(app)
    _login(client, "HttpRetOwner2")

    resp = client.get(f"/workspaces/{ws['slug']}/compositions?show_deleted=1")
    assert resp.status_code == 200
    assert "Active Toggle Comp" in resp.text
    assert "Retired Toggle Comp" in resp.text
    assert "retired" in resp.text.lower()


def test_http_retire_post_success():
    owner = make_user("HttpRetOwner3")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-post")
    comp = make_composition(ws["id"], name="Post Retire Comp")

    client = TestClient(app)
    _login(client, "HttpRetOwner3")

    resp = client.post(
        f"/workspaces/{ws['slug']}/compositions/{comp['id']}/retire",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "retired" in resp.text.lower()

    row = _get_composition(comp["id"], ws["id"])
    assert row["deleted_at"] is not None


def test_http_retire_post_by_member_denied():
    owner = make_user("HttpRetOwner4")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-deny")
    comp = make_composition(ws["id"], name="Deny Retire Comp")
    use_cases.add_workspace_member(ws["id"], owner["id"], "HttpRetMember1", role="member")

    client = TestClient(app)
    _login(client, "HttpRetMember1")

    resp = client.post(
        f"/workspaces/{ws['slug']}/compositions/{comp['id']}/retire",
        follow_redirects=True,
    )
    # Member hits require_mutator=True in authorize_workspace_action → error redirect
    assert resp.status_code == 200
    row = _get_composition(comp["id"], ws["id"])
    assert row["deleted_at"] is None  # untouched


def test_http_retire_already_retired_shows_error():
    owner = make_user("HttpRetOwner5")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-dupe")
    comp = make_composition(ws["id"], name="Dupe Retire Comp")
    use_cases.retire_composition(ws["id"], comp["id"], owner["id"])

    client = TestClient(app)
    _login(client, "HttpRetOwner5")

    resp = client.post(
        f"/workspaces/{ws['slug']}/compositions/{comp['id']}/retire",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "already retired" in resp.text.lower()


def test_http_operation_detail_with_retired_comp_does_not_crash():
    owner = make_user("HttpRetOwner6")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-detail")
    comp = make_composition(ws["id"], name="Detail Retired Comp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.retire_composition(ws["id"], comp["id"], owner["id"])

    client = TestClient(app)
    _login(client, "HttpRetOwner6")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200


def test_http_operation_detail_shows_retired_tag():
    owner = make_user("HttpRetOwner7")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-tag")
    comp = make_composition(ws["id"], name="Tag Retired Comp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.retire_composition(ws["id"], comp["id"], owner["id"])

    client = TestClient(app)
    _login(client, "HttpRetOwner7")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200
    assert "retired" in resp.text.lower()
    assert "Tag Retired Comp" in resp.text


def test_http_attach_plan_dropdown_excludes_retired():
    owner = make_user("HttpRetOwner8")
    ws = make_workspace(owner_user_id=owner["id"], slug="http-ret-dropdown")
    active = make_composition(ws["id"], name="Active Dropdown Comp")
    retired = make_composition(ws["id"], name="Retired Dropdown Comp")
    # Keep operation in 'draft' so the attach-plan dropdown is rendered
    # (can_attach_plan is only True for draft status).
    op = make_operation(ws["id"])
    use_cases.retire_composition(ws["id"], retired["id"], owner["id"])

    client = TestClient(app)
    _login(client, "HttpRetOwner8")

    resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
    assert resp.status_code == 200
    assert "Active Dropdown Comp" in resp.text
    assert "Retired Dropdown Comp" not in resp.text
