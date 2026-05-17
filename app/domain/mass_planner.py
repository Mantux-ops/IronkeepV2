"""
Mass Planner domain rules.

Governs slot generation and assignment invariants.  No DB access.

Key invariants enforced here:
- Slots can only be generated once per operation (idempotency guard).
- A slot is assignable only when it has no active assignment (determined by
  the presence of an assignments row with status='assigned').
- Assignment resolves role and build from the operation slot, not from the
  signup intent, preserving the frozen-snapshot contract.

Quick-assign ranking (lower = better):
  Tier 1 — specific willingness + role match + build match (exact)
  Tier 2 — role match (any willingness, not covered by tier 1)
  Tier 3 — fill willingness, no role match (fill anything)
  Tier 4 — no match and not fill

Within each tier: availability='confirmed' before 'tentative', then
display_name alphabetically for determinism.

Reserved participants are excluded from the quick-assign candidate pool.
The caller remains authoritative; quick-assign is speed-assist only.
"""

from __future__ import annotations

from app.errors import ConflictError, ValidationError


def validate_slots_not_yet_generated(existing_slot_count: int) -> None:
    """Raise if slots have already been generated for this operation."""
    if existing_slot_count > 0:
        raise ConflictError(
            "Operation slots have already been generated for this operation. "
            "Regeneration is not supported in the first slice."
        )


def validate_slot_is_open(active_assignment: dict | None) -> None:
    """Raise if the slot already carries an active assignment."""
    if active_assignment is not None:
        raise ConflictError(
            "This operation slot already has an active assignment. "
            "Remove the existing assignment before reassigning."
        )


def validate_plan_has_templates(template_count: int) -> None:
    """Raise if the attached composition has no slot templates to copy."""
    if template_count == 0:
        raise ValidationError(
            "Cannot generate operation slots: the attached composition has no slot templates."
        )


def sort_participants_for_slot(
    slot: dict,
    candidates: list[dict],
    signup_prefs: dict[str, dict],
) -> list[dict]:
    """
    Sort candidate participants for a specific slot, preferring role/build matches.

    This is advisory sorting — the caller may assign ANY candidate regardless of
    their signup preferences.  A 'Tank' signer CAN be assigned to a 'Healer' slot;
    the planner board must not block this (caller override is first-class).

    Each returned dict has an added 'match_label' field:
      '★'  — role AND build both match the slot
      '≈'  — role matches only
      ''   — no match (still shown and assignable)

    Args:
        slot:         An operation_slots row dict.
        candidates:   Participants who are unassigned and have signed up.
        signup_prefs: {participant_id: signup_intents row} for preference lookup.
    """
    def _score(p: dict) -> int:
        prefs = signup_prefs.get(p["id"], {})
        role_match  = (prefs.get("preferred_role")       or "").strip().lower() == slot["role"].lower()
        build_match = (prefs.get("preferred_build_name") or "").strip().lower() == slot["build_name"].lower()
        if role_match and build_match:
            return 0
        if role_match:
            return 1
        return 2

    def _label(p: dict) -> str:
        prefs = signup_prefs.get(p["id"], {})
        role_match  = (prefs.get("preferred_role")       or "").strip().lower() == slot["role"].lower()
        build_match = (prefs.get("preferred_build_name") or "").strip().lower() == slot["build_name"].lower()
        if role_match and build_match:
            return "★"
        if role_match:
            return "≈"
        return ""

    enriched = [{**p, "match_label": _label(p)} for p in candidates]
    return sorted(enriched, key=lambda p: _score(p))


def select_best_candidate(
    slot: dict,
    candidates: list[dict],
    signup_prefs: dict[str, dict],
    reserve_ids: set[str] | None = None,
) -> dict | None:
    """
    Return the highest-ranked eligible participant for a slot, or None.

    Uses a 4-tier ranking (see module docstring).  Reserved participants
    (participant_id in reserve_ids) are excluded entirely — quick-assign
    must never silently override a caller's bench decision.

    Tie-breaking within a tier:
      1. availability='confirmed' before 'tentative' (or absent).
      2. display_name alphabetically (deterministic).

    Args:
        slot:         An operation_slots row dict.
        candidates:   Unassigned, signed-up participants (no active assignment).
        signup_prefs: {participant_id: signup_intents row}.
        reserve_ids:  Set of participant_ids currently on reserve (excluded).

    Returns:
        The best candidate dict (enriched with 'match_label'), or None if the
        pool is empty after filtering.
    """
    excluded = reserve_ids or set()

    def _tier(p: dict) -> int:
        if p["id"] in excluded:
            return 99  # filtered out below, but defend with a high score
        prefs = signup_prefs.get(p["id"], {})
        role_match  = (prefs.get("preferred_role")       or "").strip().lower() == slot["role"].lower()
        build_match = (prefs.get("preferred_build_name") or "").strip().lower() == slot["build_name"].lower()
        willingness = (prefs.get("willingness") or "").strip().lower()

        if role_match and build_match and willingness == "specific":
            return 0  # Tier 1: specific exact match
        if role_match:
            return 1  # Tier 2: role match (any willingness)
        if willingness == "fill":
            return 2  # Tier 3: fill willingness, no role match
        return 3       # Tier 4: no match, not fill

    def _availability_key(p: dict) -> int:
        prefs = signup_prefs.get(p["id"], {})
        return 0 if (prefs.get("availability") or "") == "confirmed" else 1

    eligible = [p for p in candidates if p["id"] not in excluded]
    if not eligible:
        return None

    ranked = sorted(
        eligible,
        key=lambda p: (_tier(p), _availability_key(p), p["display_name"]),
    )
    best = ranked[0]
    # Tier 4 participants with no prefs are still valid (caller chose quick-assign).
    return best
