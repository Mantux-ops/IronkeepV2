"""
Slice 6 — Zero-slot / empty-operation tactical warning tests.

Informational warnings surface on the operation detail and planner pages
when the attached composition has no slot templates.  All existing actions
(attach, generate, publish, planner access) remain allowed.

Covers:
  Group 1 — operation_detail.html: Tactical Composition card warnings
  Group 2 — operation_detail.html: Roster Slots card (Generate Slots suppressed)
  Group 3 — post_generate_slots: flash message for zero-slot generation
  Group 4 — operation_planner.html: empty-state split by plan presence
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_zero_slot_comp(ws_id: str, name: str = "Zero Comp") -> dict:
    return use_cases.create_albion_composition(
        guild_workspace_id=ws_id,
        name=name,
        description=None,
        slots=[],
    )


def _make_normal_comp(ws_id: str, name: str = "Normal Comp") -> dict:
    return make_composition(ws_id, name=name)


def _attach_and_get_detail(
    client: TestClient, slug: str, ws_id: str, op_id: str, comp_id: str
) -> "Response":
    """Attach composition to operation and return the rendered detail page."""
    use_cases.attach_operation_plan(ws_id, op_id, comp_id)
    return client.get(f"/workspaces/{slug}/operations/{op_id}")


# ---------------------------------------------------------------------------
# Group 1 — Tactical Composition card warnings
# ---------------------------------------------------------------------------

class TestTacticalCompositionCardWarnings:
    """operation_detail.html Tactical Composition card shows informational note
    for a zero-slot composition; no warning for a composition with slots."""

    def test_zero_slot_composition_warning_visible(self):
        owner  = make_user("TcWarn-owner-1")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-tc-1")
        client = TestClient(app)
        _login(client, "TcWarn-owner-1")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        resp = _attach_and_get_detail(client, "zsw-tc-1", ws["id"], op["id"], comp["id"])

        assert resp.status_code == 200
        assert "currently has no slot templates" in resp.text

    def test_zero_slot_edit_slots_link_visible(self):
        owner  = make_user("TcWarn-owner-2")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-tc-2")
        client = TestClient(app)
        _login(client, "TcWarn-owner-2")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        resp = _attach_and_get_detail(client, "zsw-tc-2", ws["id"], op["id"], comp["id"])

        assert resp.status_code == 200
        assert f"/compositions/{comp['id']}/edit" in resp.text

    def test_normal_composition_no_warning(self):
        owner  = make_user("TcWarn-owner-3")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-tc-3")
        client = TestClient(app)
        _login(client, "TcWarn-owner-3")

        comp = _make_normal_comp(ws["id"])
        op   = make_operation(ws["id"])
        resp = _attach_and_get_detail(client, "zsw-tc-3", ws["id"], op["id"], comp["id"])

        assert resp.status_code == 200
        assert "currently has no slot templates" not in resp.text


# ---------------------------------------------------------------------------
# Group 2 — Roster Slots card: Generate Slots button behaviour
# ---------------------------------------------------------------------------

class TestRosterSlotsCardWarnings:
    """Generate Slots button hidden for zero-slot compositions; informational
    note shown instead.  Button still visible for compositions with slots."""

    def test_generate_slots_button_hidden_for_zero_slot_comp(self):
        owner  = make_user("RsWarn-owner-1")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-rs-1")
        client = TestClient(app)
        _login(client, "RsWarn-owner-1")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        resp = _attach_and_get_detail(client, "zsw-rs-1", ws["id"], op["id"], comp["id"])

        assert resp.status_code == 200
        assert "generate-slots" not in resp.text

    def test_informational_note_visible_for_zero_slot_comp(self):
        owner  = make_user("RsWarn-owner-2")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-rs-2")
        client = TestClient(app)
        _login(client, "RsWarn-owner-2")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        resp = _attach_and_get_detail(client, "zsw-rs-2", ws["id"], op["id"], comp["id"])

        assert resp.status_code == 200
        assert "Add slots before generating" in resp.text

    def test_generate_slots_button_visible_for_normal_comp(self):
        owner  = make_user("RsWarn-owner-3")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-rs-3")
        client = TestClient(app)
        _login(client, "RsWarn-owner-3")

        comp = _make_normal_comp(ws["id"])
        op   = make_operation(ws["id"])
        resp = _attach_and_get_detail(client, "zsw-rs-3", ws["id"], op["id"], comp["id"])

        assert resp.status_code == 200
        assert "generate-slots" in resp.text
        assert "Generate Slots" in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Flash message for zero-slot generation
# ---------------------------------------------------------------------------

class TestGenerateSlotsFlashMessage:
    """post_generate_slots emits a descriptive flash when 0 slots are generated;
    normal generation flash is unchanged."""

    def test_zero_slot_generation_flash_mentions_no_templates(self):
        owner  = make_user("FlashWarn-owner-1")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-flash-1")
        client = TestClient(app)
        _login(client, "FlashWarn-owner-1")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])

        resp = client.post(
            f"/workspaces/zsw-flash-1/operations/{op['id']}/generate-slots",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "no slot templates" in resp.text

    def test_normal_generation_flash_shows_slot_count(self):
        owner  = make_user("FlashWarn-owner-2")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-flash-2")
        client = TestClient(app)
        _login(client, "FlashWarn-owner-2")

        comp = _make_normal_comp(ws["id"])
        op   = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])

        resp = client.post(
            f"/workspaces/zsw-flash-2/operations/{op['id']}/generate-slots",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "slots generated" in resp.text
        assert "no slot templates" not in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Planner empty-state split by plan presence
# ---------------------------------------------------------------------------

class TestPlannerEmptyState:
    """operation_planner.html shows different empty-state messages depending
    on whether a plan is attached (composition may be empty) vs. no plan yet."""

    def test_plan_attached_zero_slots_shows_composition_message(self):
        owner  = make_user("PlanWarn-owner-1")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-plan-1")
        client = TestClient(app)
        _login(client, "PlanWarn-owner-1")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        resp = client.get(f"/workspaces/zsw-plan-1/operations/{op['id']}/planner")
        assert resp.status_code == 200
        # Party grid empty state: plan attached, 0 slots
        assert "may not have slot templates yet" in resp.text
        assert "Return to Overview" in resp.text

    def test_plan_attached_zero_slots_no_original_fallback_message(self):
        """When a plan is attached and 0 slots exist, the old generic fallback
        'No roster slots generated yet' is replaced by the specific message."""
        owner  = make_user("PlanWarn-owner-2")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-plan-2")
        client = TestClient(app)
        _login(client, "PlanWarn-owner-2")

        comp = _make_zero_slot_comp(ws["id"])
        op   = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        resp = client.get(f"/workspaces/zsw-plan-2/operations/{op['id']}/planner")
        assert resp.status_code == 200
        assert "No roster slots generated yet" not in resp.text

    def test_no_plan_shows_generic_no_slots_message(self):
        """Without a plan attached the original 'No roster slots generated yet' message is kept."""
        owner  = make_user("PlanWarn-owner-3")
        ws     = make_workspace(owner_user_id=owner["id"], slug="zsw-plan-3")
        client = TestClient(app)
        _login(client, "PlanWarn-owner-3")

        op = make_operation(ws["id"])
        use_cases.publish_operation(ws["id"], op["id"])

        resp = client.get(f"/workspaces/zsw-plan-3/operations/{op['id']}/planner")
        assert resp.status_code == 200
        assert "No roster slots generated yet" in resp.text
        # The "may not have slot templates" message must NOT appear without a plan
        assert "may not have slot templates yet" not in resp.text
