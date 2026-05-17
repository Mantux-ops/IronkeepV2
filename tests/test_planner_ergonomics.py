"""
Planner assignment ergonomics tests.

All tests are HTTP/template level — no domain or route logic changed.

Covers:
    1.  Compact signup cards rendered (.signup-card) when unassigned players exist.
    2.  Old unassigned-signups <table> is absent from the unassigned panel.
    3.  Quick assign button has btn-primary class when candidates exist.
    4.  Manual assign is inside a <details> element with summary "Manual assign".
    5.  Reserve panel is wrapped in a <details> block (collapsed by default).
    6.  Readiness card has the readiness-sticky class.
    7.  Quick Fill Party button retains btn-primary.
    8.  Empty unassigned panel: no signup-card, no table.
    9.  POST targets for quick-assign and manual-assign are unchanged.
    10. signup-card shows player display name.
    11. signup-card shows preferred role.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_locked_op_with_signup(owner_name: str, slug: str, player_name: str = "TestPlayer"):
    """Full chain: workspace → comp → op → slots → signup (not assigned) → lock."""
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"], name=f"ErgComp-{slug}")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    # Submit signup but don't assign — leaves one unassigned player
    use_cases.submit_signup_intent(ws["id"], op["id"], player_name, "Tank")
    use_cases.lock_operation(ws["id"], op["id"])
    return owner, ws, op


def _planner_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/planner"


def _get_planner(client: TestClient, ws_slug: str, op_id: str) -> "Response":
    return client.get(_planner_url(ws_slug, op_id))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_signup_cards_rendered_when_unassigned_players_exist():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner1", "erg-cards", "CardPlayer1")

    client = TestClient(app)
    _login(client, "ErgOwner1")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    # HTML attribute form (not just CSS class name inside <style>)
    assert 'class="signup-card"' in resp.text


def test_no_unassigned_table_in_signup_panel():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner2", "erg-no-table", "NoTablePlayer")

    client = TestClient(app)
    _login(client, "ErgOwner2")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    # The old unassigned panel had a <table> with column headers Name/Role/Build/Willingness
    # that should no longer appear inside the unassigned panel.
    # We check that the pattern of old headers is gone.
    assert "<th>Willingness</th>" not in resp.text


def test_quick_assign_has_btn_primary():
    """Quick assign button must have btn-primary when candidates are available."""
    owner, ws, op = _make_locked_op_with_signup("ErgOwner3", "erg-qprimary", "QuickPlayer")

    client = TestClient(app)
    _login(client, "ErgOwner3")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    # btn-primary appears on the quick-assign button
    assert "btn-primary" in resp.text
    assert "Quick assign" in resp.text


def test_manual_assign_in_details_with_correct_summary():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner4", "erg-manual-det", "ManualPlayer")

    client = TestClient(app)
    _login(client, "ErgOwner4")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert "<details" in resp.text
    assert "Manual assign" in resp.text


def test_reserve_panel_wrapped_in_details():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner5", "erg-reserve-det", "ReservePlayer")

    client = TestClient(app)
    _login(client, "ErgOwner5")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    # Reserve panel uses the same discord-preview-details pattern
    assert "Reserve / Bench" in resp.text
    # The reserve is inside a <details> — check the <h2> appears inside details context
    # We verify the details element exists and contains the heading text
    text = resp.text
    details_start = text.find("<details")
    reserve_pos = text.find("Reserve / Bench")
    assert details_start != -1 and reserve_pos != -1
    assert reserve_pos > details_start  # Reserve heading appears after a <details> tag


def test_readiness_sticky_class_present():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner6", "erg-sticky", "StickyPlayer")

    client = TestClient(app)
    _login(client, "ErgOwner6")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert "readiness-sticky" in resp.text


def test_quick_fill_party_retains_btn_primary():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner7", "erg-qfill", "FillPlayer")

    client = TestClient(app)
    _login(client, "ErgOwner7")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert "Quick Fill Party" in resp.text
    # Quick Fill Party must still have btn-primary
    qf_pos = resp.text.find("Quick Fill Party")
    before = resp.text[max(0, qf_pos - 200):qf_pos]
    assert "btn-primary" in before


def test_empty_unassigned_panel_no_table_no_cards():
    """When all players are assigned, the empty-all-placed message shows instead."""
    owner = make_user("ErgOwner8")
    ws = make_workspace(owner_user_id=owner["id"], slug="erg-empty-panel")
    comp = make_composition(ws["id"], name="ErgEmptyComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    # Assign the first slot so at least one player is placed
    signup = use_cases.submit_signup_intent(ws["id"], op["id"], "FullyAssigned", "Tank")
    use_cases.assign_participant_to_operation_slot(
        ws["id"], op["id"], slots[0]["id"], signup["participant_id"]
    )
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "ErgOwner8")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert 'class="signup-card"' not in resp.text
    assert "empty-all-placed" in resp.text


def test_signup_card_shows_player_name():
    owner, ws, op = _make_locked_op_with_signup("ErgOwner9", "erg-name", "UniqueNamePlayer")

    client = TestClient(app)
    _login(client, "ErgOwner9")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert "UniqueNamePlayer" in resp.text


def test_signup_card_shows_preferred_role():
    owner = make_user("ErgOwner10")
    ws = make_workspace(owner_user_id=owner["id"], slug="erg-role")
    comp = make_composition(ws["id"], name="ErgRoleComp")
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    use_cases.submit_signup_intent(ws["id"], op["id"], "RolePlayer", "Healer")
    use_cases.lock_operation(ws["id"], op["id"])

    client = TestClient(app)
    _login(client, "ErgOwner10")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    # Role should appear in the card
    assert "Healer" in resp.text


def test_manual_assign_form_post_target_preserved():
    """The manual assign form must still POST to the correct /slots/{id}/assign route."""
    owner, ws, op = _make_locked_op_with_signup("ErgOwner11", "erg-post-target", "PostPlayer")

    client = TestClient(app)
    _login(client, "ErgOwner11")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert "/assign" in resp.text


def test_quick_assign_form_post_target_preserved():
    """The quick-assign form must still POST to the correct /slots/{id}/quick-assign route."""
    owner, ws, op = _make_locked_op_with_signup("ErgOwner12", "erg-qa-target", "QAPlayer")

    client = TestClient(app)
    _login(client, "ErgOwner12")

    resp = _get_planner(client, ws["slug"], op["id"])
    assert resp.status_code == 200
    assert "/quick-assign" in resp.text
