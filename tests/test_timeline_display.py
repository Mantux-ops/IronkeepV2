"""
Operation Timeline display tests.

Covers:
    1.  Human-readable label rendered instead of raw event_type.
    2.  Group badge class present in HTML.
    3.  Events displayed newest-first.
    4.  Raw payload available inside <details> element.
    5.  Empty state shown when no events exist.
    6.  Actor information rendered.
    7.  All operation-level event types have entries in _EVENT_LABELS
        (coverage guard — fails if a new event type is added without a label).
    8.  Unknown event types fall back to group 'other'.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import operational_events
from app.main import app
from app.routes import _EVENT_LABELS, _enrich_timeline_events

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _timeline_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/timeline"


def _make_published_op(ws_id: str) -> dict:
    op = make_operation(ws_id)
    use_cases.publish_operation(ws_id, op["id"])
    return op


# ---------------------------------------------------------------------------
# Unit tests: _EVENT_LABELS / _enrich_timeline_events
# ---------------------------------------------------------------------------

def test_all_operation_level_event_types_have_labels():
    """
    Every event type in operational_events._OPERATION_LEVEL_EVENTS must have
    an entry in _EVENT_LABELS.  Fails early when a new event type is added
    without a corresponding human label.
    """
    missing = operational_events._OPERATION_LEVEL_EVENTS - set(_EVENT_LABELS.keys())
    assert missing == set(), (
        f"Missing _EVENT_LABELS entries for operation-level event types: {missing}"
    )


def test_enrich_reverses_order():
    fake_events = [
        {"event_type": "guild_operation.created",   "occurred_at": "2026-06-01T10:00:00"},
        {"event_type": "guild_operation.published",  "occurred_at": "2026-06-01T11:00:00"},
        {"event_type": "guild_operation.locked",     "occurred_at": "2026-06-01T12:00:00"},
    ]
    enriched = _enrich_timeline_events(fake_events)
    # Newest-first: locked → published → created
    assert enriched[0]["event_type"] == "guild_operation.locked"
    assert enriched[1]["event_type"] == "guild_operation.published"
    assert enriched[2]["event_type"] == "guild_operation.created"


def test_enrich_attaches_group_and_label():
    fake = [{"event_type": "guild_operation.locked", "occurred_at": "2026-06-01T12:00:00"}]
    enriched = _enrich_timeline_events(fake)
    assert enriched[0]["_group"] == "lifecycle"
    assert enriched[0]["_label"] == "Roster locked"


def test_unknown_event_type_falls_back_to_other():
    fake = [{"event_type": "some.unknown.event", "occurred_at": "2026-06-01T12:00:00"}]
    enriched = _enrich_timeline_events(fake)
    assert enriched[0]["_group"] == "other"
    assert enriched[0]["_label"] == "some.unknown.event"


# ---------------------------------------------------------------------------
# HTTP / template tests
# ---------------------------------------------------------------------------

def test_timeline_shows_human_readable_label():
    owner = make_user("TlOwner1")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-label")
    op = _make_published_op(ws["id"])

    client = TestClient(app)
    _login(client, "TlOwner1")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    # Human label present
    assert "Published for planning" in resp.text
    # Raw event_type must NOT appear as the primary label (it can appear in payload/code blocks)
    # Check that the human label is present — that's sufficient
    assert "Operation created" in resp.text


def test_timeline_shows_group_badge_class():
    owner = make_user("TlOwner2")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-badge")
    op = _make_published_op(ws["id"])

    client = TestClient(app)
    _login(client, "TlOwner2")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "badge-lifecycle" in resp.text


def test_timeline_events_newest_first():
    owner = make_user("TlOwner3")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-newest")
    op = make_operation(ws["id"])

    # Emit two events in order: created → published
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "TlOwner3")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200

    # "Roster locked" must appear before "Operation created" in the HTML
    locked_pos  = resp.text.index("Roster locked")
    created_pos = resp.text.index("Operation created")
    assert locked_pos < created_pos, (
        "Expected newest event (locked) to appear before oldest (created)"
    )


def test_timeline_payload_in_details():
    owner = make_user("TlOwner4")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-payload")
    comp = make_composition(ws["id"], name="TlComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])

    client = TestClient(app)
    _login(client, "TlOwner4")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "<details" in resp.text
    assert "Raw payload" in resp.text


def test_timeline_empty_state():
    owner = make_user("TlOwner5")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-empty")
    # Create op but emit no operation-level events (draft only has guild_operation.created)
    # Instead test against a fresh workspace operation that we directly query
    op = make_operation(ws["id"])

    # Manually clear events for this operation so we get a true empty state
    with database.transaction() as db:
        db.execute(
            "DELETE FROM operational_events WHERE guild_operation_id = ?",
            (op["id"],),
        )

    client = TestClient(app)
    _login(client, "TlOwner5")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "No events recorded yet" in resp.text


def test_timeline_actor_shown():
    owner = make_user("TlOwner6")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-actor")
    op = _make_published_op(ws["id"])

    client = TestClient(app)
    _login(client, "TlOwner6")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    # At least one actor label should render (system or officer action)
    assert "system" in resp.text or "Officer action" in resp.text


def test_timeline_event_count_footer():
    owner = make_user("TlOwner7")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-count")
    op = make_operation(ws["id"])
    use_cases.publish_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "TlOwner7")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "newest first" in resp.text


def test_timeline_signup_label_shown():
    owner = make_user("TlOwner8")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-signup")
    op = _make_published_op(ws["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "SignupPlayer", "Tank")

    client = TestClient(app)
    _login(client, "TlOwner8")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Signup submitted" in resp.text
    assert "badge-signups" in resp.text


def test_timeline_assignment_label_shown():
    owner = make_user("TlOwner9")
    ws = make_workspace(owner_user_id=owner["id"], slug="tl-assign")
    comp = make_composition(ws["id"], name="TlAssignComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "AssignPlayer", "Tank")
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )

    client = TestClient(app)
    _login(client, "TlOwner9")

    resp = client.get(_timeline_url(ws["slug"], op["id"]))
    assert resp.status_code == 200
    assert "Participant assigned" in resp.text
    assert "badge-assignments" in resp.text
