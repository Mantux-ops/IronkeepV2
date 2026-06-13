"""
Phase 5 — Tactical Planning UX.

Covers:
  Group 1  — tactical.py: open_slots + open_core_slots in party_summaries
  Group 2  — tactical.py: open_slots + open_core_slots in comp_summary
  Group 3  — tactical.py: core_slots_unfilled integrity warning
  Group 4  — tactical.py: hint wording with new open-slot language
  Group 5  — Composition detail: open slot badge in page header
  Group 6  — Composition detail: per-party open indicator
  Group 7  — Composition detail: core_slots_unfilled in integrity warnings
  Group 8  — Composition edit: tactical summary banner renders
  Group 9  — Composition edit: party health state classes
  Group 10 — Composition edit: open slot count in party header
  Group 11 — Composition edit: highlight-open button present
  Group 12 — Composition edit: collapse button present
  Group 13 — Accessibility: ARIA roles and labels on new elements
  Group 14 — Snapshot invariant: no operational mutation introduced
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories, tactical
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# These slot dicts are used ONLY for direct tactical.build_parties() calls
# (Groups 1–4).  They have intentionally empty build_name strings which the
# use-case validator rejects — so they must NOT be passed to make_composition.
_FULL_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace",    "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Bow",        "priority": "normal"},
    {"party_number": 2, "slot_index": 1, "role": "Tank",   "build_name": "Claymore",   "priority": "core"},
    {"party_number": 2, "slot_index": 2, "role": "Healer", "build_name": "Fallen",     "priority": "core"},
    {"party_number": 2, "slot_index": 3, "role": "DPS",    "build_name": "Dagger",     "priority": "normal"},
]

_OPEN_SLOTS_RAW = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace", "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "",        "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "",        "priority": "normal"},
    {"party_number": 2, "slot_index": 1, "role": "Tank",   "build_name": "",        "priority": "core"},
    {"party_number": 2, "slot_index": 2, "role": "Healer", "build_name": "Fallen",  "priority": "normal"},
    {"party_number": 2, "slot_index": 3, "role": "DPS",    "build_name": "",        "priority": "normal"},
]

# Valid composition slots for make_composition (all have build_names)
_MAKE_FULL_SLOTS = [
    {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "1H Mace",    "priority": "core"},
    {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
    {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Bow",        "priority": "normal"},
    {"party_number": 2, "slot_index": 1, "role": "Tank",   "build_name": "Claymore",   "priority": "core"},
    {"party_number": 2, "slot_index": 2, "role": "Healer", "build_name": "Fallen",     "priority": "core"},
    {"party_number": 2, "slot_index": 3, "role": "DPS",    "build_name": "Dagger",     "priority": "normal"},
]


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name}, follow_redirects=True)


def _build_parties_from_slots(slots):
    return tactical.build_parties(slots)


def _insert_open_slot(
    ws_id: str, comp_id: str,
    party_num: int = 1, slot_idx: int = 99,
    role: str = "DPS", priority: str = "normal",
) -> None:
    """Bypass use-case validation to insert a slot with empty build_name.
    Used to produce 'open' slot state in route/template tests.
    """
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        repositories.insert_composition_slot_templates(db, [{
            "id":                    str(uuid.uuid4()),
            "guild_workspace_id":    ws_id,
            "albion_composition_id": comp_id,
            "party_number":          party_num,
            "slot_index":            slot_idx,
            "role":                  role,
            "build_name":            "",
            "weapon_name":           None,
            "offhand_name":          None,
            "head_name":             None,
            "armor_name":            None,
            "shoes_name":            None,
            "cape_name":             None,
            "food_name":             None,
            "potion_name":           None,
            "albion_build_id":       None,
            "doctrine_role":         None,
            "priority":              priority,
            "created_at":            now,
            "updated_at":            now,
        }])


# ---------------------------------------------------------------------------
# Group 1 — tactical.py: open_slots + open_core_slots in party_summaries
# ---------------------------------------------------------------------------

class TestPartyOpenSlots:

    def test_all_built_party_has_zero_open_slots(self):
        parties = _build_parties_from_slots(_FULL_SLOTS)
        psumm, _ = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        assert psumm[1]["open_slots"] == 0
        assert psumm[2]["open_slots"] == 0

    def test_open_party_reports_correct_count(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, _ = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        # Party 1: slot 2 (Healer) + slot 3 (DPS) have empty build_name → 2 open
        assert psumm[1]["open_slots"] == 2
        # Party 2: slot 1 (Tank) + slot 3 (DPS) have empty build_name → 2 open
        assert psumm[2]["open_slots"] == 2

    def test_open_core_slots_counts_only_core_priority(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, _ = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        # Party 1: slot 2 (Healer, core) is open → open_core = 1
        assert psumm[1]["open_core"] == 1
        # Party 2: slot 1 (Tank, core) is open → open_core = 1
        assert psumm[2]["open_core"] == 1

    def test_normal_priority_open_not_counted_as_core(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, _ = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        # Party 1: DPS slot 3 is open but priority=normal, not counted as open_core
        # Party 1 open_core should be exactly 1 (only the core Healer slot)
        assert psumm[1]["open_core"] == 1


# ---------------------------------------------------------------------------
# Group 2 — tactical.py: open_slots + open_core_slots in comp_summary
# ---------------------------------------------------------------------------

class TestCompOpenSlots:

    def test_fully_built_comp_has_zero_open_slots(self):
        parties = _build_parties_from_slots(_FULL_SLOTS)
        _, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        assert csumm["open_slots"] == 0
        assert csumm["open_core_slots"] == 0

    def test_partial_comp_open_slots_total(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        _, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        # 4 slots are open across both parties
        assert csumm["open_slots"] == 4

    def test_partial_comp_open_core_slots_total(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        _, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        # Party 1: 1 open core (Healer); Party 2: 1 open core (Tank) → total = 2
        assert csumm["open_core_slots"] == 2

    def test_comp_summary_has_open_slots_key(self):
        """comp_summary always exposes open_slots key (may be 0)."""
        parties = _build_parties_from_slots(_FULL_SLOTS)
        _, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        assert "open_slots" in csumm
        assert "open_core_slots" in csumm


# ---------------------------------------------------------------------------
# Group 3 — tactical.py: core_slots_unfilled integrity warning
# ---------------------------------------------------------------------------

class TestCoreSlotUnfilledWarning:

    def test_no_warning_when_all_core_slots_have_builds(self):
        parties = _build_parties_from_slots(_FULL_SLOTS)
        psumm, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        warnings = tactical.derive_composition_integrity(parties, csumm, psumm)
        codes = [w["code"] for w in warnings]
        assert "core_slots_unfilled" not in codes

    def test_warning_emitted_when_core_slot_is_open(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        warnings = tactical.derive_composition_integrity(parties, csumm, psumm)
        codes = [w["code"] for w in warnings]
        assert "core_slots_unfilled" in codes

    def test_core_unfilled_warning_severity_is_warn(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        warnings = tactical.derive_composition_integrity(parties, csumm, psumm)
        w = next(w for w in warnings if w["code"] == "core_slots_unfilled")
        assert w["severity"] == "warn"

    def test_core_unfilled_warning_message_contains_count(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        warnings = tactical.derive_composition_integrity(parties, csumm, psumm)
        w = next(w for w in warnings if w["code"] == "core_slots_unfilled")
        # Should mention 2 core slots
        assert "2" in w["message"]


# ---------------------------------------------------------------------------
# Group 4 — tactical.py: hint wording with open-slot language
# ---------------------------------------------------------------------------

class TestHintWording:

    def test_hint_says_open_slots_when_builds_missing(self):
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        _, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        assert csumm["hint"] is not None
        assert "open" in csumm["hint"].lower()

    def test_hint_ok_when_all_built(self):
        parties = _build_parties_from_slots(_FULL_SLOTS)
        _, csumm = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        assert csumm["hint_state"] == "ok"
        assert csumm["hint"] is not None

    def test_party_gap_badge_uses_open_language(self):
        """Per-party gap badges say 'open' not 'no builds'."""
        parties = _build_parties_from_slots(_OPEN_SLOTS_RAW)
        psumm, _ = tactical.derive_tactical_summaries(parties, {}, track_assignments=False)
        # Party 1 has 2 open → gap badge text should contain 'open'
        gap_texts = [text for _, text in psumm[1]["gaps"]]
        assert any("open" in t.lower() for t in gap_texts)


# ---------------------------------------------------------------------------
# Group 5 — Composition detail: open slot badge in page header
# ---------------------------------------------------------------------------

class TestDetailOpenSlotHeader:

    def setup_method(self):
        self.owner = make_user("P5DetailOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-detail-1")
        self.client = TestClient(app)
        _login(self.client, "P5DetailOwner")

    def test_open_badge_shown_when_slots_are_open(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        # Inject an open (no-build) slot directly to bypass use-case validation
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=99, role="Support")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        assert resp.status_code == 200
        assert "comp-open-badge" in resp.text

    def test_open_badge_absent_when_all_slots_built(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        assert resp.status_code == 200
        assert "comp-open-badge" not in resp.text

    def test_core_unfilled_signal_shown_in_header(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=98, role="Tank", priority="core")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        assert "core unfilled" in resp.text


# ---------------------------------------------------------------------------
# Group 6 — Composition detail: per-party open indicator
# ---------------------------------------------------------------------------

class TestDetailPartyOpenIndicator:

    def setup_method(self):
        self.owner = make_user("P5PartyOpenOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-party-open")
        self.client = TestClient(app)
        _login(self.client, "P5PartyOpenOwner")

    def test_party_open_indicator_present_when_party_has_open_slots(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=99, role="Support")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        assert resp.status_code == 200
        assert "comp-party-open" in resp.text

    def test_party_open_indicator_absent_when_all_slots_built(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        assert "comp-party-open" not in resp.text


# ---------------------------------------------------------------------------
# Group 7 — Composition detail: core_slots_unfilled in integrity warnings
# ---------------------------------------------------------------------------

class TestDetailCoreUnfilledWarning:

    def setup_method(self):
        self.owner = make_user("P5CoreWarnOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-core-warn")
        self.client = TestClient(app)
        _login(self.client, "P5CoreWarnOwner")

    def test_core_unfilled_warning_rendered_on_detail_page(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=98, role="Tank", priority="core")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        assert resp.status_code == 200
        # The core_slots_unfilled integrity warning renders "core slot" text
        assert "core slot" in resp.text.lower()

    def test_no_core_unfilled_warning_when_all_built(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        # "core_slots_unfilled" warning message text should not appear when all built
        assert "core unfilled" not in resp.text


# ---------------------------------------------------------------------------
# Group 8 — Composition edit: tactical summary banner renders
# ---------------------------------------------------------------------------

class TestEditSummaryBanner:

    def setup_method(self):
        self.owner = make_user("P5EditBannerOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-edit-banner")
        self.client = TestClient(app)
        _login(self.client, "P5EditBannerOwner")

    def test_banner_present_when_comp_has_slots(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-comp-summary" in resp.text

    def test_banner_shows_slot_count(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "6 slots" in resp.text

    def test_banner_shows_open_slot_count(self):
        """Banner reports open slots when DB contains slots with empty build_name."""
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=99, role="Support")
        _insert_open_slot(self.ws["id"], comp["id"], party_num=2, slot_idx=99, role="Support")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "2 open" in resp.text

    def test_banner_shows_role_tally(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "cb-comp-tally" in resp.text

    def test_banner_surfaces_critical_integrity_issues(self):
        """Integrity issues appear inline in the edit summary banner."""
        no_healer_slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Axe", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "DPS",  "build_name": "Bow", "priority": "normal"},
        ]
        comp = make_composition(self.ws["id"], slots=no_healer_slots)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "No healer" in resp.text

    def test_banner_has_aria_status_role(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'role="status"' in resp.text


# ---------------------------------------------------------------------------
# Group 9 — Composition edit: party health state classes
# ---------------------------------------------------------------------------

class TestEditPartyHealthState:

    def setup_method(self):
        self.owner = make_user("P5HealthOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-health-1")
        self.client = TestClient(app)
        _login(self.client, "P5HealthOwner")

    def test_party_with_no_healer_gets_critical_class(self):
        no_healer = [
            {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Axe",  "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "DPS",  "build_name": "Bow",  "priority": "normal"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",  "build_name": "Mace", "priority": "normal"},
        ]
        comp = make_composition(self.ws["id"], slots=no_healer)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-party-group--critical" in resp.text

    def test_balanced_party_has_no_health_class(self):
        balanced = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Axe",        "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": "Bow",        "priority": "normal"},
        ]
        comp = make_composition(self.ws["id"], slots=balanced)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "cb-party-group--critical" not in resp.text
        assert "cb-party-group--warn" not in resp.text

    def test_party_with_open_slots_gets_warn_class(self):
        """Party with open slots (but correct roles present) gets warn class via gap badge."""
        # Create a balanced composition, then inject an open slot via DB
        balanced = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Axe",        "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall", "priority": "core"},
        ]
        comp = make_composition(self.ws["id"], slots=balanced)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=99, role="DPS", priority="normal")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "cb-party-group--warn" in resp.text


# ---------------------------------------------------------------------------
# Group 10 — Composition edit: open slot count in party header
# ---------------------------------------------------------------------------

class TestEditPartyHeaderOpen:

    def setup_method(self):
        self.owner = make_user("P5PartyHdrOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-phdr-1")
        self.client = TestClient(app)
        _login(self.client, "P5PartyHdrOwner")

    def test_open_indicator_shown_in_party_header(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=99, role="Support")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-party-header__open" in resp.text

    def test_no_open_indicator_when_party_fully_built(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "cb-party-header__open" not in resp.text


# ---------------------------------------------------------------------------
# Group 11 — Composition edit: highlight-open button present
# ---------------------------------------------------------------------------

class TestEditHighlightOpenButton:

    def setup_method(self):
        self.owner = make_user("P5HlOpenOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-hlopen-1")
        self.client = TestClient(app)
        _login(self.client, "P5HlOpenOwner")

    def test_highlight_open_button_present(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "Highlight open" in resp.text

    def test_highlight_open_button_has_aria_pressed(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'aria-pressed=' in resp.text

    def test_toggle_highlight_open_js_present(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "toggleHighlightOpen" in resp.text


# ---------------------------------------------------------------------------
# Group 12 — Composition edit: collapse button present
# ---------------------------------------------------------------------------

class TestEditCollapseButton:

    def setup_method(self):
        self.owner = make_user("P5CollapseOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-collapse-1")
        self.client = TestClient(app)
        _login(self.client, "P5CollapseOwner")

    def test_collapse_button_present_in_party_header(self):
        comp = make_composition(self.ws["id"], slots=_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert resp.status_code == 200
        assert "cb-party-collapse-btn" in resp.text

    def test_collapse_button_has_aria_expanded(self):
        comp = make_composition(self.ws["id"], slots=_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'aria-expanded="true"' in resp.text

    def test_toggle_party_collapse_js_present(self):
        comp = make_composition(self.ws["id"], slots=_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert "togglePartyCollapse" in resp.text


# ---------------------------------------------------------------------------
# Group 13 — Accessibility
# ---------------------------------------------------------------------------

class TestPhase5Accessibility:

    def setup_method(self):
        self.owner = make_user("P5A11yOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="p5-a11y-1")
        self.client = TestClient(app)
        _login(self.client, "P5A11yOwner")

    def test_edit_summary_banner_has_aria_label(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'aria-label="Composition planning state"' in resp.text

    def test_role_tally_strip_has_aria_label(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'aria-label="Role distribution"' in resp.text

    def test_party_open_indicator_has_aria_label_on_detail(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        _insert_open_slot(self.ws["id"], comp["id"], party_num=1, slot_idx=99, role="Support")
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}"
        )
        # The comp-party-open element renders aria-label with "open slot" text
        assert "open slot" in resp.text

    def test_collapse_btn_has_aria_label(self):
        comp = make_composition(self.ws["id"], slots=_MAKE_FULL_SLOTS)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'aria-label="Collapse Party' in resp.text

    def test_integrity_issues_in_banner_have_alert_role(self):
        no_healer = [
            {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Axe", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "DPS",  "build_name": "Bow", "priority": "normal"},
        ]
        comp = make_composition(self.ws["id"], slots=no_healer)
        resp = self.client.get(
            f"/workspaces/{self.ws['slug']}/compositions/{comp['id']}/edit"
        )
        assert 'role="alert"' in resp.text


# ---------------------------------------------------------------------------
# Group 14 — Snapshot invariant: no operational mutation introduced
# ---------------------------------------------------------------------------

class TestPhase5SnapshotInvariant:

    def test_operation_slots_unaffected_by_tactical_summary_changes(self):
        """Phase 5 is pure UX — verify operation_slots are not mutated."""
        from app import database, repositories

        owner = make_user("P5SnapOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="p5-snap-1")
        comp  = make_composition(ws["id"], slots=_FULL_SLOTS)
        op    = make_operation(ws["id"])

        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        with database.transaction() as db:
            before = repositories.get_operation_slots(db, op["id"], ws["id"])

        # Simulate composition edit (update_composition_slots)
        new_slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "New Axe",   "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "New Mace",  "priority": "core"},
        ]
        use_cases.update_composition_slots(ws["id"], comp["id"], owner["id"], new_slots)

        with database.transaction() as db:
            after = repositories.get_operation_slots(db, op["id"], ws["id"])

        # Operation slots must be identical before and after
        assert len(before) == len(after)
        for b, a in zip(before, after):
            assert b["build_name"] == a["build_name"]
            assert b["role"]       == a["role"]
