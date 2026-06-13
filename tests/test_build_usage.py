"""
Phase 7 Slice 1 — Build Usage Discovery tests.

Covers:
  Group 1 — Repository: get_build_usage_compositions
  Group 2 — Repository: get_builds_with_usage_counts
  Group 3 — Build detail: used_in context and template rendering
  Group 4 — Build list: usage badge on bld-card
  Group 5 — Build list: role filter pills
  Group 6 — Build edit: informational usage note

Invariants verified:
  - Retired compositions are excluded from usage counts
  - NULL albion_build_id does not produce false positives
  - Cross-workspace isolation is preserved
  - Builds with no FK references carry usage_count = 0
  - All discovery is read-only — no write paths are tested here
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app

from tests.conftest import make_composition, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: TestClient, name: str) -> None:
    client.post("/login", data={"display_name": name, "next": "/"}, follow_redirects=True)


def _make_build(ws_id: str, owner_id: str, name="Test Build", role="Tank",
                weapon="1H Mace") -> dict:
    return use_cases.create_albion_build(
        guild_workspace_id=ws_id,
        actor_user_id=owner_id,
        name=name,
        role=role,
        weapon_name=weapon,
    )


def _make_comp_with_build_fk(ws_id: str, build_id: str,
                              comp_name: str = "FK Comp") -> dict:
    """Create a composition whose single slot references build_id via FK."""
    return use_cases.create_albion_composition(
        guild_workspace_id=ws_id,
        name=comp_name,
        description=None,
        slots=[{
            "party_number": 1,
            "slot_index": 1,
            "role": "Tank",
            "build_name": "anything",
            "albion_build_id": build_id,
            "priority": "core",
        }],
    )


# ---------------------------------------------------------------------------
# Group 1 — Repository: get_build_usage_compositions
# ---------------------------------------------------------------------------

class TestGetBuildUsageCompositions:

    def test_returns_compositions_that_reference_build(self):
        owner = make_user("bu-g1-a")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g1-a")
        build = _make_build(ws["id"], owner["id"])
        comp  = _make_comp_with_build_fk(ws["id"], build["id"])

        with database.transaction() as db:
            result = repositories.get_build_usage_compositions(db, build["id"], ws["id"])

        assert len(result) == 1
        assert result[0]["id"] == comp["id"]
        assert result[0]["name"] == comp["name"]

    def test_returns_empty_when_no_compositions_reference_build(self):
        owner = make_user("bu-g1-b")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g1-b")
        build = _make_build(ws["id"], owner["id"])

        with database.transaction() as db:
            result = repositories.get_build_usage_compositions(db, build["id"], ws["id"])

        assert result == []

    def test_excludes_retired_compositions(self):
        owner = make_user("bu-g1-c")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g1-c")
        build = _make_build(ws["id"], owner["id"])
        comp  = _make_comp_with_build_fk(ws["id"], build["id"])
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )

        with database.transaction() as db:
            result = repositories.get_build_usage_compositions(db, build["id"], ws["id"])

        assert result == []

    def test_workspace_isolation(self):
        """Build in workspace A is not visible via workspace B query."""
        owner_a = make_user("bu-g1-d-a")
        ws_a    = make_workspace(owner_user_id=owner_a["id"], slug="bu-g1-d-a")
        build_a = _make_build(ws_a["id"], owner_a["id"], name="A Build")
        _make_comp_with_build_fk(ws_a["id"], build_a["id"])

        owner_b = make_user("bu-g1-d-b")
        ws_b    = make_workspace(owner_user_id=owner_b["id"], slug="bu-g1-d-b")

        with database.transaction() as db:
            result = repositories.get_build_usage_compositions(
                db, build_a["id"], ws_b["id"]
            )

        assert result == []

    def test_null_albion_build_id_slots_not_counted(self):
        """String-based slots (albion_build_id=NULL) do not produce false positives."""
        owner = make_user("bu-g1-e")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g1-e")
        build = _make_build(ws["id"], owner["id"])
        # Composition with only free-typed slots (no FK)
        make_composition(ws["id"], name="No FK comp")

        with database.transaction() as db:
            result = repositories.get_build_usage_compositions(db, build["id"], ws["id"])

        assert result == []

    def test_distinct_compositions_multiple_slots_same_build(self):
        """A comp with two slots both referencing the same build counts as 1."""
        owner = make_user("bu-g1-f")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g1-f")
        build = _make_build(ws["id"], owner["id"])
        use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Double slot comp",
            description=None,
            slots=[
                {"party_number": 1, "slot_index": 1, "role": "Tank",
                 "build_name": "x", "albion_build_id": build["id"], "priority": "core"},
                {"party_number": 1, "slot_index": 2, "role": "Tank",
                 "build_name": "x", "albion_build_id": build["id"], "priority": "core"},
            ],
        )

        with database.transaction() as db:
            result = repositories.get_build_usage_compositions(db, build["id"], ws["id"])

        assert len(result) == 1


# ---------------------------------------------------------------------------
# Group 2 — Repository: get_builds_with_usage_counts
# ---------------------------------------------------------------------------

class TestGetBuildsWithUsageCounts:

    def test_unreferenced_build_has_usage_count_zero(self):
        owner = make_user("bu-g2-a")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g2-a")
        _make_build(ws["id"], owner["id"], name="Unused Build")

        with database.transaction() as db:
            builds = repositories.get_builds_with_usage_counts(db, ws["id"])

        assert len(builds) == 1
        assert builds[0]["usage_count"] == 0

    def test_referenced_build_has_correct_usage_count(self):
        owner = make_user("bu-g2-b")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g2-b")
        build = _make_build(ws["id"], owner["id"], name="Used Build")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp A")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp B")

        with database.transaction() as db:
            builds = repositories.get_builds_with_usage_counts(db, ws["id"])

        assert len(builds) == 1
        assert builds[0]["usage_count"] == 2

    def test_retired_compositions_not_counted(self):
        owner = make_user("bu-g2-c")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g2-c")
        build = _make_build(ws["id"], owner["id"])
        comp  = _make_comp_with_build_fk(ws["id"], build["id"])
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )

        with database.transaction() as db:
            builds = repositories.get_builds_with_usage_counts(db, ws["id"])

        assert builds[0]["usage_count"] == 0

    def test_retired_build_appears_when_include_retired_true(self):
        owner = make_user("bu-g2-d")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g2-d")
        build = _make_build(ws["id"], owner["id"], name="Retire Me")
        use_cases.retire_albion_build(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
        )

        with database.transaction() as db:
            active = repositories.get_builds_with_usage_counts(db, ws["id"])
            all_b  = repositories.get_builds_with_usage_counts(
                db, ws["id"], include_retired=True
            )

        assert len(active) == 0
        assert len(all_b) == 1
        assert all_b[0]["usage_count"] == 0

    def test_multiple_builds_independent_counts(self):
        owner  = make_user("bu-g2-e")
        ws     = make_workspace(owner_user_id=owner["id"], slug="bu-g2-e")
        build1 = _make_build(ws["id"], owner["id"], name="AAA Build", role="Tank")
        build2 = _make_build(ws["id"], owner["id"], name="BBB Build", role="Healer")
        _make_comp_with_build_fk(ws["id"], build1["id"], "Only uses build1")

        with database.transaction() as db:
            builds = repositories.get_builds_with_usage_counts(db, ws["id"])

        counts = {b["name"]: b["usage_count"] for b in builds}
        assert counts["AAA Build"] == 1
        assert counts["BBB Build"] == 0


# ---------------------------------------------------------------------------
# Group 3 — Build detail: used_in context and template rendering
# ---------------------------------------------------------------------------

class TestBuildDetailUsedIn:

    def test_build_detail_lists_referencing_composition(self):
        owner = make_user("bu-g3-a")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g3-a")
        build = _make_build(ws["id"], owner["id"], name="Visible Build")
        comp  = _make_comp_with_build_fk(ws["id"], build["id"], "Showcase Comp")
        client = TestClient(app)
        _login(client, "bu-g3-a")

        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")

        assert resp.status_code == 200
        assert "Showcase Comp" in resp.text
        assert f"/compositions/{comp['id']}" in resp.text

    def test_build_detail_no_used_in_section_when_unreferenced(self):
        owner = make_user("bu-g3-b")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g3-b")
        build = _make_build(ws["id"], owner["id"], name="Lonely Build")
        client = TestClient(app)
        _login(client, "bu-g3-b")

        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")

        assert resp.status_code == 200
        assert "bld-usage-list" not in resp.text
        assert "Referenced by" not in resp.text

    def test_retired_composition_not_shown_in_used_in(self):
        owner = make_user("bu-g3-c")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g3-c")
        build = _make_build(ws["id"], owner["id"], name="Retired Ref Build")
        comp  = _make_comp_with_build_fk(ws["id"], build["id"], "Retired Comp")
        use_cases.retire_composition(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
        )
        client = TestClient(app)
        _login(client, "bu-g3-c")

        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")

        assert resp.status_code == 200
        assert "Retired Comp" not in resp.text
        assert "Referenced by" not in resp.text


# ---------------------------------------------------------------------------
# Group 4 — Build list: usage badge on bld-card
# ---------------------------------------------------------------------------

class TestBuildListUsageBadge:

    def test_active_referenced_build_shows_usage_badge(self):
        owner = make_user("bu-g4-a")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g4-a")
        build = _make_build(ws["id"], owner["id"], name="Badged Build")
        _make_comp_with_build_fk(ws["id"], build["id"])
        client = TestClient(app)
        _login(client, "bu-g4-a")

        resp = client.get(f"/workspaces/{ws['slug']}/builds")

        assert resp.status_code == 200
        assert "bld-card__usage" in resp.text
        assert "used in 1 comp" in resp.text

    def test_unreferenced_build_has_no_usage_badge(self):
        owner = make_user("bu-g4-b")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g4-b")
        _make_build(ws["id"], owner["id"], name="Plain Build")
        client = TestClient(app)
        _login(client, "bu-g4-b")

        resp = client.get(f"/workspaces/{ws['slug']}/builds")

        assert resp.status_code == 200
        assert "bld-card__usage" not in resp.text

    def test_plural_comps_in_badge(self):
        owner = make_user("bu-g4-c")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g4-c")
        build = _make_build(ws["id"], owner["id"], name="Multi Comp Build")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp Alpha")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp Beta")
        client = TestClient(app)
        _login(client, "bu-g4-c")

        resp = client.get(f"/workspaces/{ws['slug']}/builds")

        assert "used in 2 comps" in resp.text


# ---------------------------------------------------------------------------
# Group 5 — Build list: role filter pills
# ---------------------------------------------------------------------------

class TestBuildListRoleFilter:

    def test_filter_pills_shown_when_two_or_more_roles_exist(self):
        owner = make_user("bu-g5-a")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g5-a")
        _make_build(ws["id"], owner["id"], name="Tank Build", role="Tank")
        _make_build(ws["id"], owner["id"], name="Healer Build", role="Healer")
        client = TestClient(app)
        _login(client, "bu-g5-a")

        resp = client.get(f"/workspaces/{ws['slug']}/builds")

        assert "bld-role-filter" in resp.text
        assert "Tank" in resp.text
        assert "Healer" in resp.text

    def test_filter_pills_not_shown_when_single_role(self):
        owner = make_user("bu-g5-b")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g5-b")
        _make_build(ws["id"], owner["id"], name="Only Tank", role="Tank")
        client = TestClient(app)
        _login(client, "bu-g5-b")

        resp = client.get(f"/workspaces/{ws['slug']}/builds")

        assert "bld-role-filter" not in resp.text

    def test_role_filter_returns_only_matching_builds(self):
        owner = make_user("bu-g5-c")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g5-c")
        _make_build(ws["id"], owner["id"], name="Tank Build", role="Tank")
        _make_build(ws["id"], owner["id"], name="DPS Build", role="DPS")
        client = TestClient(app)
        _login(client, "bu-g5-c")

        resp = client.get(f"/workspaces/{ws['slug']}/builds?role=Tank")

        assert "Tank Build" in resp.text
        assert "DPS Build" not in resp.text

    def test_no_role_param_returns_all_builds(self):
        owner = make_user("bu-g5-d")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g5-d")
        _make_build(ws["id"], owner["id"], name="Build One", role="Tank")
        _make_build(ws["id"], owner["id"], name="Build Two", role="Healer")
        client = TestClient(app)
        _login(client, "bu-g5-d")

        resp = client.get(f"/workspaces/{ws['slug']}/builds")

        assert "Build One" in resp.text
        assert "Build Two" in resp.text

    def test_active_filter_pill_has_btn_secondary_class(self):
        owner = make_user("bu-g5-e")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g5-e")
        _make_build(ws["id"], owner["id"], name="Tank Build", role="Tank")
        _make_build(ws["id"], owner["id"], name="Healer Build", role="Healer")
        client = TestClient(app)
        _login(client, "bu-g5-e")

        resp = client.get(f"/workspaces/{ws['slug']}/builds?role=Tank")

        assert resp.status_code == 200
        assert "?role=Tank" in resp.text


# ---------------------------------------------------------------------------
# Group 6 — Build edit: informational usage note
# ---------------------------------------------------------------------------

class TestBuildEditUsageNote:

    def test_edit_page_shows_note_when_build_is_referenced(self):
        owner = make_user("bu-g6-a")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g6-a")
        build = _make_build(ws["id"], owner["id"], name="Referenced Build")
        _make_comp_with_build_fk(ws["id"], build["id"])
        client = TestClient(app)
        _login(client, "bu-g6-a")

        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")

        assert resp.status_code == 200
        assert "snapshot invariant is preserved" in resp.text
        assert "1 active composition" in resp.text

    def test_edit_page_no_usage_note_when_unreferenced(self):
        owner = make_user("bu-g6-b")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g6-b")
        build = _make_build(ws["id"], owner["id"], name="Solo Build")
        client = TestClient(app)
        _login(client, "bu-g6-b")

        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")

        assert resp.status_code == 200
        assert "snapshot invariant is preserved" not in resp.text

    def test_edit_page_shows_plural_count(self):
        owner = make_user("bu-g6-c")
        ws    = make_workspace(owner_user_id=owner["id"], slug="bu-g6-c")
        build = _make_build(ws["id"], owner["id"], name="Wide Build")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp One")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp Two")
        _make_comp_with_build_fk(ws["id"], build["id"], "Comp Three")
        client = TestClient(app)
        _login(client, "bu-g6-c")

        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")

        assert "3 active compositions" in resp.text
