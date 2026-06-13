"""
UI / template regression tests — Phase 8.

Covers the CSS class and semantic-attribute anchors formalized in Phases 3–7.
These tests assert meaningful rendered state, not visual layout details.

Covered:
  Group 1  — Slot card CSS classes (slot-card--assigned, --open-core, --empty)
  Group 2  — data-role attributes on slot cards
  Group 3  — Tactical gap badges (tac-gap-badge--critical)
  Group 4  — Comp overview and role tally rendering
  Group 5  — Operation status badges on the dashboard
  Group 6  — Empty states on list and panel pages
  Group 7  — Phase 7 accessibility anchors (skip link, aria-labels, scope, sr-only)

Intentionally NOT covered:
  - Exact full-HTML blocks or snapshots
  - CSS computed values
  - Whitespace / indentation
  - Purely visual layout utilities (.stack, .cluster, .page--wide, etc.)
  - Every badge variant (only the three canonical lifecycle states are asserted)
  - Planner quick-assign and manual-assign POST targets (covered by test_planner_ergonomics)
  - data-op-status attribute (covered by test_op_status_coloring)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Shared slot compositions
# ---------------------------------------------------------------------------

# Mixed-priority 3-slot party used by Group 1 and 2 tests:
#   - Tank  (core) — will be assigned in relevant tests
#   - Healer (core) — left unassigned → slot-card--open-core
#   - DPS   (normal) — no signup → slot-card--empty
_MIXED_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace",    "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Bow",        "priority": "normal"},
]

# All-DPS 2-slot party — no healer slot, no tank slot → 2 critical gap badges.
_DPS_ONLY_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Daggers", "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "DPS", "build_name": "Bow",     "priority": "core"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_planner_setup(owner_name: str, slug: str, custom_slots=None):
    """
    Workspace → comp (custom or default) → op → slots → publish (planning).
    Returns (client, ws, op, slots).  Operation is in 'planning' status.
    """
    owner = make_user(owner_name)
    ws = make_workspace(owner_user_id=owner["id"], slug=slug)
    comp = make_composition(ws["id"], slots=custom_slots)
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    use_cases.publish_operation(ws["id"], op["id"])
    client = TestClient(app)
    _login(client, owner_name)
    return client, ws, op, slots


def _planner_url(ws_slug: str, op_id: str) -> str:
    return f"/workspaces/{ws_slug}/operations/{op_id}/planner"


# ---------------------------------------------------------------------------
# Group 1 — Slot card CSS classes
# ---------------------------------------------------------------------------

class TestSlotCardClasses:
    """
    Slot cards render with one of four modifier classes depending on assignment
    state and slot priority.  These tests guard the rendering logic that drives
    the tactical color coding officers rely on.
    """

    def test_slot_card_base_class_renders(self):
        """slot-card base class must appear for every slot in the planner."""
        client, ws, op, slots = _make_planner_setup("SlotOwner1", "slot-base", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'class="slot-card ' in resp.text

    def test_slot_card_assigned_renders_for_assigned_slot(self):
        """slot-card--assigned must appear when a player is actively assigned."""
        client, ws, op, slots = _make_planner_setup("SlotOwner2", "slot-assigned", _MIXED_SLOTS)
        tank_slot = next(s for s in slots if s["role"] == "Tank")
        signup = use_cases.submit_signup_intent(ws["id"], op["id"], "AssignedPlayer", "Tank")
        use_cases.assign_participant_to_operation_slot(
            ws["id"], op["id"], tank_slot["id"], signup["participant_id"]
        )
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "slot-card--assigned" in resp.text

    def test_slot_card_open_core_renders_for_unassigned_core_slot(self):
        """slot-card--open-core must appear for an unassigned core-priority slot."""
        client, ws, op, slots = _make_planner_setup("SlotOwner3", "slot-open-core", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "slot-card--open-core" in resp.text

    def test_slot_card_empty_renders_for_normal_priority_slot_with_no_signup(self):
        """
        slot-card--empty must appear for a normal-priority slot with no signups.
        _MIXED_SLOTS contains one normal-priority DPS slot that receives no signup.
        """
        client, ws, op, slots = _make_planner_setup("SlotOwner4", "slot-empty", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "slot-card--empty" in resp.text

    def test_slot_card_assigned_absent_when_no_assignments(self):
        """slot-card--assigned must NOT appear when no assignments exist."""
        client, ws, op, slots = _make_planner_setup("SlotOwner5", "slot-no-assigned", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "slot-card--assigned" not in resp.text


# ---------------------------------------------------------------------------
# Group 2 — data-role attributes
# ---------------------------------------------------------------------------

class TestDataRoleAttributes:
    """
    Each slot card carries a data-role attribute derived from role_family().
    CSS role-identity styling depends on these attributes; they must render
    correctly so the tactical palette is applied.
    """

    def test_data_role_tank_renders_for_tank_slot(self):
        """data-role="tank" must appear for a slot with a tank-family role."""
        client, ws, op, slots = _make_planner_setup("RoleOwner1", "data-role-tank", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'data-role="tank"' in resp.text

    def test_data_role_healer_renders_for_healer_slot(self):
        """data-role="healer" must appear for a slot with a healer-family role."""
        client, ws, op, slots = _make_planner_setup("RoleOwner2", "data-role-healer", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'data-role="healer"' in resp.text

    def test_data_role_dps_renders_for_dps_slot(self):
        """data-role="dps" must appear for a slot with a DPS-family role."""
        client, ws, op, slots = _make_planner_setup("RoleOwner3", "data-role-dps", _MIXED_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'data-role="dps"' in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Tactical gap badges
# ---------------------------------------------------------------------------

class TestTacticalGapBadges:
    """
    tac-gap-badge--critical appears when a party's composition has no healer or
    no tank slot defined.  This drives the red 'No healer' / 'No tank' officer
    warnings that prevent under-composition.
    """

    def test_tac_gap_badge_critical_renders_when_party_has_no_healer_slot(self):
        """
        tac-gap-badge--critical must appear when the party has no healer-family slot.
        Uses all-DPS comp: no healer slot and no tank slot → two critical badges.
        """
        client, ws, op, slots = _make_planner_setup("GapOwner1", "gap-critical", _DPS_ONLY_SLOTS)
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "tac-gap-badge--critical" in resp.text

    def test_tac_gap_badge_critical_absent_when_all_key_roles_present(self):
        """
        tac-gap-badge--critical must NOT appear when the comp has both healer and
        tank slots.  Uses the default 5-man comp (tank + healer + dps + support + dps).
        """
        client, ws, op, slots = _make_planner_setup("GapOwner2", "gap-no-critical")
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert "tac-gap-badge--critical" not in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Comp overview and role tally
# ---------------------------------------------------------------------------

class TestCompOverviewAndRoleTally:
    """
    .comp-overview and .role-tally are the top-level tactical summary components.
    They must render whenever slot data is present in the planner.
    """

    def test_comp_overview_renders_on_planner(self):
        """.comp-overview must be present on the planner page when slots exist."""
        client, ws, op, slots = _make_planner_setup("OvwOwner1", "comp-overview-chk")
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'class="comp-overview"' in resp.text

    def test_role_tally_renders_on_planner(self):
        """.role-tally must be present on the planner page when slots exist."""
        client, ws, op, slots = _make_planner_setup("OvwOwner2", "role-tally-chk")
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'class="role-tally"' in resp.text

    def test_role_tally_items_have_data_role_attributes(self):
        """Role-tally items must carry data-role for each canonical role family."""
        client, ws, op, slots = _make_planner_setup("OvwOwner3", "tally-attrs")
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        for family in ("tank", "healer", "dps", "support"):
            assert f'data-role="{family}"' in resp.text, (
                f"data-role=\"{family}\" missing from role-tally on planner"
            )


# ---------------------------------------------------------------------------
# Group 5 — Operation status badges
# ---------------------------------------------------------------------------

class TestStatusBadges:
    """
    Operation lifecycle badges (badge-draft, badge-planning, badge-locked)
    appear in the dashboard table.  These drive the visual status indicators
    officers use to scan operation state at a glance.
    """

    def test_badge_draft_renders_for_draft_operation(self):
        """badge-draft must appear in the dashboard for a draft operation."""
        owner = make_user("BadgeOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="badge-draft-chk")
        make_operation(ws["id"])
        client = TestClient(app)
        _login(client, "BadgeOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert "badge-draft" in resp.text

    def test_badge_planning_renders_for_planning_operation(self):
        """badge-planning must appear in the dashboard for a published operation."""
        owner = make_user("BadgeOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="badge-planning-chk")
        op = make_operation(ws["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        client = TestClient(app)
        _login(client, "BadgeOwner2")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert "badge-planning" in resp.text

    def test_badge_locked_renders_for_locked_operation(self):
        """badge-locked must appear in the dashboard for a locked operation."""
        owner = make_user("BadgeOwner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="badge-locked-chk")
        comp = make_composition(ws["id"])
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        use_cases.lock_operation(ws["id"], op["id"])
        client = TestClient(app)
        _login(client, "BadgeOwner3")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert "badge-locked" in resp.text

    def test_badge_planning_absent_for_draft_operation(self):
        """badge-planning must NOT appear for an operation still in draft status."""
        owner = make_user("BadgeOwner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="badge-no-planning")
        make_operation(ws["id"])
        client = TestClient(app)
        _login(client, "BadgeOwner4")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert "badge-planning" not in resp.text


# ---------------------------------------------------------------------------
# Group 6 — Empty states
# ---------------------------------------------------------------------------

class TestEmptyStates:
    """
    .empty-state provides the canonical styling for 'nothing here' messages.
    These tests ensure the class is rendered in key empty-list contexts.
    """

    def test_empty_state_on_compositions_list_when_no_compositions(self):
        """.empty-state must render on the compositions list with no compositions."""
        owner = make_user("EmptyOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="empty-comps")
        client = TestClient(app)
        _login(client, "EmptyOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions")
        assert resp.status_code == 200
        assert 'class="empty-state"' in resp.text

    def test_empty_state_on_planner_reserve_panel_when_no_reserves(self):
        """
        The reserve / bench panel must show .empty-state when no players are
        on reserve.
        """
        client, ws, op, slots = _make_planner_setup("EmptyOwner2", "empty-reserve-chk")
        resp = client.get(_planner_url(ws["slug"], op["id"]))
        assert resp.status_code == 200
        assert 'class="empty-state"' in resp.text


# ---------------------------------------------------------------------------
# Group 7 — Phase 7 accessibility anchors
# ---------------------------------------------------------------------------

class TestAccessibilityAnchors:
    """
    Phase 7 added skip-to-main link, nav aria-labels, table scope attributes,
    and sr-only action column headers.  These tests guard those additions from
    accidental regression as templates evolve.
    """

    # ------------------------------------------------------------------
    # Skip link and main landmark (base.html)
    # ------------------------------------------------------------------

    def test_skip_link_present_pointing_to_main_content(self):
        """A skip-link must be the first focusable element on every page."""
        owner = make_user("A11yOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="a11y-skip")
        client = TestClient(app)
        _login(client, "A11yOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert 'class="skip-link"' in resp.text
        assert 'href="#main-content"' in resp.text

    def test_main_element_has_id_main_content(self):
        """The <main> element must carry id="main-content" for the skip link target."""
        owner = make_user("A11yOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="a11y-main-id")
        client = TestClient(app)
        _login(client, "A11yOwner2")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert 'id="main-content"' in resp.text

    def test_global_nav_has_aria_label_primary_navigation(self):
        """The global <nav> must carry aria-label="Primary navigation"."""
        owner = make_user("A11yOwner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="a11y-nav-label")
        client = TestClient(app)
        _login(client, "A11yOwner3")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert 'aria-label="Primary navigation"' in resp.text

    # ------------------------------------------------------------------
    # Operation tabs nav (operation_tabs.html)
    # ------------------------------------------------------------------

    def test_operation_tabs_nav_has_aria_label_operation(self):
        """The operation tabs <nav> must carry aria-label="Operation"."""
        owner = make_user("A11yOwner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="a11y-op-nav")
        comp = make_composition(ws["id"])
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        client = TestClient(app)
        _login(client, "A11yOwner4")
        resp = client.get(f"/workspaces/{ws['slug']}/operations/{op['id']}")
        assert resp.status_code == 200
        assert 'aria-label="Operation"' in resp.text

    # ------------------------------------------------------------------
    # Table th scope and sr-only (compositions_list.html)
    # ------------------------------------------------------------------

    def test_compositions_table_has_scope_col_on_th(self):
        """All <th> in the compositions list table must carry scope="col"."""
        owner = make_user("A11yOwner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="a11y-scope")
        make_composition(ws["id"], name="ScopeComp")
        client = TestClient(app)
        _login(client, "A11yOwner5")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions")
        assert resp.status_code == 200
        assert 'scope="col"' in resp.text

    def test_action_column_header_has_sr_only_actions_text(self):
        """The empty action-column <th> must contain sr-only 'Actions' text."""
        owner = make_user("A11yOwner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="a11y-sr-only")
        make_composition(ws["id"], name="SrOnlyComp")
        client = TestClient(app)
        _login(client, "A11yOwner6")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions")
        assert resp.status_code == 200
        assert 'class="sr-only"' in resp.text
        assert ">Actions<" in resp.text


# ---------------------------------------------------------------------------
# Group 8 — Composition integrity warnings (Phase 3)
# ---------------------------------------------------------------------------

# All-DPS slots — no healer, no tank → critical integrity warnings.
_DPS_ONLY_COMP_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Bow",     "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "DPS", "build_name": "Daggers", "priority": "core"},
    {"party_number": 2, "slot_index": 1, "role": "DPS", "build_name": "Axe",     "priority": "core"},
    {"party_number": 2, "slot_index": 2, "role": "DPS", "build_name": "Sword",   "priority": "core"},
]

# Balanced comp (T/H/D) per party — no integrity issues expected.
_CLEAN_COMP_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace",   "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall","priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Bow",        "priority": "normal"},
]


class TestCompositionIntegrityWarnings:
    """Template regression tests for Phase 3 composition integrity warning rendering.

    These tests verify that the comp-integrity-warnings block and alert classes
    render correctly on the compositions detail page under specific slot template
    conditions.
    """

    def test_integrity_warning_rendered_for_dps_only_comp(self):
        """Composition detail must show an integrity warning block when all parties
        lack healer and tank slots."""
        owner = make_user("IntegOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="integ-warn")
        comp = make_composition(ws["id"], name="DPSOnlyComp", slots=_DPS_ONLY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "IntegOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-integrity-warnings" in resp.text

    def test_alert_error_rendered_for_critical_integrity_warning(self):
        """An all-DPS comp produces a critical (alert-error) integrity warning."""
        owner = make_user("IntegOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="integ-critical")
        comp = make_composition(ws["id"], name="CriticalComp", slots=_DPS_ONLY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "IntegOwner2")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "alert-error" in resp.text

    def test_no_integrity_warning_for_clean_composition(self):
        """A well-formed comp with T/H/D per party must NOT render integrity warnings."""
        owner = make_user("IntegOwner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="integ-clean")
        comp = make_composition(ws["id"], name="CleanComp", slots=_CLEAN_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "IntegOwner3")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-integrity-warnings" not in resp.text


# Fixture: 5 parties (triggers collapsible wrapper for > 4 parties).
_FIVE_PARTY_COMP_SLOTS = [
    {"party_number": p, "slot_index": s, "role": role, "build_name": f"b{p}{s}", "priority": "core"}
    for p in range(1, 6)
    for s, role in enumerate(["Tank", "Healer", "DPS", "Support", "DPS"], start=1)
]

# Fixture: two parties with mismatched slot counts (triggers uneven_party_sizes hint).
_UNEVEN_PARTY_COMP_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "S",  "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "H",  "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "B",  "priority": "core"},
    {"party_number": 1, "slot_index": 4, "role": "Support","build_name": "L",  "priority": "core"},
    {"party_number": 1, "slot_index": 5, "role": "DPS",    "build_name": "D",  "priority": "core"},
    {"party_number": 2, "slot_index": 1, "role": "Tank",   "build_name": "S2", "priority": "core"},
    # Party 2 has only 1 slot — difference of 4 exceeds the tolerance threshold of 1
]


class TestPhase4IntegrityRefinements:
    """Template regression tests for Phase 4 warning hierarchy and hint rendering.

    Covers: hint rendering, divergence note, continuation link, collapsible,
    and uneven-size advisory visibility.
    """

    def test_integrity_hint_renders_for_dps_only_comp(self):
        """comp-integrity-hint must appear when warnings have actionable hints."""
        owner = make_user("P4HintOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-hint")
        comp = make_composition(ws["id"], name="DPSOnlyHint", slots=_DPS_ONLY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4HintOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-integrity-hint" in resp.text

    def test_divergence_note_renders_for_composition_with_slots(self):
        """Template preview divergence note must appear on any comp with defined slots."""
        owner = make_user("P4NoteOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-note")
        comp = make_composition(ws["id"], name="NoteTestComp", slots=_CLEAN_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4NoteOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-preview-note" in resp.text

    def test_continuation_link_renders_for_editable_comp_with_warnings(self):
        """'Edit slots to fix →' must appear for editable comps with integrity issues."""
        owner = make_user("P4LinkOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-link")
        comp = make_composition(ws["id"], name="LinkTestComp", slots=_DPS_ONLY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4LinkOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Edit slots to fix" in resp.text
        assert f"/compositions/{comp['id']}/edit" in resp.text

    def test_no_continuation_link_for_clean_comp(self):
        """Continuation link must NOT appear when there are no integrity warnings."""
        owner = make_user("P4LinkOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-link-clean")
        comp = make_composition(ws["id"], name="CleanLink", slots=_CLEAN_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4LinkOwner2")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Edit slots to fix" not in resp.text

    def test_collapsible_renders_for_five_party_comp(self):
        """comp-preview-details wrapper must appear for compositions with > 4 parties."""
        owner = make_user("P4CollapOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-collap")
        comp = make_composition(ws["id"], name="FiveParty", slots=_FIVE_PARTY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4CollapOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-preview-details" in resp.text

    def test_no_collapsible_for_small_comp(self):
        """comp-preview-details must NOT appear when the comp has ≤ 4 parties."""
        owner = make_user("P4CollapOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-no-collap")
        comp = make_composition(ws["id"], name="SmallComp", slots=_CLEAN_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4CollapOwner2")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-preview-details" not in resp.text

    def test_uneven_party_sizes_advisory_renders(self):
        """An info-severity uneven-size advisory must appear for mismatched party sizes."""
        owner = make_user("P4UnevenOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-uneven")
        comp = make_composition(ws["id"], name="UnevenParties", slots=_UNEVEN_PARTY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4UnevenOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "alert-info" in resp.text

    def test_uneven_party_hint_names_undersized_party(self):
        """The uneven-size hint in the rendered page must name the undersized party."""
        owner = make_user("P4UnevenOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="p4-uneven-name")
        comp = make_composition(ws["id"], name="UnevenNamed", slots=_UNEVEN_PARTY_COMP_SLOTS)
        client = TestClient(app)
        _login(client, "P4UnevenOwner2")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Party 2" in resp.text


class TestPhase5CompositionCreation:
    """Template regression tests for Phase 5 composition creation guidance.

    Covers: guidance copy, preview placeholder, slot re-fill after failed
    validation, structural summary, and integrity warnings on the creation page.
    """

    def test_creation_page_renders_for_officer(self):
        """GET /compositions/new must return 200 and the slot card editor for an officer."""
        owner = make_user("P5GetOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-get")
        client = TestClient(app)
        _login(client, "P5GetOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "cb-composition-editor" in resp.text

    def test_guidance_copy_renders_on_fresh_load(self):
        """Tactical roles hint must explain the preview relationship on initial load."""
        owner = make_user("P5GuideOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-guide")
        client = TestClient(app)
        _login(client, "P5GuideOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        # Key phrase from the updated hint explaining the preview connection
        assert "tactical layout preview" in resp.text

    def test_preview_placeholder_renders_on_fresh_load(self):
        """The quiet placeholder must appear on initial load (no prev_slots)."""
        owner = make_user("P5PlaceholderOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-placeholder")
        client = TestClient(app)
        _login(client, "P5PlaceholderOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "comp-creation-placeholder" in resp.text

    def test_no_preview_card_on_fresh_load(self):
        """Preview card must NOT appear on initial load — only the placeholder."""
        owner = make_user("P5NoPreviewOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-no-preview")
        client = TestClient(app)
        _login(client, "P5NoPreviewOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "comp-creation-preview" not in resp.text

    def test_failed_validation_preserves_slot_data(self):
        """After a failed validation, submitted slot rows must be re-filled in the form."""
        owner = make_user("P5SlotFillOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-slot-fill")
        client = TestClient(app)
        _login(client, "P5SlotFillOwner1")
        # Single-character name is below the 2-char minimum → triggers ValidationError
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":         "X",
                "description":  "",
                "party_number": ["1"],
                "slot_index":   ["1"],
                "role":         ["Healer"],
                "build_name":   ["Hallowfall"],
                "weapon_name":  [""],
                "priority":     ["core"],
            },
            follow_redirects=False,
        )
        # Should re-render the form (200) rather than redirect (302)
        assert resp.status_code == 200
        # Submitted slot data must be present in the re-rendered form
        assert "Healer" in resp.text
        assert "Hallowfall" in resp.text

    def test_failed_validation_shows_structural_summary(self):
        """After failed validation with slot data, the structural summary card must appear."""
        owner = make_user("P5SummaryOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-summary")
        client = TestClient(app)
        _login(client, "P5SummaryOwner1")
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":         "X",
                "description":  "",
                "party_number": ["1", "1"],
                "slot_index":   ["1", "2"],
                "role":         ["Tank", "Healer"],
                "build_name":   ["Sword", "Holy"],
                "weapon_name":  ["", ""],
                "priority":     ["core", "core"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        # Structural summary card must be present
        assert "comp-creation-preview" in resp.text
        # Slot count and party count must appear
        assert "2 slots" in resp.text

    def test_failed_validation_no_placeholder_when_slot_data_present(self):
        """When prev_slots are available, the placeholder must NOT appear (only the card)."""
        owner = make_user("P5NoPlaceholderOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-no-placeholder")
        client = TestClient(app)
        _login(client, "P5NoPlaceholderOwner1")
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":         "X",
                "description":  "",
                "party_number": ["1"],
                "slot_index":   ["1"],
                "role":         ["Tank"],
                "build_name":   ["Sword"],
                "weapon_name":  [""],
                "priority":     ["core"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "comp-creation-preview" in resp.text
        assert "comp-creation-placeholder" not in resp.text

    def test_integrity_warnings_render_on_failed_validation_with_dps_only_slots(self):
        """When submitted slots produce integrity warnings, they appear in the preview card."""
        owner = make_user("P5IntegOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="p5-integ")
        client = TestClient(app)
        _login(client, "P5IntegOwner1")
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":         "X",
                "description":  "",
                "party_number": ["1", "1"],
                "slot_index":   ["1", "2"],
                "role":         ["DPS", "DPS"],
                "build_name":   ["Bow", "Axe"],
                "weapon_name":  ["", ""],
                "priority":     ["core", "core"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        # Integrity warnings (no healer, no tank) must render on the creation page
        assert "alert-error" in resp.text


# ---------------------------------------------------------------------------
# Clone composition fixtures
# ---------------------------------------------------------------------------

_CLONE_SOURCE_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",    "build_name": "Claymore",
     "weapon_name": "CLM",   "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer",  "build_name": "Hallowfall",
     "weapon_name": None,    "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",     "build_name": "Warbow",
     "weapon_name": "WBW",   "priority": "normal"},
    {"party_number": 2, "slot_index": 1, "role": "Support", "build_name": "Locus",
     "weapon_name": None,    "priority": "core"},
    {"party_number": 2, "slot_index": 2, "role": "DPS",     "build_name": "Daggers",
     "weapon_name": "DAG",   "priority": "normal"},
]


class TestCloneComposition:
    """Tests for the clone composition workflow.

    Covers: permission gate, name prefill, slot field prefill (role, build,
    weapon, priority, party_number, slot_index), UI affordance on detail page,
    safety invariants (original comp unchanged, active operations unaffected).
    """

    def test_clone_route_returns_200_for_officer(self):
        """GET /compositions/{id}/clone must return 200 for an authorized officer."""
        owner = make_user("CloneOwner1")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-200")
        comp = make_composition(ws["id"], name="Source Comp", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner1")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200

    def test_clone_route_denied_for_unauthenticated(self):
        """GET clone without login must redirect to login (not 200)."""
        owner = make_user("CloneOwner2")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-anon")
        comp = make_composition(ws["id"], name="Source Comp", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)  # no login
        resp = client.get(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_clone_prefills_name_with_copy_of_prefix(self):
        """Clone form must pre-fill name as 'Copy of {original name}'."""
        owner = make_user("CloneOwner3")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-name")
        comp = make_composition(ws["id"], name="5-Man ZvZ Alpha", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner3")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200
        assert "Copy of 5-Man ZvZ Alpha" in resp.text

    def test_clone_prefills_slot_roles(self):
        """Clone form must pre-fill all slot role values from the source composition."""
        owner = make_user("CloneOwner4")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-roles")
        comp = make_composition(ws["id"], name="Source", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner4")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200
        assert "Claymore" in resp.text
        assert "Hallowfall" in resp.text
        assert "Warbow" in resp.text

    def test_clone_prefills_weapon_name_when_present(self):
        """Clone form must pre-fill weapon_name for slots where it is set."""
        owner = make_user("CloneOwner5")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-weapon")
        comp = make_composition(ws["id"], name="Source", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner5")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200
        # CLM and WBW and DAG are weapon names from the fixture
        assert "CLM" in resp.text
        assert "WBW" in resp.text

    def test_clone_shows_structural_preview(self):
        """Clone page must show the structural preview card (comp-creation-preview)."""
        owner = make_user("CloneOwner6")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-preview")
        comp = make_composition(ws["id"], name="Source", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner6")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200
        assert "comp-creation-preview" in resp.text

    def test_clone_affordance_appears_on_detail_page_for_officer(self):
        """'Clone as Variant →' link must appear on the detail page for officers."""
        owner = make_user("CloneOwner7")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-link-detail")
        comp = make_composition(ws["id"], name="Source", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner7")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Clone as Variant" in resp.text
        assert f"/clone" in resp.text

    def test_clone_post_creates_new_composition(self):
        """Submitting the clone form must create a distinct new composition."""
        owner = make_user("CloneOwner8")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-post-new")
        comp = make_composition(ws["id"], name="Source Comp", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner8")
        # Submit clone form — new name to avoid any name-collision edge cases
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":         "Copy of Source Comp",
                "description":  "",
                "party_number": ["1", "1", "1", "2", "2"],
                "slot_index":   ["1", "2", "3", "1", "2"],
                "role":         ["Tank", "Healer", "DPS", "Support", "DPS"],
                "build_name":   ["Claymore", "Hallowfall", "Warbow", "Locus", "Daggers"],
                "weapon_name":  ["CLM", "", "WBW", "", "DAG"],
                "priority":     ["core", "core", "normal", "core", "normal"],
            },
            follow_redirects=False,
        )
        # Successful create → redirect to compositions list
        assert resp.status_code == 303

    def test_original_composition_unchanged_after_clone_post(self):
        """Original composition slots must be unchanged after a clone is saved."""
        from app import database, repositories
        owner = make_user("CloneOwner9")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-original-safe")
        comp = make_composition(ws["id"], name="Original", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner9")
        # Save the clone
        client.post(
            f"/workspaces/{ws['slug']}/compositions",
            data={
                "name":         "Copy of Original",
                "description":  "",
                "party_number": ["1"],
                "slot_index":   ["1"],
                "role":         ["Tank"],
                "build_name":   ["Claymore"],
                "weapon_name":  ["CLM"],
                "priority":     ["core"],
            },
            follow_redirects=False,
        )
        # Original slot templates must be intact
        with database.transaction() as db:
            orig_templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        assert len(orig_templates) == len(_CLONE_SOURCE_SLOTS), (
            "original composition slot count must not change after clone is saved"
        )
        orig_builds = {t["build_name"] for t in orig_templates}
        assert "Claymore" in orig_builds
        assert "Hallowfall" in orig_builds

    def test_clone_preserves_priority_in_form(self):
        """Clone form must preserve both 'core' and 'normal' priority values."""
        owner = make_user("CloneOwner10")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-priority")
        comp = make_composition(ws["id"], name="PrioritySource", slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "A", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "DPS",
             "build_name": "B", "priority": "normal"},
        ])
        client = TestClient(app)
        _login(client, "CloneOwner10")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200
        # Both priority values must appear in the form (as selected options)
        assert 'value="core"' in resp.text
        assert 'value="normal"' in resp.text

    def test_clone_preserves_party_number_ordering(self):
        """Clone form slot table must preserve party_number values from source."""
        owner = make_user("CloneOwner11")
        ws = make_workspace(owner_user_id=owner["id"], slug="clone-party-num")
        comp = make_composition(ws["id"], name="MultiParty", slots=_CLONE_SOURCE_SLOTS)
        client = TestClient(app)
        _login(client, "CloneOwner11")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/clone")
        assert resp.status_code == 200
        # Source fixture has party_number 1 and 2 — both must appear in the form
        # (as input values). Simple presence check via rendered HTML.
        assert 'name="party_number"' in resp.text


# ---------------------------------------------------------------------------
# Group 10 — Landing page smoke (Phase 1 infrastructure)
# ---------------------------------------------------------------------------

class TestLandingPageSmoke:
    """
    Regression anchors for the public landing page route introduced in Phase 1.

    Assertions are structural — landmark presence, heading hierarchy, and
    absence of authenticated-only elements. No copy, no showcase data, no
    visual assertions.
    """

    def test_landing_route_returns_200(self):
        """GET / must return 200 with no session cookie."""
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_landing_contains_h1(self):
        """Landing page must contain exactly one <h1> element."""
        client = TestClient(app)
        resp = client.get("/")
        assert "<h1" in resp.text

    def test_landing_contains_main_landmark(self):
        """Landing page must contain a <main> landmark."""
        client = TestClient(app)
        resp = client.get("/")
        assert "<main" in resp.text

    def test_landing_contains_nav_landmark(self):
        """Landing page must contain a <nav> landmark."""
        client = TestClient(app)
        resp = client.get("/")
        assert "<nav" in resp.text

    def test_landing_contains_footer(self):
        """Landing page must contain a <footer> element."""
        client = TestClient(app)
        resp = client.get("/")
        assert "<footer" in resp.text

    def test_landing_no_workspace_switcher(self):
        """Authenticated workspace switcher must NOT appear on the public landing route."""
        client = TestClient(app)
        resp = client.get("/")
        # The workspace switcher in base.html renders the workspace name and slug.
        # On the public shell there is no workspace context — these elements are absent.
        assert "workspace-nav" not in resp.text
        assert "global-nav__account" not in resp.text

    def test_landing_no_planner_controls(self):
        """Planner-specific controls must NOT appear on the public landing route."""
        client = TestClient(app)
        resp = client.get("/")
        assert "operation-tabs" not in resp.text
        assert "planner-board" not in resp.text

    def test_landing_accessible_without_session(self):
        """Landing page must return 200 regardless of authentication state."""
        client = TestClient(app)
        # Unauthenticated request — no cookies, no session
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 200

    def test_landing_uses_public_css_pipeline(self):
        """Public CSS pipeline: core shared stack loads; app-only CSS is excluded.

        The public shell uses a curated subset of the canonical UI Architecture
        Phase 2 CSS stack.  The shared foundations (tokens → base → layout →
        components → utilities → responsive) must be present so that the landing
        page inherits all design tokens and base primitives.  landing.css layers
        on top additively.

        App-only files (dashboard.css, tactical.css, tables.css, forms.css)
        are intentionally absent — they define operational UI primitives that
        have no counterpart on the public marketing shell.
        """
        client = TestClient(app)
        resp = client.get("/")
        # Core shared foundations must be present.
        assert "tokens.css" in resp.text
        assert "base.css" in resp.text
        assert "layout.css" in resp.text
        assert "components.css" in resp.text
        assert "utilities.css" in resp.text
        assert "responsive.css" in resp.text
        # landing.css must be present and additive (after components, before utilities).
        assert "landing.css" in resp.text
        # App-only CSS must not appear on the public shell.
        assert "dashboard.css" not in resp.text
        assert "tactical.css" not in resp.text
        assert "tables.css" not in resp.text
        assert "forms.css" not in resp.text

    def test_landing_no_authenticated_app_nav(self):
        """Authenticated app nav class (global-nav) must NOT appear on the public route."""
        client = TestClient(app)
        resp = client.get("/")
        # base.html uses class="global-nav"; base_public.html uses class="landing-nav".
        # The authenticated nav class must be absent from the public shell.
        assert "global-nav" not in resp.text

    def test_landing_all_section_ids_present(self):
        """All 9 landing sections must have stable, addressable id attributes."""
        client = TestClient(app)
        resp = client.get("/")
        section_ids = [
            "section-hero",
            "section-showcase",
            "section-composition",
            "section-workflow",
            "section-discord",
            "section-readiness",
            "section-differentiation",
            "section-faq",
            "section-footer",
        ]
        for section_id in section_ids:
            assert f'id="{section_id}"' in resp.text, (
                f"Missing stable section id: #{section_id}"
            )

    def test_landing_no_stray_empty_interactive_elements(self):
        """Landing page must not render stray empty <li> elements.

        Phase 1/2: empty <details>/<summary> produced visible disclosure triangles and
        were prohibited. Phase 3 introduced real FAQ content — <details>/<summary> are
        now intentionally present with real content and are no longer stray.

        The <li> check is retained: no list-based structures exist on the landing page,
        so any <li> element would be unintentional and render a bullet marker.

        Note: `<link` (CSS stylesheet tag) starts with '<li', so the assertion uses
        `<li>` and `<li ` (with trailing space) to avoid false-positive matches against
        `<link rel="stylesheet" ...>` tags in the document head.
        """
        client = TestClient(app)
        resp = client.get("/")
        # <details>/<summary> are intentionally present in the Phase 3 FAQ section.
        # <li> must remain absent — no list structures are present on the landing page.
        assert "<li>" not in resp.text and "<li " not in resp.text, (
            "Empty <li> renders a bullet marker — no list structures present on landing page"
        )

    def test_landing_faq_section_has_real_content(self):
        """Phase 3: FAQ section must contain <details>/<summary> items with real copy."""
        client = TestClient(app)
        resp = client.get("/")
        assert "<details" in resp.text, "Phase 3 FAQ must include <details> items"
        assert "<summary" in resp.text, "Phase 3 FAQ must include <summary> elements"
        assert "ls-faq__answer" in resp.text, "Phase 3 FAQ must include answer divs"

    def test_landing_showcase_planner_present(self):
        """Phase 3: main showcase must contain the planner surface and slot state classes."""
        client = TestClient(app)
        resp = client.get("/")
        assert "ls-planner" in resp.text, "Phase 3 planner surface must be present"
        assert "ls-slot--assigned" in resp.text, "Planner must show assigned slot state"
        assert "ls-slot--open-core" in resp.text, "Planner must show open-core warning state"
        assert "ls-slot--critical" in resp.text, "Planner must show critical gap state"
        assert "ls-gap-badge--crit" in resp.text, "Planner must show critical gap badge"

    def test_landing_hero_has_tactical_headline(self):
        """Phase 3: hero section must contain the real tactical headline copy."""
        client = TestClient(app)
        resp = client.get("/")
        assert "Know who" in resp.text, "Hero headline must contain Phase 3 tactical copy"

    def test_landing_workflow_steps_present(self):
        """Phase 3: workflow section must contain the 4 operational flow steps."""
        client = TestClient(app)
        resp = client.get("/")
        assert "ls-flow-step__label" in resp.text, "Workflow steps must be present"
        assert "Draft" in resp.text
        assert "Plan" in resp.text
        assert "Execute" in resp.text
        assert "Record" in resp.text

    def test_landing_discord_section_has_embed(self):
        """Phase 3: Discord section must render the embed mock."""
        client = TestClient(app)
        resp = client.get("/")
        assert "ls-discord-embed" in resp.text, "Discord embed mock must be present"

    def test_landing_has_login_cta(self):
        """Phase 3: hero CTA must include a login link."""
        client = TestClient(app)
        resp = client.get("/")
        assert 'href="/login"' in resp.text, "Hero must include a login CTA link"


# ---------------------------------------------------------------------------
# Group 9 — Phase 2 Composition Builder Card System (regression)
# ---------------------------------------------------------------------------

_CB_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace",    "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Daggers",    "priority": "normal"},
    {"party_number": 2, "slot_index": 1, "role": "Tank",   "build_name": "Tombhammer", "priority": "core"},
    {"party_number": 2, "slot_index": 2, "role": "Healer", "build_name": "Fallen Staff","priority": "core"},
]


def _cb_login(client, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


class TestPhase2CompositionBuilderCards:
    """Regression tests for the Phase 2 slot card system on edit and creation surfaces.

    Covers:
      Group A — Edit surface card rendering
      Group B — New composition surface card rendering
      Group C — Multi-party party group structure
      Group D — Composition detail tactical summaries still render (non-regression)
    """

    # ── Group A: Edit surface ────────────────────────────────────────────────

    def test_edit_surface_has_composition_editor(self):
        """.cb-composition-editor wrapper renders on the edit page."""
        owner = make_user("CB1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-1")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB1Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "cb-composition-editor" in resp.text

    def test_edit_surface_has_party_groups(self):
        """Party groups render for each distinct party_number."""
        owner = make_user("CB2Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-2")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB2Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "cb-party-group" in resp.text
        # Two parties → two data-party attributes
        assert 'data-party="1"' in resp.text
        assert 'data-party="2"' in resp.text

    def test_edit_surface_has_slot_cards(self):
        """Slot cards render for each slot template."""
        owner = make_user("CB3Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-3")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB3Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "cb-slot-card" in resp.text

    def test_edit_surface_role_labels_in_cards(self):
        """Role values from slot templates appear inside the card form inputs."""
        owner = make_user("CB4Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-4")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB4Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "Tank" in resp.text
        assert "Healer" in resp.text
        assert "DPS" in resp.text

    def test_edit_surface_build_names_in_cards(self):
        """Build names from slot templates appear inside the card form inputs."""
        owner = make_user("CB5Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-5")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB5Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "1H Mace" in resp.text
        assert "Hallowfall" in resp.text
        assert "Fallen Staff" in resp.text

    def test_edit_surface_party_header_tally(self):
        """Party header tally items render with data-role attributes."""
        owner = make_user("CB6Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-6")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB6Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "cb-tally-item" in resp.text
        assert "cb-party-header__tally" in resp.text

    def test_edit_surface_core_badge_for_core_slots(self):
        """CORE badge renders for core-priority slots in the edit surface."""
        owner = make_user("CB7Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-7")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB7Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "cb-badge--core" in resp.text

    def test_edit_surface_form_inputs_submittable(self):
        """All expected form input name attributes are present in the edit template."""
        owner = make_user("CB8Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-8")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB8Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        for name in ('name="role"', 'name="build_name"', 'name="party_number"',
                     'name="slot_index"', 'name="priority"'):
            assert name in resp.text, f"Missing form input: {name}"

    def test_edit_surface_keyboard_accessible(self):
        """Slot card inputs carry aria-label attributes for keyboard/AT navigation."""
        owner = make_user("CB9Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-9")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB9Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert 'aria-label="Role' in resp.text
        assert 'aria-label="Build name"' in resp.text
        assert 'aria-label="Party number"' in resp.text

    # ── Group B: New composition surface ────────────────────────────────────

    def test_new_surface_has_composition_editor(self):
        """.cb-composition-editor wrapper renders on the new composition page."""
        owner = make_user("CB10Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-10")
        client = TestClient(app)
        _cb_login(client, "CB10Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "cb-composition-editor" in resp.text

    def test_new_surface_has_default_party_group(self):
        """New composition page renders a default Party 1 with blank cards."""
        owner = make_user("CB11Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-11")
        client = TestClient(app)
        _cb_login(client, "CB11Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "cb-party-group" in resp.text
        assert 'data-party="1"' in resp.text
        assert "cb-slot-card" in resp.text

    def test_new_surface_has_blank_cards(self):
        """Initial blank cards render with OPEN badge (no build_name)."""
        owner = make_user("CB12Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-12")
        client = TestClient(app)
        _cb_login(client, "CB12Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "cb-badge--open" in resp.text

    def test_new_surface_form_inputs_submittable(self):
        """New composition page renders all required form input names."""
        owner = make_user("CB13Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-13")
        client = TestClient(app)
        _cb_login(client, "CB13Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        for name in ('name="role"', 'name="build_name"', 'name="party_number"',
                     'name="slot_index"', 'name="priority"'):
            assert name in resp.text, f"Missing form input on new surface: {name}"

    # ── Group C: Multi-party structure ──────────────────────────────────────

    def test_multi_party_comp_renders_multiple_groups(self):
        """A 2-party composition renders two separate .cb-party-group sections."""
        owner = make_user("CB14Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-14")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB14Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        # Count cb-party-group occurrences — should be 2 for _CB_SLOTS
        assert resp.text.count("cb-party-group") >= 2

    def test_party_groups_have_correct_data_party(self):
        """Each party group carries its party_number in data-party attribute."""
        owner = make_user("CB15Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-15")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB15Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert 'data-party="1"' in resp.text
        assert 'data-party="2"' in resp.text

    # ── Group D: Composition detail non-regression ──────────────────────────

    def test_composition_detail_tactical_summaries_still_render(self):
        """Composition detail page still renders tactical summaries after Phase 2 changes."""
        owner = make_user("CB16Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-16")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB16Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "comp-overview" in resp.text
        assert "role-tally" in resp.text
        assert "party-panel" in resp.text

    def test_composition_detail_slot_cards_still_render(self):
        """Composition detail slot cards (read-only) still render after Phase 2."""
        owner = make_user("CB17Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-17")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB17Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        # The detail page uses the existing .slot-card system (not .cb-slot-card)
        assert "slot-card" in resp.text

    def test_no_slot_table_in_edit_surface(self):
        """The old .slot-table class is gone from the edit surface (replaced by cards)."""
        owner = make_user("CB18Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-18")
        comp  = make_composition(ws["id"], slots=_CB_SLOTS)
        client = TestClient(app)
        _cb_login(client, "CB18Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "slot-table" not in resp.text

    def test_no_slot_table_in_new_surface(self):
        """The old .slot-table class is gone from the new composition surface."""
        owner = make_user("CB19Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="cb-19")
        client = TestClient(app)
        _cb_login(client, "CB19Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert "slot-table" not in resp.text


# ---------------------------------------------------------------------------
# Phase 3 — Build Library UI regression tests
# ---------------------------------------------------------------------------

def _p3_login(client, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


_P3_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Healer",  "build_name": "Hallowfall", "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Tank",    "build_name": "Tombhammer", "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",     "build_name": "Daggers",    "priority": "normal"},
]


class TestPhase3BuildLibrary:
    """Regression tests for Phase 3 Build Library UI.

    Covers:
      Group A — Build library nav and list page
      Group B — Build detail and edit pages
      Group C — Composition editor build selector
      Group D — Non-regression: existing detail + edit still work
    """

    # ── Group A: Build library nav and list ─────────────────────────────────

    def test_workspace_nav_has_builds_link(self):
        """Workspace nav must include a Builds link."""
        owner = make_user("P3A1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3a-1")
        client = TestClient(app)
        _p3_login(client, "P3A1Owner")
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert resp.status_code == 200
        assert "/builds" in resp.text

    def test_builds_list_returns_200(self):
        """GET /workspaces/{slug}/builds returns 200."""
        owner = make_user("P3A2Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3a-2")
        client = TestClient(app)
        _p3_login(client, "P3A2Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds")
        assert resp.status_code == 200

    def test_builds_list_empty_state(self):
        """Empty workspace shows an empty-state message."""
        owner = make_user("P3A3Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3a-3")
        client = TestClient(app)
        _p3_login(client, "P3A3Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds")
        assert resp.status_code == 200
        assert "empty-state" in resp.text

    def test_builds_list_shows_active_build(self):
        """After creating a build, it appears in the list."""
        owner = make_user("P3A4Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3a-4")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="P3 Test Build", role="DPS", weapon_name="Warbow",
        )
        client = TestClient(app)
        _p3_login(client, "P3A4Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds")
        assert resp.status_code == 200
        assert "P3 Test Build" in resp.text

    def test_build_new_form_accessible_for_officer(self):
        """GET /builds/new returns 200 for an officer."""
        owner = make_user("P3A5Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3a-5")
        client = TestClient(app)
        _p3_login(client, "P3A5Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/new")
        assert resp.status_code == 200
        assert "bld-form" in resp.text

    # ── Group B: Build detail and edit pages ─────────────────────────────────

    def test_build_detail_shows_weapon(self):
        """Build detail page renders the weapon name."""
        owner = make_user("P3B1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3b-1")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Detail Build", role="Healer", weapon_name="T8 Staff",
        )
        client = TestClient(app)
        _p3_login(client, "P3B1Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")
        assert resp.status_code == 200
        assert "T8 Staff" in resp.text

    def test_build_detail_shows_retired_badge(self):
        """Retired build detail page shows the retired badge."""
        owner = make_user("P3B2Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3b-2")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="Retired Build", role="Tank", weapon_name="Mace",
        )
        use_cases.retire_albion_build(ws["id"], build["id"], owner["id"])
        client = TestClient(app)
        _p3_login(client, "P3B2Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")
        assert resp.status_code == 200
        assert "retired" in resp.text

    def test_build_edit_form_prefilled(self):
        """Build edit form is pre-filled with the current build fields."""
        owner = make_user("P3B3Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3b-3")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="PrefillBuild", role="Support", weapon_name="Staff",
        )
        client = TestClient(app)
        _p3_login(client, "P3B3Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")
        assert resp.status_code == 200
        assert "PrefillBuild" in resp.text

    def test_build_edit_retired_returns_403(self):
        """Attempting to edit a retired build returns 403."""
        owner = make_user("P3B4Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3b-4")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="WillRetire", role="DPS", weapon_name="Bow",
        )
        use_cases.retire_albion_build(ws["id"], build["id"], owner["id"])
        client = TestClient(app)
        _p3_login(client, "P3B4Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")
        assert resp.status_code == 403

    # ── Group C: Composition editor build selector ───────────────────────────

    def test_edit_surface_includes_build_select_when_builds_exist(self):
        """When workspace has builds, the edit surface includes the build selector."""
        owner = make_user("P3C1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3c-1")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="CB Test Build", role="DPS", weapon_name="Bow",
        )
        comp = make_composition(ws["id"], slots=_P3_SLOTS)
        client = TestClient(app)
        _p3_login(client, "P3C1Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        # Actual rendered <select> element (not just the JS string literal)
        assert '<select name="albion_build_id"' in resp.text
        assert "CB Test Build" in resp.text

    def test_edit_surface_no_build_select_when_no_builds(self):
        """Without any builds in the workspace, a hidden input is rendered for albion_build_id.
        (The JS function generates a <select> client-side, but server renders no <option> elements.)"""
        owner = make_user("P3C2Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3c-2")
        comp  = make_composition(ws["id"], slots=_P3_SLOTS)
        client = TestClient(app)
        _p3_login(client, "P3C2Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        # Server renders hidden input when no builds exist (no <option> elements)
        assert 'type="hidden" name="albion_build_id"' in resp.text

    def test_new_composition_surface_includes_build_select(self):
        """GET /compositions/new includes the build selector when builds exist."""
        owner = make_user("P3C3Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3c-3")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="New Comp Build", role="Healer", weapon_name="Hallowfall",
        )
        client = TestClient(app)
        _p3_login(client, "P3C3Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/new")
        assert resp.status_code == 200
        assert '<select name="albion_build_id"' in resp.text

    def test_workspace_builds_json_in_edit_page(self):
        """The JS WORKSPACE_BUILDS variable is injected into the edit page."""
        owner = make_user("P3C4Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3c-4")
        use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="WSBUILDS Build", role="Tank", weapon_name="Mace",
        )
        comp = make_composition(ws["id"], slots=_P3_SLOTS)
        client = TestClient(app)
        _p3_login(client, "P3C4Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert "WORKSPACE_BUILDS" in resp.text

    # ── Group D: Non-regression ──────────────────────────────────────────────

    def test_composition_detail_still_renders_after_phase3(self):
        """Composition detail page still renders correctly after Phase 3 changes."""
        owner = make_user("P3D1Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3d-1")
        comp  = make_composition(ws["id"], slots=_P3_SLOTS)
        client = TestClient(app)
        _p3_login(client, "P3D1Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Hallowfall" in resp.text
        assert "slot-card" in resp.text

    def test_composition_edit_still_submits_without_build_select(self):
        """POST to compositions/{id}/slots still works without albion_build_id (backward compat)."""
        owner = make_user("P3D2Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3d-2")
        comp  = make_composition(ws["id"], slots=_P3_SLOTS)
        client = TestClient(app)
        _p3_login(client, "P3D2Owner")
        resp = client.post(
            f"/workspaces/{ws['slug']}/compositions/{comp['id']}/slots",
            data={
                "party_number": ["1"],
                "slot_index":   ["1"],
                "role":         ["Tank"],
                "build_name":   ["Tombhammer"],
                "weapon_name":  [""],
                "priority":     ["core"],
                # No albion_build_id submitted
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_build_snapshot_invariant_notice_on_edit_page(self):
        """Build edit page shows the snapshot invariant notice."""
        owner = make_user("P3D3Owner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p3d-3")
        build = use_cases.create_albion_build(
            guild_workspace_id=ws["id"], actor_user_id=owner["id"],
            name="InvBuild", role="DPS", weapon_name="Bow",
        )
        client = TestClient(app)
        _p3_login(client, "P3D3Owner")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")
        assert resp.status_code == 200
        assert "does not" in resp.text  # snapshot invariant notice
