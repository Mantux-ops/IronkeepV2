"""
Build-name and weapon-name suggestion tests (Slice 3).

Covers:
  Group 1 — Repository: get_distinct_slot_build_suggestions
  Group 2 — Route GET /compositions/new renders datalists + list= attributes
  Group 3 — Route GET /compositions/{id}/edit renders datalists + list= attributes
  Group 4 — Route GET /operations/{id}/planner renders datalists + list= attributes
  Group 5 — JS-generated slot card template strings include list= attributes

Intentionally NOT covered here:
  - CSS / visual rendering
  - Browser autocomplete behaviour
  - albion_builds table queries (slice explicitly excludes that source)
  - Tier 5 full-suite run (read-only addition; no use-case or mutation changes)
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


def _make_workspace_with_comp(
    slug: str,
    slots: list[dict] | None = None,
    comp_name: str = "Test Comp",
) -> tuple[TestClient, dict, dict, dict]:
    """Returns (client, owner, ws, comp)."""
    owner  = make_user(f"owner-{slug}")
    ws     = make_workspace(owner_user_id=owner["id"], slug=slug)
    if slots is None:
        slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Tombhammer", "weapon_name": "1H Mace", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "Hallowfall", "weapon_name": "", "priority": "core"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",
             "build_name": "Daggers", "weapon_name": "Bloodletter", "priority": "normal"},
        ]
    comp = make_composition(ws["id"], name=comp_name, slots=slots)
    client = TestClient(app)
    _login(client, f"owner-{slug}")
    return client, owner, ws, comp


# ---------------------------------------------------------------------------
# Group 1 — Repository
# ---------------------------------------------------------------------------

class TestGetDistinctSlotBuildSuggestions:
    """get_distinct_slot_build_suggestions returns correct values."""

    def test_returns_distinct_build_names(self):
        ws    = make_workspace(slug="sugg-repo-1")
        slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Tombhammer", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "Hallowfall", "priority": "core"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",
             "build_name": "Tombhammer", "priority": "normal"},
        ]
        make_composition(ws["id"], slots=slots)
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert result["build_names"] == ["Hallowfall", "Tombhammer"]

    def test_returns_distinct_weapon_names(self):
        ws    = make_workspace(slug="sugg-repo-2")
        slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "A", "weapon_name": "1H Mace", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "B", "weapon_name": "Hallowfall", "priority": "core"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",
             "build_name": "C", "weapon_name": "1H Mace", "priority": "normal"},
        ]
        make_composition(ws["id"], slots=slots)
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert result["weapon_names"] == ["1H Mace", "Hallowfall"]

    def test_sorted_alphabetically(self):
        ws    = make_workspace(slug="sugg-repo-3")
        slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Zeppelin", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "Alpha", "priority": "core"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",
             "build_name": "Mace Build", "priority": "normal"},
        ]
        make_composition(ws["id"], slots=slots)
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert result["build_names"] == sorted(result["build_names"])

    def test_empty_workspace_returns_empty_lists(self):
        ws = make_workspace(slug="sugg-repo-4")
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert result == {"build_names": [], "weapon_names": []}

    def test_excludes_empty_build_names(self):
        """Repository-level: empty build_name rows are excluded from suggestions.
        Inserted directly via repository to bypass use-case validation which rejects
        empty build_name at the application layer.
        """
        import uuid
        from datetime import datetime, timezone
        ws   = make_workspace(slug="sugg-repo-5")
        comp = make_composition(ws["id"], name="Comp for empty test", slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Tombhammer", "priority": "core"},
        ])
        now = datetime.now(timezone.utc).isoformat()
        with database.transaction() as db:
            repositories.insert_composition_slot_templates(db, [
                {
                    "id": str(uuid.uuid4()),
                    "guild_workspace_id":    ws["id"],
                    "albion_composition_id": comp["id"],
                    "party_number":   1,
                    "slot_index":     2,
                    "role":           "Healer",
                    "build_name":     "",
                    "weapon_name":    None,
                    "offhand_name":   None,
                    "head_name":      None,
                    "armor_name":     None,
                    "shoes_name":     None,
                    "cape_name":      None,
                    "food_name":      None,
                    "potion_name":    None,
                    "albion_build_id": None,
                    "doctrine_role":  None,
                    "priority":       "core",
                    "created_at":     now,
                    "updated_at":     now,
                },
            ])
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert "" not in result["build_names"]
        assert "Tombhammer" in result["build_names"]

    def test_excludes_null_and_empty_weapon_names(self):
        """Null and empty weapon_name rows are excluded from suggestions."""
        ws    = make_workspace(slug="sugg-repo-6")
        slots = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "A", "weapon_name": "1H Mace", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "B", "priority": "core"},
        ]
        make_composition(ws["id"], slots=slots)
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert "" not in result["weapon_names"]
        assert None not in result["weapon_names"]
        assert "1H Mace" in result["weapon_names"]

    def test_workspace_scoped_does_not_leak_across_workspaces(self):
        ws1 = make_workspace(slug="sugg-scope-1")
        ws2 = make_workspace(slug="sugg-scope-2")
        slots_ws1 = [{"party_number": 1, "slot_index": 1, "role": "Tank",
                      "build_name": "WS1-Only-Build", "priority": "core"}]
        slots_ws2 = [{"party_number": 1, "slot_index": 1, "role": "Tank",
                      "build_name": "WS2-Only-Build", "priority": "core"}]
        make_composition(ws1["id"], slots=slots_ws1)
        make_composition(ws2["id"], slots=slots_ws2)

        with database.transaction() as db:
            r1 = repositories.get_distinct_slot_build_suggestions(db, ws1["id"])
            r2 = repositories.get_distinct_slot_build_suggestions(db, ws2["id"])

        assert "WS1-Only-Build" in r1["build_names"]
        assert "WS2-Only-Build" not in r1["build_names"]
        assert "WS2-Only-Build" in r2["build_names"]
        assert "WS1-Only-Build" not in r2["build_names"]

    def test_multiple_compositions_aggregated(self):
        """Suggestions are drawn from all compositions in the workspace."""
        ws = make_workspace(slug="sugg-multi-comp")
        make_composition(ws["id"], name="Comp A", slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Tombhammer", "priority": "core"},
        ])
        make_composition(ws["id"], name="Comp B", slots=[
            {"party_number": 1, "slot_index": 1, "role": "Healer",
             "build_name": "Fallen Staff", "priority": "core"},
        ])
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert "Tombhammer" in result["build_names"]
        assert "Fallen Staff" in result["build_names"]

    def test_returns_dict_with_correct_keys(self):
        ws = make_workspace(slug="sugg-keys")
        with database.transaction() as db:
            result = repositories.get_distinct_slot_build_suggestions(db, ws["id"])
        assert set(result.keys()) == {"build_names", "weapon_names"}
        assert isinstance(result["build_names"], list)
        assert isinstance(result["weapon_names"], list)


# ---------------------------------------------------------------------------
# Group 2 — Route GET /compositions/new
# ---------------------------------------------------------------------------

class TestNewCompositionDatalistRendering:
    """GET /compositions/new renders datalists and wires list= attributes."""

    def _get(self, slug: str) -> "Response":
        owner  = make_user(f"new-owner-{slug}")
        ws     = make_workspace(owner_user_id=owner["id"], slug=slug)
        # Seed a composition so the workspace has suggestions.
        make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Tombhammer", "weapon_name": "1H Mace", "priority": "core"},
        ])
        client = TestClient(app)
        _login(client, f"new-owner-{slug}")
        return client.get(f"/workspaces/{slug}/compositions/new")

    def test_build_name_datalist_present(self):
        resp = self._get("new-dl-1")
        assert resp.status_code == 200
        assert 'id="build-name-list"' in resp.text

    def test_weapon_name_datalist_present(self):
        resp = self._get("new-dl-2")
        assert resp.status_code == 200
        assert 'id="weapon-name-list"' in resp.text

    def test_build_name_datalist_contains_suggestion(self):
        resp = self._get("new-dl-3")
        assert "Tombhammer" in resp.text

    def test_weapon_name_datalist_contains_suggestion(self):
        resp = self._get("new-dl-4")
        assert "1H Mace" in resp.text

    def test_build_name_input_has_list_attribute(self):
        resp = self._get("new-dl-5")
        assert 'list="build-name-list"' in resp.text

    def test_weapon_name_input_has_list_attribute(self):
        resp = self._get("new-dl-6")
        assert 'list="weapon-name-list"' in resp.text

    def test_datalists_render_for_empty_workspace(self):
        """Datalists should still render (empty) when no templates exist."""
        owner  = make_user("new-empty-owner")
        ws     = make_workspace(owner_user_id=owner["id"], slug="new-dl-empty")
        client = TestClient(app)
        _login(client, "new-empty-owner")
        resp = client.get(f"/workspaces/new-dl-empty/compositions/new")
        assert resp.status_code == 200
        assert 'id="build-name-list"' in resp.text
        assert 'id="weapon-name-list"' in resp.text


# ---------------------------------------------------------------------------
# Group 3 — Route GET /compositions/{id}/edit
# ---------------------------------------------------------------------------

class TestEditCompositionDatalistRendering:
    """GET /compositions/{id}/edit renders datalists and wires list= attributes."""

    def _get(self, slug: str) -> "Response":
        client, owner, ws, comp = _make_workspace_with_comp(f"edit-dl-{slug}")
        return client.get(f"/workspaces/edit-dl-{slug}/compositions/{comp['id']}/edit")

    def test_build_name_datalist_present(self):
        resp = self._get("1")
        assert resp.status_code == 200
        assert 'id="build-name-list"' in resp.text

    def test_weapon_name_datalist_present(self):
        resp = self._get("2")
        assert resp.status_code == 200
        assert 'id="weapon-name-list"' in resp.text

    def test_build_name_datalist_contains_suggestion(self):
        resp = self._get("3")
        assert "Tombhammer" in resp.text

    def test_weapon_name_datalist_contains_suggestion(self):
        resp = self._get("4")
        assert "1H Mace" in resp.text

    def test_build_name_input_has_list_attribute(self):
        resp = self._get("5")
        assert 'list="build-name-list"' in resp.text

    def test_weapon_name_input_has_list_attribute(self):
        resp = self._get("6")
        assert 'list="weapon-name-list"' in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Route GET /operations/{id}/planner
# ---------------------------------------------------------------------------

class TestPlannerDatalistRendering:
    """GET /operations/{id}/planner renders datalists and wires list= attributes."""

    def _get(self, slug: str) -> "Response":
        client, owner, ws, comp = _make_workspace_with_comp(f"plan-dl-{slug}")
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        return client.get(f"/workspaces/plan-dl-{slug}/operations/{op['id']}/planner")

    def test_build_name_datalist_present(self):
        resp = self._get("1")
        assert resp.status_code == 200
        assert 'id="build-name-list"' in resp.text

    def test_weapon_name_datalist_present(self):
        resp = self._get("2")
        assert resp.status_code == 200
        assert 'id="weapon-name-list"' in resp.text

    def test_build_name_datalist_contains_suggestion(self):
        resp = self._get("3")
        assert "Tombhammer" in resp.text

    def test_weapon_name_datalist_contains_suggestion(self):
        resp = self._get("4")
        assert "1H Mace" in resp.text

    def test_build_name_input_has_list_attribute(self):
        resp = self._get("5")
        assert 'list="build-name-list"' in resp.text

    def test_weapon_name_input_has_list_attribute(self):
        resp = self._get("6")
        assert 'list="weapon-name-list"' in resp.text

    def test_datalists_render_even_if_no_prior_templates(self):
        """Planner datalists are conditional on content but the route always passes lists."""
        owner  = make_user("plan-empty-owner")
        ws     = make_workspace(owner_user_id=owner["id"], slug="plan-dl-empty")
        # Composition with no weapon_name entries
        comp = make_composition(ws["id"], slots=[
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "1H Mace", "priority": "core"},
        ])
        op = make_operation(ws["id"])
        use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
        use_cases.publish_operation(ws["id"], op["id"])
        use_cases.generate_operation_slots(ws["id"], op["id"])
        client = TestClient(app)
        _login(client, "plan-empty-owner")
        resp = client.get(f"/workspaces/plan-dl-empty/operations/{op['id']}/planner")
        assert resp.status_code == 200
        # At least one datalist is rendered (build_names will have "1H Mace").
        assert "1H Mace" in resp.text


# ---------------------------------------------------------------------------
# Group 5 — JS-generated slot card strings include list= attributes
# ---------------------------------------------------------------------------

class TestJsGeneratedSlotCardListAttributes:
    """The JS _createSlotCard string in new/edit templates includes list= attrs."""

    def test_new_comp_js_build_name_has_list_attr(self):
        owner  = make_user("js-new-owner")
        ws     = make_workspace(owner_user_id=owner["id"], slug="js-new-1")
        client = TestClient(app)
        _login(client, "js-new-owner")
        resp = client.get(f"/workspaces/js-new-1/compositions/new")
        assert resp.status_code == 200
        # The JS string literal must contain the list= attribute so dynamically
        # created cards also participate in the datalist.
        assert 'list="build-name-list"' in resp.text
        assert 'list="weapon-name-list"' in resp.text

    def test_edit_comp_js_build_name_has_list_attr(self):
        client, _, ws, comp = _make_workspace_with_comp("js-edit-1")
        resp = client.get(f"/workspaces/js-edit-1/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert 'list="build-name-list"' in resp.text
        assert 'list="weapon-name-list"' in resp.text
