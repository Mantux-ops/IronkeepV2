"""
Phase 8.6 Slice B — Planner Readiness Instrument Surface

Tests for:
  1. Readiness fill bar rendering and percentage display
  2. State-coloured fill bar classes (ready / forming / not_ready)
  3. Zero-slot safety (0%, no crash)
  4. Domain readiness calculations unchanged
  5. comp-overview accent border in tactical.css
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.application import use_cases
from app import database, repositories
from app.domain.readiness import calculate_readiness_state
from app.main import app

from tests.conftest import (
    make_composition,
    make_operation,
    make_user,
    make_workspace,
    publish_operation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planning_op(owner_name: str, slug: str, *, slots=None):
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"], slots=slots)
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots_out = use_cases.generate_operation_slots(ws["id"], op["id"])
    publish_operation(ws["id"], op["id"])
    return owner, ws, op, slots_out


def _planner(client: TestClient, ws: dict, op: dict):
    return client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}/planner")


def _assign_n_slots(ws_id: str, op_id: str, slots: list[dict], n: int) -> None:
    for i in range(n):
        signup = use_cases.submit_signup_intent(ws_id, op_id, f"Player-{i}", "Healer")
        use_cases.assign_participant_to_operation_slot(
            ws_id, op_id, slots[i]["id"], signup["participant_id"]
        )


# ---------------------------------------------------------------------------
# Group 1 — Readiness fill bar rendering
# ---------------------------------------------------------------------------

class TestReadinessFillBar:
    def setup_method(self):
        self.owner, self.ws, self.op, self.slots = _make_planning_op(
            "rdy-inst-owner", "rdy-inst"
        )
        self.client = TestClient(app)
        _login(self.client, "rdy-inst-owner")

    def test_readiness_fill_bar_renders(self):
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        resp = _planner(self.client, self.ws, self.op)
        assert resp.status_code == 200
        assert "readiness-fill" in resp.text
        assert "readiness-fill__track" in resp.text
        assert "readiness-fill__bar" in resp.text
        assert 'role="progressbar"' in resp.text

    def test_correct_percentage_is_rendered(self):
        """3 of 5 slots assigned → 60% displayed and bar width."""
        _assign_n_slots(self.ws["id"], self.op["id"], self.slots, 3)
        resp = _planner(self.client, self.ws, self.op)
        assert resp.status_code == 200
        assert "60%" in resp.text
        assert 'style="width: 60%;"' in resp.text
        assert "3 / 5 assigned" in resp.text

    def test_zero_total_slots_renders_zero_percent(self):
        """Zero-slot operation must show 0% without error."""
        import uuid

        owner = make_user("rdy-inst-zero-owner")
        ws = make_workspace(owner_user_id=owner["id"], slug="rdy-inst-zero")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Empty Shell",
            description=None,
            slots=[],
        )
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        publish_operation(ws["id"], op["id"])
        # calculate_readiness_snapshot rejects zero-slot ops — insert snapshot directly
        snap = {
            "id": str(uuid.uuid4()),
            "guild_workspace_id": ws["id"],
            "guild_operation_id": op["id"],
            "total_slots": 0,
            "assigned_slots": 0,
            "open_slots": 0,
            "unassigned_signup_count": 0,
            "missing_roles_json": "{}",
            "missing_builds_json": "{}",
            "attendance_marked_count": 0,
            "attendance_unmarked_count": 0,
            "scout_count": 0,
            "support_count": 0,
            "reserve_count": 0,
            "readiness_state": "not_ready",
            "created_at": "2026-06-01T12:00:00+00:00",
        }
        with database.transaction() as db:
            repositories.insert_readiness_snapshot(db, snap)

        client = TestClient(app)
        _login(client, "rdy-inst-zero-owner")
        resp = _planner(client, ws, op)
        assert resp.status_code == 200
        assert "0%" in resp.text
        assert 'style="width: 0%;"' in resp.text
        assert "0 / 0 assigned" in resp.text

    def test_badge_emphasis_class_present_in_planner(self):
        use_cases.calculate_readiness_snapshot(self.ws["id"], self.op["id"])
        resp = _planner(self.client, self.ws, self.op)
        assert "readiness-bar__badge" in resp.text


# ---------------------------------------------------------------------------
# Group 2 — State-coloured fill bar classes
# ---------------------------------------------------------------------------

class TestReadinessFillBarStateClasses:
    def setup_method(self):
        self.client = TestClient(app)

    def _render_with_assignments(self, slug: str, n_assign: int):
        owner, ws, op, slots = _make_planning_op(f"{slug}-owner", slug)
        _login(self.client, f"{slug}-owner")
        if n_assign:
            _assign_n_slots(ws["id"], op["id"], slots, n_assign)
        else:
            use_cases.calculate_readiness_snapshot(ws["id"], op["id"])
        return _planner(self.client, ws, op)

    def test_ready_state_uses_ready_class(self):
        resp = self._render_with_assignments("rdy-ready", 5)
        assert resp.status_code == 200
        assert "readiness-fill--ready" in resp.text
        assert "badge-ready" in resp.text
        assert "100%" in resp.text

    def test_forming_state_uses_forming_class(self):
        """4/5 assigned = 80% → forming."""
        resp = self._render_with_assignments("rdy-forming", 4)
        assert resp.status_code == 200
        assert "readiness-fill--forming" in resp.text
        assert "badge-forming" in resp.text
        assert "80%" in resp.text

    def test_not_ready_state_uses_not_ready_class(self):
        resp = self._render_with_assignments("rdy-crit", 0)
        assert resp.status_code == 200
        assert "readiness-fill--not_ready" in resp.text
        assert "badge-not_ready" in resp.text
        assert "0%" in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Domain calculations unchanged (no template-side logic drift)
# ---------------------------------------------------------------------------

class TestReadinessCalculationsUnchanged:
    def test_calculate_readiness_state_thresholds(self):
        assert calculate_readiness_state(0, 0) == "not_ready"
        assert calculate_readiness_state(5, 0) == "ready"
        assert calculate_readiness_state(5, 1) == "forming"   # 80%
        assert calculate_readiness_state(5, 2) == "not_ready"   # 60%
        assert calculate_readiness_state(4, 1) == "forming"   # 75%

    def test_snapshot_state_matches_domain_after_assignments(self):
        owner, ws, op, slots = _make_planning_op(
            "rdy-domain-owner", "rdy-domain"
        )
        _assign_n_slots(ws["id"], op["id"], slots, 4)
        snap = use_cases.calculate_readiness_snapshot(ws["id"], op["id"])
        assert snap["assigned_slots"] == 4
        assert snap["total_slots"] == 5
        assert snap["readiness_state"] == "forming"


# ---------------------------------------------------------------------------
# Group 4 — comp-overview accent
# ---------------------------------------------------------------------------

class TestCompOverviewAccent:
    def test_comp_overview_accent_in_tactical_css(self):
        css = Path("app/static/css/tactical.css").read_text(encoding="utf-8")
        assert "border-left: 3px solid var(--accent)" in css

    def test_planner_still_renders_comp_overview(self):
        owner, ws, op, _ = _make_planning_op("rdy-ovw-owner", "rdy-ovw")
        client = TestClient(app)
        _login(client, "rdy-ovw-owner")
        resp = _planner(client, ws, op)
        assert resp.status_code == 200
        assert 'class="comp-overview"' in resp.text
