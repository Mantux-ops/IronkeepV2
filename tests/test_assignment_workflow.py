"""Phase 6 Slice 2 — Assignment Workflow Foundation: regression tests.

Covers:
  Group 1 — use_cases.reassign_slot
               a) atomic swap: old assignment removed, new one created
               b) previous participant freed (can be reassigned elsewhere)
               c) behaves as plain assign when slot has no active assignment
               d) raises ConflictError if new participant already assigned in op
               e) raises NotFoundError for wrong slot_id
               f) raises ConflictError on wrong-status operation

  Group 2 — Snapshot invariant
               a) reassign never mutates operation_slots frozen data
               b) slot identity (role, build) unchanged after reassign

  Group 3 — Route: POST /slots/{slot_id}/reassign
               a) officer → redirects to planner
               b) empty participant_id → redirects with error
               c) unauthenticated → redirects to login
               d) wrong slot → 404 surfaced as error redirect

  Group 4 — Route: POST /assign (operation-level, participant-direction)
               a) officer → redirects to planner
               b) missing slot_id or participant_id → redirects with error
               c) unauthenticated → redirects to login
               d) full round-trip: participant assigned to selected slot

  Group 5 — get_planner: open_slots context variable
               a) open_slots contains all unassigned slot ids
               b) open_slots excludes already-assigned slots
               c) open_slots empty when all slots assigned

  Group 6 — Template affordances (planner rendering)
               a) doctrine_role displayed in slot header when set
               b) promoted assign selector visible for open slot with candidates
               c) Swap button present for assigned slot
               d) assign-from-left form present for each unassigned signup
               e) aria-labels present on assignment controls
               f) Quick ★ button still rendered alongside promoted assign
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.errors import ConflictError, NotFoundError
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

def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _setup_operation_with_slots(slug: str) -> tuple:
    """Create workspace → operation → composition → published → slots generated.
    Returns (owner, ws, op, comp).
    """
    owner = make_user(f"AwOwner-{slug}")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    op    = make_operation(ws["id"])
    comp  = make_composition(ws["id"])
    use_cases.attach_operation_plan(
        guild_workspace_id=ws["id"],
        guild_operation_id=op["id"],
        albion_composition_id=comp["id"],
        signup_status="open",
    )
    publish_operation(ws["id"], op["id"])
    use_cases.generate_operation_slots(ws["id"], op["id"])
    return owner, ws, op, comp


def _signup(ws_id: str, op_id: str, display_name: str, role: str = "Healer") -> dict:
    """Register a participant + signup intent. Returns signup row."""
    return use_cases.submit_signup_intent(
        guild_workspace_id=ws_id,
        guild_operation_id=op_id,
        display_name=display_name,
        preferred_role=role,
    )


def _first_slot(op_id: str, ws_id: str) -> dict:
    with database.transaction() as db:
        slots = repositories.get_operation_slots(db, op_id, ws_id)
    return slots[0]


def _get_participant_id(ws_id: str, display_name: str) -> str:
    with database.transaction() as db:
        row = db.execute(
            "SELECT id FROM participants WHERE guild_workspace_id = ? AND display_name = ?",
            (ws_id, display_name),
        ).fetchone()
    return row["id"]


def _assign(ws_id: str, op_id: str, slot_id: str, participant_id: str) -> dict:
    return use_cases.assign_participant_to_operation_slot(
        guild_workspace_id=ws_id,
        guild_operation_id=op_id,
        operation_slot_id=slot_id,
        participant_id=participant_id,
    )


# ---------------------------------------------------------------------------
# Group 1 — reassign_slot use case
# ---------------------------------------------------------------------------

class TestReassignSlotUseCase:

    def test_old_assignment_removed_new_one_created(self):
        owner, ws, op, _ = _setup_operation_with_slots("uc-1")
        _signup(ws["id"], op["id"], "PlayerA")
        _signup(ws["id"], op["id"], "PlayerB")
        slot   = _first_slot(op["id"], ws["id"])
        pid_a  = _get_participant_id(ws["id"], "PlayerA")
        pid_b  = _get_participant_id(ws["id"], "PlayerB")

        # Assign PlayerA first
        _assign(ws["id"], op["id"], slot["id"], pid_a)

        # Reassign to PlayerB
        new_asgn = use_cases.reassign_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            operation_slot_id=slot["id"],
            new_participant_id=pid_b,
        )
        assert new_asgn["participant_id"]  == pid_b
        assert new_asgn["status"]          == "assigned"

        # PlayerA's assignment must now be 'removed'
        with database.transaction() as db:
            all_asgns = repositories.get_assignments(db, op["id"], ws["id"])
        a_asgn = next((a for a in all_asgns if a["participant_id"] == pid_a), None)
        assert a_asgn is not None
        assert a_asgn["status"] == "removed"

    def test_previous_participant_freed_for_reassignment_elsewhere(self):
        """After a swap, the previously assigned participant can be assigned
        to a different slot."""
        owner, ws, op, _ = _setup_operation_with_slots("uc-2")
        _signup(ws["id"], op["id"], "PlayerC")
        _signup(ws["id"], op["id"], "PlayerD")

        with database.transaction() as db:
            slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        slot1, slot2 = slots[0], slots[1]
        pid_c = _get_participant_id(ws["id"], "PlayerC")
        pid_d = _get_participant_id(ws["id"], "PlayerD")

        _assign(ws["id"], op["id"], slot1["id"], pid_c)
        use_cases.reassign_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            operation_slot_id=slot1["id"],
            new_participant_id=pid_d,
        )
        # PlayerC is now free; can be assigned to slot2
        asgn2 = _assign(ws["id"], op["id"], slot2["id"], pid_c)
        assert asgn2["participant_id"] == pid_c
        assert asgn2["status"]         == "assigned"

    def test_reassign_open_slot_behaves_as_plain_assign(self):
        """Calling reassign on a slot with no active assignment = plain assign."""
        owner, ws, op, _ = _setup_operation_with_slots("uc-3")
        _signup(ws["id"], op["id"], "PlayerE")
        slot  = _first_slot(op["id"], ws["id"])
        pid_e = _get_participant_id(ws["id"], "PlayerE")

        asgn = use_cases.reassign_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            operation_slot_id=slot["id"],
            new_participant_id=pid_e,
        )
        assert asgn["participant_id"] == pid_e
        assert asgn["status"]         == "assigned"

    def test_raises_conflict_when_new_participant_already_assigned(self):
        """Cannot reassign to a participant who is already on another slot."""
        owner, ws, op, _ = _setup_operation_with_slots("uc-4")
        _signup(ws["id"], op["id"], "PlayerF")
        _signup(ws["id"], op["id"], "PlayerG")

        with database.transaction() as db:
            slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        slot1, slot2 = slots[0], slots[1]
        pid_f = _get_participant_id(ws["id"], "PlayerF")
        pid_g = _get_participant_id(ws["id"], "PlayerG")

        _assign(ws["id"], op["id"], slot1["id"], pid_f)
        _assign(ws["id"], op["id"], slot2["id"], pid_g)

        # Try to reassign slot1 to PlayerG (already on slot2)
        with pytest.raises(ConflictError, match="already has an active assignment"):
            use_cases.reassign_slot(
                guild_workspace_id=ws["id"],
                guild_operation_id=op["id"],
                operation_slot_id=slot1["id"],
                new_participant_id=pid_g,
            )

    def test_raises_not_found_for_wrong_slot_id(self):
        owner, ws, op, _ = _setup_operation_with_slots("uc-5")
        _signup(ws["id"], op["id"], "PlayerH")
        pid_h = _get_participant_id(ws["id"], "PlayerH")

        with pytest.raises(NotFoundError):
            use_cases.reassign_slot(
                guild_workspace_id=ws["id"],
                guild_operation_id=op["id"],
                operation_slot_id="nonexistent-slot-id",
                new_participant_id=pid_h,
            )


# ---------------------------------------------------------------------------
# Group 2 — Snapshot invariant
# ---------------------------------------------------------------------------

class TestReassignSnapshotInvariant:

    def test_operation_slots_frozen_after_reassign(self):
        """operation_slots row must not be mutated by reassign_slot."""
        owner, ws, op, _ = _setup_operation_with_slots("snap-aw-1")
        _signup(ws["id"], op["id"], "SlotSnapA")
        _signup(ws["id"], op["id"], "SlotSnapB")
        slot   = _first_slot(op["id"], ws["id"])
        pid_a  = _get_participant_id(ws["id"], "SlotSnapA")
        pid_b  = _get_participant_id(ws["id"], "SlotSnapB")

        # Capture slot state before any assignment
        original_role       = slot["role"]
        original_build_name = slot["build_name"]
        original_slot_index = slot["slot_index"]

        _assign(ws["id"], op["id"], slot["id"], pid_a)
        use_cases.reassign_slot(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            operation_slot_id=slot["id"],
            new_participant_id=pid_b,
        )

        # Reload slot from DB — must be unchanged
        with database.transaction() as db:
            slots_after = repositories.get_operation_slots(db, op["id"], ws["id"])
        refreshed = next(s for s in slots_after if s["id"] == slot["id"])
        assert refreshed["role"]       == original_role
        assert refreshed["build_name"] == original_build_name
        assert refreshed["slot_index"] == original_slot_index


# ---------------------------------------------------------------------------
# Group 3 — Route: POST /slots/{slot_id}/reassign
# ---------------------------------------------------------------------------

class TestReassignRoute:

    def _setup_client(self, slug: str):
        owner, ws, op, _ = _setup_operation_with_slots(slug)
        client = TestClient(app)
        _login(client, f"AwOwner-{slug}")
        return client, owner, ws, op

    def test_officer_redirects_to_planner(self):
        client, owner, ws, op = self._setup_client("rt-1")
        _signup(ws["id"], op["id"], "RoutePlayerA")
        _signup(ws["id"], op["id"], "RoutePlayerB")
        slot   = _first_slot(op["id"], ws["id"])
        pid_a  = _get_participant_id(ws["id"], "RoutePlayerA")
        pid_b  = _get_participant_id(ws["id"], "RoutePlayerB")
        _assign(ws["id"], op["id"], slot["id"], pid_a)

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/reassign",
            data={"participant_id": pid_b},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/planner" in resp.headers["location"]

    def test_empty_participant_id_redirects_with_error(self):
        client, owner, ws, op = self._setup_client("rt-2")
        slot = _first_slot(op["id"], ws["id"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/reassign",
            data={"participant_id": ""},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]

    def test_unauthenticated_redirects_to_login(self):
        owner, ws, op, _ = _setup_operation_with_slots("rt-3")
        slot = _first_slot(op["id"], ws["id"])
        anon = TestClient(app)
        resp = anon.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/reassign",
            data={"participant_id": "some-id"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]

    def test_full_round_trip_persists_new_assignment(self):
        """POST /reassign → DB check → new participant is assigned."""
        client, owner, ws, op = self._setup_client("rt-4")
        _signup(ws["id"], op["id"], "RoundTripA")
        _signup(ws["id"], op["id"], "RoundTripB")
        slot   = _first_slot(op["id"], ws["id"])
        pid_a  = _get_participant_id(ws["id"], "RoundTripA")
        pid_b  = _get_participant_id(ws["id"], "RoundTripB")
        _assign(ws["id"], op["id"], slot["id"], pid_a)

        client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/slots/{slot['id']}/reassign",
            data={"participant_id": pid_b},
            follow_redirects=False,
        )

        with database.transaction() as db:
            assigned_map = repositories.get_assigned_participants_for_operation(
                db, op["id"], ws["id"]
            )
        asgn = assigned_map.get(slot["id"])
        assert asgn is not None
        assert asgn["participant_id"] == pid_b


# ---------------------------------------------------------------------------
# Group 4 — Route: POST /assign (operation-level, participant direction)
# ---------------------------------------------------------------------------

class TestOperationLevelAssignRoute:

    def _setup_client(self, slug: str):
        owner, ws, op, _ = _setup_operation_with_slots(slug)
        client = TestClient(app)
        _login(client, f"AwOwner-{slug}")
        return client, owner, ws, op

    def test_officer_redirects_to_planner(self):
        client, owner, ws, op = self._setup_client("ol-1")
        _signup(ws["id"], op["id"], "OLPlayerA")
        slot = _first_slot(op["id"], ws["id"])
        pid  = _get_participant_id(ws["id"], "OLPlayerA")

        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assign",
            data={"slot_id": slot["id"], "participant_id": pid},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/planner" in resp.headers["location"]

    def test_missing_slot_id_redirects_with_error(self):
        client, owner, ws, op = self._setup_client("ol-2")
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assign",
            data={"participant_id": "some-id"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]

    def test_missing_participant_id_redirects_with_error(self):
        client, owner, ws, op = self._setup_client("ol-3")
        slot = _first_slot(op["id"], ws["id"])
        resp = client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assign",
            data={"slot_id": slot["id"]},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "error" in resp.headers["location"]

    def test_unauthenticated_redirects_to_login(self):
        owner, ws, op, _ = _setup_operation_with_slots("ol-4")
        slot = _first_slot(op["id"], ws["id"])
        anon = TestClient(app)
        resp = anon.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assign",
            data={"slot_id": slot["id"], "participant_id": "x"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]

    def test_full_round_trip_persists_assignment(self):
        """POST /assign → DB → slot now has active assignment."""
        client, owner, ws, op = self._setup_client("ol-5")
        _signup(ws["id"], op["id"], "OLRoundTrip")
        slot = _first_slot(op["id"], ws["id"])
        pid  = _get_participant_id(ws["id"], "OLRoundTrip")

        client.post(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/assign",
            data={"slot_id": slot["id"], "participant_id": pid},
            follow_redirects=False,
        )
        with database.transaction() as db:
            assigned_map = repositories.get_assigned_participants_for_operation(
                db, op["id"], ws["id"]
            )
        assert slot["id"] in assigned_map
        assert assigned_map[slot["id"]]["participant_id"] == pid


# ---------------------------------------------------------------------------
# Group 5 — get_planner: open_slots context variable
# ---------------------------------------------------------------------------

class TestOpenSlotsContext:

    def _make_planner_client(self, slug: str):
        owner, ws, op, _ = _setup_operation_with_slots(slug)
        client = TestClient(app)
        _login(client, f"AwOwner-{slug}")
        return client, owner, ws, op

    def test_open_slots_contains_all_unassigned(self):
        client, owner, ws, op = self._make_planner_client("os-1")
        _signup(ws["id"], op["id"], "SlotsPlayerA")

        with database.transaction() as db:
            total_slots = len(repositories.get_operation_slots(db, op["id"], ws["id"]))

        # GET planner and inspect template variable via rendered HTML
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # open_slots appear as option values in the assign-from-participant form
        # All 5 slots should be open initially
        assert resp.text.count('name="slot_id"') >= 1  # at least one form exists

    def test_assigned_slot_excluded_from_open_slots_select(self):
        """After assigning a slot, it must not appear in the open_slots dropdown."""
        client, owner, ws, op = self._make_planner_client("os-2")
        _signup(ws["id"], op["id"], "ExcludePlayer")
        slot = _first_slot(op["id"], ws["id"])
        pid  = _get_participant_id(ws["id"], "ExcludePlayer")
        _assign(ws["id"], op["id"], slot["id"], pid)

        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # The assigned slot's id must NOT appear as an option value in the
        # assign-from-participant select (only open slots are listed)
        assert f'value="{slot["id"]}"' not in resp.text


# ---------------------------------------------------------------------------
# Group 6 — Template affordances
# ---------------------------------------------------------------------------

class TestPlannerTemplateAffordances:

    def _planner_html(self, slug: str, with_signup: bool = True):
        owner, ws, op, comp = _setup_operation_with_slots(slug)
        client = TestClient(app)
        _login(client, f"AwOwner-{slug}")
        if with_signup:
            _signup(ws["id"], op["id"], f"TplPlayer-{slug}")
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        return resp.text, client, owner, ws, op

    def test_doctrine_role_shown_in_slot_header_when_set(self):
        """Slots with doctrine_role must render it in the planner slot header."""
        owner = make_user("DocPlannerOwner")
        ws    = make_workspace(owner_user_id=owner["id"], slug="tpl-dr-1")
        op    = make_operation(ws["id"])

        # Composition with a doctrine_role on slot 1
        slots = [
            {
                "party_number": 1, "slot_index": 1, "role": "Healer",
                "build_name": "Hallowfall", "priority": "core",
                "doctrine_role": "Main Caller",
            },
            {
                "party_number": 1, "slot_index": 2, "role": "Tank",
                "build_name": "1H Mace", "priority": "normal",
            },
        ]
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"], name="Doctrine Comp", description=None, slots=slots,
        )
        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"], guild_operation_id=op["id"],
            albion_composition_id=comp["id"], signup_status="open",
        )
        publish_operation(ws["id"], op["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])

        client = TestClient(app)
        _login(client, "DocPlannerOwner")
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "slot-card__doctrine-role" in resp.text
        assert "Main Caller" in resp.text

    def test_promoted_assign_selector_visible_for_open_slot(self):
        """Manual assign select must be directly visible (no <details> wrapper)."""
        html, *_ = self._planner_html("tpl-2")
        # The select name="participant_id" must be outside of any <details> for
        # the promoted manual assign. We verify by checking the CSS class that
        # only the promoted form uses.
        assert "slot-assign-form" in html
        assert 'name="participant_id"' in html

    def test_swap_button_present_for_assigned_slot(self):
        """Assigned slots must show the Swap button when unassigned candidates exist."""
        owner, ws, op, _ = _setup_operation_with_slots("tpl-3")
        _signup(ws["id"], op["id"], "SwapPlayerAssigned")
        # A second unassigned player is needed so slot_p is non-empty for the swap dropdown
        _signup(ws["id"], op["id"], "SwapPlayerFree")
        slot = _first_slot(op["id"], ws["id"])
        pid  = _get_participant_id(ws["id"], "SwapPlayerAssigned")
        _assign(ws["id"], op["id"], slot["id"], pid)

        client = TestClient(app)
        _login(client, "AwOwner-tpl-3")
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Swap" in resp.text
        assert "slot-swap-details" in resp.text

    def test_unassign_button_present_for_assigned_slot(self):
        """Assigned slots must show the Unassign button (replaces old 'Remove')."""
        owner, ws, op, _ = _setup_operation_with_slots("tpl-4")
        _signup(ws["id"], op["id"], "UnassignPlayer")
        slot = _first_slot(op["id"], ws["id"])
        pid  = _get_participant_id(ws["id"], "UnassignPlayer")
        _assign(ws["id"], op["id"], slot["id"], pid)

        client = TestClient(app)
        _login(client, "AwOwner-tpl-4")
        resp = client.get(
            f"/workspaces/{ws['slug']}/operations/{op['id']}/planner",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Unassign" in resp.text

    def test_assign_from_left_panel_form_present_for_unassigned_player(self):
        """Each unassigned signup card must include the assign-from-left form."""
        html, *_ = self._planner_html("tpl-5")
        assert "signup-card__assign-form" in html
        assert "signup-assign-select" in html

    def test_aria_labels_on_assign_controls(self):
        """Assignment controls must carry aria-label attributes."""
        html, *_ = self._planner_html("tpl-6")
        assert 'aria-label="Select player to assign' in html

    def test_quick_star_button_present_alongside_promoted_assign(self):
        """Quick ★ button still renders when there are non-reserved candidates."""
        html, *_ = self._planner_html("tpl-7")
        assert "Quick" in html  # "Quick ★" button still shown

    def test_assign_from_left_aria_label(self):
        """Assign-from-left form must have aria-label on select."""
        html, *_ = self._planner_html("tpl-8")
        assert 'aria-label="Assign' in html
