"""
Unit tests for sort_participants_for_slot() in app/domain/mass_planner.py.

These tests require no database.  They verify that:
- Exact role+build matches are sorted first (★)
- Role-only matches come second (≈)
- Non-matching participants come last (no label)
- ALL candidates appear in the result regardless of match quality
- A participant with no match is still assignable (caller override)
"""

import pytest

from app.domain.mass_planner import sort_participants_for_slot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slot(role: str, build: str) -> dict:
    return {"id": "slot-1", "role": role, "build_name": build}


def _participant(pid: str, name: str) -> dict:
    return {"id": pid, "display_name": name}


def _prefs(participant_id: str, role: str, build: str | None = None) -> tuple[str, dict]:
    return participant_id, {
        "participant_id": participant_id,
        "preferred_role": role,
        "preferred_build_name": build,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exact_match_floated_to_top():
    slot    = _slot("Healer", "Hallowfall")
    exact   = _participant("p1", "ExactMatch")
    role_m  = _participant("p2", "RoleOnly")
    no_m    = _participant("p3", "NoMatch")

    signup_prefs = dict([
        _prefs("p1", "Healer", "Hallowfall"),   # exact match
        _prefs("p2", "Healer", None),            # role only
        _prefs("p3", "Tank",   "1H Mace"),       # no match
    ])
    candidates = [no_m, role_m, exact]          # deliberately wrong order

    result = sort_participants_for_slot(slot, candidates, signup_prefs)

    assert result[0]["id"] == "p1"
    assert result[1]["id"] == "p2"
    assert result[2]["id"] == "p3"


def test_match_labels_are_set_correctly():
    slot = _slot("Healer", "Hallowfall")
    signup_prefs = dict([
        _prefs("p1", "Healer", "Hallowfall"),
        _prefs("p2", "Healer", None),
        _prefs("p3", "Tank",   "1H Mace"),
    ])
    candidates = [
        _participant("p1", "ExactMatch"),
        _participant("p2", "RoleOnly"),
        _participant("p3", "NoMatch"),
    ]

    result = sort_participants_for_slot(slot, candidates, signup_prefs)
    by_id = {p["id"]: p for p in result}

    assert by_id["p1"]["match_label"] == "★"
    assert by_id["p2"]["match_label"] == "≈"
    assert by_id["p3"]["match_label"] == ""


def test_non_matching_participant_still_present():
    """
    Caller override invariant: a participant with NO matching role/build must
    still appear in the sorted result.  The planner board must not filter them out.
    """
    slot = _slot("Healer", "Hallowfall")
    signup_prefs = dict([_prefs("p1", "Tank", "1H Mace")])
    candidates   = [_participant("p1", "TankPlayer")]

    result = sort_participants_for_slot(slot, candidates, signup_prefs)

    assert len(result) == 1
    assert result[0]["id"] == "p1"
    assert result[0]["match_label"] == ""


def test_empty_candidates_returns_empty_list():
    slot = _slot("Healer", "Hallowfall")
    result = sort_participants_for_slot(slot, [], {})
    assert result == []


def test_case_insensitive_role_match():
    slot = _slot("Healer", "Hallowfall")
    signup_prefs = dict([_prefs("p1", "healer", "hallowfall")])
    candidates   = [_participant("p1", "CaseSensitiveCheck")]

    result = sort_participants_for_slot(slot, candidates, signup_prefs)
    assert result[0]["match_label"] == "★"


def test_role_match_without_build_preference():
    """
    A participant with matching role but no build preference gets ≈, not ★.
    """
    slot = _slot("Healer", "Hallowfall")
    signup_prefs = dict([_prefs("p1", "Healer")])   # no build preference
    candidates   = [_participant("p1", "NoBuildPref")]

    result = sort_participants_for_slot(slot, candidates, signup_prefs)
    assert result[0]["match_label"] == "≈"


def test_no_signup_prefs_entry_treated_as_no_match():
    """
    A participant with no entry in signup_prefs dict should appear at the bottom.
    """
    slot = _slot("Healer", "Hallowfall")
    candidates = [_participant("p1", "NoPrefs")]

    result = sort_participants_for_slot(slot, candidates, signup_prefs={})
    assert len(result) == 1
    assert result[0]["match_label"] == ""


def test_multiple_exact_matches_all_present_and_first():
    slot = _slot("DPS", "Bow")
    signup_prefs = dict([
        _prefs("p1", "DPS",    "Bow"),
        _prefs("p2", "DPS",    "Bow"),
        _prefs("p3", "DPS",    None),
        _prefs("p4", "Healer", "Hallowfall"),
    ])
    candidates = [_participant(f"p{i}", f"P{i}") for i in range(1, 5)]

    result = sort_participants_for_slot(slot, candidates, signup_prefs)
    labels = [r["match_label"] for r in result]

    # p1 and p2 both ★, p3 is ≈, p4 is ""
    assert labels.count("★") == 2
    assert labels.count("≈") == 1
    assert labels.count("") == 1
    # All four must be present
    assert len(result) == 4
