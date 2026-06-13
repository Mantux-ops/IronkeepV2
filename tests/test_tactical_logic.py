"""Unit tests for app.tactical — canonical tactical interpretation logic.

Covers:
- role_family() classification
- derive_tactical_summaries() tally, gap detection, and hint generation
- track_assignments flag (operation mode vs. template/preview mode)
- Edge cases: empty parties, None roles, malformed slots, multi-party comps
"""
import pytest

from app.tactical import (
    ROLE_FAMILIES,
    build_parties,
    derive_composition_integrity,
    derive_tactical_summaries,
    role_family,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slot(id, role, build_name=None, weapon_name=None):
    """Build a minimal slot dict matching the expected interface."""
    return {
        "id":           id,
        "role":         role,
        "build_name":   build_name,
        "weapon_name":  weapon_name,
    }


# ---------------------------------------------------------------------------
# role_family — classification
# ---------------------------------------------------------------------------

class TestRoleFamily:

    def test_tank_keywords(self):
        assert role_family("Tank")      == "tank"
        assert role_family("Frontline") == "tank"
        assert role_family("Brawler")   == "tank"
        assert role_family("TANK")      == "tank"
        assert role_family("front")     == "tank"

    def test_healer_keywords(self):
        assert role_family("Healer")       == "healer"
        assert role_family("Main Healer")  == "healer"
        assert role_family("HEALER")       == "healer"
        assert role_family("healer 1")     == "healer"

    def test_healer_not_support(self):
        """Healer is a distinct family from Support — must never be classified as support."""
        assert role_family("Healer")  != "support"
        assert role_family("HEALER")  != "support"
        assert role_family("healer")  != "support"

    def test_support_keywords(self):
        assert role_family("Support")       == "support"
        assert role_family("Utility")       == "support"
        assert role_family("util")          == "support"

    def test_support_not_healer(self):
        """Support is a distinct family from Healer — 'SUPPORT' must never be classified as healer."""
        assert role_family("Support")  != "healer"
        assert role_family("SUPPORT")  != "healer"
        assert role_family("support")  != "healer"

    def test_doctrine_role_names_healer(self):
        """Ironkeep healer doctrine sub-roles: Main Heal, Backline Heal, Support Heal.
        All contain 'heal' and must classify as healer, not support."""
        assert role_family("Main Heal")     == "healer"
        assert role_family("Backline Heal") == "healer"
        assert role_family("Support Heal")  == "healer"   # 'heal' checked before 'support'

    def test_doctrine_role_names_support(self):
        """Ironkeep support doctrine sub-roles: Debuff, Utility, Soak, Peel.
        None contain 'heal' — must classify as support (or default for Soak/Peel)."""
        assert role_family("Utility")  == "support"
        assert role_family("Debuff")   == "default"   # no keyword match → default
        assert role_family("Soak")     == "default"

    def test_dps_keywords(self):
        assert role_family("DPS")           == "dps"
        assert role_family("Melee DPS")     == "dps"
        assert role_family("Caller")        == "dps"
        assert role_family("Engage")        == "dps"
        assert role_family("caller dps")    == "dps"

    def test_ranged_keywords(self):
        assert role_family("Ranged")        == "ranged"
        assert role_family("Warbow")        == "ranged"
        assert role_family("Frost Mage")    == "ranged"
        assert role_family("Frost")         == "ranged"
        assert role_family("Mage")          == "ranged"

    def test_default_fallback(self):
        assert role_family("Scout")   == "default"
        assert role_family("Reserve") == "default"
        assert role_family("Flex")    == "default"
        assert role_family("")        == "default"

    def test_none_input_returns_default(self):
        assert role_family(None) == "default"

    def test_priority_ordering_tank_before_healer(self):
        # "frontline heal" contains both "front" (tank) and "heal" (healer).
        # tank is checked first — must win.
        assert role_family("frontline heal") == "tank"

    def test_case_insensitive(self):
        assert role_family("FRONTLINE") == "tank"
        assert role_family("HEALER")    == "healer"
        assert role_family("SUPPORT")   == "support"
        assert role_family("RANGED")    == "ranged"

    def test_all_families_reachable(self):
        """Every family except default must be reachable via some role string."""
        reachable = {
            role_family("Tank"),
            role_family("Healer"),
            role_family("DPS"),
            role_family("Support"),
            role_family("Ranged"),
            role_family("Scout"),  # default
        }
        assert reachable == set(ROLE_FAMILIES)

    def test_role_families_constant_has_six_entries(self):
        assert len(ROLE_FAMILIES) == 6
        assert "default" in ROLE_FAMILIES


# ---------------------------------------------------------------------------
# derive_tactical_summaries — tally and gap detection
# ---------------------------------------------------------------------------

class TestDeriveTacticalSummaries:

    def test_empty_parties_returns_empty_summaries(self):
        ps, cs = derive_tactical_summaries({}, {})
        assert ps == {}
        assert cs["total"]      == 0
        assert cs["built"]      == 0
        assert cs["assigned"]   == 0
        assert cs["hint"]       is None
        assert cs["hint_state"] == "neutral"

    def test_single_party_all_built_all_assigned(self):
        parties = {1: [
            _slot("s1", "Tank",   build_name="Sword"),
            _slot("s2", "Healer", build_name="Nature Staff"),
            _slot("s3", "DPS",    weapon_name="Warbow"),
        ]}
        assigned_map = {"s1": {}, "s2": {}, "s3": {}}
        ps, cs = derive_tactical_summaries(parties, assigned_map)

        assert ps[1]["tally"]["tank"]   == 1
        assert ps[1]["tally"]["healer"] == 1
        assert ps[1]["tally"]["dps"]    == 1
        assert ps[1]["built"]           == 3
        assert ps[1]["assigned"]        == 3
        assert ps[1]["total"]           == 3
        assert ps[1]["gaps"]            == []

        assert cs["hint"]       == "All slots built and assigned"
        assert cs["hint_state"] == "ok"

    def test_missing_healer_generates_critical_gap(self):
        parties = {1: [
            _slot("s1", "Tank", build_name="Sword"),
            _slot("s2", "DPS",  build_name="Bow"),
        ]}
        ps, _ = derive_tactical_summaries(parties, {})
        gap_severities_texts = ps[1]["gaps"]
        assert any(
            sev == "critical" and "healer" in text.lower()
            for sev, text in gap_severities_texts
        )

    def test_missing_tank_generates_critical_gap(self):
        parties = {1: [
            _slot("s1", "Healer", build_name="Holy"),
            _slot("s2", "DPS",    build_name="Bow"),
        ]}
        ps, _ = derive_tactical_summaries(parties, {})
        assert any(
            sev == "critical" and "tank" in text.lower()
            for sev, text in ps[1]["gaps"]
        )

    def test_no_builds_generates_warn_gap(self):
        parties = {1: [
            _slot("s1", "Tank"),
            _slot("s2", "Healer"),
            _slot("s3", "DPS"),
        ]}
        ps, cs = derive_tactical_summaries(parties, {})
        gap_texts = [text for _, text in ps[1]["gaps"]]
        assert any("open" in t.lower() for t in gap_texts)
        assert cs["hint_state"] == "warn"

    def test_single_missing_build_singular_label(self):
        parties = {1: [
            _slot("s1", "Tank", build_name="Sword"),
            _slot("s2", "Healer"),  # no build
        ]}
        ps, _ = derive_tactical_summaries(parties, {})
        gap_texts = [text for _, text in ps[1]["gaps"]]
        assert "1 open" in gap_texts

    def test_multiple_missing_builds_plural_label(self):
        parties = {1: [
            _slot("s1", "Tank"),
            _slot("s2", "Healer"),
            _slot("s3", "DPS"),
        ]}
        ps, _ = derive_tactical_summaries(parties, {})
        gap_texts = [text for _, text in ps[1]["gaps"]]
        assert "3 open" in gap_texts

    def test_weapon_name_alone_counts_as_built(self):
        parties = {1: [_slot("s1", "DPS", weapon_name="Warbow")]}
        ps, _ = derive_tactical_summaries(parties, {})
        assert ps[1]["built"] == 1

    def test_both_build_and_weapon_counts_as_one_built(self):
        parties = {1: [_slot("s1", "DPS", build_name="Ranged DPS", weapon_name="Warbow")]}
        ps, _ = derive_tactical_summaries(parties, {})
        assert ps[1]["built"] == 1

    def test_empty_party_no_gaps_no_errors(self):
        """A party with zero slots must not generate any gaps."""
        parties = {1: []}
        ps, cs = derive_tactical_summaries(parties, {})
        assert ps[1]["gaps"]  == []
        assert ps[1]["total"] == 0
        assert cs["total"]    == 0

    def test_multi_party_comp_totals(self):
        parties = {
            1: [
                _slot("s1", "Tank",   build_name="Sword"),
                _slot("s2", "Healer", build_name="Holy"),
            ],
            2: [
                _slot("s3", "DPS",     build_name="Bow"),
                _slot("s4", "Support"),  # no build
            ],
        }
        ps, cs = derive_tactical_summaries(parties, {})
        assert cs["total"]           == 4
        assert cs["built"]           == 3
        assert cs["tally"]["tank"]   == 1
        assert cs["tally"]["healer"] == 1
        assert cs["tally"]["dps"]    == 1
        assert cs["tally"]["support"] == 1

    def test_healer_and_support_tallied_separately(self):
        """Core Ironkeep invariant: Healer and Support are distinct role families.
        A Healer slot must NOT count toward Support tally and vice versa."""
        parties = {1: [
            _slot("h1", "Healer",  build_name="Hallowfall"),
            _slot("h2", "HEALER",  build_name="Holy Staff"),
            _slot("s1", "Support", build_name="Incubus Mace"),
            _slot("s2", "SUPPORT", build_name="Grovekeeper"),
        ]}
        ps, cs = derive_tactical_summaries(parties, {})
        assert cs["tally"]["healer"]  == 2
        assert cs["tally"]["support"] == 2

    def test_doctrine_support_heal_role_counts_as_healer(self):
        """Ironkeep doctrine sub-role 'Support Heal' contains 'Heal'.
        When used as the slot ROLE field it must classify as healer, not support."""
        parties = {1: [_slot("x1", "Support Heal", build_name="Hallowfall")]}
        ps, cs = derive_tactical_summaries(parties, {})
        assert cs["tally"]["healer"]  == 1
        assert cs["tally"]["support"] == 0

    def test_healer_slot_does_not_fire_no_healer_gap(self):
        """A party with a Healer slot must NOT fire the 'No healer' gap warning."""
        parties = {1: [
            _slot("t1", "Tank",   build_name="Tombstone"),
            _slot("h1", "Healer", build_name="Hallowfall"),
        ]}
        ps, _ = derive_tactical_summaries(parties, {})
        gap_codes = [text for _, text in ps[1]["gaps"]]
        assert "No healer" not in gap_codes

    def test_support_slot_does_fire_no_healer_gap(self):
        """A party with only Support slots (not Healer) MUST fire 'No healer' gap.
        Support ≠ Healer — the gap check must not conflate them."""
        parties = {1: [
            _slot("t1", "Tank",    build_name="Tombstone"),
            _slot("s1", "Support", build_name="Incubus Mace"),
        ]}
        ps, _ = derive_tactical_summaries(parties, {})
        gap_texts = [text for _, text in ps[1]["gaps"]]
        assert "No healer" in gap_texts

    def test_assignment_count_tracked(self):
        parties = {1: [
            _slot("s1", "Tank",   build_name="Sword"),
            _slot("s2", "Healer", build_name="Holy"),
        ]}
        assigned_map = {"s1": {"display_name": "Alice"}}
        ps, cs = derive_tactical_summaries(parties, assigned_map)
        assert ps[1]["assigned"] == 1
        assert cs["assigned"]    == 1

    def test_unassigned_hint_when_some_unassigned(self):
        parties = {1: [
            _slot("s1", "Tank",   build_name="Sword"),
            _slot("s2", "Healer", build_name="Holy"),
        ]}
        assigned_map = {"s1": {}}
        _, cs = derive_tactical_summaries(parties, assigned_map)
        assert "unassigned" in (cs["hint"] or "")
        assert cs["hint_state"] == "warn"

    def test_hint_both_missing_builds_and_unassigned(self):
        parties = {1: [
            _slot("s1", "Tank"),          # no build
            _slot("s2", "Healer"),        # no build
        ]}
        _, cs = derive_tactical_summaries(parties, {})
        # unbuilt=2, unassigned=2 — hint mentions both open slots and unassigned
        assert "open" in (cs["hint"] or "")
        assert "unassigned" in (cs["hint"] or "")


# ---------------------------------------------------------------------------
# derive_tactical_summaries — track_assignments=False (template mode)
# ---------------------------------------------------------------------------

class TestDeriveTacticalSummariesTemplateMode:

    def test_all_built_hint_is_plain_not_assignment_aware(self):
        parties = {1: [
            _slot("s1", "Tank",   build_name="Sword"),
            _slot("s2", "Healer", weapon_name="Holy"),
        ]}
        ps, cs = derive_tactical_summaries(parties, {}, track_assignments=False)
        # With track_assignments=False, hint must not mention players/assignment.
        assert cs["hint"]       == "All slots built"
        assert cs["hint_state"] == "ok"
        # assigned count is still 0 (empty map)
        assert ps[1]["assigned"] == 0

    def test_missing_builds_hint_template_mode(self):
        parties = {1: [
            _slot("s1", "Tank", build_name="Sword"),
            _slot("s2", "Healer"),  # no build
        ]}
        _, cs = derive_tactical_summaries(parties, {}, track_assignments=False)
        assert "open" in (cs["hint"] or "")
        assert cs["hint_state"] == "warn"
        # Must NOT mention "unassigned"
        assert "unassigned" not in (cs["hint"] or "")

    def test_empty_comp_template_mode(self):
        _, cs = derive_tactical_summaries({}, {}, track_assignments=False)
        assert cs["hint"]       is None
        assert cs["hint_state"] == "neutral"

    def test_plural_missing_builds_template_mode(self):
        parties = {1: [_slot("s1", "Tank"), _slot("s2", "Healer"), _slot("s3", "DPS")]}
        _, cs = derive_tactical_summaries(parties, {}, track_assignments=False)
        assert cs["hint"] == "3 open slots"

    def test_singular_missing_build_template_mode(self):
        parties = {1: [_slot("s1", "Tank", build_name="Sword"), _slot("s2", "Healer")]}
        _, cs = derive_tactical_summaries(parties, {}, track_assignments=False)
        assert cs["hint"] == "1 open slot"

    def test_gap_detection_unchanged_in_template_mode(self):
        """Gap detection (missing healer/tank/builds) is independent of track_assignments."""
        parties = {1: [_slot("s1", "DPS", build_name="Bow"), _slot("s2", "DPS", build_name="Bow2")]}
        ps, _ = derive_tactical_summaries(parties, {}, track_assignments=False)
        gap_severities = {sev for sev, _ in ps[1]["gaps"]}
        # Both healer and tank are missing → two critical gaps
        assert "critical" in gap_severities
        assert ps[1]["tally"]["tank"]   == 0
        assert ps[1]["tally"]["healer"] == 0


# ---------------------------------------------------------------------------
# ROLE_FAMILIES constant
# ---------------------------------------------------------------------------

class TestRoleFamiliesConstant:

    def test_is_tuple(self):
        assert isinstance(ROLE_FAMILIES, tuple)

    def test_contains_all_expected_families(self):
        expected = {"tank", "healer", "dps", "support", "ranged", "default"}
        assert set(ROLE_FAMILIES) == expected

    def test_no_duplicates(self):
        assert len(ROLE_FAMILIES) == len(set(ROLE_FAMILIES))


# ---------------------------------------------------------------------------
# build_parties — Phase 2 shared synthesis helper
# ---------------------------------------------------------------------------

def _raw_slot(party_number, slot_index, role, build_name=None, weapon_name=None, **extra):
    """Minimal slot row as returned by get_composition_slot_templates /
    get_operation_slots.  Extra kwargs allow injecting any additional fields
    (e.g. 'id', 'priority') without changing the test helper signature."""
    return {
        "party_number": party_number,
        "slot_index":   slot_index,
        "role":         role,
        "build_name":   build_name,
        "weapon_name":  weapon_name,
        **extra,
    }


class TestBuildParties:
    """Tests for build_parties() — the shared party-grouping helper.

    build_parties() is the single canonical path used by both the
    composition detail preview route and the live tactical planner route.
    These tests verify deterministic grouping, ordering, and annotation
    so that a future refactor cannot silently break either surface.
    """

    # ------------------------------------------------------------------
    # Empty input
    # ------------------------------------------------------------------

    def test_empty_input_returns_empty_dict(self):
        assert build_parties([]) == {}

    # ------------------------------------------------------------------
    # Single slot
    # ------------------------------------------------------------------

    def test_single_slot_creates_one_party(self):
        rows = [_raw_slot(1, 1, "Tank", build_name="Sword")]
        parties = build_parties(rows)
        assert list(parties.keys()) == [1]
        assert len(parties[1]) == 1

    def test_single_slot_role_family_annotated(self):
        rows = [_raw_slot(1, 1, "Healer", build_name="Holy")]
        parties = build_parties(rows)
        assert parties[1][0]["role_family"] == "healer"

    def test_single_slot_original_fields_preserved(self):
        rows = [_raw_slot(1, 1, "Tank", build_name="Sword", weapon_name="1H Mace")]
        slot = build_parties(rows)[1][0]
        assert slot["role"]       == "Tank"
        assert slot["build_name"] == "Sword"
        assert slot["weapon_name"]== "1H Mace"

    # ------------------------------------------------------------------
    # Single party, multiple slots
    # ------------------------------------------------------------------

    def test_multi_slot_single_party_grouping(self):
        rows = [
            _raw_slot(1, 1, "Tank"),
            _raw_slot(1, 2, "Healer"),
            _raw_slot(1, 3, "DPS"),
        ]
        parties = build_parties(rows)
        assert list(parties.keys()) == [1]
        assert len(parties[1]) == 3

    def test_slot_ordering_preserved_within_party(self):
        """Slots must appear in input order (slot_index ascending from query)."""
        rows = [
            _raw_slot(1, 1, "Tank"),
            _raw_slot(1, 2, "Healer"),
            _raw_slot(1, 3, "DPS"),
            _raw_slot(1, 4, "Support"),
            _raw_slot(1, 5, "DPS"),
        ]
        parties = build_parties(rows)
        indices = [s["slot_index"] for s in parties[1]]
        assert indices == [1, 2, 3, 4, 5]

    # ------------------------------------------------------------------
    # Multi-party
    # ------------------------------------------------------------------

    def test_multi_party_grouping_correct(self):
        rows = [
            _raw_slot(1, 1, "Tank"),
            _raw_slot(1, 2, "Healer"),
            _raw_slot(2, 1, "DPS"),
            _raw_slot(2, 2, "Support"),
        ]
        parties = build_parties(rows)
        assert set(parties.keys()) == {1, 2}
        assert len(parties[1]) == 2
        assert len(parties[2]) == 2

    def test_party_keys_in_insertion_order(self):
        """Party dict preserves insertion order (ascending party_number from query).
        Templates iterate with | sort, but insertion order is also deterministic."""
        rows = [
            _raw_slot(1, 1, "Tank"),
            _raw_slot(2, 1, "Healer"),
            _raw_slot(3, 1, "DPS"),
        ]
        parties = build_parties(rows)
        assert list(parties.keys()) == [1, 2, 3]

    def test_role_family_annotated_for_all_families(self):
        """Every canonical role family must be reachable via build_parties annotation."""
        rows = [
            _raw_slot(1, 1, "Tank"),
            _raw_slot(1, 2, "Healer"),
            _raw_slot(1, 3, "DPS"),
            _raw_slot(1, 4, "Support"),
            _raw_slot(1, 5, "Ranged"),
            _raw_slot(1, 6, "Scout"),   # → default
        ]
        families = {s["role_family"] for s in build_parties(rows)[1]}
        assert families == {"tank", "healer", "dps", "support", "ranged", "default"}

    # ------------------------------------------------------------------
    # Standard ZvZ composition shapes
    # ------------------------------------------------------------------

    def test_standard_5man_party_structure(self):
        """A standard 5-man party (T/H/D/S/D) produces one party of 5 slots."""
        rows = [
            _raw_slot(1, 1, "Tank",    build_name="1H Mace"),
            _raw_slot(1, 2, "Healer",  build_name="Hallowfall"),
            _raw_slot(1, 3, "DPS",     build_name="Daggers"),
            _raw_slot(1, 4, "Support", build_name="Locus"),
            _raw_slot(1, 5, "DPS",     build_name="Bow"),
        ]
        parties = build_parties(rows)
        assert len(parties) == 1
        assert len(parties[1]) == 5

    def test_standard_20slot_4party_composition(self):
        """A 20-slot ZvZ comp with 4 parties of 5 produces exactly 4 parties."""
        roles = ["Tank", "Healer", "DPS", "Support", "DPS"]
        rows = [
            _raw_slot(p, s, roles[s - 1], build_name=f"build-{p}-{s}")
            for p in range(1, 5)
            for s in range(1, 6)
        ]
        parties = build_parties(rows)
        assert len(parties) == 4
        for p in range(1, 5):
            assert len(parties[p]) == 5, f"Party {p} should have 5 slots"

    def test_large_multi_party_composition(self):
        """A 30-slot comp with 6 parties of 5 is correctly grouped."""
        rows = [
            _raw_slot(p, s, "DPS")
            for p in range(1, 7)
            for s in range(1, 6)
        ]
        parties = build_parties(rows)
        assert len(parties) == 6
        for p in range(1, 7):
            assert len(parties[p]) == 5

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_none_role_annotated_as_default(self):
        rows = [_raw_slot(1, 1, None)]
        parties = build_parties(rows)
        assert parties[1][0]["role_family"] == "default"

    def test_extra_fields_on_slot_are_preserved(self):
        """Fields beyond the minimal set (e.g. 'priority', 'id') pass through."""
        rows = [_raw_slot(1, 1, "Tank", build_name="Sword", id="abc-123", priority="core")]
        slot = build_parties(rows)[1][0]
        assert slot["id"]       == "abc-123"
        assert slot["priority"] == "core"

    # ------------------------------------------------------------------
    # Consistency between preview and planner data sources
    # ------------------------------------------------------------------

    def test_equivalent_inputs_produce_equivalent_party_structure(self):
        """Preview (composition_slot_templates) and planner (operation_slots) carry
        the same party_number / slot_index / role / build_name / weapon_name fields.
        build_parties() must produce structurally identical grouping for both.

        This test guards against future divergence introduced by adding
        source-specific fields to either table.
        """
        # Simulate the shared fields present in both composition_slot_templates
        # and operation_slots for a 2-party, 2-slot-per-party composition.
        shared_fields = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Sword",     "weapon_name": None},
            {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall","weapon_name": None},
            {"party_number": 2, "slot_index": 1, "role": "DPS",    "build_name": None,         "weapon_name": "Warbow"},
            {"party_number": 2, "slot_index": 2, "role": "Support","build_name": "Locus",      "weapon_name": None},
        ]

        # Add source-specific extra fields (as each table would have them).
        comp_template_rows = [
            {**row, "id": f"tpl-{i}", "albion_composition_id": "comp-1",
             "guild_workspace_id": "ws-1", "priority": "core"}
            for i, row in enumerate(shared_fields)
        ]
        operation_slot_rows = [
            {**row, "id": f"opslot-{i}", "guild_operation_id": "op-1",
             "guild_workspace_id": "ws-1", "priority": "core"}
            for i, row in enumerate(shared_fields)
        ]

        comp_parties  = build_parties(comp_template_rows)
        planner_parties = build_parties(operation_slot_rows)

        # Party structure must be equivalent on shared keys.
        assert set(comp_parties.keys()) == set(planner_parties.keys())
        for party_num in comp_parties:
            cp = comp_parties[party_num]
            pp = planner_parties[party_num]
            assert len(cp) == len(pp)
            for cs, ps in zip(cp, pp):
                assert cs["party_number"] == ps["party_number"]
                assert cs["slot_index"]   == ps["slot_index"]
                assert cs["role"]         == ps["role"]
                assert cs["build_name"]   == ps["build_name"]
                assert cs["weapon_name"]  == ps["weapon_name"]
                assert cs["role_family"]  == ps["role_family"]

    def test_equivalent_tactical_summaries_from_both_sources(self):
        """derive_tactical_summaries() on equivalent build_parties() output must
        produce identical tally, built, and gap results — regardless of source table.

        This test guards the Phase 2 invariant: preview and planner surfaces
        derive tactical summaries from the same shared logic, producing
        identical tactical understanding of an equivalent composition.
        """
        shared_rows = [
            {"party_number": 1, "slot_index": 1, "role": "Tank",   "build_name": "Sword",    "weapon_name": None},
            {"party_number": 1, "slot_index": 2, "role": "Healer", "build_name": "Hallowfall","weapon_name": None},
            {"party_number": 1, "slot_index": 3, "role": "DPS",    "build_name": None,        "weapon_name": None},
        ]
        comp_rows = [{**r, "id": f"t{i}", "albion_composition_id": "c1"} for i, r in enumerate(shared_rows)]
        op_rows   = [{**r, "id": f"o{i}", "guild_operation_id": "op1"}    for i, r in enumerate(shared_rows)]

        comp_ps, comp_cs    = derive_tactical_summaries(build_parties(comp_rows), {}, track_assignments=False)
        planner_ps, plan_cs = derive_tactical_summaries(build_parties(op_rows),   {}, track_assignments=False)

        # Tally must be identical.
        assert comp_ps[1]["tally"]  == planner_ps[1]["tally"]
        assert comp_ps[1]["built"]  == planner_ps[1]["built"]
        assert comp_ps[1]["total"]  == planner_ps[1]["total"]
        assert comp_ps[1]["gaps"]   == planner_ps[1]["gaps"]

        assert comp_cs["tally"]      == plan_cs["tally"]
        assert comp_cs["built"]      == plan_cs["built"]
        assert comp_cs["total"]      == plan_cs["total"]
        assert comp_cs["hint_state"] == plan_cs["hint_state"]


# ---------------------------------------------------------------------------
# derive_composition_integrity — Phase 3 composition integrity helper
# ---------------------------------------------------------------------------

def _make_parties_and_summaries(rows):
    """Helper: run build_parties + derive_tactical_summaries(track_assignments=False)."""
    parties = build_parties(rows)
    ps, cs  = derive_tactical_summaries(parties, {}, track_assignments=False)
    return parties, cs, ps


def _codes(warnings):
    return [w["code"] for w in warnings]


def _severities(warnings):
    return [w["severity"] for w in warnings]


class TestDeriveCompositionIntegrity:
    """Unit tests for derive_composition_integrity().

    Phase 3 source-of-truth note: role_counts and build_slot_counts_json
    do not exist in IronkeepV2.  The composition_slot_templates table is
    the single source of truth.  These tests verify integrity checks based
    solely on actual slot template data.
    """

    # ------------------------------------------------------------------
    # Clean compositions — no warnings expected
    # ------------------------------------------------------------------

    def test_clean_5man_party_no_warnings(self):
        """A well-formed single party with T/H/D/S/D produces no integrity warnings."""
        rows = [
            _raw_slot(1, 1, "Tank",    build_name="Sword"),
            _raw_slot(1, 2, "Healer",  build_name="Holy"),
            _raw_slot(1, 3, "DPS",     build_name="Bow"),
            _raw_slot(1, 4, "Support", build_name="Locus"),
            _raw_slot(1, 5, "DPS",     build_name="Daggers"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert warnings == []

    def test_clean_multi_party_no_warnings(self):
        """A 4-party comp with balanced structure produces no integrity warnings."""
        roles = ["Tank", "Healer", "DPS", "Support", "DPS"]
        rows = [
            _raw_slot(p, s, roles[s - 1], build_name=f"b{p}{s}")
            for p in range(1, 5)
            for s in range(1, 6)
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert warnings == []

    def test_matching_role_counts_and_slots_no_warning(self):
        """When slot templates fully cover T/H/D/S/D for every party, no warnings."""
        rows = [
            _raw_slot(1, 1, "Tank",    build_name="S"),
            _raw_slot(1, 2, "Healer",  build_name="H"),
            _raw_slot(2, 1, "Tank",    build_name="S2"),
            _raw_slot(2, 2, "Healer",  build_name="H2"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert warnings == []

    # ------------------------------------------------------------------
    # Empty composition
    # ------------------------------------------------------------------

    def test_empty_composition_returns_critical_warning(self):
        parties, cs, ps = _make_parties_and_summaries([])
        warnings = derive_composition_integrity(parties, cs, ps)
        assert len(warnings) == 1
        assert warnings[0]["code"]     == "empty_template"
        assert warnings[0]["severity"] == "critical"

    def test_empty_composition_returns_only_one_warning(self):
        """No further checks run for an empty composition."""
        parties, cs, ps = _make_parties_and_summaries([])
        assert len(derive_composition_integrity(parties, cs, ps)) == 1

    # ------------------------------------------------------------------
    # Healer gaps
    # ------------------------------------------------------------------

    def test_all_parties_missing_healer_critical(self):
        """When NO party has a healer slot, severity must be critical."""
        rows = [
            _raw_slot(1, 1, "Tank", build_name="Sword"),
            _raw_slot(1, 2, "DPS",  build_name="Bow"),
            _raw_slot(2, 1, "Tank", build_name="Axe"),
            _raw_slot(2, 2, "DPS",  build_name="Daggers"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        healer_w = [w for w in warnings if w["code"] == "parties_missing_healer"]
        assert len(healer_w) == 1
        assert healer_w[0]["severity"] == "critical"

    def test_some_parties_missing_healer_warn(self):
        """When SOME (but not all) parties lack a healer slot, severity is warn."""
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="Sword"),
            _raw_slot(1, 2, "Healer", build_name="Holy"),   # party 1 has healer
            _raw_slot(2, 1, "Tank",   build_name="Axe"),
            _raw_slot(2, 2, "DPS",    build_name="Bow"),    # party 2 missing healer
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        healer_w = [w for w in warnings if w["code"] == "parties_missing_healer"]
        assert len(healer_w) == 1
        assert healer_w[0]["severity"] == "warn"
        assert "1 of 2" in healer_w[0]["message"]

    def test_single_party_missing_healer_critical(self):
        """A single party with no healer gets critical (all parties = 1)."""
        rows = [
            _raw_slot(1, 1, "Tank", build_name="Sword"),
            _raw_slot(1, 2, "DPS",  build_name="Bow"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        healer_w = [w for w in warnings if w["code"] == "parties_missing_healer"]
        assert healer_w[0]["severity"] == "critical"

    def test_no_healer_warning_absent_when_healer_present(self):
        """When every party has a healer, no healer warning is produced."""
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="S"),
            _raw_slot(1, 2, "Healer", build_name="H"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert "parties_missing_healer" not in _codes(warnings)

    # ------------------------------------------------------------------
    # Tank gaps
    # ------------------------------------------------------------------

    def test_all_parties_missing_tank_critical(self):
        """When NO party has a tank slot, severity must be critical."""
        rows = [
            _raw_slot(1, 1, "Healer", build_name="Holy"),
            _raw_slot(1, 2, "DPS",    build_name="Bow"),
            _raw_slot(2, 1, "Healer", build_name="Holy2"),
            _raw_slot(2, 2, "DPS",    build_name="Daggers"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        tank_w = [w for w in warnings if w["code"] == "parties_missing_tank"]
        assert len(tank_w) == 1
        assert tank_w[0]["severity"] == "critical"

    def test_some_parties_missing_tank_warn(self):
        """When only some parties lack a tank, severity is warn."""
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="S"),
            _raw_slot(1, 2, "Healer", build_name="H"),   # party 1 ok
            _raw_slot(2, 1, "Healer", build_name="H2"),   # party 2 missing tank
            _raw_slot(2, 2, "DPS",    build_name="B"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        tank_w = [w for w in warnings if w["code"] == "parties_missing_tank"]
        assert len(tank_w) == 1
        assert tank_w[0]["severity"] == "warn"

    def test_expected_tank_count_exceeds_actual_tank_slots(self):
        """Alias: a composition expecting 2 tanks per party but defining 0 warns."""
        rows = [
            _raw_slot(1, 1, "DPS",    build_name="Bow"),
            _raw_slot(1, 2, "Healer", build_name="Holy"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert "parties_missing_tank" in _codes(warnings)

    def test_no_tank_warning_absent_when_tank_present(self):
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="Sword"),
            _raw_slot(1, 2, "Healer", build_name="Holy"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert "parties_missing_tank" not in _codes(warnings)

    # ------------------------------------------------------------------
    # Uneven party sizes
    # ------------------------------------------------------------------

    def test_equal_party_sizes_no_uneven_warning(self):
        rows = [
            _raw_slot(1, 1, "Tank"),   _raw_slot(1, 2, "Healer"),
            _raw_slot(2, 1, "Tank"),   _raw_slot(2, 2, "Healer"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert "uneven_party_sizes" not in _codes(warnings)

    def test_party_size_diff_of_one_no_warning(self):
        """A difference of exactly 1 slot between parties is within tolerance."""
        rows = [
            _raw_slot(1, 1, "Tank"),   _raw_slot(1, 2, "Healer"), _raw_slot(1, 3, "DPS"),
            _raw_slot(2, 1, "Tank"),   _raw_slot(2, 2, "Healer"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert "uneven_party_sizes" not in _codes(warnings)

    def test_party_size_diff_of_two_produces_info_warning(self):
        """A gap of > 1 slot between parties produces an info-severity warning."""
        rows = [
            _raw_slot(1, 1, "Tank"),   _raw_slot(1, 2, "Healer"), _raw_slot(1, 3, "DPS"),
            _raw_slot(2, 1, "Tank"),   # party 2 has only 1 slot
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        uneven = [w for w in warnings if w["code"] == "uneven_party_sizes"]
        assert len(uneven) == 1
        assert uneven[0]["severity"] == "info"

    def test_single_party_no_uneven_warning(self):
        """Uneven size check requires >1 party — single party always passes."""
        rows = [_raw_slot(1, 1, "Tank"), _raw_slot(1, 2, "Healer"), _raw_slot(1, 3, "DPS")]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert "uneven_party_sizes" not in _codes(warnings)

    # ------------------------------------------------------------------
    # Multiple warnings in combination
    # ------------------------------------------------------------------

    def test_multiple_warnings_can_coexist(self):
        """A DPS-only 2-party comp with uneven sizes produces multiple warnings."""
        rows = [
            _raw_slot(1, 1, "DPS", build_name="Bow"),
            _raw_slot(1, 2, "DPS", build_name="Daggers"),
            _raw_slot(1, 3, "DPS", build_name="Axe"),
            _raw_slot(2, 1, "DPS", build_name="Bow2"),   # party 2 has 1 slot
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        codes = _codes(warnings)
        assert "parties_missing_healer" in codes
        assert "parties_missing_tank"   in codes
        assert "uneven_party_sizes"     in codes

    def test_warning_list_is_stable_for_same_input(self):
        """Repeated calls with identical input produce identical warning lists."""
        rows = [_raw_slot(1, 1, "DPS", build_name="Bow")]
        parties, cs, ps = _make_parties_and_summaries(rows)
        w1 = derive_composition_integrity(parties, cs, ps)
        w2 = derive_composition_integrity(parties, cs, ps)
        assert w1 == w2

    # ------------------------------------------------------------------
    # Phase 4 — hint field and actionable copy (warning hierarchy)
    # ------------------------------------------------------------------

    def test_every_warning_has_hint_key(self):
        """Every warning dict must expose a 'hint' key (may be None)."""
        rows = [
            _raw_slot(1, 1, "DPS", build_name="Bow"),
            _raw_slot(2, 1, "DPS", build_name="Axe"),
            _raw_slot(2, 2, "DPS", build_name="Daggers"),
            _raw_slot(2, 3, "DPS", build_name="Staff"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        assert len(warnings) > 0, "expected warnings for this DPS-only uneven comp"
        for w in warnings:
            assert "hint" in w, f"Warning {w['code']} missing 'hint' key"

    def test_empty_template_has_hint(self):
        """Empty-template warning includes a non-None, non-empty hint."""
        parties, cs, ps = _make_parties_and_summaries([])
        warnings = derive_composition_integrity(parties, cs, ps)
        assert warnings[0]["code"] == "empty_template"
        assert warnings[0]["hint"], "expected a non-empty hint for empty_template"

    def test_all_healer_missing_hint_references_parties(self):
        """Critical healer warning hint must reference parties (all highlighted)."""
        rows = [
            _raw_slot(1, 1, "Tank", build_name="S"),
            _raw_slot(2, 1, "Tank", build_name="S2"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        healer_w = [w for w in warnings if w["code"] == "parties_missing_healer"]
        assert healer_w, "expected parties_missing_healer warning"
        hint = healer_w[0]["hint"]
        assert hint, "critical healer warning must have a non-empty hint"
        assert "below" in hint.lower(), "hint should reference parties below"

    def test_partial_healer_missing_hint_names_party_numbers(self):
        """Partial healer warning hint must name the specific missing party."""
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="S"),
            _raw_slot(1, 2, "Healer", build_name="H"),   # party 1 ok
            _raw_slot(2, 1, "Tank",   build_name="S2"),  # party 2 missing healer
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        healer_w = [w for w in warnings if w["code"] == "parties_missing_healer"]
        assert healer_w
        hint = healer_w[0]["hint"]
        assert "Party 2" in hint, f"expected 'Party 2' in hint; got: {hint!r}"

    def test_all_tank_missing_hint_references_parties(self):
        """Critical tank warning hint must reference parties (all highlighted)."""
        rows = [
            _raw_slot(1, 1, "Healer", build_name="H"),
            _raw_slot(2, 1, "Healer", build_name="H2"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        tank_w = [w for w in warnings if w["code"] == "parties_missing_tank"]
        assert tank_w
        hint = tank_w[0]["hint"]
        assert hint and "below" in hint.lower()

    def test_partial_tank_missing_hint_names_party_numbers(self):
        """Partial tank warning hint names the affected parties."""
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="S"),
            _raw_slot(1, 2, "Healer", build_name="H"),
            _raw_slot(2, 1, "Healer", build_name="H2"),
            _raw_slot(2, 2, "DPS",    build_name="B"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        tank_w = [w for w in warnings if w["code"] == "parties_missing_tank"]
        assert tank_w
        hint = tank_w[0]["hint"]
        assert "Party 2" in hint

    def test_uneven_party_sizes_hint_names_undersized_party(self):
        """Uneven-size hint must name the specific undersized party and its count."""
        rows = [
            _raw_slot(1, 1, "Tank"),   _raw_slot(1, 2, "Healer"),
            _raw_slot(1, 3, "DPS"),    _raw_slot(1, 4, "Support"),
            _raw_slot(1, 5, "DPS"),    # party 1 — 5 slots
            _raw_slot(2, 1, "Tank"),   _raw_slot(2, 2, "Healer"),
            _raw_slot(2, 3, "DPS"),    _raw_slot(2, 4, "Support"),
            _raw_slot(2, 5, "DPS"),    # party 2 — 5 slots
            _raw_slot(3, 1, "Tank"),   # party 3 — only 1 slot (undersized)
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        uneven = [w for w in warnings if w["code"] == "uneven_party_sizes"]
        assert uneven
        hint = uneven[0]["hint"]
        assert "Party 3" in hint, f"hint should name Party 3; got: {hint!r}"
        assert "1" in hint, f"hint should mention the small size; got: {hint!r}"

    def test_uneven_party_sizes_message_is_concise(self):
        """Uneven-size warning message is a short summary; detail lives in hint."""
        rows = [
            _raw_slot(1, 1, "Tank"),  _raw_slot(1, 2, "Healer"), _raw_slot(1, 3, "DPS"),
            _raw_slot(2, 1, "Tank"),  # party 2 undersized
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        uneven = [w for w in warnings if w["code"] == "uneven_party_sizes"]
        assert uneven
        # Message should be a high-level summary, not the per-party breakdown
        msg = uneven[0]["message"]
        assert len(msg) <= 60, f"message should be concise; got: {msg!r}"

    def test_partial_healer_message_is_concise(self):
        """Partial healer warning message must not embed party-level detail."""
        rows = [
            _raw_slot(1, 1, "Tank",   build_name="S"),
            _raw_slot(1, 2, "Healer", build_name="H"),
            _raw_slot(2, 1, "Tank",   build_name="S2"),
        ]
        parties, cs, ps = _make_parties_and_summaries(rows)
        warnings = derive_composition_integrity(parties, cs, ps)
        healer_w = [w for w in warnings if w["code"] == "parties_missing_healer"]
        assert healer_w
        msg = healer_w[0]["message"]
        # Message should not mention specific party numbers — those belong in hint
        assert "Party 2" not in msg, f"party detail belongs in hint, not message; got: {msg!r}"
