"""
Phase 6 — Slot template model regression harness.

These tests protect the canonical slot template → operation slot data flow.
They establish a regression baseline that must continue to pass through any
future model extension (cloning, versioning, preset library, etc.).

Canonical flow:
  composition_slot_templates
  → generate_operation_slots (1:1 frozen copy)
  → operation_slots (tactical planner source)

Both the composition preview and the live planner pass their slot rows through
tactical.build_parties(), so grouping logic is shared and cannot diverge.

Tests are integration-level (use_cases + in-memory DB via conftest fixtures).
"""

from __future__ import annotations

import pytest

from app import database, repositories
from app import tactical
from app.application import use_cases
from tests.conftest import make_composition, make_operation, make_workspace, publish_operation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws():
    return make_workspace(slug="model-harness")


def _make_and_generate(ws, slots):
    """Create a composition, attach it to a new operation, generate slots.

    Returns (comp, op, operation_slots, template_rows).
    """
    comp = use_cases.create_albion_composition(
        guild_workspace_id=ws["id"],
        name="Harness Comp",
        description=None,
        slots=slots,
    )
    op = make_operation(ws["id"])
    use_cases.attach_operation_plan(ws["id"], op["id"], comp["id"])
    op_slots = use_cases.generate_operation_slots(ws["id"], op["id"])
    with database.transaction() as db:
        template_rows = repositories.get_composition_slot_templates(
            db, comp["id"], ws["id"]
        )
    return comp, op, op_slots, template_rows


# ---------------------------------------------------------------------------
# 1. Count invariant
# ---------------------------------------------------------------------------

class TestSlotCountInvariant:
    """Operation slot count must always equal template count."""

    def test_single_slot_generates_one_operation_slot(self, ws):
        _, _, op_slots, templates = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "Healer",
             "build_name": "Hallowfall", "priority": "core"},
        ])
        assert len(op_slots) == len(templates) == 1

    def test_five_slots_generates_five_operation_slots(self, ws):
        slot_defs = [
            {"party_number": 1, "slot_index": i, "role": "DPS",
             "build_name": f"Build{i}", "priority": "normal"}
            for i in range(1, 6)
        ]
        _, _, op_slots, templates = _make_and_generate(ws, slot_defs)
        assert len(op_slots) == len(templates) == 5

    def test_multi_party_slot_count_matches_template_count(self, ws):
        slot_defs = [
            {"party_number": p, "slot_index": s, "role": "DPS",
             "build_name": f"b{p}{s}", "priority": "normal"}
            for p in range(1, 4)
            for s in range(1, 6)
        ]  # 3 parties × 5 slots = 15
        _, _, op_slots, templates = _make_and_generate(ws, slot_defs)
        assert len(op_slots) == len(templates) == 15


# ---------------------------------------------------------------------------
# 2. Field propagation — every tactical field must copy 1:1
# ---------------------------------------------------------------------------

class TestFieldPropagation:
    """Every tactical field in composition_slot_templates must arrive
    unchanged in the generated operation_slot row."""

    @pytest.fixture()
    def generated(self, ws):
        comp, op, op_slots, templates = _make_and_generate(ws, [
            {
                "party_number": 2,
                "slot_index":   3,
                "role":         "Support",
                "build_name":   "Locus of Power",
                "weapon_name":  "Locus",
                "priority":     "core",
            }
        ])
        return op_slots[0], templates[0]

    def test_party_number_propagates(self, generated):
        slot, tmpl = generated
        assert slot["party_number"] == tmpl["party_number"] == 2

    def test_slot_index_propagates(self, generated):
        slot, tmpl = generated
        assert slot["slot_index"] == tmpl["slot_index"] == 3

    def test_role_propagates(self, generated):
        slot, tmpl = generated
        assert slot["role"] == tmpl["role"] == "Support"

    def test_build_name_propagates(self, generated):
        slot, tmpl = generated
        assert slot["build_name"] == tmpl["build_name"] == "Locus of Power"

    def test_weapon_name_propagates(self, generated):
        slot, tmpl = generated
        assert slot["weapon_name"] == tmpl["weapon_name"] == "Locus"

    def test_priority_propagates(self, generated):
        slot, tmpl = generated
        assert slot["priority"] == tmpl["priority"] == "core"


class TestNullableWeaponName:
    """weapon_name is nullable — both None and a value must survive the copy."""

    def test_none_weapon_name_preserved(self, ws):
        _, _, op_slots, _ = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Sword", "weapon_name": None, "priority": "normal"},
        ])
        assert op_slots[0]["weapon_name"] is None

    def test_string_weapon_name_preserved(self, ws):
        _, _, op_slots, _ = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "Healer",
             "build_name": "Hallowfall", "weapon_name": "HWF", "priority": "core"},
        ])
        assert op_slots[0]["weapon_name"] == "HWF"


class TestPriorityVariants:
    """Both priority values must survive template → operation slot copy."""

    def test_core_priority_preserved(self, ws):
        _, _, op_slots, _ = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Claymore", "priority": "core"},
        ])
        assert op_slots[0]["priority"] == "core"

    def test_normal_priority_preserved(self, ws):
        _, _, op_slots, _ = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "DPS",
             "build_name": "Bow", "priority": "normal"},
        ])
        assert op_slots[0]["priority"] == "normal"

    def test_mixed_priority_slots_both_preserved(self, ws):
        _, _, op_slots, _ = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "A", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "DPS",
             "build_name": "B", "priority": "normal"},
        ])
        priorities = {s["slot_index"]: s["priority"] for s in op_slots}
        assert priorities[1] == "core"
        assert priorities[2] == "normal"


# ---------------------------------------------------------------------------
# 3. Ordering — operation_slots must be returned in party_number, slot_index order
# ---------------------------------------------------------------------------

class TestSlotOrdering:
    """Slot ordering must match the ORDER BY party_number, slot_index guarantee
    that both get_composition_slot_templates and get_operation_slots provide."""

    def test_single_party_slots_in_slot_index_order(self, ws):
        # Insert in reverse order to ensure ORDER BY is doing the work
        _, _, op_slots, templates = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 3, "role": "DPS",
             "build_name": "Axe", "priority": "normal"},
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Sword", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "Holy", "priority": "core"},
        ])
        # Templates must be ordered by slot_index
        assert [t["slot_index"] for t in templates] == [1, 2, 3]
        # Operation slots must also come back ordered
        with database.transaction() as db:
            op_id = op_slots[0]["guild_operation_id"]
            ws_id = op_slots[0]["guild_workspace_id"]
            ordered = repositories.get_operation_slots(db, op_id, ws_id)
        assert [s["slot_index"] for s in ordered] == [1, 2, 3]

    def test_multi_party_slots_in_party_then_slot_order(self, ws):
        slot_defs = [
            {"party_number": 2, "slot_index": 1, "role": "Tank",
             "build_name": "b21", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "DPS",
             "build_name": "b12", "priority": "normal"},
            {"party_number": 1, "slot_index": 1, "role": "Healer",
             "build_name": "b11", "priority": "core"},
            {"party_number": 2, "slot_index": 2, "role": "Support",
             "build_name": "b22", "priority": "normal"},
        ]
        _, _, op_slots, templates = _make_and_generate(ws, slot_defs)
        # Both templates and op_slots must be sorted by (party_number, slot_index)
        assert [(t["party_number"], t["slot_index"]) for t in templates] == [
            (1, 1), (1, 2), (2, 1), (2, 2)
        ]
        with database.transaction() as db:
            op_id = op_slots[0]["guild_operation_id"]
            ws_id = op_slots[0]["guild_workspace_id"]
            ordered = repositories.get_operation_slots(db, op_id, ws_id)
        assert [(s["party_number"], s["slot_index"]) for s in ordered] == [
            (1, 1), (1, 2), (2, 1), (2, 2)
        ]


# ---------------------------------------------------------------------------
# 4. Source tracking — operation_slots must link back to templates
# ---------------------------------------------------------------------------

class TestSourceTracking:
    """operation_slots.source_composition_slot_template_id must reference the
    exact template row that was cloned.  This audit link enables future
    clone/revision lineage without a model change."""

    def test_source_id_matches_template_id(self, ws):
        comp, op, op_slots, templates = _make_and_generate(ws, [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Sword", "priority": "core"},
        ])
        assert op_slots[0]["source_composition_slot_template_id"] == templates[0]["id"]

    def test_all_slots_have_source_ids(self, ws):
        slot_defs = [
            {"party_number": 1, "slot_index": i, "role": "DPS",
             "build_name": f"b{i}", "priority": "normal"}
            for i in range(1, 4)
        ]
        _, _, op_slots, templates = _make_and_generate(ws, slot_defs)
        template_ids = {t["id"] for t in templates}
        for slot in op_slots:
            assert slot["source_composition_slot_template_id"] in template_ids

    def test_source_ids_are_unique_per_slot(self, ws):
        """Each operation slot must link to a distinct template (no fan-out)."""
        slot_defs = [
            {"party_number": 1, "slot_index": i, "role": "DPS",
             "build_name": f"b{i}", "priority": "normal"}
            for i in range(1, 4)
        ]
        _, _, op_slots, _ = _make_and_generate(ws, slot_defs)
        source_ids = [s["source_composition_slot_template_id"] for s in op_slots]
        assert len(source_ids) == len(set(source_ids)), "source IDs must be distinct"


# ---------------------------------------------------------------------------
# 5. Preview / planner grouping consistency
# ---------------------------------------------------------------------------

class TestPreviewPlannerGroupingConsistency:
    """build_parties() is shared by both the composition preview and the live
    planner.  Given the same tactical fields, both paths must produce
    structurally identical party groupings.

    This is the cross-source consistency guarantee established in Phase 2
    (TestBuildParties in test_tactical_logic.py) validated here at the
    integration level with real DB rows.
    """

    def test_preview_and_planner_produce_same_party_keys(self, ws):
        slot_defs = [
            {"party_number": p, "slot_index": s, "role": role,
             "build_name": f"b{p}{s}", "priority": "core"}
            for p in range(1, 4)
            for s, role in enumerate(["Tank", "Healer", "DPS", "Support", "DPS"], 1)
        ]
        _, op, op_slots, templates = _make_and_generate(ws, slot_defs)

        preview_parties = tactical.build_parties(templates)
        planner_parties = tactical.build_parties(op_slots)

        assert set(preview_parties.keys()) == set(planner_parties.keys()), (
            "preview and planner must group into the same set of party numbers"
        )

    def test_preview_and_planner_produce_same_slot_counts_per_party(self, ws):
        slot_defs = [
            {"party_number": p, "slot_index": s, "role": "DPS",
             "build_name": f"b{p}{s}", "priority": "normal"}
            for p in (1, 2, 3)
            for s in (1, 2, 3, 4, 5)
        ]
        _, op, op_slots, templates = _make_and_generate(ws, slot_defs)

        preview_parties = tactical.build_parties(templates)
        planner_parties = tactical.build_parties(op_slots)

        for pn in preview_parties:
            assert len(preview_parties[pn]) == len(planner_parties[pn]), (
                f"Party {pn}: preview has {len(preview_parties[pn])} slots "
                f"but planner has {len(planner_parties[pn])}"
            )

    def test_preview_and_planner_role_families_match(self, ws):
        """role_family annotation applied to templates must match annotation
        applied to operation slots for the same role strings."""
        slot_defs = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",
             "build_name": "Sword", "priority": "core"},
            {"party_number": 1, "slot_index": 2, "role": "Healer",
             "build_name": "Holy", "priority": "core"},
            {"party_number": 1, "slot_index": 3, "role": "DPS",
             "build_name": "Bow", "priority": "normal"},
        ]
        _, op, op_slots, templates = _make_and_generate(ws, slot_defs)

        preview_parties = tactical.build_parties(templates)
        planner_parties = tactical.build_parties(op_slots)

        preview_families = [s["role_family"] for s in preview_parties[1]]
        planner_families = [s["role_family"] for s in planner_parties[1]]
        assert preview_families == planner_families, (
            "role_family classification must be identical for templates and operation slots"
        )


# ---------------------------------------------------------------------------
# 6. Empty composition safety
# ---------------------------------------------------------------------------

class TestEmptyCompositionSafety:
    """Zero-slot compositions are valid named shells; per-slot rules still enforced."""

    def test_create_zero_slot_composition_is_allowed(self, ws):
        """create_albion_composition with an empty slot list succeeds.

        A zero-slot composition is a valid named shell — slots may be added
        later via update_composition_slots.  The old "must have at least one
        slot template" gate was removed in Slice 5.
        """
        comp = use_cases.create_albion_composition(
            guild_workspace_id=ws["id"],
            name="Empty Comp",
            description=None,
            slots=[],
        )
        assert comp["id"]  # composition was created
