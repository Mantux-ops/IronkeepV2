"""
Tactical Doctrine Identity slice — regression tests.

Covers:
  Group 1  — Domain validation: doctrine_role field accepted / rejected correctly
  Group 2  — Repository round-trips: albion_builds insert/update with doctrine_role
  Group 3  — Use case: create / update build with doctrine_role persists
  Group 4  — _resolve_build_for_slot propagation:
               a) build default propagated when slot doctrine_role is empty
               b) slot-level override preserved when slot already has a value
               c) no-FK path preserves slot doctrine_role as-is
  Group 5  — Snapshot invariant:
               a) doctrine_role frozen in operation_slots at generation time
               b) build edit does NOT mutate historical composition slot templates
               c) build edit does NOT mutate historical operation_slots
  Group 6  — create_albion_composition / update_composition_slots propagation
  Group 7  — Tactical summaries remain role_family-based (doctrine_role excluded)
  Group 8  — Route GET / POST: builds_new, builds_edit, build create/update
  Group 9  — Composition template: doctrine_role renders as primary tier in edit/detail
  Group 10 — Nullable / blank semantics: omitting doctrine_role persists NULL
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.domain import albion_builds as builds_domain
from app.errors import ValidationError
from app.main import app
from app import tactical

from tests.conftest import make_composition, make_operation, make_user, make_workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_setup(slug: str = "doctrine-ws"):
    owner = make_user("Doc Officer")
    ws    = make_workspace(owner_user_id=owner["id"], slug=slug)
    client = TestClient(app)
    client.post("/login", data={"display_name": "Doc Officer", "next": "/"}, follow_redirects=True)
    return client, owner, ws


def _create_build(ws_id: str, actor_id: str, **overrides) -> dict:
    defaults = {
        "guild_workspace_id": ws_id,
        "actor_user_id":      actor_id,
        "name":               "Hallowfall Healer",
        "role":               "Healer",
        "weapon_name":        "T8.3 Hallowfall",
    }
    return use_cases.create_albion_build(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Group 1 — Domain validation
# ---------------------------------------------------------------------------

class TestDoctrineRoleDomainValidation:
    def test_accepts_no_doctrine_role(self):
        """doctrine_role is optional; absent is valid."""
        builds_domain.validate_build({
            "name": "Test Build", "role": "Tank", "weapon_name": "1H Mace",
        })

    def test_accepts_null_doctrine_role(self):
        builds_domain.validate_build({
            "name": "Test Build", "role": "Tank", "weapon_name": "1H Mace",
            "doctrine_role": None,
        })

    def test_accepts_valid_doctrine_role(self):
        builds_domain.validate_build({
            "name": "Test Build", "role": "Tank", "weapon_name": "1H Mace",
            "doctrine_role": "Main Caller",
        })

    def test_accepts_slash_notation(self):
        builds_domain.validate_build({
            "name": "Test Build", "role": "Tank", "weapon_name": "1H Mace",
            "doctrine_role": "Peel / Stopper",
        })

    def test_rejects_doctrine_role_exceeding_max_length(self):
        with pytest.raises(ValidationError, match="doctrine_role"):
            builds_domain.validate_build({
                "name": "Test Build", "role": "Tank", "weapon_name": "1H Mace",
                "doctrine_role": "x" * 121,
            })

    def test_accepts_doctrine_role_at_max_length(self):
        builds_domain.validate_build({
            "name": "Test Build", "role": "Tank", "weapon_name": "1H Mace",
            "doctrine_role": "x" * 120,
        })


# ---------------------------------------------------------------------------
# Group 2 — Repository round-trips
# ---------------------------------------------------------------------------

class TestDoctrineRoleRepository:
    def test_insert_read_with_doctrine_role(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="repo-dr")

        with database.transaction() as db:
            build_row = {
                "id": "bld-dr-01",
                "guild_workspace_id": ws["id"],
                "name": "Occult Beam",
                "role": "Support",
                "weapon_name": "Occult Staff",
                "offhand_name": None,
                "head_name": None,
                "armor_name": None,
                "shoes_name": None,
                "cape_name": None,
                "food_name": None,
                "potion_name": None,
                "notes": None,
                "doctrine_role": "Beam Spike",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "retired_at": None,
            }
            repositories.insert_albion_build(db, build_row)
            fetched = repositories.get_albion_build(db, "bld-dr-01", ws["id"])

        assert fetched["doctrine_role"] == "Beam Spike"

    def test_update_doctrine_role(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="repo-dr-upd")
        build = _create_build(ws["id"], owner["id"])

        with database.transaction() as db:
            repositories.update_albion_build_fields(
                db,
                build["id"],
                ws["id"],
                {
                    "name": build["name"],
                    "role": build["role"],
                    "weapon_name": build["weapon_name"],
                    "offhand_name": None,
                    "head_name": None,
                    "armor_name": None,
                    "shoes_name": None,
                    "cape_name": None,
                    "food_name": None,
                    "potion_name": None,
                    "notes": None,
                    "doctrine_role": "Backline Heal",
                },
                updated_at="2026-01-01T01:00:00",
            )
            updated = repositories.get_albion_build(db, build["id"], ws["id"])

        assert updated["doctrine_role"] == "Backline Heal"


# ---------------------------------------------------------------------------
# Group 3 — Use case: create / update
# ---------------------------------------------------------------------------

class TestDoctrineRoleUseCases:
    def test_create_build_persists_doctrine_role(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-dr-create")
        build = _create_build(ws["id"], owner["id"], doctrine_role="Engage")

        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], ws["id"])

        assert fetched["doctrine_role"] == "Engage"

    def test_create_build_without_doctrine_role_stores_null(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-dr-null")
        build = _create_build(ws["id"], owner["id"])

        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], ws["id"])

        assert fetched["doctrine_role"] is None

    def test_update_build_doctrine_role(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-dr-upd")
        build = _create_build(ws["id"], owner["id"])

        use_cases.update_albion_build(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            name=build["name"],
            role=build["role"],
            weapon_name=build["weapon_name"],
            doctrine_role="Peel / Stopper",
        )

        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], ws["id"])
        assert fetched["doctrine_role"] == "Peel / Stopper"

    def test_update_build_clears_doctrine_role_when_empty(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="uc-dr-clr")
        build = _create_build(ws["id"], owner["id"], doctrine_role="Engage")

        use_cases.update_albion_build(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            name=build["name"],
            role=build["role"],
            weapon_name=build["weapon_name"],
            doctrine_role="",  # empty → NULL
        )

        with database.transaction() as db:
            fetched = repositories.get_albion_build(db, build["id"], ws["id"])
        assert fetched["doctrine_role"] is None


# ---------------------------------------------------------------------------
# Group 4 — _resolve_build_for_slot propagation
# ---------------------------------------------------------------------------

class TestResolveDoctrineRole:
    def test_build_default_propagated_to_empty_slot(self):
        """When slot doctrine_role is empty, build default propagates."""
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="resolve-dr-prop")
        build = _create_build(ws["id"], owner["id"], doctrine_role="Soak")

        slot = {
            "role": "Support",
            "build_name": "",
            "weapon_name": "",
            "albion_build_id": build["id"],
            "doctrine_role": "",   # empty → use build default
            "priority": "normal",
        }
        with database.transaction() as db:
            resolved = use_cases._resolve_build_for_slot(db, ws["id"], slot)

        assert resolved["doctrine_role"] == "Soak"

    def test_slot_override_preserved_over_build_default(self):
        """When slot already has doctrine_role, it wins over build default."""
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="resolve-dr-ovr")
        build = _create_build(ws["id"], owner["id"], doctrine_role="Soak")

        slot = {
            "role": "Support",
            "build_name": "",
            "weapon_name": "",
            "albion_build_id": build["id"],
            "doctrine_role": "Support Heal",  # slot-level override
            "priority": "normal",
        }
        with database.transaction() as db:
            resolved = use_cases._resolve_build_for_slot(db, ws["id"], slot)

        assert resolved["doctrine_role"] == "Support Heal"

    def test_no_build_id_preserves_slot_doctrine_role(self):
        """When no build FK, slot doctrine_role is kept unchanged."""
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="resolve-dr-nobi")

        slot = {
            "role": "Tank",
            "build_name": "1H Mace",
            "weapon_name": "1H Mace",
            "albion_build_id": None,
            "doctrine_role": "Main Caller",
            "priority": "core",
        }
        with database.transaction() as db:
            resolved = use_cases._resolve_build_for_slot(db, ws["id"], slot)

        assert resolved["doctrine_role"] == "Main Caller"

    def test_missing_build_id_preserves_slot_doctrine_role(self):
        """When build FK does not resolve, slot doctrine_role is kept."""
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="resolve-dr-miss")

        slot = {
            "role": "Tank",
            "build_name": "1H Mace",
            "weapon_name": "1H Mace",
            "albion_build_id": "nonexistent-build-id",
            "doctrine_role": "Engage",
            "priority": "normal",
        }
        with database.transaction() as db:
            resolved = use_cases._resolve_build_for_slot(db, ws["id"], slot)

        assert resolved["doctrine_role"] == "Engage"
        assert resolved["albion_build_id"] is None  # FK cleared


# ---------------------------------------------------------------------------
# Group 5 — Snapshot invariants
# ---------------------------------------------------------------------------

class TestDoctrineRoleSnapshotInvariant:
    def _setup_frozen(self, slug: str):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug=slug)
        build = _create_build(ws["id"], owner["id"], doctrine_role="Engage")

        slots = [
            {
                "party_number": 1, "slot_index": i, "role": r, "build_name": b,
                "albion_build_id": build["id"] if i == 1 else None,
                "doctrine_role": None,
                "priority": "normal",
            }
            for i, (r, b) in enumerate(
                [("Tank", "1H Mace"), ("Healer", "Hallowfall"),
                 ("DPS", "Daggers"), ("Support", "Locus"), ("DPS", "Bow")],
                start=1,
            )
        ]
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Freeze Test",
            description=None,
            slots=slots,
        )
        return owner, ws, build, comp

    def test_doctrine_role_frozen_in_composition_slot_template(self):
        """doctrine_role propagated from build is frozen into slot template at attach time."""
        owner, ws, build, comp = self._setup_frozen("dr-frozen-cst")

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(
                db, comp["id"], ws["id"]
            )
        slot_1 = next(t for t in templates if t["slot_index"] == 1)
        assert slot_1["doctrine_role"] == "Engage"

    def test_build_edit_does_not_mutate_composition_slot_template(self):
        """Editing build doctrine_role later does NOT update existing slot templates."""
        owner, ws, build, comp = self._setup_frozen("dr-bsi-cst")

        # Read the frozen value before edit
        with database.transaction() as db:
            before = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        slot_before = next(t for t in before if t["slot_index"] == 1)
        frozen_doctrine = slot_before["doctrine_role"]

        # Edit the build's doctrine_role
        use_cases.update_albion_build(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            name=build["name"],
            role=build["role"],
            weapon_name=build["weapon_name"],
            doctrine_role="MUTATED — should not appear",
        )

        # Slot template must be unchanged
        with database.transaction() as db:
            after = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        slot_after = next(t for t in after if t["slot_index"] == 1)
        assert slot_after["doctrine_role"] == frozen_doctrine

    def test_doctrine_role_frozen_in_operation_slots(self):
        """doctrine_role is frozen into operation_slots at generation time."""
        owner, ws, build, comp = self._setup_frozen("dr-frozen-ops")
        op = make_operation(ws["id"])

        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )

        with database.transaction() as db:
            op_slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        slot_1 = next(s for s in op_slots if s["slot_index"] == 1)
        assert slot_1["doctrine_role"] == "Engage"

    def test_build_edit_does_not_mutate_operation_slots(self):
        """Editing build doctrine_role after slot generation does NOT affect frozen op slots."""
        owner, ws, build, comp = self._setup_frozen("dr-bsi-ops")
        op = make_operation(ws["id"])

        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )

        # Edit build doctrine_role
        use_cases.update_albion_build(
            guild_workspace_id=ws["id"],
            build_id=build["id"],
            actor_user_id=owner["id"],
            name=build["name"],
            role=build["role"],
            weapon_name=build["weapon_name"],
            doctrine_role="MUTATED AFTER GENERATION",
        )

        # Operation slots must still carry the original frozen value
        with database.transaction() as db:
            op_slots = repositories.get_operation_slots(db, op["id"], ws["id"])
        slot_1 = next(s for s in op_slots if s["slot_index"] == 1)
        assert slot_1["doctrine_role"] == "Engage"


# ---------------------------------------------------------------------------
# Group 6 — Composition create / update propagation
# ---------------------------------------------------------------------------

class TestCompositionDoctrineRolePropagation:
    def test_create_composition_with_manual_doctrine_role(self):
        """Manually-typed doctrine_role (no build FK) persists in slot template."""
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="comp-dr-manual")

        slots = [
            {
                "party_number": 1, "slot_index": 1,
                "role": "Tank", "build_name": "1H Mace",
                "doctrine_role": "Main Caller",
                "priority": "core",
            }
        ] + [
            {
                "party_number": 1, "slot_index": i,
                "role": r, "build_name": b,
                "priority": "normal",
            }
            for i, (r, b) in enumerate(
                [("Healer", "Hallowfall"), ("DPS", "Daggers"),
                 ("Support", "Locus"), ("DPS", "Bow")],
                start=2,
            )
        ]
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Doctrine Manual Comp",
            description=None,
            slots=slots,
        )

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])
        slot_1 = next(t for t in templates if t["slot_index"] == 1)
        assert slot_1["doctrine_role"] == "Main Caller"

    def test_update_composition_slots_preserves_doctrine_role(self):
        """update_composition_slots round-trips doctrine_role correctly."""
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="comp-dr-update")
        comp = make_composition(ws["id"])

        new_slots = [
            {
                "party_number": 1, "slot_index": i, "role": r, "build_name": b,
                "doctrine_role": dr,
                "priority": "normal",
            }
            for i, (r, b, dr) in enumerate(
                [
                    ("Tank", "1H Mace", "Engage"),
                    ("Healer", "Hallowfall", "Backline Heal"),
                    ("DPS", "Daggers", "Debuff"),
                    ("Support", "Locus", "Utility"),
                    ("DPS", "Bow", None),
                ],
                start=1,
            )
        ]
        use_cases.update_composition_slots(
            guild_workspace_id=ws["id"],
            composition_id=comp["id"],
            actor_user_id=owner["id"],
            slots=new_slots,
        )

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])

        dr_map = {t["slot_index"]: t["doctrine_role"] for t in templates}
        assert dr_map[1] == "Engage"
        assert dr_map[2] == "Backline Heal"
        assert dr_map[3] == "Debuff"
        assert dr_map[4] == "Utility"
        assert dr_map[5] is None


# ---------------------------------------------------------------------------
# Group 7 — Tactical summaries remain role_family-based
# ---------------------------------------------------------------------------

class TestTacticalSummaryStillRoleFamilyBased:
    """doctrine_role must NOT appear in tactical summary keys or integrity hints."""

    def _make_parties(self, doctrine_roles):
        slots = [
            {
                "party_number": 1,
                "slot_index": i + 1,
                "role": r,
                "build_name": b,
                "weapon_name": None,
                "doctrine_role": dr,
                "priority": "normal",
            }
            for i, (r, b, dr) in enumerate(doctrine_roles)
        ]
        parties = tactical.build_parties(slots)
        return parties

    def test_comp_summary_role_tally_is_role_family(self):
        parties = self._make_parties([
            ("Tank", "1H Mace", "Engage"),
            ("Healer", "Hallowfall", "Backline Heal"),
            ("DPS", "Daggers", "Debuff"),
            ("Support", "Locus", "Utility"),
            ("DPS", "Bow", "Soak"),
        ])
        _, comp_summary = tactical.derive_tactical_summaries(
            parties, assigned_map={}, track_assignments=False
        )
        tally = comp_summary["tally"]
        # Keys must be role_family names, not doctrine_role values
        assert "tank" in tally or "healer" in tally or "dps" in tally
        assert "Engage" not in tally
        assert "Backline Heal" not in tally

    def test_integrity_warnings_mention_role_family_not_doctrine(self):
        parties = self._make_parties([
            ("Tank", "", "Engage"),     # open slot
            ("Healer", "Hallowfall", None),
            ("DPS", "Daggers", None),
            ("Support", "Locus", None),
            ("DPS", "Bow", None),
        ])
        _, comp_summary = tactical.derive_tactical_summaries(
            parties, assigned_map={}, track_assignments=False
        )
        warnings = tactical.derive_composition_integrity(parties, comp_summary, {})
        # No warning should mention a doctrine_role value
        for w in warnings:
            assert "Engage" not in w.get("message", "")


# ---------------------------------------------------------------------------
# Group 8 — Route: build create / edit with doctrine_role
# ---------------------------------------------------------------------------

class TestDoctrineRoleRoutes:
    def test_new_build_form_shows_doctrine_role_input(self):
        client, owner, ws = _make_setup(slug="route-dr-new")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/new")
        assert resp.status_code == 200
        assert 'name="doctrine_role"' in resp.text

    def test_edit_build_form_shows_doctrine_role_input(self):
        client, owner, ws = _make_setup(slug="route-dr-edit")
        build = _create_build(ws["id"], owner["id"], doctrine_role="Soak")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}/edit")
        assert resp.status_code == 200
        assert 'name="doctrine_role"' in resp.text
        assert "Soak" in resp.text

    def test_create_build_post_persists_doctrine_role(self):
        client, owner, ws = _make_setup(slug="route-dr-post")
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "name": "Occult",
                "role": "Support",
                "weapon_name": "Occult Staff",
                "doctrine_role": "Beam Spike",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, ws["id"])
        assert any(b["doctrine_role"] == "Beam Spike" for b in builds)

    def test_update_build_post_updates_doctrine_role(self):
        client, owner, ws = _make_setup(slug="route-dr-put")
        build = _create_build(ws["id"], owner["id"])

        resp = client.post(
            f"/workspaces/{ws['slug']}/builds/{build['id']}",
            data={
                "name": build["name"],
                "role": build["role"],
                "weapon_name": build["weapon_name"],
                "doctrine_role": "Support Heal",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

        with database.transaction() as db:
            updated = repositories.get_albion_build(db, build["id"], ws["id"])
        assert updated["doctrine_role"] == "Support Heal"

    def test_build_detail_renders_doctrine_role(self):
        client, owner, ws = _make_setup(slug="route-dr-detail")
        build = _create_build(ws["id"], owner["id"], doctrine_role="Peel / Stopper")
        resp = client.get(f"/workspaces/{ws['slug']}/builds/{build['id']}")
        assert resp.status_code == 200
        assert "Peel / Stopper" in resp.text


# ---------------------------------------------------------------------------
# Group 9 — Composition templates: doctrine_role renders as primary tier
# ---------------------------------------------------------------------------

class TestDoctrineRoleCompositionRendering:
    def _setup_comp_with_doctrine(self, slug: str):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug=slug)
        client = TestClient(app)
        client.post("/login", data={"display_name": owner["display_name"], "next": "/"}, follow_redirects=True)

        slots = [
            {
                "party_number": 1, "slot_index": i, "role": r, "build_name": b,
                "doctrine_role": dr, "priority": "normal",
            }
            for i, (r, b, dr) in enumerate(
                [
                    ("Tank", "1H Mace", "Main Caller"),
                    ("Healer", "Hallowfall", "Backline Heal"),
                    ("DPS", "Daggers", "Debuff"),
                    ("Support", "Locus", None),
                    ("DPS", "Bow", None),
                ],
                start=1,
            )
        ]
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Doctrine Render Test",
            description=None,
            slots=slots,
        )
        return client, ws, comp

    def test_composition_detail_renders_doctrine_role(self):
        client, ws, comp = self._setup_comp_with_doctrine("rend-dr-detail")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        assert "Main Caller" in resp.text
        assert "Backline Heal" in resp.text

    def test_composition_detail_slot_card_has_doctrine_role_class(self):
        client, ws, comp = self._setup_comp_with_doctrine("rend-dr-cls")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert "slot-card__doctrine-role" in resp.text

    def test_composition_edit_renders_doctrine_role_input(self):
        client, ws, comp = self._setup_comp_with_doctrine("rend-dr-edit")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}/edit")
        assert resp.status_code == 200
        assert 'name="doctrine_role"' in resp.text
        assert "Main Caller" in resp.text

    def test_composition_detail_role_family_still_visible(self):
        """role_family (Tank, Healer…) must still appear even when doctrine_role is set."""
        client, ws, comp = self._setup_comp_with_doctrine("rend-dr-rf")
        resp = client.get(f"/workspaces/{ws['slug']}/compositions/{comp['id']}")
        assert resp.status_code == 200
        # Role names still rendered in slot-card__role elements
        assert "Tank" in resp.text
        assert "Healer" in resp.text


# ---------------------------------------------------------------------------
# Group 10 — Nullable / blank semantics
# ---------------------------------------------------------------------------

class TestDoctrineRoleNullableSemantics:
    def test_omitting_doctrine_role_stores_null_in_template(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="null-dr")
        comp = make_composition(ws["id"])

        with database.transaction() as db:
            templates = repositories.get_composition_slot_templates(db, comp["id"], ws["id"])

        for t in templates:
            assert t["doctrine_role"] is None

    def test_omitting_doctrine_role_stores_null_in_op_slots(self):
        owner = make_user()
        ws = make_workspace(owner_user_id=owner["id"], slug="null-dr-ops")
        comp = make_composition(ws["id"])
        op = make_operation(ws["id"])

        use_cases.attach_operation_plan(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
            albion_composition_id=comp["id"],
        )
        use_cases.generate_operation_slots(
            guild_workspace_id=ws["id"],
            guild_operation_id=op["id"],
        )

        with database.transaction() as db:
            op_slots = repositories.get_operation_slots(db, op["id"], ws["id"])

        for s in op_slots:
            assert s["doctrine_role"] is None

    def test_blank_doctrine_role_post_stores_null(self):
        client, owner, ws = _make_setup(slug="blank-dr")
        resp = client.post(
            f"/workspaces/{ws['slug']}/builds",
            data={
                "name": "Plain Build",
                "role": "Tank",
                "weapon_name": "1H Mace",
                "doctrine_role": "",   # blank → should store NULL
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

        with database.transaction() as db:
            builds = repositories.get_albion_builds(db, ws["id"])
        assert any(b["name"] == "Plain Build" and b["doctrine_role"] is None for b in builds)
