"""
Slice 5 — Zero-slot composition tests.

A "named shell" composition has a valid name but zero slot templates.
Slots may be added later via the Edit Slots page.

Covers:
  Group 1 — Domain validation: validate_slot_templates allows empty list
  Group 2 — Use case: create_albion_composition with zero slots
  Group 3 — Edit semantics: update_composition_slots still rejects empty list
  Group 4 — Routes: POST /compositions succeeds with no valid slot cards
  Group 5 — Templates/UI: zero-slot compositions rendered correctly
  Group 6 — Integration invariants: attach and generate_operation_slots
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import albion_compositions
from app.errors import ValidationError
from app.main import app

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _setup(slug: str) -> tuple[TestClient, dict, dict]:
    """Returns (client, owner, ws)."""
    owner  = make_user(f"owner-{slug}")
    ws     = make_workspace(owner_user_id=owner["id"], slug=slug)
    client = TestClient(app)
    _login(client, f"owner-{slug}")
    return client, owner, ws


def _get_templates(ws_id: str, comp_id: str) -> list[dict]:
    with database.transaction() as db:
        return repositories.get_composition_slot_templates(db, comp_id, ws_id)


# ---------------------------------------------------------------------------
# Group 1 — Domain validation
# ---------------------------------------------------------------------------

class TestDomainValidation:
    """validate_slot_templates permits an empty list; per-slot rules unchanged."""

    def test_empty_list_does_not_raise(self):
        albion_compositions.validate_slot_templates([])  # must not raise

    def test_invalid_slot_still_raises(self):
        bad_slot = {"party_number": 1, "slot_index": 1, "role": "", "build_name": "Bow"}
        with pytest.raises(ValidationError, match="role must not be empty"):
            albion_compositions.validate_slot_templates([bad_slot])

    def test_empty_build_name_still_raises(self):
        bad_slot = {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": ""}
        with pytest.raises(ValidationError, match="build_name must not be empty"):
            albion_compositions.validate_slot_templates([bad_slot])

    def test_duplicate_party_index_still_raises(self):
        slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Mace"},
            {"party_number": 1, "slot_index": 1, "role": "Healer", "build_name": "Fall"},
        ]
        with pytest.raises(ValidationError, match="Duplicate slot template"):
            albion_compositions.validate_slot_templates(slots)

    def test_valid_single_slot_still_passes(self):
        slot = {"party_number": 1, "slot_index": 1, "role": "Tank", "build_name": "Mace"}
        albion_compositions.validate_slot_templates([slot])  # must not raise


# ---------------------------------------------------------------------------
# Group 2 — Use case: create with zero slots
# ---------------------------------------------------------------------------

class TestCreateZeroSlotComposition:
    """create_albion_composition accepts an empty slot list."""

    def setup_method(self):
        self.owner = make_user("ZeroSlotOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="zsc-create")

    def test_create_succeeds_with_empty_slots(self):
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="WIP Comp",
            description=None,
            slots=[],
        )
        assert comp["id"]

    def test_created_composition_is_active(self):
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Active Shell",
            description=None,
            slots=[],
        )
        with database.transaction() as db:
            row = repositories.get_albion_composition(db, comp["id"], self.ws["id"])
        assert row["deleted_at"] is None

    def test_zero_slot_templates_stored(self):
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Shell Comp",
            description=None,
            slots=[],
        )
        templates = _get_templates(self.ws["id"], comp["id"])
        assert templates == []

    def test_name_validation_still_enforced(self):
        with pytest.raises(ValidationError):
            use_cases.create_albion_composition(
                guild_workspace_id=self.ws["id"],
                name="",
                description=None,
                slots=[],
            )


# ---------------------------------------------------------------------------
# Group 3 — Edit semantics: update_composition_slots still rejects empty
# ---------------------------------------------------------------------------

class TestUpdateCompositionSlotsRejectsEmpty:
    """update_composition_slots must not clear all slots to zero."""

    def setup_method(self):
        self.owner = make_user("EditGuardOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="zsc-edit")
        self.comp  = make_composition(self.ws["id"])

    def test_empty_update_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Clearing all slots via Edit is not allowed"):
            use_cases.update_composition_slots(
                guild_workspace_id=self.ws["id"],
                composition_id=self.comp["id"],
                actor_user_id=self.owner["id"],
                slots=[],
            )

    def test_valid_update_still_works(self):
        new_slots = [
            {"party_number": 1, "slot_index": 1, "role": "DPS", "build_name": "Daggers"},
        ]
        use_cases.update_composition_slots(
            guild_workspace_id=self.ws["id"],
            composition_id=self.comp["id"],
            actor_user_id=self.owner["id"],
            slots=new_slots,
        )
        templates = _get_templates(self.ws["id"], self.comp["id"])
        assert len(templates) == 1
        assert templates[0]["build_name"] == "Daggers"


# ---------------------------------------------------------------------------
# Group 4 — Routes: POST /compositions with no valid slot cards
# ---------------------------------------------------------------------------

class TestPostCreateCompositionNoSlots:
    """POST /compositions succeeds when all cards are incomplete or none submitted."""

    def test_valid_name_no_slots_redirects_to_list(self):
        client, _, ws = _setup("zsc-route-1")
        resp = client.post(
            f"/workspaces/zsc-route-1/compositions",
            data={"name": "Shell Comp"},
            follow_redirects=False,
        )
        # FastAPI POST redirects use 303 See Other
        assert resp.status_code in (302, 303)
        assert "/compositions" in resp.headers["location"]

    def test_all_incomplete_cards_filtered_succeeds(self):
        """Cards missing role or build_name are silently dropped at the route layer."""
        client, _, ws = _setup("zsc-route-2")
        resp = client.post(
            f"/workspaces/zsc-route-2/compositions",
            data={
                "name": "Partial Comp",
                # Incomplete card: has role but no build_name
                "party_number": ["1"],
                "slot_index": ["1"],
                "role": ["Tank"],
                "build_name": [""],       # empty → dropped
                "weapon_name": [""],
                "doctrine_role": [""],
                "priority": ["normal"],
                "albion_build_id": [""],
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_invalid_name_still_renders_error(self):
        """Name validation error returns the form, not a redirect."""
        client, _, ws = _setup("zsc-route-3")
        resp = client.post(
            f"/workspaces/zsc-route-3/compositions",
            data={"name": "X"},  # too short
            follow_redirects=False,
        )
        # Returns 200 with inline error (not a redirect)
        assert resp.status_code == 200
        assert "compositions_new" in resp.template.name or "error" in resp.text.lower() or "must be at least" in resp.text


# ---------------------------------------------------------------------------
# Group 5 — Templates / UI
# ---------------------------------------------------------------------------

class TestZeroSlotTemplateRendering:
    """Zero-slot compositions are correctly rendered in list and detail pages."""

    def test_zero_slot_comp_visible_in_list(self):
        client, _, ws = _setup("zsc-tmpl-1")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="No Slots Comp",
            description=None,
            slots=[],
        )
        resp = client.get(f"/workspaces/zsc-tmpl-1/compositions")
        assert resp.status_code == 200
        assert "No Slots Comp" in resp.text

    def test_zero_slot_count_visible(self):
        """The slot count cell shows the 'no slots yet' indicator for a 0-slot comp."""
        client, _, ws = _setup("zsc-tmpl-2")
        use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Zero Comp",
            description=None,
            slots=[],
        )
        resp = client.get(f"/workspaces/zsc-tmpl-2/compositions")
        assert resp.status_code == 200
        assert "no slots yet" in resp.text

    def test_detail_page_renders_empty_state(self):
        """compositions_detail.html shows the empty-state block for a 0-slot comp."""
        client, _, ws = _setup("zsc-tmpl-3")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Empty Detail",
            description=None,
            slots=[],
        )
        resp = client.get(f"/workspaces/zsc-tmpl-3/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "No slots defined yet" in resp.text

    def test_detail_page_shows_edit_slots_cta(self):
        """Edit Slots → button present for a 0-slot active composition."""
        client, _, ws = _setup("zsc-tmpl-4")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="CTA Comp",
            description=None,
            slots=[],
        )
        resp = client.get(f"/workspaces/zsc-tmpl-4/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Edit Slots" in resp.text
        assert f"/compositions/{comp['id']}/edit" in resp.text

    def test_compositions_new_hint_text(self):
        """New composition form includes the 'Slots can be added after saving' hint."""
        client, _, ws = _setup("zsc-tmpl-5")
        resp = client.get(f"/workspaces/zsc-tmpl-5/compositions/new")
        assert resp.status_code == 200
        assert "Slots can be added after saving" in resp.text


# ---------------------------------------------------------------------------
# Group 6 — Integration invariants
# ---------------------------------------------------------------------------

class TestZeroSlotIntegration:
    """attach_operation_plan and generate_operation_slots handle zero-slot comps."""

    def setup_method(self):
        self.owner = make_user("IntegOwner")
        self.ws    = make_workspace(owner_user_id=self.owner["id"], slug="zsc-integ")

    def test_attach_succeeds_for_zero_slot_comp(self):
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Shell Comp",
            description=None,
            slots=[],
        )
        op = make_operation(self.ws["id"])
        # Must not raise
        use_cases.attach_operation_plan(self.ws["id"], op["id"], comp["id"])
        with database.transaction() as db:
            plan = repositories.get_operation_plan(db, op["id"], self.ws["id"])
        assert plan is not None

    def test_generate_operation_slots_returns_zero(self):
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Empty Slots Comp",
            description=None,
            slots=[],
        )
        op = make_operation(self.ws["id"])
        use_cases.attach_operation_plan(self.ws["id"], op["id"], comp["id"])
        op_slots = use_cases.generate_operation_slots(self.ws["id"], op["id"])
        assert op_slots == []

    def test_zero_slot_comp_in_new_op_shortcut(self):
        """GET /operations/new?composition_id= works for a zero-slot composition."""
        from fastapi.testclient import TestClient
        client = TestClient(app)
        _login(client, "IntegOwner")
        comp = use_cases.create_albion_composition(
            guild_workspace_id=self.ws["id"],
            name="Shell For Op",
            description=None,
            slots=[],
        )
        resp = client.get(
            f"/workspaces/zsc-integ/operations/new?composition_id={comp['id']}"
        )
        assert resp.status_code == 200
        assert "Shell For Op" in resp.text
